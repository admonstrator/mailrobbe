"""DKIM verification of one mail (SPEC 3.4, decisions D10 and D12).

verify_mail is pure: the raw message and a KeySource in, a MailVerdict out. It does no I/O of its
own (keys come only from the KeySource) and never raises, whatever the bytes are.

It runs the checks of dkimpy's DKIM.verify_sig_process itself, on dkimpy's primitives: the header
parser (rfc822_parse), the tag parser, header selection and canonicalisation and the RSA key
parser; the body canonicalisation (canonical.py) is byte-identical to dkimpy's. dkim.verify could
not report what is stored per signature: it returns the same False for a missing key and a bad
signature, drops the body hash result when the key is missing, judges t= and x= by the wall
clock (archived mail would fail for its age) and parses and canonicalises the whole message,
which is slow on large attachments. Here only the header section is parsed, the body is
canonicalised straight from the raw bytes once per mail and body canonicalisation, and a mail
without a signature costs one scan of its header section.

Every signature gets the outcome of the first check it does not pass:

1. header section unparsable: fail, message_malformed (every signature of the mail)
2. tag list unparsable, a mandatory tag missing, an invalid value: fail, signature_malformed;
   a= other than rsa-sha256, rsa-sha1, ed25519-sha256: fail, unsupported_algorithm
3. From not in h=: fail, from_not_signed (RFC 6376 5.4)
4. the key, from one KeySource call: temp_error with the answer's reason; no_key, key_not_found;
   no_key, key_revoked (empty p=); fail, key_malformed (no usable key for this signature);
   fail, key_too_short (RSA below 1024 bits, RFC 8301)
5. fail, body_hash_mismatch
6. fail, signature_mismatch
7. pass

t= and x= are recorded but never judged (D10). The body hash is compared before the key lookup,
so body_hash_ok is known for no_key and temp_error results as well. Every result from step 4 on
that rests on the key found in DNS has key_origin dns.

Keys of deleted selectors (D100): when step 4 or 6 ends the check (today's DNS gives no key, a
revoked or unusable one, a temp_error, or a key that does not verify), the candidate keys of the
name are tried, strongest origin first. A candidate counts only when it suits the signature
(key type, h=, s=, at least 1024 bits for RSA) and verifies its header hash; the first that does
decides: pass for an intact body (consistent for a reconstructed key), fail body_hash_mismatch
for a changed one, with the candidate's key_id, key_origin and key_bits. When none does, the
result of DNS stays, except that no_key becomes no_key key_mismatch. Without candidates the
results are those of DNS alone. Every key DNS gave once is a candidate of origin dns (D106), so
a signature its key verified still passes after the domain dropped or replaced it; when DNS
gives no key (not found, revoked, temp_error) and no candidate verifies, the newest key kept
from DNS decides steps 4 to 7 as DNS did, so a failure stays the failure it was.

signature_material gives what reconstructing and testing keys need from each signature: the
header hash b= signs, b= itself and its hash algorithm (dkim/keys).
"""

import base64
import binascii
import contextlib
import functools
import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from email.utils import getaddresses
from typing import Any

import dkim
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from dkim.canonicalization import (
    CanonicalizationPolicy,
    InvalidCanonicalizationPolicyError,
    Relaxed,
)
from dkim.crypto import parse_public_key
from dkim.util import InvalidTagValueList, parse_tag_value

from mailrobbe.dkim.canonical import canonical_blocks
from mailrobbe.dkim.model import (
    NO_CANDIDATES,
    DnsAnswer,
    KeyCandidates,
    KeySource,
    MailVerdict,
    SignatureMaterial,
    SignatureResult,
)
from mailrobbe.dkim.override import key_name
from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus, KeyOrigin, origin_status

logger = logging.getLogger(__name__)

MIN_RSA_BITS = 1024

# a= -> key type (k= of the key record) and hash algorithm
_ALGORITHMS = {
    b"rsa-sha256": (b"rsa", "sha256"),
    b"rsa-sha1": (b"rsa", "sha1"),
    b"ed25519-sha256": (b"ed25519", "sha256"),
}
_PREHASHED = {"sha256": Prehashed(hashes.SHA256()), "sha1": Prehashed(hashes.SHA1())}
_MANDATORY_TAGS = (b"v", b"a", b"b", b"bh", b"d", b"h", b"s")
_HEADER_END = re.compile(rb"\n\r?\n")  # the line break before the first empty line
_SIGNATURE_FIELD = re.compile(rb"^dkim-signature[ \t]*:(.*(?:\r?\n[ \t].*)*)", re.I | re.M)
_HEADER_LIST = re.compile(rb"\s*:\s*")  # h=, split as dkimpy splits it
_DECIMAL = re.compile(rb"\d+")
_LENGTH = re.compile(rb"\d{1,76}")  # l=, at most as long as RFC 6376 allows
_WHITESPACE = re.compile(rb"\s+")
# d= and s=: dkimpy's specials for d=, whitespace and control characters (a NUL could not even
# be stored as a dns_cache name)
_NOT_IN_NAME = re.compile(r"[\x00-\x1f\x7f\s()<>\[\]:;@\\,\"]")


def verify_mail(
    raw: bytes, keys: KeySource, candidates: KeyCandidates = NO_CANDIDATES
) -> MailVerdict:
    """Verify every DKIM-Signature header field of raw (LF or CRLF line endings).

    candidates: keys from other sources than today's DNS by key name (D100), tried when DNS
    gives no key that verifies.
    """
    header_end, body_start = _split(raw)
    head = raw[:header_end]
    if b"dkim-signature" not in head.lower():
        return MailVerdict()
    try:
        headers, _ = dkim.rfc822_parse(head)
    except Exception:  # MessageFormatError, or IndexError for a continuation line first
        return MailVerdict(tuple(map(_malformed_message, _SIGNATURE_FIELD.findall(head))))
    mail = _Mail(raw, body_start, headers)
    return MailVerdict(
        tuple(
            mail.check(name, value, keys, candidates)
            for name, value in headers
            if name.lower() == b"dkim-signature"
        )
    )


def signature_material(raw: bytes) -> list[SignatureMaterial]:
    """What each verifiable DKIM-Signature of raw signs; never raises.

    Signatures that fail before their key is asked for (malformed, unsupported algorithm, From
    not signed) have none; the others keep their signature_index.
    """
    header_end, body_start = _split(raw)
    head = raw[:header_end]
    if b"dkim-signature" not in head.lower():
        return []
    try:
        headers, _ = dkim.rfc822_parse(head)
    except Exception:
        return []
    mail = _Mail(raw, body_start, headers)
    fields = [(name, value) for name, value in headers if name.lower() == b"dkim-signature"]
    found = (mail.material(index, name, value) for index, (name, value) in enumerate(fields))
    return [material for material in found if material is not None]


def key_verifies(record: str, material: SignatureMaterial) -> bool:
    """Whether the key of a record may verify this signature and verifies its header hash: the
    rule every candidate key follows (D100), for keys found outside the check."""
    key = parse_key_record(record)
    return (
        not isinstance(key, DkimReason)
        and key.fits(material.key_type.encode(), material.hash_name)
        and key.verifies(material.header_hash, material.signature, material.hash_name)
    )


def _split(raw: bytes) -> tuple[int, int]:
    """End of the header section (after its last line break) and start of the body.

    The same division as rfc822_parse makes: at the first empty line, with LF or CRLF.
    """
    if raw.startswith(b"\n"):
        return 0, 1
    if raw.startswith(b"\r\n"):
        return 0, 2
    match = _HEADER_END.search(raw)
    if match is None:
        return len(raw), len(raw)
    return match.start() + 1, match.end()


@dataclass(slots=True)
class _Details:
    """What is known about one signature so far; becomes its SignatureResult."""

    domain: str | None = None
    selector: str | None = None
    algorithm: str | None = None
    key_bits: int | None = None
    signed_headers: tuple[str, ...] | None = None
    body_hash_ok: bool | None = None
    signed_at: datetime | None = None
    aligned: bool | None = None
    dns_cached: bool = False
    key_id: int | None = None
    key_origin: KeyOrigin | None = None

    def describe(self, tags: dict[bytes, bytes], author: str | None) -> None:
        """Fill in what the tags say, whether or not they are valid."""
        if b"d" in tags:
            self.domain = _text(tags[b"d"])
        if b"s" in tags:
            self.selector = _text(tags[b"s"])
        if b"a" in tags:
            self.algorithm = _text(tags[b"a"])
        if b"h" in tags:
            names = map(_text, _HEADER_LIST.split(tags[b"h"]))
            self.signed_headers = tuple(name for name in names if name)
        if b"t" in tags:
            self.signed_at = _timestamp(tags[b"t"])
        if author and self.domain:
            self.aligned = _aligned(author, self.domain)

    def result(self, status: DkimStatus, reason: DkimReason | None) -> SignatureResult:
        return SignatureResult(
            status=status,
            reason=reason,
            domain=self.domain,
            selector=self.selector,
            algorithm=self.algorithm,
            key_bits=self.key_bits,
            signed_headers=self.signed_headers,
            body_hash_ok=self.body_hash_ok,
            signed_at=self.signed_at,
            aligned=self.aligned,
            dns_cached=self.dns_cached,
            key_id=self.key_id,
            key_origin=self.key_origin,
        )


@dataclass(frozen=True, slots=True)
class _Signature:
    """The validated tags of one DKIM-Signature header field."""

    domain: str
    selector: str
    key_type: bytes  # the k= a key must have
    hash_name: str
    policy: Any  # dkim.canonicalization.CanonicalizationPolicy
    headers: list[bytes]  # h=, lowercase, as dkimpy hashes them
    length: int | None  # l=
    body_hash: bytes
    signature: bytes


@dataclass(frozen=True, slots=True)
class PublicKey:
    """A key record that holds a key, parsed once per process and record (parse_key_record)."""

    key_type: bytes  # k=
    hashes: frozenset[bytes] | None  # h=: hash algorithms the key may be used with; None: any
    for_email: bool  # s= is absent or includes "*" or "email"
    bits: int
    public: rsa.RSAPublicKey | Ed25519PublicKey
    modulus: int = 0  # RSA only

    def suits(self, key_type: bytes, hash_name: str) -> bool:
        """The key's k=, h= and s= allow a signature of this key type and hash algorithm."""
        return (
            self.key_type == key_type
            and self.for_email
            and (self.hashes is None or hash_name.encode() in self.hashes)
        )

    def fits(self, key_type: bytes, hash_name: str) -> bool:
        """suits, and large enough to count (RFC 8301): what a candidate key must be (D100)."""
        return self.suits(key_type, hash_name) and (key_type != b"rsa" or self.bits >= MIN_RSA_BITS)

    def verifies(self, digest: bytes, signature: bytes, hash_name: str) -> bool:
        """b= is the key's signature of the header hash."""
        try:
            if isinstance(self.public, Ed25519PublicKey):
                self.public.verify(signature, digest)
            else:
                # dkimpy's RSASSA_PKCS1_v1_5_verify takes b= as a number, so a value with its
                # leading zero bytes dropped (or one above the modulus) verifies there too;
                # OpenSSL wants exactly the modulus length.
                value = int.from_bytes(signature) % self.modulus
                self.public.verify(
                    value.to_bytes((self.bits + 7) // 8),
                    digest,
                    padding.PKCS1v15(),
                    _PREHASHED[hash_name],
                )
        except InvalidSignature:
            return False
        return True


@dataclass(slots=True)
class _Mail:
    """One message as its signatures see it, with the work they share."""

    raw: bytes
    body_start: int
    headers: list[list[bytes]]  # rfc822_parse's [name, value] pairs
    author: str | None = field(init=False)  # domain of the From address, for alignment
    _body_hashes: dict[tuple[bool, int | None, str], bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.author = _author_domain(self.headers)

    def check(
        self, name: bytes, value: bytes, keys: KeySource, candidates: KeyCandidates
    ) -> SignatureResult:
        """The result for one DKIM-Signature header field; never raises."""
        details = _Details()
        try:
            status, reason = self._check(name, value, keys, candidates, details)
        except Exception:
            logger.warning(
                "unexpected error checking the DKIM signature d=%s s=%s",
                details.domain,
                details.selector,
                exc_info=True,
            )
            status, reason = DkimStatus.FAIL, DkimReason.SIGNATURE_MALFORMED
            details.key_id = details.key_origin = None
        return details.result(status, reason)

    def _check(
        self,
        name: bytes,
        value: bytes,
        keys: KeySource,
        candidates: KeyCandidates,
        details: _Details,
    ) -> tuple[DkimStatus, DkimReason | None]:
        try:
            tags = parse_tag_value(value)
        except InvalidTagValueList:
            return DkimStatus.FAIL, DkimReason.SIGNATURE_MALFORMED
        details.describe(tags, self.author)
        signature = _parse_signature(tags)
        if isinstance(signature, DkimReason):
            return DkimStatus.FAIL, signature
        details.body_hash_ok = self._body_hash(signature) == signature.body_hash
        if b"from" not in signature.headers:
            return DkimStatus.FAIL, DkimReason.FROM_NOT_SIGNED

        digest = functools.cache(lambda: self._header_hash(name, value, signature))
        dns_name = key_name(signature.selector, signature.domain)
        answer = keys(dns_name)
        details.dns_cached = answer.from_cache
        status, reason = self._with_dns_key(answer, signature, digest, details)
        if status is DkimStatus.PASS or reason is DkimReason.BODY_HASH_MISMATCH:
            return status, reason
        found = candidates.get(dns_name, ())
        for candidate in found:
            if answer.record is not None and candidate.record == answer.record.strip():
                continue  # today's DNS key, kept (D106): tried already
            key = parse_key_record(candidate.record)
            if (
                isinstance(key, DkimReason)
                or not key.fits(signature.key_type, signature.hash_name)
                or not key.verifies(digest(), signature.signature, signature.hash_name)
            ):
                continue
            details.key_bits = key.bits
            details.key_id, details.key_origin = candidate.key_id, candidate.origin
            if not details.body_hash_ok:
                return DkimStatus.FAIL, DkimReason.BODY_HASH_MISMATCH
            return origin_status(candidate.origin), None
        kept = [candidate for candidate in found if candidate.origin is KeyOrigin.DNS]
        if kept and status in (DkimStatus.NO_KEY, DkimStatus.TEMP_ERROR):
            # DNS gives no key any more: the newest one it gave decides, as it did (D106)
            latest = replace(answer, status=DnsStatus.FOUND, record=kept[-1].record)
            details.key_id = kept[-1].key_id
            return self._with_dns_key(latest, signature, digest, details)
        if found and status is DkimStatus.NO_KEY:
            return DkimStatus.NO_KEY, DkimReason.KEY_MISMATCH
        return status, reason

    def _with_dns_key(
        self,
        answer: DnsAnswer,
        signature: _Signature,
        digest: Callable[[], bytes],
        details: _Details,
    ) -> tuple[DkimStatus, DkimReason | None]:
        """Steps 4 to 7 with today's DNS answer."""
        if answer.status is DnsStatus.TEMP_ERROR:
            return DkimStatus.TEMP_ERROR, answer.reason or DkimReason.DNS_TIMEOUT
        if answer.status is DnsStatus.NOT_FOUND or answer.record is None:
            return DkimStatus.NO_KEY, DkimReason.KEY_NOT_FOUND
        key = parse_key_record(answer.record)
        if key is DkimReason.KEY_REVOKED:
            return DkimStatus.NO_KEY, key
        details.key_origin = KeyOrigin.DNS
        if isinstance(key, DkimReason):
            return DkimStatus.FAIL, key
        details.key_bits = key.bits
        if not key.suits(signature.key_type, signature.hash_name):
            return DkimStatus.FAIL, DkimReason.KEY_MALFORMED
        if key.key_type == b"rsa" and key.bits < MIN_RSA_BITS:
            return DkimStatus.FAIL, DkimReason.KEY_TOO_SHORT

        if not details.body_hash_ok:
            return DkimStatus.FAIL, DkimReason.BODY_HASH_MISMATCH
        if not key.verifies(digest(), signature.signature, signature.hash_name):
            return DkimStatus.FAIL, DkimReason.SIGNATURE_MISMATCH
        return DkimStatus.PASS, None

    def material(self, index: int, name: bytes, value: bytes) -> SignatureMaterial | None:
        """signature_material of one DKIM-Signature header field; never raises."""
        try:
            tags = parse_tag_value(value)
            signature = _parse_signature(tags)
            if isinstance(signature, DkimReason) or b"from" not in signature.headers:
                return None
            return SignatureMaterial(
                index=index,
                name=key_name(signature.selector, signature.domain),
                key_type=signature.key_type.decode(),
                hash_name=signature.hash_name,
                header_hash=self._header_hash(name, value, signature),
                signature=signature.signature,
                body_hash_ok=self._body_hash(signature) == signature.body_hash,
                signed_at=_timestamp(tags[b"t"]) if b"t" in tags else None,
            )
        except Exception:
            logger.warning("unexpected error reading the DKIM signature %d", index, exc_info=True)
            return None

    def _body_hash(self, signature: _Signature) -> bytes:
        """The hash of the canonical body, computed once per canonicalisation, l= and hash."""
        relaxed = signature.policy.body_algorithm is Relaxed
        key = (relaxed, signature.length, signature.hash_name)
        digest = self._body_hashes.get(key)
        if digest is None:
            hasher = hashlib.new(signature.hash_name)
            remaining = signature.length
            for block in canonical_blocks(self.raw, relaxed, self.body_start):
                if remaining is not None:
                    if remaining <= 0:
                        break
                    block = block[:remaining]
                    remaining -= len(block)
                hasher.update(block)
            digest = self._body_hashes[key] = hasher.digest()
        return digest

    def _header_hash(self, name: bytes, value: bytes, signature: _Signature) -> bytes:
        """dkim.hash_headers, canonicalising only the fields it hashes instead of all of them.

        Fields are selected by lowercase name, the same before and after canonicalisation.
        """
        # As dkimpy (Debian bug 644046): every From field is hashed, so a second one added after
        # signing breaks the signature. From is in h= by now.
        selected = dkim.select_headers(self.headers, [*signature.headers, b"from"])
        unsigned = (name, dkim.RE_BTAG.sub(b"\\1", value))  # b= emptied
        fields = signature.policy.canonicalize_headers([*selected, unsigned])
        hasher = hashlib.new(signature.hash_name)
        for field_name, field_value in fields[:-1]:
            hasher.update(field_name + b":" + field_value)
        field_name, field_value = fields[-1]
        hasher.update(field_name + b":" + field_value.rstrip())  # without its line break
        return hasher.digest()


def _parse_signature(tags: dict[bytes, bytes]) -> _Signature | DkimReason:
    """The checks of dkim.validate_signature_fields, except t= and x= against the clock."""
    if any(tag not in tags for tag in _MANDATORY_TAGS) or tags[b"v"] != b"1":
        return DkimReason.SIGNATURE_MALFORMED
    domain, selector = _name(tags[b"d"]), _name(tags[b"s"])
    try:
        policy = CanonicalizationPolicy.from_c_value(tags.get(b"c", b"simple/simple"))
    except InvalidCanonicalizationPolicyError:
        return DkimReason.SIGNATURE_MALFORMED
    length, query = tags.get(b"l"), tags.get(b"q")
    body_hash, signature = _base64(tags[b"bh"]), _base64(tags[b"b"])
    if (
        domain is None
        or selector is None
        or (b"i" in tags and not _within(tags[b"i"], domain))
        or (length is not None and not _LENGTH.fullmatch(length))
        or any(tag in tags and not _DECIMAL.fullmatch(tags[tag]) for tag in (b"t", b"x"))
        or (query is not None and b"dns/txt" not in [m.strip() for m in query.split(b":")])
        or body_hash is None
        or signature is None
    ):
        return DkimReason.SIGNATURE_MALFORMED
    algorithm = _ALGORITHMS.get(tags[b"a"])
    if algorithm is None:
        return DkimReason.UNSUPPORTED_ALGORITHM
    key_type, hash_name = algorithm
    return _Signature(
        domain=domain,
        selector=selector,
        key_type=key_type,
        hash_name=hash_name,
        policy=policy,
        headers=[name.lower() for name in _HEADER_LIST.split(tags[b"h"])],
        length=None if length is None else int(length),
        body_hash=body_hash,
        signature=signature,
    )


@functools.lru_cache(maxsize=4096)
def parse_key_record(record: str) -> PublicKey | DkimReason:
    """The key in a DKIM key record (RFC 6376 3.6.1), or why there is none to use."""
    try:
        tags = parse_tag_value(record.encode("utf-8", "replace"))
    except InvalidTagValueList:
        return DkimReason.KEY_MALFORMED
    if tags.get(b"v", b"DKIM1") != b"DKIM1" or b"p" not in tags:
        return DkimReason.KEY_MALFORMED
    data = _WHITESPACE.sub(b"", tags[b"p"])
    if not data:
        return DkimReason.KEY_REVOKED
    key_type = tags.get(b"k", b"rsa")
    hashes = frozenset(name.strip() for name in tags[b"h"].split(b":")) if b"h" in tags else None
    services = {name.strip() for name in tags.get(b"s", b"*").split(b":")}
    for_email = bool(services & {b"*", b"email"})
    if key_type not in (b"rsa", b"ed25519"):
        return DkimReason.KEY_MALFORMED
    # Garbage in p= makes dkimpy's ASN.1 parser raise more than its UnparsableKeyError, and
    # cryptography raises ValueError for a wrong length or an exponent it cannot verify with
    # (below 3, or even): either way there is no key.
    try:
        der = base64.b64decode(data)
        if key_type == b"ed25519":
            return PublicKey(
                key_type, hashes, for_email, 256, Ed25519PublicKey.from_public_bytes(der)
            )
        numbers = parse_public_key(der)  # SubjectPublicKeyInfo or a bare RSAPublicKey
        modulus = numbers["modulus"]
        public = rsa.RSAPublicNumbers(numbers["publicExponent"], modulus).public_key()
    except Exception:
        return DkimReason.KEY_MALFORMED
    return PublicKey(key_type, hashes, for_email, modulus.bit_length(), public, modulus)


def _malformed_message(value: bytes) -> SignatureResult:
    """A signature in a header section rfc822_parse rejects: fail, with what its tags say."""
    details = _Details()
    with contextlib.suppress(InvalidTagValueList):
        details.describe(parse_tag_value(value), None)
    return details.result(DkimStatus.FAIL, DkimReason.MESSAGE_MALFORMED)


def _author_domain(headers: list[list[bytes]]) -> str | None:
    """Domain of the From address (D12); None unless one From field holds exactly one address."""
    values = [value for name, value in headers if name.lower() == b"from"]
    if len(values) != 1:
        return None
    pairs = getaddresses([values[0].decode("utf-8", "replace")])
    addresses = [address for _, address in pairs if address]
    if len(addresses) != 1 or "@" not in addresses[0]:
        return None
    return addresses[0].rpartition("@")[2].strip().rstrip(".").lower() or None


def _aligned(author: str, domain: str) -> bool:
    """D12: the From domain equals d=, or one is a subdomain of the other."""
    domain = domain.rstrip(".")
    return author == domain or author.endswith("." + domain) or domain.endswith("." + author)


def _name(value: bytes) -> str | None:
    """d= or s= as a lowercase DNS name; None if it cannot be one."""
    try:
        name = value.decode("utf-8").lower().rstrip(".")
    except UnicodeDecodeError:
        return None
    return None if not name or _NOT_IN_NAME.search(name) else name


def _within(identity: bytes, domain: str) -> bool:
    """i= is in the signing domain or a subdomain of it (RFC 6376 3.5)."""
    owner = identity.rpartition(b"@")[2].decode("utf-8", "replace").lower().rstrip(".")
    return owner == domain or owner.endswith("." + domain)


def _base64(value: bytes) -> bytes | None:
    """b= or bh=, whitespace ignored; None if empty or not base64."""
    try:
        decoded = base64.b64decode(_WHITESPACE.sub(b"", value), validate=True)
    except binascii.Error:
        return None
    return decoded or None


def _timestamp(value: bytes) -> datetime | None:
    """t= as an aware UTC datetime; None if it is no number or out of datetime's range."""
    try:
        return datetime.fromtimestamp(int(value), UTC) if _DECIMAL.fullmatch(value) else None
    except (OverflowError, OSError, ValueError):
        return None


def _text(value: bytes) -> str:
    """A tag value as stored: lowercase text without NUL, which PostgreSQL text cannot hold."""
    text = value.decode("utf-8", "replace").strip().lower()
    return text.replace("\x00", "\N{REPLACEMENT CHARACTER}")

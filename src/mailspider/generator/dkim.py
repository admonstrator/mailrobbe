"""DKIM test keys, selector plans and signing for generated mails (SPEC 3.4, 3.6).

build_dkim_setup (main process) derives two RSA test keys from the run seed, 2048 bits for most
selectors and a 1024-bit legacy key for some old ones, decides per domain from when it signs and
rotates selectors over the date range. The DNS override table publishes the current and recently
retired selectors; older ones are gone, so old mails often come out no_key, and the lookup of a
few published names times out (temp_error).

sign_mail (workers) signs with the selector valid at the mail's date and sets t= to that date. The
header is built exactly as dkim.DKIM.sign builds it (dkimpy's parser, canonicalisation, header
selection and folding); only the RSA operation runs through cryptography instead of dkimpy's pure
Python, which is more than ten times faster and gives the same bytes, because PKCS#1 v1.5
signatures are deterministic. Some mails are changed after signing (a list footer or a subject
tag: fail), some get a second signature from a list or service domain on top. Faults are applied
before signing, so they never break a signature by themselves.

The signed share follows config.dkim_signed_share under two assumptions: mails spread evenly over
the date range, and external mails come about half from freemail and service domains and half
from organisations (_SERVICE_SENDER_SHARE). Internal domains sign exactly the target share.
"""

import base64
import bisect
import functools
import hashlib
import math
import random
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from dkim.canonicalization import (
    CanonicalizationPolicy,
    Relaxed,
    correct_empty_body,
    strip_trailing_lines,
)

import dkim
from mailspider.dkim.override import DnsOverrideTable, key_name
from mailspider.enums import DkimStatus, best_dkim_status
from mailspider.generator.config import DKIM_KEY_DIR, DNS_OVERRIDE_NAME, GeneratorConfig
from mailspider.generator.faults import append_footer, header_end, tag_subject
from mailspider.generator.model import (
    DkimOutcome,
    DkimSignatureOutcome,
    Domain,
    DomainKind,
    PlannedMail,
    RenderedMail,
)

KEY_SIZES = (2048, 1024)

_SERVICE_ADOPTION = 2.5  # freemail and service domains sign 1 - (1 - share) ** 2.5 of their mails
_SERVICE_SENDER_SHARE = 0.5  # assumed share of freemail and service senders among external mails
_NEVER_SIGN_SHARE = 0.15  # external organisations that never sign
_ROTATION_YEARS = (1.25, 4.0)
_RETIRED_GRACE_YEARS = (0.25, 1.5)  # a retired selector stays published this long
_KEEPS_OLD_KEYS = 0.2  # domains that never unpublish a retired selector
_LEGACY_KEY_SHARE = 0.5  # selectors from the first third of the range on the 1024-bit key
_RELAXED_SIMPLE_SHARE = 0.2
_TEMP_ERROR_SHARE = 0.05  # published selectors of external domains whose lookup times out

_RESIGN_LIST = 0.5  # list mails re-signed by the list host
_RESIGN_AUTOMATED = 0.3  # newsletters and notifications also signed by the sending service
_RESIGN_OTHER = 0.02
_TAMPER_LIST = 0.3  # list mails changed after the author signed
_TAMPER_OTHER = 0.025  # other mails changed by a gateway

# Selector naming styles; "{n}" counts rotations, "dkim" never rotates.
_SELECTOR_SCHEMES = (
    "mail{year}",
    "k{year}",
    "dkim{year}",
    "{year}{month:02d}",
    "s{n}",
    "selector{n}",
    "dkim",
)
_HEADER_ORDERS = (
    (
        "from",
        "to",
        "cc",
        "subject",
        "date",
        "message-id",
        "mime-version",
        "content-type",
        "in-reply-to",
        "references",
        "list-id",
    ),
    (
        "mime-version",
        "references",
        "in-reply-to",
        "from",
        "date",
        "message-id",
        "subject",
        "to",
        "cc",
        "content-type",
        "list-id",
    ),
)
_REASONS = {DkimStatus.NO_KEY: "selector_retired", DkimStatus.TEMP_ERROR: "dns_timeout"}
_SIGNATURE_HEADER = b"DKIM-Signature"
_KEYS_README = """\
Test keys of the Mailspider test data generator. They sign synthetic mails only and are
derived from the generator seed: never use them for real mail.

rsa-2048.pem  signs most selectors
rsa-1024.pem  signs some old selectors (legacy key size)

The public halves are the p= values in ../dns_override.json.
"""


@dataclass(frozen=True, slots=True)
class Selector:
    name: str
    valid_from: datetime  # first mail date it signs; the next selector takes over at its own
    key_bits: int  # one of KEY_SIZES
    status: DkimStatus  # what an intact signature verifies as: PASS, NO_KEY or TEMP_ERROR


@dataclass(frozen=True, slots=True)
class Signer:
    domain: str
    canonicalization: str  # "relaxed/relaxed" or "relaxed/simple"
    header_order: tuple[str, ...]  # h= order; headers missing from a mail are left out
    selectors: tuple[Selector, ...]  # by valid_from; the domain signs from the first one on

    def selector_at(self, when: datetime) -> Selector | None:
        index = bisect.bisect_right(self.selectors, when, key=lambda selector: selector.valid_from)
        return self.selectors[index - 1] if index else None


@dataclass(frozen=True, slots=True)
class DkimSetup:
    """Keys and selector plan, built once in the main process and shipped to the workers."""

    keys: Mapping[int, bytes] = field(default_factory=dict)  # key size in bits -> PKCS#1 PEM
    signers: Mapping[str, Signer] = field(default_factory=dict)  # other domains never sign
    relays: tuple[str, ...] = ()  # service domains that add a second signature

    def dns_table(self) -> DnsOverrideTable:
        records = {bits: _key_record(pem) for bits, pem in self.keys.items()}
        published: dict[str, str] = {}
        timeouts: set[str] = set()
        for signer in self.signers.values():
            for selector in signer.selectors:
                name = key_name(selector.name, signer.domain)
                if selector.status is DkimStatus.PASS:
                    published[name] = records[selector.key_bits]
                elif selector.status is DkimStatus.TEMP_ERROR:
                    timeouts.add(name)
        return DnsOverrideTable(published, frozenset(timeouts))


def build_dkim_setup(
    domains: Sequence[Domain], config: GeneratorConfig, rng: random.Random
) -> DkimSetup:
    keys = {bits: generate_test_key(bits, rng) for bits in KEY_SIZES}
    start = datetime.combine(config.date_from, time(), UTC)
    end = datetime.combine(config.date_to, time(), UTC) + timedelta(days=1)
    signers = {
        name: _plan_signer(name, share, start, end, rng)
        for name, share in _signed_shares(domains, config.dkim_signed_share, rng).items()
        if share > 0
    }
    internal = {domain.name for domain in domains if domain.internal}
    _add_temp_errors(signers, internal, rng)
    relays = tuple(
        domain.name
        for domain in domains
        if domain.kind is DomainKind.SERVICE and not domain.internal and domain.name in signers
    )
    return DkimSetup(keys=keys, signers=signers, relays=relays)


def write_dkim_artifacts(setup: DkimSetup, meta_dir: Path) -> None:
    """Write dns_override.json and the test keys (dkim_keys/) into meta_dir."""
    key_dir = meta_dir / DKIM_KEY_DIR
    key_dir.mkdir(parents=True, exist_ok=True)
    setup.dns_table().dump(meta_dir / DNS_OVERRIDE_NAME)
    for bits, pem in sorted(setup.keys.items()):
        (key_dir / f"rsa-{bits}.pem").write_bytes(pem)
    (key_dir / "README.txt").write_text(_KEYS_README, encoding="utf-8")


def sign_mail(mail: RenderedMail, setup: DkimSetup, rng: random.Random) -> RenderedMail:
    """Sign (or deliberately mis-sign) the mail and record the expected outcome in mail.dkim.

    mail.dkim.signatures lists the signatures in header order, topmost first.
    """
    planned = mail.planned
    author = setup.signers.get(planned.sender.domain)
    selector = author.selector_at(planned.date) if author else None
    if author is None or selector is None:
        return mail
    timestamp = int(planned.date.timestamp())
    raw = _signed(mail.raw, setup, author, selector, timestamp, planned.automated)
    signatures = [_outcome(author, selector)]
    relay = _relay(planned, setup, rng)
    if rng.random() < (_TAMPER_LIST if planned.list_id else _TAMPER_OTHER):
        # changed in transit: by the list host before it re-signs, or by a gateway
        raw, reason = _tamper(raw, planned, rng)
        if reason is not None and selector.status is DkimStatus.PASS:
            signatures[0] = replace(signatures[0], expected=DkimStatus.FAIL, reason=reason)
    if relay is not None:
        relay_signer, relay_selector = relay
        raw = _signed(raw, setup, relay_signer, relay_selector, timestamp, True)
        signatures.insert(0, _outcome(relay_signer, relay_selector))
    mail.raw = raw
    mail.dkim = DkimOutcome(
        expected=best_dkim_status(signature.expected for signature in signatures),
        signatures=tuple(signatures),
    )
    return mail


# Keys


_PUBLIC_EXPONENT = 65537
_SMALL_PRIMES = math.prod(
    p for p in range(3, 2000, 2) if all(p % q for q in range(3, math.isqrt(p) + 1, 2))
)


def _probable_prime(n: int, rng: random.Random) -> bool:
    """Trial division by the primes below 2000, then Miller-Rabin with 20 random bases."""
    if math.gcd(n, _SMALL_PRIMES) != 1:
        return False
    d, s = n - 1, 0
    while d % 2 == 0:
        d, s = d // 2, s + 1
    for _ in range(20):
        x = pow(rng.randrange(2, n - 1), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int, rng: random.Random) -> int:
    while True:
        # top two bits set, so the product of two such primes has exactly 2 * bits bits
        candidate = rng.getrandbits(bits) | (3 << (bits - 2)) | 1
        if candidate % _PUBLIC_EXPONENT != 1 and _probable_prime(candidate, rng):
            return candidate


def generate_test_key(bits: int, rng: random.Random) -> bytes:
    """RSA key as PKCS#1 PEM, derived from rng alone: the same seed always gives the same key.

    cryptography cannot generate keys from a seed, so the primes come from rng and cryptography
    assembles, checks and serialises the key.
    """
    p = _prime(bits // 2, rng)
    q = p
    while q == p:
        q = _prime(bits // 2, rng)
    d = pow(_PUBLIC_EXPONENT, -1, (p - 1) * (q - 1))
    numbers = rsa.RSAPrivateNumbers(
        p=p,
        q=q,
        d=d,
        dmp1=rsa.rsa_crt_dmp1(d, p),
        dmq1=rsa.rsa_crt_dmq1(d, q),
        iqmp=rsa.rsa_crt_iqmp(p, q),
        public_numbers=rsa.RSAPublicNumbers(_PUBLIC_EXPONENT, p * q),
    )
    return numbers.private_key().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )


@functools.cache
def _private_key(pem: bytes) -> rsa.RSAPrivateKey:
    """Parsed once per process and key."""
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError("DKIM test keys are RSA keys")
    return key


def _key_record(pem: bytes) -> str:
    public = (
        _private_key(pem)
        .public_key()
        .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    return "v=DKIM1; k=rsa; p=" + base64.b64encode(public).decode("ascii")


# Selector plan


def _signed_shares(domains: Sequence[Domain], share: float, rng: random.Random) -> dict[str, float]:
    """Share of its mails (over the date range) each domain signs; 0 for domains that never do."""
    internal = [domain.name for domain in domains if domain.internal]
    external = [domain for domain in domains if not domain.internal]
    services = [d.name for d in external if d.kind is not DomainKind.ORGANISATION]
    organisations = [d.name for d in external if d.kind is DomainKind.ORGANISATION]
    service_share = 1 - (1 - share) ** _SERVICE_ADOPTION
    organisation_share = (share - _SERVICE_SENDER_SHARE * service_share) / (
        1 - _SERVICE_SENDER_SHARE
    )
    shares = dict.fromkeys(internal, share)
    shares |= _spread(services, service_share, 0.0, rng)
    shares |= _spread(organisations, min(1.0, max(0.0, organisation_share)), _NEVER_SIGN_SHARE, rng)
    return shares


def _spread(names: list[str], mean: float, never: float, rng: random.Random) -> dict[str, float]:
    """Per-domain shares averaging `mean`: a few domains never sign, the others spread evenly."""
    if not names or mean <= 0:
        return dict.fromkeys(names, 0.0)
    silent = min(round(len(names) * never), int(len(names) * (1 - mean)))
    signing = len(names) - silent
    signing_mean = mean * len(names) / signing
    low, high = max(0.0, 2 * signing_mean - 1), min(1.0, 2 * signing_mean)
    shares = [0.0] * silent + [low + (high - low) * (i + 0.5) / signing for i in range(signing)]
    rng.shuffle(shares)
    return dict(zip(names, shares, strict=True))


def _plan_signer(
    domain: str, share: float, start: datetime, end: datetime, rng: random.Random
) -> Signer:
    span = end - start
    # share 1: the domain signed before the range began
    since = start - timedelta(days=rng.uniform(30, 3 * 365)) if share >= 1 else end - span * share
    scheme = rng.choice(_SELECTOR_SCHEMES)
    period = rng.uniform(*_ROTATION_YEARS) * 365  # at least 388 days: year-based names stay unique
    starts = [since]
    if "{" in scheme:
        while (following := starts[-1] + timedelta(days=period * rng.uniform(0.85, 1.15))) < end:
            starts.append(following)
    grace = timedelta(days=rng.uniform(*_RETIRED_GRACE_YEARS) * 365)
    keeps_old_keys = rng.random() < _KEEPS_OLD_KEYS
    legacy_until = start + span / 3
    selectors = []
    for number, valid_from in enumerate(starts, 1):
        retired = starts[number] if number < len(starts) else None
        published = retired is None or keeps_old_keys or retired > end - grace
        legacy = valid_from < legacy_until and rng.random() < _LEGACY_KEY_SHARE
        selectors.append(
            Selector(
                name=scheme.format(year=valid_from.year, month=valid_from.month, n=number),
                valid_from=valid_from,
                key_bits=1024 if legacy else 2048,
                status=DkimStatus.PASS if published else DkimStatus.NO_KEY,
            )
        )
    canonicalization = (
        "relaxed/simple" if rng.random() < _RELAXED_SIMPLE_SHARE else "relaxed/relaxed"
    )
    return Signer(domain, canonicalization, rng.choice(_HEADER_ORDERS), tuple(selectors))


def _add_temp_errors(signers: dict[str, Signer], internal: set[str], rng: random.Random) -> None:
    candidates = [
        (domain, index)
        for domain, signer in signers.items()
        if domain not in internal
        for index, selector in enumerate(signer.selectors)
        if selector.status is DkimStatus.PASS
    ]
    if not candidates:
        return
    for domain, index in rng.sample(candidates, max(1, round(len(candidates) * _TEMP_ERROR_SHARE))):
        selectors = list(signers[domain].selectors)
        selectors[index] = replace(selectors[index], status=DkimStatus.TEMP_ERROR)
        signers[domain] = replace(signers[domain], selectors=tuple(selectors))


# Signing


def _outcome(signer: Signer, selector: Selector) -> DkimSignatureOutcome:
    return DkimSignatureOutcome(
        domain=signer.domain,
        selector=selector.name,
        algorithm="rsa-sha256",
        key_bits=selector.key_bits,
        expected=selector.status,
        reason=_REASONS.get(selector.status),
    )


def _relay(
    planned: PlannedMail, setup: DkimSetup, rng: random.Random
) -> tuple[Signer, Selector] | None:
    """The list host or sending service that adds a second signature, if any."""
    if planned.list_id:
        chance = _RESIGN_LIST
    else:
        chance = _RESIGN_AUTOMATED if planned.automated else _RESIGN_OTHER
    if rng.random() >= chance:
        return None
    sender = planned.sender.domain
    host = _list_address(planned.list_id)[1] if planned.list_id else ""
    relays = [domain for domain in setup.relays if domain != sender]
    if host in setup.signers and host != sender:
        signer = setup.signers[host]
    elif relays:
        route = planned.list_id or sender  # the same list or sender always takes the same route
        signer = setup.signers[relays[zlib.crc32(route.encode()) % len(relays)]]
    else:
        return None
    selector = signer.selector_at(planned.date)
    return None if selector is None else (signer, selector)


def _list_address(list_id: str) -> tuple[str, str]:
    """('team', 'lists.verband.example') from '<team.lists.verband.example>' or 'Team <...>'."""
    name, _, host = list_id.rpartition("<")[2].rstrip(">").strip().lower().partition(".")
    return name or "list", host


def _tamper(raw: bytes, planned: PlannedMail, rng: random.Random) -> tuple[bytes, str | None]:
    """Change the signed mail the way a list server or gateway does; reason None if impossible."""
    if planned.list_id:
        name, host = _list_address(planned.list_id)
        host = host or planned.sender.domain
        tag = f"[{name}]"
        footer = (
            f"_______________________________________________\n{name} mailing list\n"
            f"To unsubscribe write to {name}-leave@{host}"
        )
        body_first = rng.random() < 0.7
    else:
        tag = "[EXTERN]"
        footer = "--\nDiese Nachricht wurde vom E-Mail-Gateway auf Viren geprueft."
        body_first = rng.random() < 0.5
    edits = [(append_footer, footer, "body_modified"), (tag_subject, tag, "header_modified")]
    if not body_first:
        edits.reverse()
    for edit, text, reason in edits:
        changed = edit(raw, text)
        if changed is not None:
            return changed, reason
    return raw, None


def _signed(
    raw: bytes,
    setup: DkimSetup,
    signer: Signer,
    selector: Selector,
    timestamp: int,
    sign_list_id: bool,
) -> bytes:
    key = setup.keys[selector.key_bits]
    return _signature(raw, signer, selector, key, timestamp, sign_list_id) + raw


def _canonical_body(policy: CanonicalizationPolicy, body: bytes) -> bytes:
    """policy.canonicalize_body of the body as dkim.rfc822_parse returns it, only faster.

    dkimpy splits the body into lines and runs two whitespace regexes over it, which costs about
    80 ms per MB. bytes.replace gives the same CRLF body, and the regexes cannot change a body
    without tabs, double spaces and spaces before a line end, which covers base64 attachments.
    """
    body = body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    plain = not (b"\t" in body or b"  " in body or b" \r\n" in body)
    canonical: bytes
    if policy.body_algorithm is Relaxed and plain:
        canonical = correct_empty_body(strip_trailing_lines(body))  # what remains of relaxed
    else:
        canonical = policy.canonicalize_body(body)
    return canonical


def _tag_list(fields: list[tuple[bytes, bytes]]) -> bytes:
    return b"; ".join(b"=".join(tag) for tag in fields)


def _signature(
    message: bytes,
    signer: Signer,
    selector: Selector,
    pem: bytes,
    timestamp: int,
    sign_list_id: bool,
) -> bytes:
    """The DKIM-Signature header field with LF line endings, built like dkim.DKIM.sign."""
    head_end = header_end(message)
    headers, _ = dkim.rfc822_parse(message[:head_end])
    present = {name.lower() for name, _ in headers}
    include = tuple(
        name
        for name in (header.encode() for header in signer.header_order)
        if name in present and (sign_list_id or name != b"list-id")
    )
    policy = CanonicalizationPolicy.from_c_value(signer.canonicalization.encode())
    body = _canonical_body(policy, message[head_end + 1 :])
    body_hash = base64.b64encode(hashlib.sha256(body).digest())
    domain = signer.domain.encode()
    fields = [
        (b"v", b"1"),
        (b"a", b"rsa-sha256"),
        (b"c", policy.to_c_value()),
        (b"d", domain),
        (b"i", b"@" + domain),
        (b"q", b"dns/txt"),
        (b"s", selector.name.encode()),
        (b"t", str(timestamp).encode()),
        (b"h", b" : ".join(include)),
        (b"bh", body_hash),
        (b"b", b"0" * 60),  # placeholder as in dkimpy, so that b= folds onto its own line
    ]
    # The steps of dkim.DomainSigner.gen_header, with the RSA operation done by cryptography.
    folded = dkim.fold(_tag_list(fields), namelen=len(_SIGNATURE_HEADER), linesep=b"\r\n")
    unsigned = (_SIGNATURE_HEADER, b" " + dkim.RE_BTAG.sub(b"\\1", folded))
    hasher = hashlib.sha256()
    canonical = policy.canonicalize_headers(headers)
    dkim.hash_headers(hasher, policy, canonical, include, unsigned, dict(fields))
    digest = hasher.digest()
    signature = _private_key(pem).sign(digest, padding.PKCS1v15(), Prehashed(hashes.SHA256()))
    fields[-1] = (b"b", base64.b64encode(signature))
    value: bytes = dkim.fold(
        _tag_list(fields) + b"\n", namelen=len(_SIGNATURE_HEADER), linesep=b"\n"
    )
    return _SIGNATURE_HEADER + b": " + value

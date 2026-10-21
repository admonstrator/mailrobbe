"""verify_mail on hand-built signed mails: every outcome and detail, with dkimpy as a cross-check.

The mails are signed here with dkimpy's parser, canonicalisation and header hashing and keys from
cryptography (RSA 2048, 1024 and 512 bits, ed25519), the way the generator signs, so every tag can
be set or broken on purpose. Keys come from small dict-backed key sources; nothing reaches DNS.
"""

import base64
import functools
import hashlib
import logging
import random
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import dkim
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from dkim.canonicalization import CanonicalizationPolicy, InvalidCanonicalizationPolicyError
from dkim.util import parse_tag_value

from mailrobbe.dkim import verify
from mailrobbe.dkim.canonical import canonical_blocks
from mailrobbe.dkim.model import (
    NO_CANDIDATES,
    CandidateKey,
    DnsAnswer,
    KeyCandidates,
    MailVerdict,
    SignatureResult,
)
from mailrobbe.dkim.override import DnsOverrideTable, key_name
from mailrobbe.dkim.verify import verify_mail
from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus, KeyOrigin
from mailrobbe.generator.dkim import generate_test_key
from tests import dkim_check
from tests.dkim.conftest import Corpus
from tests.dkim.samples import INTERNAL, sample_mail, sample_setup

PrivateKey = rsa.RSAPrivateKey | Ed25519PrivateKey

DOMAIN = INTERNAL.name  # the From domain of MESSAGE
SELECTOR = "s1"
NAME = key_name(SELECTOR, DOMAIN)
SIGNED = "from:to:subject:date:message-id"
TIMESTAMP = 1_300_000_000  # 2011-03-13 07:06:40 UTC
MESSAGE = sample_mail(4, "mixed", sender=INTERNAL).raw  # multipart, LF line endings

FAIL, PASS, NO_KEY, TEMP_ERROR = (
    DkimStatus.FAIL,
    DkimStatus.PASS,
    DkimStatus.NO_KEY,
    DkimStatus.TEMP_ERROR,
)
R = DkimReason


@functools.cache
def private_key(kind: str) -> PrivateKey:
    """ "rsa2048" and "rsa1024" are the sample setup's keys, "rsa512" and "ed25519" fixed ones."""
    if kind == "ed25519":
        return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    bits = int(kind.removeprefix("rsa"))
    keys = sample_setup().keys
    pem = keys[bits] if bits in keys else generate_test_key(bits, random.Random(bits))
    key = serialization.load_pem_private_key(pem, password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    return key


def _tag_list(values: Mapping[str, str], drop: Iterable[str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in values.items() if name not in drop)


def record(kind: str = "rsa2048", *, drop: Iterable[str] = (), **tags: str) -> str:
    """The key record publishing a key, with tags set or dropped."""
    public = private_key(kind).public_key()
    if isinstance(public, rsa.RSAPublicKey):
        data = public.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    else:
        data = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    values = {
        "v": "DKIM1",
        "k": "rsa" if kind.startswith("rsa") else "ed25519",
        "p": base64.b64encode(data).decode(),
    }
    return _tag_list(values | tags, drop)


def bare_rsa_record() -> str:
    """The 2048-bit key as a bare RSAPublicKey (PKCS#1) instead of a SubjectPublicKeyInfo."""
    public = private_key("rsa2048").public_key()
    data = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.PKCS1)
    return "v=DKIM1; k=rsa; p=" + base64.b64encode(data).decode()


def _policy(c: str | None) -> Any:
    try:
        return CanonicalizationPolicy.from_c_value(None if c is None else c.encode())
    except InvalidCanonicalizationPolicyError:  # signing a deliberately broken c=
        return CanonicalizationPolicy.from_c_value(b"relaxed/relaxed")


def sign(
    message: bytes,
    kind: str = "rsa2048",
    *,
    length: int | None = None,
    field_name: bytes = b"DKIM-Signature",
    drop: Iterable[str] = (),
    **tags: str,
) -> bytes:
    """message with a DKIM-Signature field on top, computed as dkim.DKIM.sign computes it.

    Tags default to a=, c=relaxed/relaxed, d=DOMAIN, s=SELECTOR, t=TIMESTAMP, h=SIGNED; tags in
    drop are left out, bh= and b= are computed unless given.
    """
    drop = set(drop)
    values = {
        "v": "1",
        "a": "ed25519-sha256" if kind == "ed25519" else "rsa-sha256",
        "c": "relaxed/relaxed",
        "d": DOMAIN,
        "s": SELECTOR,
        "t": str(TIMESTAMP),
        "h": SIGNED,
    }
    if length is not None:
        values["l"] = str(length)
    values |= {name: value for name, value in tags.items() if name not in ("bh", "b")}
    headers, body = dkim.rfc822_parse(message)
    policy = _policy(None if "c" in drop else values["c"])
    hash_name = "sha1" if values["a"] == "rsa-sha1" else "sha256"
    canonical = policy.canonicalize_body(body)
    if length is not None:
        canonical = canonical[:length]
    computed = base64.b64encode(hashlib.new(hash_name, canonical).digest()).decode()
    values["bh"] = tags.get("bh", computed)
    unsigned = _tag_list(values, drop)
    if "b" in tags or "b" in drop:
        value = unsigned + ("" if "b" in drop else f"; b={tags['b']}")
        return field_name + b": " + value.encode() + b"\n" + message
    unsigned += "; b="
    signed = "" if "h" in drop else values["h"]
    include = [name.lower() for name in re.split(rb"\s*:\s*", signed.encode())]
    hasher = hashlib.new(hash_name)
    canonical_headers = policy.canonicalize_headers(headers)
    dkim.hash_headers(
        hasher, policy, canonical_headers, include, (field_name, b" " + unsigned.encode()), {}
    )
    key = private_key(kind)
    if isinstance(key, Ed25519PrivateKey):
        signature = key.sign(hasher.digest())
    else:
        algorithm = hashes.SHA1() if hash_name == "sha1" else hashes.SHA256()
        signature = key.sign(hasher.digest(), padding.PKCS1v15(), Prehashed(algorithm))
    value = unsigned + base64.b64encode(signature).decode()
    return field_name + b": " + value.encode() + b"\n" + message


def signature_value(raw: bytes) -> bytes:
    """The tag list of the topmost DKIM-Signature field."""
    headers, _ = dkim.rfc822_parse(raw.split(b"\n\n")[0] + b"\n\n")
    value: bytes = next(value for name, value in headers if name.lower() == b"dkim-signature")
    return value


@dataclass
class Keys:
    """A KeySource over a dict of key records; names in timeouts time out. Records its calls."""

    records: Mapping[str, str] = field(default_factory=dict)
    timeouts: frozenset[str] = frozenset()
    reason: DkimReason | None = None  # for timeouts; default dns_timeout
    from_cache: bool = False
    calls: list[str] = field(default_factory=list)

    @property
    def table(self) -> DnsOverrideTable:
        return DnsOverrideTable(self.records, self.timeouts)

    def __call__(self, name: str) -> DnsAnswer:
        self.calls.append(name)
        answer = replace(self.table.answer(name), from_cache=self.from_cache)
        if answer.status is DnsStatus.TEMP_ERROR and self.reason is not None:
            answer = replace(answer, reason=self.reason)
        return answer


def published(kind: str = "rsa2048", *, drop: Iterable[str] = (), **tags: str) -> dict[str, str]:
    return {NAME: record(kind, drop=drop, **tags)}


def only(raw: bytes, keys: Keys, candidates: KeyCandidates = NO_CANDIDATES) -> SignatureResult:
    verdict = verify_mail(raw, keys, candidates)
    assert len(verdict.signatures) == 1
    return verdict.signatures[0]


def changed_body(raw: bytes) -> bytes:
    return raw + b"Added after signing\n"


def changed_subject(raw: bytes) -> bytes:
    return raw.replace(b"\nSubject: ", b"\nSubject: [EXTERN] ", 1)


def with_from(value: bytes, message: bytes = MESSAGE) -> bytes:
    return re.sub(rb"(?m)^From: .*\n", b"From: " + value + b"\n", message, count=1)


def without_leading_zero() -> bytes:
    """A signed mail whose b= value has lost its leading zero byte."""
    for number in range(5000):
        message = MESSAGE.replace(b"Subject: ", f"Subject: {number} ".encode(), 1)
        raw = sign(message, "rsa1024")
        encoded = parse_tag_value(signature_value(raw))[b"b"]
        signature = base64.b64decode(encoded)
        if signature[0] == 0:
            return raw.replace(encoded, base64.b64encode(signature[1:]))
    raise AssertionError("no signature with a leading zero byte")


@dataclass(frozen=True)
class Case:
    raw: bytes
    status: DkimStatus
    reason: DkimReason | None
    records: Mapping[str, str] = field(default_factory=dict)
    timeouts: frozenset[str] = frozenset()
    offline: bool = False
    dkimpy: bool = True  # tests/dkim_check reaches the same status
    # keys of deleted selectors (D100); the cases with candidates that decide are in
    # test_keys_verify.py
    candidates: Mapping[str, Sequence[CandidateKey]] = field(default_factory=dict)

    def keys(self) -> Keys:
        return Keys(self.records, self.timeouts, R.DNS_OFFLINE if self.offline else None)


def _pass(raw: bytes, records: Mapping[str, str] | None = None, *, dkimpy: bool = True) -> Case:
    return Case(raw, PASS, None, published() if records is None else records, dkimpy=dkimpy)


def _fail(raw: bytes, reason: DkimReason, records: Mapping[str, str] | None = None) -> Case:
    return Case(raw, FAIL, reason, published() if records is None else records)


def _missing(tag: str) -> Case:
    return _fail(sign(MESSAGE, drop=[tag]), R.SIGNATURE_MALFORMED)


# One mail per row of the order of checks (verify.py). dkimpy=False where dkimpy decides
# differently or not at all; the comment says why.
CASES: dict[str, Callable[[], Case]] = {
    # 1. header section; dkimpy raises MessageFormatError (IndexError) for the whole mail
    "line without colon": lambda: replace(
        _fail(sign(MESSAGE).replace(b"\nSubject:", b"\nno field\nSubject:"), R.MESSAGE_MALFORMED),
        dkimpy=False,
    ),
    "continuation line first": lambda: replace(
        _fail(b" folded\n" + sign(MESSAGE), R.MESSAGE_MALFORMED), dkimpy=False
    ),
    # 2. tags
    "duplicate tag": lambda: _fail(sign(MESSAGE, d=f"{DOMAIN}; d={DOMAIN}"), R.SIGNATURE_MALFORMED),
    **{
        f"no {tag}=": functools.partial(_missing, tag)
        for tag in ("v", "a", "b", "bh", "d", "h", "s")
    },
    "v=2": lambda: _fail(sign(MESSAGE, v="2"), R.SIGNATURE_MALFORMED),
    "t= not decimal": lambda: _fail(sign(MESSAGE, t="yesterday"), R.SIGNATURE_MALFORMED),
    "x= not decimal": lambda: _fail(sign(MESSAGE, x="soon"), R.SIGNATURE_MALFORMED),
    "l= not decimal": lambda: _fail(sign(MESSAGE, l="all"), R.SIGNATURE_MALFORMED),
    "b= not base64": lambda: _fail(sign(MESSAGE, b="not base64!"), R.SIGNATURE_MALFORMED),
    "bh= not base64": lambda: _fail(sign(MESSAGE, bh="@@@@"), R.SIGNATURE_MALFORMED),
    "i= outside d=": lambda: _fail(sign(MESSAGE, i="@other.example"), R.SIGNATURE_MALFORMED),
    "unknown c=": lambda: _fail(sign(MESSAGE, c="fancy/simple"), R.SIGNATURE_MALFORMED),
    "q= without dns/txt": lambda: _fail(sign(MESSAGE, q="dns/xml"), R.SIGNATURE_MALFORMED),
    "d= with specials": lambda: _fail(sign(MESSAGE, d="nordwind,example"), R.SIGNATURE_MALFORMED),
    "a=rsa-sha512": lambda: _fail(sign(MESSAGE, a="rsa-sha512"), R.UNSUPPORTED_ALGORITHM),
    # 3. RFC 6376 5.4; dkimpy does not check it when verifying and passes the signature
    "from not signed": lambda: replace(
        _fail(sign(MESSAGE, h="to:subject:date"), R.FROM_NOT_SIGNED), dkimpy=False
    ),
    # 4. key
    "dns timeout": lambda: Case(
        sign(MESSAGE), TEMP_ERROR, R.DNS_TIMEOUT, timeouts=frozenset([NAME])
    ),
    "dns offline": lambda: Case(
        sign(MESSAGE), TEMP_ERROR, R.DNS_OFFLINE, timeouts=frozenset([NAME]), offline=True
    ),
    "key not found": lambda: Case(sign(MESSAGE), NO_KEY, R.KEY_NOT_FOUND),
    "no candidate key fits": lambda: Case(
        sign(MESSAGE),
        NO_KEY,
        R.KEY_MISMATCH,
        candidates={NAME: [CandidateKey(1, KeyOrigin.RECONSTRUCTED, record("rsa1024"))]},
    ),
    # dkimpy treats a revoked key like a broken one: fail
    "key revoked": lambda: Case(
        sign(MESSAGE), NO_KEY, R.KEY_REVOKED, {NAME: "v=DKIM1; k=rsa; p="}, dkimpy=False
    ),
    "key record unparsable": lambda: _fail(sign(MESSAGE), R.KEY_MALFORMED, {NAME: "v=DKIM1; p"}),
    "key record empty": lambda: _fail(sign(MESSAGE), R.KEY_MALFORMED, {NAME: ""}),
    "key v=DKIM2": lambda: _fail(sign(MESSAGE), R.KEY_MALFORMED, published(v="DKIM2")),
    "key p= garbage": lambda: _fail(sign(MESSAGE), R.KEY_MALFORMED, {NAME: "p=QUJDRA=="}),
    "key k=dsa": lambda: _fail(sign(MESSAGE), R.KEY_MALFORMED, published(k="dsa")),
    "rsa key, ed25519 signature": lambda: _fail(sign(MESSAGE, "ed25519"), R.KEY_MALFORMED),
    # dkimpy cannot read ed25519 keys at all (no pynacl)
    "ed25519 key, rsa signature": lambda: replace(
        _fail(sign(MESSAGE), R.KEY_MALFORMED, published("ed25519")), dkimpy=False
    ),
    # dkimpy ignores the key's h=
    "key only for sha1": lambda: replace(
        _fail(sign(MESSAGE), R.KEY_MALFORMED, published(h="sha1")), dkimpy=False
    ),
    "key for another service": lambda: _fail(sign(MESSAGE), R.KEY_MALFORMED, published(s="tlsrpt")),
    "512-bit key": lambda: _fail(sign(MESSAGE, "rsa512"), R.KEY_TOO_SHORT, published("rsa512")),
    # 5. and 6.
    "body changed": lambda: _fail(changed_body(sign(MESSAGE)), R.BODY_HASH_MISMATCH),
    "header changed": lambda: _fail(changed_subject(sign(MESSAGE)), R.SIGNATURE_MISMATCH),
    "another key": lambda: _fail(sign(MESSAGE), R.SIGNATURE_MISMATCH, published("rsa1024")),
    "second From added": lambda: _fail(
        sign(MESSAGE).replace(b"\nTo:", b"\nFrom: someone@nordwind.example\nTo:", 1),
        R.SIGNATURE_MISMATCH,
    ),
    # 7. pass
    "rsa-sha256": lambda: _pass(sign(MESSAGE)),
    "rsa-sha1": lambda: _pass(sign(MESSAGE, a="rsa-sha1")),
    "rsa 1024 relaxed/simple": lambda: _pass(
        sign(MESSAGE, "rsa1024", c="relaxed/simple"), published("rsa1024")
    ),
    "simple/simple": lambda: _pass(sign(MESSAGE, c="simple/simple")),
    "no c=": lambda: _pass(sign(MESSAGE, drop=["c"])),
    "relaxed": lambda: _pass(sign(MESSAGE, c="relaxed")),
    # dkimpy cannot verify ed25519 (no pynacl)
    "ed25519-sha256": lambda: _pass(sign(MESSAGE, "ed25519"), published("ed25519"), dkimpy=False),
    "l= and text added": lambda: _pass(changed_body(sign(MESSAGE, length=40))),
    "l=0": lambda: _pass(changed_body(sign(MESSAGE, length=0))),
    "l= beyond the body": lambda: _pass(sign(MESSAGE, length=10**6)),
    "i= in a subdomain": lambda: _pass(sign(MESSAGE, i=f"info@mail.{DOMAIN}")),
    "q=dns/txt": lambda: _pass(sign(MESSAGE, q="dns/txt")),
    # dkimpy judges t= and x= by the wall clock
    "x= in the past": lambda: _pass(sign(MESSAGE, x=str(TIMESTAMP + 3600)), dkimpy=False),
    "t= in the future": lambda: _pass(sign(MESSAGE, t="4000000000"), dkimpy=False),
    "upper case d= and s=": lambda: _pass(sign(MESSAGE, d="NordWind.Example", s="S1")),
    "h= with spaces and case": lambda: _pass(sign(MESSAGE, h="From : To:SUBJECT")),
    "key as RSAPublicKey": lambda: _pass(sign(MESSAGE), {NAME: bare_rsa_record()}),
    "key without v= and k=": lambda: _pass(sign(MESSAGE), published(drop=["v", "k"])),
    "key h= and s= that fit": lambda: _pass(sign(MESSAGE), published(h="sha1:sha256", s="email")),
    "key t=y": lambda: _pass(sign(MESSAGE), published(t="y")),
    "crlf": lambda: _pass(sign(MESSAGE).replace(b"\n", b"\r\n")),
    "lower case field name, simple": lambda: _pass(
        sign(MESSAGE, c="simple/simple", field_name=b"dkim-signature")
    ),
    "signed by dkimpy": lambda: _pass(
        dkim.sign(
            MESSAGE,
            SELECTOR.encode(),
            DOMAIN.encode(),
            sample_setup().keys[2048],
            include_headers=[b"from", b"to", b"subject", b"date", b"message-id", b"from"],
            linesep=b"\n",
        )
        + MESSAGE
    ),
    "b= without its leading zero byte": lambda: _pass(without_leading_zero(), published("rsa1024")),
}


_NO_LOOKUP = {
    R.MESSAGE_MALFORMED,
    R.SIGNATURE_MALFORMED,
    R.UNSUPPORTED_ALGORITHM,
    R.FROM_NOT_SIGNED,
}


@functools.cache
def built(name: str) -> Case:
    return CASES[name]()


@pytest.mark.parametrize("name", CASES)
def test_order_of_checks(name: str) -> None:
    case = built(name)
    keys = case.keys()
    result = only(case.raw, keys, case.candidates)
    assert (result.status, result.reason) == (case.status, case.reason)
    assert keys.calls == ([] if case.reason in _NO_LOOKUP else [NAME])
    if case.dkimpy:
        assert dkim_check.verify_mail(case.raw, keys.table)[1] == [case.status]


def test_every_reason_has_a_case() -> None:
    assert {built(name).reason for name in CASES} == set(DkimReason) | {None}


def test_lf_and_crlf_give_the_same_results() -> None:
    for name in ("rsa-sha256", "simple/simple", "body changed", "header changed", "l=0"):
        case = built(name)
        lf = verify_mail(case.raw, case.keys())
        assert verify_mail(case.raw.replace(b"\n", b"\r\n"), case.keys()) == lf


def test_details_of_a_pass() -> None:
    raw = sign(MESSAGE, d="NordWind.Example", s="S1", h="From : To:Subject", t="1234567890")
    result = only(raw, Keys(published()))
    assert result == SignatureResult(
        status=PASS,
        reason=None,
        domain="nordwind.example",
        selector="s1",
        algorithm="rsa-sha256",
        key_bits=2048,
        signed_headers=("from", "to", "subject"),
        body_hash_ok=True,
        signed_at=datetime(2009, 2, 13, 23, 31, 30, tzinfo=UTC),
        aligned=True,
        dns_cached=False,
        key_origin=KeyOrigin.DNS,
    )


@pytest.mark.parametrize(
    ("raw", "kind", "reason", "bits"),
    [
        (lambda: changed_subject(sign(MESSAGE)), "rsa2048", R.SIGNATURE_MISMATCH, 2048),
        (lambda: sign(MESSAGE), "rsa1024", R.SIGNATURE_MISMATCH, 1024),
        (lambda: sign(MESSAGE, "rsa512"), "rsa512", R.KEY_TOO_SHORT, 512),
        (lambda: sign(MESSAGE), "ed25519", R.KEY_MALFORMED, 256),
        (lambda: changed_body(sign(MESSAGE, "ed25519")), "ed25519", R.BODY_HASH_MISMATCH, 256),
    ],
    ids=["mismatch", "other key", "too short", "wrong key type", "ed25519 body"],
)
def test_key_bits_also_when_failing(
    raw: Callable[[], bytes], kind: str, reason: DkimReason, bits: int
) -> None:
    result = only(raw(), Keys(published(kind)))
    assert (result.status, result.reason, result.key_bits) == (FAIL, reason, bits)


def test_body_hash_is_known_before_the_key() -> None:
    signed = sign(MESSAGE)
    assert only(signed, Keys()).body_hash_ok is True
    assert only(changed_body(signed), Keys()).body_hash_ok is False
    assert only(signed, Keys(timeouts=frozenset([NAME]))).body_hash_ok is True
    assert only(changed_body(signed), Keys(published())).body_hash_ok is False
    assert only(changed_subject(signed), Keys(published())).body_hash_ok is True
    assert only(sign(MESSAGE, h="to:subject"), Keys()).body_hash_ok is True
    assert only(sign(MESSAGE, v="2"), Keys()).body_hash_ok is None
    assert only(sign(MESSAGE, a="rsa-sha512"), Keys()).body_hash_ok is None


def test_details_of_broken_signatures() -> None:
    result = only(sign(MESSAGE, a="RSA-SHA256"), Keys(published()))
    assert (result.reason, result.algorithm, result.domain, result.selector) == (
        R.UNSUPPORTED_ALGORITHM,
        "rsa-sha256",
        DOMAIN,
        SELECTOR,
    )
    assert result.signed_headers == tuple(SIGNED.split(":"))
    assert result.signed_at == datetime.fromtimestamp(TIMESTAMP, UTC)
    assert result.aligned is True
    malformed = only(sign(MESSAGE).replace(b"\nSubject:", b"\nno field\nSubject:"), Keys())
    assert (malformed.reason, malformed.domain, malformed.selector) == (
        R.MESSAGE_MALFORMED,
        DOMAIN,
        SELECTOR,
    )
    assert malformed.aligned is None
    unparsable = only(sign(MESSAGE, d=f"{DOMAIN}; d={DOMAIN}"), Keys())
    assert unparsable.domain is None
    keys = Keys()
    nul = only(sign(MESSAGE, s="s\x001"), keys)
    assert (nul.reason, nul.selector, keys.calls) == (R.SIGNATURE_MALFORMED, "s�1", [])


@pytest.mark.parametrize(
    ("t", "signed_at"),
    [
        (None, None),
        ("0", datetime(1970, 1, 1, tzinfo=UTC)),
        ("99999999999999999999", None),
        ("9" * 5000, None),
    ],
)
def test_signed_at(t: str | None, signed_at: datetime | None) -> None:
    raw = sign(MESSAGE, drop=["t"]) if t is None else sign(MESSAGE, t=t)
    result = only(raw, Keys(published()))
    assert (result.status, result.signed_at) == (PASS, signed_at)


@pytest.mark.parametrize(
    ("author", "domain", "aligned"),
    [
        (b"Max <max@nordwind.example>", DOMAIN, True),
        (b"max@nordwind.example", DOMAIN, True),
        (b"Max <max@NordWind.Example>", DOMAIN, True),
        (b"Max <max@mail.nordwind.example>", DOMAIN, True),
        (b"Max <max@nordwind.example>", f"lists.{DOMAIN}", True),
        (b'"M\xc3\xbcller, Karin" <karin@nordwind.example>', DOMAIN, True),
        (b"Max <max@other.example>", DOMAIN, False),
        (b"Max <max@evilnordwind.example>", DOMAIN, False),
        (b"Max <max@nordwind.example>", "example", True),
        (b"max@nordwind.example, anna@nordwind.example", DOMAIN, None),
        (b"undisclosed-recipients:;", DOMAIN, None),
        (b"no address", DOMAIN, None),
    ],
)
def test_alignment(author: bytes, domain: str, aligned: bool | None) -> None:
    raw = sign(with_from(author), d=domain)
    result = only(raw, Keys({key_name(SELECTOR, domain): record()}))
    assert result.status is PASS
    assert result.aligned is aligned


def test_alignment_needs_exactly_one_from_field() -> None:
    message = MESSAGE.replace(b"\nTo:", b"\nFrom: max@nordwind.example\nTo:", 1)
    assert only(sign(message), Keys(published())).aligned is None


def test_answer_from_the_cache() -> None:
    assert only(sign(MESSAGE), Keys(published(), from_cache=True)).dns_cached is True
    assert only(sign(MESSAGE), Keys(from_cache=True)).dns_cached is True
    assert only(sign(MESSAGE), Keys(published())).dns_cached is False


def test_several_signatures_in_header_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def counted(data: bytes, relaxed: bool, start: int = 0) -> Iterator[bytes]:
        calls.append(relaxed)
        return canonical_blocks(data, relaxed, start)

    monkeypatch.setattr(verify, "canonical_blocks", counted)
    list_domain = "lists.verband.example"
    raw = sign(MESSAGE)  # the author
    raw = sign(raw, "rsa1024", d=list_domain, s="list", h=SIGNED + ":list-id")
    raw = sign(raw, "ed25519", d="relay.example", s="r", c="relaxed/simple")
    keys = Keys(
        {
            NAME: record(),
            key_name("list", list_domain): record("rsa1024"),
            # relay.example has no key
        }
    )
    verdict = verify_mail(raw, keys)
    assert [(s.domain, s.status) for s in verdict.signatures] == [
        ("relay.example", NO_KEY),
        (list_domain, PASS),
        (DOMAIN, PASS),
    ]
    assert [s.aligned for s in verdict.signatures] == [False, False, True]
    assert verdict.status is PASS
    assert keys.calls == [key_name("r", "relay.example"), key_name("list", list_domain), NAME]
    assert sorted(calls) == [False, True]  # one canonical body per body canonicalisation


def test_unsigned_mail() -> None:
    keys = Keys()
    assert verify_mail(MESSAGE, keys) == MailVerdict()
    assert verify_mail(MESSAGE, keys).status is DkimStatus.UNSIGNED
    assert keys.calls == []


def test_an_unexpected_error_fails_the_signature(caplog: pytest.LogCaptureFixture) -> None:
    def broken(name: str) -> DnsAnswer:
        raise RuntimeError("resolver bug")

    raw = sign(MESSAGE)
    raw = sign(raw, d="other.example")
    with caplog.at_level(logging.WARNING, logger=verify.__name__):
        verdict = verify_mail(raw, broken)
    assert [(s.status, s.reason) for s in verdict.signatures] == [(FAIL, R.SIGNATURE_MALFORMED)] * 2
    first = verdict.signatures[0]
    assert (first.domain, first.selector, first.body_hash_ok) == ("other.example", SELECTOR, True)
    warnings = [r for r in caplog.records if r.name == verify.__name__]
    assert len(warnings) == 2
    assert all(r.levelno == logging.WARNING and r.exc_info for r in warnings)


def _broken_inputs(corpus: Corpus) -> Iterator[bytes]:
    rng = random.Random(11)
    yield from (b"", b"\n", b"\r\n", b"\n\n", b"DKIM-Signature:", b"DKIM-Signature: \x00\xff;;=\n")
    yield b"dkim-signature: v=1; a=rsa-sha256; d=x; s=y; h=from; bh=; b=\n\n"
    for _ in range(200):
        yield rng.randbytes(rng.randint(1, 3000))
        yield b"DKIM-Signature: " + rng.randbytes(rng.randint(0, 300)) + b"\n\nbody"
    signed = sign(sign(MESSAGE), "ed25519", d="relay.example", length=50)
    yield signed.replace(b"\n\n", b"\n", 1)  # no empty line after the header section
    yield signed.replace(b"\n\n", b"\n \n", 1)  # a whitespace line instead of an empty one
    yield b"X-Filler: y\n" * 20000 + signed  # a huge header section
    value = signature_value(signed)
    for _ in range(300):  # damaged tag lists
        damaged = bytearray(value)
        for _ in range(rng.randint(1, 5)):
            position = rng.randrange(len(damaged))
            damaged[position : position + rng.randint(0, 3)] = rng.choice(
                (b"", b";", b"=", b" ", b"\r\n", b"\n\t", rng.randbytes(2))
            )
        yield signed.replace(value.strip(), bytes(damaged).strip(), 1)
    mails = [corpus.message(r) for r in corpus.records if r["dkim"]["signatures"]][:60]
    for raw in mails:
        for _ in range(5):
            yield raw[: rng.randrange(len(raw))]  # truncated, in the header or in the body


def test_broken_input_never_raises(corpus: Corpus, caplog: pytest.LogCaptureFixture) -> None:
    rng = random.Random(12)
    garbage = ("", "v=DKIM1; p=", "p=" + "A" * 400, "k=ed25519; p=AAAA", "p=MIIB;;", "\x00")
    records = {NAME: record(), key_name(SELECTOR, "relay.example"): record("ed25519")}
    with caplog.at_level(logging.WARNING, logger=verify.__name__):
        for raw in _broken_inputs(corpus):
            assert isinstance(verify_mail(raw, Keys(records)), MailVerdict)
            assert isinstance(verify_mail(raw, corpus.table.answer), MailVerdict)
            assert isinstance(verify_mail(raw, Keys({NAME: rng.choice(garbage)})), MailVerdict)
    assert [r for r in caplog.records if r.name == verify.__name__] == []

"""verify_mail with candidate keys of deleted selectors (D100), and signature_material.

The mails and keys are test_verify's: MESSAGE signed with its keys, DNS from a dict-backed key
source. A candidate counts only when it suits the signature and verifies its header hash.
"""

import base64
import hashlib
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from dkim.util import parse_tag_value

from mailrobbe.dkim.checker import DkimChecker
from mailrobbe.dkim.model import CandidateKey, MailVerdict
from mailrobbe.dkim.verify import key_verifies, signature_material, verify_mail
from mailrobbe.enums import DkimReason, DkimStatus, KeyOrigin
from tests.dkim.test_verify import (
    DOMAIN,
    MESSAGE,
    NAME,
    SELECTOR,
    TIMESTAMP,
    Keys,
    changed_body,
    changed_subject,
    only,
    private_key,
    published,
    record,
    sign,
    signature_value,
)

PASS, CONSISTENT, FAIL, NO_KEY, TEMP_ERROR = (
    DkimStatus.PASS,
    DkimStatus.CONSISTENT,
    DkimStatus.FAIL,
    DkimStatus.NO_KEY,
    DkimStatus.TEMP_ERROR,
)
R = DkimReason


def candidate(
    kind: str = "rsa2048", origin: KeyOrigin = KeyOrigin.RECONSTRUCTED, key_id: int = 7
) -> CandidateKey:
    return CandidateKey(key_id, origin, record(kind))


def check(
    raw: bytes, keys: Keys, *candidates: CandidateKey
) -> tuple[DkimStatus, DkimReason | None, int | None, KeyOrigin | None, int | None]:
    result = only(raw, keys, {NAME: candidates})
    return result.status, result.reason, result.key_id, result.key_origin, result.key_bits


DNS_GIVES_NO_KEY = {
    "not found": Keys(),
    "revoked": Keys({NAME: "v=DKIM1; k=rsa; p="}),
    "timeout": Keys(timeouts=frozenset([NAME])),
    "malformed": Keys({NAME: "v=DKIM1; p"}),
    "unsuitable": Keys(published("ed25519")),
    "too short": Keys(published("rsa512")),
    "another key": Keys(published("rsa1024")),  # signature_mismatch with an intact body
}


@pytest.mark.parametrize("dns", DNS_GIVES_NO_KEY)
@pytest.mark.parametrize(
    ("origin", "status"),
    [
        (KeyOrigin.OBSERVED, PASS),
        (KeyOrigin.DOCUMENTED, PASS),
        (KeyOrigin.RECONSTRUCTED, CONSISTENT),
    ],
)
def test_a_candidate_decides_when_dns_gives_no_key_that_verifies(
    dns: str, origin: KeyOrigin, status: DkimStatus
) -> None:
    raw = sign(MESSAGE)
    assert check(raw, DNS_GIVES_NO_KEY[dns], candidate(origin=origin)) == (
        status,
        None,
        7,
        origin,
        2048,
    )
    # a changed body is a failure whatever the key's origin; with a usable key in DNS it fails
    # before any header is verified, so no candidate is tried
    changed = check(changed_body(raw), DNS_GIVES_NO_KEY[dns], candidate(origin=origin))
    if dns == "another key":
        assert changed == (FAIL, R.BODY_HASH_MISMATCH, None, KeyOrigin.DNS, 1024)
    else:
        assert changed == (FAIL, R.BODY_HASH_MISMATCH, 7, origin, 2048)


def test_results_of_todays_dns_stay_and_name_their_origin() -> None:
    raw = sign(MESSAGE)
    other = candidate("rsa1024")  # verifies nothing here
    assert check(raw, Keys(published()), other) == (PASS, None, None, KeyOrigin.DNS, 2048)
    # with a key in DNS a changed body fails before the header is verified: no candidate
    assert check(changed_body(raw), Keys(published()), candidate()) == (
        FAIL,
        R.BODY_HASH_MISMATCH,
        None,
        KeyOrigin.DNS,
        2048,
    )
    # no candidate verifies: the result of DNS, with its origin where it rests on a key
    expected = {
        "not found": (NO_KEY, R.KEY_MISMATCH, None, None, None),
        "revoked": (NO_KEY, R.KEY_MISMATCH, None, None, None),
        "timeout": (TEMP_ERROR, R.DNS_TIMEOUT, None, None, None),
        "malformed": (FAIL, R.KEY_MALFORMED, None, KeyOrigin.DNS, None),
        "unsuitable": (FAIL, R.KEY_MALFORMED, None, KeyOrigin.DNS, 256),
        "too short": (FAIL, R.KEY_TOO_SHORT, None, KeyOrigin.DNS, 512),
        "another key": (FAIL, R.SIGNATURE_MISMATCH, None, KeyOrigin.DNS, 1024),
    }
    for dns, keys in DNS_GIVES_NO_KEY.items():
        assert check(raw, keys, other) == expected[dns], dns
    # a changed header breaks the signature for every key
    assert check(changed_subject(raw), Keys(), candidate()) == expected["not found"]


def test_without_candidates_no_key_keeps_its_reason() -> None:
    raw = sign(MESSAGE)
    assert check(raw, Keys()) == (NO_KEY, R.KEY_NOT_FOUND, None, None, None)
    assert only(raw, Keys(), {"other._domainkey.example": [candidate()]}).reason is (
        R.KEY_NOT_FOUND
    )


def test_candidates_that_do_not_fit_are_ignored() -> None:
    raw = sign(MESSAGE, "rsa512")
    # the 512-bit key verifies, but is too short to count
    assert check(raw, Keys(), candidate("rsa512")) == (NO_KEY, R.KEY_MISMATCH, None, None, None)
    raw = sign(MESSAGE)
    wrong_type = candidate("ed25519", KeyOrigin.OBSERVED, key_id=1)
    other_key = candidate("rsa1024", KeyOrigin.DOCUMENTED, key_id=2)
    only_sha1 = CandidateKey(3, KeyOrigin.DOCUMENTED, record(h="sha1"))
    fitting = candidate(key_id=4)
    assert check(raw, Keys(), wrong_type, other_key, only_sha1, fitting) == (
        CONSISTENT,
        None,
        4,
        KeyOrigin.RECONSTRUCTED,
        2048,
    )
    assert check(raw, Keys(), CandidateKey(5, KeyOrigin.OBSERVED, "v=DKIM1; p=")) == (
        NO_KEY,
        R.KEY_MISMATCH,
        None,
        None,
        None,
    )


def test_ed25519_candidates_and_names_in_any_case() -> None:
    raw = sign(MESSAGE, "ed25519", d="NordWind.Example", s="S1")
    assert check(raw, Keys(), candidate("ed25519", KeyOrigin.OBSERVED)) == (
        PASS,
        None,
        7,
        KeyOrigin.OBSERVED,
        256,
    )


def test_consistent_ranks_between_pass_and_temp_error() -> None:
    raw = sign(sign(MESSAGE), d="relay.example", s="r1")
    verdict = verify_mail(
        raw, Keys(timeouts=frozenset(["r1._domainkey.relay.example"])), {NAME: [candidate()]}
    )
    assert [s.status for s in verdict.signatures] == [TEMP_ERROR, CONSISTENT]
    assert verdict.status is CONSISTENT
    dns = verify_mail(raw, Keys(published()))
    assert MailVerdict((*verdict.signatures, *dns.signatures)).status is PASS
    rows = verdict.result_rows(1, datetime(2026, 10, 21, tzinfo=UTC))
    assert [(row["key_id"], row["key_origin"]) for row in rows] == [
        (None, None),
        (7, "reconstructed"),
    ]


# signature_material ---------------------------------------------------------------------------


def _header_hash_and_signature(raw: bytes) -> tuple[bytes, bytes]:
    """b= of the topmost signature and the digest it signs, recovered with the private key."""
    signature = base64.b64decode(parse_tag_value(signature_value(raw))[b"b"])
    key = private_key("rsa2048")
    assert isinstance(key, rsa.RSAPrivateKey)
    numbers = key.private_numbers()
    encoded = pow(int.from_bytes(signature), 65537, numbers.public_numbers.n)
    digest = encoded.to_bytes(256)[-32:]
    key.public_key().verify(signature, digest, padding.PKCS1v15(), Prehashed(hashes.SHA256()))
    return digest, signature


def test_signature_material_is_what_b_signs() -> None:
    raw = sign(sign(MESSAGE, a="rsa-sha1"), d="relay.example", s="r1", t="1234567890")
    relay, author = signature_material(raw)
    digest, signature = _header_hash_and_signature(raw)
    assert (relay.index, relay.name, relay.key_type, relay.hash_name) == (
        0,
        "r1._domainkey.relay.example",
        "rsa",
        "sha256",
    )
    assert (relay.header_hash, relay.signature, relay.body_hash_ok) == (digest, signature, True)
    assert relay.signed_at is not None and relay.signed_at.timestamp() == 1234567890
    assert (author.index, author.name, author.hash_name) == (1, NAME, "sha1")
    assert author.signed_at is not None and author.signed_at.timestamp() == TIMESTAMP
    assert len(author.header_hash) == hashlib.sha1().digest_size
    for material in (relay, author):
        assert key_verifies(record(), material)
        assert not key_verifies(record("rsa1024"), material)
        assert not key_verifies(record("rsa512"), material)
        assert not key_verifies(record(h="sha512"), material)
    changed = signature_material(changed_body(sign(MESSAGE)))
    assert [m.body_hash_ok for m in changed] == [False]
    assert key_verifies(record(), changed[0])  # the header hash does not depend on the body


def test_signature_material_leaves_out_what_cannot_be_verified() -> None:
    raw = sign(sign(MESSAGE, a="rsa-sha512"), h="to:subject", d=DOMAIN, s=SELECTOR)
    assert signature_material(raw) == []
    raw = sign(sign(MESSAGE, v="2"), "ed25519")
    [material] = signature_material(raw)
    assert (material.index, material.key_type) == (0, "ed25519")
    assert key_verifies(record("ed25519"), material)
    assert signature_material(MESSAGE) == []
    assert signature_material(b" folded\n" + sign(MESSAGE)) == []
    assert signature_material(b"") == []


def test_the_checker_hands_its_candidates_to_every_check() -> None:
    raw = sign(MESSAGE)
    checker = DkimChecker(Keys(), {NAME: [candidate(origin=KeyOrigin.DOCUMENTED)]})
    [result] = checker.check(raw).signatures
    assert (result.status, result.key_id, result.key_origin) == (PASS, 7, KeyOrigin.DOCUMENTED)
    [result] = DkimChecker(Keys()).check(raw).signatures
    assert (result.status, result.reason) == (NO_KEY, R.KEY_NOT_FOUND)

"""keys.identity and keys.store: one key per name and content, its origin the strongest evidence."""

import base64
import functools
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.db.models import DkimKey, DkimKeyEvidence, DkimKeyLookup
from mailrobbe.dkim.keys.identity import key_identity, rsa_record, split_key_name
from mailrobbe.dkim.keys.store import (
    TOOL_VERSION,
    Evidence,
    load_candidates,
    save_evidence,
    save_lookup,
)
from mailrobbe.enums import KeyLookupSource, KeyOrigin, LookupOutcome

NAME = "s2019._domainkey.nordwind.example"


@functools.cache
def _rsa(bits: int = 1024) -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def _bare_rsa_record(key: rsa.RSAPrivateKey) -> str:
    """p= as a bare RSAPublicKey (PKCS#1), which some publishers use."""
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.PKCS1
    )
    return "v=DKIM1; k=rsa; p=" + base64.b64encode(der).decode()


def test_rsa_identity_is_the_same_for_both_forms_of_p() -> None:
    numbers = _rsa().public_key().public_numbers()
    made = rsa_record(numbers.n, numbers.e)
    spki = key_identity(made)
    bare = key_identity(_bare_rsa_record(_rsa()))
    assert spki is not None and bare is not None
    assert spki == bare
    assert (spki.key_type, spki.bits, spki.modulus, spki.exponent) == (
        "rsa",
        1024,
        numbers.n,
        65537,
    )
    # whitespace in p=, as TXT records split over several strings come back joined with it
    spaced = made.replace("p=", "p= ").replace("AQAB", " AQ AB")
    assert key_identity(spaced) == spki


def test_ed25519_identity_and_records_without_a_key() -> None:
    raw = (
        ed25519.Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    identity = key_identity("v=DKIM1; k=ed25519; p=" + base64.b64encode(raw).decode())
    assert identity is not None and identity.key_type == "ed25519" and identity.bits == 256
    assert key_identity("v=DKIM1; k=rsa; p=") is None  # revoked
    assert key_identity("v=DKIM1; k=rsa; p=bm8ga2V5") is None
    assert key_identity("not a record") is None


def test_split_key_name() -> None:
    assert split_key_name("S2019._DomainKey.Nordwind.Example.") == ("s2019", "nordwind.example")
    assert split_key_name("nordwind.example") is None
    assert split_key_name("._domainkey.nordwind.example") is None
    assert split_key_name("a._domainkey.b._domainkey.c") is None


@pytest.mark.db
async def test_one_key_per_content_with_the_strongest_origin(db_session: AsyncSession) -> None:
    numbers = _rsa().public_key().public_numbers()
    record = rsa_record(numbers.n, numbers.e)
    reconstruction = await save_lookup(
        db_session, KeyLookupSource.RECONSTRUCTION, NAME, LookupOutcome.FOUND, name=NAME
    )
    first = await save_evidence(
        db_session,
        reconstruction,
        NAME,
        record,
        Evidence(KeyOrigin.RECONSTRUCTED, details={"exponent": 65537}),
    )
    archive = await save_lookup(
        db_session,
        KeyLookupSource.ZKEMAIL,
        "https://archive.zk.email/api/key?domain=nordwind.example",
        LookupOutcome.FOUND,
        domain="nordwind.example",
        raw=b"[]",
        raw_type="application/json",
        http_status=200,
    )
    seen = datetime(2019, 3, 1, tzinfo=UTC)
    # the same key in the other form of p=, under the name in capitals
    second = await save_evidence(
        db_session,
        archive,
        NAME.upper(),
        _bare_rsa_record(_rsa()),
        Evidence(KeyOrigin.OBSERVED, observed_from=seen, reference="https://archive.zk.email"),
    )
    again = await save_evidence(
        db_session, archive, NAME, record, Evidence(KeyOrigin.OBSERVED, observed_from=seen)
    )
    # a weaker origin later does not lower it
    weaker = await save_evidence(
        db_session, reconstruction, NAME, record, Evidence(KeyOrigin.RECONSTRUCTED)
    )
    assert first is not None and first == second == again == weaker

    key = await db_session.get_one(DkimKey, first)
    assert (key.name, key.domain, key.selector, key.origin, key.record) == (
        NAME,
        "nordwind.example",
        "s2019",
        KeyOrigin.OBSERVED,
        record,
    )
    evidence = await db_session.scalar(
        select(func.count()).select_from(DkimKeyEvidence).where(DkimKeyEvidence.key_id == first)
    )
    assert evidence == 2
    lookup = await db_session.get_one(DkimKeyLookup, archive)
    assert lookup.raw_sha256 == (
        "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"  # SHA-256 of "[]"
    )
    assert lookup.tool_version == TOOL_VERSION

    candidates = await load_candidates(db_session)
    assert [(c.key_id, c.origin) for c in candidates[NAME]] == [(first, KeyOrigin.OBSERVED)]


@pytest.mark.db
async def test_no_key_without_a_usable_record_and_factorable_keys_are_no_candidates(
    db_session: AsyncSession,
) -> None:
    lookup = await save_lookup(
        db_session, KeyLookupSource.MANUAL, NAME, LookupOutcome.FOUND, name=NAME
    )
    manual = Evidence(KeyOrigin.DOCUMENTED, reference="Zonendatei", editor="Eva")
    assert await save_evidence(db_session, lookup, NAME, "v=DKIM1; p=", manual) is None
    numbers = _rsa().public_key().public_numbers()
    record = rsa_record(numbers.n, numbers.e)
    assert await save_evidence(db_session, lookup, "nordwind.example", record, manual) is None

    other = _rsa(2048).public_key().public_numbers()
    kept = await save_evidence(db_session, lookup, NAME, record, manual)
    factorable = await save_evidence(db_session, lookup, NAME, rsa_record(other.n, other.e), manual)
    assert kept is not None and factorable is not None
    (await db_session.get_one(DkimKey, factorable)).factorable = True
    await db_session.flush()
    candidates = await load_candidates(db_session)
    assert [candidate.key_id for candidate in candidates[NAME]] == [kept]

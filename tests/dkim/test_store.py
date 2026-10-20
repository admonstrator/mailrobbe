"""store.py against the migrated schema: dkim_result, dns_cache and mail.dkim_status."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.db.models import DkimResult, Mail, MboxFile
from mailrobbe.dkim.model import (
    FOUND_TTL,
    NOT_FOUND_TTL,
    TEMP_ERROR_TTL,
    DnsAnswer,
    MailVerdict,
    SignatureResult,
)
from mailrobbe.dkim.store import load_dns_cache, save_verdicts, upsert_dns_cache
from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus

pytestmark = pytest.mark.db

CHECKED_AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
FETCHED_AT = datetime(2026, 10, 19, 8, 30, tzinfo=UTC)


def _signature(
    status: DkimStatus, reason: DkimReason | None = None, domain: str = "nordwind.example"
) -> SignatureResult:
    return SignatureResult(
        status=status,
        reason=reason,
        domain=domain,
        selector="s1",
        algorithm="rsa-sha256",
        key_bits=2048 if status is DkimStatus.PASS else None,
        signed_headers=("from", "to", "subject", "date"),
        body_hash_ok=status is DkimStatus.PASS,
        signed_at=datetime(2019, 3, 4, 9, 30, tzinfo=UTC),
        aligned=True,
        dns_cached=False,
    )


TWO_SIGNATURES = MailVerdict(
    (
        _signature(DkimStatus.FAIL, DkimReason.BODY_HASH_MISMATCH, "lists.verband.example"),
        _signature(DkimStatus.PASS),
    )
)
NO_KEY = MailVerdict((_signature(DkimStatus.NO_KEY, DkimReason.KEY_NOT_FOUND),))
TEMP_ERROR = MailVerdict((_signature(DkimStatus.TEMP_ERROR, DkimReason.DNS_TIMEOUT),))


async def _mails(session: AsyncSession, count: int) -> list[Mail]:
    mbox_file = MboxFile(path="mbox-0001.mbox", size_bytes=4096)
    session.add(mbox_file)
    await session.flush()
    mails = [
        Mail(mbox_file_id=mbox_file.id, byte_offset=index * 100, byte_length=100, raw_sha256="0")
        for index in range(count)
    ]
    session.add_all(mails)
    await session.flush()
    for mail in mails:
        await session.refresh(mail)  # loaded, as the API would have them
    return mails


async def _results(session: AsyncSession, mail: Mail) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(*DkimResult.__table__.columns)
        .where(DkimResult.mail_id == mail.id)
        .order_by(DkimResult.signature_index)
    )
    return [dict(row._mapping) for row in rows]


async def _status(session: AsyncSession, mail: Mail) -> DkimStatus | None:
    return await session.scalar(select(Mail.dkim_status).where(Mail.id == mail.id))


async def test_save_verdicts_writes_every_signature_and_the_mail_status(
    db_session: AsyncSession,
) -> None:
    signed, missing, unsigned, untouched = await _mails(db_session, 4)
    verdicts = [(signed.id, TWO_SIGNATURES), (missing.id, NO_KEY), (unsigned.id, MailVerdict())]
    await save_verdicts(db_session, verdicts, CHECKED_AT)

    assert await _results(db_session, signed) == TWO_SIGNATURES.result_rows(signed.id, CHECKED_AT)
    assert await _results(db_session, missing) == NO_KEY.result_rows(missing.id, CHECKED_AT)
    assert await _results(db_session, unsigned) == []
    assert await _status(db_session, signed) is DkimStatus.PASS
    assert await _status(db_session, missing) is DkimStatus.NO_KEY
    assert await _status(db_session, unsigned) is DkimStatus.UNSIGNED
    assert await _status(db_session, untouched) is None
    # Through a session the loaded objects follow the update.
    assert (signed.dkim_status, unsigned.dkim_status) == (DkimStatus.PASS, DkimStatus.UNSIGNED)


async def test_save_verdicts_replaces_earlier_results(db_session: AsyncSession) -> None:
    first, second = await _mails(db_session, 2)
    await save_verdicts(db_session, [(first.id, TWO_SIGNATURES), (second.id, NO_KEY)], CHECKED_AT)

    # Also through a plain connection; a mail given twice keeps its last verdict.
    before = datetime.now(UTC)
    connection = await db_session.connection()
    await save_verdicts(connection, [(first.id, NO_KEY), (first.id, TEMP_ERROR)])
    rows = await _results(db_session, first)
    assert len(rows) == 1  # no stale second signature
    checked_at = rows[0]["checked_at"]
    assert before - timedelta(seconds=1) <= checked_at <= datetime.now(UTC)
    assert rows == TEMP_ERROR.result_rows(first.id, checked_at)
    assert await _status(db_session, first) is DkimStatus.TEMP_ERROR
    assert await _results(db_session, second) == NO_KEY.result_rows(second.id, CHECKED_AT)

    await save_verdicts(db_session, [(first.id, MailVerdict())])
    assert await _results(db_session, first) == []
    assert await _status(db_session, first) is DkimStatus.UNSIGNED

    await save_verdicts(db_session, [])
    assert await _status(db_session, second) is DkimStatus.NO_KEY


def _answer(
    name: str,
    status: DnsStatus,
    record: str | None = None,
    ttl: int | None = None,
    reason: DkimReason | None = None,
) -> DnsAnswer:
    default_ttl = {
        DnsStatus.FOUND: FOUND_TTL,
        DnsStatus.NOT_FOUND: NOT_FOUND_TTL,
        DnsStatus.TEMP_ERROR: TEMP_ERROR_TTL,
    }
    return DnsAnswer(
        name, status, record, FETCHED_AT, default_ttl[status] if ttl is None else ttl, reason
    )


async def test_dns_cache_round_trip(db_session: AsyncSession) -> None:
    answers = [
        _answer("s1._domainkey.nordwind.example", DnsStatus.FOUND, "v=DKIM1; k=rsa; p=AAAA"),
        _answer("old._domainkey.nordwind.example", DnsStatus.NOT_FOUND),
        _answer("s1._domainkey.slow.example", DnsStatus.TEMP_ERROR, reason=DkimReason.DNS_OFFLINE),
    ]
    await upsert_dns_cache(db_session, answers)

    loaded = sorted(await load_dns_cache(db_session), key=lambda answer: answer.name)
    assert [answer.name for answer in loaded] == [
        "old._domainkey.nordwind.example",
        "s1._domainkey.nordwind.example",
        "s1._domainkey.slow.example",
    ]
    missing, found, slow = loaded
    assert found == DnsAnswer(
        "s1._domainkey.nordwind.example",
        DnsStatus.FOUND,
        "v=DKIM1; k=rsa; p=AAAA",
        FETCHED_AT,
        FOUND_TTL,
        None,
        from_cache=True,
    )
    assert found.fetched_at.tzinfo is not None
    assert (missing.status, missing.record, missing.ttl, missing.reason) == (
        DnsStatus.NOT_FOUND,
        None,
        NOT_FOUND_TTL,
        None,
    )
    # The reason is not stored: a cached temp_error reads back as a timeout.
    assert (slow.status, slow.reason, slow.from_cache) == (
        DnsStatus.TEMP_ERROR,
        DkimReason.DNS_TIMEOUT,
        True,
    )


async def test_upsert_dns_cache_replaces_by_name(db_session: AsyncSession) -> None:
    name = "s1._domainkey.nordwind.example"
    await upsert_dns_cache(db_session, [_answer(name, DnsStatus.TEMP_ERROR)])
    later = FETCHED_AT + timedelta(hours=1)
    await upsert_dns_cache(
        await db_session.connection(),  # also through a plain connection
        [
            _answer(name, DnsStatus.NOT_FOUND),
            DnsAnswer(name, DnsStatus.FOUND, "v=DKIM1; p=BBBB", later, FOUND_TTL),
            _answer("s2._domainkey.nordwind.example", DnsStatus.FOUND, "v=DKIM1; p=CCCC", ttl=0),
        ],
    )
    await upsert_dns_cache(db_session, [])

    (answer,) = await load_dns_cache(db_session)
    assert (answer.name, answer.status, answer.record, answer.fetched_at) == (
        name,
        DnsStatus.FOUND,
        "v=DKIM1; p=BBBB",
        later,
    )

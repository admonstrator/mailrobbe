"""global_stats (D19): the refresh, the readers, finalize, and the API's lazy refresh.

The lock is tested in tests/api/test_stats.py: db_session would hold it until its rollback.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import aggregates
from mailrobbe.enums import DkimStatus
from mailrobbe.importer.finalize import finalize
from mailrobbe.importer.store import Batch, Store
from tests.importer.doubles import (
    FakeVerdict,
    add_mbox_file,
    address,
    make_mail,
    make_record,
    message,
)

pytestmark = pytest.mark.db

ANNA, ANNE, BERT = address("anna@a.example"), address("anne@a.example"), address("bert@b.example")
CARL, DORA = address("carl@sub.b.example"), address("dora@d.example")


async def _store(session: AsyncSession, first_index: int = 0, extra: int = 0) -> None:
    """Four mails (and `extra` more without a date) from a.example and b.example senders."""
    file_id = await add_mbox_file(session, f"{first_index}.mbox")
    mails = [
        (make_mail(date_utc=_day(2020, 1, 1), sender=(ANNA,), to=(BERT,)), "pass"),
        (make_mail(date_utc=_day(2021, 6, 1), sender=(BERT,), to=(ANNA,), cc=(CARL,)), "fail"),
        (make_mail(sender=(ANNA,), to=(DORA,)), None),
        # two senders of one domain: the mail counts once for a.example
        (make_mail(date_utc=_day(2019, 3, 3), sender=(ANNA, ANNE), to=(CARL,)), "unsigned"),
    ]
    mails += [(make_mail(sender=(DORA,)), None)] * extra
    batch = Batch()
    offset = 0
    for index, (mail, status) in enumerate(mails, first_index):
        record = make_record(offset, message(index))
        batch.add(record, mail, None if status is None else FakeVerdict(DkimStatus(status)))
        offset += record.byte_length
    await Store().write(session, file_id, batch)


def _day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


async def _merge_anne(session: AsyncSession) -> None:
    await session.execute(
        text(
            "UPDATE person SET merged_into = (SELECT id FROM person WHERE canonical_email = "
            "'anna@a.example') WHERE canonical_email = 'anne@a.example'"
        )
    )
    await session.commit()


async def _age(session: AsyncSession) -> None:
    await session.execute(text("UPDATE global_stats SET updated_at = updated_at - interval '1h'"))
    await session.commit()


async def test_refresh_computes_every_figure(db_session: AsyncSession) -> None:
    assert await aggregates.read_global_stats(db_session) is None
    await _store(db_session)
    await _merge_anne(db_session)

    await aggregates.refresh_global_stats(db_session)
    figures = await aggregates.read_global_stats(db_session)

    assert figures is not None
    assert figures.mails == 4
    assert figures.dkim == {
        "pass": 1,
        "fail": 1,
        "no_key": 0,
        "unsigned": 1,
        "temp_error": 0,
        aggregates.UNCHECKED: 1,
    }
    assert figures.persons == 4  # anne is merged into anna
    assert figures.domains == 4  # a.example, b.example, sub.b.example, d.example
    assert (figures.date_min, figures.date_max) == (_day(2019, 3, 3), _day(2021, 6, 1))
    assert figures.sender_domain_count == 2
    assert figures.mbox_files == 1
    assert figures.updated_at == await db_session.scalar(select(func.now()))


async def test_sender_domains_by_mails_with_search_and_limit(db_session: AsyncSession) -> None:
    await _store(db_session)
    await aggregates.refresh_global_stats(db_session)

    assert await aggregates.read_sender_domains(db_session) == [("a.example", 3), ("b.example", 1)]
    assert await aggregates.read_sender_domains(db_session, q=" B.Ex ") == [("b.example", 1)]
    assert await aggregates.read_sender_domains(db_session, limit=1) == [("a.example", 3)]
    assert await aggregates.read_sender_domains(db_session, q="nowhere") == []


async def test_finalize_writes_global_stats(db_session: AsyncSession) -> None:
    await _store(db_session)
    await finalize(db_session)

    figures = await aggregates.read_global_stats(db_session)
    assert figures is not None
    assert (figures.mails, figures.persons, figures.sender_domain_count) == (4, 5, 2)


async def test_api_refreshes_missing_and_stale_figures_only(db_session: AsyncSession) -> None:
    await _store(db_session)
    await db_session.commit()
    figures = await aggregates.current_global_stats(db_session, max_age=300)
    assert figures.mails == 4  # missing: computed

    await _store(db_session, first_index=10, extra=2)
    assert (await aggregates.current_global_stats(db_session, max_age=300)).mails == 4  # fresh

    await _age(db_session)
    assert (await aggregates.current_global_stats(db_session, max_age=300)).mails == 10

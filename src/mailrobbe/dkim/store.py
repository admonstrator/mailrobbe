"""DKIM results and the DNS cache in PostgreSQL (dkim_result, dns_cache, mail.dkim_status).

The functions take an AsyncSession or AsyncConnection and run inside the caller's transaction;
they never commit. The importer writes result rows itself (MailVerdict.result_rows) and uses
load_dns_cache/upsert_dns_cache; the recheck command and the API use save_verdicts.

Every call is a handful of set-based statements whatever the number of mails or answers: mail
ids go in as one array parameter, rows as one executemany. Through a session the statements are
ORM-enabled, so loaded Mail and DkimResult objects follow the changes.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, ColumnElement, any_, delete, insert, literal, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.db.models import DkimResult, DnsCache, Mail
from mailrobbe.dkim.keys.store import keep_dns_keys
from mailrobbe.dkim.model import DnsAnswer, MailVerdict
from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus

Executor = AsyncSession | AsyncConnection


async def load_dns_cache(db: Executor) -> list[DnsAnswer]:
    """Every dns_cache row as an answer with from_cache=True (temp_error with dns_timeout)."""
    rows = await db.execute(
        select(DnsCache.name, DnsCache.status, DnsCache.record, DnsCache.fetched_at, DnsCache.ttl)
    )
    return [
        DnsAnswer(
            name=name,
            status=status,
            record=record,
            fetched_at=fetched_at,
            ttl=ttl,
            reason=DkimReason.DNS_TIMEOUT if status is DnsStatus.TEMP_ERROR else None,
            from_cache=True,
        )
        for name, status, record, fetched_at, ttl in rows
    ]


async def upsert_dns_cache(db: Executor, answers: Iterable[DnsAnswer]) -> None:
    """Insert or replace dns_cache rows by name; answers with ttl 0 are skipped.

    Of several answers for one name only the last is written: one statement cannot update the
    same row twice. The key of every found answer is kept beyond the cache row (D106,
    keys.store.keep_dns_keys), so a later not found or error replaces the row, never the key.
    """
    latest = {answer.name: answer for answer in answers if answer.ttl > 0}
    if not latest:
        return
    statement = postgresql.insert(DnsCache)
    statement = statement.on_conflict_do_update(
        index_elements=[DnsCache.name],
        set_={
            "record": statement.excluded.record,
            "status": statement.excluded.status,
            "fetched_at": statement.excluded.fetched_at,
            "ttl": statement.excluded.ttl,
        },
    )
    rows = [
        {
            "name": answer.name,
            "record": answer.record,
            "status": answer.status,
            "fetched_at": answer.fetched_at,
            "ttl": answer.ttl,
        }
        for answer in latest.values()
    ]
    await db.execute(statement, rows)
    # After the rows: their locks keep concurrent batches from keeping one answer twice.
    await keep_dns_keys(db, latest.values())


async def save_verdicts(
    db: Executor, verdicts: Iterable[tuple[int, MailVerdict]], checked_at: datetime | None = None
) -> None:
    """Replace the dkim_result rows of each mail and set mail.dkim_status.

    checked_at defaults to the current time, the same for every row of the call.
    """
    latest = dict(verdicts)  # a mail given twice keeps its last verdict
    if not latest:
        return
    checked_at = checked_at or datetime.now(UTC)
    await db.execute(
        delete(DkimResult)
        .where(DkimResult.mail_id == _any_id(latest))
        .execution_options(synchronize_session="fetch")
    )
    rows: list[dict[str, Any]] = []
    by_status: defaultdict[DkimStatus, list[int]] = defaultdict(list)
    for mail_id, verdict in latest.items():
        rows.extend(verdict.result_rows(mail_id, checked_at))
        by_status[verdict.status].append(mail_id)
    if rows:
        await db.execute(insert(DkimResult), rows)
    for status, mail_ids in by_status.items():
        await db.execute(
            update(Mail)
            .where(Mail.id == _any_id(mail_ids))
            .values(dkim_status=status)
            .execution_options(synchronize_session="fetch")
        )


def _any_id(ids: Iterable[int]) -> ColumnElement[Any]:
    """`= ANY($1::bigint[])`: one parameter for any number of ids."""
    return any_(literal(list(ids), postgresql.ARRAY(BigInteger)))

"""Aggregation tables (SPEC 3.3, 6.3): figures read by the UI instead of counting mails.

refresh_aggregates recomputes all of them in dependency order (D33): the edges between persons
(graph.edges, milestone 6), the person figures that count them as contacts and the alias
suggestions (persons, milestone 5), then global_stats. It runs after each import
(importer.finalize) and after `mailrobbe dkim`, and for the persons concerned after a merge.

global_stats holds the whole-archive figures (D19), one row per key: mails, DKIM counts, persons,
domains, date range, every sender domain with its mails and the number of MBOX files. They are
recomputed after each import (importer.finalize), after `mailrobbe dkim` and by the API when they
are older than MAILROBBE_STATS_MAX_AGE.

refresh_global_stats and the readers run in the caller's transaction and never commit;
current_global_stats manages its own short transaction for the API.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.db.models import GlobalStats
from mailrobbe.enums import DkimStatus
from mailrobbe.graph.edges import refresh_edges
from mailrobbe.persons.stats import refresh_person_stats
from mailrobbe.persons.suggestions import refresh_alias_suggestions

Executor = AsyncSession | AsyncConnection

UNCHECKED = "unchecked"  # the DKIM count key of mails not checked yet (dkim_status NULL)
# Transaction-level advisory lock: one refresh at a time; API requests do not wait for it.
_LOCK_KEY = int.from_bytes(b"mrglobal", "big")
_FIGURES = ("mails", "dkim", "persons", "domains", "date_min", "date_max", "mbox_files")
_SENDER_DOMAINS = "sender_domains"  # [{"domain", "mails"}], most mails first; read in SQL
_SENDER_DOMAIN_COUNT = "sender_domain_count"
_KEYS = (*_FIGURES, _SENDER_DOMAINS, _SENDER_DOMAIN_COUNT)

_DKIM_COUNTS = text("SELECT dkim_status::text, count(*) FROM mail GROUP BY dkim_status")
_DATES = text("SELECT min(date_utc), max(date_utc) FROM mail")
_PERSONS = text(
    "SELECT count(*) FILTER (WHERE merged_into IS NULL), count(DISTINCT domain) FROM person"
)
# A mail counts once per sender domain, as the sender_domain filter of the mail list counts it.
_SENDER_COUNTS = text("""
    SELECT s.domain, count(DISTINCT p.mail_id) AS mails
    FROM participation p JOIN person s ON s.id = p.person_id
    WHERE p.role = 'from'
    GROUP BY s.domain
    ORDER BY mails DESC, s.domain
""")
_STATE = text("""
    SELECT count(*), bool_and(updated_at > now() - make_interval(secs => :max_age))
    FROM global_stats WHERE key = ANY(:keys)
""")
_DOMAINS = text("""
    SELECT d.value ->> 'domain', (d.value ->> 'mails')::bigint
    FROM global_stats g CROSS JOIN LATERAL jsonb_array_elements(g.value) WITH ORDINALITY AS d
    WHERE g.key = 'sender_domains' AND strpos(d.value ->> 'domain', :q) > 0
    ORDER BY d.ordinality
    LIMIT :limit
""")


@dataclass(frozen=True, slots=True)
class GlobalFigures:
    """The global_stats rows apart from the sender domains themselves."""

    mails: int
    dkim: dict[str, int]  # every DkimStatus value and UNCHECKED
    persons: int  # not merged into another person
    domains: int  # distinct domains of all addresses
    date_min: datetime | None
    date_max: datetime | None
    sender_domain_count: int
    mbox_files: int
    updated_at: datetime  # when they were computed


async def refresh_aggregates(db: Executor, persons: Collection[int] | None = None) -> None:
    """Every aggregation table; persons limits all but global_stats to these persons (D33)."""
    await refresh_edges(db, persons)
    await refresh_person_stats(db, persons)
    await refresh_alias_suggestions(db, persons)
    await refresh_global_stats(db)


async def refresh_global_stats(db: Executor) -> None:
    """Recompute every global_stats row; waits while another refresh holds the lock."""
    await db.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))
    await _compute(db)


async def current_global_stats(session: AsyncSession, max_age: float) -> GlobalFigures:
    """The figures for an API request, recomputed first when missing or older than max_age.

    Runs in its own transaction, so the session must not be in one. Of concurrent requests
    that find the figures stale only one recomputes them; the others serve the stored ones, or
    wait for that one when nothing is stored yet.
    """
    async with session.begin():
        complete, fresh = await _state(session, max_age)
        if not fresh:
            if complete:
                locked = await session.scalar(select(func.pg_try_advisory_xact_lock(_LOCK_KEY)))
            else:  # nothing to serve yet: wait for a refresh that may be running
                await session.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))
                locked = True
            if locked and not (await _state(session, max_age))[1]:  # not refreshed meanwhile
                await _compute(session)
        figures = await read_global_stats(session)
    assert figures is not None, "global_stats are complete after a refresh"
    return figures


async def read_global_stats(db: Executor) -> GlobalFigures | None:
    """The stored figures; None when they were never computed."""
    keys = (*_FIGURES, _SENDER_DOMAIN_COUNT)
    rows = await db.execute(
        select(GlobalStats.key, GlobalStats.value, GlobalStats.updated_at).where(
            GlobalStats.key.in_(keys)
        )
    )
    values: dict[str, Any] = {}
    updated_at: datetime | None = None
    for key, value, updated in rows:
        values[key] = value
        updated_at = updated if updated_at is None else min(updated_at, updated)
    if len(values) < len(keys) or updated_at is None:
        return None
    return GlobalFigures(
        mails=values["mails"],
        dkim=values["dkim"],
        persons=values["persons"],
        domains=values["domains"],
        date_min=_timestamp(values["date_min"]),
        date_max=_timestamp(values["date_max"]),
        sender_domain_count=values[_SENDER_DOMAIN_COUNT],
        mbox_files=values["mbox_files"],
        updated_at=updated_at,
    )


async def read_sender_domains(db: Executor, q: str = "", limit: int = 100) -> list[tuple[str, int]]:
    """Sender domains with their mails, most first; only those containing q (any case)."""
    rows = await db.execute(_DOMAINS, {"q": q.strip().lower(), "limit": limit})
    return [(domain, mails) for domain, mails in rows]


async def _compute(db: Executor) -> None:
    dkim = {status.value: 0 for status in DkimStatus} | {UNCHECKED: 0}
    for status, count in await db.execute(_DKIM_COUNTS):
        dkim[status or UNCHECKED] = count
    date_min, date_max = (await db.execute(_DATES)).one()
    persons, domains = (await db.execute(_PERSONS)).one()
    senders = [
        {"domain": domain, "mails": mails} for domain, mails in await db.execute(_SENDER_COUNTS)
    ]
    values: dict[str, Any] = {
        "mails": sum(dkim.values()),
        "dkim": dkim,
        "persons": persons,
        "domains": domains,
        "date_min": None if date_min is None else date_min.isoformat(),
        "date_max": None if date_max is None else date_max.isoformat(),
        "mbox_files": await db.scalar(text("SELECT count(*) FROM mbox_file")),
        _SENDER_DOMAINS: senders,
        _SENDER_DOMAIN_COUNT: len(senders),
    }
    statement = postgresql.insert(GlobalStats).values(
        [{"key": key, "value": value} for key, value in values.items()]
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[GlobalStats.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
    )


async def _state(db: Executor, max_age: float) -> tuple[bool, bool]:
    """Whether every global_stats row exists, and whether they are also younger than max_age."""
    count, young = (
        await db.execute(_STATE, {"max_age": float(max_age), "keys": list(_KEYS)})
    ).one()
    complete = count == len(_KEYS)
    return complete, complete and bool(young)


def _timestamp(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)

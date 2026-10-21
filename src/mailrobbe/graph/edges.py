"""edge, edge_year and person.kind, recomputed from the imported mails (D36, D39).

Edges join root persons (coalesce(person.merged_into, person.id)) and count mails that are no
duplicates: the sender to each To/Bcc recipient in mails_a_to_b or mails_b_to_a, to each Cc
recipient in mails_cc, once per mail and pair (To before Cc), never a person to itself and never
recipients among themselves; the pass_* counters count the same for mails whose DKIM check
passed. edge_year holds the same counters per UTC year of date_utc; undated mails are only in
edge. global_stats gets a row "edges" with the number of pairs and the time of the refresh.

person.kind marks the root persons that are no humans (D39). automated: an address with a
noreply-style local part; or more than half of the person's mails sent by a program
(mail.automated) or in bulk (a List-Id naming none of the recipients); or at least
AUTOMATED_MIN_SENT mails, none a reply or a list post, and never one received. list, when not
automated: it received a mail whose List-Id is its own address (local.domain); or it never sent
a mail, at least LIST_MIN_SENDERS sender addresses wrote to it as the only recipient, and none
of its mails came through another list or newsletter (distribution lists that a mail server
expands carry no List-Id; a person who never writes is mostly one recipient among others).
Every feature belongs to the person's own addresses, so a merge elsewhere never changes its
kind.

Everything is computed into temporary tables first; then only rows that differ are inserted,
updated or deleted, so readers of edge are never blocked and a refresh without changes writes
nothing but the global_stats row. A partial refresh (persons given, after a merge or split)
counts the pairs touching those persons again from their mails and ends with the same rows as a
full one.

refresh_edges runs in the caller's transaction and never commits.
"""

import time
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.db.models import GlobalStats

Executor = AsyncSession | AsyncConnection

STATS_KEY = "edges"  # global_stats: {"pairs": rows of edge, "refreshed_at": ISO 8601 UTC}
AUTOMATED_MIN_SENT = 10
LIST_MIN_SENDERS = 10
# Local parts of addresses nobody reads, optionally with a tag ("bounces+1234").
NOREPLY_LOCAL = (
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer[-_.]?daemon|postmaster|bounces?)([-_.+].*)?$"
)
# Transaction-level advisory lock: one refresh at a time (global_stats has its own key).
_LOCK_KEY = int.from_bytes(b"mr_edges", "big")
_COUNTERS = ("mails_a_to_b", "mails_b_to_a", "mails_cc", "pass_a_to_b", "pass_b_to_a", "pass_cc")

# The persons of a partial refresh, with whether each is a root: the given ids, their roots and
# every address merged into those roots, so a member's stale rows go even if only its root is
# given.
_SCOPE = text("""
    WITH given AS (SELECT DISTINCT unnest(CAST(:ids AS bigint[])) AS id),
    roots AS (SELECT coalesce(p.merged_into, p.id) AS id FROM person p JOIN given g ON g.id = p.id),
    scope AS (
        SELECT id FROM given UNION SELECT id FROM roots
        UNION SELECT p.id FROM person p JOIN roots r ON p.merged_into = r.id
    )
    SELECT s.id, p.id IS NOT NULL AND p.merged_into IS NULL
    FROM scope s LEFT JOIN person p ON p.id = s.id
""")

# Counted (mail, sender, recipient) pairs, summed per pair and UTC year (NULL: undated), then
# per pair. A pair of one mail is the sender's root and a recipient's root; grouping by them
# counts it once, as Cc only when every recipient address of that root is in Cc. {mails} and
# {pairs} narrow a partial refresh to the mails of its roots and the pairs touching them.
_PAIRS = """
    DROP TABLE IF EXISTS edge_calc;
    CREATE TEMP TABLE edge_calc ON COMMIT DROP AS
    WITH part AS (
        SELECT p.mail_id, coalesce(x.merged_into, x.id) AS root, p.role
        FROM participation p JOIN person x ON x.id = p.person_id
        {mails}
    ),
    pairs AS (
        SELECT s.mail_id, s.root AS sender, r.root AS recipient, bool_and(r.role = 'cc') AS cc
        FROM part s JOIN part r ON r.mail_id = s.mail_id AND r.role <> 'from' AND r.root <> s.root
        WHERE s.role = 'from' {pairs}
        GROUP BY s.mail_id, s.root, r.root
    )
    SELECT least(sender, recipient) AS person_a, greatest(sender, recipient) AS person_b,
        extract(year FROM m.date_utc AT TIME ZONE 'UTC')::smallint AS year,
        count(*) FILTER (WHERE NOT cc AND sender < recipient)::int AS mails_a_to_b,
        count(*) FILTER (WHERE NOT cc AND sender > recipient)::int AS mails_b_to_a,
        count(*) FILTER (WHERE cc)::int AS mails_cc,
        count(*) FILTER (WHERE pass AND NOT cc AND sender < recipient)::int AS pass_a_to_b,
        count(*) FILTER (WHERE pass AND NOT cc AND sender > recipient)::int AS pass_b_to_a,
        count(*) FILTER (WHERE pass AND cc)::int AS pass_cc,
        min(m.date_utc) AS first_date, max(m.date_utc) AS last_date
    FROM pairs JOIN (
        SELECT id, date_utc, coalesce(dkim_status = 'pass', false) AS pass FROM mail
        WHERE is_duplicate_of IS NULL
    ) m ON m.id = pairs.mail_id
    GROUP BY 1, 2, 3;
    DROP TABLE IF EXISTS edge_new;
    CREATE TEMP TABLE edge_new ON COMMIT DROP AS
    SELECT person_a, person_b,
        sum(mails_a_to_b)::int AS mails_a_to_b, sum(mails_b_to_a)::int AS mails_b_to_a,
        sum(mails_cc)::int AS mails_cc, sum(pass_a_to_b)::int AS pass_a_to_b,
        sum(pass_b_to_a)::int AS pass_b_to_a, sum(pass_cc)::int AS pass_cc,
        min(first_date) AS first_date, max(last_date) AS last_date
    FROM edge_calc GROUP BY person_a, person_b;
    DROP TABLE IF EXISTS edge_year_new;
    CREATE TEMP TABLE edge_year_new ON COMMIT DROP AS
    SELECT person_a, person_b, year, {counters} FROM edge_calc WHERE year IS NOT NULL
"""
# The mails in which an address of a partial refresh's roots takes part.
_ROOT_MAILS = """
    SELECT p.mail_id FROM participation p JOIN person x ON x.id = p.person_id
    WHERE coalesce(x.merged_into, x.id) = ANY(CAST(:roots AS bigint[]))"""
_PARTIAL_PAIRS = (
    "AND (s.root = ANY(CAST(:roots AS bigint[])) OR r.root = ANY(CAST(:roots AS bigint[])))"
)
_PARTIAL_ROWS = (
    "(t.person_a = ANY(CAST(:scope AS bigint[])) OR t.person_b = ANY(CAST(:scope AS bigint[])))"
)


def _sync(table: str, key: tuple[str, ...], columns: tuple[str, ...]) -> tuple[str, ...]:
    """DELETE, UPDATE and INSERT that make `table` equal to `table`_new among the rows that
    {rows} selects; rows that already match are not touched.

    The INSERT skips existing rows through the primary key rather than an anti join with the
    table it fills: with statistics of an empty table, PostgreSQL scans the growing table once
    per inserted row, which made the first refresh of 30,000 edges take 5 s instead of 0.1 s.
    """
    match = " AND ".join(f"n.{c} = t.{c}" for c in key)
    old = ", ".join(f"t.{c}" for c in columns)
    new = ", ".join(f"n.{c}" for c in columns)
    names = ", ".join((*key, *columns))
    return (
        f"DELETE FROM {table} t WHERE {{rows}} "
        f"AND NOT EXISTS (SELECT 1 FROM {table}_new n WHERE {match})",
        f"UPDATE {table} t SET {', '.join(f'{c} = n.{c}' for c in columns)} "
        f"FROM {table}_new n WHERE {match} AND ({old}) IS DISTINCT FROM ({new})",
        f"INSERT INTO {table} ({names}) SELECT {names} FROM {table}_new n "
        f"ON CONFLICT ({', '.join(key)}) DO NOTHING",
    )


_EDGE_SYNC = _sync("edge", ("person_a", "person_b"), (*_COUNTERS, "first_date", "last_date"))
_YEAR_SYNC = _sync("edge_year", ("person_a", "person_b", "year"), _COUNTERS)

# The kind of every root person whose addresses {members} selects (all persons, or those of a
# partial refresh's roots), from the counted mails of those addresses (D39); {mails} narrows a
# partial refresh to the mails of its roots.
_KINDS = """
    DROP TABLE IF EXISTS edge_kind;
    DROP TABLE IF EXISTS edge_listed;
    CREATE TEMP TABLE edge_listed ON COMMIT DROP AS  -- the lists among the recipients
    SELECT DISTINCT p.mail_id, p.person_id
    FROM mail m JOIN participation p ON p.mail_id = m.id AND p.role <> 'from'
    JOIN person_email e ON e.person_id = p.person_id
    WHERE m.list_id IS NOT NULL AND m.is_duplicate_of IS NULL
        AND replace(e.email, '@', '.') = m.list_id {mails};
    ANALYZE edge_listed;
    CREATE TEMP TABLE edge_kind ON COMMIT DROP AS
    WITH own AS (  -- one row per root and mail
        SELECT coalesce(x.merged_into, x.id) AS root, p.mail_id,
            bool_or(p.role = 'from') AS sent, bool_or(p.role <> 'from') AS received,
            bool_or(p.role <> 'from' AND l.mail_id IS NOT NULL) AS named
        FROM participation p JOIN person x ON x.id = p.person_id
        LEFT JOIN edge_listed l ON l.mail_id = p.mail_id AND l.person_id = p.person_id
        WHERE {members}
        GROUP BY 1, 2
    ),
    features AS (
        SELECT o.root,
            count(*) FILTER (WHERE o.sent) AS sent,
            count(*) FILTER (
                WHERE o.sent AND (m.automated OR (m.list_id IS NOT NULL AND post.mail_id IS NULL))
            ) AS programmatic,
            count(*) FILTER (
                WHERE o.sent AND (m.in_reply_to IS NOT NULL OR m.reference_ids IS NOT NULL
                    OR post.mail_id IS NOT NULL)
            ) AS conversational,
            count(*) FILTER (WHERE o.received) AS received,
            bool_or(o.named) AS named,
            bool_or(o.received AND NOT o.named AND m.list_id IS NOT NULL) AS subscribed
        FROM own o JOIN mail m ON m.id = o.mail_id AND m.is_duplicate_of IS NULL
        LEFT JOIN (SELECT DISTINCT mail_id FROM edge_listed) post ON post.mail_id = o.mail_id
        GROUP BY o.root
    ),
    senders AS (  -- who wrote to a candidate list without List-Id as the only recipient
        SELECT f.root, count(DISTINCT s.person_id) AS senders
        FROM features f JOIN person x ON coalesce(x.merged_into, x.id) = f.root
        JOIN participation r ON r.person_id = x.id AND r.role <> 'from'
        JOIN mail m ON m.id = r.mail_id AND m.is_duplicate_of IS NULL
        JOIN participation s ON s.mail_id = r.mail_id AND s.role = 'from'
        WHERE f.sent = 0 AND f.received >= :list_min_senders AND NOT f.subscribed
            AND NOT EXISTS (
                SELECT 1 FROM participation o
                WHERE o.mail_id = r.mail_id AND o.role <> 'from' AND o.person_id <> r.person_id
            )
        GROUP BY f.root
    ),
    noreply AS (
        SELECT DISTINCT coalesce(x.merged_into, x.id) AS root
        FROM person x JOIN person_email e ON e.person_id = x.id
        WHERE {members} AND split_part(e.email, '@', 1) ~ :noreply
    )
    SELECT x.id, CASE
        WHEN n.root IS NOT NULL OR f.programmatic * 2 > f.sent
            OR (f.sent >= :automated_min_sent AND f.conversational = 0 AND f.received = 0)
            THEN 'automated'
        WHEN f.named OR s.senders >= :list_min_senders THEN 'list'
    END::person_kind AS kind
    FROM person x
    LEFT JOIN features f ON f.root = x.id
    LEFT JOIN senders s ON s.root = x.id
    LEFT JOIN noreply n ON n.root = x.id
    WHERE x.merged_into IS NULL AND {members};
    UPDATE person p SET kind = k.kind FROM edge_kind k
    WHERE p.id = k.id AND p.kind IS DISTINCT FROM k.kind;
    UPDATE person SET kind = NULL WHERE merged_into IS NOT NULL AND kind IS NOT NULL {clear}
"""
_PAIR_COUNT = text("SELECT count(*) FROM edge")


@dataclass(frozen=True, slots=True)
class EdgeRefresh:
    """What one refresh changed."""

    inserted: int  # edge rows
    updated: int
    deleted: int
    years: int  # edge_year rows inserted, updated or deleted
    kinds: int  # persons whose kind changed
    pairs: int  # rows of edge afterwards
    seconds: float

    @property
    def changed(self) -> int:
        """edge rows inserted, updated or deleted."""
        return self.inserted + self.updated + self.deleted


async def refresh_edges(db: Executor, persons: Collection[int] | None = None) -> EdgeRefresh:
    """Recompute edges and person kinds: all of them, or those touching some persons.

    persons may hold root persons and addresses merged into them or split off again; every edge
    touching one of them or its current root is deleted and counted again, and person.kind is
    recomputed for those roots. Serialised with other refreshes by an advisory lock.
    """
    started = time.monotonic()
    await db.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))
    params: dict[str, Any] = {
        "noreply": NOREPLY_LOCAL,
        "automated_min_sent": AUTOMATED_MIN_SENT,
        "list_min_senders": LIST_MIN_SENDERS,
    }
    if persons is None:
        part = pairs = mails = clear = ""
        rows = members = "true"
    else:
        scope = (await db.execute(_SCOPE, {"ids": sorted(set(persons))})).all()
        params["scope"] = [person_id for person_id, _ in scope]
        params["roots"] = [person_id for person_id, root in scope if root]
        part = f"WHERE p.mail_id IN ({_ROOT_MAILS})"
        pairs, rows = _PARTIAL_PAIRS, _PARTIAL_ROWS
        mails = f"AND m.id IN ({_ROOT_MAILS})"
        members = "coalesce(x.merged_into, x.id) = ANY(CAST(:roots AS bigint[]))"
        clear = "AND id = ANY(CAST(:scope AS bigint[]))"
    counters = ", ".join(_COUNTERS)
    await _script(db, _PAIRS.format(mails=part, pairs=pairs, counters=counters), params)
    deleted, updated, inserted = [
        await _rowcount(db, statement.format(rows=rows), params) for statement in _EDGE_SYNC
    ]
    years = [await _rowcount(db, s.format(rows=rows), params) for s in _YEAR_SYNC]
    kinds = await _script(db, _KINDS.format(members=members, mails=mails, clear=clear), params)
    pairs_now = await db.scalar(_PAIR_COUNT) or 0
    await _store_stats(db, pairs_now)
    seconds = round(time.monotonic() - started, 3)
    return EdgeRefresh(inserted, updated, deleted, sum(years), kinds, pairs_now, seconds)


async def _script(db: Executor, script: str, params: dict[str, Any]) -> int:
    """Run statements separated by semicolons; returns the rows the UPDATEs among them changed."""
    changed = 0
    for statement in script.split(";"):
        rows = await _rowcount(db, statement, params)
        changed += rows if statement.lstrip().startswith("UPDATE") else 0
    return changed


async def _rowcount(db: Executor, statement: str, params: dict[str, Any]) -> int:
    result = cast(CursorResult[Any], await db.execute(text(statement), params))
    return result.rowcount


async def _store_stats(db: Executor, pairs: int) -> None:
    value = {"pairs": pairs, "refreshed_at": datetime.now(UTC).isoformat()}
    statement = postgresql.insert(GlobalStats).values(key=STATS_KEY, value=value)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[GlobalStats.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
    )

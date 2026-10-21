"""person_stats and person_year of the root persons (D29).

A mail that is not a duplicate counts once per root person, however many of the root's
addresses take part in it: sent when one of them is in From, received otherwise (To, Cc or
Bcc), and only Cc when the root is in Cc and in no other role. Every root has a person_stats
row, zeros when all its mails are duplicates; persons merged into another have none.
person_year counts sent and received per UTC year, so mails without a date count in
person_stats only. The DKIM share is pass among the sent mails with a DKIM status; contacts are
the person's rows in edge.

A refresh first collects the figures per root and year in a temporary table, in one pass over
the participations (all of them, or through the participation index those of the roots
concerned) and their mails, then brings both tables in line with it (sync.sync_rows), which
writes only the rows that change. A refresh for some persons also counts the contacts of their
contacts again, whose edges a merge changes as well.
"""

from collections.abc import Collection
from typing import Any

from sqlalchemy import text

from mailrobbe.persons.roots import Executor, lock_persons
from mailrobbe.persons.sync import sync_rows

_FIGURES_TABLE = (
    "DROP TABLE IF EXISTS pg_temp.person_figures",
    """
    CREATE TEMP TABLE person_figures (
        root bigint, year integer, sent integer, received integer, cc_only integer,
        first_date timestamptz, last_date timestamptz, dkim_pass integer, dkim_checked integer
    ) ON COMMIT DROP
    """,
)
# Figures per root and UTC year (NULL: no date); {members} limits the participations read.
_FIGURES = """
    INSERT INTO person_figures
    WITH per_mail AS (
        SELECT coalesce(x.merged_into, x.id) AS root, p.mail_id,
            bool_or(p.role = 'from') AS sent, bool_and(p.role = 'cc') AS cc_only
        FROM participation p JOIN person x ON x.id = p.person_id
        {members}
        GROUP BY 1, 2
    )
    SELECT r.root, date_part('year', m.date_utc AT TIME ZONE 'UTC')::integer,
        count(*) FILTER (WHERE r.sent), count(*) FILTER (WHERE NOT r.sent),
        count(*) FILTER (WHERE r.cc_only), min(m.date_utc), max(m.date_utc),
        count(*) FILTER (WHERE r.sent AND m.dkim_status = 'pass'),
        count(*) FILTER (WHERE r.sent AND m.dkim_status IS NOT NULL)
    FROM per_mail r JOIN mail m ON m.id = r.mail_id
    WHERE m.is_duplicate_of IS NULL
    GROUP BY 1, 2
"""
# One row per root ({roots} limits them), zeros when none of its mails counts.
_STATS = """
    SELECT r.id AS person_id, coalesce(f.sent, 0) AS sent, coalesce(f.received, 0) AS received,
        coalesce(f.cc_only, 0) AS cc_only, coalesce(c.contacts, 0) AS contacts, f.first_date,
        f.last_date, f.dkim_pass_ratio
    FROM person r
    LEFT JOIN (
        SELECT root, sum(sent)::integer AS sent, sum(received)::integer AS received,
            sum(cc_only)::integer AS cc_only, min(first_date) AS first_date,
            max(last_date) AS last_date,
            (sum(dkim_pass)::float8 / nullif(sum(dkim_checked), 0))::real AS dkim_pass_ratio
        FROM person_figures GROUP BY root
    ) f ON f.root = r.id
    LEFT JOIN (
        SELECT person, count(*)::integer AS contacts
        FROM (
            SELECT person_a FROM edge {edge_a} UNION ALL SELECT person_b FROM edge {edge_b}
        ) AS e (person)
        GROUP BY person
    ) c ON c.person = r.id
    WHERE r.merged_into IS NULL {roots}
"""
_STATS_KEYS = ("person_id",)
_STATS_VALUES = (
    "sent",
    "received",
    "cc_only",
    "contacts",
    "first_date",
    "last_date",
    "dkim_pass_ratio",
)
_YEARS = "SELECT root AS person_id, year, sent, received FROM person_figures WHERE year IS NOT NULL"
_YEAR_KEYS = ("person_id", "year")
_YEAR_VALUES = ("sent", "received")

_ANY_ROOT = "ANY(CAST(:roots AS bigint[]))"
_ROOTS_OF = text(
    "SELECT DISTINCT coalesce(merged_into, id) FROM person WHERE id = ANY(CAST(:ids AS bigint[]))"
)
_MEMBERS_OF = text(f"SELECT id FROM person WHERE id = {_ANY_ROOT} OR merged_into = {_ANY_ROOT}")
# A merge or unmerge changes the edges of the roots concerned, and with them the contacts of the
# persons at their other end: a contact of both merged persons has one edge less.
_NEIGHBOUR_CONTACTS = text(f"""
    WITH neighbour AS (
        SELECT person_b AS person FROM edge WHERE person_a = {_ANY_ROOT}
        UNION SELECT person_a FROM edge WHERE person_b = {_ANY_ROOT}
    )
    UPDATE person_stats s SET contacts = c.contacts
    FROM (
        SELECT n.person, (
            SELECT count(*) FROM edge e WHERE e.person_a = n.person OR e.person_b = n.person
        )::integer AS contacts
        FROM neighbour n
    ) c
    WHERE s.person_id = c.person AND s.contacts <> c.contacts
""")


async def refresh_person_stats(db: Executor, persons: Collection[int] | None = None) -> None:
    """Recompute the figures of every root person, or only those of these persons.

    persons may name roots and former roots or aliases (after a merge or unmerge): the figures
    of each one's current root are recomputed, the rows of those that are no longer roots are
    deleted, and the contacts of the persons they have edges with are counted again. Counts
    contacts from edge, so it runs after graph.edges.refresh_edges.
    """
    if persons is not None and not persons:
        return
    await lock_persons(db)
    for statement in _FIGURES_TABLE:
        await db.execute(text(statement))
    params: dict[str, Any] = {}
    if persons is None:
        members, roots, scope = "", "", "true"
        edge_a = edge_b = ""
    else:
        ids = set(persons)
        params["roots"] = sorted(await db.scalars(_ROOTS_OF, {"ids": sorted(ids)}))
        params["members"] = list(await db.scalars(_MEMBERS_OF, params))
        params["ids"] = sorted(ids.union(params["roots"]))  # rows that may change
        members = "WHERE p.person_id = ANY(CAST(:members AS bigint[]))"
        roots = f"AND r.id = {_ANY_ROOT}"
        edge_a, edge_b = f"WHERE person_a = {_ANY_ROOT}", f"WHERE person_b = {_ANY_ROOT}"
        scope = "t.person_id = ANY(CAST(:ids AS bigint[]))"
    await db.execute(text(_FIGURES.format(members=members)), params)
    await db.execute(text("ANALYZE person_figures"))
    stats = _STATS.format(edge_a=edge_a, edge_b=edge_b, roots=roots)
    await sync_rows(db, "person_stats", _STATS_KEYS, _STATS_VALUES, stats, params, scope)
    await sync_rows(db, "person_year", _YEAR_KEYS, _YEAR_VALUES, _YEARS, params, scope)
    if persons is not None:
        await db.execute(_NEIGHBOUR_CONTACTS, params)

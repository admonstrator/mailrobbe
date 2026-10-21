"""The near phase of an import (D153), from the database alone; nothing is read from the MBOX
files.

    near_texts   the fingerprint (model.fingerprint) of every mail without a mail_near row or
                 with one of an older NEAR_VERSION, from mail.subject and mail.body_text, in
                 batches of BATCH mails by id, one transaction each; duplicates too, since
                 their rows carry their group
    near_groups  mail_near.group_id recomputed for every mail in one statement, rows written
                 only where it changed: a fingerprint shared by at least two mails that are no
                 duplicates (D16) is a group, its id the smallest of their ids; a duplicate
                 takes the group of its original, whatever its own fingerprint; every other
                 mail none. Then the figures in global_stats 'near', in the same transaction

A stop (D46) ends near_texts between two batches: the fingerprints stored so far stay, and the
groups are left as they were until the next import.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.db.models import NEAR_VERSION
from mailrobbe.jobrun import Step
from mailrobbe.near.model import NearFigures, fingerprint, write_figures

log = logging.getLogger(__name__)

STEPS = ("near_texts", "near_groups")  # in order
BATCH = 1000  # mails per read and transaction of near_texts

_WAITING = """
    FROM mail m
    WHERE NOT EXISTS (
        SELECT 1 FROM mail_near n WHERE n.mail_id = m.id AND n.version = :version)
"""
_COUNT = text(f"SELECT count(*) {_WAITING}")
_TEXTS = text(f"""
    SELECT m.id, m.subject, m.body_text {_WAITING} AND m.id > :after ORDER BY m.id LIMIT :limit
""")
_STORE = text("""
    INSERT INTO mail_near (mail_id, version, fingerprint)
    SELECT u.id, :version, u.fingerprint
    FROM unnest(CAST(:ids AS bigint[]), CAST(:fingerprints AS bytea[])) AS u(id, fingerprint)
    ON CONFLICT (mail_id) DO UPDATE
    SET version = EXCLUDED.version, fingerprint = EXCLUDED.fingerprint
""")
_GROUPS = text("""
    WITH shared AS (
        SELECT n.fingerprint, min(n.mail_id) AS group_id
        FROM mail_near n JOIN mail m ON m.id = n.mail_id
        WHERE n.fingerprint IS NOT NULL AND m.is_duplicate_of IS NULL
        GROUP BY n.fingerprint
        HAVING count(*) > 1
    ),
    originals AS (
        SELECT n.mail_id, s.group_id
        FROM mail_near n JOIN mail m ON m.id = n.mail_id
        JOIN shared s ON s.fingerprint = n.fingerprint
        WHERE m.is_duplicate_of IS NULL
    ),
    grouped AS (
        SELECT mail_id, group_id FROM originals
        UNION ALL
        SELECT m.id, o.group_id FROM mail m JOIN originals o ON o.mail_id = m.is_duplicate_of
    ),
    target AS (
        SELECT r.mail_id, g.group_id
        FROM mail_near r LEFT JOIN grouped g ON g.mail_id = r.mail_id
        WHERE r.group_id IS NOT NULL OR g.group_id IS NOT NULL
    )
    UPDATE mail_near n SET group_id = t.group_id
    FROM target t
    WHERE n.mail_id = t.mail_id AND n.group_id IS DISTINCT FROM t.group_id
""")
_FIGURES = text("""
    SELECT count(DISTINCT n.group_id) AS groups,
        count(*) FILTER (WHERE m.is_duplicate_of IS NULL) AS mails,
        count(*) AS members
    FROM mail_near n JOIN mail m ON m.id = n.mail_id
    WHERE n.group_id IS NOT NULL
""")


async def waiting(session: AsyncSession) -> int:
    """Mails without a fingerprint of the current NEAR_VERSION."""
    return int(await session.scalar(_COUNT, {"version": NEAR_VERSION}) or 0)


async def fingerprint_mails(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event, step: Step
) -> int:
    """The step near_texts: fingerprint the waiting mails; the mails stored."""
    stored = after = 0
    while not stop.is_set():
        async with sessionmaker() as session, session.begin():
            parameters = {"version": NEAR_VERSION, "after": after, "limit": BATCH}
            rows = (await session.execute(_TEXTS, parameters)).all()
            if not rows:
                break
            found = await asyncio.to_thread(_fingerprints, rows)
            ids = [row.id for row in rows]
            await session.execute(
                _STORE, {"version": NEAR_VERSION, "ids": ids, "fingerprints": found}
            )
        stored += len(rows)
        step.advance(len(rows))
        after = ids[-1]
    return stored


def _fingerprints(rows: Sequence[Any]) -> list[bytes | None]:
    return [fingerprint(row.subject, row.body_text) for row in rows]


async def group_mails(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event, step: Step
) -> int:
    """The step near_groups: recompute the groups and the figures; the mails in a group. One
    statement, so a stop waits for its end."""
    async with sessionmaker() as session, session.begin():
        changed = cast(CursorResult[Any], await session.execute(_GROUPS)).rowcount
        groups, mails, members = (await session.execute(_FIGURES)).one()
        figures = NearFigures(datetime.now(UTC), groups, mails, members - groups)
        await write_figures(session, figures)
    log.info(
        "near duplicates: %d groups, %d mails in them (%d rows changed), %d hidden when collapsed",
        groups,
        members,
        changed,
        figures.hidden,
    )
    return int(members)

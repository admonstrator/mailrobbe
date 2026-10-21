"""After importing: duplicates (D16), threads (D17) and display names, recomputed as a whole,
then the global figures of the web UI (global_stats, D19).

Every step is set-based SQL apart from threading, a union-find in the main process over the
Message-IDs of all mails that are not duplicates. Each step writes only rows whose value
changes, so a finalize without new mails changes nothing but the time stamp of global_stats. It
may run while workers import: it works on the mails committed when each step starts, and the
next finalize picks up the rest.
"""

import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, Executable, text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.aggregates import refresh_global_stats
from mailrobbe.importer.store import copy_rows

# The earliest mail by file path and offset is the original; paths compare bytewise, as the
# scan sorts them. Mails without Message-ID are compared by the SHA-256 of their message.
_DUPLICATES = text("""
    WITH ranked AS (
        SELECT m.id, first_value(m.id) OVER (
            PARTITION BY m.message_id,
                CASE WHEN m.message_id IS NULL THEN m.raw_sha256 ELSE m.subject END
            ORDER BY f.path COLLATE "C", m.byte_offset
        ) AS original
        FROM mail m JOIN mbox_file f ON f.id = m.mbox_file_id
    )
    UPDATE mail SET is_duplicate_of = NULLIF(ranked.original, ranked.id)
    FROM ranked
    WHERE mail.id = ranked.id
      AND mail.is_duplicate_of IS DISTINCT FROM NULLIF(ranked.original, ranked.id)
""")

# Read in partitions: row by row, the async stream costs about 6 s per 400,000 mails, not 1 s.
_THREAD_NODES = text(
    "SELECT id, message_id, in_reply_to, reference_ids FROM mail WHERE is_duplicate_of IS NULL"
).execution_options(yield_per=10_000)
_THREAD_TABLE = (
    "DROP TABLE IF EXISTS finalize_thread",
    "CREATE TEMP TABLE finalize_thread (id bigint PRIMARY KEY, thread_id bigint) ON COMMIT DROP",
)
_SET_THREADS = text("""
    UPDATE mail SET thread_id = t.thread_id FROM finalize_thread t
    WHERE mail.id = t.id AND mail.thread_id IS DISTINCT FROM t.thread_id
""")
_DUPLICATE_THREADS = text("""
    UPDATE mail SET thread_id = o.thread_id FROM mail o
    WHERE mail.is_duplicate_of = o.id AND mail.thread_id IS DISTINCT FROM o.thread_id
""")

_NAME_TABLE = (
    "DROP TABLE IF EXISTS finalize_name",
    """
    CREATE TEMP TABLE finalize_name ON COMMIT DROP AS
    SELECT person_id, display_name, count(*) AS n FROM participation
    WHERE display_name IS NOT NULL GROUP BY person_id, display_name
    """,
)
_SET_NAME_COUNTS = text("""
    WITH maps AS (
        SELECT person_id, jsonb_object_agg(display_name, n) AS names
        FROM finalize_name GROUP BY person_id
    )
    UPDATE person_email e SET display_names = COALESCE(maps.names, '{}'::jsonb)
    FROM person_email x LEFT JOIN maps ON maps.person_id = x.person_id
    WHERE x.email = e.email AND e.display_names IS DISTINCT FROM COALESCE(maps.names, '{}'::jsonb)
""")
_SET_PERSON_NAMES = text("""
    WITH best AS (
        SELECT DISTINCT ON (person_id) person_id, display_name FROM finalize_name
        ORDER BY person_id, n DESC, display_name
    )
    UPDATE person p SET display_name = best.display_name
    FROM person x LEFT JOIN best ON best.person_id = x.id
    WHERE x.id = p.id AND p.display_name IS DISTINCT FROM best.display_name
""")


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    """Rows changed by one finalize."""

    duplicates: int  # mails whose is_duplicate_of changed
    threads: int  # mails whose thread_id changed
    display_names: int  # person and person_email rows whose display names changed
    seconds: float


async def finalize(session: AsyncSession) -> FinalizeResult:
    """Recompute duplicates, then threads (which skip duplicates), display names, global_stats."""
    started = time.monotonic()
    async with session.begin():
        duplicates = await _changed(session, _DUPLICATES)
    async with session.begin():
        threads = await _set_threads(session)
    async with session.begin():
        for statement in _NAME_TABLE:
            await session.execute(text(statement))
        names = await _changed(session, _SET_NAME_COUNTS)
        names += await _changed(session, _SET_PERSON_NAMES)
    async with session.begin():
        await refresh_global_stats(session)
    return FinalizeResult(duplicates, threads, names, time.monotonic() - started)


class ThreadForest:
    """Union-find over Message-IDs: add() every mail that is not a duplicate, then thread_ids().

    Nodes are Message-IDs, so mails that refer to the same missing parent share a thread. Only
    the nodes and one anchor per mail are kept, not the rows.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._anchors: list[tuple[int, str]] = []  # (mail id, first node of the mail)

    def add(
        self,
        mail_id: int,
        message_id: str | None,
        in_reply_to: str | None,
        reference_ids: Sequence[str] | None,
    ) -> None:
        nodes = [node for node in (message_id, in_reply_to, *(reference_ids or ())) if node]
        if not nodes:
            return
        root = self._find(nodes[0])
        for node in nodes[1:]:
            other = self._find(node)
            if other != root:
                self._parent[other] = root
        self._anchors.append((mail_id, nodes[0]))

    def thread_ids(self) -> dict[int, int]:
        """Mail id -> smallest mail id of its thread, for threads of at least two mails."""
        sizes: Counter[str] = Counter()
        smallest: dict[str, int] = {}
        for mail_id, node in self._anchors:
            root = self._find(node)
            sizes[root] += 1
            smallest[root] = min(mail_id, smallest.get(root, mail_id))
        return {
            mail_id: smallest[root]
            for mail_id, node in self._anchors
            if sizes[root := self._find(node)] >= 2
        }

    def _find(self, node: str) -> str:
        parent = self._parent
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]  # path halving
            node = parent[node]
        return node


async def _set_threads(session: AsyncSession) -> int:
    forest = ThreadForest()
    mail_ids: list[int] = []
    async for partition in (await session.stream(_THREAD_NODES)).partitions():
        for mail_id, message_id, in_reply_to, reference_ids in partition:
            forest.add(mail_id, message_id, in_reply_to, reference_ids)
            mail_ids.append(mail_id)
    threads = forest.thread_ids()
    for statement in _THREAD_TABLE:
        await session.execute(text(statement))
    rows = [(mail_id, threads.get(mail_id)) for mail_id in mail_ids]
    await copy_rows(session, "finalize_thread", ("id", "thread_id"), rows)
    await session.execute(text("ANALYZE finalize_thread"))
    return await _changed(session, _SET_THREADS) + await _changed(session, _DUPLICATE_THREADS)


async def _changed(session: AsyncSession, statement: Executable) -> int:
    result = cast(CursorResult[Any], await session.execute(statement))
    return result.rowcount

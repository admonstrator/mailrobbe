"""The import's steps paragraphs and blocks (D224, D225), from the database alone: the stored
texts (mail.body_text) are split, nothing is read from the MBOX files.

    paragraphs  every mail without a mail_paragraph_scan row of PARAGRAPH_VERSION, duplicates
                too (the mail list shows them when hide_duplicates is off): its text split by
                model.paragraphs in a thread, its mail_paragraph rows replaced and its scan row
                written with the ranges of its quotes (model.history), in batches of BATCH mails
                by id, one transaction each. A mail the rule fails on gets a scan row without
                paragraphs and is logged; a stop ends the step between two batches
    blocks      always: the standard blocks detected (tail occurrences in at least
                settings.block_min_mails mails that are no duplicates, and at least two such
                mails per distinct sender address), then the team's choices (paragraph_override:
                marked by hand, or taken back); paragraph_block replaced with every detected or
                chosen paragraph and its figures over all mails holding it anywhere, in one
                transaction. Then every mail whose ranges differ from what its scan row and the
                standard blocks give gets both in one UPDATE (the trigger mail_tsv weighs its
                tsvector anew, D226), in batches by id; a mail whose blocks changed loses its
                mail_entity_scan row, so the next entities phase scans it again (D205). Last the
                figures in global_stats 'blocks'. A stop ends the step between two batches; the
                next run applies everything again, and a run without changes writes no mail.

The detection reads the tail rows of mail_paragraph once and keeps the paragraphs with at least
block_min_mails of them; only those are counted exactly, through ix_mail_paragraph_hash.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.api.schemas import BLOCK_SAMPLE_LIMIT
from mailrobbe.blocks.model import (
    BlockFigures,
    Paragraph,
    history,
    multirange,
    paragraphs,
    write_figures,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import PARAGRAPH_VERSION
from mailrobbe.jobrun import Step, describe
from mailrobbe.quotes import split_text

log = logging.getLogger(__name__)

STEPS = ("paragraphs", "blocks")  # in order
BATCH = 1000  # mails per read and transaction of both steps

_WAITING = """
    FROM mail m
    WHERE NOT EXISTS (
        SELECT 1 FROM mail_paragraph_scan s WHERE s.mail_id = m.id AND s.version = :version)
"""
_COUNT = text(f"SELECT count(*) {_WAITING}")
_TEXTS = text(f"""
    SELECT m.id, m.body_text {_WAITING} AND m.id > :after ORDER BY m.id LIMIT :limit
""")
_FORGET = text("DELETE FROM mail_paragraph WHERE mail_id = ANY(CAST(:ids AS bigint[]))")
_PARAGRAPHS = text("""
    INSERT INTO mail_paragraph (mail_id, position, hash, span, quoted, tail)
    SELECT u.mail_id, u.position, u.hash, int4range(u.lower, u.upper), u.quoted, u.tail
    FROM unnest(CAST(:mail_ids AS bigint[]), CAST(:positions AS smallint[]),
        CAST(:hashes AS bigint[]), CAST(:lowers AS integer[]), CAST(:uppers AS integer[]),
        CAST(:quoted AS boolean[]), CAST(:tails AS boolean[]))
        AS u(mail_id, position, hash, lower, upper, quoted, tail)
""")
_SCANS = text("""
    INSERT INTO mail_paragraph_scan (mail_id, version, history)
    SELECT u.id, :version, CAST(u.history AS int4multirange)
    FROM unnest(CAST(:ids AS bigint[]), CAST(:histories AS text[])) AS u(id, history)
    ON CONFLICT (mail_id) DO UPDATE SET version = EXCLUDED.version, history = EXCLUDED.history
""")

# The blocks of D225 with their figures, replacing paragraph_block. candidates reads the tail
# rows once; a paragraph with fewer tail rows than the threshold cannot have that many mails.
_REPLACE = (
    text("DELETE FROM paragraph_block"),
    text("""
    WITH candidates AS (
        SELECT hash FROM mail_paragraph WHERE tail GROUP BY hash HAVING count(*) >= :min_mails
    ),
    detected AS (
        SELECT p.hash
        FROM mail_paragraph p
        JOIN candidates c ON c.hash = p.hash
        JOIN mail m ON m.id = p.mail_id AND m.is_duplicate_of IS NULL
        LEFT JOIN participation f ON f.mail_id = m.id AND f.role = 'from'
        WHERE p.tail
        GROUP BY p.hash
        HAVING count(DISTINCT m.id) >= :min_mails
            AND count(DISTINCT m.id) >= 2 * count(DISTINCT f.person_id)
    ),
    looked AS (
        SELECT coalesce(d.hash, o.hash) AS hash, d.hash IS NOT NULL AS detected,
            coalesce(o.standard, true) AS standard, o.sample AS chosen
        FROM detected d FULL JOIN paragraph_override o ON o.hash = d.hash
    ),
    held AS (
        SELECT DISTINCT p.hash, p.mail_id FROM mail_paragraph p JOIN looked l ON l.hash = p.hash
    ),
    figures AS (
        SELECT h.hash, count(DISTINCT m.id) AS mails, count(DISTINCT f.person_id) AS senders,
            min(m.date_utc) AS first_date, max(m.date_utc) AS last_date
        FROM held h
        JOIN mail m ON m.id = h.mail_id AND m.is_duplicate_of IS NULL
        LEFT JOIN participation f ON f.mail_id = m.id AND f.role = 'from'
        GROUP BY h.hash
    ),
    picked AS (  -- the occurrence shown: one as written, unquoted where there is one
        SELECT DISTINCT ON (p.hash) p.hash, p.mail_id, p.span
        FROM mail_paragraph p JOIN looked l ON l.hash = p.hash
        ORDER BY p.hash, p.quoted, p.mail_id
    )
    INSERT INTO paragraph_block
        (hash, standard, detected, mails, senders, first_date, last_date, sample)
    SELECT l.hash, l.standard, l.detected, coalesce(f.mails, 0), coalesce(f.senders, 0),
        f.first_date, f.last_date,
        coalesce(substr(m.body_text, lower(k.span) + 1, least(upper(k.span) - lower(k.span),
            :limit)), left(l.chosen, :limit))
    FROM looked l
    LEFT JOIN figures f ON f.hash = l.hash
    LEFT JOIN picked k ON k.hash = l.hash
    LEFT JOIN mail m ON m.id = k.mail_id
"""),
)
# One batch of mails by id: the ranges its scan row and the standard blocks give, written where
# they differ (NULL for none on both sides, so a second run finds no difference); the mails
# whose blocks changed are scanned again by the next entities phase.
_APPLY = text("""
    WITH batch AS MATERIALIZED (
        SELECT m.id, m.is_duplicate_of IS NULL AS original, m.history, m.blocks,
            s.history AS new_history,
            (SELECT range_agg(p.span) FROM mail_paragraph p
                JOIN paragraph_block b ON b.hash = p.hash AND b.standard
                WHERE p.mail_id = m.id) AS new_blocks
        FROM mail m LEFT JOIN mail_paragraph_scan s ON s.mail_id = m.id
        WHERE m.id > :after
        ORDER BY m.id
        LIMIT :limit
    ),
    changed AS (
        UPDATE mail m SET history = b.new_history, blocks = b.new_blocks
        FROM batch b
        WHERE m.id = b.id
            AND (b.history IS DISTINCT FROM b.new_history OR b.blocks IS DISTINCT FROM b.new_blocks)
        RETURNING m.id, b.blocks IS DISTINCT FROM b.new_blocks AS blocks_changed
    ),
    rescan AS (
        DELETE FROM mail_entity_scan e USING changed c
        WHERE e.mail_id = c.id AND c.blocks_changed
        RETURNING e.mail_id
    )
    SELECT (SELECT max(id) FROM batch) AS last,
        (SELECT count(*) FROM batch) AS looked,
        (SELECT count(*) FROM batch WHERE original AND new_blocks IS NOT NULL) AS with_blocks,
        (SELECT count(*) FROM changed) AS changed,
        (SELECT count(*) FILTER (WHERE blocks_changed) FROM changed) AS blocks_changed
""")
_KINDS = text("""
    SELECT count(*) FILTER (WHERE standard) AS blocks,
        count(*) FILTER (WHERE standard AND detected) AS detected,
        count(*) FILTER (WHERE standard AND NOT detected) AS marked,
        count(*) FILTER (WHERE detected AND NOT standard) AS dismissed
    FROM paragraph_block
""")
_MAILS = text("SELECT count(*) FROM mail")


async def waiting(session: AsyncSession) -> int:
    """Mails not split by the current PARAGRAPH_VERSION."""
    return int(await session.scalar(_COUNT, {"version": PARAGRAPH_VERSION}) or 0)


async def split_mails(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event, step: Step
) -> int:
    """The step paragraphs: split the waiting mails; the mails split."""
    split = after = 0
    while not stop.is_set():
        async with sessionmaker() as session, session.begin():
            parameters = {"version": PARAGRAPH_VERSION, "after": after, "limit": BATCH}
            rows = (await session.execute(_TEXTS, parameters)).all()
            if not rows:
                break
            found = await asyncio.to_thread(_split, rows)
            ids = [row.id for row in rows]
            await session.execute(_FORGET, {"ids": ids})
            await session.execute(
                _PARAGRAPHS, _paragraph_rows(ids, [pieces for pieces, _ in found])
            )
            histories = [ranges for _, ranges in found]
            await session.execute(
                _SCANS, {"version": PARAGRAPH_VERSION, "ids": ids, "histories": histories}
            )
        split += len(rows)
        step.advance(len(rows))
        after = ids[-1]
    return split


def _split(rows: Sequence[Any]) -> list[tuple[list[Paragraph], str | None]]:
    """Every mail's paragraphs and history literal; a mail whose text the rule fails on gets
    none, so one mail never stops the step."""
    found: list[tuple[list[Paragraph], str | None]] = []
    for row in rows:
        body = row.body_text or ""
        try:
            segments = split_text(body)
            found.append((paragraphs(body, segments), multirange(history(body, segments))))
        except Exception as error:  # the rule never raises: a bug, for this mail alone
            log.warning("paragraphs: mail %d: %s", row.id, describe(error))
            found.append(([], None))
    return found


def _paragraph_rows(ids: Sequence[int], found: Sequence[list[Paragraph]]) -> dict[str, list[Any]]:
    """The columns of the batch's mail_paragraph rows, for unnest."""
    columns: dict[str, list[Any]] = {
        key: []
        for key in ("mail_ids", "positions", "hashes", "lowers", "uppers", "quoted", "tails")
    }
    for mail_id, pieces in zip(ids, found, strict=True):
        for position, paragraph in enumerate(pieces):
            columns["mail_ids"].append(mail_id)
            columns["positions"].append(position)
            columns["hashes"].append(paragraph.hash)
            columns["lowers"].append(paragraph.start)
            columns["uppers"].append(paragraph.end)
            columns["quoted"].append(paragraph.quoted)
            columns["tails"].append(paragraph.tail)
    return columns


async def find_blocks(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    stop: asyncio.Event,
    step: Step,
) -> int:
    """The step blocks: the standard blocks recomputed and applied; the mails whose ranges
    changed."""
    async with sessionmaker() as session, session.begin():
        for statement in _REPLACE:
            await session.execute(
                statement, {"min_mails": settings.block_min_mails, "limit": BLOCK_SAMPLE_LIMIT}
            )
        kinds = (await session.execute(_KINDS)).one()
        step.unit, step.total = "mails", int(await session.scalar(_MAILS) or 0)
    log.info(
        "standard blocks: %d (%d detected, %d marked by hand), %d taken back",
        kinds.blocks,
        kinds.detected,
        kinds.marked,
        kinds.dismissed,
    )
    changed = rescanned = with_blocks = after = 0
    while True:
        if stop.is_set():  # the figures stay those of the last whole step
            log.info("standard blocks: stopped after %d mails, %d changed", step.done, changed)
            return changed
        async with sessionmaker() as session, session.begin():
            batch = (await session.execute(_APPLY, {"after": after, "limit": BATCH})).one()
        if not batch.looked:
            break
        changed += batch.changed
        rescanned += batch.blocks_changed
        with_blocks += batch.with_blocks
        step.advance(batch.looked)
        after = batch.last
    figures = BlockFigures(
        computed_at=datetime.now(UTC),
        blocks=kinds.blocks,
        detected=kinds.detected,
        marked=kinds.marked,
        dismissed=kinds.dismissed,
        mails=with_blocks,
    )
    async with sessionmaker() as session, session.begin():
        await write_figures(session, figures)
    log.info(
        "standard blocks: %d mails hold one, ranges of %d mails changed, %d to scan again",
        with_blocks,
        changed,
        rescanned,
    )
    return changed

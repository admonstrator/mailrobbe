"""The entities phase of an import (D84): every text not scanned by the current scan version is
scanned for entities, and its mentions replace the earlier ones.

    work list   documents with a text (status text or timeout) not scanned by the current
                model.scan_version() or extracted again since (document.extracted_at), then
                mails not scanned by it, each by id; documents scanned before whose text is gone
                lose their mentions first. waiting() counts it for the import's step.
    batches     at most BATCH_TEXTS texts or BATCH_BYTES bytes of them; a larger text is a batch
                of its own, never joined with others. The main process reads a batch's texts
                (one query), a mail's with its standard blocks blanked (without_blocks, D205),
                and hands them to the pool.
    workers     spawned processes, as many as the import has; each reads the gazetteers and word
                lists once (extract.prepare) and extracts each text of a batch on its own.
    store       the results in the order the batches were handed out, one transaction each: new
                entities first, in the order found and only those not stored yet (an INSERT
                that skips a stored one would still draw an id), so that an archive gets the
                same ids whatever the number of workers or the size of the batches; then the
                texts' old mentions deleted, the new ones inserted and the scans recorded. The
                step counts the bytes of the texts stored.
    figures     at the end of a phase that was not stopped, figures.refresh_entity_figures in a
                transaction of its own (D85).

A stop (D46) ends the phase between two batches at once: the workers are killed, the stored
batches stay, the rest waits for the next import. A worker that dies (out of memory, a crash)
takes the batches in work with it: they are scanned again one text at a time, and a text that
kills its worker alone is recorded as scanned without entities, with a warning naming it. A text
whose extraction raises is recorded the same way, by the worker itself.
"""

import asyncio
import logging
import multiprocessing
import re
import time
from array import array
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.entities.extract import extract_entities, prepare
from mailrobbe.entities.figures import FiguresRefresh, refresh_entity_figures
from mailrobbe.entities.model import Found, scan_version, scanned_text
from mailrobbe.jobrun import describe, ignore_interrupts, kill_workers, spawning_workers

log = logging.getLogger(__name__)

BATCH_TEXTS = 500  # texts per batch and transaction at most
BATCH_BYTES = 4_000_000  # bytes of text per batch at most (a larger text is a batch alone)
QUEUED = 2  # batches handed to the pool per worker, so that no worker waits for the next
_DIED = "the worker process died while scanning it"
_BLANKED = re.compile(r"[^\n]")  # what a standard block's text loses (without_blocks)

Source = Literal["mail", "document"]

# The texts waiting (module docstring), as FROM and WHERE of the queries over them; size is the
# bytes of the text as stored, which octet_length reads without unpacking it.
_MAIL_SIZE = "COALESCE(octet_length(m.subject), 0) + COALESCE(octet_length(m.body_text), 0) + 1"
_MAILS = """
    FROM mail m
    WHERE NOT EXISTS (
        SELECT 1 FROM mail_entity_scan s WHERE s.mail_id = m.id AND s.version = :version)
"""
_HAS_TEXT = "d.text_status IN ('text', 'timeout') AND d.extracted_text IS NOT NULL"
_DOCUMENTS = f"""
    FROM document d
    WHERE {_HAS_TEXT} AND NOT EXISTS (
        SELECT 1 FROM document_entity_scan s
        WHERE s.document_id = d.id AND s.version = :version
          AND s.extracted_at IS NOT DISTINCT FROM d.extracted_at)
"""
_GONE = f"""
    FROM document_entity_scan s JOIN document d ON d.id = s.document_id
    WHERE NOT ({_HAS_TEXT})
"""
_COUNT = text(f"""
    SELECT 'mail' AS work, count(*) AS texts, COALESCE(sum({_MAIL_SIZE}), 0) AS bytes {_MAILS}
    UNION ALL
    SELECT 'document', count(*), COALESCE(sum(octet_length(d.extracted_text)), 0) {_DOCUMENTS}
    UNION ALL
    SELECT 'gone', count(*), 0 {_GONE}
""")
_LIST = {
    "mail": text(f"SELECT m.id, {_MAIL_SIZE} AS size {_MAILS} ORDER BY m.id"),
    "document": text(
        f"SELECT d.id, octet_length(d.extracted_text) AS size {_DOCUMENTS} ORDER BY d.id"
    ),
}
_FORGET_GONE = text(f"""
    DELETE FROM document_entity_scan WHERE document_id IN (SELECT s.document_id {_GONE})
    RETURNING document_id
""")
_TEXTS = {
    "mail": text("""
        SELECT id, subject, body_text, blocks FROM mail WHERE id = ANY(CAST(:ids AS bigint[]))
    """),
    "document": text(f"""
        SELECT d.id, d.extracted_text, d.extracted_at FROM document d
        WHERE d.id = ANY(CAST(:ids AS bigint[])) AND {_HAS_TEXT}
    """),
}
_NEW_ENTITIES = text("""
    INSERT INTO entity (kind, key, label, value, currency, detail)
    SELECT CAST(u.kind AS entity_kind), u.key, u.label, u.value, u.currency, u.detail
    FROM unnest(CAST(:kinds AS text[]), CAST(:keys AS text[]), CAST(:labels AS text[]),
                CAST(:values AS numeric[]), CAST(:currencies AS text[]), CAST(:details AS text[]))
        WITH ORDINALITY AS u(kind, key, label, value, currency, detail, ordinal)
    WHERE NOT EXISTS (
        SELECT 1 FROM entity e WHERE e.kind = CAST(u.kind AS entity_kind) AND e.key = u.key)
    ORDER BY u.ordinal
    ON CONFLICT (kind, key) DO NOTHING
""")
_ENTITY_IDS = text("""
    SELECT e.id, u.ordinal
    FROM unnest(CAST(:kinds AS text[]), CAST(:keys AS text[]))
        WITH ORDINALITY AS u(kind, key, ordinal)
    JOIN entity e ON e.kind = CAST(u.kind AS entity_kind) AND e.key = u.key
""")
_TABLES: dict[Source, tuple[str, str, str]] = {
    "mail": ("mail_entity", "mail_entity_scan", "mail_id"),
    "document": ("document_entity", "document_entity_scan", "document_id"),
}
_FORGET = {
    source: text(f"DELETE FROM {mentions} WHERE {column} = ANY(CAST(:ids AS bigint[]))")
    for source, (mentions, _, column) in _TABLES.items()
}
_MENTIONS = {
    source: text(f"""
        INSERT INTO {mentions} (entity_id, {column}, occurrences, context, position)
        SELECT * FROM unnest(CAST(:entities AS bigint[]), CAST(:sources AS bigint[]),
            CAST(:occurrences AS integer[]), CAST(:contexts AS smallint[]),
            CAST(:positions AS integer[]))
    """)
    for source, (mentions, _, column) in _TABLES.items()
}
_SCANNED = {
    "mail": text("""
        INSERT INTO mail_entity_scan (mail_id, version)
        SELECT unnest(CAST(:ids AS bigint[])), :version
        ON CONFLICT (mail_id) DO UPDATE SET version = EXCLUDED.version
    """),
    "document": text("""
        INSERT INTO document_entity_scan (document_id, version, extracted_at)
        SELECT u.id, :version, u.extracted_at
        FROM unnest(CAST(:ids AS bigint[]), CAST(:extracted AS timestamptz[]))
            AS u(id, extracted_at)
        ON CONFLICT (document_id) DO UPDATE
        SET version = EXCLUDED.version, extracted_at = EXCLUDED.extracted_at
    """),
}


class Progress(Protocol):
    """What the phase counts the bytes of the texts it stored into: the import's step
    (jobrun.Step with unit bytes; its total is Waiting.bytes)."""

    def advance(self, count: int = 1) -> None: ...


class Extractor(Protocol):
    """extract.extract_entities; tests hand in module-level doubles (spawned workers do not see
    monkeypatching)."""

    def __call__(self, text: str) -> list[Found]: ...


@dataclass(frozen=True, slots=True)
class Waiting:
    """The work of the next entities phase."""

    mails: int  # mails to scan
    documents: int  # document texts to scan
    bytes: int  # of their texts: the step's total
    gone: int  # documents scanned before whose text is gone: their mentions are deleted

    def __bool__(self) -> bool:
        return bool(self.mails or self.documents or self.gone)


async def waiting(session: AsyncSession) -> Waiting:
    """What the phase would do now (a few counting queries; no text is read)."""
    rows = {row.work: row for row in await session.execute(_COUNT, {"version": scan_version()})}
    return Waiting(
        mails=rows["mail"].texts,
        documents=rows["document"].texts,
        bytes=int(rows["mail"].bytes) + int(rows["document"].bytes),
        gone=rows["gone"].texts,
    )


def without_blocks(body_text: str | None, blocks: Iterable[Any]) -> str | None:
    """A mail's stored text as the phase scans it (D205): in its standard blocks (mail.blocks,
    ranges of character offsets) every character but a line break becomes a space, so that
    nothing in them is found and every position stays the stored text's. The blocks step
    deletes the scans of the mails whose blocks change, so that they are scanned again."""
    if not body_text:
        return body_text
    pieces: list[str] = []
    start = 0
    for block in blocks:
        lower = max(start, block.lower or 0)
        upper = len(body_text) if block.upper is None else min(block.upper, len(body_text))
        if lower < upper:
            pieces += [body_text[start:lower], _BLANKED.sub(" ", body_text[lower:upper])]
            start = upper
    return "".join([*pieces, body_text[start:]]) if pieces else body_text


@dataclass(slots=True)
class EntityPhaseResult:
    """What one scan_entities did, for its log line and the tests."""

    mails_waiting: int = 0
    documents_waiting: int = 0
    mails: int = 0  # scanned and stored
    documents: int = 0  # scanned and stored
    failed: int = 0  # texts recorded as scanned without entities: they killed or broke the scan
    gone: int = 0  # documents whose text was gone, mentions deleted
    entities: int = 0  # entities new in the database
    mentions: int = 0  # mention rows written
    bytes: int = 0  # of the texts scanned
    seconds: float = 0.0
    stopped: bool = False
    figures: FiguresRefresh | None = None  # None after a stop


async def scan_entities(
    sessionmaker: async_sessionmaker[AsyncSession],
    workers: int,
    stop: asyncio.Event,
    step: Progress,
    *,
    extract: Extractor = extract_entities,
) -> EntityPhaseResult:
    """Scan every waiting text with `workers` processes until done or `stop` is set (module
    docstring); step.advance counts the bytes of the texts stored."""
    started = time.monotonic()
    result = EntityPhaseResult()
    version = scan_version()
    async with sessionmaker() as session, session.begin():
        gone = list((await session.execute(_FORGET_GONE)).scalars())
        if gone:
            await session.execute(_FORGET["document"], {"ids": gone})
        result.gone = len(gone)
        sources: tuple[Source, ...] = ("document", "mail")
        work = {
            source: _WorkList.read(
                source, await session.execute(_LIST[source], {"version": version})
            )
            for source in sources
        }
    result.mails_waiting = len(work["mail"].ids)
    result.documents_waiting = len(work["document"].ids)
    total = work["document"].bytes + work["mail"].bytes
    if (result.mails_waiting or result.documents_waiting) and not stop.is_set():
        count = max(1, min(workers, work["document"].batches + work["mail"].batches))
        log.info(
            "entities: scanning %d mails and %d documents (%.1f MB) with %d workers",
            result.mails_waiting,
            result.documents_waiting,
            total / 1024**2,
            count,
        )
        batches = _batches(work["document"], work["mail"])
        await _Scan(sessionmaker, version, count, step, extract, result).run(batches, stop)
    result.stopped = stop.is_set()
    if not result.stopped:
        async with sessionmaker() as session, session.begin():
            result.figures = await refresh_entity_figures(session)
    result.seconds = time.monotonic() - started
    _log_result(result)
    return result


# Work list -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _WorkList:
    """The ids of the texts of one source to scan and their sizes, compact (400,000 mails)."""

    source: Source
    ids: "array[int]"
    sizes: "array[int]"

    @classmethod
    def read(cls, source: Source, rows: Iterable[Any]) -> "_WorkList":
        ids, sizes = array("q"), array("q")
        for row in rows:
            ids.append(row.id)
            sizes.append(row.size)
        return cls(source, ids, sizes)

    @property
    def bytes(self) -> int:
        return sum(self.sizes)

    @property
    def batches(self) -> int:
        return sum(1 for _ in self.split())

    def split(self) -> Iterator["_Batch"]:
        ids, sizes = self.ids, self.sizes
        start = 0
        while start < len(ids):
            end, size = start + 1, sizes[start]
            while end < len(ids) and end - start < BATCH_TEXTS and size + sizes[end] <= BATCH_BYTES:
                size += sizes[end]
                end += 1
            yield _Batch(self.source, ids[start:end].tolist(), size)
            start = end


@dataclass(slots=True)
class _Batch:
    source: Source
    ids: list[int]
    bytes: int
    texts: list[str] = field(default_factory=list)  # read: of the ids still there, in order
    read: list[int] = field(default_factory=list)  # their ids
    extracted_at: list[datetime | None] = field(default_factory=list)  # documents


def _batches(*lists: _WorkList) -> Iterator[_Batch]:
    for work in lists:
        yield from work.split()


# Worker processes ------------------------------------------------------------------------------

_extract: Extractor | None = None

# What a worker returns for one text: its entities, or why the extraction failed.
_Outcome = list[Found] | str


def _init_worker(extract: Extractor) -> None:
    ignore_interrupts()
    global _extract
    _extract = extract
    prepare()


def _scan(texts: list[str]) -> list[_Outcome]:
    assert _extract is not None, "worker not initialised"
    outcomes: list[_Outcome] = []
    for one in texts:
        try:
            outcomes.append(_extract(one))
        except Exception as error:  # extract_entities never raises: a bug, for this text alone
            outcomes.append(f"the extraction failed: {describe(error)}")
    return outcomes


class _Pool:
    """The worker processes; kill() ends them at once."""

    def __init__(self, count: int, extract: Extractor) -> None:
        context = multiprocessing.get_context("spawn")
        self.count = count
        self._executor = ProcessPoolExecutor(
            count, mp_context=context, initializer=_init_worker, initargs=(extract,)
        )

    def submit(self, texts: list[str]) -> "asyncio.Future[list[_Outcome]]":
        with spawning_workers():
            future = asyncio.get_running_loop().run_in_executor(self._executor, _scan, texts)
        future.add_done_callback(_retrieved)  # batches a stop or a dying worker drops
        return future

    def close(self, kill: bool) -> None:
        if kill:
            kill_workers(self._executor)
        self._executor.shutdown(wait=True, cancel_futures=True)


def _retrieved(future: "asyncio.Future[list[_Outcome]]") -> None:
    """Mark the error of a batch nobody waits for any more as seen, so asyncio logs nothing."""
    if not future.cancelled():
        future.exception()


# Main process ----------------------------------------------------------------------------------


class _Scan:
    """The pool working through the batches in order, storing each as its turn comes."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        version: int,
        count: int,
        step: Progress,
        extract: Extractor,
        result: EntityPhaseResult,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.version = version
        self.count = count
        self.step = step
        self.extract = extract
        self.result = result

    async def run(self, batches: Iterator[_Batch], stop: asyncio.Event) -> None:
        pool: _Pool | None = None
        in_work: deque[tuple[_Batch, asyncio.Future[list[_Outcome]]]] = deque()
        stop_request = asyncio.ensure_future(stop.wait())
        try:
            while not stop.is_set():
                while len(in_work) < self.count * QUEUED and not stop.is_set():
                    batch = next(batches, None)
                    if batch is None:
                        break
                    await self._read(batch)
                    pool = pool or _Pool(self.count, self.extract)
                    in_work.append((batch, pool.submit(batch.texts)))
                if not in_work or stop.is_set():
                    break
                batch, future = in_work[0]
                await _done_or_stopped(future, stop_request)
                if stop.is_set():
                    break
                in_work.popleft()
                try:
                    outcomes = future.result()
                except BrokenProcessPool:
                    assert pool is not None
                    pool.close(kill=True)
                    pool = None
                    suspects = [batch, *(other for other, _ in in_work)]
                    in_work.clear()
                    log.warning(
                        "entities: a worker process died; %d texts in work are scanned again "
                        "one at a time",
                        sum(len(suspect.texts) for suspect in suspects),
                    )
                    await self._alone(suspects, stop)
                    continue
                await self._store(batch, outcomes)
        finally:
            stop_request.cancel()
            if pool is not None:
                pool.close(kill=bool(in_work))

    async def _read(self, batch: _Batch) -> None:
        """The batch's texts from the database; a mail or document gone since is left out."""
        async with self.sessionmaker() as session:
            rows = (await session.execute(_TEXTS[batch.source], {"ids": batch.ids})).all()
            await session.commit()
        by_id = {row.id: row for row in rows}
        for text_id in batch.ids:
            row = by_id.get(text_id)
            if row is None:
                continue
            batch.read.append(text_id)
            if batch.source == "mail":
                body = without_blocks(row.body_text, row.blocks or ())
                batch.texts.append(scanned_text(row.subject, body))
            else:
                batch.texts.append(row.extracted_text)
                batch.extracted_at.append(row.extracted_at)

    async def _alone(self, suspects: Sequence[_Batch], stop: asyncio.Event) -> None:
        """Scan the texts of these batches one at a time in a pool of one worker, and store
        each batch; a text that kills the worker is recorded without entities."""
        pool: _Pool | None = None
        stop_request = asyncio.ensure_future(stop.wait())
        try:
            for batch in suspects:
                outcomes: list[_Outcome] = []
                for one in batch.texts:
                    pool = pool or _Pool(1, self.extract)
                    future = pool.submit([one])
                    await _done_or_stopped(future, stop_request)
                    if stop.is_set():
                        return
                    try:
                        outcomes += future.result()
                    except BrokenProcessPool:
                        pool.close(kill=True)
                        pool = None
                        outcomes.append(_DIED)
                await self._store(batch, outcomes)
        finally:
            stop_request.cancel()
            if pool is not None:
                pool.close(kill=stop.is_set())

    async def _store(self, batch: _Batch, outcomes: Sequence[_Outcome]) -> None:
        """One transaction: the batch's new entities, its mentions instead of the old ones, and
        its scans."""
        entities: dict[tuple[str, str], Found] = {}
        for outcome in outcomes:
            if isinstance(outcome, list):
                for found in outcome:
                    entities.setdefault((found.kind.value, found.key), found)
        order = list(entities.values())
        mentions = _Mentions()
        async with self.sessionmaker() as session, session.begin():
            if order:
                kinds = [found.kind.value for found in order]
                keys = [found.key for found in order]
                created = await session.execute(
                    _NEW_ENTITIES,
                    {
                        "kinds": kinds,
                        "keys": keys,
                        "labels": [found.label for found in order],
                        "values": [found.value for found in order],
                        "currencies": [found.currency for found in order],
                        "details": [found.detail for found in order],
                    },
                )
                self.result.entities += cast(CursorResult[Any], created).rowcount
                rows = await session.execute(_ENTITY_IDS, {"kinds": kinds, "keys": keys})
                ids = {(kinds[row.ordinal - 1], keys[row.ordinal - 1]): row.id for row in rows}
                for text_id, outcome in zip(batch.read, outcomes, strict=True):
                    if isinstance(outcome, list):
                        mentions.add(text_id, outcome, ids)
            await session.execute(_FORGET[batch.source], {"ids": batch.read})
            if mentions.entities:
                await session.execute(_MENTIONS[batch.source], mentions.parameters())
            scanned: dict[str, Any] = {"ids": batch.read, "version": self.version}
            if batch.source == "document":
                scanned["extracted"] = batch.extracted_at
            await session.execute(_SCANNED[batch.source], scanned)
        for text_id, outcome in zip(batch.read, outcomes, strict=True):
            if isinstance(outcome, str):
                self.result.failed += 1
                log.warning("entities: %s %d recorded without entities: %s", batch.source,
                            text_id, outcome)  # fmt: skip
        if batch.source == "mail":
            self.result.mails += len(batch.read)
        else:
            self.result.documents += len(batch.read)
        self.result.mentions += len(mentions.entities)
        self.result.bytes += batch.bytes
        self.step.advance(batch.bytes)


async def _done_or_stopped(
    future: "asyncio.Future[Any]", stop_request: "asyncio.Future[Any]"
) -> None:
    waiting: list[asyncio.Future[Any]] = [future, stop_request]
    await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)


class _Mentions:
    """The mention rows of a batch as the columns _MENTIONS unnests."""

    def __init__(self) -> None:
        self.entities: list[int] = []
        self.sources: list[int] = []
        self.occurrences: list[int] = []
        self.contexts: list[int] = []
        self.positions: list[int] = []

    def add(self, source_id: int, found: list[Found], ids: dict[tuple[str, str], int]) -> None:
        for one in found:
            self.entities.append(ids[one.kind.value, one.key])
            self.sources.append(source_id)
            self.occurrences.append(one.occurrences)
            self.contexts.append(int(one.context))
            self.positions.append(one.position)

    def parameters(self) -> dict[str, list[int]]:
        return {
            "entities": self.entities,
            "sources": self.sources,
            "occurrences": self.occurrences,
            "contexts": self.contexts,
            "positions": self.positions,
        }


def _log_result(result: EntityPhaseResult) -> None:
    gone = f", {result.gone} documents without text forgotten" if result.gone else ""
    if not (result.mails_waiting or result.documents_waiting or result.stopped):
        log.info("entities: nothing to scan%s", gone)
    else:
        rate = result.bytes / 1024**2 / result.seconds if result.seconds > 0 else 0.0
        log.info(
            "entities: %s%d of %d mails and %d of %d documents scanned in %.1f s (%.1f MB/s), "
            "%d new entities, %d mentions%s%s",
            "stopped; " if result.stopped else "",
            result.mails,
            result.mails_waiting,
            result.documents,
            result.documents_waiting,
            result.seconds,
            rate,
            result.entities,
            result.mentions,
            f", {result.failed} texts without entities after errors" if result.failed else "",
            gone,
        )
    if result.figures is not None:
        log.info(
            "entities: figures of %d entities changed, %d entities no longer mentioned deleted",
            result.figures.updated,
            result.figures.deleted,
        )

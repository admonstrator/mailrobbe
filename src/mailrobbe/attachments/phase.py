"""The attachments phase of an import: the text of each document, read and extracted once (D72).

After finalize, the import works through the documents waiting for their text:

    work list   documents pending or unreadable, too_large ones the size limit now admits, and
                those an older EXTRACTOR_VERSION extracted (not those unsupported by their kind,
                which finalize decided without reading them)
    order       the occurrence content.document_sources picks for each, sorted by MBOX file and
                offset, so that every file is read front to back
    too large   above MAILROBBE_ATTACHMENT_TEXT_MAX_SIZE: too_large, without a read
    workers     spawned processes, as many as the import has; each reads one document's bytes
                (content.read_attachment) and extracts its text (extract.extract_document, which
                runs the reader of its format in a child process with time and memory limits).
                A missing or changed MBOX file makes the document unreadable, tried again at the
                next import; a text extracted before stays until its file can be read again.
    store       the results in batches, one transaction each, with EXTRACTOR_VERSION; a text
                whose tsvector PostgreSQL refuses (above 1 MB) is halved until it fits, on its
                own, so that one document never fails a batch

The worker that has a document's bytes also reads its metadata (metadata.read_metadata, D167)
when that waits too, so a new import reads each document once. The metadata step after it
(collect_metadata) uses the same workers, order and batches for the documents left: those not
read for their text (images, documents extracted before), and those read by an older
METADATA_VERSION. Documents of a kind or format without metadata it reads are unsupported at
once, those above the text extraction's size limit too_large (read again once the limit admits
them), without a read; a missing or changed MBOX file leaves the metadata as it was, tried again
at the next import.

A stop (Ctrl-C, SIGTERM or the dashboard, D46) kills the workers at once together with their
extraction children: each worker leads a process group of its own, which the main process kills.
The results that came back are stored, the documents in work stay waiting, and the next import
continues with them. A worker that dies otherwise (out of memory, a crash) takes the documents in
work with it: they are tried again one at a time, and one that kills its worker alone is failed.
"""

import asyncio
import json
import logging
import multiprocessing
import os
import signal
import time
from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import suppress
from dataclasses import dataclass, field
from multiprocessing.sharedctypes import SynchronizedArray
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import TextClause, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.attachments.content import (
    AttachmentChanged,
    AttachmentSource,
    document_sources,
    read_attachment,
)
from mailrobbe.attachments.extract import Extraction, ExtractionLimits, extract_document
from mailrobbe.attachments.metadata import METADATA_VERSION, MetadataLimits, read_metadata
from mailrobbe.attachments.metadata.model import (
    Fields,
    Reading,
    Summary,
    clean,
    may_carry,
    summarize,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import DOCUMENT_TEXT_LIMIT, EXTRACTOR_VERSION
from mailrobbe.enums import DocumentKind, DocumentMetadataStatus, DocumentTextStatus
from mailrobbe.jobrun import Step, describe, ignore_interrupts, spawning_workers

if TYPE_CHECKING:  # not at run time: the spawned workers import this module, and need little
    from mailrobbe.importer.runner import ImportFigures

log = logging.getLogger(__name__)

BATCH = 100  # documents per transaction at most
BATCH_CHARACTERS = 4_000_000  # characters of text per transaction at most
BATCH_SECONDS = 5.0  # a result waits at most about this long for its transaction
SOURCES_PAGE = 10_000  # documents per lookup of the occurrences to read
QUEUED = 2  # documents handed to the pool per worker, so that no worker waits for the next
_TOO_LONG = "54000"  # SQLSTATE program_limit_exceeded: "string is too long for tsvector"
_DIED = "the worker process died while extracting it"

S = DocumentTextStatus
M = DocumentMetadataStatus
# Statuses the phase decides without an extraction; any other one came from an extractor.
_NOT_EXTRACTED = frozenset({S.PENDING, S.UNREADABLE, S.TOO_LARGE})

_WAITING = text("""
    SELECT id, name, mime_type, size_bytes, text_status::text AS text_status, kind::text AS kind,
        metadata_version < :metadata_version AS metadata
    FROM document
    WHERE text_status IN ('pending', 'unreadable')
       OR (text_status = 'too_large' AND size_bytes <= :max_size)
       OR (extractor_version BETWEEN 1 AND :version - 1 AND size_bytes <= :max_size
           AND text_status NOT IN ('pending', 'unreadable', 'too_large'))
    ORDER BY id
""")
_STORE = text("""
    UPDATE document d SET text_status = CAST(u.status AS document_text_status),
        extracted_text = u.text, text_truncated = u.truncated, text_error = u.error,
        pages = u.pages, kind = COALESCE(CAST(u.kind AS document_kind), d.kind),
        extractor_version = :version, extracted_at = now()
    FROM unnest(CAST(:ids AS bigint[]), CAST(:statuses AS text[]), CAST(:texts AS text[]),
                CAST(:truncated AS boolean[]), CAST(:errors AS text[]),
                CAST(:pages AS integer[]), CAST(:kinds AS text[]))
        AS u(id, status, text, truncated, error, pages, kind)
    WHERE d.id = u.id
""")
_METADATA_WAITING = text("""
    SELECT id, name, mime_type, size_bytes, text_status::text AS text_status, kind::text AS kind,
        true AS metadata
    FROM document
    WHERE metadata_version < :version
       OR (metadata_status = 'too_large' AND size_bytes <= :max_size)
    ORDER BY id
""")
_STORE_METADATA = text("""
    UPDATE document d SET metadata_status = CAST(u.status AS document_metadata_status),
        metadata_fields = CAST(u.fields AS jsonb), metadata_error = u.error,
        metadata_author = u.author, metadata_modified_by = u.modified_by,
        metadata_program = u.program, metadata_device = u.device, metadata_created = u.created,
        metadata_gps = u.gps, metadata_version = :version
    FROM unnest(CAST(:ids AS bigint[]), CAST(:statuses AS text[]), CAST(:fields AS text[]),
                CAST(:errors AS text[]), CAST(:authors AS text[]), CAST(:modified_by AS text[]),
                CAST(:programs AS text[]), CAST(:devices AS text[]),
                CAST(:created AS timestamptz[]), CAST(:gps AS boolean[]))
        AS u(id, status, fields, error, author, modified_by, program, device, created, gps)
    WHERE d.id = u.id
""")


@dataclass(frozen=True, slots=True)
class WaitingDocument:
    """A document whose text the phase extracts (or decides too large), or whose metadata the
    metadata step reads."""

    id: int
    name: str | None  # the file name used most, which the extraction classifies by
    mime_type: str
    size_bytes: int
    text_status: DocumentTextStatus
    kind: DocumentKind | None = None
    metadata: bool = False  # its metadata waits too (METADATA_VERSION)


async def waiting_documents(session: AsyncSession, max_size: int) -> list[WaitingDocument]:
    """The documents waiting for their text (the module docstring's work list), by id."""
    parameters = {
        "max_size": max_size,
        "version": EXTRACTOR_VERSION,
        "metadata_version": METADATA_VERSION,
    }
    return await _documents(session, _WAITING, parameters)


async def metadata_waiting(session: AsyncSession, max_size: int) -> list[WaitingDocument]:
    """The documents waiting for their metadata (D167), by id."""
    parameters = {"max_size": max_size, "version": METADATA_VERSION}
    return await _documents(session, _METADATA_WAITING, parameters)


async def _documents(
    session: AsyncSession, statement: TextClause, parameters: dict[str, Any]
) -> list[WaitingDocument]:
    rows = await session.execute(statement, parameters)
    await session.commit()
    return [
        WaitingDocument(
            row.id,
            row.name,
            row.mime_type,
            row.size_bytes,
            S(row.text_status),
            None if row.kind is None else DocumentKind(row.kind),
            row.metadata,
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class PhaseResult:
    total: int  # documents waiting at the start
    stored: int  # documents stored by this run, with or without text (or metadata)
    statuses: dict[str, int]  # of those: text statuses (or metadata statuses)
    seconds: float


# Worker processes ------------------------------------------------------------------------------


class Extractor(Protocol):
    """extract.extract_document; tests hand in module-level doubles (spawned workers do not see
    monkeypatching)."""

    def __call__(
        self, data: bytes, filename: str | None, mime_type: str, limits: ExtractionLimits
    ) -> Extraction: ...


class MetadataReader(Protocol):
    """metadata.read_metadata, or a module-level double."""

    def __call__(
        self, data: bytes, filename: str | None, mime_type: str, limits: MetadataLimits
    ) -> Reading: ...


@dataclass(frozen=True, slots=True)
class _Task:
    document: WaitingDocument
    source: AttachmentSource
    text: bool = True  # extract its text
    metadata: bool = False  # read its metadata


@dataclass(frozen=True, slots=True)
class _Outcome:
    extraction: Extraction | None  # None: the bytes could not be read, or no text asked for
    problem: str | None = None  # why the bytes could not be read, one line
    reading: Reading | None = None  # its metadata, when asked for and read


@dataclass(frozen=True, slots=True)
class _WorkerState:
    mbox_dir: Path
    limits: ExtractionLimits
    extract: Extractor
    read: MetadataReader
    metadata_limits: MetadataLimits


_state: _WorkerState | None = None


def _init_worker(state: _WorkerState, pids: "SynchronizedArray[int]") -> None:
    ignore_interrupts()
    # A group of its own: its extraction children join it, and a stop kills the whole group.
    os.setpgrp()
    with pids.get_lock():
        pids[pids[:].index(0)] = os.getpid()
    global _state
    _state = state


def _extract(task: _Task) -> _Outcome:
    assert _state is not None, "worker not initialised"
    try:
        data = read_attachment(_state.mbox_dir, task.source)
    except (OSError, AttachmentChanged) as error:
        return _Outcome(None, describe(error))
    document = task.document
    extraction = reading = None
    if task.text:
        try:
            extraction = _state.extract(data, document.name, document.mime_type, _state.limits)
        except Exception as error:  # extract_document never raises for a bad document: a bug
            extraction = Extraction(S.FAILED, error=f"extraction failed: {describe(error)}")
    if task.metadata:
        try:
            limits = _state.metadata_limits
            reading = _state.read(data, document.name, document.mime_type, limits)
        except Exception as error:  # read_metadata never raises either
            reading = Reading(M.FAILED, error=f"reading failed: {describe(error)}")
    return _Outcome(extraction, reading=reading)


class _Pool:
    """The worker processes; kill() ends them and whatever they started at once."""

    def __init__(self, count: int, state: _WorkerState) -> None:
        context = multiprocessing.get_context("spawn")
        self.count = count
        self._pids: SynchronizedArray[int] = context.Array("q", count)
        self._executor = ProcessPoolExecutor(
            count, mp_context=context, initializer=_init_worker, initargs=(state, self._pids)
        )

    def submit(self, task: _Task) -> "asyncio.Future[_Outcome]":
        with spawning_workers():
            future = asyncio.get_running_loop().run_in_executor(self._executor, _extract, task)
        future.add_done_callback(_retrieved)  # tasks a stop or a dying worker drops
        return future

    def kill(self) -> None:
        # The workers are not reaped before shutdown, so their ids are still theirs.
        for pid in self._pids[:]:
            if pid:
                with suppress(ProcessLookupError, PermissionError):
                    os.killpg(pid, signal.SIGKILL)

    def close(self, kill: bool) -> None:
        if kill:
            self.kill()
        self._executor.shutdown(wait=True, cancel_futures=True)


def _retrieved(future: "asyncio.Future[_Outcome]") -> None:
    """Mark the error of a task nobody waits for any more as seen, so asyncio logs nothing."""
    if not future.cancelled():
        future.exception()


# Main process ----------------------------------------------------------------------------------


async def extract_texts(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    waiting: Sequence[WaitingDocument],
    workers: int,
    stop: asyncio.Event,
    figures: "ImportFigures",
    step: Step,
    *,
    extract: Extractor = extract_document,
    read: MetadataReader = read_metadata,
) -> PhaseResult:
    """Extract and store the texts of these documents until done or `stop` is set, and the
    metadata of those whose metadata waits too.

    figures follows the workers running, step the documents stored.
    """
    started = time.monotonic()
    max_size = int(settings.attachment_text_max_size)
    store = _Store(sessionmaker, step, "attachments")
    for document in waiting:
        if document.size_bytes > max_size:
            await store.add(_Row(document.id, S.TOO_LARGE), None)
    readable = [document for document in waiting if document.size_bytes <= max_size]
    tasks = await _tasks(sessionmaker, readable, text=True)
    if tasks and not stop.is_set():
        log.info(
            "extracting the text of %d documents (%.1f MB) with %d workers",
            len(tasks),
            sum(task.source.size_bytes for task in tasks) / 1024**2,
            min(workers, len(tasks)),
        )
        state = _worker_state(settings, mbox_dir, extract, read)
        await _Work(store, figures, tasks, min(workers, len(tasks)), state).run(stop)
    await store.flush()
    store.warn_unreadable()
    seconds = time.monotonic() - started
    result = PhaseResult(len(waiting), store.stored, dict(store.statuses), seconds)
    _log_result(result, stop.is_set())
    return result


async def collect_metadata(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    waiting: Sequence[WaitingDocument],
    workers: int,
    stop: asyncio.Event,
    figures: "ImportFigures",
    step: Step,
    *,
    read: MetadataReader = read_metadata,
) -> PhaseResult:
    """The metadata step (D167): read and store the metadata of these documents until done or
    `stop` is set; see the module docstring. step counts the documents stored."""
    started = time.monotonic()
    max_size = int(settings.attachment_text_max_size)
    store = _Store(sessionmaker, step, "metadata of attachments")
    readable = []
    for document in waiting:
        if not may_carry(document.kind, document.name, document.mime_type):
            await store.add(None, _Meta(document.id, M.UNSUPPORTED))
        elif document.size_bytes > max_size:
            await store.add(None, _Meta(document.id, M.TOO_LARGE))
        else:
            readable.append(document)
    tasks = await _tasks(sessionmaker, readable, text=False)
    if tasks and not stop.is_set():
        log.info(
            "reading the metadata of %d documents (%.1f MB) with %d workers",
            len(tasks),
            sum(task.source.size_bytes for task in tasks) / 1024**2,
            min(workers, len(tasks)),
        )
        state = _worker_state(settings, mbox_dir, extract_document, read)
        await _Work(store, figures, tasks, min(workers, len(tasks)), state).run(stop)
    await store.flush()
    store.warn_unreadable()
    seconds = time.monotonic() - started
    result = PhaseResult(len(waiting), store.metadata_stored, dict(store.metadata), seconds)
    rate = result.stored / max(result.seconds, 1e-9)
    log.info(
        "%s: %d of %d documents stored in %.1f s (%.1f documents/s)%s",
        "metadata stopped" if stop.is_set() else "metadata done",
        result.stored,
        result.total,
        result.seconds,
        rate,
        _statuses(result.statuses, M),
    )
    return result


def _worker_state(
    settings: Settings, mbox_dir: Path, extract: Extractor, read: MetadataReader
) -> _WorkerState:
    timeout, memory = settings.attachment_text_timeout, int(settings.attachment_text_memory)
    limits = ExtractionLimits(max_chars=DOCUMENT_TEXT_LIMIT, timeout=timeout, memory=memory)
    return _WorkerState(mbox_dir, limits, extract, read, MetadataLimits(timeout, memory))


async def _tasks(
    sessionmaker: async_sessionmaker[AsyncSession],
    documents: Sequence[WaitingDocument],
    *,
    text: bool,
) -> list[_Task]:
    """A task per document with its occurrence to read, in file and offset order: its text
    when `text`, its metadata when it waits."""
    by_id = {document.id: document for document in documents}
    ids = list(by_id)
    sources: dict[int, AttachmentSource] = {}
    async with sessionmaker() as session:
        for start in range(0, len(ids), SOURCES_PAGE):
            sources.update(await document_sources(session, ids[start : start + SOURCES_PAGE]))
        await session.commit()
    tasks = [
        _Task(by_id[document_id], source, text, by_id[document_id].metadata)
        for document_id, source in sources.items()
    ]
    # Python orders str by code point, as PostgreSQL's "C" collation orders UTF-8.
    tasks.sort(key=lambda task: (task.source.path, task.source.byte_offset, task.source.position))
    return tasks


class _Work:
    """The pool working through the tasks, in order, until done or stopped."""

    def __init__(
        self,
        store: "_Store",
        figures: "ImportFigures",
        tasks: Iterable[_Task],
        count: int,
        state: _WorkerState,
    ) -> None:
        self.store = store
        self.figures = figures
        self.queue = deque(tasks)
        self.count = count
        self.state = state
        self.running: dict[asyncio.Future[_Outcome], _Task] = {}
        # Documents in work when a worker died: each one is tried again alone.
        self.suspects: set[int] = set()

    async def run(self, stop: asyncio.Event) -> None:
        pool = _Pool(self.count, self.state)
        stop_request = asyncio.ensure_future(stop.wait())
        try:
            while (self.queue or self.running) and not stop.is_set():
                self._hand_out(pool)
                self.figures.workers = pool.count
                waiting: list[asyncio.Future[Any]] = [*self.running, stop_request]
                done, _ = await asyncio.wait(
                    waiting, timeout=BATCH_SECONDS, return_when=asyncio.FIRST_COMPLETED
                )
                died = False
                for future in [future for future in done if future in self.running]:
                    task = self.running.pop(future)
                    try:
                        outcome = future.result()
                    except BrokenProcessPool:
                        died = True
                        self.running[future] = task  # with the others in work, below
                        continue
                    except Exception as error:  # the result did not come back
                        outcome = _failed(task, describe(error))
                    await self.store.done(task, outcome)
                if died and not stop.is_set():
                    pool.close(kill=True)  # their extraction children too
                    await self._retry_alone()
                    pool = _Pool(self.count, self.state)
                await self.store.flush_when_due()
        finally:
            stop_request.cancel()
            pool.close(kill=bool(self.running))
            self.figures.workers = 0

    def _hand_out(self, pool: _Pool) -> None:
        """Hand the next tasks to the pool; a suspect only when nothing else is in work, and
        then alone."""
        while self.queue and len(self.running) < self.count * QUEUED:
            if self.suspects & {task.document.id for task in self.running.values()}:
                return
            task = self.queue[0]
            if task.document.id in self.suspects and self.running:
                return
            self.queue.popleft()
            self.running[pool.submit(task)] = task
            if task.document.id in self.suspects:
                return

    async def _retry_alone(self) -> None:
        """The tasks in work died with a worker: each is tried again alone, unless it was."""
        died = list(self.running.values())
        self.running.clear()
        log.warning("a worker process died; %d documents in work are tried again", len(died))
        for task in reversed(died):
            if task.document.id in self.suspects:
                log.warning("document %d failed: %s", task.document.id, _DIED)
                await self.store.done(task, _failed(task, _DIED))
            else:
                self.suspects.add(task.document.id)
                self.queue.appendleft(task)


@dataclass(frozen=True, slots=True)
class _Row:
    """What is stored for one document."""

    document_id: int
    status: DocumentTextStatus
    text: str | None = None
    truncated: bool = False
    error: str | None = None
    pages: int | None = None
    kind: DocumentKind | None = None
    source: AttachmentSource | None = None  # of an unreadable one, for the warning


def _row(task: _Task, outcome: _Outcome) -> _Row | None:
    """The row to store; None leaves the document as it is (an older extraction whose file
    cannot be read now keeps its text, and is tried again at the next import)."""
    extraction = outcome.extraction
    if extraction is None:
        if task.document.text_status not in _NOT_EXTRACTED:
            return None
        return _Row(task.document.id, S.UNREADABLE, error=outcome.problem, source=task.source)
    return _Row(
        task.document.id,
        extraction.status,
        _clean(extraction.text) or None,
        extraction.truncated,
        extraction.error,
        extraction.pages,
        extraction.kind,
    )


@dataclass(frozen=True, slots=True)
class _Meta:
    """What is stored of one document's metadata."""

    document_id: int
    status: DocumentMetadataStatus
    fields: Fields = field(default_factory=dict)
    error: str | None = None


def _meta(task: _Task, outcome: _Outcome) -> _Meta | None:
    """The metadata to store; None leaves it as it is (the file cannot be read now: tried again
    at the next import)."""
    reading = outcome.reading
    if reading is None:
        return None
    return _Meta(task.document.id, reading.status, reading.fields, reading.error)


def _failed(task: _Task, error: str) -> _Outcome:
    """The outcome of a task whose result never came: failed, for what it was to do."""
    extraction = Extraction(S.FAILED, error=error) if task.text else None
    return _Outcome(extraction, reading=Reading(M.FAILED, error=error) if task.metadata else None)


def _clean(value: str) -> str:
    """Text PostgreSQL can store: no NUL, no lone surrogates (the extractors should give none)."""
    return value.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")


class _Store:
    """Texts and metadata in batches, one transaction each; step counts the documents stored.
    `what` names the files' contents in the warning about unreadable ones."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], step: Step, what: str
    ) -> None:
        self._sessionmaker = sessionmaker
        self._step = step
        self._what = what
        self._rows: list[_Row] = []
        self._metas: list[_Meta] = []
        self._documents = 0
        self._characters = 0
        self._since = 0.0
        self.stored = 0
        self.metadata_stored = 0
        self.statuses: Counter[str] = Counter()
        self.metadata: Counter[str] = Counter()  # metadata statuses stored
        self._unreadable: dict[str, list[tuple[int, str | None]]] = {}  # file: (offset, why)

    async def done(self, task: _Task, outcome: _Outcome) -> None:
        """One document's outcome, as the task asked for its text, its metadata or both."""
        if outcome.problem is not None and not task.text:  # a text row notes it itself
            self._note(task.source, outcome.problem)
        row = _row(task, outcome) if task.text else None
        await self.add(row, _meta(task, outcome) if task.metadata else None)

    async def add(self, row: _Row | None, meta: _Meta | None) -> None:
        if row is None and meta is None:
            self._step.advance()
            return
        if not self._documents:
            self._since = time.monotonic()
        self._documents += 1
        if row is not None:
            self._rows.append(row)
            self._characters += len(row.text or "")
        if meta is not None:
            self._metas.append(meta)
        if self._documents >= BATCH or self._characters >= BATCH_CHARACTERS:
            await self.flush()

    async def flush_when_due(self) -> None:
        if self._documents and time.monotonic() - self._since >= BATCH_SECONDS:
            await self.flush()

    async def flush(self) -> None:
        rows, metas, documents = self._rows, self._metas, self._documents
        self._rows, self._metas, self._documents, self._characters = [], [], 0, 0
        if not documents:
            return
        async with self._sessionmaker() as session:
            if rows:
                await _write(session, rows)
            if metas:
                metas = await _write_metadata(session, metas)
        self.stored += len(rows)
        self.metadata_stored += len(metas)
        self._step.advance(documents)
        self.statuses.update(row.status for row in rows)
        self.metadata.update(meta.status for meta in metas)
        for row in rows:
            if row.source is not None:
                self._note(row.source, row.error)

    def _note(self, source: AttachmentSource, problem: str | None) -> None:
        self._unreadable.setdefault(source.path, []).append((source.byte_offset, problem))

    def warn_unreadable(self) -> None:
        """One warning per MBOX file whose attachments could not be read."""
        for path, found in sorted(self._unreadable.items()):
            offset, problem = min(found, key=lambda each: each[0])
            log.warning(
                "%s in %s not read: %d documents, the first in the mail at byte %d: %s; "
                "they are tried again at the next import",
                self._what,
                path,
                len(found),
                offset,
                problem,
            )


async def _write(session: AsyncSession, rows: Sequence[_Row]) -> None:
    """One transaction for the rows; when a tsvector is too long, each row alone, halving the
    text that is too long until it fits."""
    try:
        async with session.begin():
            await session.execute(_STORE, _parameters(rows))
        return
    except DBAPIError as error:
        if not _too_long(error):
            raise
    for row in rows:
        while True:
            try:
                async with session.begin():
                    await session.execute(_STORE, _parameters([row]))
                break
            except DBAPIError as error:
                if not (_too_long(error) and row.text):
                    raise
                kept = len(row.text) // 2
                log.info(
                    "document %d: the tsvector of its text is above PostgreSQL's limit of 1 MB, "
                    "keeping %d characters",
                    row.document_id,
                    kept,
                )
                row = _Row(
                    row.document_id,
                    row.status,
                    row.text[:kept],
                    True,
                    row.error,
                    row.pages,
                    row.kind,
                    row.source,
                )


async def _write_metadata(session: AsyncSession, metas: list[_Meta]) -> list[_Meta]:
    """One transaction for the metadata; when PostgreSQL refuses it, each document alone, and one
    refused again as failed without its fields. The metadata as stored."""
    try:
        async with session.begin():
            await session.execute(_STORE_METADATA, _metadata_parameters(metas))
        return metas
    except DBAPIError:
        pass
    stored = []
    for meta in metas:
        try:
            async with session.begin():
                await session.execute(_STORE_METADATA, _metadata_parameters([meta]))
        except DBAPIError as error:
            why = clean(f"cannot be stored: {error.orig}", 300)
            log.warning("document %d: its metadata %s", meta.document_id, why)
            meta = _Meta(meta.document_id, M.FAILED, error=why)
            async with session.begin():
                await session.execute(_STORE_METADATA, _metadata_parameters([meta]))
        stored.append(meta)
    return stored


def _too_long(error: DBAPIError) -> bool:
    return getattr(error.orig, "sqlstate", None) == _TOO_LONG


def _parameters(rows: Sequence[_Row]) -> dict[str, Any]:
    return {
        "version": EXTRACTOR_VERSION,
        "ids": [row.document_id for row in rows],
        "statuses": [row.status.value for row in rows],
        "texts": [row.text for row in rows],
        "truncated": [row.truncated for row in rows],
        "errors": [row.error for row in rows],
        "pages": [row.pages for row in rows],
        "kinds": [None if row.kind is None else row.kind.value for row in rows],
    }


def _metadata_parameters(metas: Sequence[_Meta]) -> dict[str, Any]:
    summaries = [summarize(meta.fields) if meta.fields else Summary() for meta in metas]
    return {
        "version": METADATA_VERSION,
        "ids": [meta.document_id for meta in metas],
        "statuses": [meta.status.value for meta in metas],
        "fields": [
            json.dumps(meta.fields, ensure_ascii=False) if meta.fields else None for meta in metas
        ],
        "errors": [None if meta.error is None else _clean(meta.error) for meta in metas],
        "authors": [summary.author for summary in summaries],
        "modified_by": [summary.modified_by for summary in summaries],
        "programs": [summary.program for summary in summaries],
        "devices": [summary.device for summary in summaries],
        "created": [summary.created for summary in summaries],
        "gps": [summary.gps for summary in summaries],
    }


def _statuses(counts: Mapping[str, int], order: Iterable[str]) -> str:
    """ ": text 3, empty 1", the statuses with documents in order; "" without any."""
    found = ", ".join(f"{status} {counts[status]}" for status in order if counts.get(status))
    return f": {found}" if found else ""


def _log_result(result: PhaseResult, stopped: bool) -> None:
    rate = result.stored / max(result.seconds, 1e-9)
    log.info(
        "%s: %d of %d documents stored in %.1f s (%.1f documents/s)%s",
        "attachments stopped" if stopped else "attachments done",
        result.stored,
        result.total,
        result.seconds,
        rate,
        _statuses(result.statuses, S),
    )

"""The worker pool: one MBOX file per task, resumable after every committed batch (D15).

The main process hands out files, largest first, one to each idle worker. A worker process
(spawned, so it imports everything afresh and gets all it needs through the pool initializer)
reads its file from bytes_done to the end: iter_records -> parse_record -> DKIM check -> Batch
-> Store. When asked to stop (Ctrl-C, SIGTERM or the dashboard), the main process hands out no
more files and every worker stores the batch it holds and marks its file paused. A killed
worker loses at most its uncommitted batch; the next scan finds its file still running and
resumes it.

ImportFigures gathers the run's live figures for its job row (jobs.ImportProgress, D47): the
totals of the run's files from mbox_file, the files running and ended, and the mails with a DKIM
verdict, which the workers add to a shared counter per committed batch.
"""

import asyncio
import logging
import multiprocessing
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from multiprocessing.queues import Queue
from multiprocessing.sharedctypes import Synchronized
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import Any, BinaryIO, NamedTuple, Protocol

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mailrobbe.config import Settings
from mailrobbe.enums import ImportErrorKind, MboxStatus
from mailrobbe.importer import dkim_hook, parse, split
from mailrobbe.importer.dkim_hook import DkimVerdict
from mailrobbe.importer.finalize import finalize
from mailrobbe.importer.model import Issue, ParsedMail
from mailrobbe.importer.scan import ScannedFile
from mailrobbe.importer.split import MboxRecord
from mailrobbe.importer.store import Batch, Store
from mailrobbe.jobrun import RateWindow, describe, ignore_interrupts, spawning_workers
from mailrobbe.jobs import Executor, ImportProgress

log = logging.getLogger(__name__)

PROGRESS_SECONDS = 5.0  # a log line this often while files are imported
FINALIZE_SECONDS = 600.0  # during a long import, finalize after a file when this much older


class RecordReader(Protocol):
    def __call__(
        self, handle: BinaryIO, start: int = 0, *, max_size: int
    ) -> Iterator[MboxRecord]: ...


class RecordParser(Protocol):
    def __call__(self, record: MboxRecord, *, attachment_hash_limit: int) -> ParsedMail: ...


@dataclass(frozen=True, slots=True)
class Pipeline:
    """How a worker reads and parses records; tests hand in module-level doubles."""

    iter_records: RecordReader = split.iter_records
    parse_record: RecordParser = parse.parse_record


DEFAULT_PIPELINE = Pipeline()


@dataclass(frozen=True, slots=True)
class FileTask:
    mbox_file_id: int
    path: str  # relative to the MBOX directory


@dataclass(frozen=True, slots=True)
class FileOutcome:
    path: str
    status: MboxStatus  # done, paused or error
    bytes_done: int
    mails: int  # stored by this task
    issues: int  # import errors stored by this task
    error: str | None = None  # why the file ended in error


# Worker processes ---------------------------------------------------------------------------


class _Worker:
    """State of one worker process, created once by the pool initializer."""

    def __init__(
        self,
        settings: Settings,
        preload: Any,
        mbox_dir: Path,
        pipeline: Pipeline,
        worker_id: int,
        stop: Event,
        dkim_checked: "Synchronized[int]",
    ) -> None:
        self.mbox_dir = mbox_dir
        self.pipeline = pipeline
        self.worker_id = worker_id
        self.max_size = int(settings.import_max_mail_size)
        self.hash_limit = int(settings.import_attachment_hash_limit)
        self.checker = dkim_hook.create_checker(settings, preload)
        self.store = Store(self.checker)
        self._stop = stop
        self._dkim_checked = dkim_checked
        self._parent = multiprocessing.parent_process()
        # NullPool: every task runs in its own event loop, so no connection may outlive one.
        self.engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)

    def stopping(self) -> bool:
        """A stop request, or the main process is gone (then nobody would record the end)."""
        return self._stop.is_set() or (self._parent is not None and not self._parent.is_alive())

    async def import_file(self, task: FileTask) -> FileOutcome:
        async with self.engine.connect() as connection:
            session = AsyncSession(bind=connection, expire_on_commit=False)
            async with session.begin():
                start = await session.scalar(
                    text(
                        "UPDATE mbox_file SET status = 'running', worker_id = :worker, "
                        "started_at = now(), finished_at = NULL WHERE id = :id RETURNING bytes_done"
                    ),
                    {"id": task.mbox_file_id, "worker": self.worker_id},
                )
            assert start is not None, f"no mbox_file row {task.mbox_file_id}"
            run = _FileImport(self, session, task, start)
            try:
                status = await run.run()
            except Exception as error:  # a broken mail never gets here; the database or a bug
                run.error = Issue(ImportErrorKind.INTERNAL, f"import stopped: {describe(error)}")
                status = MboxStatus.ERROR
            await _end_file(session, task.mbox_file_id, status, run.stored, run.error)
        message = None if run.error is None else run.error.message
        return FileOutcome(task.path, status, run.stored, run.mails, run.issues, message)

    def count_verdicts(self, count: int) -> None:
        """Mails of a committed batch that got a DKIM verdict, for ImportFigures."""
        with self._dkim_checked.get_lock():
            self._dkim_checked.value += count

    def examine(self, record: MboxRecord) -> tuple[ParsedMail, DkimVerdict | None, list[Issue]]:
        """Parse and DKIM-check a record; neither stops the import, whatever the record holds."""
        issues: list[Issue] = []
        try:
            mail = self.pipeline.parse_record(record, attachment_hash_limit=self.hash_limit)
        except Exception as error:
            mail = _unparsed()
            issues.append(Issue(ImportErrorKind.PARSE, f"parser failed: {describe(error)}"))
        verdict = None
        if self.checker is not None and not record.truncated:
            try:
                verdict = self.checker.check(record.message)
            except Exception as error:
                issues.append(Issue(ImportErrorKind.DKIM, f"DKIM check failed: {describe(error)}"))
        return mail, verdict, issues


class _FileImport:
    """One file in one worker: from its progress to the end, or until a stop request."""

    def __init__(self, worker: _Worker, session: AsyncSession, task: FileTask, start: int):
        self.worker = worker
        self.session = session
        self.task = task
        self.position = start  # end of the last record read
        self.stored = start  # end of the last record committed: the file's progress
        self.mails = 0
        self.issues = 0
        self.error: Issue | None = None
        self._batch = Batch()

    async def run(self) -> MboxStatus:
        """DONE, PAUSED, or ERROR when the file cannot be read (self.error says why).

        Only reading is guarded here: an OSError from the database must not pass for a broken
        disk, so it propagates.
        """
        worker = self.worker
        try:
            handle = (worker.mbox_dir / self.task.path).open("rb")
        except OSError as error:
            return self._unreadable(error)
        with handle:
            records = worker.pipeline.iter_records(handle, self.position, max_size=worker.max_size)
            while True:
                try:
                    record = next(records, None)
                except OSError as error:
                    await self._flush()
                    return self._unreadable(error)
                if record is None:
                    break
                self._batch.add(record, *worker.examine(record))
                self.position = record.byte_offset + record.byte_length
                if worker.stopping():
                    await self._flush()
                    return MboxStatus.PAUSED
                if self._batch.is_full():
                    await self._flush()
        await self._flush()
        return MboxStatus.DONE

    async def _flush(self) -> None:
        batch = self._batch
        if not batch:
            return
        await self.worker.store.write(self.session, self.task.mbox_file_id, batch)
        self.worker.count_verdicts(batch.verdict_count)
        self.stored = batch.end
        self.mails += len(batch)
        self.issues += batch.issue_count
        self._batch = Batch()

    def _unreadable(self, error: OSError) -> MboxStatus:
        reason = error.strerror or describe(error)
        self.error = Issue(ImportErrorKind.IO, f"cannot read {self.task.path}: {reason}")
        return MboxStatus.ERROR


def _unparsed() -> ParsedMail:
    """What is stored for a record the parser failed on: framing, hash and nothing else."""
    return ParsedMail(None, None, (), None, None, (), (), (), (), None, (), ())


async def _end_file(
    session: AsyncSession, file_id: int, status: MboxStatus, offset: int, error: Issue | None
) -> None:
    async with session.begin():
        if error is not None:
            await session.execute(
                text(
                    "INSERT INTO import_error (mbox_file_id, byte_offset, kind, message) "
                    "VALUES (:id, :offset, :kind, :message)"
                ),
                {"id": file_id, "offset": offset, "kind": error.kind, "message": error.message},
            )
        await session.execute(
            text(
                "UPDATE mbox_file SET status = CAST(:status AS mbox_status), worker_id = NULL, "
                "error_count = error_count + :errors, "
                "finished_at = CASE WHEN :done THEN now() END, "
                "size_bytes = CASE WHEN :done THEN greatest(size_bytes, bytes_done) "
                "ELSE size_bytes END WHERE id = :id"
            ),
            {
                "id": file_id,
                "status": status,
                "errors": int(error is not None),
                "done": status is MboxStatus.DONE,
            },
        )


_worker: _Worker | None = None


def _init_worker(
    settings: Settings,
    preload: Any,
    mbox_dir: Path,
    pipeline: Pipeline,
    worker_ids: "Queue[int]",
    stop: Event,
    dkim_checked: "Synchronized[int]",
) -> None:
    # Ctrl-C reaches the whole process group; the main process decides and sets `stop`.
    ignore_interrupts()
    global _worker
    _worker = _Worker(settings, preload, mbox_dir, pipeline, worker_ids.get(), stop, dkim_checked)


def _run_task(task: FileTask) -> FileOutcome:
    assert _worker is not None, "worker not initialised"
    return asyncio.run(_worker.import_file(task))


# Main process -------------------------------------------------------------------------------


async def run_files(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    files: Sequence[ScannedFile],
    workers: int,
    stop: asyncio.Event,
    *,
    pipeline: Pipeline = DEFAULT_PIPELINE,
    figures: "ImportFigures | None" = None,
) -> list[FileOutcome]:
    """Import the pending files in up to `workers` processes until done or `stop` is set.

    figures, when given, follows the files running and ended and the mails checked for DKIM.
    """
    figures = figures or ImportFigures()
    queue = sorted(
        (file for file in files if file.status is MboxStatus.PENDING),
        key=lambda file: (-file.size_bytes, file.path),
    )
    if not queue:
        return []
    async with sessionmaker() as session, session.begin():
        preload = await dkim_hook.load_preload(session)
    context = multiprocessing.get_context("spawn")
    count = min(workers, len(queue))
    worker_ids: Queue[int] = context.Queue()
    for worker_id in range(1, count + 1):
        worker_ids.put(worker_id)
    stop_workers = context.Event()
    async with sessionmaker() as session:
        await figures.start(session, [file.id for file in files])
    log.info(
        "importing %d files (%s) with %d workers",
        len(queue),
        _megabytes(sum(file.size_bytes - file.bytes_done for file in queue)),
        count,
    )
    initargs = (
        settings,
        preload,
        mbox_dir,
        pipeline,
        worker_ids,
        stop_workers,
        figures.dkim_checked,
    )
    outcomes: list[FileOutcome] = []
    last_finalize = time.monotonic()
    loop = asyncio.get_running_loop()
    stop_request = asyncio.ensure_future(stop.wait())
    with ProcessPoolExecutor(
        count, mp_context=context, initializer=_init_worker, initargs=initargs
    ) as executor:
        running: dict[asyncio.Future[FileOutcome], ScannedFile] = {}
        broken = False
        try:
            while queue or running:
                while queue and len(running) < count and not (stop.is_set() or broken):
                    file = queue.pop(0)
                    task = FileTask(file.id, file.path)
                    with spawning_workers():
                        running[loop.run_in_executor(executor, _run_task, task)] = file
                figures.workers = len(running)
                if not running:
                    break
                waiting: list[asyncio.Future[Any]] = [*running]
                if not stop_request.done():
                    waiting.append(stop_request)
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if stop.is_set() and not stop_workers.is_set():
                    stop_workers.set()
                    log.info("stopping: %d workers store their current batch", len(running))
                for future in [future for future in done if future in running]:
                    file = running.pop(future)
                    figures.workers = len(running)
                    outcome = await _outcome(sessionmaker, future, file, stop.is_set())
                    figures.files_finished += 1
                    broken = broken or outcome.error == _BROKEN
                    outcomes.append(outcome)
                    _log_outcome(outcome, file)
                    due = time.monotonic() - last_finalize >= FINALIZE_SECONDS
                    if outcome.status is MboxStatus.DONE and due and (queue or running):
                        await _finalize(sessionmaker)
                        last_finalize = time.monotonic()
        finally:
            stop_workers.set()  # also when this loop fails: leaving the pool waits for them
            stop_request.cancel()
    return outcomes


_BROKEN = "a worker process died"


async def _outcome(
    sessionmaker: async_sessionmaker[AsyncSession],
    future: asyncio.Future[FileOutcome],
    file: ScannedFile,
    stopping: bool,
) -> FileOutcome:
    """The worker's outcome; when the worker failed without recording it, record it here."""
    try:
        return future.result()
    except BrokenProcessPool:
        # Killed (out of memory, a signal) or crashed: whatever it committed stays valid.
        status = MboxStatus.PAUSED if stopping else MboxStatus.ERROR
        message = _BROKEN
    except Exception as error:
        status, message = MboxStatus.ERROR, f"import stopped: {describe(error)}"
    async with sessionmaker() as session:
        issue = None if status is MboxStatus.PAUSED else Issue(ImportErrorKind.INTERNAL, message)
        bytes_done = await session.scalar(
            text("SELECT bytes_done FROM mbox_file WHERE id = :id"), {"id": file.id}
        )
        await session.commit()
        offset = int(bytes_done or 0)
        await _end_file(session, file.id, status, offset, issue)
    return FileOutcome(file.path, status, offset, 0, 0, message)


def _log_outcome(outcome: FileOutcome, file: ScannedFile) -> None:
    if outcome.status is MboxStatus.DONE:
        log.info("done %s: %d mails, %d import errors", outcome.path, outcome.mails, outcome.issues)
    elif outcome.status is MboxStatus.PAUSED:
        share = outcome.bytes_done / file.size_bytes if file.size_bytes else 1.0
        log.info("paused %s at byte %d (%.0f%%)", outcome.path, outcome.bytes_done, share * 100)
    else:
        log.warning("error %s at byte %d: %s", outcome.path, outcome.bytes_done, outcome.error)


async def _finalize(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        result = await finalize(session)
    log.info(
        "updated duplicates, threads, display names and aggregates in %.1f s, "
        "%d of %d edges changed",
        result.seconds,
        result.edges.changed,
        result.edges.pairs,
    )


class _Totals(NamedTuple):
    done: int  # files
    files: int
    mails: int
    bytes_done: int
    size: int
    errors: int
    left: int  # bytes still to import in the files pending or running


_TOTALS = text("""
    SELECT count(*) FILTER (WHERE status = 'done'), count(*), COALESCE(sum(mails_parsed), 0),
           COALESCE(sum(bytes_done), 0), COALESCE(sum(size_bytes), 0),
           COALESCE(sum(error_count), 0),
           COALESCE(sum(greatest(size_bytes - bytes_done, 0))
                    FILTER (WHERE status IN ('pending', 'running')), 0)
    FROM mbox_file WHERE id = ANY(CAST(:ids AS bigint[]))
""")


async def _totals(db: Executor, ids: list[int]) -> _Totals:
    row = (await db.execute(_TOTALS, {"ids": ids})).one()
    return _Totals(*(int(value) for value in row))


class ImportFigures:
    """The live figures of an import run (jobs.ImportProgress) and its log line.

    The phases fill them in turn: the command the files queued after the scan, the header
    refresh its counts, run_files the files running and ended, the workers the DKIM counter,
    the attachments phase its documents (attachments.phase). report() adds the totals of the
    run's files from mbox_file, as the dashboard reads them, and the rates over the last
    RATE_WINDOW seconds of the import phase and of the attachments phase.
    """

    def __init__(self) -> None:
        self.files_queued = 0
        self.files_finished = 0
        self.workers = 0
        self.headers_total = 0
        self.headers_done = 0
        self.documents_total = 0
        self.documents_done = 0
        self._documents: RateWindow | None = None  # from the start of the attachments phase
        # Mails with a DKIM verdict, added to by the worker processes per committed batch.
        self.dkim_checked: Synchronized[int] = multiprocessing.get_context("spawn").Value("q", 0)
        self._ids: list[int] = []
        self._base: _Totals | None = None
        self._window: RateWindow | None = None
        self._next_log = 0.0

    async def start(self, db: Executor, ids: list[int]) -> None:
        """The import phase begins with these files: figures count from their progress now."""
        self._ids = ids
        self._base = await _totals(db, ids)
        self._window = RateWindow(0, self.dkim_checked.value, 0)
        self._next_log = time.monotonic() + PROGRESS_SECONDS

    def start_documents(self, total: int) -> None:
        """The attachments phase begins with this many documents to work through."""
        self.documents_total = total
        self.documents_done = 0
        self._documents = RateWindow(0)
        self._next_log = time.monotonic() + PROGRESS_SECONDS

    async def report(self, db: Executor) -> ImportProgress:
        """The figures now; while files are imported or documents extracted, a log line every
        PROGRESS_SECONDS."""
        progress = ImportProgress(
            workers=self.workers,
            files_queued=self.files_queued,
            files_finished=self.files_finished,
            headers_total=self.headers_total,
            headers_done=self.headers_done,
            documents_total=self.documents_total,
            documents_done=self.documents_done,
        )
        if self._documents is not None:
            (progress.documents_per_second,) = self._documents.rates(self.documents_done)
            self._log_documents(progress.documents_per_second)
        if self._base is None or self._window is None:
            return progress
        totals = await _totals(db, self._ids)
        mails = totals.mails - self._base.mails
        size = totals.bytes_done - self._base.bytes_done
        mail_rate, dkim_rate, byte_rate = self._window.rates(mails, self.dkim_checked.value, size)
        eta = totals.left / byte_rate if byte_rate > 0 else None
        if self.workers and self._documents is None and time.monotonic() >= self._next_log:
            self._next_log = time.monotonic() + PROGRESS_SECONDS
            log.info(
                "files %d/%d, %d mails, %.0f mails/s, %.1f MB/s, %d import errors, %.0f%%, ETA %s",
                totals.done,
                totals.files,
                totals.mails,
                mail_rate,
                byte_rate / 1024**2,
                totals.errors,
                100 * totals.bytes_done / totals.size if totals.size else 100.0,
                "unknown" if eta is None else _duration(eta),
            )
        return progress.model_copy(
            update={
                "mails_imported": mails,
                "bytes_imported": size,
                "mails_per_second": mail_rate,
                "dkim_per_second": dkim_rate,
                "bytes_per_second": byte_rate,
                "eta_seconds": eta,
            }
        )

    def _log_documents(self, rate: float) -> None:
        if not self.workers or time.monotonic() < self._next_log:
            return
        self._next_log = time.monotonic() + PROGRESS_SECONDS
        left = self.documents_total - self.documents_done
        log.info(
            "documents %d/%d, %.1f documents/s, ETA %s",
            self.documents_done,
            self.documents_total,
            rate,
            _duration(left / rate) if rate > 0 else "unknown",
        )


def _megabytes(size: int) -> str:
    return f"{size / 1024**2:.1f} MB"


def _duration(seconds: float) -> str:
    minutes, rest = divmod(int(seconds + 0.5), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{rest:02d}s" if minutes else f"{rest}s"

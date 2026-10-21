"""The worker pool: one MBOX file per task, resumable after every committed batch (D15).

The main process hands out files, largest first, one to each idle worker, and reports progress
from mbox_file every few seconds. A worker process (spawned, so it imports everything afresh and
gets all it needs through the pool initializer) reads its file from bytes_done to the end:
iter_records -> parse_record -> DKIM check -> Batch -> Store. When asked to stop (Ctrl-C or
SIGTERM in the main process), the main process hands out no more files and every worker stores
the batch it holds and marks its file paused. A killed worker loses at most its uncommitted
batch; the next scan finds its file still running and resumes it.
"""

import asyncio
import logging
import multiprocessing
import signal
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from dataclasses import dataclass
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import Any, BinaryIO, Protocol

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

log = logging.getLogger(__name__)

PROGRESS_SECONDS = 5.0
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
    ) -> None:
        self.mbox_dir = mbox_dir
        self.pipeline = pipeline
        self.worker_id = worker_id
        self.max_size = int(settings.import_max_mail_size)
        self.hash_limit = int(settings.import_attachment_hash_limit)
        self.checker = dkim_hook.create_checker(settings, preload)
        self.store = Store(self.checker)
        self._stop = stop
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


def describe(error: BaseException) -> str:
    """An exception as one line of text PostgreSQL can store."""
    line = " ".join(f"{type(error).__name__}: {error}".split())[:500]
    return line.encode("utf-8", "replace").decode("utf-8").replace("\0", "")


_worker: _Worker | None = None


def _init_worker(
    settings: Settings,
    preload: Any,
    mbox_dir: Path,
    pipeline: Pipeline,
    worker_ids: "Queue[int]",
    stop: Event,
) -> None:
    # Ctrl-C reaches the whole process group; the main process decides and sets `stop`. Until
    # here SIGINT was blocked (_spawning_workers), so an early Ctrl-C cannot kill the worker.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})
    global _worker
    _worker = _Worker(settings, preload, mbox_dir, pipeline, worker_ids.get(), stop)


@contextmanager
def _spawning_workers() -> Iterator[None]:
    """SIGINT blocked in this thread while the pool may spawn worker processes.

    A spawned process inherits the blocked signal, so a Ctrl-C while it is still importing its
    modules waits until _init_worker ignores it, instead of killing it with a traceback.
    """
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})


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
) -> list[FileOutcome]:
    """Import the pending files in up to `workers` processes until done or `stop` is set."""
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
    progress = _Progress(sessionmaker, [file.id for file in files])
    await progress.start()
    log.info(
        "importing %d files (%s) with %d workers",
        len(queue),
        _megabytes(sum(file.size_bytes - file.bytes_done for file in queue)),
        count,
    )
    initargs = (settings, preload, mbox_dir, pipeline, worker_ids, stop_workers)
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
                    with _spawning_workers():
                        running[loop.run_in_executor(executor, _run_task, task)] = file
                if not running:
                    break
                waiting: list[asyncio.Future[Any]] = [*running]
                if not stop_request.done():
                    waiting.append(stop_request)
                done, _ = await asyncio.wait(
                    waiting, timeout=progress.wait_time(), return_when=asyncio.FIRST_COMPLETED
                )
                if stop.is_set() and not stop_workers.is_set():
                    stop_workers.set()
                    log.info("stopping: %d workers store their current batch", len(running))
                for future in [future for future in done if future in running]:
                    file = running.pop(future)
                    outcome = await _outcome(sessionmaker, future, file, stop.is_set())
                    broken = broken or outcome.error == _BROKEN
                    outcomes.append(outcome)
                    _log_outcome(outcome, file)
                    due = time.monotonic() - last_finalize >= FINALIZE_SECONDS
                    if outcome.status is MboxStatus.DONE and due and (queue or running):
                        await _finalize(sessionmaker)
                        last_finalize = time.monotonic()
                if progress.wait_time() <= 0:
                    await progress.report()
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
        "updated duplicates, threads and display names in %.1f s, %d of %d edges changed",
        result.seconds,
        result.edges.changed,
        result.edges.pairs,
    )


_TOTALS = text("""
    SELECT count(*) FILTER (WHERE status = 'done'), count(*), COALESCE(sum(mails_parsed), 0),
           COALESCE(sum(bytes_done), 0), COALESCE(sum(size_bytes), 0),
           COALESCE(sum(error_count), 0)
    FROM mbox_file WHERE id = ANY(CAST(:ids AS bigint[]))
""")


class _Progress:
    """One line every PROGRESS_SECONDS, read from mbox_file like the import dashboard does."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], ids: list[int]) -> None:
        self._sessionmaker = sessionmaker
        self._ids = ids
        self._started = self._next = time.monotonic()
        self._base: Sequence[int] = ()

    async def start(self) -> None:
        self._base = await self._totals()
        self._started = time.monotonic()
        self._next = self._started + PROGRESS_SECONDS

    def wait_time(self) -> float:
        return max(0.0, self._next - time.monotonic())

    async def report(self) -> None:
        done, total, mails, bytes_done, size, errors = await self._totals()
        now = time.monotonic()
        self._next = now + PROGRESS_SECONDS
        elapsed = max(now - self._started, 1e-9)
        byte_rate = (bytes_done - self._base[3]) / elapsed
        eta = _duration((size - bytes_done) / byte_rate) if byte_rate > 0 else "unknown"
        log.info(
            "files %d/%d, %d mails, %.0f mails/s, %.1f MB/s, %d import errors, %.0f%%, ETA %s",
            done,
            total,
            mails,
            (mails - self._base[2]) / elapsed,
            byte_rate / 1024**2,
            errors,
            100 * bytes_done / size if size else 100.0,
            eta,
        )

    async def _totals(self) -> Sequence[int]:
        async with self._sessionmaker() as session:
            row = (await session.execute(_TOTALS, {"ids": self._ids})).one()
        return tuple(int(value) for value in row)


def _megabytes(size: int) -> str:
    return f"{size / 1024**2:.1f} MB"


def _duration(seconds: float) -> str:
    minutes, rest = divmod(int(seconds + 0.5), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{rest:02d}s" if minutes else f"{rest}s"

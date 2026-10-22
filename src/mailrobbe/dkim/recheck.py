"""Checking imported mails again from their MBOX files (`mailrobbe dkim`, SPEC 3.4, D13).

The main process selects the mails in file order, with keyset pagination on (mbox_file_id,
byte_offset), so a run over 400,000 mails never holds more than one page and every file is read
front to back. Pages go as chunks to a pool of worker processes; each worker reads the messages
with mbox.read_message, makes sure they are still the bytes that were imported (raw_sha256) and
checks them with its own DkimChecker, built once from the dns_cache rows and the candidate keys
of deleted selectors (D100) the main process loaded. The main process writes every finished
chunk (save_verdicts, upsert_dns_cache) and commits it, so an interrupted run keeps what it
finished. check_mails is that part on its own; `mailrobbe dkim-keys` checks the mails of the key
names it touched with it (by_key_names, keys/run.py). A run that checked mails ends by
recomputing the aggregates (D33): the pass_* counters of the edges (D36), the person figures
with their DKIM share and global_stats, whose DKIM counts the mail list shows (D19).

A mail whose file is missing, whose record cannot be read or whose bytes changed is skipped:
counted by kind and logged, never written, and the run goes on.

A run holds the DKIM lock and records itself in `job` (mailrobbe.jobrun, D47) with the phases
check and aggregates and its figures every few seconds; its steps (D110) are check and those of
refresh_aggregates. Ctrl-C, SIGTERM and the dashboard's stop
request end it alike: no new chunks, the chunks in flight are written, the aggregates are
recomputed when anything was checked.

Workers are started with "spawn", like the generator's (generator/pipeline.py); jobs == 1 runs
the same code in a thread of the main process, so its event loop keeps reporting.
"""

import asyncio
import hashlib
import logging
import math
import multiprocessing
import time
from collections import Counter, deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Collection, Iterator
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import aclosing, contextmanager
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import ColumnElement, false, func, or_, select, true, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from mailrobbe import aggregates
from mailrobbe.config import Settings
from mailrobbe.db.models import DkimResult, Mail, MboxFile
from mailrobbe.db.session import create_engine
from mailrobbe.dkim import store
from mailrobbe.dkim.checker import DkimChecker
from mailrobbe.dkim.keys.store import keep_cached_keys, load_candidates, of_key_names
from mailrobbe.dkim.model import DnsAnswer, KeyCandidates, MailVerdict
from mailrobbe.enums import DkimStatus, JobKind, JobOrigin, JobStatus
from mailrobbe.jobrun import (
    JobRun,
    RateWindow,
    Step,
    Steps,
    ignore_interrupts,
    job_run,
    spawning_workers,
)
from mailrobbe.jobs import DkimOptions, DkimProgress, application_name
from mailrobbe.mbox import read_message

log = logging.getLogger(__name__)

CHUNK = 250  # mails per database page, per worker task and per commit
WINDOW_PER_JOB = 3  # chunks in flight per worker
PROGRESS_SECONDS = 5.0  # a log line this often

# D13: the mails not checked yet, and those whose key was missing or did not answer in time.
DEFAULT_STATUSES: frozenset[DkimStatus | None] = frozenset(
    {None, DkimStatus.NO_KEY, DkimStatus.TEMP_ERROR}
)
UNCHECKED = "unchecked"  # how a NULL mail.dkim_status appears in the summary


class Skip(StrEnum):
    """Why a selected mail was not checked."""

    MISSING_FILE = "missing_file"  # its MBOX file is not there
    UNREADABLE = "unreadable"  # read error, or no MBOX record at the stored offset
    HASH_MISMATCH = "hash_mismatch"  # the bytes differ from the imported ones (raw_sha256)


@dataclass(slots=True)
class RecheckSummary:
    """Printed as JSON by `mailrobbe dkim`."""

    selected: int  # mails matching the selection when the run started
    checked: int
    skipped: dict[str, int]  # Skip value -> mails
    statuses: dict[str, int]  # DkimStatus value -> checked mails with that status now
    transitions: dict[str, int]  # "no_key -> pass" -> checked mails whose status changed
    dns_answers_saved: int  # dns_cache rows written
    dns_lookups: int  # key lookups that went past the workers' caches
    dns_hits: int  # key lookups the caches answered
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class RecheckRun:
    summary: RecheckSummary
    stopped: bool  # by Ctrl-C, SIGTERM or the dashboard; the summary covers what was checked


def recheck(
    settings: Settings,
    *,
    statuses: Collection[DkimStatus | None] | None = DEFAULT_STATUSES,
    mail_ids: Collection[int] = (),
    jobs: int = 1,
) -> RecheckSummary:
    """Check the selected mails from their MBOX files and store the results (run_recheck)."""
    run = asyncio.run(run_recheck(settings, statuses=statuses, mail_ids=mail_ids, jobs=jobs))
    return run.summary


async def run_recheck(
    settings: Settings,
    *,
    statuses: Collection[DkimStatus | None] | None = DEFAULT_STATUSES,
    mail_ids: Collection[int] = (),
    jobs: int = 1,
    origin: JobOrigin = JobOrigin.CLI,
) -> RecheckRun:
    """The run of `mailrobbe dkim`; raises jobrun.RunRefused when it cannot start.

    statuses: the mail.dkim_status values to select, None in it for mails not checked yet;
    statuses=None selects every mail. mail_ids, when not empty, selects exactly those mails,
    whatever their status. jobs: worker processes, at most one per chunk of selected mails.
    """
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    keys = None
    if statuses is not None:
        keys = sorted(UNCHECKED if status is None else status.value for status in statuses)
    options = DkimOptions(
        statuses=keys,
        mail_ids=sorted(set(mail_ids)),
        workers=jobs,
        offline=settings.dkim_offline,
    )
    tally = CheckTally()
    engine = create_engine(settings.database_url, application_name(JobKind.DKIM))
    try:
        async with job_run(
            engine, JobKind.DKIM, origin, options, phase="check", figures=tally.report
        ) as job:
            job.steps.plan("check", *aggregates.STEPS)
            await _run(engine, settings, _selection(statuses, mail_ids), jobs, tally, job)
            summary = tally.finish()
            stopped = job.stop.is_set()
            job.end(JobStatus.STOPPED if stopped else JobStatus.DONE, _one_line(summary))
    finally:
        await engine.dispose()
    return RecheckRun(summary, stopped)


def _selection(
    statuses: Collection[DkimStatus | None] | None, mail_ids: Collection[int]
) -> ColumnElement[bool]:
    if mail_ids:
        return Mail.id.in_(sorted(set(mail_ids)))
    if statuses is None:
        return true()
    known = sorted(status for status in statuses if status is not None)
    conditions = [Mail.dkim_status.in_(known)] if known else []
    if None in statuses:
        conditions.append(Mail.dkim_status.is_(None))
    return or_(false(), *conditions)


def by_key_names(names: Collection[str]) -> ColumnElement[bool]:
    """The mails with a signature of one of these key names ('<selector>._domainkey.<domain>')."""
    return Mail.id.in_(select(DkimResult.mail_id).where(of_key_names(names)))


async def _run(
    engine: AsyncEngine,
    settings: Settings,
    where: ColumnElement[bool],
    jobs: int,
    tally: "CheckTally",
    job: JobRun,
) -> None:
    async with engine.connect() as connection:
        await check_mails(connection, settings, where, jobs, tally, job.steps, job.stop)
        if tally.checked:
            job.set_phase("aggregates")
            await aggregates.refresh_aggregates(connection, steps=job.steps)
            await connection.commit()
        else:
            job.steps.skip(*aggregates.STEPS)


async def check_mails(
    connection: AsyncConnection,
    settings: Settings,
    where: ColumnElement[bool],
    jobs: int,
    tally: "CheckTally",
    steps: Steps,
    stop: asyncio.Event,
    *,
    refresh_negative: bool = True,
) -> None:
    """Check the selected mails with every candidate key and store them, chunk by chunk, as the
    step check of `steps`.

    Commits each chunk; once `stop` is set no chunk is started, and those in flight are written.
    refresh_negative: ask DNS again for the keys the cache has as missing or timed out (D11).
    """
    count = select(func.count()).select_from(Mail).where(where)
    selected = await connection.scalar(count) or 0
    files = await connection.execute(select(MboxFile.id, MboxFile.path))
    paths = {file_id: path for file_id, path in files}
    answers = await store.load_dns_cache(connection)
    await keep_cached_keys(connection)  # D106
    candidates = await load_candidates(connection)
    await connection.commit()
    jobs = max(1, min(jobs, math.ceil(selected / CHUNK)))
    log.info(
        "%d mails selected, %d cached DNS answers, keys for %d names, %d worker(s)",
        selected,
        len(answers),
        len(candidates),
        jobs,
    )
    tally.start(selected, jobs)
    keys = _Keys(answers, candidates, refresh_negative)
    # The tally logs the progress itself, with the mails skipped.
    with (
        steps.step("check", unit="mails", total=selected, log_progress=False) as step,
        _checkers(settings, keys, jobs) as submit,
    ):
        tally.step = step
        pending: deque[tuple[list[_Mail], Awaitable[_Checked]]] = deque()
        try:
            async with aclosing(_chunks(connection, where, paths)) as chunks:
                async for chunk in chunks:
                    if stop.is_set():
                        break
                    pending.append((chunk, submit(chunk)))
                    if len(pending) >= jobs * WINDOW_PER_JOB:
                        await _write(connection, *pending.popleft(), tally)
            while pending:
                await _write(connection, *pending.popleft(), tally)
        except Exception:
            # The pool waits for the chunks in flight anyway; their errors are this one's.
            await asyncio.gather(*(result for _, result in pending), return_exceptions=True)
            raise
    tally.workers = 0


def _one_line(summary: RecheckSummary) -> str:
    """The summary in one line, for job.message."""
    statuses = ", ".join(f"{status} {count}" for status, count in summary.statuses.items())
    line = (
        f"{summary.checked} of {summary.selected} mails checked, "
        f"{sum(summary.skipped.values())} skipped"
    )
    return f"{line} ({statuses})" if statuses else line


@dataclass(frozen=True, slots=True)
class _Mail:
    """One selected mail, as a worker needs it."""

    id: int
    path: str  # mbox_file.path, relative to settings.mbox_dir
    byte_offset: int
    byte_length: int
    raw_sha256: str
    dkim_status: DkimStatus | None


@dataclass(slots=True)
class _Checked:
    """A worker's result for one chunk: one outcome per mail, in chunk order."""

    outcomes: list[MailVerdict | Skip]
    answers: list[DnsAnswer]  # the worker's new key answers, for dns_cache
    lookups: int  # the checker's counters for this chunk
    hits: int


async def _chunks(
    connection: AsyncConnection, where: ColumnElement[bool], paths: dict[int, str]
) -> AsyncGenerator[list[_Mail], None]:
    """The selected mails in file order, CHUNK at a time; each page is one index range scan."""
    page = (
        select(
            Mail.id,
            Mail.mbox_file_id,
            Mail.byte_offset,
            Mail.byte_length,
            Mail.raw_sha256,
            Mail.dkim_status,
        )
        .where(where)
        .order_by(Mail.mbox_file_id, Mail.byte_offset)
        .limit(CHUNK)
    )
    key = tuple_(Mail.mbox_file_id, Mail.byte_offset)
    query = page
    while True:
        rows = (await connection.execute(query)).all()
        if rows:
            yield [
                _Mail(mail_id, paths[file_id], offset, length, sha256, status)
                for mail_id, file_id, offset, length, sha256, status in rows
            ]
        if len(rows) < CHUNK:
            return
        query = page.where(key > tuple_(rows[-1].mbox_file_id, rows[-1].byte_offset))


async def _write(
    connection: AsyncConnection,
    chunk: list[_Mail],
    result: Awaitable[_Checked],
    tally: "CheckTally",
) -> None:
    checked = await result
    await store.save_verdicts(connection, tally.count(chunk, checked))
    await store.upsert_dns_cache(connection, checked.answers)
    await connection.commit()


# Workers -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Keys:
    """What every checker of a run starts from, read once by the main process."""

    answers: list[DnsAnswer]  # dns_cache
    candidates: KeyCandidates  # keys of deleted selectors (keys.store.load_candidates)
    refresh_negative: bool


class _Worker:
    """What a checking process keeps between chunks: the MBOX directory and its checker."""

    def __init__(self, settings: Settings, keys: _Keys) -> None:
        self._mbox_dir = settings.mbox_dir
        self._checker = DkimChecker.from_settings(
            settings,
            preload=keys.answers,
            refresh_negative=keys.refresh_negative,
            candidates=keys.candidates,
        )

    def check(self, chunk: list[_Mail]) -> _Checked:
        lookups, hits = self._checker.lookups, self._checker.hits
        outcomes = [self._check(mail) for mail in chunk]
        return _Checked(
            outcomes,
            self._checker.take_new_answers(),
            self._checker.lookups - lookups,
            self._checker.hits - hits,
        )

    def _check(self, mail: _Mail) -> MailVerdict | Skip:
        try:
            raw = read_message(self._mbox_dir / mail.path, mail.byte_offset, mail.byte_length)
        except FileNotFoundError:
            return Skip.MISSING_FILE
        except (OSError, ValueError):
            return Skip.UNREADABLE
        if hashlib.sha256(raw).hexdigest() != mail.raw_sha256:
            return Skip.HASH_MISMATCH
        return self._checker.check(raw)


@contextmanager
def _checkers(
    settings: Settings, keys: _Keys, jobs: int
) -> Iterator[Callable[[list[_Mail]], Awaitable[_Checked]]]:
    """submit(chunk) starts checking a chunk and returns its result to await."""
    loop = asyncio.get_running_loop()
    if jobs == 1:
        worker = _Worker(settings, keys)
        with ThreadPoolExecutor(1) as thread:  # one checker: one chunk after the other
            yield lambda chunk: loop.run_in_executor(thread, worker.check, chunk)
        return
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        jobs, mp_context=context, initializer=_init_worker, initargs=(settings, keys)
    ) as pool:

        def submit(chunk: list[_Mail]) -> Awaitable[_Checked]:
            with spawning_workers():  # the pool starts its workers as chunks come
                return loop.run_in_executor(pool, _work, chunk)

        yield submit


_worker: _Worker | Exception | None = None


def _init_worker(settings: Settings, keys: _Keys) -> None:
    """Pool initializer: the cached answers and keys reach each worker once, not with every
    chunk."""
    global _worker
    # Ctrl-C reaches the whole process group; the main process decides and stops submitting.
    ignore_interrupts()
    try:
        _worker = _Worker(settings, keys)
    except Exception as error:
        # Raised from every task instead, so the run fails with the error itself rather than
        # with a broken pool.
        _worker = error


def _work(chunk: list[_Mail]) -> _Checked:
    if isinstance(_worker, Exception):
        raise _worker
    assert _worker is not None, "worker not initialised"
    return _worker.check(chunk)


# Counting and progress ---------------------------------------------------------------------


class CheckTally:
    """The summary's counters, and the run's live figures with a log line every few seconds."""

    def __init__(self) -> None:
        self._started = time.monotonic()
        self._selected = 0
        self.workers = 0
        self.step: Step | None = None  # the run's check step
        self._window: RateWindow | None = None
        self._next_log = 0.0
        self._skipped: Counter[str] = Counter()
        self._statuses: Counter[str] = Counter()
        self._transitions: Counter[str] = Counter()
        self._missing_files: set[str] = set()
        self._answers_saved = 0
        self._lookups = 0
        self._hits = 0

    def start(self, selected: int, workers: int) -> None:
        """The check begins: rates count from now."""
        self._selected = selected
        self.workers = workers
        self._window = RateWindow(0)
        self._next_log = time.monotonic() + PROGRESS_SECONDS

    async def report(self, _db: AsyncConnection) -> DkimProgress:
        """The figures for the job row (jobrun.Figures)."""
        skipped = self._skipped.total()
        progress = DkimProgress(
            workers=self.workers, selected=self._selected, checked=self.checked, skipped=skipped
        )
        if self._window is None:
            return progress
        done = self.checked + skipped
        (rate,) = self._window.rates(done)
        eta = (self._selected - done) / rate if rate > 0 else None
        if self.workers and time.monotonic() >= self._next_log:
            self._next_log = time.monotonic() + PROGRESS_SECONDS
            log.info("%d/%d mails, %d skipped, %.0f mails/s", done, self._selected, skipped, rate)
        return progress.model_copy(update={"mails_per_second": rate, "eta_seconds": eta})

    @property
    def checked(self) -> int:
        return self._statuses.total()

    @property
    def changed(self) -> int:
        """Checked mails whose status changed."""
        return self._transitions.total()

    def count(self, chunk: list[_Mail], checked: _Checked) -> list[tuple[int, MailVerdict]]:
        """Count a finished chunk; returns the verdicts to save."""
        verdicts: list[tuple[int, MailVerdict]] = []
        for mail, outcome in zip(chunk, checked.outcomes, strict=True):
            if isinstance(outcome, Skip):
                self._skip(mail, outcome)
                continue
            verdicts.append((mail.id, outcome))
            status = outcome.status
            self._statuses[status.value] += 1
            if status != mail.dkim_status:
                self._transitions[f"{mail.dkim_status or UNCHECKED} -> {status}"] += 1
        # what upsert_dns_cache writes: the last answer per name, ttl 0 left out
        self._answers_saved += len({answer.name for answer in checked.answers if answer.ttl > 0})
        self._lookups += checked.lookups
        self._hits += checked.hits
        if self.step is not None:
            self.step.done = self.checked + self._skipped.total()
        return verdicts

    def _skip(self, mail: _Mail, reason: Skip) -> None:
        self._skipped[reason.value] += 1
        if reason is not Skip.MISSING_FILE:
            log.warning(
                "mail %d skipped (%s): %s at offset %d",
                mail.id,
                reason,
                mail.path,
                mail.byte_offset,
            )
        elif mail.path not in self._missing_files:
            self._missing_files.add(mail.path)
            log.warning("skipping the mails of %s: file not found", mail.path)

    def finish(self) -> RecheckSummary:
        elapsed = time.monotonic() - self._started
        checked = self.checked
        log.info(
            "done: %d mails checked, %d skipped in %.1f s (%.0f mails/s)",
            checked,
            self._skipped.total(),
            elapsed,
            (checked + self._skipped.total()) / max(elapsed, 1e-9),
        )
        return RecheckSummary(
            selected=self._selected,
            checked=checked,
            skipped=dict(sorted(self._skipped.items())),
            statuses=dict(sorted(self._statuses.items())),
            transitions=dict(sorted(self._transitions.items())),
            dns_answers_saved=self._answers_saved,
            dns_lookups=self._lookups,
            dns_hits=self._hits,
            elapsed_seconds=round(elapsed, 3),
        )

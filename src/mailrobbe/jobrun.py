"""The run side of `mailrobbe import` and `mailrobbe dkim` (D46, D47); jobs.py is the table side.

    job_run      connect; take the kind's advisory lock on a connection of the run's own; check
                 the schema; end what dead runs of the kind left in the database; record the
                 job; stop on Ctrl-C, SIGTERM or the dashboard's request; report the figures
                 every REPORT_SECONDS; record how the run ended
    Steps        the run's steps (JobRun.steps, D110): waiting, running, ended, with counters,
                 rates and remaining times; logged when they start and end and every LOG_SECONDS
    RateWindow   throughput over the last RATE_WINDOW seconds

The reports go out from a task of their own on the lock connection, so they go on while the run
awaits something long (a finalize, a slow batch, a chunk of DKIM checks): job.updated_at shows
that the process lives, and a stop request is read within REPORT_SECONDS. Each report adds the
steps and the run's longest running statement (jobs.db_activity) to the run's own figures, which
the run's engine makes visible by naming its connections (jobs.application_name). A stop request
sets the same event as Ctrl-C, so everything after it is the Ctrl-C path of the command.

A run that cannot record its end (the database went away) keeps its exit status; its row stays
running without a lock holder, which the dashboard shows as aborted and the next run marks failed.

Worker processes are spawned with SIGINT blocked (spawning_workers) and ignore it from their
initializer on (ignore_interrupts): Ctrl-C reaches the whole process group, and the main process
alone decides what it means.
"""

import asyncio
import logging
import multiprocessing
import os
import signal
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NoReturn

from alembic.script import ScriptDirectory
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from mailrobbe import migrate
from mailrobbe.enums import JobKind, JobOrigin, JobStatus
from mailrobbe.jobs import (
    LOCK_KEYS,
    RATE_WINDOW,
    REPORT_SECONDS,
    DbActivity,
    RunProgress,
    StepProgress,
    StepStatus,
    StepUnit,
    begin_job,
    db_activity,
    end_job,
    end_leftovers,
    report_job,
)

log = logging.getLogger(__name__)

EXIT_INTERRUPTED = 130
REPEAT_SECONDS = 1.0  # a second Ctrl-C earlier than this is the first one delivered twice
LOG_SECONDS = 10.0  # how often the log shows the steps running

_LOCK = text("SELECT pg_try_advisory_lock(:key)")
_UNLOCK = text("SELECT pg_advisory_unlock(:key)")
_BUSY = {
    JobKind.IMPORT: "another import is running",
    JobKind.DKIM: "another DKIM check is running",
}
_ABORTED = {
    JobKind.IMPORT: "aborted: run `mailrobbe import` again to continue",
    JobKind.DKIM: "aborted: the mails checked so far are stored",
}
_ERRORS = (OSError, SQLAlchemyError)

# The run's live figures (a jobs.*Progress model), computed on the lock connection.
Figures = Callable[[AsyncConnection], Awaitable[RunProgress]]


class RunRefused(Exception):
    """The run did not start: no database, another run of its kind is alive, or an old schema."""


def describe(error: BaseException) -> str:
    """An exception as one line of text PostgreSQL can store."""
    line = " ".join(f"{type(error).__name__}: {error}".split())[:500]
    return line.encode("utf-8", "replace").decode("utf-8").replace("\0", "")


class JobRun:
    """A started run as its command sees it: the stop event, the phase, the steps, and how it
    ends."""

    def __init__(
        self,
        connection: AsyncConnection,
        job_id: int,
        kind: JobKind,
        figures: Figures,
        phase: str,
    ):
        self.job_id = job_id
        self.stop = asyncio.Event()  # Ctrl-C, SIGTERM or a stop request from the dashboard
        self.steps = Steps(self.stop, log_steps=True)
        self._connection = connection
        self._kind = kind
        self._figures = figures
        self._phase = phase
        self._wake = asyncio.Event()
        self._closing = False
        self._outcome: tuple[JobStatus, str] | None = None
        self._next_log = time.monotonic() + LOG_SECONDS

    def set_phase(self, phase: str) -> None:
        """Enter a phase (jobs.ImportPhase, jobs.DkimPhase); reported at once."""
        self._phase = phase
        self._wake.set()

    def end(self, status: JobStatus, message: str) -> None:
        """How the run ends: done, stopped or failed, with a one-line English message."""
        self._outcome = (status, message)

    async def _report(self) -> None:
        """Every REPORT_SECONDS and after each phase change, until _finish."""
        failing = False
        while not self._closing:
            self._wake.clear()
            try:
                progress = await self._progress(live=True)
                stop = await report_job(
                    self._connection, self.job_id, phase=self._phase, progress=progress
                )
                await self._connection.commit()
            except Exception as error:  # the run goes on; a database gone stops it soon enough
                if not failing:
                    log.warning("cannot report the run's progress: %s", describe(error))
                failing = True
                with suppress(*_ERRORS):
                    await self._connection.rollback()
            else:
                failing = False
                if stop and not self.stop.is_set():
                    log.info("stop requested from the dashboard")
                    self.stop.set()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), REPORT_SECONDS)

    async def _finish(self, reporting: "asyncio.Task[None]") -> None:
        """Stop reporting (never in the middle of a report) and record the outcome."""
        self._closing = True
        self._wake.set()
        await reporting
        status, message = self._outcome or (JobStatus.FAILED, "the run ended without an outcome")
        try:
            progress = await self._progress(live=False)
            await end_job(self._connection, self.job_id, status, message=message, progress=progress)
            await self._connection.commit()
        except _ERRORS as error:
            log.error("cannot record the end of the run: %s", describe(error))

    async def _progress(self, *, live: bool) -> RunProgress:
        """The run's figures with its steps and, while it runs, its database activity."""
        progress = await self._figures(self._connection)
        steps = self.steps.snapshot()
        database = None
        if live:
            database = await db_activity(self._connection, self._kind, os.getpid())
            if time.monotonic() >= self._next_log:
                self._next_log = time.monotonic() + LOG_SECONDS
                self.steps.log_running(steps, database)
        return progress.model_copy(update={"steps": steps, "database": database})


@asynccontextmanager
async def job_run(
    engine: AsyncEngine,
    kind: JobKind,
    origin: JobOrigin,
    options: BaseModel,
    *,
    phase: str,
    figures: Figures,
) -> AsyncIterator[JobRun]:
    """A run of this kind from its lock to its recorded end; raises RunRefused when it cannot start.

    The body calls JobRun.end; when it raises instead, the run ends failed with the error as its
    message and the error propagates.
    """
    key = LOCK_KEYS[kind]
    try:
        connection = await engine.connect()
    except (OSError, DBAPIError) as error:
        raise RunRefused(f"cannot connect to the database: {describe(error)}") from error
    locked = False
    try:
        locked = bool(await connection.scalar(_LOCK, {"key": key}))
        await connection.commit()  # the lock belongs to the connection, not to the transaction
        if not locked:
            raise RunRefused(_BUSY[kind])
        problem = await _schema_problem(connection, engine)
        if problem is not None:
            raise RunRefused(problem)
        ended = await end_leftovers(connection, kind)
        if ended:
            plural = "" if ended == 1 else "s"
            log.warning(
                "ended %d database session%s left by an earlier %s run", ended, plural, kind
            )
        job_id = await begin_job(connection, kind, origin, options, phase)
        await connection.commit()
        run = JobRun(connection, job_id, kind, figures, phase)
        with stop_on_signals(run.stop, _ABORTED[kind]):
            reporting = asyncio.create_task(run._report())
            try:
                yield run
            except Exception as error:
                run.end(JobStatus.FAILED, describe(error))
                raise
            finally:
                await run._finish(reporting)
    finally:
        with suppress(*_ERRORS):  # a connection that broke has lost its lock already
            if locked:
                await connection.execute(_UNLOCK, {"key": key})
                await connection.commit()
            await connection.close()


async def _schema_problem(connection: AsyncConnection, engine: AsyncEngine) -> str | None:
    url = engine.url.render_as_string(hide_password=False)
    head = ScriptDirectory.from_config(migrate.alembic_config(url)).get_current_head()
    current = None
    if await connection.scalar(text("SELECT to_regclass('alembic_version') IS NOT NULL")):
        current = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    await connection.commit()
    if current == head:
        return None
    return (
        f"the database schema is at revision {current or 'none'}, not at {head}: "
        "run `mailrobbe migrate` first"
    )


@contextmanager
def stop_on_signals(stop: asyncio.Event, aborted: str) -> Iterator[None]:
    """Ctrl-C or SIGTERM sets `stop`; a second one, REPEAT_SECONDS or more later, aborts.

    `uv run` forwards a terminal's Ctrl-C to its child, which therefore gets it twice within
    milliseconds; that still counts as one. Signals reach the main thread only: a run on another
    thread (recheck() through asyncio.to_thread) leaves them to it and stops on request alone.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    loop = asyncio.get_running_loop()
    first: float | None = None

    def request(signum: int) -> None:
        nonlocal first
        now = time.monotonic()
        if first is None:
            first = now
            log.info("stopping after the work in progress; Ctrl-C again aborts")
            stop.set()
        elif now - first >= REPEAT_SECONDS:
            abort(aborted)

    signals = (signal.SIGINT, signal.SIGTERM)
    for signum in signals:
        loop.add_signal_handler(signum, request, signum)
    try:
        yield
    finally:
        for signum in signals:
            loop.remove_signal_handler(signum)


def abort(message: str) -> NoReturn:
    """End the workers and this process at once, without waiting for any of their work.

    Uncommitted work rolls back when its connection drops, so the next run continues from what
    was committed, as after a crash.
    """
    for child in multiprocessing.active_children():
        child.kill()
    log.error("%s", message)
    os._exit(EXIT_INTERRUPTED)


@contextmanager
def spawning_workers() -> Iterator[None]:
    """SIGINT blocked in this thread while a pool may spawn worker processes.

    A spawned process inherits the blocked signal, so a Ctrl-C while it is still importing its
    modules waits until its initializer ignores it (ignore_interrupts), instead of killing it
    with a traceback.
    """
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})


def ignore_interrupts() -> None:
    """In a worker's initializer: Ctrl-C is for the main process, which sets the stop flag."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})


class RateWindow:
    """Rates of growing counters over the last RATE_WINDOW seconds, or since the start while the
    run is younger; one sample per report."""

    def __init__(self, *start: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._samples: deque[tuple[float, tuple[float, ...]]] = deque([(clock(), start)])

    def rates(self, *values: float) -> tuple[float, ...]:
        """Add the counters' values now; per second since the oldest sample in the window."""
        now = self._clock()
        samples = self._samples
        samples.append((now, values))
        while len(samples) > 2 and samples[1][0] <= now - RATE_WINDOW:
            samples.popleft()
        then, before = samples[0]
        elapsed = now - then
        if elapsed <= 0:
            return tuple(0.0 for _ in values)
        return tuple((value - old) / elapsed for value, old in zip(values, before, strict=True))


# Steps (D110) ----------------------------------------------------------------------------------


def duration(seconds: float) -> str:
    """Seconds for the log: "45s", "3m07s", "1h05m"."""
    minutes, rest = divmod(int(seconds + 0.5), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{rest:02d}s" if minutes else f"{rest}s"


class Step:
    """The counter of a running step: done of total units; the step's code moves it on."""

    def __init__(self, unit: StepUnit | None = None, total: int | None = None) -> None:
        self.unit = unit
        self.total = total
        self.done = 0

    def advance(self, count: int = 1) -> None:
        self.done += count


@dataclass(slots=True)
class _Entry:
    key: str
    status: StepStatus = "waiting"
    counter: Step = field(default_factory=Step)
    started: float = 0.0  # monotonic
    started_at: datetime | None = None
    ended: float | None = None
    window: RateWindow | None = None
    log_progress: bool = True


class Steps:
    """The steps of a run in their order, as job.progress.steps lists them (D110).

    plan() names the steps still to come, so the dashboard lists them waiting; skip() marks one
    with nothing to do. step() runs one: running while its body runs, then done; stopped when
    the run's stop event is set and its counter fell short of its total; failed when the body
    raises (the error propagates). A step run again (the finalize between the files of a long
    import) starts afresh, and reset() makes steps wait again. snapshot() is what a report
    stores. Without a run (refresh_aggregates after a merge) the steps are kept and not logged.
    """

    def __init__(
        self,
        stop: asyncio.Event | None = None,
        *,
        log_steps: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stop = stop
        self._logging = log_steps
        self._clock = clock
        self._entries: dict[str, _Entry] = {}

    def plan(self, *keys: str) -> None:
        for key in keys:
            self._entry(key)

    def skip(self, *keys: str) -> None:
        for key in keys:
            self._entries[key] = _Entry(key, "skipped")

    def reset(self, *keys: str) -> None:
        for key in keys:
            self._entries[key] = _Entry(key)

    @contextmanager
    def step(
        self,
        key: str,
        *,
        unit: StepUnit | None = None,
        total: int | None = None,
        log_progress: bool = True,
    ) -> Iterator[Step]:
        """Run step key; log_progress=False when the step logs its progress itself."""
        counter = Step(unit, total)
        entry = _Entry(key, "running", counter, self._clock(), datetime.now(UTC))
        entry.window = RateWindow(0, clock=self._clock) if unit is not None else None
        entry.log_progress = log_progress
        self._entries[key] = entry
        if self._logging:
            size = "" if total is None else f", {_amount(total, unit)}"
            log.info("%s: started%s", key, size)
        status: StepStatus = "failed"
        try:
            yield counter
            short = counter.total is not None and counter.done < counter.total
            stopped = self._stop is not None and self._stop.is_set()
            status = "stopped" if short and stopped else "done"
        finally:
            entry.status, entry.ended = status, self._clock()
            if self._logging:
                log.info("%s: %s in %s", key, status, duration(entry.ended - entry.started))

    def snapshot(self) -> list[StepProgress]:
        """Every step now; the rates of running steps get a sample, so once per report."""
        now = self._clock()
        steps = []
        for entry in self._entries.values():
            counter = entry.counter
            end = now if entry.ended is None else entry.ended
            step = StepProgress(
                key=entry.key,
                status=entry.status,
                unit=counter.unit,
                done=counter.done,
                total=counter.total,
                started_at=entry.started_at,
                seconds=0.0 if entry.started_at is None else end - entry.started,
            )
            if entry.status == "running" and entry.window is not None:
                (rate,) = entry.window.rates(counter.done)
                step.rate = rate
                if rate > 0 and counter.total is not None:
                    step.eta_seconds = max(0, counter.total - counter.done) / rate
            steps.append(step)
        return steps

    def log_running(self, steps: list[StepProgress], database: DbActivity | None) -> None:
        """A line for each running step that does not log its progress itself."""
        quiet = {key for key, entry in self._entries.items() if not entry.log_progress}
        for step in steps:
            if step.status == "running" and step.key not in quiet:
                log.info("%s", _progress_line(step, database))

    def _entry(self, key: str) -> _Entry:
        return self._entries.setdefault(key, _Entry(key))


def _amount(value: float, unit: StepUnit | None) -> str:
    if unit == "bytes":
        return f"{value / 1024**2:,.1f} MB"
    return f"{value:,.0f} {unit}" if unit else f"{value:,.0f}"


def _progress_line(step: StepProgress, database: DbActivity | None) -> str:
    """The log line of a running step: "edges: running for 1m10s; database busy for 1m09s", or
    "attachments: 1,200 documents of 5,000 documents, 40.0 documents/s, about 1m35s left
    (estimate), running for 30s"."""
    parts = []
    if step.unit is not None:
        done = _amount(step.done, step.unit)
        parts.append(done if step.total is None else f"{done} of {_amount(step.total, step.unit)}")
        if step.rate is not None:
            per = "MB/s" if step.unit == "bytes" else f"{step.unit}/s"
            rate = step.rate / 1024**2 if step.unit == "bytes" else step.rate
            parts.append(f"{rate:,.1f} {per}")
        if step.eta_seconds is not None:
            parts.append(f"about {duration(step.eta_seconds)} left (estimate)")
    parts.append(f"running for {duration(step.seconds)}")
    line = f"{step.key}: {', '.join(parts)}"
    if step.unit is None and database is not None:
        doing = "waiting for a lock" if database.wait == "Lock" else "busy"
        line += f"; database {doing} for {duration(database.seconds)}"
    return line

"""The run side of `mailrobbe import` and `mailrobbe dkim` (D46, D47); jobs.py is the table side.

    job_run      connect; take the kind's advisory lock on a connection of the run's own; check
                 the schema; record the job; stop on Ctrl-C, SIGTERM or the dashboard's request;
                 report the figures every REPORT_SECONDS; record how the run ended
    RateWindow   throughput over the last RATE_WINDOW seconds

The reports go out from a task of their own on the lock connection, so they go on while the run
awaits something long (a finalize, a slow batch, a chunk of DKIM checks): job.updated_at shows
that the process lives, and a stop request is read within REPORT_SECONDS. A stop request sets the
same event as Ctrl-C, so everything after it is the Ctrl-C path of the command.

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
    begin_job,
    end_job,
    report_job,
)

log = logging.getLogger(__name__)

EXIT_INTERRUPTED = 130
REPEAT_SECONDS = 1.0  # a second Ctrl-C earlier than this is the first one delivered twice

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
Figures = Callable[[AsyncConnection], Awaitable[BaseModel]]


class RunRefused(Exception):
    """The run did not start: no database, another run of its kind is alive, or an old schema."""


def describe(error: BaseException) -> str:
    """An exception as one line of text PostgreSQL can store."""
    line = " ".join(f"{type(error).__name__}: {error}".split())[:500]
    return line.encode("utf-8", "replace").decode("utf-8").replace("\0", "")


class JobRun:
    """A started run as its command sees it: the stop event, the phase, and how it ends."""

    def __init__(self, connection: AsyncConnection, job_id: int, figures: Figures, phase: str):
        self.job_id = job_id
        self.stop = asyncio.Event()  # Ctrl-C, SIGTERM or a stop request from the dashboard
        self._connection = connection
        self._figures = figures
        self._phase = phase
        self._wake = asyncio.Event()
        self._closing = False
        self._outcome: tuple[JobStatus, str] | None = None

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
                progress = await self._figures(self._connection)
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
            progress = await self._figures(self._connection)
            await end_job(self._connection, self.job_id, status, message=message, progress=progress)
            await self._connection.commit()
        except _ERRORS as error:
            log.error("cannot record the end of the run: %s", describe(error))


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
        job_id = await begin_job(connection, kind, origin, options, phase)
        await connection.commit()
        run = JobRun(connection, job_id, figures, phase)
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

"""The `mailrobbe import` command: lock, schema check, scan, worker pool, finalize, summary.

Exit status: 0 when every file is done (import errors of single mails are normal), 1 when a file
ended in error or the import could not start, 130 when it was interrupted; the next run resumes.
"""

import argparse
import asyncio
import logging
import multiprocessing
import os
import signal
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import NoReturn

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from mailrobbe import migrate
from mailrobbe.config import Settings, get_settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.importer.finalize import finalize
from mailrobbe.importer.runner import DEFAULT_PIPELINE, FileOutcome, Pipeline, describe, run_files
from mailrobbe.importer.scan import ScanReport, scan

log = logging.getLogger(__name__)

# Key of the session-level advisory lock held for a whole run: one import at a time.
IMPORT_LOCK_KEY = int.from_bytes(b"mailrobb", "big")
_LOCK = text("SELECT pg_try_advisory_lock(:key)")
_UNLOCK = text("SELECT pg_advisory_unlock(:key)")
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INTERRUPTED = 130
REPEAT_SECONDS = 1.0  # a second Ctrl-C earlier than this is the first one delivered twice


def _worker_count(value: str) -> int:
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return count


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dir", type=Path, help="directory with the MBOX files (default: MAILROBBE_MBOX_DIR)"
    )
    parser.add_argument(
        "--workers",
        type=_worker_count,
        help="worker processes (default: MAILROBBE_IMPORT_WORKERS, min(8, CPU count))",
    )


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    workers = args.workers or max(1, settings.import_workers)
    try:
        return asyncio.run(run_import(settings, args.dir or settings.mbox_dir, workers))
    except KeyboardInterrupt:  # a second Ctrl-C: the next run resumes all the same
        log.error("aborted")
        return EXIT_INTERRUPTED


async def run_import(
    settings: Settings, mbox_dir: Path, workers: int, *, pipeline: Pipeline = DEFAULT_PIPELINE
) -> int:
    """The whole command; returns the exit status."""
    if not mbox_dir.is_dir():
        log.error("%s is not a directory", mbox_dir)
        return EXIT_FAILED
    # The DKIM checker looks for the generator's DNS override table below settings.mbox_dir.
    settings = settings.model_copy(update={"mbox_dir": mbox_dir})
    engine = create_engine(settings.database_url)
    try:
        connection = await engine.connect()
    except (OSError, DBAPIError) as error:
        await engine.dispose()
        log.error("cannot connect to the database: %s", describe(error))
        return EXIT_FAILED
    try:
        async with _import_lock(connection) as locked:
            if not locked:
                log.error("another import is running")
                return EXIT_FAILED
            problem = await _schema_problem(connection, settings.database_url)
            if problem is not None:
                log.error("%s", problem)
                return EXIT_FAILED
            stop = asyncio.Event()
            with _stop_on_signals(stop):
                sessionmaker = create_sessionmaker(engine)
                return await _import(sessionmaker, settings, mbox_dir, workers, stop, pipeline)
    finally:
        await connection.close()
        await engine.dispose()


@asynccontextmanager
async def _import_lock(connection: AsyncConnection) -> AsyncIterator[bool]:
    """The advisory lock of the whole run; yields whether this run got it."""
    locked = bool(await connection.scalar(_LOCK, {"key": IMPORT_LOCK_KEY}))
    await connection.commit()  # the lock belongs to the connection, not to the transaction
    try:
        yield locked
    finally:
        if locked:
            await connection.execute(_UNLOCK, {"key": IMPORT_LOCK_KEY})
            await connection.commit()


async def _schema_problem(connection: AsyncConnection, database_url: str) -> str | None:
    head = ScriptDirectory.from_config(migrate.alembic_config(database_url)).get_current_head()
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
def _stop_on_signals(stop: asyncio.Event) -> Iterator[None]:
    """Ctrl-C or SIGTERM sets `stop`; a second one, REPEAT_SECONDS or more later, aborts.

    `uv run` forwards a terminal's Ctrl-C to its child, which therefore gets it twice within
    milliseconds; that still counts as one.
    """
    loop = asyncio.get_running_loop()
    first: float | None = None

    def request(signum: int) -> None:
        nonlocal first
        now = time.monotonic()
        if first is None:
            first = now
            log.info("stopping after the current batches; Ctrl-C again aborts")
            stop.set()
        elif now - first >= REPEAT_SECONDS:
            abort()

    signals = (signal.SIGINT, signal.SIGTERM)
    for signum in signals:
        loop.add_signal_handler(signum, request, signum)
    try:
        yield
    finally:
        for signum in signals:
            loop.remove_signal_handler(signum)


def abort() -> NoReturn:
    """End the workers and this process at once, without waiting for any batch.

    Uncommitted batches roll back when their connections drop, so the next run resumes every
    file at its last committed batch, as after a crash.
    """
    for child in multiprocessing.active_children():
        child.kill()
    log.error("aborted: run `mailrobbe import` again to continue")
    os._exit(EXIT_INTERRUPTED)


async def _import(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    workers: int,
    stop: asyncio.Event,
    pipeline: Pipeline,
) -> int:
    started = time.monotonic()
    async with sessionmaker() as session:
        report = await scan(session, mbox_dir)
    _log_scan(report, mbox_dir)
    outcomes: list[FileOutcome] = []
    if not stop.is_set():
        outcomes = await run_files(
            sessionmaker, settings, mbox_dir, report.files, workers, stop, pipeline=pipeline
        )
    if not stop.is_set():
        async with sessionmaker() as session:
            result = await finalize(session)
        log.info(
            "updated duplicates, threads, display names and aggregates in %.1f s", result.seconds
        )
    async with sessionmaker() as session:
        summary, failed = await _summary(session, report, outcomes, time.monotonic() - started)
    print(summary)
    if stop.is_set():
        log.info("interrupted: run `mailrobbe import` again to continue")
        return EXIT_INTERRUPTED
    return EXIT_FAILED if failed else EXIT_OK


def _log_scan(report: ScanReport, mbox_dir: Path) -> None:
    log.info(
        "scan of %s: %d MBOX files, %d new, %d to import",
        mbox_dir,
        len(report.files),
        len(report.new),
        len(report.pending),
    )
    for path, reason in report.replaced:
        log.warning("replaced, importing again from the start: %s (%s)", path, reason)
    for path in report.missing:
        log.warning("missing on disk, its mails are kept: %s", path)
    for path, reason in report.unreadable:
        log.warning("skipped, cannot be read: %s (%s)", path, reason)


async def _summary(
    session: AsyncSession, report: ScanReport, outcomes: Sequence[FileOutcome], elapsed: float
) -> tuple[str, bool]:
    """The closing summary, and whether a file of this run ended in error."""
    ids = [file.id for file in report.files]
    statuses = {"done": 0, "error": 0}
    rows = await session.execute(
        text(
            "SELECT status::text, count(*) FROM mbox_file "
            "WHERE id = ANY(CAST(:ids AS bigint[])) GROUP BY status ORDER BY status"
        ),
        {"ids": ids},
    )
    statuses.update((status, count) for status, count in rows)
    mails, duplicates, threads = (
        await session.execute(
            text("SELECT count(*), count(is_duplicate_of), count(DISTINCT thread_id) FROM mail")
        )
    ).one()
    persons = await session.scalar(text("SELECT count(*) FROM person"))
    kinds = [
        (kind, count)
        for kind, count in await session.execute(
            text("SELECT kind, count(*) FROM import_error GROUP BY kind ORDER BY 2 DESC, 1")
        )
    ]
    imported = sum(outcome.mails for outcome in outcomes)
    by_kind = ", ".join(f"{kind} {count}" for kind, count in kinds)
    lines = [
        "files:         "
        + ", ".join(f"{count} {status}" for status, count in statuses.items())
        + f", {len(report.missing)} missing",
        f"mails:         {mails} ({imported} imported in this run)",
        f"duplicates:    {duplicates}",
        f"threads:       {threads}",
        f"persons:       {persons}",
        f"import errors: {sum(count for _, count in kinds)}" + (f" ({by_kind})" if kinds else ""),
        f"elapsed:       {elapsed:.1f} s, {imported / max(elapsed, 1e-9):.0f} mails/s",
    ]
    return "\n".join(lines), statuses["error"] > 0

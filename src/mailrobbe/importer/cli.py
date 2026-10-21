"""The `mailrobbe import` command: a run (jobrun) of scan, worker pool, finalize.

The run records itself in `job` (D47) with its phases scan, import and finalize, and reports its
figures (ImportFigures) every few seconds. It stops on Ctrl-C, SIGTERM and the dashboard's stop
request alike: the workers store their batch, the files pause, and the finalize is left to the
next run.

Exit status: 0 when every file is done (import errors of single mails are normal), 1 when a file
ended in error or the import could not start, 130 when it was stopped; the next run resumes.
"""

import argparse
import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.config import Settings, get_settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.enums import JobKind, JobOrigin, JobStatus, MboxStatus
from mailrobbe.importer.finalize import finalize
from mailrobbe.importer.runner import (
    DEFAULT_PIPELINE,
    FileOutcome,
    ImportFigures,
    Pipeline,
    run_files,
)
from mailrobbe.importer.scan import ScanReport, find_mbox_files, scan
from mailrobbe.jobrun import EXIT_INTERRUPTED, JobRun, RunRefused, job_run
from mailrobbe.jobs import ImportOptions

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1


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
    # Who started the run (job.origin); the dashboard's API passes ui.
    parser.add_argument(
        "--origin",
        type=JobOrigin,
        choices=list(JobOrigin),
        default=JobOrigin.CLI,
        help=argparse.SUPPRESS,
    )


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    workers = args.workers or max(1, settings.import_workers)
    try:
        return asyncio.run(
            run_import(settings, args.dir or settings.mbox_dir, workers, origin=args.origin)
        )
    except KeyboardInterrupt:  # a Ctrl-C before the run could take it over
        log.error("aborted")
        return EXIT_INTERRUPTED


async def run_import(
    settings: Settings,
    mbox_dir: Path,
    workers: int,
    *,
    pipeline: Pipeline = DEFAULT_PIPELINE,
    origin: JobOrigin = JobOrigin.CLI,
) -> int:
    """The whole command; returns the exit status."""
    if not mbox_dir.is_dir():
        log.error("%s is not a directory", mbox_dir)
        return EXIT_FAILED
    # The DKIM checker looks for the generator's DNS override table below settings.mbox_dir.
    settings = settings.model_copy(update={"mbox_dir": mbox_dir})
    options = ImportOptions.from_settings(settings, workers)
    figures = ImportFigures()
    engine = create_engine(settings.database_url)
    try:
        async with job_run(
            engine, JobKind.IMPORT, origin, options, phase="scan", figures=figures.report
        ) as job:
            sessionmaker = create_sessionmaker(engine)
            ending = await _import(
                sessionmaker, settings, mbox_dir, workers, job, figures, pipeline
            )
            job.end(ending.status, ending.message)
            return ending.exit_code
    except RunRefused as refusal:
        log.error("%s", refusal)
        return EXIT_FAILED
    finally:
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class _Ending:
    status: JobStatus
    message: str  # one line for job.message
    exit_code: int


async def _import(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    workers: int,
    job: JobRun,
    figures: ImportFigures,
    pipeline: Pipeline,
) -> _Ending:
    started = time.monotonic()
    stop = job.stop
    found = await asyncio.to_thread(find_mbox_files, mbox_dir)  # the event loop keeps reporting
    async with sessionmaker() as session:
        report = await scan(session, mbox_dir, found)
    _log_scan(report, mbox_dir)
    figures.files_queued = len(report.pending)
    outcomes: list[FileOutcome] = []
    if not stop.is_set():
        job.set_phase("import")
        outcomes = await run_files(
            sessionmaker,
            settings,
            mbox_dir,
            report.files,
            workers,
            stop,
            pipeline=pipeline,
            figures=figures,
        )
    if not stop.is_set():
        job.set_phase("finalize")
        async with sessionmaker() as session:
            result = await finalize(session)
        log.info(
            "updated duplicates, threads, display names and aggregates in %.1f s, "
            "%d of %d edges changed",
            result.seconds,
            result.edges.changed,
            result.edges.pairs,
        )
    async with sessionmaker() as session:
        summary = await _summary(session, report, outcomes, time.monotonic() - started)
    print(summary.text)
    if stop.is_set():
        log.info("interrupted: run `mailrobbe import` again to continue")
        return _Ending(JobStatus.STOPPED, summary.line, EXIT_INTERRUPTED)
    if summary.files_in_error:
        line = summary.line
        failed = [outcome for outcome in outcomes if outcome.status is MboxStatus.ERROR]
        if failed:  # the first one, so the message stays one line
            line += f"; {failed[0].path}: {failed[0].error}"
        return _Ending(JobStatus.FAILED, line, EXIT_FAILED)
    return _Ending(JobStatus.DONE, summary.line, EXIT_OK)


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


@dataclass(frozen=True, slots=True)
class _Summary:
    text: str  # printed at the end
    line: str  # the same in one line, for job.message
    files_in_error: int  # files of this run with status error


async def _summary(
    session: AsyncSession, report: ScanReport, outcomes: Sequence[FileOutcome], elapsed: float
) -> _Summary:
    """The closing summary, and how many files of this run ended in error."""
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
    errors = sum(count for _, count in kinds)
    by_kind = ", ".join(f"{kind} {count}" for kind, count in kinds)
    files = ", ".join(f"{count} {status}" for status, count in statuses.items())
    lines = [
        f"files:         {files}, {len(report.missing)} missing",
        f"mails:         {mails} ({imported} imported in this run)",
        f"duplicates:    {duplicates}",
        f"threads:       {threads}",
        f"persons:       {persons}",
        f"import errors: {errors}" + (f" ({by_kind})" if kinds else ""),
        f"elapsed:       {elapsed:.1f} s, {imported / max(elapsed, 1e-9):.0f} mails/s",
    ]
    line = (
        f"{imported} mails imported in {elapsed:.0f} s; {mails} mails, {errors} import errors; "
        f"files: {files}, {len(report.missing)} missing"
    )
    return _Summary("\n".join(lines), line, statuses["error"])

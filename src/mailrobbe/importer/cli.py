"""The `mailrobbe import` command: a run (jobrun) of scan, header refresh, worker pool, finalize,
text extraction, entities and signals.

The run records itself in `job` (D47) with its phases scan, headers (only when older files need
it, D52), import, finalize, attachments (only when documents wait for their text, D72), entities
(only when texts wait for their scan, D84) and signals (always, D135), and reports its figures
(ImportFigures) every few seconds, with one step per phase and per part of the finalize (STEPS,
D110). It stops on Ctrl-C, SIGTERM and the dashboard's stop request alike: the workers store
their batch, the files pause, the global figures count what is stored, and the finalize, the
attachments, the entities and the signals are left to the next run; during the attachments,
entities and signals phases, what is stored so far stays.

Exit status: 0 when every file is done (import errors of single mails are normal), 1 when a file
ended in error, the signals phase failed (a time zone PostgreSQL does not know, D133) or the
import could not start, 130 when it was stopped; the next run resumes.
"""

import argparse
import asyncio
import logging
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mailrobbe.aggregates import refresh_global_stats
from mailrobbe.attachments import phase
from mailrobbe.attachments.extract import extract_document
from mailrobbe.config import Settings, get_settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.entities import phase as entities
from mailrobbe.enums import JobKind, JobOrigin, JobStatus, MboxStatus
from mailrobbe.importer import finalize, headers
from mailrobbe.importer.runner import (
    DEFAULT_PIPELINE,
    FileOutcome,
    ImportFigures,
    Pipeline,
    run_files,
)
from mailrobbe.importer.scan import ScanReport, find_mbox_files, scan
from mailrobbe.jobrun import EXIT_INTERRUPTED, JobRun, RunRefused, job_run
from mailrobbe.jobs import ImportOptions, application_name
from mailrobbe.signals import phase as signals
from mailrobbe.signals.model import rules as signal_rules

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
# The steps of a run, in order (D110).
STEPS = ("scan", "headers", "import", *finalize.STEPS, "attachments", "entities", "signals")


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
    extract: phase.Extractor = extract_document,
) -> int:
    """The whole command; returns the exit status. extract: tests hand in doubles."""
    if not mbox_dir.is_dir():
        log.error("%s is not a directory", mbox_dir)
        return EXIT_FAILED
    # The DKIM checker looks for the generator's DNS override table below settings.mbox_dir.
    settings = settings.model_copy(update={"mbox_dir": mbox_dir})
    options = ImportOptions.from_settings(settings, workers)
    figures = ImportFigures()
    engine = create_engine(settings.database_url, application_name(JobKind.IMPORT))
    try:
        async with job_run(
            engine, JobKind.IMPORT, origin, options, phase="scan", figures=figures.report
        ) as job:
            sessionmaker = create_sessionmaker(engine)
            ending = await _import(
                sessionmaker, settings, mbox_dir, workers, job, figures, pipeline, extract, engine
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
    extract: phase.Extractor,
    engine: AsyncEngine,
) -> _Ending:
    started = time.monotonic()
    stop = job.stop
    job.steps.plan(*STEPS)
    with job.steps.step("scan"):
        found = await asyncio.to_thread(find_mbox_files, mbox_dir)  # the event loop reports on
        async with sessionmaker() as session:
            report = await scan(session, mbox_dir, found)
    _log_scan(report, mbox_dir)
    figures.files_queued = len(report.pending)
    if not stop.is_set():
        await _refresh_headers(sessionmaker, mbox_dir, job)
    outcomes: list[FileOutcome] = []
    if not stop.is_set():
        job.set_phase("import")
        outcomes = await _import_files(
            sessionmaker, settings, mbox_dir, report, workers, job, figures, pipeline
        )
    if not stop.is_set():
        job.set_phase("finalize")
        async with sessionmaker() as session:
            result = await finalize.finalize(session, job.steps)
        log.info(
            "updated duplicates, threads, display names and aggregates in %.1f s, "
            "%d of %d edges changed",
            result.seconds,
            result.edges.changed,
            result.edges.pairs,
        )
    extracted = 0
    if not stop.is_set():
        extracted = await _extract_texts(
            sessionmaker, settings, mbox_dir, workers, job, figures, extract
        )
    scanned = 0
    if not stop.is_set():
        scanned = await _scan_entities(sessionmaker, workers, job)
    failure = None
    if not stop.is_set():
        failure = await _compute_signals(engine, settings, job)
    async with sessionmaker() as session:
        summary = await _summary(
            session, report, outcomes, extracted, scanned, time.monotonic() - started
        )
    print(summary.text)
    if stop.is_set():
        # The figures in the header and on the dashboard count the mails stored so far (D48).
        async with sessionmaker() as session, session.begin():
            await refresh_global_stats(session)
        log.info("interrupted: run `mailrobbe import` again to continue")
        return _Ending(JobStatus.STOPPED, summary.line, EXIT_INTERRUPTED)
    if summary.files_in_error:
        line = summary.line
        failed = [outcome for outcome in outcomes if outcome.status is MboxStatus.ERROR]
        if failed:  # the first one, so the message stays one line
            line += f"; {failed[0].path}: {failed[0].error}"
        return _Ending(JobStatus.FAILED, line, EXIT_FAILED)
    if failure is not None:
        return _Ending(JobStatus.FAILED, f"{summary.line}; {failure}", EXIT_FAILED)
    return _Ending(JobStatus.DONE, summary.line, EXIT_OK)


async def _refresh_headers(
    sessionmaker: async_sessionmaker[AsyncSession], mbox_dir: Path, job: JobRun
) -> None:
    """The headers phase (D52), when files imported before need it."""
    async with sessionmaker() as session:
        files = await headers.outdated_files(session)
    if not files:
        job.steps.skip("headers")
        return
    total = sum(file.mails for file in files)
    job.set_phase("headers")
    log.info("reading the headers of %d mails in %d files imported before again", total, len(files))
    with job.steps.step("headers", unit="mails", total=total) as step:
        await headers.refresh_headers(sessionmaker, mbox_dir, files, job.stop, step)


async def _import_files(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    report: ScanReport,
    workers: int,
    job: JobRun,
    figures: ImportFigures,
    pipeline: Pipeline,
) -> list[FileOutcome]:
    """The import phase: the pending files, as a step counting their bytes left."""
    if not report.pending:
        job.steps.skip("import")
        return []
    left = sum(max(0, file.size_bytes - file.bytes_done) for file in report.pending)
    # The runner logs its progress itself, with files, mails and import errors.
    with job.steps.step("import", unit="bytes", total=left, log_progress=False) as step:
        figures.step = step
        outcomes = await run_files(
            sessionmaker,
            settings,
            mbox_dir,
            report.files,
            workers,
            job.stop,
            pipeline=pipeline,
            figures=figures,
            steps=job.steps,
        )
        async with sessionmaker() as session:
            await figures.report(session)  # the bytes of the last batches
    figures.step = None
    return outcomes


async def _extract_texts(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    workers: int,
    job: JobRun,
    figures: ImportFigures,
    extract: phase.Extractor,
) -> int:
    """The attachments phase (D72), when documents wait for their text; the documents stored."""
    async with sessionmaker() as session:
        waiting = await phase.waiting_documents(session, int(settings.attachment_text_max_size))
    if not waiting:
        job.steps.skip("attachments")
        return 0
    job.set_phase("attachments")
    with job.steps.step("attachments", unit="documents", total=len(waiting)) as step:
        result = await phase.extract_texts(
            sessionmaker,
            settings,
            mbox_dir,
            waiting,
            workers,
            job.stop,
            figures,
            step,
            extract=extract,
        )
    return result.stored


async def _scan_entities(
    sessionmaker: async_sessionmaker[AsyncSession], workers: int, job: JobRun
) -> int:
    """The entities phase (D84), when texts wait for their scan; the texts scanned."""
    async with sessionmaker() as session:
        waiting = await entities.waiting(session)
    if not waiting:
        job.steps.skip("entities")
        return 0
    job.set_phase("entities")
    with job.steps.step("entities", unit="bytes", total=waiting.bytes) as step:
        result = await entities.scan_entities(sessionmaker, workers, job.stop, step)
    return result.mails + result.documents


async def _compute_signals(engine: AsyncEngine, settings: Settings, job: JobRun) -> str | None:
    """The signals phase (D135), after every import that was not stopped; why it failed."""
    job.set_phase("signals")
    try:
        with job.steps.step("signals") as step:
            await signals.compute_signals(engine, signal_rules(settings), job.stop, step)
    except signals.UnknownTimeZone as error:
        log.error("signals: %s", error)
        return str(error)
    return None


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
    session: AsyncSession,
    report: ScanReport,
    outcomes: Sequence[FileOutcome],
    extracted: int,
    scanned: int,
    elapsed: float,
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
    found = await session.scalar(text("SELECT count(*) FROM entity"))
    signalled = await session.scalar(text("SELECT count(DISTINCT mail_id) FROM mail_signal"))
    silent = await session.scalar(
        text("SELECT count(*) FROM person_signal WHERE signal = 'silent'")
    )
    kinds = [
        (kind, count)
        for kind, count in await session.execute(
            text("SELECT kind, count(*) FROM import_error GROUP BY kind ORDER BY 2 DESC, 1")
        )
    ]
    documents: Counter[str] = Counter()
    rows = await session.execute(
        text("SELECT text_status::text, count(*) FROM document GROUP BY text_status")
    )
    for status, count in rows:
        documents[status] = count
    with_text = documents["text"] + documents["timeout"]  # a timeout keeps the text read
    waiting = documents["pending"] + documents["unreadable"]
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
        f"documents:     {documents.total()} ({with_text} with text, {waiting} waiting; "
        f"{extracted} stored in this run)",
        f"entities:      {found} ({scanned} texts scanned in this run)",
        f"signals:       {signalled} mails with a signal, {silent} persons silent",
        f"elapsed:       {elapsed:.1f} s, {imported / max(elapsed, 1e-9):.0f} mails/s",
    ]
    line = (
        f"{imported} mails imported in {elapsed:.0f} s; {mails} mails, {errors} import errors; "
        f"{with_text} of {documents.total()} documents with text, {waiting} waiting; "
        f"files: {files}, {len(report.missing)} missing"
    )
    return _Summary("\n".join(lines), line, statuses["error"])

"""The `mailrobbe import` command: a run (jobrun) of scan, header refresh, worker pool, finalize,
archives, text extraction, passwords, metadata, calendar, near duplicates, hide rules,
paragraphs, entities, places, signals and topics.

The run records itself in `job` (D47) with its phases scan, headers (only when older files need it,
D52), import, finalize, attachments (with the steps archives, when containers wait to be unpacked,
D231; attachments, when documents wait for their text, D72; passwords, when a locked document could
be opened, D235; metadata, when documents wait for their metadata, D167), calendar (only when mails
wait for a look, D154), near (fingerprints when mails wait for one, groups always, D153), hidden
(always, D221), paragraphs (the split when mails wait for it, the standard blocks always, D224,
D225), entities (only when texts wait for their scan, D84), places (only when place entities or
invitations wait for a point, or the lists changed, D242, D243), signals (always, D135) and topics
(only when the archive changed since they were computed, D146), and reports its figures
(ImportFigures) every few seconds, with one step per phase and per part of the finalize and the
topics (STEPS, D110). It stops on Ctrl-C, SIGTERM and the dashboard's stop request alike: the
workers store their batch, the files pause, the global figures count what is stored, and the
finalize and every later phase are left to the next run; during the attachments, calendar, near,
paragraphs, entities, places and signals phases, what is stored so far stays, and the topics stay
as last computed.

Exit status: 0 when every file is done (import errors of single mails are normal), 1 when a file
ended in error, the signals phase failed (a time zone PostgreSQL does not know, D133) or the
import could not start (also while an AI run is alive, D187), 130 when it was stopped; the next
run resumes.
"""

import argparse
import asyncio
import logging
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mailrobbe.aggregates import refresh_global_stats
from mailrobbe.attachments import containers, phase
from mailrobbe.attachments.extract import extract_document
from mailrobbe.blocks import phase as blocks
from mailrobbe.config import Settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.entities import phase as entities
from mailrobbe.enums import JobKind, JobOrigin, JobStatus, MboxStatus
from mailrobbe.hiding import phase as hiding
from mailrobbe.ical import phase as calendar
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
from mailrobbe.near import phase as near
from mailrobbe.passwords import phase as passwords
from mailrobbe.places import phase as places
from mailrobbe.signals import phase as signals
from mailrobbe.signals.model import rules as signal_rules
from mailrobbe.stored_settings import command_settings
from mailrobbe.topics import phase as topics

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
STEPS = (
    "scan",
    "headers",
    "import",
    *finalize.STEPS,
    "archives",
    "attachments",
    "passwords",
    "metadata",
    "calendar",
    *near.STEPS,
    hiding.STEP,
    *blocks.STEPS,
    "entities",
    places.STEP,
    "signals",
    *topics.STEPS,
)  # in order


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
    settings = command_settings(args.origin)
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
            engine,
            JobKind.IMPORT,
            origin,
            options,
            phase="scan",
            figures=figures.report,
            excluded=(JobKind.AI,),  # an AI run writes document texts (D187)
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
    if not stop.is_set():
        await _unpack_containers(sessionmaker, settings, mbox_dir, workers, job)
    extracted = 0
    if not stop.is_set():
        extracted = await _extract_texts(
            sessionmaker, settings, mbox_dir, workers, job, figures, extract
        )
    if not stop.is_set():
        await _open_protected(sessionmaker, settings, mbox_dir, workers, job)
    if not stop.is_set():
        await _collect_metadata(sessionmaker, settings, mbox_dir, workers, job, figures)
    if not stop.is_set():
        await _scan_calendar(sessionmaker, mbox_dir, workers, job)
    if not stop.is_set():
        await _find_near(sessionmaker, job)
    if not stop.is_set():
        await _refresh_hidden(sessionmaker, job)
    if not stop.is_set():
        await _find_blocks(sessionmaker, settings, job)
    scanned = 0
    if not stop.is_set():
        scanned = await _scan_entities(sessionmaker, workers, job)
    if not stop.is_set():
        await _locate_places(sessionmaker, job)
    failure = None
    if not stop.is_set():
        failure = await _compute_signals(engine, settings, job)
    computed: _Topics = None
    if not stop.is_set():
        computed = await _compute_topics(sessionmaker, job)
    async with sessionmaker() as session:
        summary = await _summary(
            session, report, outcomes, extracted, scanned, computed, time.monotonic() - started
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


async def _unpack_containers(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    workers: int,
    job: JobRun,
) -> None:
    """The archives step (D231), when containers wait to be unpacked."""
    async with sessionmaker() as session:
        waiting = await containers.waiting_containers(session)
    if not waiting:
        job.steps.skip("archives")
        return
    job.set_phase("attachments")  # the step belongs to the attachments phase (jobs.ImportPhase)
    with job.steps.step("archives", unit="documents", total=len(waiting)) as step:
        await containers.unpack_containers(
            sessionmaker, settings, mbox_dir, waiting, workers, job.stop, step
        )


async def _open_protected(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    workers: int,
    job: JobRun,
) -> None:
    """The passwords step (D235), when a locked document could be opened."""
    async with sessionmaker() as session:
        waiting = await passwords.waiting(session)
    if not waiting:
        job.steps.skip("passwords")
        return
    job.set_phase("attachments")
    with job.steps.step("passwords", unit="documents", total=waiting) as step:
        await passwords.run_passwords(sessionmaker, settings, mbox_dir, workers, job.stop, step)


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


async def _collect_metadata(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    workers: int,
    job: JobRun,
    figures: ImportFigures,
) -> None:
    """The metadata step (D167), when documents wait for their metadata."""
    async with sessionmaker() as session:
        waiting = await phase.metadata_waiting(session, int(settings.attachment_text_max_size))
    if not waiting:
        job.steps.skip("metadata")
        return
    job.set_phase("attachments")  # the step belongs to the attachments phase (jobs.ImportPhase)
    with job.steps.step("metadata", unit="documents", total=len(waiting)) as step:
        await phase.collect_metadata(
            sessionmaker, settings, mbox_dir, waiting, workers, job.stop, figures, step
        )


async def _scan_calendar(
    sessionmaker: async_sessionmaker[AsyncSession], mbox_dir: Path, workers: int, job: JobRun
) -> None:
    """The calendar phase (D154), when mails wait for a look at their calendar parts."""
    async with sessionmaker() as session:
        waiting = await calendar.waiting(session)
    if not waiting:
        job.steps.skip("calendar")
        return
    job.set_phase("calendar")
    with job.steps.step("calendar", unit="mails", total=waiting) as step:
        await calendar.scan_calendar(sessionmaker, mbox_dir, workers, job.stop, step)


async def _find_near(sessionmaker: async_sessionmaker[AsyncSession], job: JobRun) -> None:
    """The near phase (D153): fingerprints when mails wait for one, then the groups."""
    job.set_phase("near")
    async with sessionmaker() as session:
        waiting = await near.waiting(session)
    if waiting:
        with job.steps.step("near_texts", unit="mails", total=waiting) as step:
            await near.fingerprint_mails(sessionmaker, job.stop, step)
    else:
        job.steps.skip("near_texts")
    if job.stop.is_set():
        return
    with job.steps.step("near_groups") as step:
        await near.group_mails(sessionmaker, job.stop, step)


async def _refresh_hidden(sessionmaker: async_sessionmaker[AsyncSession], job: JobRun) -> None:
    """The step hidden (D221): the mails of every enabled hide rule, new mails and the addresses
    merges gave a person included."""
    job.set_phase("hidden")
    with job.steps.step(hiding.STEP) as step:
        await hiding.refresh_hidden(sessionmaker, job.stop, step)


async def _find_blocks(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, job: JobRun
) -> None:
    """The paragraphs phase (D224, D225): the split when mails wait for it, then the standard
    blocks and the ranges of every mail whose ranges changed."""
    job.set_phase("paragraphs")
    async with sessionmaker() as session:
        waiting = await blocks.waiting(session)
    if waiting:
        with job.steps.step("paragraphs", unit="mails", total=waiting) as step:
            await blocks.split_mails(sessionmaker, job.stop, step)
    else:
        job.steps.skip("paragraphs")
    if job.stop.is_set():
        return
    with job.steps.step("blocks") as step:
        await blocks.find_blocks(sessionmaker, settings, job.stop, step)


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


async def _locate_places(sessionmaker: async_sessionmaker[AsyncSession], job: JobRun) -> None:
    """The places phase (D242, D243), when place entities or invitations wait for a point or
    the lists changed."""
    async with sessionmaker() as session:
        plan = await places.waiting(session)
    if not plan.outdated and not plan.rows:
        job.steps.skip(places.STEP)
        return
    job.set_phase("places")
    with job.steps.step(places.STEP, unit="places", total=plan.rows) as step:
        await places.locate_places(sessionmaker, plan, job.stop, step)


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


# What the topics phase of a run did: computed them, found them unchanged, or not computed them
# (stopped, or not reached).
_Topics = topics.TopicsResult | Literal["unchanged"] | None


async def _compute_topics(sessionmaker: async_sessionmaker[AsyncSession], job: JobRun) -> _Topics:
    """The topics phase (D146), when the archive changed since the topics were computed."""
    async with sessionmaker() as session:
        fingerprint = await topics.waiting(session)
    if fingerprint is None:
        job.steps.skip(*topics.STEPS)
        log.info("topics unchanged: the archive is the one they were computed for")
        return "unchanged"
    job.set_phase("topics")
    result = await topics.compute_topics(sessionmaker, fingerprint, job.stop, job.steps)
    if result is not None:
        log.info(
            "computed the topics in %.1f s: %d terms, %d periods, %d clusters",
            result.seconds,
            result.terms,
            result.periods,
            result.clusters,
        )
    return result


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
    computed: _Topics,
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
    located = await session.scalar(text("SELECT count(*) FROM entity WHERE latitude IS NOT NULL"))
    meeting = await session.scalar(
        text("SELECT count(*) FROM calendar_event WHERE latitude IS NOT NULL")
    )
    events, invited = (
        await session.execute(text("SELECT count(*), count(DISTINCT mail_id) FROM calendar_event"))
    ).one()
    groups, grouped = (
        await session.execute(
            text(
                "SELECT count(DISTINCT group_id), count(*) FROM mail_near "
                "WHERE group_id IS NOT NULL"
            )
        )
    ).one()
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
        f"calendar:      {events} events in {invited} mails",
        f"near:          {groups} groups of near duplicates, {grouped} mails in them",
        f"entities:      {found} ({scanned} texts scanned in this run)",
        f"places:        {located} places named with a point, {meeting} events with one",
        f"signals:       {signalled} mails with a signal, {silent} persons silent",
        f"topics:        {_topics_line(computed)}",
        f"elapsed:       {elapsed:.1f} s, {imported / max(elapsed, 1e-9):.0f} mails/s",
    ]
    line = (
        f"{imported} mails imported in {elapsed:.0f} s; {mails} mails, {errors} import errors; "
        f"{with_text} of {documents.total()} documents with text, {waiting} waiting; "
        f"files: {files}, {len(report.missing)} missing"
    )
    return _Summary("\n".join(lines), line, statuses["error"])


def _topics_line(computed: _Topics) -> str:
    if computed is None:
        return "not computed in this run"
    if computed == "unchanged":
        return "unchanged"
    return (
        f"{computed.terms} terms, {computed.periods} periods, {computed.clusters} clusters "
        f"({computed.seconds:.1f} s)"
    )

"""`mailrobbe ai`: text of scanned PDFs and images from Tesseract or a vision model (D180 to D189),
transcripts of audio and video from Parakeet (D290 to D297), summaries, AI tags and theme hints
of mails and documents from a text model (D300 to D308), and the alias check (D321 to D323).

    run     work through the queue (ai.run): a run of kind ai with the steps check, ocr,
            transcribe, summarize, entities and signals; stoppable at any page, piece of a
            recording or part, the next run continues there. --document, --mail and --thread
            take only the tasks of these elements; --aliases takes no task and asks the text
            model about the alias candidates instead (ai.aliases)
    check   ask each configured service for real (a picture with a known word for vision, a
            short text whose summary must name that word for text) and print what it found as
            JSON
    queue   put a selection on the queue: the work lists "scanned", "images" and "media" of the
            AI page, or documents by id (D186, D295); with --summarize, summaries of mails, of
            the mails of an Akte, of documents and of threads (D308, D316)
    model   print the state of the transcriber's files as JSON; with --download fetch what is
            missing (D291), which a run that transcribes also does in its check step
    status  print the tasks per kind and status, the transcriber and the latest run as JSON

The dashboard starts `mailrobbe ai --origin ui run [options]` as a child process (D46) and stops
it with a stop request; "Zusammenfassen" on a mail or a document starts it with --mail=ID or
--document=ID (D307), "Mit KI prüfen" on the alias suggestions with --aliases (D321), "KI
fragen" on one suggestion with --aliases --person=A --person=B (D328). Exit status of run as in
ai.run: 0 done, 130 stopped by request, 1 when it could not start or ended early for a reason it
names, 2 for arguments it cannot use; check exits with 1 when a configured
service fails. `model --download` holds the lock of the AI runs while it
downloads, so it refuses (1) while a run is alive and a run refuses meanwhile; Ctrl-C stops it
(130), keeping what came for the next download.
"""

import argparse
import asyncio
import json
import logging
import threading
import time
from dataclasses import asdict
from typing import Any, get_args

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from mailrobbe import jobs
from mailrobbe.ai.aliases.candidates import GROUP_MAX
from mailrobbe.ai.audio import parakeet
from mailrobbe.ai.model import (
    TRANSCRIBE_MODEL,
    AiOptions,
    OcrEngineChoice,
    ServiceCheck,
    configured_services,
    transcribe_threads,
    transcriber_available,
)
from mailrobbe.ai.queue import enqueue, enqueue_summaries, task_counts, work_list_ids
from mailrobbe.ai.run import EXIT_FAILED, Engines, default_engines, run_ai
from mailrobbe.config import Settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.dkim.cli import error_line
from mailrobbe.enums import JobKind, JobOrigin
from mailrobbe.jobrun import EXIT_INTERRUPTED, RunRefused, describe, stop_on_signals
from mailrobbe.jobs import latest_job
from mailrobbe.stored_settings import command_settings

log = logging.getLogger(__name__)

EXIT_USAGE = 2
# The mails of Akten: every mail with the content of one in them (D53); duplicates share a task.
_AKTE_MAILS = text("""
    SELECT m.id FROM collection_mail c JOIN mail m ON m.raw_sha256 = c.mail_sha256
    WHERE c.collection_id = ANY(CAST(:ids AS bigint[]))
""")


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def add_arguments(parser: argparse.ArgumentParser) -> None:
    # Who started the run (job.origin); the dashboard's API passes ui before the task.
    parser.add_argument(
        "--origin",
        type=JobOrigin,
        choices=list(JobOrigin),
        default=JobOrigin.CLI,
        help=argparse.SUPPRESS,
    )
    tasks = parser.add_subparsers(dest="task", required=True, metavar="TASK")
    engines = get_args(OcrEngineChoice)
    work = tasks.add_parser(
        "run",
        help="recognise and transcribe the queued documents and summarise the queued texts",
        description="Work through the queue: render the pages of each queued document, read "
        "them with Tesseract or the vision model and store the text; decode each queued "
        "recording and transcribe its speech with Parakeet, downloading the model's files "
        "first when they are missing (MAILROBBE_AI_MODEL_DIR). Both texts become searchable "
        "like an extracted one; summarise the queued mails and documents with the text model, "
        "with AI tags and theme hints; then scan the new texts for entities and compute the "
        "signals. Ctrl-C stops after the page, piece or part in work; the next run continues "
        "there.",
    )
    work.add_argument(
        "--engine",
        choices=engines,
        help="for tasks queued with auto: auto (PDFs with Tesseract, images with the vision "
        "model when one is set, uncertain pages again with it), tesseract or vision "
        "(default: MAILROBBE_AI_OCR_ENGINE)",
    )
    work.add_argument(
        "--vision-model", help="the vision model for this run (default: MAILROBBE_AI_VISION_MODEL)"
    )
    work.add_argument(
        "--max-pages",
        type=_positive,
        help="pages per document and pass at most (default: MAILROBBE_AI_OCR_MAX_PAGES)",
    )
    work.add_argument(
        "--concurrency",
        type=_positive,
        help="requests to the vision service at once (default: MAILROBBE_AI_CONCURRENCY)",
    )
    work.add_argument(
        "--max-minutes",
        type=_positive,
        help="minutes per recording and pass at most "
        "(default: MAILROBBE_AI_TRANSCRIBE_MAX_MINUTES)",
    )
    work.add_argument(
        "--document",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="read only this queued document, leaving the rest of the queue waiting; repeatable",
    )
    work.add_argument(
        "--mail",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="summarise only this queued mail (with --document: and these documents), leaving "
        "the rest of the queue waiting; repeatable",
    )
    work.add_argument(
        "--thread",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="summarise only this queued thread (mail.thread_id), as --mail; repeatable",
    )
    work.add_argument(
        "--question",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="answer this question about persons (person_question.id) and what it waits for, "
        "leaving the rest of the queue waiting; repeatable",
    )
    work.add_argument(
        "--text-model", help="the text model for this run (default: MAILROBBE_AI_TEXT_MODEL)"
    )
    work.add_argument(
        "--aliases",
        action="store_true",
        help="take no task: ask the text model, on this machine only, whether the persons of "
        "each uncertain alias suggestion and of similar names are one person, and keep its "
        "verdict beside the suggestions; it never merges",
    )
    work.add_argument(
        "--person",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="with --aliases: ask only about these persons, 2 to 6, as one group, even when "
        "they were checked before; repeatable",
    )
    work.add_argument("--quiet", action="store_true", help="no progress output")
    tasks.add_parser(
        "check",
        help="test the configured AI services and print what they answered as JSON",
        description="Ask each configured service for its models, read a picture with a known "
        "word with the vision model and have the text model summarise a short text naming that "
        "word; refused services (outside this machine without MAILROBBE_AI_ALLOW_REMOTE) are "
        "not asked. Exits with 1 when one fails.",
    )
    queue = tasks.add_parser(
        "queue",
        help="queue documents for OCR or transcription, or mails and documents for summaries",
        description="Queue OCR for the scanned PDFs, the images of the AI page's work list "
        "(100 KB and more, in at most 50 mails), a transcription for the recordings, or what "
        "fits documents by id. Documents with a text of their own and documents without a "
        "SHA-256 are left out. With --summarize, queue summaries of mails, of the mails of "
        "an Akte and of documents with a text instead.",
    )
    queue.add_argument(
        "--summarize",
        action="store_true",
        help="summaries, AI tags and theme hints of --mail, --collection, --document and --thread",
    )
    queue.add_argument(
        "--thread",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="a thread by mail.thread_id, summarised as a whole; repeatable",
    )
    queue.add_argument(
        "--mail", type=int, action="append", default=[], metavar="ID", help="a mail; repeatable"
    )
    queue.add_argument(
        "--collection",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="the mails of an Akte; repeatable",
    )
    queue.add_argument("--scanned", action="store_true", help="every scanned PDF not read yet")
    queue.add_argument("--images", action="store_true", help="the work list of images")
    queue.add_argument(
        "--media", action="store_true", help="every recording (audio, video) not transcribed yet"
    )
    queue.add_argument(
        "--document",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="a document by id; repeatable",
    )
    queue.add_argument(
        "--engine",
        choices=engines,
        default="auto",
        help="the engine of the OCR tasks (default: auto); a transcription has its own",
    )
    queue.add_argument(
        "--include-logos",
        action="store_true",
        help="also images carried by more than 50 mails, mostly logos of signatures",
    )
    model = tasks.add_parser(
        "model",
        help="print or download the transcriber's model files",
        description="Print as JSON whether the files of the transcriber (Parakeet and Silero "
        "VAD, about 670 MB) are in MAILROBBE_AI_MODEL_DIR. With --download fetch what is "
        "missing from Hugging Face, each file checked against its SHA-256; a run with "
        "transcribe tasks does so itself. Refused while an AI run is alive; Ctrl-C stops and "
        "keeps what came.",
    )
    model.add_argument("--download", action="store_true", help="download the missing files now")
    tasks.add_parser(
        "status",
        help="print the queue, the transcriber and the latest run as JSON",
        description="Print the tasks per kind and status, the transcriber's state and the "
        "latest AI run as JSON.",
    )


def run(args: argparse.Namespace) -> int:
    quiet = getattr(args, "quiet", False)
    logging.basicConfig(level=logging.WARNING if quiet else logging.INFO, format="%(message)s")
    settings = command_settings(args.origin)
    try:
        if args.task == "check":
            checks = asyncio.run(check(settings))
            print(json.dumps([found.model_dump(mode="json") for found in checks], indent=2))
            return EXIT_FAILED if any(failed(found) for found in checks) else 0
        if args.task == "queue":
            return asyncio.run(_queue(settings, args))
        if args.task == "model":
            code = asyncio.run(download(settings)) if args.download else 0
            print(json.dumps(transcriber(settings), indent=2))
            return code
        if args.task == "status":
            print(json.dumps(asyncio.run(status(settings)), indent=2))
            return 0
        persons = set(getattr(args, "person", []))
        if persons and not (args.aliases and 2 <= len(persons) <= GROUP_MAX):
            log.error("--person takes 2 to %d persons, with --aliases", GROUP_MAX)
            return EXIT_FAILED
        result = asyncio.run(run_ai(settings, options(settings, args), origin=args.origin))
    except RunRefused as refused:
        log.error("%s", refused)
        return EXIT_FAILED
    except SQLAlchemyError as error:
        log.error("database error: %s", error_line(error))
        return EXIT_FAILED
    print(json.dumps(asdict(result.summary), indent=2))
    return result.exit_code


def options(settings: Settings, args: argparse.Namespace) -> AiOptions:
    """The run's options: the settings, with what the command line gives."""
    found = AiOptions.from_settings(settings)
    update: dict[str, Any] = {}
    if args.engine:
        update["ocr_engine"] = args.engine
    if args.vision_model:
        update["vision_model"] = args.vision_model.strip()
    if args.max_pages:
        update["max_pages"] = args.max_pages
    if args.concurrency:
        update["concurrency"] = args.concurrency
    if args.max_minutes:
        update["max_minutes"] = args.max_minutes
    if args.document:
        update["documents"] = sorted(set(args.document))
    if args.mail:
        update["mails"] = sorted(set(args.mail))
    if args.thread:
        update["threads"] = sorted(set(args.thread))
    if args.question:
        update["questions"] = sorted(set(args.question))
    if args.text_model:
        update["text_model"] = args.text_model.strip()
    if args.aliases:
        update["aliases"] = True
    if args.person:
        update["persons"] = sorted(set(args.person))
    return found.model_copy(update=update)


async def check(settings: Settings, engines: Engines | None = None) -> list[ServiceCheck]:
    """Each configured service checked for real, in the order of the capabilities."""
    services = configured_services(settings)
    if not services:
        log.info("no AI service is configured (MAILROBBE_AI_VISION_URL, MAILROBBE_AI_TEXT_URL)")
        return []
    engines = engines or default_engines()
    return [
        await asyncio.to_thread(engines.check, service, settings, test=True)
        for service in services.values()
    ]


def failed(found: ServiceCheck) -> bool:
    """Whether a check found the service unusable."""
    return bool(
        found.refused
        or found.reachable is False
        or found.model_found is False
        or found.test == "failed"
        or found.error
    )


async def _queue(settings: Settings, args: argparse.Namespace) -> int:
    if args.summarize:
        return await _queue_summaries(settings, args)
    if args.mail or args.collection or args.thread:
        log.error("--mail, --collection and --thread queue summaries: add --summarize")
        return EXIT_USAGE
    if not (args.scanned or args.images or args.media or args.document):
        log.error("name what to queue: --scanned, --images, --media or --document ID")
        return EXIT_USAGE
    engine = create_engine(settings.database_url)
    try:
        async with create_sessionmaker(engine).begin() as session:
            ids = list(args.document)
            if args.scanned:
                ids += await work_list_ids(session, "scanned")
            if args.images:
                ids += await work_list_ids(session, "images")
            if args.media:
                ids += await work_list_ids(session, "media")
            queued = await enqueue(
                session, ids, engine=args.engine, include_logos=args.include_logos
            )
    finally:
        await engine.dispose()
    print(json.dumps(asdict(queued), indent=2))
    return 0


async def _queue_summaries(settings: Settings, args: argparse.Namespace) -> int:
    """Summaries of the mails, the Akten's mails and the documents named (D308)."""
    if args.scanned or args.images or args.media:
        log.error(
            "--summarize takes --mail, --collection, --document and --thread, not a work list"
        )
        return EXIT_USAGE
    if not (args.mail or args.collection or args.document or args.thread):
        log.error("name what to summarise: --mail, --collection, --document or --thread ID")
        return EXIT_USAGE
    engine = create_engine(settings.database_url)
    try:
        async with create_sessionmaker(engine).begin() as session:
            mails = list(args.mail)
            if args.collection:
                found = await session.execute(_AKTE_MAILS, {"ids": args.collection})
                mails += found.scalars()
            queued = await enqueue_summaries(
                session, mail_ids=mails, document_ids=args.document, thread_ids=args.thread
            )
    finally:
        await engine.dispose()
    print(json.dumps(asdict(queued), indent=2))
    return 0


def transcriber(settings: Settings) -> dict[str, Any]:
    """The transcriber's state, as `mailrobbe ai model` and `status` print it."""
    state = parakeet.model_state(settings.ai_model_dir)
    return {
        "model": TRANSCRIBE_MODEL,
        "available": transcriber_available(),
        "model_dir": str(settings.ai_model_dir),
        "ready": state.ready,
        "missing_bytes": state.missing_bytes,
        "total_bytes": state.total_bytes,
        "threads": transcribe_threads(settings),
        "max_minutes": settings.ai_transcribe_max_minutes,
    }


async def download(settings: Settings) -> int:
    """Download the transcriber's missing files while holding the lock of the AI runs."""
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            locked = await connection.scalar(select(func.pg_try_advisory_lock(jobs.AI_LOCK_KEY)))
            await connection.commit()
            if not locked:
                log.error("an AI run is running: it downloads the model itself when it needs it")
                return EXIT_FAILED
            return await _download(settings)
    finally:
        await engine.dispose()  # the lock ends with the connection


async def _download(settings: Settings) -> int:
    directory = settings.ai_model_dir
    state = await asyncio.to_thread(parakeet.model_state, directory)
    if state.ready:
        log.info("the model is complete in %s", directory)
        return 0
    log.info("downloading %.1f MB into %s", state.missing_bytes / 1024**2, directory)
    done = 0
    shown = time.monotonic()

    def progress(count: int) -> None:  # in the download's thread
        nonlocal done, shown
        done += count
        if time.monotonic() - shown >= 2.0:
            shown = time.monotonic()
            log.info("%.1f of %.1f MB", done / 1024**2, state.missing_bytes / 1024**2)

    requested = asyncio.Event()
    stop = threading.Event()

    async def relay() -> None:
        await requested.wait()
        stop.set()

    relaying = asyncio.create_task(relay())
    try:
        with stop_on_signals(requested, "aborted: run `mailrobbe ai model --download` again"):
            await asyncio.to_thread(
                parakeet.download_model, directory, progress=progress, stop=stop
            )
    except (parakeet.ModelMissing, OSError) as error:
        log.error("cannot download the model into %s: %s", directory, describe(error))
        return EXIT_FAILED
    finally:
        relaying.cancel()
    if stop.is_set():
        log.info("stopped: run `mailrobbe ai model --download` again to continue")
        return EXIT_INTERRUPTED
    return 0


async def status(settings: Settings) -> dict[str, Any]:
    """What `mailrobbe ai status` prints."""
    engine = create_engine(settings.database_url)
    try:
        async with create_sessionmaker(engine)() as session:
            counts = await task_counts(session)
            job = await latest_job(session, JobKind.AI)
    finally:
        await engine.dispose()
    latest = None
    if job is not None:
        latest = {
            "id": job.id,
            "status": job.status,
            "origin": job.origin,
            "phase": job.phase,
            "message": job.message,
            "started_at": job.started_at.isoformat(),
            "finished_at": None if job.finished_at is None else job.finished_at.isoformat(),
            "progress": job.progress,
        }
    return {
        "tasks": {
            kind.value: {state.value: count for state, count in states.items()}
            for kind, states in counts.items()
        },
        "latest_run": latest,
        "transcriber": await asyncio.to_thread(transcriber, settings),
    }

"""`mailrobbe ai`: text of scanned PDFs and images from Tesseract or a vision model (D180 to D189).

    run     work through the queue (ai.run): a run of kind ai with the steps check, ocr,
            entities and signals; stoppable at any page, the next run continues there
    check   ask each configured service for real (a picture with a known word for vision) and
            print what it found as JSON
    queue   put a selection on the queue: the work lists "scanned" and "images" of the AI page,
            or documents by id (D186)
    status  print the tasks per kind and status and the latest run as JSON

The dashboard starts `mailrobbe ai --origin ui run [options]` as a child process (D46) and stops
it with a stop request. Exit status of run as in ai.run: 0 done, 130 stopped by request, 1 when
it could not start or ended early for a reason it names, 2 for arguments it cannot use; check
exits with 1 when a configured service fails.
"""

import argparse
import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any, get_args

from sqlalchemy.exc import SQLAlchemyError

from mailrobbe.ai.model import AiOptions, OcrEngineChoice, ServiceCheck, configured_services
from mailrobbe.ai.queue import enqueue_ocr, task_counts, work_list_ids
from mailrobbe.ai.run import EXIT_FAILED, Engines, default_engines, run_ai
from mailrobbe.config import Settings, get_settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.dkim.cli import error_line
from mailrobbe.enums import JobKind, JobOrigin
from mailrobbe.jobrun import RunRefused
from mailrobbe.jobs import latest_job

log = logging.getLogger(__name__)

EXIT_USAGE = 2


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
        help="recognise the text of the queued documents",
        description="Work through the queue: render the pages of each queued document, read "
        "them with Tesseract or the vision model and store the text, which becomes searchable "
        "like an extracted one; then scan the new texts for entities and compute the signals. "
        "Ctrl-C stops after the page in work; the next run continues there.",
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
    work.add_argument("--quiet", action="store_true", help="no progress output")
    tasks.add_parser(
        "check",
        help="test the configured AI services and print what they answered as JSON",
        description="Ask each configured service for its models and read a picture with a "
        "known word with the vision model; refused services (outside this machine without "
        "MAILROBBE_AI_ALLOW_REMOTE) are not asked. Exits with 1 when one fails.",
    )
    queue = tasks.add_parser(
        "queue",
        help="queue documents for text recognition",
        description="Queue OCR for the scanned PDFs, the images of the AI page's work list "
        "(100 KB and more, in at most 50 mails), or documents by id. Documents with a text "
        "of their own and documents without a SHA-256 are left out.",
    )
    queue.add_argument("--scanned", action="store_true", help="every scanned PDF not read yet")
    queue.add_argument("--images", action="store_true", help="the work list of images")
    queue.add_argument(
        "--document",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="a document by id; repeatable",
    )
    queue.add_argument(
        "--engine", choices=engines, default="auto", help="the engine of the tasks (default: auto)"
    )
    queue.add_argument(
        "--include-logos",
        action="store_true",
        help="also images carried by more than 50 mails, mostly logos of signatures",
    )
    tasks.add_parser(
        "status",
        help="print the queue and the latest run as JSON",
        description="Print the tasks per kind and status and the latest AI run as JSON.",
    )


def run(args: argparse.Namespace) -> int:
    quiet = getattr(args, "quiet", False)
    logging.basicConfig(level=logging.WARNING if quiet else logging.INFO, format="%(message)s")
    settings = get_settings()
    try:
        if args.task == "check":
            checks = asyncio.run(check(settings))
            print(json.dumps([found.model_dump(mode="json") for found in checks], indent=2))
            return EXIT_FAILED if any(failed(found) for found in checks) else 0
        if args.task == "queue":
            return asyncio.run(_queue(settings, args))
        if args.task == "status":
            print(json.dumps(asyncio.run(status(settings)), indent=2))
            return 0
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
    return found.model_copy(update=update)


async def check(settings: Settings, engines: Engines | None = None) -> list[ServiceCheck]:
    """Each configured service checked for real, in the order of the capabilities."""
    services = configured_services(settings)
    if not services:
        log.info("no AI service is configured (MAILROBBE_AI_VISION_URL)")
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
    if not (args.scanned or args.images or args.document):
        log.error("name what to queue: --scanned, --images or --document ID")
        return EXIT_USAGE
    engine = create_engine(settings.database_url)
    try:
        async with create_sessionmaker(engine).begin() as session:
            ids = list(args.document)
            if args.scanned:
                ids += await work_list_ids(session, "scanned")
            if args.images:
                ids += await work_list_ids(session, "images")
            queued = await enqueue_ocr(
                session, ids, engine=args.engine, include_logos=args.include_logos
            )
    finally:
        await engine.dispose()
    print(json.dumps(asdict(queued), indent=2))
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
    }

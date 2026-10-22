"""A stand-in for `mailrobbe import`, `mailrobbe dkim`, `mailrobbe dkim-keys`, `mailrobbe map` and
`mailrobbe ai` in the dashboard's tests.

    python fake_run.py BEHAVIOUR KIND --origin ORIGIN [--workers N] [--status S...] [--jobs N]
    python fake_run.py BEHAVIOUR dkim-keys --origin ORIGIN TASK [--name N]... [--domain D]...
        [--skip-domain D]...
    python fake_run.py BEHAVIOUR map --origin ORIGIN download --region R --detail D [--bbox B]
    python fake_run.py BEHAVIOUR ai --origin ORIGIN run --engine E --max-pages N --max-minutes N
        [--vision-model M] [--text-model M] [--document ID]... [--mail ID]...

Tests put (sys.executable, this file, BEHAVIOUR) into api.processes.CLI. Like the real commands,
it takes the advisory lock of its kind, records its run with jobs.begin_job (options from its
arguments and the MAILROBBE_* variables the server passed) and then behaves as told:

    done      ends the run as done at once
    wait      reports every 0.1 s and ends the run as stopped, with the message "stop requested"
              once the dashboard asked for it, or "SIGTERM" when that signal arrives
    stubborn  like wait, but ignores SIGTERM, so only SIGKILL ends it
    silent    records nothing and waits for SIGTERM
    exit      exits with EXIT_STATUS at once
"""

import argparse
import asyncio
import signal
import sys
from collections.abc import Sequence

from pydantic import BaseModel
from sqlalchemy import func, select

from mailrobbe import jobs
from mailrobbe.ai.model import AiOptions
from mailrobbe.config import Settings
from mailrobbe.db.session import create_engine
from mailrobbe.dkim.keys.model import DkimKeysOptions
from mailrobbe.enums import JobKind, JobOrigin, JobStatus
from mailrobbe.places.tiles import map_options, source_setting

EXIT_STATUS = 3
REPORT_SECONDS = 0.1


def _options(kind: JobKind, args: argparse.Namespace, settings: Settings) -> BaseModel:
    if kind is JobKind.IMPORT:
        return jobs.ImportOptions.from_settings(settings, args.workers)
    if kind is JobKind.MAP:
        bbox = None if args.bbox is None else [float(part) for part in args.bbox.split(",")]
        source = source_setting(settings.map_source)
        assert source is not None, "the API starts no map run while the map is off"
        return map_options(args.region, args.detail, bbox, source)
    if kind is JobKind.AI:
        options = AiOptions.from_settings(settings)
        update = {
            "ocr_engine": args.engine,
            "max_pages": args.max_pages,
            "max_minutes": args.max_minutes,
        }
        if args.vision_model is not None:
            update["vision_model"] = args.vision_model
        if args.document:
            update["documents"] = args.document
        if args.text_model is not None:
            update["text_model"] = args.text_model
        if args.mail:
            update["mails"] = args.mail
        return options.model_copy(update=update)
    if kind is JobKind.DKIM_KEYS:
        return DkimKeysOptions(
            task=args.task,
            names=args.name or [],
            domains=args.domain or [],
            skip_domains=args.skip_domain or [],
            workers=args.jobs or settings.import_workers,
        )
    return jobs.DkimOptions(
        statuses=args.status,
        workers=args.jobs or settings.import_workers,
        offline=settings.dkim_offline,
    )


async def main(argv: Sequence[str]) -> int:
    behaviour, kind_name, *rest = argv
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--status", nargs="+")
    parser.add_argument("task", nargs="?")  # dkim-keys, map, ai
    parser.add_argument("--name", action="append")
    parser.add_argument("--domain", action="append")
    parser.add_argument("--skip-domain", action="append")
    parser.add_argument("--region")  # map
    parser.add_argument("--detail")
    parser.add_argument("--bbox")
    parser.add_argument("--engine")  # ai
    parser.add_argument("--vision-model")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--max-minutes", type=int)
    parser.add_argument("--document", type=int, action="append")
    parser.add_argument("--text-model")
    parser.add_argument("--mail", type=int, action="append")
    args = parser.parse_args(rest)
    kind = JobKind(kind_name.replace("-", "_"))
    if behaviour == "exit":
        return EXIT_STATUS
    terminated = asyncio.Event()
    if behaviour == "stubborn":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    else:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, terminated.set)
    if behaviour == "silent":
        await terminated.wait()
        return 0

    settings = Settings()
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            locked = await connection.scalar(
                select(func.pg_try_advisory_lock(jobs.LOCK_KEYS[kind]))
            )
            assert locked, "another run holds the lock"
            options = _options(kind, args, settings)
            job_id = await jobs.begin_job(connection, kind, JobOrigin(args.origin), options)
            await connection.commit()
            if behaviour == "done":
                await jobs.end_job(connection, job_id, JobStatus.DONE, message="nothing to do")
                await connection.commit()
                return 0
            message = None
            while message is None:
                if await jobs.report_job(connection, job_id):
                    message = "stop requested"
                await connection.commit()
                try:
                    await asyncio.wait_for(terminated.wait(), REPORT_SECONDS)
                    message = "SIGTERM"
                except TimeoutError:
                    pass
            await jobs.end_job(connection, job_id, JobStatus.STOPPED, message=message)
            await connection.commit()
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))

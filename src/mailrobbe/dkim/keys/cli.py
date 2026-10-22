"""`mailrobbe dkim-keys`: keys of deleted selectors (D100 to D104, docs/DKIM-RECOVERY.md).

    reconstruct  rebuild RSA keys from two or more signatures of each concerned key name
    search       key records quoted in the archive's mail and attachment texts
    fetch        ask the ZK Email DKIM archive, one request per domain
    check        check the mails of key names again with every candidate key
    add          store a key a person found elsewhere, with a reference, then check its name
    status       the figures of the dashboard card, as JSON

The tasks record themselves in `job` (kind dkim_keys) and hold the DKIM lock, so they exclude
`mailrobbe dkim` and each other. Exit status as for `mailrobbe dkim`: 0 when done, 130 when
stopped by Ctrl-C, SIGTERM or the dashboard (the printed summary covers what was done), 1 when
it could not start or failed, 2 for an argument the command cannot use (a missing file, a key
it cannot read).
"""

import argparse
import asyncio
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from mailrobbe.api.schemas import EVIDENCE_FILE_LIMIT
from mailrobbe.config import Settings, get_settings
from mailrobbe.db.session import create_engine
from mailrobbe.dkim.cli import error_line, positive_int
from mailrobbe.dkim.keys.model import DkimKeysOptions, DkimKeysTask
from mailrobbe.dkim.keys.run import run_keys
from mailrobbe.dkim.keys.store import KeyRejected, add_manual_key, selector_summary
from mailrobbe.enums import JobOrigin
from mailrobbe.jobrun import EXIT_INTERRUPTED, RunRefused

EXIT_USAGE = 2

_TASKS: dict[DkimKeysTask, str] = {
    "reconstruct": "rebuild RSA keys from two or more signatures of each concerned key name",
    "search": "find key records quoted in the archive's mail and attachment texts",
    "fetch": "ask the ZK Email DKIM archive (MAILROBBE_DKIM_KEY_ARCHIVE_URL), once per domain",
    "check": "check the mails of key names again with every candidate key",
}


def _moment(value: str) -> datetime:
    """An ISO date or time; without a zone, UTC."""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not an ISO date or time: {value!r}") from error
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


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
    for task, description in _TASKS.items():
        command = tasks.add_parser(task, help=description, description=description)
        command.add_argument(
            "--name",
            action="append",
            default=[],
            metavar="NAME",
            help="only this key name ('<selector>._domainkey.<domain>'); repeatable"
            + ("" if task != "check" else " (default: every name a stored key may help)"),
        )
        if task == "fetch":
            domains = command.add_mutually_exclusive_group()
            domains.add_argument(
                "--domain",
                action="append",
                default=[],
                metavar="DOMAIN",
                help="ask for this domain; repeatable (default: every concerned domain, and "
                "after a fetch that was stopped only those it did not get an answer for)",
            )
            domains.add_argument(
                "--skip-domain",
                action="append",
                default=[],
                metavar="DOMAIN",
                help="leave this domain out of every concerned domain; repeatable",
            )
        _common(command)
    add = tasks.add_parser(
        "add",
        help="store a key found elsewhere, with a reference, and check its name's mails",
        description="Store a key a person found elsewhere (a zone file, a provider's mail) as "
        "documented, with a reference, then check the mails of its name.",
    )
    add.add_argument("--name", required=True, metavar="NAME", help="the key name")
    record = add.add_mutually_exclusive_group(required=True)
    record.add_argument(
        "--record", metavar="TEXT", help="the TXT record, its quoted strings or only the p= value"
    )
    record.add_argument("--record-file", type=Path, metavar="PATH", help="read the record here")
    add.add_argument("--reference", required=True, metavar="TEXT", help="where the key comes from")
    add.add_argument("--note", metavar="TEXT", help="a note on the key")
    add.add_argument(
        "--evidence-file",
        type=Path,
        metavar="PATH",
        help="the source as a file (stored unchanged as the lookup's answer)",
    )
    add.add_argument("--editor", metavar="NAME", help="who entered the key")
    add.add_argument(
        "--observed-from", type=_moment, metavar="WHEN", help="published since (ISO date)"
    )
    add.add_argument("--observed-to", type=_moment, metavar="WHEN", help="published until")
    _common(add)
    tasks.add_parser(
        "status",
        help="print the figures of the deleted selectors as JSON",
        description="Print the figures of the dashboard card for deleted selectors as JSON.",
    )


def _common(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--jobs",
        "--workers",
        dest="workers",
        type=positive_int,
        metavar="N",
        help="worker processes (default: MAILROBBE_IMPORT_WORKERS)",
    )
    command.add_argument("--quiet", action="store_true", help="no progress output")


def run(args: argparse.Namespace) -> int:
    quiet = getattr(args, "quiet", False)
    logging.basicConfig(level=logging.WARNING if quiet else logging.INFO, format="%(message)s")
    settings = get_settings()
    workers = getattr(args, "workers", None) or settings.import_workers
    try:
        if args.task == "status":
            return asyncio.run(_status(settings))
        if args.task == "add":
            failed = asyncio.run(_add(settings, args))
            if failed is not None:
                return failed
            options = DkimKeysOptions(task="check", names=[args.name], workers=workers)
        else:
            options = DkimKeysOptions(
                task=args.task,
                names=args.name,
                domains=getattr(args, "domain", []),
                skip_domains=getattr(args, "skip_domain", []),
                workers=workers,
            )
        result = asyncio.run(run_keys(settings, options, origin=args.origin))
    except RunRefused as refusal:
        stored = "; the key is stored, check its name later" if args.task == "add" else ""
        logging.error("%s%s", refusal, stored)
        return 1
    except (SQLAlchemyError, OSError) as error:
        logging.error("database error: %s", error_line(error))
        return 1
    print(json.dumps(asdict(result.summary), indent=2))
    return EXIT_INTERRUPTED if result.stopped else 0


async def _status(settings: Settings) -> int:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            summary = await selector_summary(connection)
    finally:
        await engine.dispose()
    print(summary.model_dump_json(indent=2))
    return 0


async def _add(settings: Settings, args: argparse.Namespace) -> int | None:
    """Store the key; None when it is stored, else the exit status."""
    try:
        record = args.record if args.record_file is None else args.record_file.read_text()
        evidence = None
        if args.evidence_file is not None:
            if args.evidence_file.stat().st_size > EVIDENCE_FILE_LIMIT:
                logging.error("the evidence file is larger than %d bytes", EVIDENCE_FILE_LIMIT)
                return EXIT_USAGE
            evidence = args.evidence_file.read_bytes()
    except (OSError, UnicodeDecodeError) as error:
        logging.error("cannot read the file: %s", error)
        return EXIT_USAGE
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            key_id = await add_manual_key(
                connection,
                args.name,
                record,
                reference=args.reference,
                note=args.note,
                observed_from=args.observed_from,
                observed_to=args.observed_to,
                file_name=None if args.evidence_file is None else args.evidence_file.name,
                file_bytes=evidence,
                editor=args.editor,
            )
            await connection.commit()
    except KeyRejected as rejected:
        logging.error("%s", rejected)
        return EXIT_USAGE
    finally:
        await engine.dispose()
    logging.info("stored as key %d; checking the mails of %s", key_id, args.name)
    return None

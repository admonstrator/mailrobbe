"""`mailrobbe dkim`: check or recheck the DKIM signatures of imported mails (SPEC 3.4)."""

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from mailrobbe.config import get_settings
from mailrobbe.dkim.recheck import DEFAULT_STATUSES, UNCHECKED, recheck
from mailrobbe.enums import DkimStatus

_STATUSES: dict[str, DkimStatus | None] = {
    UNCHECKED: None,
    **{status.value: status for status in DkimStatus},
}
_DEFAULT = [name for name, status in _STATUSES.items() if status in DEFAULT_STATUSES]


def _positive(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f"not a positive integer: {value!r}")
    return int(value)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--status",
        action="extend",
        nargs="+",
        choices=list(_STATUSES),
        metavar="STATUS",
        help=f"select mails by DKIM status, several allowed: {', '.join(_STATUSES)} "
        f"(default: {' '.join(_DEFAULT)})",
    )
    selection.add_argument("--all", action="store_true", help="select every mail")
    parser.add_argument(
        "--mail",
        action="append",
        type=_positive,
        metavar="ID",
        help="check this mail whatever its status; repeatable, overrides the status selection",
    )
    parser.add_argument(
        "--jobs",
        type=_positive,
        metavar="N",
        help="worker processes (default: MAILROBBE_IMPORT_WORKERS)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="no DNS lookups: keys missing from the cache give temp_error",
    )
    parser.add_argument(
        "--dns-override", type=Path, metavar="PATH", help="DNS override table for this run"
    )
    parser.add_argument("--quiet", action="store_true", help="no progress output")


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s")
    changes: dict[str, Any] = {}
    if args.offline:
        changes["dkim_offline"] = True
    if args.dns_override is not None:
        changes["dkim_dns_override"] = args.dns_override
    settings = get_settings().model_copy(update=changes)
    override = settings.dkim_dns_override
    if override is not None and not override.is_file():
        logging.error("DNS override table not found: %s", override)
        return 2
    try:
        summary = recheck(
            settings,
            statuses=None if args.all else {_STATUSES[name] for name in args.status or _DEFAULT},
            mail_ids=args.mail or (),
            jobs=args.jobs or settings.import_workers,
        )
    except (SQLAlchemyError, OSError) as error:
        logging.error("database error: %s", _message(error))
        return 1
    print(json.dumps(asdict(summary), indent=2))
    return 0


def _message(error: Exception) -> str:
    """The first line of the error, without SQLAlchemy's wrapping."""
    cause: BaseException = error.orig if isinstance(error, DBAPIError) and error.orig else error
    text = str(cause).strip()
    return text.splitlines()[0] if text else type(cause).__name__

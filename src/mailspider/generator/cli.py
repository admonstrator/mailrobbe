import argparse
import json
import logging
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path

from mailspider.generator.config import GeneratorConfig, parse_size
from mailspider.generator.pipeline import generate

_DEFAULTS = GeneratorConfig(out_dir=Path("data/mbox"), meta_dir=Path("data/mbox/_generator"))


def _share(value: str) -> float:
    share = float(value)
    if not 0.0 <= share <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return share


def _size(value: str) -> int:
    try:
        return parse_size(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def add_arguments(parser: argparse.ArgumentParser) -> None:
    d = _DEFAULTS
    parser.add_argument("--out", type=Path, default=d.out_dir, help="directory for the MBOX files")
    parser.add_argument(
        "--meta-dir",
        type=Path,
        help="directory for manifest, DNS override table, DKIM keys and summary "
        "(default: OUT/_generator)",
    )
    parser.add_argument("--mails", type=int, default=d.mails, help="number of mails")
    parser.add_argument("--persons", type=int, default=d.persons, help="number of persons")
    parser.add_argument("--domains", type=int, default=d.domains, help="number of domains")
    parser.add_argument("--date-from", type=date.fromisoformat, default=d.date_from)
    parser.add_argument("--date-to", type=date.fromisoformat, default=d.date_to)
    parser.add_argument(
        "--attachment-share",
        type=_share,
        default=d.attachment_share,
        help="share of mails with attachments",
    )
    parser.add_argument(
        "--file-size",
        type=_size,
        default=d.file_size,
        help="target size per MBOX file, e.g. 128MB or 4GB",
    )
    parser.add_argument(
        "--dkim-signed-share",
        type=_share,
        default=d.dkim_signed_share,
        help="share of DKIM-signed mails",
    )
    parser.add_argument(
        "--fault-rate",
        type=_share,
        default=d.fault_rate,
        help="share of mails with byte-level defects",
    )
    parser.add_argument(
        "--duplicate-rate", type=_share, default=d.duplicate_rate, help="share of duplicated mails"
    )
    parser.add_argument(
        "--large-attachments",
        type=int,
        default=d.large_attachments,
        help="number of very large attachments",
    )
    parser.add_argument(
        "--large-attachment-size",
        type=_size,
        default=d.large_attachment_size,
        help="size of each, e.g. 55MB",
    )
    parser.add_argument("--seed", type=int, default=d.seed)
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 1,
        help="worker processes (default: CPU count)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace existing generator output"
    )
    parser.add_argument("--quiet", action="store_true", help="no progress output")


def config_from_args(args: argparse.Namespace) -> GeneratorConfig:
    return GeneratorConfig(
        out_dir=args.out,
        meta_dir=args.meta_dir or args.out / "_generator",
        mails=args.mails,
        persons=args.persons,
        domains=args.domains,
        date_from=args.date_from,
        date_to=args.date_to,
        attachment_share=args.attachment_share,
        file_size=args.file_size,
        dkim_signed_share=args.dkim_signed_share,
        fault_rate=args.fault_rate,
        duplicate_rate=args.duplicate_rate,
        large_attachments=args.large_attachments,
        large_attachment_size=args.large_attachment_size,
        seed=args.seed,
        jobs=args.jobs,
        overwrite=args.overwrite,
    )


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s")
    try:
        config = config_from_args(args)
    except ValueError as error:
        logging.error("invalid configuration: %s", error)
        return 2
    summary = generate(config)
    print(json.dumps(asdict(summary), indent=2, default=str))
    return 0

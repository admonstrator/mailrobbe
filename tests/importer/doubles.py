"""Test doubles and builders for the importer tests.

iter_records and parse_record stand in for the real split and parse modules where a test is
about storage, the worker pool or the command rather than about MBOX framing or MIME. They are
module-level functions, so a test can hand them to worker processes through runner.Pipeline
(spawned workers do not see monkeypatching). They are only good enough for well-formed data:
the generator archive and the small MBOX files written here.
"""

import asyncio
import errno
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from email.parser import BytesHeaderParser
from email.policy import compat32
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from mailrobbe.config import Settings
from mailrobbe.enums import DkimStatus
from mailrobbe.importer.cli import run_import as cli_run_import
from mailrobbe.importer.model import Issue, ParsedAddress, ParsedAttachment, ParsedMail
from mailrobbe.importer.runner import Pipeline
from mailrobbe.importer.split import MboxRecord
from mailrobbe.mbox import message_from_record

SEPARATOR = b"From sender@example.test Mon Jan  1 00:00:00 2024"
# Headers that make the doubles fail: iter_records with EIO on reaching the record,
# parse_record with ValueError.
READ_ERROR_HEADER = b"X-Double-Read-Error: yes"
PARSE_ERROR_HEADER = b"X-Double-Parse-Error: yes"

# Builders ----------------------------------------------------------------------------------


def make_record(
    byte_offset: int,
    message: bytes,
    *,
    separator: bytes = SEPARATOR,
    issues: tuple[Issue, ...] = (),
    truncated: bool = False,
) -> MboxRecord:
    """The record of `message` written at byte_offset: separator, message, empty line."""
    return MboxRecord(
        byte_offset=byte_offset,
        byte_length=len(separator) + 1 + len(message) + 1,
        separator=separator,
        message=message,
        raw_sha256=hashlib.sha256(message).hexdigest(),
        truncated=truncated,
        issues=issues,
    )


def make_mail(**changes: Any) -> ParsedMail:
    """A ParsedMail with empty defaults; keyword arguments set fields."""
    values: dict[str, Any] = {
        "message_id": None,
        "in_reply_to": None,
        "reference_ids": (),
        "subject": None,
        "date_utc": None,
        "sender": (),
        "to": (),
        "cc": (),
        "bcc": (),
        "body_text": None,
        "attachments": (),
        "issues": (),
    }
    values.update(changes)
    return ParsedMail(**values)


def address(email: str, name: str | None = None) -> ParsedAddress:
    return ParsedAddress(email, name)


def attachment(
    name: str | None = "a.pdf", size: int = 3, sha256: str | None = "ab"
) -> ParsedAttachment:
    return ParsedAttachment(name, "application/pdf", size, sha256)


def message(
    index: int,
    *,
    sender: str = "anna@a.example",
    to: str = "bert@b.example",
    subject: str | None = None,
    extra_headers: bytes = b"",
) -> bytes:
    """A small well-formed message with Message-ID <index@a.example>."""
    return (
        (
            f"Message-ID: <{index}@a.example>\nFrom: Anna <{sender}>\nTo: {to}\n"
            f"Subject: {subject or f'Mail {index}'}\nDate: Mon, 01 Jan 2024 10:00:00 +0000\n"
        ).encode()
        + extra_headers
        + f"\nBody of mail {index}.\n".encode()
    )


def write_mbox(path: Path, messages: Iterable[bytes]) -> list[MboxRecord]:
    """Write messages as an mboxrd file (no From quoting needed for these) and their records."""
    records = []
    offset = 0
    with path.open("wb") as handle:
        for raw in messages:
            record = make_record(offset, raw)
            handle.write(SEPARATOR + b"\n" + raw + b"\n")
            records.append(record)
            offset += record.byte_length
    return records


def copy_archive(source: Path, target: Path) -> Path:
    """Copy the MBOX files of a generated archive (not its _generator directory)."""
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("*.mbox")):
        shutil.copyfile(path, target / path.name)
    return target


async def add_mbox_file(session: AsyncSession, path: str = "a.mbox") -> int:
    """An mbox_file row (committed) for tests that write mails without a scan."""
    file_id = await session.scalar(
        text("INSERT INTO mbox_file (path, size_bytes) VALUES (:path, 100000) RETURNING id"),
        {"path": path},
    )
    await session.commit()
    assert file_id is not None
    return int(file_id)


async def fetch(session: AsyncSession, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    """Rows of a query as tuples; commits, because importer code begins its own transactions."""
    rows = [tuple(row) for row in await session.execute(text(sql), params)]
    await session.commit()
    return rows


class FakeVerdict:
    def __init__(self, status: DkimStatus, domain: str = "a.example") -> None:
        self.status = status
        self._domain = domain

    def result_rows(self, mail_id: int, checked_at: datetime) -> list[dict[str, Any]]:
        if self.status is DkimStatus.UNSIGNED:
            return []
        return [
            {
                "mail_id": mail_id,
                "signature_index": 0,
                "status": self.status.value,
                "domain": self._domain,
                "selector": "s1",
                "checked_at": checked_at,
            }
        ]


# Pipeline doubles (picklable, used in worker processes) -------------------------------------

_HEADER_LINE = re.compile(rb"[!-9;-~]+:")


def _record_starts(data: bytes) -> Iterator[int]:
    if data.startswith(b"From "):
        yield 0
    position = data.find(b"\n\nFrom ")
    while position >= 0:
        start = position + 2
        line_end = data.find(b"\n", start)
        if line_end >= 0 and _HEADER_LINE.match(data, line_end + 1):
            yield start
        position = data.find(b"\n\nFrom ", start)


def iter_records(
    handle: BinaryIO, start: int = 0, *, max_size: int, block_size: int = 0
) -> Iterator[MboxRecord]:
    """A From_ line after an empty line and before a header line starts a record.

    Reads the rest of the file at once (test data is small). Raises OSError(EIO) on reaching a
    record that contains READ_ERROR_HEADER, as if the disk failed there.
    """
    handle.seek(start)
    data = handle.read()
    starts = list(_record_starts(data))
    for begin, end in zip(starts, [*starts[1:], len(data)], strict=True):
        chunk = data[begin:end]
        if READ_ERROR_HEADER in chunk:
            raise OSError(errno.EIO, "Input/output error")
        raw = message_from_record(chunk)
        yield MboxRecord(
            byte_offset=start + begin,
            byte_length=end - begin,
            separator=chunk[: chunk.index(b"\n")],
            message=raw,
            raw_sha256=hashlib.sha256(raw).hexdigest(),
        )


def parse_record(record: MboxRecord, *, attachment_hash_limit: int) -> ParsedMail:
    """Headers only: Message-ID, In-Reply-To, References, Subject, Date and addresses."""
    if PARSE_ERROR_HEADER in record.message:
        raise ValueError("double parser failure")
    head = record.message[: record.message.find(b"\n\n") + 1] or record.message
    headers = BytesHeaderParser(policy=compat32).parsebytes(head)

    def value(name: str) -> str | None:
        raw = headers.get(name)
        return None if raw is None else _text(str(raw))

    def addresses(name: str) -> tuple[ParsedAddress, ...]:
        values = [_text(str(raw)) for raw in headers.get_all(name, [])]
        return tuple(
            ParsedAddress(email.lower(), name or None)
            for name, email in getaddresses(values)
            if email.count("@") == 1 and not email.startswith("@") and not email.endswith("@")
        )

    ids = re.findall(r"<[^<>\s]+>", value("references") or "")
    in_reply_to = re.findall(r"<[^<>\s]+>", value("in-reply-to") or "")
    message_id = (value("message-id") or "").strip()
    return ParsedMail(
        message_id=message_id if re.fullmatch(r"<[^<>\s]+>", message_id) else None,
        in_reply_to=in_reply_to[0] if in_reply_to else None,
        reference_ids=tuple(dict.fromkeys(ids)),
        subject=value("subject"),
        date_utc=_date(value("date")),
        sender=addresses("from"),
        to=addresses("to"),
        cc=addresses("cc"),
        bcc=addresses("bcc"),
        body_text=None,
        attachments=(),
        issues=(),
    )


def slow_parse_record(record: MboxRecord, *, attachment_hash_limit: int) -> ParsedMail:
    """parse_record taking 20 ms per record, so that a test can interrupt a running import."""
    time.sleep(0.02)
    return parse_record(record, attachment_hash_limit=attachment_hash_limit)


PIPELINE = Pipeline(iter_records, parse_record)
SLOW_PIPELINE = Pipeline(iter_records, slow_parse_record)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def start_import(database_url: str, mbox_dir: Path, speed: str) -> subprocess.Popen[str]:
    """run_import in a new process (group) with 2 workers; stdout and stderr in .stdout."""
    code = (
        "import sys; from tests.importer.doubles import run_import; "
        "sys.exit(run_import(sys.argv[1:]))"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code, database_url, str(mbox_dir), "2", speed],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


async def wait_until(
    engine: AsyncEngine, sql: str, process: "subprocess.Popen[str] | None" = None
) -> None:
    """Until the query returns true; fails when `process` ended first or after 30 seconds."""
    deadline = time.monotonic() + 30
    while True:
        async with engine.connect() as connection:
            if await connection.scalar(text(sql)):
                return
        if process is not None and process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"the import ended with {process.returncode}:\n{output}")
        assert time.monotonic() < deadline, f"timed out waiting for: {sql}"
        await asyncio.sleep(0.05)


def run_import(argv: list[str]) -> int:
    """`mailrobbe import` with the doubles, for tests that signal or kill a separate process.

    argv: database URL, MBOX directory, workers, and "slow" or "fast".
    """
    url, directory, workers, speed = argv
    pipeline = SLOW_PIPELINE if speed == "slow" else PIPELINE
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings(database_url=url)
    return asyncio.run(cli_run_import(settings, Path(directory), int(workers), pipeline=pipeline))


def _text(value: str) -> str:
    """Header text without surrogates or NUL, which PostgreSQL text cannot hold."""
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace").replace("\0", "")


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None

"""Test doubles and builders for the importer tests."""

import hashlib
import shutil
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.enums import DkimStatus
from mailrobbe.importer.model import Issue, ParsedAddress, ParsedAttachment, ParsedMail
from mailrobbe.importer.split import MboxRecord

SEPARATOR = b"From sender@example.test Mon Jan  1 00:00:00 2024"

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

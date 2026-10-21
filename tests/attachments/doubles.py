"""Doubles for the attachments phase: mails with real attachments, and a text extraction that the
spawned workers can import (they do not see monkeypatching).

fake_extract stands in for extract.extract_document. The first bytes of a content choose what
it does (the markers below); any other content goes to the real extract_document. Environment
variables, which spawned workers inherit, let a test watch it:

    MAILROBBE_TEST_CALLS  a file it appends the SHA-256 of every content it is given to
    MAILROBBE_TEST_PIDS   a file it appends "worker <pid>" and "child <pid>" to
    MAILROBBE_TEST_FAST   set: SLOW and HANG give their text at once
"""

import asyncio
import hashlib
import logging
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import format_datetime
from pathlib import Path

from mailrobbe.attachments.extract import Extraction, ExtractionLimits, extract_document
from mailrobbe.config import Settings
from mailrobbe.enums import DocumentKind, DocumentTextStatus
from mailrobbe.importer.cli import run_import

S = DocumentTextStatus

FAIL = b"FAIL"  # failed, "damaged file"
SCAN = b"SCAN"  # scanned, 2 pages, a PDF
TIME = b"TIME"  # timeout with the text read until then
HUGE = b"HUGE"  # text whose tsvector is above PostgreSQL's limit (HUGE_LENGTH characters)
SLOW = b"SLOW"  # text after SLOW_SECONDS
HANG = b"HANG"  # starts a child process, as the sandbox does, and waits for good
DIE = b"DIE!"  # kills its worker process
SLOW_SECONDS = 0.3
HUGE_LENGTH = 400_000
CALLS_ENV = "MAILROBBE_TEST_CALLS"
PIDS_ENV = "MAILROBBE_TEST_PIDS"
FAST_ENV = "MAILROBBE_TEST_FAST"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

Attached = tuple[str | None, str, bytes]  # file name (None: sent without one), MIME type, content
FIRST_DAY = datetime(2024, 1, 1, 10, tzinfo=UTC)  # the date of mail 0; mail n is n days later


def attachment_mail(
    index: int,
    files: Sequence[Attached],
    subject: str | None = None,
    *,
    sender: str = "Anna <anna@a.example>",
    to: Sequence[str] = ("Bert <bert@b.example>",),
    body: str | None = None,
    dated: bool = True,
) -> bytes:
    """A mail with these attachments, base64-encoded; by default from anna@a.example to
    bert@b.example, dated FIRST_DAY plus index days."""
    message = MIMEMultipart()
    message["Message-ID"] = f"<{index}@a.example>"
    message["From"] = sender
    message["To"] = ", ".join(to)
    message["Subject"] = subject or f"Mail {index}"
    if dated:
        message["Date"] = format_datetime(FIRST_DAY + timedelta(days=index))
    message.attach(MIMEText(body or f"Body of mail {index}.\n", "plain", "utf-8"))
    for name, mime_type, data in files:
        major, minor = mime_type.split("/")
        part = MIMEBase(major, minor)
        part.set_payload(data)
        encoders.encode_base64(part)
        if name is None:
            part.add_header("Content-Disposition", "attachment")
        else:
            part.add_header("Content-Disposition", "attachment", filename=name)
        message.attach(part)
    return message.as_bytes()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def huge_text() -> str:
    """HUGE_LENGTH characters of distinct two-character words in three-byte characters: their
    tsvector needs about 1.3 MB, half of them about 0.9 MB."""
    words = (chr(0x4E00 + i // 400) + chr(0x4E00 + i % 400) for i in range(HUGE_LENGTH // 3 + 1))
    return " ".join(words)[:HUGE_LENGTH]


def _note(variable: str, line: str) -> None:
    path = os.environ.get(variable)
    if path:
        with open(path, "a", encoding="utf-8") as handle:  # one short write: atomic
            handle.write(line + "\n")


def fake_extract(
    data: bytes, filename: str | None, mime_type: str, limits: ExtractionLimits
) -> Extraction:
    _note(CALLS_ENV, digest(data))
    _note(PIDS_ENV, f"worker {os.getpid()}")
    marker = data[:4]
    fast = bool(os.environ.get(FAST_ENV))
    if marker == FAIL:
        return Extraction(S.FAILED, error="damaged file")
    if marker == SCAN:
        return Extraction(S.SCANNED, pages=2, kind=DocumentKind.PDF)
    if marker == TIME:
        return Extraction(S.TIMEOUT, "Seite eins", truncated=True, error="stopped after 60 s")
    if marker == HUGE:
        return Extraction(S.TEXT, huge_text())
    if marker == DIE:
        os._exit(1)
    if marker == SLOW and not fast:
        time.sleep(SLOW_SECONDS)
    if marker == HANG and not fast:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        _note(PIDS_ENV, f"child {child.pid}")
        time.sleep(300)
    if marker in (SLOW, HANG):
        return Extraction(S.TEXT, data.decode())
    return extract_document(data, filename, mime_type, limits)


def recorded(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def alive(pid: int) -> bool:
    """The process exists and is no zombie (Linux)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    except (FileNotFoundError, IndexError):
        return False
    return state != "Z"


def start_import(database_url: str, mbox_dir: Path, workers: int) -> subprocess.Popen[str]:
    """run_main in a new process (group); stdout and stderr in .stdout."""
    code = (
        "import sys; from tests.attachments.doubles import run_main; "
        "sys.exit(run_main(sys.argv[1:]))"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code, database_url, str(mbox_dir), str(workers)],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def run_main(argv: list[str]) -> int:
    """`mailrobbe import` with fake_extract; argv: database URL, MBOX directory, workers."""
    url, directory, workers = argv
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings(database_url=url)
    return asyncio.run(run_import(settings, Path(directory), int(workers), extract=fake_extract))

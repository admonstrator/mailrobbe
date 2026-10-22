"""Protected documents and their passwords (D233 to D237, D209): the one place that tries a
password and decrypts, and the process of its own both run in.

What runs in the child, bytes in (pure, blocking, reading untrusted bytes):

    trial_format   "pdf", "ooxml" or "archive" (ZIP, 7z): which attempt opens a document, or
                   None when no password can be tried on it (ODF is detected, not opened, D239)
    opens          whether a password opens the document
    try_values     the first of several passwords that opens it, and how many were tried, in
                   order, up to a deadline (D235)
    decrypted      the plain bytes of a protected PDF (pypdf) or OOXML file (msoffcrypto); the
                   bytes as they are for anything else (a ZIP or 7z keeps its own bytes, its
                   members are read with the password, packed.read_member). Encrypted for a
                   wrong password, Damaged for a file it cannot read

The importer and the server both run threads, so neither may fork (extract.sandbox): like the
preview conversion (preview.convert) the parent side starts a fresh interpreter, `python -I -B
-m mailrobbe.attachments.protected`, with only PATH and the locale in its environment and the
document on stdin. The child limits itself first (preview.convert.confine; the files it may write
only as large as the document, since 7-Zip reads an archive from a temporary file), then:

    try_passwords  tries the passwords and, when one opens a PDF or OOXML file, extracts its
                   text with it (extract_document, D236): the passwords step and the API's typed-in
                   passwords (D237) alike
    decrypt        the decrypted bytes, for the download and the preview of an opened document
                   (D209); they are never stored
"""

import asyncio
import contextlib
import io
import json
import os
import signal
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from mailrobbe.attachments import packed
from mailrobbe.attachments.extract import Extraction, ExtractionLimits, extract_document
from mailrobbe.attachments.extract.base import Damaged, Encrypted, one_line, reason
from mailrobbe.attachments.extract.ooxml import decrypt_ooxml, is_encrypted_ole
from mailrobbe.attachments.kinds import HEAD_SIZE, classify
from mailrobbe.enums import DocumentKind, DocumentTextStatus

_OOXML = frozenset({"docx", "xlsx", "pptx"})
_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
_GRACE = 10.0  # seconds the parent waits beyond the child's own limits
_MEMORY_EXIT = 71


# Child side: the operations ---------------------------------------------------------------------


def trial_format(filename: str | None, mime_type: str, head: bytes) -> str | None:
    """ "pdf", "ooxml", "archive" or None: which attempt opens this document, if any."""
    name = classify(filename, mime_type, head[:HEAD_SIZE]).name
    if name == "pdf":
        return "pdf"
    if name in _OOXML:
        return "ooxml"
    if name in packed.CONTAINER_FORMATS and name != "eml":
        return "archive"
    return None


def opens(data: bytes, filename: str | None, mime_type: str, password: str) -> bool:
    """Whether the password opens the document."""
    kind = trial_format(filename, mime_type, data)
    try:
        if kind == "pdf":
            return _pdf_reader(data, password) is not None
        if kind == "ooxml":
            return is_encrypted_ole(data) and bool(decrypt_ooxml(data, password))
        if kind == "archive":
            return packed.opens_archive(data, filename, mime_type, password)
    except Exception:  # Encrypted for a wrong password, anything else for a broken file
        return False
    return False


def try_values(
    data: bytes,
    filename: str | None,
    mime_type: str,
    values: Sequence[str],
    *,
    deadline: float | None = None,
) -> tuple[int | None, int]:
    """The index of the first password in `values` that opens the document (or None) and how
    many were tried. Stops at the deadline (a monotonic time)."""
    for index, value in enumerate(values):
        if deadline is not None and time.monotonic() > deadline:
            return None, index
        if opens(data, filename, mime_type, value):
            return index, index + 1
    return None, len(values)


def decrypted(data: bytes, filename: str | None, mime_type: str, password: str) -> bytes:
    """The plain bytes of a protected PDF or OOXML file; see the module docstring."""
    kind = trial_format(filename, mime_type, data)
    if kind == "ooxml" and is_encrypted_ole(data):
        return decrypt_ooxml(data, password)
    if kind != "pdf":
        return data
    from pypdf import PdfWriter

    reader = _pdf_reader(data, password)
    if reader is None:
        raise Encrypted
    if not reader.is_encrypted:
        return data
    out = io.BytesIO()
    PdfWriter(clone_from=reader).write(out)
    return out.getvalue()


def _pdf_reader(data: bytes, password: str) -> Any:
    """A pypdf reader opened with the password (or one not encrypted), or None."""
    from pypdf import PasswordType, PdfReader

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and reader.decrypt(password) == PasswordType.NOT_DECRYPTED:
            return None
    except NotImplementedError:  # a security handler pypdf does not know
        return None
    except Exception as error:
        raise Damaged(reason(error)) from None
    return reader


# Parent side ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tried:
    """What try_passwords found."""

    index: int | None  # of the password that opened the document
    tried: int  # passwords tried before the time budget ended or one opened it
    extraction: Extraction | None = None  # the opened PDF's or OOXML file's text (D236)
    error: str | None = None  # why the child ended without an answer (English, one line)


class DecryptFailed(Exception):
    """The document could not be decrypted (English, one line)."""


async def try_passwords(
    data: bytes,
    filename: str | None,
    mime_type: str,
    values: Sequence[str],
    *,
    seconds: float,
    limits: ExtractionLimits,
) -> Tried:
    """Try the passwords in a child process; see the module docstring. Never raises for a bad
    document: a child that failed counts every password as tried, with the reason."""
    header = {
        "op": "try",
        "filename": filename,
        "mime_type": mime_type,
        "values": list(values),
        "seconds": seconds,
        "limits": [limits.max_chars, limits.timeout, limits.memory],
    }
    budget = seconds + limits.timeout
    code, output, problem = await _run(header, data, budget, limits.memory)
    if problem is not None or code != 0:
        return Tried(None, len(values), error=problem or f"child ended with {code}")
    answer = json.loads(output)
    found = answer["extraction"]
    extraction = None
    if found is not None:
        extraction = Extraction(
            DocumentTextStatus(found["status"]),
            found["text"],
            found["truncated"],
            found["pages"],
            found["error"],
            None if found["kind"] is None else DocumentKind(found["kind"]),
        )
    return Tried(answer["index"], answer["tried"], extraction)


async def decrypt(
    data: bytes,
    filename: str | None,
    mime_type: str,
    password: str,
    *,
    timeout: float,
    memory: int,
) -> bytes:
    """The decrypted bytes of an opened document, made in a child process (D209)."""
    header = {"op": "decrypt", "filename": filename, "mime_type": mime_type, "password": password}
    code, output, problem = await _run(header, data, timeout, memory)
    if problem is not None:
        raise DecryptFailed(problem)
    status, _, payload = output.partition(b"\n")
    if code == 0 and status == b"ok":
        return payload
    if code == 0 and status == b"failed":
        raise DecryptFailed(payload.decode("utf-8", "replace"))
    if code == _MEMORY_EXIT:
        raise DecryptFailed(f"memory limit of {memory // 1024**2} MiB exceeded")
    raise DecryptFailed(f"decryption process ended with {code}")


async def _run(
    header: dict[str, Any], data: bytes, timeout: float, memory: int
) -> tuple[int, bytes, str | None]:
    """Run the child with the header line and the document on stdin: its exit code, its output,
    and why it gave no answer (the time limit), or None."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-B",
        "-m",
        "mailrobbe.attachments.protected",
        f"{timeout:g}",
        str(memory),
        str(len(data)),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={key: os.environ[key] for key in _ENVIRONMENT if key in os.environ},
        close_fds=True,
    )
    payload = json.dumps(header).encode() + b"\n" + data
    try:
        output, _ = await asyncio.wait_for(process.communicate(payload), timeout + _GRACE)
    except TimeoutError:
        return -signal.SIGKILL, b"", f"stopped after the time limit of {timeout:g} s"
    finally:
        if process.returncode is None:  # the time limit, or the request was cancelled
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    return await process.wait(), output, None


# Child side: the process ------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    """The child: TIMEOUT MEMORY SIZE as arguments, a JSON header line and the document on
    stdin, the answer on stdout."""
    from mailrobbe.preview.convert import confine

    timeout, memory, size = float(argv[0]), int(argv[1]), int(argv[2])
    confine(timeout, memory, file_size=size + 1024**2)
    header = json.loads(sys.stdin.buffer.readline())
    data = sys.stdin.buffer.read()
    try:
        if header["op"] == "decrypt":
            result = _decrypt_answer(header, data)
        else:
            result = json.dumps(_try_answer(header, data)).encode()
    except MemoryError:
        return _MEMORY_EXIT
    sys.stdout.buffer.write(result)
    sys.stdout.buffer.flush()
    return 0


def _try_answer(header: dict[str, Any], data: bytes) -> dict[str, Any]:
    filename, mime_type, values = header["filename"], header["mime_type"], header["values"]
    deadline = time.monotonic() + header["seconds"]
    index, tried = try_values(data, filename, mime_type, values, deadline=deadline)
    found = None
    if index is not None and trial_format(filename, mime_type, data) != "archive":
        max_chars, timeout, memory = header["limits"]
        extraction = extract_document(
            data, filename, mime_type, ExtractionLimits(max_chars, timeout, memory), values[index]
        )
        found = {
            "status": extraction.status.value,
            "text": extraction.text,
            "truncated": extraction.truncated,
            "pages": extraction.pages,
            "error": extraction.error,
            "kind": None if extraction.kind is None else extraction.kind.value,
        }
    return {"index": index, "tried": tried, "extraction": found}


def _decrypt_answer(header: dict[str, Any], data: bytes) -> bytes:
    try:
        plain = decrypted(data, header["filename"], header["mime_type"], header["password"])
    except Encrypted:
        return b"failed\nthe password does not open the document"
    except Damaged as error:
        return f"failed\ndamaged document: {one_line(str(error)) or 'unreadable'}".encode()
    except Exception as error:
        return f"failed\ndamaged document: {reason(error)}".encode()
    return b"ok\n" + plain


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

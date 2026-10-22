"""Containers and their members (D231, D232): what is inside a ZIP, a 7z or an attached mail.

A container document is unpacked once by the archives step (attachments.phase); its entries
become member documents of their own. This module does the unpacking, bytes in, a listing out:

    list_members   every entry with its path, unpacked size, status (a readable document, or
                   locked, too large, too many, damaged) and, for a readable one, its SHA-256,
                   so the member documents can be deduplicated like any attachment (D231). It
                   never returns the entries' bytes; the text extraction reads each member back
                   with read_member, as content.read_attachment reads an attachment (D232).
    read_member    the bytes of one entry, by its path, with an optional password.

ZIP and 7z (by their first bytes; RAR, tar and gzip stay unopened, D239) go through the 7-Zip
command (ZIP with AES and 7z need it), an attached mail through the e-mail parser the importer
uses, in the worker processes of the archives step (attachments.containers). Bounded against
archive bombs: at most `max_members` entries and `max_size` bytes unpacked per container (the
rest is listed as too_many or too_large), never more read from 7-Zip than the bytes left, whatever
an entry's header says, a time limit per 7-Zip call, and only one level deep, so a container
inside a container is a member document, not unpacked again.

CONTAINER_FORMATS names the formats this unpacks (attachments.kinds); classify decides them.
"""

import hashlib
import logging
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesParser
from email.policy import compat32

from mailrobbe.attachments.kinds import HEAD_SIZE, classify
from mailrobbe.enums import DocumentMembersStatus, DocumentMemberStatus
from mailrobbe.importer.parse import attachment_payload, mime_parts

log = logging.getLogger(__name__)

# Container formats (attachments.kinds): ZIP and 7z archives, and attached mails.
CONTAINER_FORMATS = frozenset({"zip", "archive", "eml"})
_SEVEN_ZIP_FORMATS = frozenset({"zip", "archive"})  # unpacked with the 7-Zip command ...
# ... when the first bytes are a ZIP or a 7z: RAR, tar, gzip and the rest stay unopened (D239)
_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"7z\xbc\xaf\x27\x1c")

MS = DocumentMembersStatus
ES = DocumentMemberStatus
_PARSER = BytesParser(policy=compat32)
_SEVENZIP = shutil.which("7z") or shutil.which("7za") or shutil.which("7zz")
SEVEN_ZIP = _SEVENZIP is not None  # without the command, ZIP and 7z containers wait unopened
LISTED = 10_000  # entries listed per container at most; past max_members they are too_many
_LIST_TIMEOUT = 30.0  # seconds for one `7z l`
_READ_TIMEOUT = 60.0  # seconds for one entry extraction


@dataclass(frozen=True, slots=True)
class Member:
    """One entry of a container, as list_members found it."""

    path: str
    size_bytes: int | None  # unpacked, as declared or read
    status: DocumentMemberStatus
    sha256: str | None = None  # of a readable entry (status document)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Members:
    """What unpacking one container gave."""

    status: DocumentMembersStatus
    members: list[Member]
    error: str | None = None


def is_container(filename: str | None, mime_type: str, head: bytes) -> bool:
    """Whether the content is a container this module unpacks."""
    return classify(filename, mime_type, head[:HEAD_SIZE]).name in CONTAINER_FORMATS


def list_members(
    data: bytes,
    filename: str | None,
    mime_type: str,
    *,
    max_members: int,
    max_size: int,
    password: str | None = None,
) -> Members:
    """Unpack the container and describe its entries; see the module docstring. Never raises. A
    password unpacks a container opened before (D236)."""
    fmt = classify(filename, mime_type, data[:HEAD_SIZE])
    try:
        if fmt.name == "eml":
            return _list_mail(data, max_members=max_members, max_size=max_size)
        if _is_seven_zip(fmt.name, data):
            if _SEVENZIP is None:
                return Members(MS.UNSUPPORTED, [], "the 7-Zip command is not installed")
            return _list_seven_zip(
                data, max_members=max_members, max_size=max_size, password=password
            )
    except _Damaged as error:
        return Members(MS.FAILED, [], str(error))
    except Exception as error:  # a container must never raise: a bug, reported as failed
        return Members(MS.FAILED, [], f"unpacking failed: {_reason(error)}")
    return Members(MS.UNSUPPORTED, [], f"not unpacked ({fmt.name})")


def read_member(
    data: bytes,
    filename: str | None,
    mime_type: str,
    path: str,
    password: str | None = None,
    limit: int | None = None,
) -> bytes | None:
    """The bytes of the entry at `path`, or None when it is not there, needs another password or
    unpacks to more than `limit` bytes (the size it had when it was listed)."""
    fmt = classify(filename, mime_type, data[:HEAD_SIZE])
    if fmt.name == "eml":
        return _read_mail_part(data, path)
    if _is_seven_zip(fmt.name, data) and _SEVENZIP is not None:
        return _read_seven_zip(data, path, password, limit)
    return None


def opens_archive(data: bytes, filename: str | None, mime_type: str, password: str) -> bool:
    """Whether the password opens a protected ZIP or 7z: it reads a locked entry (D235)."""
    fmt = classify(filename, mime_type, data[:HEAD_SIZE])
    if not _is_seven_zip(fmt.name, data) or _SEVENZIP is None:
        return False
    with _as_file(data) as archive:
        entries, header_locked = _seven_zip_entries(archive)
        if header_locked:  # even the names need the password: test the archive as a whole
            return _seven_zip_test(archive, password)
        locked = next((e for e in entries if e.encrypted), None)
        if locked is None:
            return False
        return _seven_zip_test(archive, password, locked.path)


def _is_seven_zip(name: str, data: bytes) -> bool:
    return name in _SEVEN_ZIP_FORMATS and data.startswith(_MAGIC)


def _seven_zip_test(archive: str, password: str, path: str | None = None) -> bool:
    """Whether 7-Zip tests the archive (or one entry of it) good with the password: the data
    decrypts and its checksum matches."""
    assert _SEVENZIP is not None
    result = subprocess.run(
        [_SEVENZIP, "t", "-spd", f"-p{password}", "--", archive, *([path] if path else [])],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=_READ_TIMEOUT,
    )
    return result.returncode == 0


# Attached mails --------------------------------------------------------------------------------


def _mail_parts(data: bytes) -> list[tuple[Message, str]]:
    """The attachments of an attached mail, each with the path it is given (its file name, or
    "part-<n>" when it has none), paths made unique by a suffix."""
    message = _PARSER.parsebytes(data)
    found = mime_parts(message, []).attachments
    seen: dict[str, int] = {}
    parts: list[tuple[Message, str]] = []
    for index, (part, name) in enumerate(found):
        base = (name or f"part-{index + 1}").replace("\x00", "").strip() or f"part-{index + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        parts.append((part, base if count == 0 else f"{base} ({count + 1})"))
    return parts


def _list_mail(data: bytes, *, max_members: int, max_size: int) -> Members:
    members: list[Member] = []
    total = 0
    parts = _mail_parts(data)
    for index, (part, path) in enumerate(parts[:LISTED]):
        if index >= max_members:
            members.append(Member(path, None, ES.TOO_MANY))
            continue
        payload = attachment_payload(part, "member", [])
        size = len(payload)
        if total + size > max_size:
            members.append(Member(path, size, ES.TOO_LARGE))
            continue
        total += size
        members.append(Member(path, size, ES.DOCUMENT, hashlib.sha256(payload).hexdigest()))
    return Members(MS.DONE, members, _unlisted(len(parts)))


def _read_mail_part(data: bytes, path: str) -> bytes | None:
    for part, part_path in _mail_parts(data):
        if part_path == path:
            return attachment_payload(part, "member", [])
    return None


# ZIP and 7z ------------------------------------------------------------------------------------


class _Damaged(Exception):
    """The 7-Zip command could not read the archive at all."""


@dataclass(frozen=True, slots=True)
class _Entry:
    path: str
    size: int | None
    encrypted: bool


def _list_seven_zip(
    data: bytes, *, max_members: int, max_size: int, password: str | None = None
) -> Members:
    with _as_file(data) as archive:
        entries, header_locked = _seven_zip_entries(archive, password)
        if header_locked:
            return Members(MS.LOCKED, [], "the archive's entries need a password")
        members: list[Member] = []
        total = 0
        any_locked = False
        for index, entry in enumerate(entries[:LISTED]):
            if index >= max_members:
                members.append(Member(entry.path, entry.size, ES.TOO_MANY))
                continue
            if entry.encrypted and password is None:
                any_locked = True
                members.append(Member(entry.path, entry.size, ES.LOCKED))
                continue
            if entry.size is not None and total + entry.size > max_size:
                members.append(Member(entry.path, entry.size, ES.TOO_LARGE))
                continue
            try:
                payload = _seven_zip_read(archive, entry.path, password, max_size - total)
            except _TooLarge:  # its header said less than it unpacks to
                members.append(Member(entry.path, entry.size, ES.TOO_LARGE))
                continue
            if payload is None:
                members.append(Member(entry.path, entry.size, ES.FAILED, error="not extracted"))
                continue
            total += len(payload)
            members.append(
                Member(entry.path, len(payload), ES.DOCUMENT, hashlib.sha256(payload).hexdigest())
            )
    status = MS.LOCKED if any_locked else MS.DONE
    return Members(status, members, _unlisted(len(entries)))


def _unlisted(count: int) -> str | None:
    if count <= LISTED:
        return None
    return f"{count - LISTED} entries beyond the first {LISTED} not listed"


def _read_seven_zip(
    data: bytes, path: str, password: str | None, limit: int | None
) -> bytes | None:
    with _as_file(data) as archive:
        try:
            return _seven_zip_read(archive, path, password, limit)
        except _TooLarge:
            return None


@contextmanager
def _as_file(data: bytes) -> Iterator[str]:
    with tempfile.NamedTemporaryFile(suffix=".bin") as handle:
        handle.write(data)
        handle.flush()
        yield handle.name


def _seven_zip_entries(path: str, password: str | None = None) -> tuple[list[_Entry], bool]:
    """Every file entry of the archive and whether its headers themselves need a password."""
    assert _SEVENZIP is not None
    switch = f"-p{password}" if password is not None else "-p"
    result = subprocess.run(
        [_SEVENZIP, "l", "-slt", switch, "--", path],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=_LIST_TIMEOUT,
    )
    text = result.stdout.decode("utf-8", "replace")
    if result.returncode != 0 and not _has_blocks(text):
        if _needs_password(text + result.stderr.decode("utf-8", "replace")):
            return [], True
        raise _Damaged(f"7-Zip could not read the archive (exit {result.returncode})")
    return list(_parse_slt(text)), False


def _parse_slt(text: str) -> Iterator[_Entry]:
    """The file entries of `7z l -slt` output; folders and the header block are skipped."""
    for block in text.split("\n\n"):
        fields = _block_fields(block)
        path = fields.get("Path")
        if path is None or ("Attributes" not in fields and "Size" not in fields):
            continue
        if "D" in fields.get("Attributes", "") or fields.get("Folder") == "+":
            continue
        size = _as_int(fields.get("Size"))
        encrypted = fields.get("Encrypted", "").strip() == "+"
        yield _Entry(path, size, encrypted)


def _block_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw in block.splitlines():
        key, sep, value = raw.partition(" = ")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


class _TooLarge(Exception):
    """An entry unpacks to more bytes than allowed."""


def _seven_zip_read(
    archive: str, path: str, password: str | None, limit: int | None = None
) -> bytes | None:
    """The entry's bytes, or None when 7-Zip cannot extract it (a wrong password, damage, the
    time limit). Never more than `limit` bytes are read: _TooLarge, whatever its header says."""
    assert _SEVENZIP is not None
    switch = f"-p{password}" if password is not None else "-p"
    command = [_SEVENZIP, "e", "-so", "-spd", switch, "--", archive, path]
    with subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as process:
        timer = threading.Timer(_READ_TIMEOUT, process.kill)
        timer.start()
        try:
            assert process.stdout is not None
            data = process.stdout.read() if limit is None else process.stdout.read(limit + 1)
            if limit is not None and len(data) > limit:
                process.kill()
                raise _TooLarge
            code = process.wait()
        finally:
            timer.cancel()
    return data if code == 0 else None


def _has_blocks(text: str) -> bool:
    return "Path = " in text


def _needs_password(text: str) -> bool:
    return "password" in text.lower()  # "Enter password", "Wrong password?"


def _as_int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _reason(error: BaseException) -> str:
    message = " ".join(str(error).split())
    name = type(error).__name__
    line = f"{name}: {message}" if message else name
    return line if len(line) <= 300 else line[:297] + "..."

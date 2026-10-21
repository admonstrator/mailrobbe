"""Finding MBOX files and keeping their mbox_file rows in step with the disk (D14).

The scan decides, per file, where the import continues: a file it has seen before with the same
first MiB keeps its progress (it may have grown); a file whose first MiB changed, or that is now
shorter than its progress, is a different file and is imported again from scratch. Rows of files
that disappeared are left as they are, so a temporarily missing mount loses nothing.
"""

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.enums import MboxStatus

MBOX_MAGIC = b"From "
HEAD_SIZE = 1024**2  # sha256_head covers this many bytes
SKIPPED_DIRECTORY = "_generator"  # generator output: manifest, keys, DNS table


@dataclass(frozen=True, slots=True)
class FoundFile:
    path: str  # relative to the MBOX directory, POSIX
    size_bytes: int
    sha256_head: str


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """An MBOX file on disk and its row after the scan."""

    id: int
    path: str
    size_bytes: int
    bytes_done: int
    status: MboxStatus  # done or pending


@dataclass(frozen=True, slots=True)
class ScanReport:
    files: tuple[ScannedFile, ...]  # every MBOX file found, sorted by path
    new: tuple[str, ...]
    replaced: tuple[tuple[str, str], ...]  # (path, reason): imported again from scratch
    missing: tuple[str, ...]  # rows whose file is gone; left untouched
    unreadable: tuple[tuple[str, str], ...]  # (path, reason): skipped, no row

    @property
    def pending(self) -> tuple[ScannedFile, ...]:
        return tuple(file for file in self.files if file.status is MboxStatus.PENDING)


def find_mbox_files(mbox_dir: Path) -> tuple[list[FoundFile], list[tuple[str, str]]]:
    """MBOX files below mbox_dir sorted by path, and the files that could not be examined."""
    found: list[FoundFile] = []
    unreadable: list[tuple[str, str]] = []
    for path in _candidates(mbox_dir):
        relative = path.relative_to(mbox_dir).as_posix()
        try:
            relative.encode("utf-8")
            found_file = _examine(path, relative)
        except UnicodeEncodeError:
            unreadable.append((relative.encode("utf-8", "replace").decode(), "name is not UTF-8"))
        except OSError as error:
            unreadable.append((relative, error.strerror or str(error)))
        else:
            if found_file is not None:
                found.append(found_file)
    return found, unreadable


def _candidates(mbox_dir: Path) -> list[Path]:
    """Regular files below mbox_dir without hidden entries and generator output."""
    paths: list[Path] = []
    for directory, dirnames, filenames in os.walk(mbox_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != SKIPPED_DIRECTORY]
        for name in filenames:
            path = Path(directory, name)
            try:
                regular = stat.S_ISREG(path.lstat().st_mode)  # symbolic links are left out
            except OSError:  # gone since the directory was listed
                continue
            if regular and not name.startswith("."):
                paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(mbox_dir).as_posix())


def _examine(path: Path, relative: str) -> FoundFile | None:
    with path.open("rb") as handle:
        magic = handle.read(len(MBOX_MAGIC))
        if magic != MBOX_MAGIC:
            return None
        head = magic + handle.read(HEAD_SIZE - len(magic))
        size = os.fstat(handle.fileno()).st_size
    return FoundFile(relative, size, hashlib.sha256(head).hexdigest())


def _head_digest(path: Path, length: int) -> str:
    with path.open("rb") as handle:
        return hashlib.sha256(handle.read(length)).hexdigest()


async def scan(
    session: AsyncSession,
    mbox_dir: Path,
    found: tuple[list[FoundFile], list[tuple[str, str]]] | None = None,
) -> ScanReport:
    """Bring mbox_file in line with the MBOX files below mbox_dir, in one transaction.

    found: what find_mbox_files(mbox_dir) returned, when the caller examined the files itself,
    for example in a thread, to keep its event loop free while they are read.
    """
    found_files, unreadable = find_mbox_files(mbox_dir) if found is None else found
    async with session.begin():
        rows = {
            row.path: row
            for row in await session.execute(
                text("SELECT id, path, size_bytes, sha256_head, bytes_done FROM mbox_file")
            )
        }
        files: list[ScannedFile] = []
        new: list[str] = []
        replaced: list[tuple[str, str]] = []
        for file in found_files:
            row = rows.get(file.path)
            if row is None:
                new.append(file.path)
                files.append(await _insert(session, file))
                continue
            reason = _replace_reason(mbox_dir, file, row)
            if reason is not None:
                replaced.append((file.path, reason))
                await _forget_mails(session, row.id)
                bytes_done = 0
            else:
                bytes_done = row.bytes_done
            files.append(await _update(session, row.id, file, bytes_done))
        on_disk = {file.path for file in found_files} | {path for path, _ in unreadable}
        missing = tuple(sorted(path for path in rows if path not in on_disk))
    return ScanReport(tuple(files), tuple(new), tuple(replaced), missing, tuple(unreadable))


def _replace_reason(mbox_dir: Path, file: FoundFile, row: Row[Any]) -> str | None:
    """Why a known file must be imported again from scratch; None when it can continue."""
    if file.size_bytes < row.bytes_done:
        return f"shrank to {file.size_bytes} bytes, below its progress of {row.bytes_done}"
    head = file.sha256_head
    if row.size_bytes < min(file.size_bytes, HEAD_SIZE):  # grew inside its first MiB
        head = _head_digest(mbox_dir / file.path, row.size_bytes)
    return None if head == row.sha256_head else "first MiB changed"


def _status(file: FoundFile, bytes_done: int) -> MboxStatus:
    return MboxStatus.DONE if bytes_done == file.size_bytes else MboxStatus.PENDING


async def _insert(session: AsyncSession, file: FoundFile) -> ScannedFile:
    status = _status(file, 0)
    file_id = await session.scalar(
        text(
            "INSERT INTO mbox_file (path, size_bytes, sha256_head, status) "
            "VALUES (:path, :size, :head, CAST(:status AS mbox_status)) RETURNING id"
        ),
        {"path": file.path, "size": file.size_bytes, "head": file.sha256_head, "status": status},
    )
    assert file_id is not None
    return ScannedFile(file_id, file.path, file.size_bytes, 0, status)


async def _forget_mails(session: AsyncSession, file_id: int) -> None:
    """Delete a file's mails (cascading to their rows) and import errors, reset its progress."""
    await session.execute(text("DELETE FROM mail WHERE mbox_file_id = :id"), {"id": file_id})
    await session.execute(
        text("DELETE FROM import_error WHERE mbox_file_id = :id"), {"id": file_id}
    )
    await session.execute(
        text(
            "UPDATE mbox_file SET bytes_done = 0, mails_parsed = 0, error_count = 0, "
            "started_at = NULL, finished_at = NULL WHERE id = :id"
        ),
        {"id": file_id},
    )


async def _update(
    session: AsyncSession, file_id: int, file: FoundFile, bytes_done: int
) -> ScannedFile:
    """Known file: new size and head; done or pending (rows left running or paused resume)."""
    status = _status(file, bytes_done)
    await session.execute(
        text(
            "UPDATE mbox_file SET size_bytes = :size, sha256_head = :head, "
            "status = CAST(:status AS mbox_status), worker_id = NULL WHERE id = :id"
        ),
        {"id": file_id, "size": file.size_bytes, "head": file.sha256_head, "status": status},
    )
    return ScannedFile(file_id, file.path, file.size_bytes, bytes_done, status)

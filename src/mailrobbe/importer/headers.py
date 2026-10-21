"""The headers phase of an import: header fields of older imports read again (D52).

mbox_file.header_version says which header fields the stored mails of a file have. Mails of a
file below db.models.HEADER_VERSION were imported before the importer read List-Id,
Auto-Submitted and Precedence (D39), so the import first reads their header blocks again:

    per file, in file order, PAGE mails at a time (keyset on byte_offset):
        read the head of each record, HEAD_SIZE bytes or more when its header block is longer;
        heads close to each other with one read, so the file is read front to back in large
        blocks and attachments are never read
     -> parse.list_fields: list_id and automated as parse_record gives them
     -> written for the rows whose values change, a page per transaction
    and the file's new version once every mail was read

A file that is missing or cannot be read, or that no longer holds a record where it was
imported, keeps its version with a warning, so the next import tries again; its mails stay as
they are (the scan imports a file whose head changed again from scratch, D14). person.kind
follows at the finalize that ends the import.
"""

import asyncio
import logging
import re
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.db.models import HEADER_VERSION
from mailrobbe.importer.parse import list_fields
from mailrobbe.importer.runner import ImportFigures
from mailrobbe.importer.split import MboxRecord
from mailrobbe.jobrun import describe
from mailrobbe.mbox import unescape_from_lines

log = logging.getLogger(__name__)

PAGE = 1000  # mails per page and per transaction
HEAD_SIZE = 64 * 1024  # bytes read of a record at first
READ_SPAN = 1024**2  # the heads of records within this many bytes are read together
_EMPTY_LINE = re.compile(rb"\n\r?\n")  # the end of a header block

_OUTDATED = text("""
    SELECT f.id, f.path, (SELECT count(*) FROM mail m WHERE m.mbox_file_id = f.id) AS mails
    FROM mbox_file f WHERE f.header_version < :version ORDER BY f.path
""")
_PAGE = text("""
    SELECT id, byte_offset, byte_length, list_id, automated FROM mail
    WHERE mbox_file_id = :file AND byte_offset > :after ORDER BY byte_offset LIMIT :limit
""")
_UPDATE = text("""
    UPDATE mail SET list_id = u.list_id, automated = u.automated
    FROM unnest(CAST(:ids AS bigint[]), CAST(:list_ids AS text[]), CAST(:automated AS boolean[]))
        AS u(id, list_id, automated)
    WHERE mail.id = u.id
""")
_VERSION = text("UPDATE mbox_file SET header_version = :version WHERE id = :id")

ListFields = tuple[str | None, bool]  # mail.list_id, mail.automated


@dataclass(frozen=True, slots=True)
class OutdatedFile:
    id: int
    path: str  # relative to the MBOX directory
    mails: int  # stored mails


async def outdated_files(session: AsyncSession) -> list[OutdatedFile]:
    """Files whose stored mails lack header fields the importer reads now, by path."""
    rows = await session.execute(_OUTDATED, {"version": HEADER_VERSION})
    await session.commit()
    return [OutdatedFile(file_id, path, mails) for file_id, path, mails in rows]


async def refresh_headers(
    sessionmaker: async_sessionmaker[AsyncSession],
    mbox_dir: Path,
    files: Sequence[OutdatedFile],
    stop: asyncio.Event,
    figures: ImportFigures,
) -> None:
    """Read the headers of these files' mails again, until done or `stop` is set (between pages).

    figures.headers_done counts the mails read.
    """
    for file in files:
        if stop.is_set():
            return
        async with sessionmaker() as session:
            await _refresh_file(session, mbox_dir, file, stop, figures)


async def _refresh_file(
    session: AsyncSession,
    mbox_dir: Path,
    file: OutdatedFile,
    stop: asyncio.Event,
    figures: ImportFigures,
) -> None:
    if file.mails == 0:
        await _raise_version(session, file)
        return
    started = time.monotonic()
    try:
        handle = await asyncio.to_thread((mbox_dir / file.path).open, "rb")
    except OSError as error:
        log.warning("headers of %s not read again: %s", file.path, error.strerror or error)
        return
    read = changed = 0
    lost: list[int] = []  # offsets of records the file no longer holds
    with handle:
        after = -1
        while not stop.is_set():
            async with session.begin():
                rows = (
                    await session.execute(_PAGE, {"file": file.id, "after": after, "limit": PAGE})
                ).all()
            if not rows:
                break
            try:
                fields = await asyncio.to_thread(_read_page, handle, rows)
            except OSError as error:
                log.warning(
                    "headers of %s not read again from byte %d on: %s",
                    file.path,
                    rows[0].byte_offset,
                    error.strerror or describe(error),
                )
                return
            updates = []
            for row, found in zip(rows, fields, strict=True):
                if found is None:
                    lost.append(row.byte_offset)
                elif found != (row.list_id, row.automated):
                    updates.append((row.id, *found))
            if updates:
                ids, list_ids, automated = zip(*updates, strict=True)
                async with session.begin():
                    await session.execute(
                        _UPDATE,
                        {
                            "ids": list(ids),
                            "list_ids": list(list_ids),
                            "automated": list(automated),
                        },
                    )
            read += len(rows)
            changed += len(updates)
            figures.headers_done += len(rows)
            after = rows[-1].byte_offset
            if len(rows) < PAGE:
                break
        else:
            return  # stopped: the next import reads the file again from its start
    seconds = time.monotonic() - started
    rate = read / max(seconds, 1e-9)
    if lost:
        log.warning(
            "headers of %s: %d of %d mails are no longer at their offsets (the first at byte "
            "%d); its mails keep their header fields until the next import",
            file.path,
            len(lost),
            read,
            lost[0],
        )
        return
    await _raise_version(session, file)
    log.info(
        "headers of %s read again: %d mails, %d changed in %.1f s (%.0f mails/s)",
        file.path,
        read,
        changed,
        seconds,
        rate,
    )


async def _raise_version(session: AsyncSession, file: OutdatedFile) -> None:
    async with session.begin():
        await session.execute(_VERSION, {"version": HEADER_VERSION, "id": file.id})


# Reading heads (in a thread) ------------------------------------------------------------------


def _read_page(handle: BinaryIO, rows: Sequence[Row[Any]]) -> list[ListFields | None]:
    """The list fields of each record in the page, None for one the file no longer holds."""
    fields: list[ListFields | None] = []
    for group in _groups(rows):
        start = group[0].byte_offset
        handle.seek(start)
        block = handle.read(_head_end(group[-1]) - start)
        for row in group:
            at = row.byte_offset - start
            fields.append(_list_fields(handle, row, block[at : _head_end(row) - start]))
    return fields


def _head_end(row: Row[Any]) -> int:
    return int(row.byte_offset + min(row.byte_length, HEAD_SIZE))


def _groups(rows: Sequence[Row[Any]]) -> Iterator[Sequence[Row[Any]]]:
    """Runs of records whose heads lie within READ_SPAN bytes, in file order: one read each."""
    first = 0
    for index, row in enumerate(rows):
        if index > first and _head_end(row) - rows[first].byte_offset > READ_SPAN:
            yield rows[first:index]
            first = index
    yield rows[first:]


def _list_fields(handle: BinaryIO, row: Row[Any], head: bytes) -> ListFields | None:
    """list_id and automated of the record whose first bytes are `head`; reads further when its
    header block is longer, up to the whole record."""
    wanted = min(row.byte_length, HEAD_SIZE)
    while True:
        if len(head) < wanted or not head.startswith(b"From "):
            return None  # the file is shorter now, or another record starts here
        line_end = head.find(b"\n")
        end = _EMPTY_LINE.search(head, line_end) if line_end >= 0 else None
        if end is not None or wanted == row.byte_length:
            break
        wanted = min(row.byte_length, 4 * wanted)
        handle.seek(row.byte_offset)
        head = handle.read(wanted)
    if end is not None:
        head = head[: end.end()]
    separator, _, message = head.partition(b"\n")
    record = MboxRecord(
        row.byte_offset,
        row.byte_length,
        separator.removesuffix(b"\r"),
        unescape_from_lines(message),
        "",
        truncated=True,  # its head only, as for a record above the size limit
    )
    return list_fields(record)

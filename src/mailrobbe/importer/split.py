"""MBOX framing: a file read sequentially in large blocks, cut into records (mailrobbe.mbox).

Every byte from the start offset to the end of the file belongs to exactly one record, so the
lengths of all records add up to the bytes read, and the end of the last record handed out is a
safe resume offset (mbox_file.bytes_done).

A record boundary is a line starting with `From ` that (a) looks like a From_ line: an envelope
sender without spaces and an asctime date (`From a@b.example Mon Mar  4 09:12:33 2019`, also with
a numeric zone before the year as Gmail writes it), and (b) is followed by a header field. Body
lines that start with `From ` but are prose fail (a); a quoted separator inside a body is
followed by an empty line and fails (b). The offset handed in as `start` is always a boundary.
Defects become issues on the record, never a lost or merged mail: data at `start` without a
From_ line, a malformed From_ line at `start`, a separator not preceded by an empty line, and a
record above max_size (kept as its first TRUNCATED_HEAD_SIZE message bytes, still hashed whole).

CRLF line endings are accepted: a From_ line, the field name after it and the empty line before
it may end with CR LF (MboxRecord.separator is then given without the CR). The message keeps
its bytes unchanged; mailrobbe.mbox only strips the LF of a closing LF LF, so a CRLF record's
message keeps its closing CR LF as a trailing empty line, which DKIM body canonicalisation
ignores.
"""

import hashlib
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import BinaryIO, cast

from mailrobbe.enums import ImportErrorKind
from mailrobbe.importer.model import TRUNCATED_HEAD_SIZE, Issue
from mailrobbe.mbox import unescape_from_lines

# Bytes per read: large and sequential, because bind mounts are slow on Docker Desktop (macOS).
BLOCK_SIZE = 16 * 1024**2


@dataclass(frozen=True, slots=True)
class MboxRecord:
    byte_offset: int  # offset of the `F` of the separator line
    byte_length: int  # separator, message and the empty line, up to the next record
    separator: bytes  # the From_ line without its LF; b"" for data without a From_ line
    message: bytes  # mailrobbe.mbox.message_from_record(); the first TRUNCATED_HEAD_SIZE bytes
    # of it when truncated
    raw_sha256: str  # hex SHA-256 of the complete message, also when truncated
    truncated: bool = False  # the message is longer than max_size and was not kept in memory
    issues: tuple[Issue, ...] = ()  # framing defects (ImportErrorKind.SEPARATOR, TOO_LARGE)


_MONTHS = b"Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_FROM_LINE = (
    rb"From \S+ +(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) +(" + b"|".join(_MONTHS) + rb") +(\d{1,2})"
    rb" +(\d{1,2}):(\d\d)(?::(\d\d))? +(?:([+-])(\d\d)(\d\d) +)?(\d{4})[ \t]*"
)
_SEPARATOR = re.compile(_FROM_LINE + rb"\r?\n[!-9;-~]+[ \t]*:")  # (a) and (b), at a candidate
_SEPARATOR_LINE = re.compile(_FROM_LINE + rb"\r?")
_CANDIDATE = b"\nFrom "
# A From_ line and the field name of the next line fit into this many bytes.
_LOOKAHEAD = 4096
# Bytes kept in front of a candidate: the empty line before it, LF LF or LF CR LF.
_CONTEXT = 3
# A record above max_size is hashed in pieces of this size, which bounds the copies it needs.
_STREAM_PIECE = 256 * 1024


def separator_date(separator: bytes) -> datetime | None:
    """The instant of a From_ line (asctime in UTC unless it carries an offset), else None."""
    match = _SEPARATOR_LINE.fullmatch(separator)
    if match is None:
        return None
    month, day, hour, minute, second, sign, zone_h, zone_m, year = match.groups()
    try:
        instant = datetime(
            int(year),
            _MONTHS.index(month) + 1,
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            tzinfo=UTC,
        )
    except ValueError:
        return None
    if sign:
        offset = timedelta(hours=int(zone_h), minutes=int(zone_m))
        instant = instant - offset if sign == b"+" else instant + offset
    return instant


def iter_records(
    handle: BinaryIO, start: int = 0, *, max_size: int, block_size: int = BLOCK_SIZE
) -> Iterator[MboxRecord]:
    """Records of an open MBOX file from `start` to its end.

    `start` is 0 or the end of a record handed out earlier. Memory stays bounded by block_size
    plus max_size, however large the file or a single record is.
    """
    yield from _Framer(handle, start, max_size, block_size).records()


class _Framer:
    """Reads the file forward into one reused buffer and cuts it at accepted separators.

    self._buf[: self._end] holds the file bytes from offset self._base on: a few context bytes,
    the part of the current record not consumed yet (from index self._at) and what was read
    after it. A record that spans reads is consumed into _pending, or into a _StreamedMessage
    once it is larger than max_size, so the buffer holds one block and a short tail at most.
    """

    def __init__(self, handle: BinaryIO, start: int, max_size: int, block_size: int) -> None:
        # typing.BinaryIO lacks readinto, which every binary file object has; reading into one
        # reused buffer saves copying each block.
        self._readinto = cast(io.BufferedIOBase, handle).readinto
        self._max_size = max_size
        self._block_size = block_size
        self._buf = bytearray(_CONTEXT + _LOOKAHEAD + block_size)
        context = max(0, start - _CONTEXT)
        handle.seek(context)
        head = handle.read(start - context)
        self._buf[: len(head)] = head
        self._end = len(head)
        self._base = context
        self._at = start - context
        self._eof = self._end < self._at
        # the current record
        self._offset = start
        self._separator = b""
        self._issues: list[Issue] = []
        self._pending = bytearray()
        self._streamed: _StreamedMessage | None = None

    def records(self) -> Iterator[MboxRecord]:
        while self._end < self._at + _LOOKAHEAD and self._read():
            pass
        if self._end <= self._at:
            return
        self._begin_first()
        buf = self._buf
        search = self._at
        while True:
            newline = buf.find(_CANDIDATE, search, self._end)
            if newline < 0:
                if self._eof:
                    break
                self._advance(max(search, self._end - len(_CANDIDATE) + 1))
                search = self._at
                continue
            candidate = newline + 1
            end = candidate + _LOOKAHEAD
            if _SEPARATOR.match(buf, candidate, min(end, self._end)) is None:
                if self._end < end and not self._eof:
                    self._advance(newline)
                    search = self._at
                else:
                    search = candidate
                continue
            yield self._finish(candidate)
            self._begin(candidate)
            search = candidate
        yield self._finish(self._end)

    def _read(self) -> bool:
        if self._eof:
            return False
        view = memoryview(self._buf)[self._end : self._end + self._block_size]
        count = self._readinto(view)
        if not count:
            self._eof = True
            return False
        self._end += count
        return True

    def _advance(self, keep: int) -> None:
        """Consume the current record up to index `keep`, drop what lies before, read on.

        The bytes kept are a few context bytes plus at most _LOOKAHEAD, so a block fits behind.
        """
        self._consume(memoryview(self._buf)[self._at : keep])
        drop = max(0, keep - _CONTEXT)
        self._buf[: self._end - drop] = self._buf[drop : self._end]
        self._end -= drop
        self._base += drop
        self._at = keep - drop
        self._read()

    def _consume(self, data: memoryview) -> None:
        """Add bytes to the current record: kept up to max_size, streamed beyond."""
        if self._streamed is not None:
            self._streamed.update(data)
            return
        self._pending += data
        if len(self._pending) > self._max_size:
            self._start_streaming()

    def _start_streaming(self) -> "_StreamedMessage":
        streamed = self._streamed = _StreamedMessage(bool(self._separator))
        pending, self._pending = self._pending, bytearray()
        streamed.update(memoryview(pending))
        return streamed

    def _begin_first(self) -> None:
        """The record at `start`, a boundary whatever it holds."""
        if not self._buf.startswith(b"From ", self._at, self._end):
            self._issues = [Issue(ImportErrorKind.SEPARATOR, "data without a From_ line")]
            return
        self._begin(self._at)
        if separator_date(self._separator) is None:
            self._issues.append(Issue(ImportErrorKind.SEPARATOR, "malformed From_ line"))

    def _begin(self, at: int) -> None:
        buf = self._buf
        self._offset = self._base + at
        self._at = at
        line_end = min(self._end, at + _LOOKAHEAD)
        newline = buf.find(b"\n", at, line_end)
        if newline >= 0:
            line_end = newline
        self._separator = bytes(buf[at:line_end]).removesuffix(b"\r")
        self._issues = []
        empty_line = buf.endswith(b"\n\n", 0, at) or buf.endswith(b"\n\r\n", 0, at)
        if self._offset > 0 and not empty_line:
            self._issues.append(
                Issue(ImportErrorKind.SEPARATOR, "From_ line not preceded by an empty line")
            )

    def _finish(self, end: int) -> MboxRecord:
        """The record from its start up to index `end` of the buffer."""
        tail = memoryview(self._buf)[self._at : end]
        length = self._base + end - self._offset
        streamed = self._streamed
        if streamed is None and length <= self._max_size:
            if self._pending:
                self._pending += tail
                message = _message(self._pending, 0, len(self._pending))
                self._pending = bytearray()
            else:
                message = _message(self._buf, self._at, end)
            return MboxRecord(
                self._offset,
                length,
                self._separator,
                message,
                hashlib.sha256(message).hexdigest(),
                issues=tuple(self._issues),
            )
        if streamed is None:
            self._pending += tail
            streamed = self._start_streaming()
        else:
            streamed.update(tail)
        head, digest = streamed.finish()
        self._streamed = None
        issue = Issue(
            ImportErrorKind.TOO_LARGE,
            f"record of {length} bytes is larger than {self._max_size}: headers only",
        )
        return MboxRecord(
            self._offset, length, self._separator, head, digest, True, (*self._issues, issue)
        )


def _message(buf: bytes | bytearray, start: int, end: int) -> bytes:
    """message_from_record(buf[start:end]), with one copy instead of three for a large record."""
    if buf.startswith(b"From ", start, end):
        newline = buf.find(b"\n", start, end)
        start = end if newline < 0 else newline + 1
    if buf.endswith(b"\n\n", start, end):
        end -= 1
    return unescape_from_lines(bytes(memoryview(buf)[start:end]))


class _StreamedMessage:
    """message_from_record over a record fed in pieces: the head of the message and its SHA-256.

    The separator line is skipped, mboxrd quoting is undone line by line (a line start that may
    still turn out to be `>+From ` is held back, at most one `>` and four letters), and a final
    LF is held back until the end shows whether the record closed with LF LF.
    """

    def __init__(self, has_separator: bool) -> None:
        self._skip_line = has_separator
        self._mid_line = False  # inside a line whose start was already written
        self._held = b""  # start of a line that may still be a quoted From_ line
        self._last_two = b""  # last two bytes of the message so far
        self._held_newline = False
        self._hash = hashlib.sha256()
        self._head = bytearray()

    def update(self, data: memoryview) -> None:
        for at in range(0, len(data), _STREAM_PIECE):
            self._piece(bytes(data[at : at + _STREAM_PIECE]))

    def _piece(self, data: bytes) -> None:
        if self._skip_line or self._mid_line:
            newline = data.find(b"\n")
            if newline < 0:
                if self._mid_line:
                    self._write(data)
                return
            if self._mid_line:
                self._write(data[: newline + 1])
            self._skip_line = self._mid_line = False
            data = data[newline + 1 :]
        if self._held:
            data, self._held = self._held + data, b""
        cut = data.rfind(b"\n") + 1
        self._write(unescape_from_lines(data[:cut]))
        rest = data[cut:]
        quotes = len(rest) - len(rest.lstrip(b">"))
        if quotes and len(rest) - quotes < 5 and b"From ".startswith(rest[quotes:]):
            # every `>` but the last one is written whatever comes next
            self._write(rest[: quotes - 1])
            self._held = rest[quotes - 1 :]
        elif rest:
            self._mid_line = True
            self._write(unescape_from_lines(rest))

    def finish(self) -> tuple[bytes, str]:
        self._write(self._held)
        if self._held_newline and self._last_two != b"\n\n":
            self._emit(b"\n")
        return bytes(self._head), self._hash.hexdigest()

    def _write(self, data: bytes) -> None:
        if not data:
            return
        self._last_two = (self._last_two + data[-2:])[-2:]
        if self._held_newline:
            self._emit(b"\n")
        self._held_newline = data.endswith(b"\n")
        self._emit(memoryview(data)[: len(data) - self._held_newline])

    def _emit(self, data: bytes | memoryview) -> None:
        self._hash.update(data)
        room = TRUNCATED_HEAD_SIZE - len(self._head)
        if room > 0:
            self._head += data[:room]

"""MBOX framing: a file read sequentially in large blocks, cut into records (mailrobbe.mbox).

Every byte from the start offset to the end of the file belongs to exactly one record, so the
lengths of all records add up to the bytes read, and the end of the last record handed out is a
safe resume offset (mbox_file.bytes_done).
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

from mailrobbe.importer.model import Issue

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


def iter_records(
    handle: BinaryIO, start: int = 0, *, max_size: int, block_size: int = BLOCK_SIZE
) -> Iterator[MboxRecord]:
    """Records of an open MBOX file from `start` to its end.

    `start` is 0 or the end of a record handed out earlier. Memory stays bounded by block_size
    plus max_size, however large the file or a single record is.
    """
    raise NotImplementedError

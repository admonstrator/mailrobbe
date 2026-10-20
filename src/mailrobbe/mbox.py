"""Reading one message back from an mboxrd file by its byte range (interim reader).

A stand-in so `mailrobbe dkim` works before the importer (milestone 2) lands; the importer ships
its own module with the same read_message, which replaces this one.
"""

import re
from pathlib import Path

_ESCAPED_FROM_LINE = re.compile(rb"^>(>*From )", re.MULTILINE)


def read_message(path: Path, byte_offset: int, byte_length: int) -> bytes:
    """The message of the record at byte_offset, as mail.raw_sha256 was computed over it.

    byte_offset points at the `F` of the `From ` separator line; byte_length covers that line,
    the quoted message and the record's empty line. The result has neither line, and the
    mboxrd quoting is undone. LF and CRLF records are accepted. Raises ValueError when the
    range does not hold such a record, OSError when the file cannot be read.
    """
    with path.open("rb") as handle:
        handle.seek(byte_offset)
        record = handle.read(byte_length)
    separator_end = record.find(b"\n") + 1
    if not record.startswith(b"From ") or not separator_end or len(record) != byte_length:
        raise ValueError(f"{path}: no MBOX record of {byte_length} bytes at offset {byte_offset}")
    end = len(record) - (2 if record.endswith(b"\r\n") else 1 if record.endswith(b"\n") else 0)
    message = record[separator_end:end]
    return _ESCAPED_FROM_LINE.sub(rb"\1", message) if b"From " in message else message

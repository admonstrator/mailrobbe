"""Reading single messages back from MBOX files (mboxrd), the one place that defines a record.

A record starts at the `F` of its `From ` separator line (byte_offset) and runs up to the next
accepted separator or the end of the file (byte_length), so it includes the empty line that
ends it. Its message is the record without the separator line and without that last empty
line, with mboxrd quoting undone (`>From ` -> `From `, `>>From ` -> `>From `, ...). The SHA-256
of the message is mail.raw_sha256 and, for generated data, the manifest's sha256.

The importer (mailrobbe.importer.split) finds records; the DKIM recheck and the mail detail
view read them back through read_message.
"""

import re
from pathlib import Path

_ESCAPED_FROM_LINE = re.compile(rb"^>(>*From )", re.MULTILINE)


def unescape_from_lines(data: bytes) -> bytes:
    """Undo mboxrd quoting: one `>` less in front of every line that matches `^>+From `."""
    if b"From " not in data:
        return data
    return _ESCAPED_FROM_LINE.sub(rb"\1", data)


def message_from_record(record: bytes) -> bytes:
    """The message of a complete record: separator line and final empty line removed, unquoted.

    A record that does not start with `From ` (data the importer found without a separator)
    keeps its first line. A record not ended by an empty line (the next separator followed
    directly) loses no trailing byte.
    """
    if record.startswith(b"From "):
        newline = record.find(b"\n")
        record = b"" if newline < 0 else record[newline + 1 :]
    if record.endswith(b"\n\n"):
        record = record[:-1]
    return unescape_from_lines(record)


def read_message(path: Path, byte_offset: int, byte_length: int) -> bytes:
    """The message of the record at byte_offset, as message_from_record returns it.

    Raises OSError when the file cannot be read and ValueError when it is shorter than the
    record (the file changed since it was imported).
    """
    with path.open("rb") as handle:
        handle.seek(byte_offset)
        record = handle.read(byte_length)
    if len(record) != byte_length:
        raise ValueError(
            f"{path}: record at {byte_offset} has {len(record)} of {byte_length} bytes"
        )
    return message_from_record(record)

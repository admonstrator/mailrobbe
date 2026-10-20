"""One MBOX record -> ParsedMail: headers, addresses, date, body text, attachment metadata."""

from mailrobbe.importer.model import ParsedMail
from mailrobbe.importer.split import MboxRecord


def parse_record(record: MboxRecord, *, attachment_hash_limit: int) -> ParsedMail:
    """Parse the message of a record; never raises for a broken message.

    Defects end up in ParsedMail.issues (ImportErrorKind); the record's own framing issues are
    not repeated there. A truncated record yields headers only: no body text, no attachments.
    Attachments larger than attachment_hash_limit bytes get sha256 None.
    """
    raise NotImplementedError

"""Attached mails (message/rfc822, .eml; D71): read as the importer reads a mail.

importer.parse.parse_record gives sender, recipients, date, subject and the body text (the first
text/plain part, else the text of the first HTML part, cut at BODY_TEXT_LIMIT); they are written
as a short header block in front of the text, with the names of the mail's own attachments,
whose texts are not read (no recursion).
"""

from mailrobbe.attachments.extract.base import Sink
from mailrobbe.enums import DocumentTextStatus
from mailrobbe.importer.model import ParsedAddress
from mailrobbe.importer.parse import parse_record
from mailrobbe.importer.split import MboxRecord


def _addresses(addresses: tuple[ParsedAddress, ...]) -> str:
    """Name <address>, as a reader sees it (email.utils.formataddr would encode the names)."""
    return ", ".join(
        f"{a.display_name} <{a.email}>" if a.display_name else a.email for a in addresses
    )


def extract_mail(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    record = MboxRecord(
        byte_offset=0, byte_length=len(data), separator=b"", message=data, raw_sha256=""
    )
    mail = parse_record(record, attachment_hash_limit=0)
    fields = (
        ("From", _addresses(mail.sender)),
        ("To", _addresses(mail.to)),
        ("Cc", _addresses(mail.cc)),
        ("Date", f"{mail.date_utc:%Y-%m-%d %H:%M:%S} UTC" if mail.date_utc else ""),
        ("Subject", mail.subject or ""),
        ("Attachments", ", ".join(a.filename for a in mail.attachments if a.filename)),
    )
    for name, value in fields:
        if value:
            sink.line(f"{name}: {value}")
    sink.block()
    if mail.body_text:
        sink.text(mail.body_text)
    return None

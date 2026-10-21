"""Reading an attachment's bytes back from its MBOX file: the one way to get them (D76).

The database stores no attachment bytes (SPEC 2). An attachment is found again as the importer
found it: read the mail's record (mbox.read_message), check it is still the imported message
(raw_sha256), walk its MIME tree with importer.parse.mime_parts and take the part at
attachment.position, decoded by importer.parse.attachment_payload; the bytes must have the
stored SHA-256, or the stored size when the attachment was too large to hash (D18).

attachment_source and document_sources look up where to read; read_attachment reads, in a
worker thread or process, since a file may be slow. The text extraction (D72), the downloads of
the API and the export of the Rechercheakte use these.
"""

import email.parser
import email.policy
import hashlib
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.importer.parse import attachment_payload, mime_parts
from mailrobbe.mbox import read_message

Executor = AsyncSession | AsyncConnection

_PARSER = email.parser.BytesParser(policy=email.policy.compat32)


class AttachmentChanged(Exception):
    """The MBOX file no longer holds the attachment as it was imported (409 source_changed)."""


@dataclass(frozen=True, slots=True)
class AttachmentSource:
    """Where an attachment is, and what its bytes must be."""

    attachment_id: int
    mail_id: int
    path: str  # of the MBOX file, relative to MAILROBBE_MBOX_DIR
    byte_offset: int  # of the mail's record
    byte_length: int
    raw_sha256: str  # of the mail's message
    position: int  # among the mail's attachments (attachment.position)
    size_bytes: int
    sha256: str | None  # None above the hash limit (D18)
    filename: str | None
    mime_type: str  # as declared in the mail


def read_attachment(mbox_dir: Path, source: AttachmentSource) -> bytes:
    """The attachment's bytes. Blocking: call it in a thread or a worker process.

    Raises OSError when the MBOX file cannot be read and AttachmentChanged when the record, the
    MIME part or the bytes are not the imported ones any more.
    """
    try:
        message = read_message(mbox_dir / source.path, source.byte_offset, source.byte_length)
    except ValueError as error:  # the file is shorter than the record now
        raise AttachmentChanged(str(error)) from None
    if hashlib.sha256(message).hexdigest() != source.raw_sha256:
        raise AttachmentChanged(f"{source.path}: the mail at byte {source.byte_offset} changed")
    attachments = mime_parts(_PARSER.parsebytes(message), []).attachments
    if source.position >= len(attachments):
        raise AttachmentChanged(
            f"mail {source.mail_id} has no attachment at position {source.position}"
        )
    data = attachment_payload(attachments[source.position][0], "attachment", [])
    if source.sha256 is None:
        if len(data) != source.size_bytes:
            raise AttachmentChanged(f"attachment {source.attachment_id} has another size")
    elif hashlib.sha256(data).hexdigest() != source.sha256:
        raise AttachmentChanged(f"attachment {source.attachment_id} has other bytes")
    return data


_SOURCE_COLUMNS = """
    a.id AS attachment_id, a.mail_id, f.path, m.byte_offset, m.byte_length, m.raw_sha256,
    a.position, a.size_bytes, a.sha256, a.filename, a.mime_type
"""
_ATTACHMENT = text(f"""
    SELECT {_SOURCE_COLUMNS}
    FROM attachment a JOIN mail m ON m.id = a.mail_id JOIN mbox_file f ON f.id = m.mbox_file_id
    WHERE a.id = :id
""")
# The occurrence a document is read from: one in a mail that is no duplicate, then the first by
# file path and offset, so the reads of many documents go through the files front to back.
_DOCUMENTS = text(f"""
    SELECT DISTINCT ON (a.document_id) a.document_id, {_SOURCE_COLUMNS}
    FROM attachment a JOIN mail m ON m.id = a.mail_id JOIN mbox_file f ON f.id = m.mbox_file_id
    WHERE a.document_id = ANY(CAST(:ids AS bigint[]))
    ORDER BY a.document_id, m.is_duplicate_of IS NOT NULL, f.path COLLATE "C", m.byte_offset,
        a.position
""")


async def attachment_source(db: Executor, attachment_id: int) -> AttachmentSource | None:
    """Where this attachment is; None when there is no attachment with this id."""
    row = (await db.execute(_ATTACHMENT, {"id": attachment_id})).one_or_none()
    return None if row is None else AttachmentSource(*row)


async def document_sources(
    db: Executor, document_ids: Collection[int]
) -> dict[int, AttachmentSource]:
    """For each document, the occurrence to read it from (see _DOCUMENTS); documents without
    attachments are left out."""
    rows = await db.execute(_DOCUMENTS, {"ids": list(document_ids)})
    return {document_id: AttachmentSource(*rest) for document_id, *rest in rows}

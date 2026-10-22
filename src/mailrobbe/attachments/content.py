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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

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
    position: int  # among the mail's attachments, or among the container's entries (D231)
    size_bytes: int
    sha256: str | None  # None above the hash limit (D18)
    filename: str | None
    mime_type: str  # as declared in the mail
    # A member of a container (D231, D232): where it sits in which container attachment. For the
    # mail's own MIME attachments both are None. member_path is its path inside the container.
    container_id: int | None = None
    member_path: str | None = None
    # The password that opens this document, when one was found (document_password, D236); used
    # to read this attachment's members (read_member) when it is a container.
    password: str | None = None
    # Where to read the container from, resolved by attachment_source/document_sources.
    container: "AttachmentSource | None" = None


def read_attachment(mbox_dir: Path, source: AttachmentSource) -> bytes:
    """The attachment's bytes, decrypted when it is a member of an opened container (D232).

    Blocking: call it in a thread or a worker process. Raises OSError when the MBOX file cannot
    be read and AttachmentChanged when the record, the container, the MIME part or the bytes are
    not the imported ones any more.
    """
    if source.container is not None:
        return _read_member(mbox_dir, source)
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
    _verify(source, data)
    return data


def _read_member(mbox_dir: Path, source: AttachmentSource) -> bytes:
    """The decrypted bytes of a member, read from its container (D232)."""
    from mailrobbe.attachments import packed

    container = source.container
    assert container is not None and source.member_path is not None
    container_bytes = read_attachment(mbox_dir, container)
    data = packed.read_member(
        container_bytes,
        container.filename,
        container.mime_type,
        source.member_path,
        container.password,
        source.size_bytes,
    )
    if data is None:
        raise AttachmentChanged(
            f"attachment {source.attachment_id}: {source.member_path!r} is not in its container"
        )
    _verify(source, data)
    return data


def _verify(source: AttachmentSource, data: bytes) -> None:
    if source.sha256 is None:
        if len(data) != source.size_bytes:
            raise AttachmentChanged(f"attachment {source.attachment_id} has another size")
    elif hashlib.sha256(data).hexdigest() != source.sha256:
        raise AttachmentChanged(f"attachment {source.attachment_id} has other bytes")


# f.path is the MBOX file; a.path, read as member_path, is a member's path inside its container
# (NULL for a mail's own attachment), whose own row says where to read it (_container_rows).
_SOURCE_COLUMNS = """
    a.id AS attachment_id, a.mail_id, f.path, m.byte_offset, m.byte_length, m.raw_sha256,
    a.position, a.size_bytes, a.sha256, a.filename, a.mime_type,
    a.container_id, a.path AS member_path, pw.value AS password
"""
_SOURCE_JOINS = """
    FROM attachment a JOIN mail m ON m.id = a.mail_id JOIN mbox_file f ON f.id = m.mbox_file_id
    LEFT JOIN document_password dp ON dp.document_id = a.document_id
    LEFT JOIN password pw ON pw.id = dp.password_id
"""
_ATTACHMENT = text(f"SELECT {_SOURCE_COLUMNS} {_SOURCE_JOINS} WHERE a.id = :id")
_ATTACHMENTS = text(
    f"SELECT {_SOURCE_COLUMNS} {_SOURCE_JOINS} WHERE a.id = ANY(CAST(:ids AS bigint[]))"
)
# The occurrence a document is read from: a mail's own attachment before a container's member, one
# in a mail that is no duplicate, then the first by file path and offset, so the reads of many
# documents go through the files front to back.
_DOCUMENTS = text(f"""
    SELECT DISTINCT ON (a.document_id) a.document_id, {_SOURCE_COLUMNS}
    {_SOURCE_JOINS}
    WHERE a.document_id = ANY(CAST(:ids AS bigint[]))
    ORDER BY a.document_id, a.container_id IS NOT NULL, m.is_duplicate_of IS NOT NULL,
        f.path COLLATE "C", m.byte_offset, a.position
""")


def _source(row: Any) -> AttachmentSource:
    return AttachmentSource(
        attachment_id=row.attachment_id,
        mail_id=row.mail_id,
        path=row.path,
        byte_offset=row.byte_offset,
        byte_length=row.byte_length,
        raw_sha256=row.raw_sha256,
        position=row.position,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        filename=row.filename,
        mime_type=row.mime_type,
        container_id=row.container_id,
        member_path=row.member_path if row.container_id is not None else None,
        password=row.password,
    )


async def _resolve_containers(
    db: Executor, sources: list[AttachmentSource]
) -> list[AttachmentSource]:
    """Attach each member's container source, up to one level (D231: depth 2)."""
    needed = {s.container_id for s in sources if s.container_id is not None}
    if not needed:
        return sources
    rows = await db.execute(_ATTACHMENTS, {"ids": list(needed)})
    containers = {row.attachment_id: _source(row) for row in rows}
    return [
        s if s.container_id is None else _with_container(s, containers.get(s.container_id))
        for s in sources
    ]


def _with_container(
    source: AttachmentSource, container: AttachmentSource | None
) -> AttachmentSource:
    return replace(source, container=container)


async def attachment_source(db: Executor, attachment_id: int) -> AttachmentSource | None:
    """Where this attachment is; None when there is no attachment with this id."""
    row = (await db.execute(_ATTACHMENT, {"id": attachment_id})).one_or_none()
    if row is None:
        return None
    (resolved,) = await _resolve_containers(db, [_source(row)])
    return resolved


async def document_sources(
    db: Executor, document_ids: Collection[int]
) -> dict[int, AttachmentSource]:
    """For each document, the occurrence to read it from (see _DOCUMENTS); documents without
    attachments are left out."""
    rows = await db.execute(_DOCUMENTS, {"ids": list(document_ids)})
    by_id = {row.document_id: _source(row) for row in rows}
    resolved = await _resolve_containers(db, list(by_id.values()))
    return dict(zip(by_id.keys(), resolved, strict=True))

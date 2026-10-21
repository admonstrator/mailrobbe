"""attachments.content.read_attachment: an attachment's bytes back from its MBOX file (D76)."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from mailrobbe.attachments.content import AttachmentChanged, AttachmentSource, read_attachment
from mailrobbe.importer.parse import parse_record
from mailrobbe.importer.split import iter_records
from tests.conftest import GeneratedArchive


def _sources(archive: GeneratedArchive) -> list[AttachmentSource]:
    """Every attachment of the first generated mails that have some, as the importer sees them."""
    sources: list[AttachmentSource] = []
    for entry in archive.manifest:
        if not entry["attachments"] or len(sources) > 20:
            continue
        with (archive.mbox_dir / entry["file"]).open("rb") as handle:
            record = next(iter_records(handle, entry["offset"], max_size=128 * 1024**2))
        mail = parse_record(record, attachment_hash_limit=50 * 1024**2)
        for position, attachment in enumerate(mail.attachments):
            sources.append(
                AttachmentSource(
                    attachment_id=len(sources) + 1,
                    mail_id=entry["index"],
                    path=entry["file"],
                    byte_offset=record.byte_offset,
                    byte_length=record.byte_length,
                    raw_sha256=record.raw_sha256,
                    position=position,
                    size_bytes=attachment.size_bytes,
                    sha256=attachment.sha256,
                    filename=attachment.filename,
                    mime_type=attachment.mime_type,
                )
            )
    return sources


def test_reads_every_attachment_with_the_imported_hash(generated_archive: GeneratedArchive) -> None:
    sources = _sources(generated_archive)
    assert len(sources) > 10
    for source in sources:
        data = read_attachment(generated_archive.mbox_dir, source)
        assert len(data) == source.size_bytes
        assert source.sha256 is None or hashlib.sha256(data).hexdigest() == source.sha256


def test_an_attachment_that_is_not_the_imported_one_is_refused(
    generated_archive: GeneratedArchive,
) -> None:
    source = _sources(generated_archive)[0]
    mbox_dir = generated_archive.mbox_dir
    changes = [
        replace(source, raw_sha256="0" * 64),
        replace(source, position=99),
        replace(source, sha256="0" * 64),
        replace(source, sha256=None, size_bytes=source.size_bytes + 1),
        replace(source, byte_length=source.byte_length + 1000),
    ]
    for changed in changes:
        with pytest.raises(AttachmentChanged):
            read_attachment(mbox_dir, changed)
    with pytest.raises(OSError):
        read_attachment(mbox_dir, replace(source, path="missing.mbox"))
    assert read_attachment(Path(mbox_dir), replace(source, sha256=None))

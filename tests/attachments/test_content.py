"""attachments.content.read_attachment: an attachment's bytes back from its MBOX file (D76)."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from mailrobbe.attachments.content import AttachmentChanged, AttachmentSource, read_attachment
from mailrobbe.importer.parse import parse_record
from mailrobbe.importer.split import iter_records
from tests.conftest import GeneratedArchive
from tests.importer.doubles import write_mbox
from tests.passwords import samples


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


# Members of containers (D231, D232) ----------------------------------------------------------


def _carried(mbox_dir: Path, files: list[tuple[str, str, bytes]]) -> list[AttachmentSource]:
    """A mail carrying these files, written to mbox_dir/a.mbox; its attachments as sources."""
    message = samples.mail(0, samples.ANNA, samples.BERT, "Anbei", "Anbei.\n", files)
    write_mbox(mbox_dir / "a.mbox", [message.as_bytes()])
    with (mbox_dir / "a.mbox").open("rb") as handle:
        record = next(iter_records(handle, 0, max_size=1024**2))
    mail = parse_record(record, attachment_hash_limit=1024**2)
    return [
        AttachmentSource(
            attachment_id=position + 1,
            mail_id=1,
            path="a.mbox",
            byte_offset=record.byte_offset,
            byte_length=record.byte_length,
            raw_sha256=record.raw_sha256,
            position=position,
            size_bytes=attachment.size_bytes,
            sha256=attachment.sha256,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
        )
        for position, attachment in enumerate(mail.attachments)
    ]


def _member(container: AttachmentSource, path: str, data: bytes) -> AttachmentSource:
    """The entry at path in the container, as the archives step stores it."""
    return replace(
        container,
        attachment_id=100,
        position=0,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        filename=path.rpartition("/")[2],
        mime_type="text/plain",
        container_id=container.attachment_id,
        member_path=path,
        password=None,
        container=container,
    )


@samples.needs_seven_zip
def test_a_member_is_read_through_its_container_with_its_password(tmp_path: Path) -> None:
    notiz_bytes, plan = b"Notiz zum Treffen\n", samples.PLAN
    paket = samples.seven_zip({"Plan.txt": plan}, "Paket.zip", "-tzip", "-pWellen#5", "-mem=AES256")
    akten, locked = _carried(
        tmp_path,
        [
            ("Akten.zip", samples.ZIP_MIME, samples.packed({"Ordner/Notiz.txt": notiz_bytes})),
            ("Paket.zip", samples.ZIP_MIME, paket),
        ],
    )
    notiz = _member(akten, "Ordner/Notiz.txt", notiz_bytes)
    assert read_attachment(tmp_path, notiz) == notiz_bytes
    member = _member(replace(locked, password="Wellen#5"), "Plan.txt", plan)
    assert read_attachment(tmp_path, member) == plan
    assert read_attachment(tmp_path, replace(member, sha256=None)) == plan  # by its size
    refused = [
        replace(member, container=locked),  # no password
        replace(member, container=replace(locked, password="Falsch")),
        replace(member, sha256="0" * 64),  # other bytes
        replace(member, sha256=None, size_bytes=len(plan) - 1),  # read no further than its size
        replace(notiz, container=replace(akten, raw_sha256="0" * 64)),  # another mail
    ]
    for source in refused:
        with pytest.raises(AttachmentChanged):
            read_attachment(tmp_path, source)
    with pytest.raises(AttachmentChanged, match=r"'Fehlt.txt' is not in its container$"):
        read_attachment(tmp_path, replace(member, member_path="Fehlt.txt"))
    with pytest.raises(OSError):
        read_attachment(tmp_path / "fehlt", notiz)

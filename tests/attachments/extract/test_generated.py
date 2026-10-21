"""Ground truth: every attachment of the generated archive, read back from its MBOX file as the
attachments phase reads it (read_attachment) and extracted, gives what manifest.jsonl expects:
the SHA-256, the kind, the status, the marker word in the text and the pages (D77)."""

import hashlib
from collections import Counter
from typing import Any

import pytest

from mailrobbe.attachments.content import AttachmentSource, read_attachment
from mailrobbe.attachments.extract import ExtractionLimits, extract_document
from mailrobbe.enums import DocumentTextStatus
from mailrobbe.importer.parse import parse_record
from mailrobbe.importer.split import iter_records
from tests.conftest import GeneratedArchive

TEXT_MAX_SIZE = 50 * 1024**2
LIMITS = ExtractionLimits(timeout=30)


def _occurrences(archive: GeneratedArchive) -> list[tuple[dict[str, Any], AttachmentSource]]:
    """(manifest truth, source) for every attachment of every mail, in manifest order."""
    found: list[tuple[dict[str, Any], AttachmentSource]] = []
    for entry in archive.manifest:
        if not entry["documents"]:
            continue
        with (archive.mbox_dir / entry["file"]).open("rb") as handle:
            record = next(iter_records(handle, entry["offset"], max_size=128 * 1024**2))
        mail = parse_record(record, attachment_hash_limit=TEXT_MAX_SIZE)
        names = [a.filename for a in mail.attachments]
        assert names == [d["filename"] for d in entry["documents"]], entry["index"]
        for position, (truth, attachment) in enumerate(
            zip(entry["documents"], mail.attachments, strict=True)
        ):
            source = AttachmentSource(
                attachment_id=len(found) + 1,
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
            found.append((truth, source))
    return found


@pytest.fixture(scope="module")
def occurrences(
    generated_archive: GeneratedArchive,
) -> list[tuple[dict[str, Any], AttachmentSource]]:
    return _occurrences(generated_archive)


def test_manifest_hashes_are_those_of_the_imported_attachments(
    occurrences: list[tuple[dict[str, Any], AttachmentSource]],
) -> None:
    damaged = 0
    for truth, source in occurrences:
        if truth["sha256"] is None:  # the invalid_base64 fault hit this attachment
            damaged += 1
            assert truth["status"] is None and truth["marker"] is None
            continue
        assert (source.sha256, source.size_bytes) == (truth["sha256"], truth["size"])
    assert damaged < len(occurrences) // 10


def test_every_distinct_document_extracts_as_the_manifest_expects(
    generated_archive: GeneratedArchive,
    occurrences: list[tuple[dict[str, Any], AttachmentSource]],
) -> None:
    statuses: Counter[str] = Counter()
    done: set[str] = set()
    for truth, source in occurrences:
        if truth["sha256"] is None or truth["sha256"] in done:
            continue
        done.add(truth["sha256"])
        statuses[truth["status"]] += 1
        if truth["status"] == DocumentTextStatus.TOO_LARGE:
            assert source.size_bytes > TEXT_MAX_SIZE
            continue
        data = read_attachment(generated_archive.mbox_dir, source)
        assert hashlib.sha256(data).hexdigest() == truth["sha256"]
        result = extract_document(data, source.filename, source.mime_type, LIMITS)
        where = (source.mail_id, source.filename)
        assert (result.kind, result.status) == (truth["kind"], truth["status"]), where
        if truth["marker"] is not None:
            assert truth["marker"] in result.text, where
        if truth["pages"] is not None:
            assert result.pages == truth["pages"], where
    for status in ("text", "unsupported", "scanned"):
        assert statuses[status], (status, statuses)
    assert len(done) > 40


def test_documents_circulate(occurrences: list[tuple[dict[str, Any], AttachmentSource]]) -> None:
    """The same document in several mails, also under other file names."""
    documents = [truth for truth, _ in occurrences if truth["marker"] is not None]
    by_hash = Counter(truth["sha256"] for truth in documents)
    assert len(documents) / len(by_hash) > 1.5
    names: dict[str, set[str]] = {}
    for truth in documents:
        names.setdefault(truth["sha256"], set()).add(truth["filename"])
    assert any(len(found) > 1 for found in names.values())
    markers = {truth["sha256"]: truth["marker"] for truth in documents}
    assert len(set(markers.values())) == len(markers)  # one marker per distinct document

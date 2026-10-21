"""attachments.kinds.classify: content first, then file name, then MIME type (D71)."""

import pytest

from mailrobbe.attachments.kinds import FORMATS, classify
from mailrobbe.enums import DocumentKind

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ZIP_HEAD = b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00[Content_Types].xml"
ODT_HEAD = (
    b"PK\x03\x04\x14\x00\x00\x08\x00\x00"
    + b"\x00" * 16
    + b"mimetypeapplication/vnd.oasis.opendocument.text"
)
OLE_HEAD = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32


@pytest.mark.parametrize(
    ("filename", "mime_type", "head", "expected"),
    [
        ("Vertrag.pdf", "application/pdf", b"", "pdf"),
        ("Vertrag.PDF", "application/octet-stream", b"", "pdf"),
        ("Rechnung", "application/pdf", b"", "pdf"),
        (None, "application/octet-stream", b"%PDF-1.7\n", "pdf"),
        ("Liste.docx", "application/pdf", b"%PDF-1.4", "pdf"),  # the content wins
        ("Protokoll.docx", "application/octet-stream", ZIP_HEAD, "docx"),
        (None, DOCX, ZIP_HEAD, "docx"),
        ("Unterlagen.zip", "application/zip", ZIP_HEAD, "zip"),
        (None, "application/octet-stream", ZIP_HEAD, "zip"),
        ("Bericht.odt", "application/octet-stream", ODT_HEAD, "odt"),
        ("Bericht.zip", "application/zip", ODT_HEAD, "odt"),
        ("Alt.doc", "application/msword", OLE_HEAD, "doc"),
        ("Geheim.xlsx", "application/octet-stream", OLE_HEAD, "xlsx"),  # encrypted OOXML
        (None, "application/octet-stream", OLE_HEAD, "ole"),
        ("Spenden.xlsm", "application/octet-stream", b"", "xlsx"),
        ("Folien.ppsx", "", b"", "pptx"),
        (
            None,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            b"",
            "pptx",
        ),
        ("Konto.csv", "text/plain", b"", "csv"),
        ("notes", "text/plain; charset=utf-8", b"", "text"),
        ("Einladung.ics", "application/octet-stream", b"", "calendar"),
        ("Weitergeleitet", "message/rfc822", b"", "eml"),
        ("Brief.rtf", "application/octet-stream", b"", "rtf"),
        (None, "application/octet-stream", b"{\\rtf1\\ansi", "rtf"),
        ("IMG_1.jpg", "image/jpeg", b"", "image"),
        ("scan", "application/octet-stream", b"\x89PNG\r\n\x1a\n\x00", "image"),
        ("film.mp4", "application/octet-stream", b"\x00\x00\x00\x18ftypmp42", "media"),
        ("Backup.7z", "application/octet-stream", b"", "archive"),
        (".pdf", "application/octet-stream", b"", "other"),  # a hidden name, no extension
        (None, "application/octet-stream", b"", "other"),
        ("daten.bin", "application/x-whatever", b"\x00\x01", "other"),
    ],
)
def test_classify(filename: str | None, mime_type: str, head: bytes, expected: str) -> None:
    assert classify(filename, mime_type, head).name == expected


def test_every_format_has_a_kind_and_legacy_office_is_not_extracted() -> None:
    assert {fmt.kind for fmt in FORMATS.values()} == set(DocumentKind)
    assert [name for name in ("doc", "xls", "ppt", "msg") if FORMATS[name].extractable] == []
    extractable = {name for name, fmt in FORMATS.items() if fmt.extractable}
    assert {"pdf", "docx", "xlsx", "pptx", "odt", "ods", "odp", "csv", "text", "eml"} <= extractable

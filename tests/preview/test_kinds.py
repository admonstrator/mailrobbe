"""preview_kind (D120): which attachments the browser shows, and how."""

import pytest

from mailrobbe.enums import DocumentKind
from mailrobbe.preview.kinds import PreviewKind, preview_kind

K = DocumentKind
MiB = 1024**2


def _kind(
    kind: DocumentKind | None,
    filename: str | None,
    mime_type: str = "application/octet-stream",
    size: int = 1000,
    hashed: bool = True,
) -> PreviewKind | None:
    return preview_kind(kind, filename, mime_type, size, hashed=hashed, max_size=50 * MiB)


@pytest.mark.parametrize(
    ("kind", "filename", "mime_type", "expected"),
    [
        (K.PDF, "Angebot.pdf", "application/pdf", "pdf"),
        (K.PDF, "scan", "application/octet-stream", "pdf"),  # the first bytes said PDF
        (K.IMAGE, "Foto.png", "image/png", "image"),
        (K.IMAGE, "IMG_1.JPG", "application/octet-stream", "image"),
        (K.IMAGE, "bild", "image/webp", "image"),
        (K.IMAGE, "Plan.tif", "image/tiff", None),
        (K.IMAGE, "logo.svg", "image/svg+xml", None),  # scriptable: download only
        (K.DOCUMENT, "Vertrag.docx", "application/octet-stream", "html"),
        (K.DOCUMENT, "Protokoll.odt", "application/vnd.oasis.opendocument.text", "html"),
        (K.DOCUMENT, "Brief.doc", "application/msword", None),
        (K.DOCUMENT, "Notiz.rtf", "application/rtf", None),
        (K.SPREADSHEET, "Angebot.xlsx", "application/octet-stream", None),
        (K.MEDIA, "Ansage.mp3", "audio/mpeg", "audio"),
        (K.MEDIA, "Memo.M4A", "application/octet-stream", "audio"),
        (K.MEDIA, "Aufnahme.wav", "audio/wav", "audio"),
        (K.MEDIA, "Messe_Video.mp4", "video/mp4", "video"),
        (K.MEDIA, "Clip.webm", "video/webm", "video"),
        (K.MEDIA, "IMG_0042.MOV", "video/quicktime", "video"),
        (K.MEDIA, "Sprachnachricht", "audio/ogg", "audio"),
        (K.MEDIA, "Mitschnitt.wma", "audio/mpeg", None),  # the name says WMA
        (K.MEDIA, "Film.avi", "video/x-msvideo", None),
        (K.ARCHIVE, "Unterlagen.zip", "application/zip", None),
        (None, "Angebot.pdf", "application/pdf", "pdf"),  # not classified yet
        (None, "Vertrag.docx", "application/octet-stream", "html"),
        (None, "Ansage", "audio/mpeg", "audio"),
        (None, "Daten.bin", "application/octet-stream", None),
    ],
)
def test_kinds(
    kind: DocumentKind | None, filename: str, mime_type: str, expected: PreviewKind | None
) -> None:
    assert _kind(kind, filename, mime_type) == expected


def test_size_limits() -> None:
    assert _kind(K.PDF, "a.pdf", size=0) is None
    assert _kind(K.PDF, "a.pdf", size=50 * MiB) == "pdf"
    assert _kind(K.PDF, "a.pdf", size=50 * MiB + 1) is None


def test_cached_previews_need_the_hash() -> None:
    assert _kind(K.DOCUMENT, "a.docx", hashed=False) is None
    assert _kind(K.MEDIA, "a.mp3", hashed=False) is None
    assert _kind(K.PDF, "a.pdf", hashed=False) == "pdf"  # read from the MBOX file each time
    assert _kind(K.IMAGE, "a.png", hashed=False) == "image"

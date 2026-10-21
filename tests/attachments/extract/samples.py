"""Small documents of every format, built in the tests (no fixtures on disk)."""

import io
import random
import zipfile
from datetime import datetime

from mailrobbe.attachments.extract import Extraction, ExtractionLimits, extract_document
from mailrobbe.generator import fileformats as ff

WHEN = datetime(2021, 3, 4, 10, 30)
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ODF = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"'
)


LIMITS = ExtractionLimits(timeout=30)


def extract(
    data: bytes,
    filename: str,
    mime_type: str = "application/octet-stream",
    limits: ExtractionLimits = LIMITS,
) -> Extraction:
    return extract_document(data, filename, mime_type, limits)


def package(members: dict[str, str | bytes], *, deflate: bool = True) -> bytes:
    buffer = io.BytesIO()
    method = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", method) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def rels(*targets: tuple[str, str]) -> str:
    items = "".join(
        f'<Relationship Id="rId{n}" Type="{R}/{kind}" Target="{target}"/>'
        for n, (kind, target) in enumerate(targets, 1)
    )
    ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    return f'<?xml version="1.0"?><Relationships xmlns="{ns}">{items}</Relationships>'


def paragraph(*runs: str) -> str:
    texts = "".join(f"<w:r><w:t xml:space='preserve'>{run}</w:t></w:r>" for run in runs)
    return f"<w:p>{texts}</w:p>"


def docx(
    body: str, extra: dict[str, str] | None = None, related: tuple[tuple[str, str], ...] = ()
) -> bytes:
    """A DOCX with this body XML; `related` parts (kind, member under word/) with `extra` XML."""
    members: dict[str, str | bytes] = {
        "[Content_Types].xml": "<Types/>",
        "_rels/.rels": rels(("officeDocument", "word/document.xml")),
        "word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>",
        "word/_rels/document.xml.rels": rels(*related),
    }
    for name, xml in (extra or {}).items():
        members[f"word/{name}"] = xml
    return package(members)


def odf(mimetype: str, body: str, manifest: str = "") -> bytes:
    content = (
        f"<office:document-content {ODF}><office:body>{body}</office:body>"
        "</office:document-content>"
    )
    members: dict[str, str | bytes] = {"mimetype": mimetype, "content.xml": content}
    if manifest:
        members["META-INF/manifest.xml"] = manifest
    return package(members)


def pdf(
    pages: list[list[str]], *, password: str | None = None, images: tuple[int, ...] = ()
) -> bytes:
    return ff.pdf(pages, random.Random(1), password=password, images=images)


def ole(*streams: str) -> bytes:
    """An OLE compound file head with these stream names in its directory (UTF-16)."""
    names = b"".join(name.encode("utf-16-le") + b"\x00\x00" for name in streams)
    return OLE + b"\x00" * 504 + names + b"\x00" * 1024

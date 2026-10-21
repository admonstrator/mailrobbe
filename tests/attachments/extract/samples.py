"""Small documents of every format, built in the tests (no fixtures on disk)."""

import html
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
XPS_NS = 'xmlns="http://schemas.microsoft.com/xps/2005/06"'
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
    filename: str | None,
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


def xps(pages: list[str], *, order: list[int] | None = None, chain: bool = True) -> bytes:
    """An XPS package of FixedPage bodies, Pages/1.fpage and on; the document lists them in
    order (page numbers), and without chain the package does not name its document at all."""
    members: dict[str, str | bytes] = {
        f"Documents/1/Pages/{n}.fpage": f'<FixedPage {XPS_NS} Width="816">{body}</FixedPage>'
        for n, body in enumerate(pages, 1)
    }
    if chain:
        contents = "".join(
            f'<PageContent Source="Pages/{n}.fpage"/>' for n in order or range(1, len(pages) + 1)
        )
        members["Documents/1/FixedDocument.fdoc"] = (
            f"<FixedDocument {XPS_NS}>{contents}</FixedDocument>"
        )
        members["FixedDocSeq.fdseq"] = (
            f'<FixedDocumentSequence {XPS_NS}><DocumentReference Source="Documents/1/'
            'FixedDocument.fdoc"/></FixedDocumentSequence>'
        )
        ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        kind = "http://schemas.microsoft.com/xps/2005/06/fixedrepresentation"
        members["_rels/.rels"] = (
            f'<Relationships xmlns="{ns}"><Relationship Id="R0" Type="{kind}"'
            ' Target="/FixedDocSeq.fdseq"/></Relationships>'
        )
    return package(members)


def glyphs(text: str, baseline: int) -> str:
    """One run of XPS text on a baseline."""
    value = html.escape(text, quote=True)
    return (
        f'<Glyphs OriginX="96" OriginY="{baseline}" FontRenderingEmSize="12"'
        f' UnicodeString="{value}"/>'
    )


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

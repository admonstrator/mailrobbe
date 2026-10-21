"""Small documents and media for the preview tests, built here (no fixtures on disk)."""

import io
import struct
import wave
import zipfile
import zlib
from collections.abc import Mapping
from xml.sax.saxutils import escape

from tests.attachments.extract.samples import package

REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DOCX_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    f'xmlns:r="{REL}" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
)
ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)
ODT_MIME = "application/vnd.oasis.opendocument.text"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EMF = b"\x01\x00\x00\x00\x6c\x00\x00\x00" + bytes(100)  # an EMF record header
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect/></svg>'
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + bytes(64)


def png(width: int = 4, height: int = 3) -> bytes:
    """A valid PNG of red pixels."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def wav(frames: int = 8000) -> bytes:
    """A second of 8 kHz mono sound."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(bytes(i * 7 % 251 for i in range(2 * frames)))
    return buffer.getvalue()


# DOCX


def run(text: str, *properties: str) -> str:
    props = f"<w:rPr>{''.join(properties)}</w:rPr>" if properties else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def para(*runs: str, style: str | None = None) -> str:
    head = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{head}{''.join(runs)}</w:p>"


def drawing(relationship: str, alt: str = "", *, linked: bool = False) -> str:
    blip = f'<a:blip r:{"link" if linked else "embed"}="{relationship}"/>'
    return (
        f'<w:r><w:drawing><wp:inline><wp:docPr id="1" name="Bild" descr="{escape(alt)}"/>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f"<pic:pic><pic:blipFill>{blip}</pic:blipFill></pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r>"
    )


def relationships(*items: tuple[str, str, str, bool]) -> str:
    """(id, kind, target, external) as a relationships part."""
    entries = "".join(
        f'<Relationship Id="{rid}" Type="{REL}/{kind}" Target="{escape(target)}"'
        + (' TargetMode="External"/>' if external else "/>")
        for rid, kind, target, external in items
    )
    ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    return f'<?xml version="1.0"?><Relationships xmlns="{ns}">{entries}</Relationships>'


def docx(
    body: str,
    *,
    related: tuple[tuple[str, str, str, bool], ...] = (),
    parts: Mapping[str, str | bytes] | None = None,
    main: str = "word/document.xml",
) -> bytes:
    """A DOCX with this body XML, relationships of the main part and further parts (by member
    name)."""
    folder, _, name = main.rpartition("/")
    return package(
        {
            "[Content_Types].xml": "<Types/>",
            "_rels/.rels": relationships(("rId1", "officeDocument", main, False)),
            main: f"<w:document {DOCX_NS}><w:body>{body}</w:body></w:document>",
            f"{folder}/_rels/{name}.rels": relationships(*related),
            **(parts or {}),
        }
    )


def footnotes(*texts: str) -> str:
    notes = "".join(
        f'<w:footnote w:id="{number}">{para(run(text))}</w:footnote>'
        for number, text in enumerate(texts, 1)
    )
    return f"<w:footnotes {DOCX_NS}>{notes}</w:footnotes>"


# ODT


def odt(
    body: str,
    *,
    automatic: str = "",
    styles: str = "",
    files: Mapping[str, str | bytes] | None = None,
    manifest: str = "",
) -> bytes:
    """An ODT with this office:text content, automatic styles of content.xml, styles of
    styles.xml and further members."""
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ODF_NS}>'
        f"<office:automatic-styles>{automatic}</office:automatic-styles>"
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )
    members: dict[str, str | bytes] = {"content.xml": content}
    if styles:
        members["styles.xml"] = (
            f"<office:document-styles {ODF_NS}><office:styles>{styles}</office:styles>"
            "</office:document-styles>"
        )
    if manifest:
        members["META-INF/manifest.xml"] = manifest
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", ODT_MIME, zipfile.ZIP_STORED)  # first and stored, as ODF wants
        for name, data in {**members, **(files or {})}.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def text_style(name: str, family: str = "text", parent: str = "", **properties: str) -> str:
    """A style:style with fo or style text properties, e.g. font_weight="bold"."""
    attrs = ""
    for key, value in properties.items():
        prefix = "style" if key.startswith("text_underline") else "fo"
        attrs += f' {prefix}:{key.replace("_", "-")}="{value}"'
    parent_attr = f' style:parent-style-name="{parent}"' if parent else ""
    return (
        f'<style:style style:name="{name}" style:family="{family}"{parent_attr}>'
        f"<style:text-properties{attrs}/></style:style>"
    )

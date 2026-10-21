"""Small files with metadata, built in the tests from bytes (no fixtures on disk): TIFF structures
with EXIF and GPS, JPEG, PNG, WebP, PDF with incremental updates, DOCX, XLSX and ODT."""

import struct
import zlib
from collections.abc import Sequence

from tests.attachments.extract.samples import package

Entry = tuple[int, int, int, bytes]  # tag, type, count, value bytes

XMP_NS = b"http://ns.adobe.com/xap/1.0/\x00"


def ascii_(tag: int, value: str) -> Entry:
    data = value.encode() + b"\x00"
    return (tag, 2, len(data), data)


def byte(tag: int, *values: int) -> Entry:
    return (tag, 1, len(values), bytes(values))


def undefined(tag: int, data: bytes) -> Entry:
    return (tag, 7, len(data), data)


def rational(tag: int, *pairs: tuple[int, int], endian: str = "<") -> Entry:
    data = b"".join(struct.pack(f"{endian}II", n, d) for n, d in pairs)
    return (tag, 5, len(pairs), data)


def _size(entries: Sequence[Entry]) -> int:
    extra = sum(len(value) + len(value) % 2 for *_, value in entries if len(value) > 4)
    return 2 + 12 * len(entries) + 4 + extra


def _directory(entries: Sequence[Entry], start: int, endian: str) -> bytes:
    table = struct.pack(f"{endian}H", len(entries))
    data = b""
    data_at = start + 2 + 12 * len(entries) + 4
    for tag, kind, count, value in sorted(entries):
        if len(value) <= 4:
            field = value.ljust(4, b"\x00")
        else:
            field = struct.pack(f"{endian}I", data_at + len(data))
            data += value + b"\x00" * (len(value) % 2)
        table += struct.pack(f"{endian}HHI", tag, kind, count) + field
    return table + struct.pack(f"{endian}I", 0) + data


def tiff(
    ifd0: Sequence[Entry],
    exif: Sequence[Entry] = (),
    gps: Sequence[Entry] = (),
    endian: str = "<",
) -> bytes:
    """A TIFF structure: IFD0, then the Exif IFD and the GPS IFD it points to, if any."""
    first = list(ifd0)
    if exif:
        first.append((0x8769, 4, 1, b"\x00" * 4))
    if gps:
        first.append((0x8825, 4, 1, b"\x00" * 4))
    exif_at = 8 + _size(first)
    gps_at = exif_at + (_size(exif) if exif else 0)
    pointers = {0x8769: exif_at, 0x8825: gps_at}
    first = [
        (tag, kind, count, struct.pack(f"{endian}I", pointers[tag]) if tag in pointers else value)
        for tag, kind, count, value in first
    ]
    header = (b"II*\x00" if endian == "<" else b"MM\x00*") + struct.pack(f"{endian}I", 8)
    body = _directory(first, 8, endian)
    if exif:
        body += _directory(exif, exif_at, endian)
    if gps:
        body += _directory(gps, gps_at, endian)
    return header + body


def camera_tiff(endian: str = "<") -> bytes:
    """A camera's EXIF: make, model, software, dates with offsets, artist, serial, lens, GPS
    52°31'12.3"N 13°24'36"E at 34.5 m on 2024-05-06 08:09:10 UTC."""
    ifd0 = [
        ascii_(0x010F, "Canon"),
        ascii_(0x0110, "Canon EOS R6"),
        ascii_(0x0131, "Firmware 1.8.1"),
        ascii_(0x0132, "2024:05-06 10:00:00"),  # broken: kept as found
        ascii_(0x013B, "Peter Hofmann"),
        ascii_(0x8298, "Peter Hofmann\x00Redaktion"),
        byte(0x9C9D, *"Peter H.".encode("utf-16-le"), 0, 0),
    ]
    exif = [
        ascii_(0x9003, "2024:05:06 10:09:10"),
        ascii_(0x9011, "+02:00"),
        ascii_(0x9004, "2024:05:06 10:09:10"),
        ascii_(0xA431, "032021001234"),
        ascii_(0xA434, "RF24-105mm F4 L IS USM"),
        ascii_(0xA430, "Redaktion Nord"),
        undefined(0x9286, b"ASCII\x00\x00\x00Probe am Hafen   "),
    ]
    gps = [
        ascii_(1, "N"),
        rational(2, (52, 1), (31, 1), (123, 10), endian=endian),
        ascii_(3, "E"),
        rational(4, (13, 1), (24, 1), (36, 1), endian=endian),
        byte(5, 0),
        rational(6, (345, 10), endian=endian),
        rational(7, (8, 1), (9, 1), (10, 1), endian=endian),
        ascii_(0x1D, "2024:05:06"),
    ]
    return tiff(ifd0, exif, gps, endian)


def segment(marker: int, body: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body


def jpeg(*segments: bytes) -> bytes:
    """SOI, a JFIF APP0, the segments, a scan and EOI."""
    jfif = segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    scan = segment(0xDA, b"\x00" * 10) + b"\x12\x34\xff\x00\x56"
    return b"\xff\xd8" + jfif + b"".join(segments) + scan + b"\xff\xd9"


def exif_segment(data: bytes) -> bytes:
    return segment(0xE1, b"Exif\x00\x00" + data)


def xmp_packet(body: str) -> bytes:
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f"{body}</rdf:RDF></x:xmpmeta>"
        '<?xpacket end="w"?>'
    ).encode()


XMP_DESCRIPTION = (
    '<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:pdf="http://ns.adobe.com/pdf/1.3/" '
    'xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/" '
    'xmlns:stEvt="http://ns.adobe.com/xap/1.0/sType/ResourceEvent#" '
    'xmp:CreatorTool="Adobe InDesign 18.2" xmp:CreateDate="2024-05-06T10:09:10+02:00">'
    "<xmp:ModifyDate>2024-05-07T08:00:00Z</xmp:ModifyDate>"
    "<pdf:Producer>Adobe PDF Library 17.0</pdf:Producer>"
    "<dc:creator><rdf:Seq><rdf:li>Peter Hofmann</rdf:li><rdf:li>Anna Berg</rdf:li></rdf:Seq>"
    "</dc:creator>"
    '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Spendenliste</rdf:li></rdf:Alt></dc:title>'
    "<xmpMM:DocumentID>xmp.did:1234</xmpMM:DocumentID>"
    "<xmpMM:InstanceID>uuid:5678</xmpMM:InstanceID>"
    "<xmpMM:History><rdf:Seq>"
    '<rdf:li stEvt:action="created" stEvt:softwareAgent="Adobe InDesign 18.2"/>'
    '<rdf:li rdf:parseType="Resource"><stEvt:action>saved</stEvt:action>'
    "<stEvt:softwareAgent>Adobe Photoshop 25.0</stEvt:softwareAgent></rdf:li>"
    "</rdf:Seq></xmpMM:History>"
    "</rdf:Description>"
)


def chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(data, zlib.crc32(kind))
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png(*chunks: bytes) -> bytes:
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    image = chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
    return b"\x89PNG\r\n\x1a\n" + header + image + b"".join(chunks) + chunk(b"IEND", b"")


def webp(*chunks: tuple[bytes, bytes]) -> bytes:
    body = b"WEBP" + b"VP8L" + struct.pack("<I", 5) + b"\x2f\x00\x00\x00\x00\x00"
    for kind, data in chunks:
        body += kind + struct.pack("<I", len(data)) + data + b"\x00" * (len(data) % 2)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def pdf(
    info: str,
    *,
    xmp: bytes | None = None,
    updates: Sequence[str] = (),
    embedded: Sequence[str] = (),
    linearized: bool = False,
) -> bytes:
    """A one-page PDF with this information dictionary (the inside of << >>), an XMP stream,
    embedded files of these names, and an incremental update per entry of `updates`, each
    writing the information dictionary again."""
    objects: dict[int, bytes] = {}
    names = b" ".join(b"(%s) %d 0 R" % (name.encode(), 10 + i) for i, name in enumerate(embedded))
    catalog = b"<< /Type /Catalog /Pages 2 0 R"
    if xmp is not None:
        catalog += b" /Metadata 4 0 R"
    if embedded:
        catalog += b" /Names << /EmbeddedFiles << /Names [" + names + b"] >> >>"
    objects[1] = catalog + b" >>"
    objects[2] = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    objects[3] = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>"
    if xmp is not None:
        objects[4] = (
            b"<< /Type /Metadata /Subtype /XML /Length %d >>\nstream\n" % len(xmp)
            + xmp
            + b"\nendstream"
        )
    for index, name in enumerate(embedded):
        objects[10 + index] = b"<< /Type /Filespec /F (%s) /EF << /F %d 0 R >> >>" % (
            name.encode(),
            20 + index,
        )
        objects[20 + index] = b"<< /Type /EmbeddedFile /Length 5 >>\nstream\nhallo\nendstream"
    objects[5] = b"<< " + info.encode("latin-1") + b" >>"
    head = b"%PDF-1.7\n"
    if linearized:
        head += b"6 0 obj\n<< /Linearized 1 >>\nendobj\n"
    out = bytearray(head + b"%\xe2\xe3\xcf\xd3\n")
    size = max(objects) + 1
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + objects[number] + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for number in range(1, size):
        if number in offsets:
            out += b"%010d 00000 n \n" % offsets[number]
        else:
            out += b"0000000000 65535 f \n"
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        size,
        xref,
    )
    for update in updates:
        at = len(out)
        out += b"5 0 obj\n<< " + update.encode("latin-1") + b" >>\nendobj\n"
        previous, xref = xref, len(out)
        out += b"xref\n0 1\n0000000000 65535 f \n5 1\n%010d 00000 n \n" % at
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R /Prev %d >>\n" % (size, previous)
        out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
CORE = (
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
    'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    "<dc:title>Protokoll</dc:title><dc:creator>Peter Hofmann</dc:creator>"
    "<cp:lastModifiedBy>Anna Berg</cp:lastModifiedBy><cp:revision>7</cp:revision>"
    "<cp:lastPrinted>2024-05-01T09:00:00Z</cp:lastPrinted>"
    '<dcterms:created xsi:type="dcterms:W3CDTF">2024-04-30T08:15:00Z</dcterms:created>'
    '<dcterms:modified xsi:type="dcterms:W3CDTF">2024-05-02T17:45:30Z</dcterms:modified>'
    "</cp:coreProperties>"
)
APP = (
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
    ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    "<Template>Normal.dotm</Template><TotalTime>95</TotalTime><Pages>3</Pages>"
    "<Application>Microsoft Office Word</Application><AppVersion>16.0000</AppVersion>"
    "<Company>Verein Nord e.V.</Company>"
    '<TitlesOfParts><vt:vector size="1" baseType="lpstr"><vt:lpstr>Protokoll</vt:lpstr>'
    "</vt:vector></TitlesOfParts></Properties>"
)


def docx(body: str, comments: Sequence[str] = ()) -> bytes:
    """A DOCX with the core and app properties above, this body and comments by these
    authors."""
    root_rels = (
        f'<Relationships xmlns="{PR}">'
        f'<Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
        'relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        f'<Relationship Id="rId3" Type="{R}/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )
    members: dict[str, str | bytes] = {
        "_rels/.rels": root_rels,
        "word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>",
        "docProps/core.xml": CORE,
        "docProps/app.xml": APP,
    }
    if comments:
        members["word/_rels/document.xml.rels"] = (
            f'<Relationships xmlns="{PR}"><Relationship Id="rId9" Type="{R}/comments" '
            'Target="comments.xml"/></Relationships>'
        )
        members["word/comments.xml"] = (
            f"<w:comments {W}>"
            + "".join(
                f'<w:comment w:id="{i}" w:author="{author}"><w:p><w:r><w:t>Notiz</w:t></w:r>'
                "</w:p></w:comment>"
                for i, author in enumerate(comments)
            )
            + "</w:comments>"
        )
    return package(members)


def xlsx() -> bytes:
    """An XLSX with only its properties, found by their usual names."""
    return package(
        {
            "xl/workbook.xml": "<workbook/>",
            "docProps/core.xml": CORE,
            "docProps/app.xml": APP.replace("Microsoft Office Word", "Microsoft Excel"),
        }
    )


ODF_META = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xlink="http://www.w3.org/1999/xlink"'
)


def odt(meta: str) -> bytes:
    return package(
        {
            "mimetype": "application/vnd.oasis.opendocument.text",
            "content.xml": "<office:document-content/>",
            "meta.xml": (
                f"<office:document-meta {ODF_META}><office:meta>{meta}</office:meta>"
                "</office:document-meta>"
            ),
        },
        deflate=False,
    )

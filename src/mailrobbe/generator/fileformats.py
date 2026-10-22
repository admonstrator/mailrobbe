"""Byte writers for generated documents (D77): PDF, DOCX, XLSX, PPTX, ODT, ZIP, and pictures
(PNG, JPEG) and recordings (D125).

Written by hand, small and deterministic: the same arguments give the same bytes (ZIP entries
carry the document's own date, never the clock; deflate output is that of the local zlib).
Each file is as small as a valid file of its format gets, and filler (an embedded picture, or
an unreferenced PDF stream) brings it to about the planned attachment size, so archives keep
realistic byte volumes while the text stays what the extractors must find. Filler is a short
random part of its own and then one fixed block of noise repeated, which encode_base64 finds and
encodes once, as the renderer does for the attachments that are filler only.

PDF: Helvetica with WinAnsiEncoding, so German text (umlauts, euro sign, quotes) reads back
as written; content streams are deflated. Encrypted PDFs use the standard security handler,
revision 4 with AES-128 (AESV2), with a user password, as Acrobat writes them. Scanned PDFs
have pages that show only an image.

Pictures: PNGs drawn here, JPEGs from the photos in media/, some with the EXIF of a phone or
camera and its GPS position (exif_segment); noise where every decoder skips it (a private PNG
chunk, JPEG comment segments) brings them to the planned size and makes each one a file of its
own. Recordings are the files in media/ as they are, made once with ffmpeg from
synthetic sources (media/README.md).
"""

import base64
import functools
import hashlib
import io
import random
import struct
import zipfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from mailrobbe.generator.model import PhotoGps

Table = Sequence[Sequence[str | float]]  # rows of cells; floats are amounts (numbers in XLSX)


@dataclass(frozen=True, slots=True)
class Para:
    """A paragraph of a text document."""

    text: str
    style: str = "text"  # "title", "heading" or "text"


Block = Para | Table

_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


_LINE = 57  # bytes per base64 line of 76 characters
_BLOCK = _LINE * 1024
_NOISE = random.Random("fileformats:noise").randbytes(_BLOCK)
_OWN = _LINE * 16  # random bytes of each filler's own, in front of the repeated block
_PROBE = _NOISE[:64]


def filler(rng: random.Random, size: int, magic: bytes = _PNG) -> bytes:
    """`size` bytes of picture-like noise behind a magic number."""
    own = (magic + rng.randbytes(_OWN))[:size]
    rest = size - len(own)
    if rest <= 0:
        return own
    repeats, tail = divmod(rest, _BLOCK)
    return b"".join((own, _NOISE * repeats, _NOISE[:tail]))


_ROTATIONS: dict[int, bytes] = {}


def _rotated(shift: int) -> bytes:
    """Base64 lines of the noise block rotated by `shift` bytes (it starts `shift` bytes in)."""
    found = _ROTATIONS.get(shift)
    if found is None:
        found = _ROTATIONS[shift] = base64.encodebytes(_NOISE[shift:] + _NOISE[:shift])
    return found


def encode_base64(data: bytes) -> tuple[bytes, ...]:
    """base64.encodebytes(data) as pieces whose concatenation is the same, the repeated noise
    blocks of filler encoded once and referenced again."""
    pieces: list[bytes] = []
    done = 0  # bytes encoded so far; always a multiple of _LINE until the last piece
    while (found := data.find(_PROBE, done)) >= 0:
        start = found + (-found) % _LINE  # the first line start inside the noise
        period = _NOISE[start - found :] + _NOISE[: start - found]
        end = start
        while data[end : end + _BLOCK] == period:
            end += _BLOCK
        if end == start:
            break
        pieces.append(base64.encodebytes(data[done:start]))
        pieces += [_rotated(start - found)] * ((end - start) // _BLOCK)
        done = end
    pieces.append(base64.encodebytes(data[done:]))
    return tuple(piece for piece in pieces if piece)


def amount_text(value: float) -> str:
    """1234.5 -> '1.234,50' (German notation, as people type amounts)."""
    text = f"{value:,.2f}"
    return text.replace(",", " ").replace(".", ",").replace(" ", ".")


def number_text(value: float) -> str:
    """An amount as a spreadsheet stores it in <v>: 1234.5 -> '1234.5'."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def cell_text(cell: str | float) -> str:
    return cell if isinstance(cell, str) else amount_text(cell)


# PDF ----------------------------------------------------------------------------------------

_PAD = bytes.fromhex("28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a")
_PERMISSIONS = -3904  # print, copy, annotate: what Acrobat sets by default


def _pdf_string(text: str) -> bytes:
    data = text.encode("cp1252", "replace")
    return b"(" + data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _page_stream(lines: Sequence[str], first: bool) -> bytes:
    ops = [b"BT", b"56 786 Td", b"14 TL"]
    for number, line in enumerate(lines):
        font = b"/F2 13 Tf" if first and number == 0 else b"/F1 10 Tf"
        ops.append(font + b" " + _pdf_string(line) + b" Tj T*")
    ops.append(b"ET")
    return b"\n".join(ops)


def _rc4(key: bytes, data: bytes) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]
    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        out.append(byte ^ state[(state[i] + state[j]) % 256])
    return bytes(out)


class _Security:
    """Standard security handler, revision 4, AES-128 for streams (PDF 1.6, 7.6.3)."""

    def __init__(self, user: str, owner: str, file_id: bytes, rng: random.Random) -> None:
        self.file_id = file_id
        self._rng = rng
        user_pad = (user.encode("latin-1") + _PAD)[:32]
        owner_key = hashlib.md5((owner.encode("latin-1") + _PAD)[:32]).digest()
        for _ in range(50):
            owner_key = hashlib.md5(owner_key).digest()
        o_value = _rc4(owner_key, user_pad)
        for i in range(1, 20):
            o_value = _rc4(bytes(b ^ i for b in owner_key), o_value)
        permissions = (_PERMISSIONS & 0xFFFFFFFF).to_bytes(4, "little")
        key = hashlib.md5(user_pad + o_value + permissions + file_id).digest()
        for _ in range(50):
            key = hashlib.md5(key).digest()
        self._key = key
        u_value = _rc4(key, hashlib.md5(_PAD + file_id).digest())
        for i in range(1, 20):
            u_value = _rc4(bytes(b ^ i for b in key), u_value)
        u_value += rng.randbytes(16)
        self.dictionary = (
            b"<< /Filter /Standard /V 4 /R 4 /Length 128 /P %d "
            b"/CF << /StdCF << /CFM /AESV2 /AuthEvent /DocOpen /Length 16 >> >> "
            b"/StmF /StdCF /StrF /StdCF /O <%s> /U <%s> >>"
            % (_PERMISSIONS, o_value.hex().encode(), u_value.hex().encode())
        )

    def encrypt(self, number: int, data: bytes) -> bytes:
        salt = number.to_bytes(3, "little") + b"\x00\x00sAlT"
        key = hashlib.md5(self._key + salt).digest()
        iv = self._rng.randbytes(16)
        padder = padding.PKCS7(128).padder()
        plain = padder.update(data) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return iv + encryptor.update(plain) + encryptor.finalize()


def _stream(dictionary: bytes, data: bytes) -> bytes:
    return dictionary[:-2] + b"/Length %d >>\nstream\n" % len(data) + data + b"\nendstream"


def pdf(
    pages: Sequence[Sequence[str]],
    rng: random.Random,
    *,
    size: int = 0,
    password: str | None = None,
    images: Sequence[int] = (),
) -> bytes:
    """A PDF with one page per entry of `pages` (lines of text, the first one bold on page 1).

    `images` gives, per page, the size of a picture the page shows instead of text (scans);
    `password` encrypts the file with that user password; an unreferenced stream of noise
    brings the file to about `size` bytes.
    """
    file_id = rng.randbytes(16)
    security = None
    if password is not None:
        owner = f"{rng.getrandbits(64):016x}"
        security = _Security(password, owner, file_id, rng)
    count = max(len(pages), len(images))
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>",
    }
    kids = []
    number = 5
    for index in range(count):
        page, content = number, number + 1
        number += 2
        kids.append(b"%d 0 R" % page)
        if images:
            image = number
            number += 1
            picture = filler(rng, images[index], _JPEG)
            objects[image] = _stream(
                b"<< /Type /XObject /Subtype /Image /Width 1240 /Height 1754 "
                b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode >>",
                security.encrypt(image, picture) if security else picture,
            )
            data = b"q 595 0 0 842 0 0 cm /Im1 Do Q"
            resources = b"/XObject << /Im1 %d 0 R >>" % image
        else:
            data = _page_stream(pages[index], index == 0)
            resources = b"/Font << /F1 3 0 R /F2 4 0 R >>"
        data = zlib.compress(data)
        if security:
            data = security.encrypt(content, data)
        objects[content] = _stream(b"<< /Filter /FlateDecode >>", data)
        objects[page] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << " + resources + b" >> /Contents %d 0 R >>" % content
        )
    objects[2] = b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count %d >>" % count
    encrypt_ref = b""
    if security:
        objects[number] = security.dictionary
        encrypt_ref = b" /Encrypt %d 0 R" % number
        number += 1
    written = sum(len(body) + 24 for body in objects.values()) + 20 * number + 220
    pad = size - written - 100
    if pad > 0:
        noise = filler(rng, pad, b"")
        objects[number] = _stream(b"<< >>", security.encrypt(number, noise) if security else noise)
        number += 1
    out = bytearray(b"%PDF-1.6\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for key in sorted(objects):
        offsets[key] = len(out)
        out += b"%d 0 obj\n" % key + objects[key] + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % number
    for key in range(1, number):
        out += b"%010d 00000 n \n" % offsets[key]
    ident = file_id.hex().encode()
    out += b"trailer\n<< /Size %d /Root 1 0 R%s /ID [<%s> <%s>] >>\nstartxref\n%d\n%%%%EOF\n" % (
        number,
        encrypt_ref,
        ident,
        ident,
        xref,
    )
    return bytes(out)


# ZIP containers -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Picture:
    """The last member of a ZIP, stored noise (PNG, or JPEG by its name) sized so that the
    archive comes to `size` bytes; at least `least` bytes, left out at 0."""

    name: str
    size: int
    rng: random.Random
    least: int = 0


_ZIP_ENTRY = 30 + 46  # local header and central directory entry, without the name
_ZIP_END = 22


def zip_bytes(
    members: Sequence[tuple[str, bytes, bool]], when: datetime, picture: Picture | None = None
) -> bytes:
    """A ZIP of (name, data, deflate) members, every entry dated `when`; names ending in "/"
    are folders."""
    return zip_archive(members, when, picture)[0]


def zip_archive(
    members: Sequence[tuple[str, bytes, bool]],
    when: datetime,
    picture: Picture | None = None,
    *,
    password: str | None = None,
    rng: random.Random | None = None,
) -> tuple[bytes, list[tuple[str, bytes]]]:
    """zip_bytes, and the files it holds as (name, data), the picture included. With a
    password every file entry is encrypted with the traditional PKWARE encryption (folders stay
    plain), its 12-byte header drawn from `rng`."""
    stamp = (
        max(when.year, 1980),
        when.month,
        when.day,
        when.hour,
        when.minute,
        when.second // 2 * 2,
    )
    if password is not None:
        assert rng is not None, "an encrypted ZIP draws its headers from rng"
        return _encrypted_zip(members, stamp, picture, password.encode("ascii"), rng)

    files: list[tuple[str, bytes]] = []

    def add(archive: zipfile.ZipFile, name: str, data: bytes, deflate: bool) -> None:
        info = zipfile.ZipInfo(name, date_time=stamp)
        info.create_system = 0
        info.external_attr = 0x10 if name.endswith("/") else 0
        info.compress_type = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
        archive.writestr(info, data)
        if not name.endswith("/"):
            files.append((name, data))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data, deflate in members:
            add(archive, name, data, deflate)
        if picture is not None:
            central = sum(
                46 + len(info.filename.encode()) + len(info.extra) for info in archive.infolist()
            )
            used = buffer.tell() + central + _ZIP_END
            length = picture.size - used - _ZIP_ENTRY - 2 * len(picture.name.encode())
            length = max(length, picture.least)
            if length > 0:
                add(archive, picture.name, _picture_bytes(picture, length), False)
    return buffer.getvalue(), files


def _picture_bytes(picture: Picture, length: int) -> bytes:
    magic = _JPEG if picture.name.endswith((".jpg", ".jpeg")) else _PNG
    return filler(picture.rng, length, magic)


# Traditional PKWARE encryption (APPNOTE.TXT 6.1), the counterpart of zipfile's _ZipDecrypter.
_CRC_TABLE = tuple(
    functools.reduce(lambda c, _: (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1, range(8), n)
    for n in range(256)
)
_ENCRYPTION_HEADER = 12


class _ZipCrypto:
    def __init__(self, password: bytes) -> None:
        self._keys = [0x12345678, 0x23456789, 0x34567890]
        for byte in password:
            self._update(byte)

    def _update(self, byte: int) -> None:
        keys = self._keys
        keys[0] = (keys[0] >> 8) ^ _CRC_TABLE[(keys[0] ^ byte) & 0xFF]
        keys[1] = ((keys[1] + (keys[0] & 0xFF)) * 134775813 + 1) & 0xFFFFFFFF
        keys[2] = (keys[2] >> 8) ^ _CRC_TABLE[(keys[2] ^ (keys[1] >> 24)) & 0xFF]

    def encrypt(self, data: bytes) -> bytes:
        k0, k1, k2 = self._keys
        table = _CRC_TABLE
        out = bytearray(len(data))
        for index, byte in enumerate(data):
            mixed = k2 | 2
            out[index] = byte ^ ((mixed * (mixed ^ 1)) >> 8) & 0xFF
            k0 = (k0 >> 8) ^ table[(k0 ^ byte) & 0xFF]
            k1 = ((k1 + (k0 & 0xFF)) * 134775813 + 1) & 0xFFFFFFFF
            k2 = (k2 >> 8) ^ table[(k2 ^ (k1 >> 24)) & 0xFF]
        self._keys = [k0, k1, k2]
        return bytes(out)


def _encrypted_zip(
    members: Sequence[tuple[str, bytes, bool]],
    stamp: tuple[int, int, int, int, int, int],
    picture: Picture | None,
    password: bytes,
    rng: random.Random,
) -> tuple[bytes, list[tuple[str, bytes]]]:
    """The ZIP written by hand, as zipfile lays it out, with every file entry encrypted."""
    year, month, day, hour, minute, second = stamp
    dos_time = hour << 11 | minute << 5 | second // 2
    dos_date = (year - 1980) << 9 | month << 5 | day
    entries = list(members)
    if picture is not None:
        names = [*(name for name, _, _ in entries), picture.name]
        files = sum(not name.endswith("/") for name in names)
        used = sum(_ZIP_ENTRY + 2 * len(name.encode()) for name, _, _ in entries) + _ZIP_END
        used += _ENCRYPTION_HEADER * files
        used += sum(len(_compressed(data, deflate)) for _, data, deflate in entries)
        length = picture.size - used - _ZIP_ENTRY - 2 * len(picture.name.encode())
        length = max(length, picture.least)
        if length > 0:
            entries.append((picture.name, _picture_bytes(picture, length), False))
    out = bytearray()
    central = bytearray()
    found: list[tuple[str, bytes]] = []
    for name, data, deflate in entries:
        raw_name = name.encode()
        folder = name.endswith("/")
        flags = (0 if raw_name.isascii() else 0x800) | (0 if folder else 1)
        method = zipfile.ZIP_DEFLATED if deflate and not folder else zipfile.ZIP_STORED
        crc = zlib.crc32(data)
        payload = _compressed(data, method == zipfile.ZIP_DEFLATED)
        if not folder:
            header = rng.randbytes(_ENCRYPTION_HEADER - 1) + bytes([crc >> 24])
            payload = _ZipCrypto(password).encrypt(header + payload)
            found.append((name, data))
        fields = (20, flags, method, dos_time, dos_date, crc, len(payload), len(data))
        offset = len(out)
        out += struct.pack("<4s5HL2L2H", b"PK\x03\x04", *fields, len(raw_name), 0)
        out += raw_name + payload
        central += struct.pack(
            "<4s6HL2L5HLL", b"PK\x01\x02", 20, *fields, len(raw_name), 0, 0, 0, 0,
            0x10 if folder else 0, offset,
        )  # fmt: skip
        central += raw_name
    count = len(entries)
    out += central + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, count, count, len(central),
                                 len(out), 0)  # fmt: skip
    return bytes(out), found


def _compressed(data: bytes, deflate: bool) -> bytes:
    """Deflate as zipfile writes it (default level, raw stream), or the data as it is."""
    if not deflate:
        return data
    compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    return compressor.compress(data) + compressor.flush()


_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_W3CDTF = "%Y-%m-%dT%H:%M:%SZ"


def _t(text: str) -> str:
    space = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
    return f"<w:t{space}>{escape(text)}</w:t>"


def _core(title: str, author: str, when: datetime) -> bytes:
    stamp = when.strftime(_W3CDTF)
    return (
        _XML + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
        'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>"
        f"<cp:lastModifiedBy>{escape(author)}</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified>'
        "</cp:coreProperties>"
    ).encode()


_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT = "application/vnd.openxmlformats-officedocument."


def _rels(*targets: tuple[str, str]) -> bytes:
    items = "".join(
        f'<Relationship Id="rId{n}" Type="{kind}" Target="{target}"/>'
        for n, (kind, target) in enumerate(targets, 1)
    )
    return (_XML + f'<Relationships xmlns="{_PKG_REL}">{items}</Relationships>').encode()


def _types(overrides: Sequence[tuple[str, str]]) -> bytes:
    items = "".join(f'<Override PartName="/{p}" ContentType="{c}"/>' for p, c in overrides)
    return (
        _XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Default Extension="jpeg" ContentType="image/jpeg"/>'
        f"{items}"
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>'
    ).encode()


def _root_rels(main: str) -> bytes:
    return _rels(
        (f"{_REL}/officeDocument", main),
        ("http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
         "docProps/core.xml"),
    )  # fmt: skip


# DOCX ---------------------------------------------------------------------------------------


def _w_paragraph(style: str, text: str) -> str:
    props = {"title": "Title", "heading": "Heading1"}.get(style)
    head = f'<w:pPr><w:pStyle w:val="{props}"/></w:pPr>' if props else ""
    runs = "<w:r><w:tab/></w:r>".join(f"<w:r>{_t(part)}</w:r>" for part in text.split("\t"))
    return f"<w:p>{head}{runs}</w:p>"


def _w_table(table: Table) -> str:
    rows = "".join(
        "<w:tr>"
        + "".join(f"<w:tc><w:p><w:r>{_t(cell_text(c))}</w:r></w:p></w:tc>" for c in row)
        + "</w:tr>"
        for row in table
    )
    return (
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/>'
        f"</w:tblPr>{rows}</w:tbl>"
    )


_W = f'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="{_REL}"'


def docx(
    body: Sequence[Block],
    *,
    title: str,
    author: str,
    when: datetime,
    header: str,
    footer: str,
    size: int,
    rng: random.Random,
) -> bytes:
    """A Word document: paragraphs and tables in order, a header and a footer; about `size`
    bytes with its picture."""
    parts = "".join(
        _w_paragraph(item.style, item.text) if isinstance(item, Para) else _w_table(item)
        for item in body
    )
    section = (
        '<w:sectPr><w:headerReference w:type="default" r:id="rId1"/>'
        '<w:footerReference w:type="default" r:id="rId2"/>'
        '<w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
    )
    document = f"{_XML}<w:document {_W}><w:body>{parts}{section}</w:body></w:document>"
    margin = {"header": header, "footer": footer}
    members = [
        (
            "[Content_Types].xml",
            _types(
                [
                    ("word/document.xml", f"{_CT}wordprocessingml.document.main+xml"),
                    ("word/header1.xml", f"{_CT}wordprocessingml.header+xml"),
                    ("word/footer1.xml", f"{_CT}wordprocessingml.footer+xml"),
                ]
            ),
            True,
        ),
        ("_rels/.rels", _root_rels("word/document.xml"), True),
        ("docProps/core.xml", _core(title, author, when), True),
        ("word/document.xml", document.encode(), True),
        (
            "word/_rels/document.xml.rels",
            _rels(
                (f"{_REL}/header", "header1.xml"),
                (f"{_REL}/footer", "footer1.xml"),
                (f"{_REL}/image", "media/image1.png"),
            ),
            True,
        ),
    ]
    for kind, text in margin.items():
        element = "hdr" if kind == "header" else "ftr"
        xml = f"{_XML}<w:{element} {_W}>{_w_paragraph('text', text)}</w:{element}>"
        members.append((f"word/{kind}1.xml", xml.encode(), True))
    return zip_bytes(members, when, Picture("word/media/image1.png", size, rng, 64))


# XLSX ---------------------------------------------------------------------------------------

_STYLES_XLSX = (
    _XML + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00\\ &quot;€&quot;"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    "</styleSheet>"
)
_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def xlsx(
    sheets: Sequence[tuple[str, Table]],
    *,
    title: str,
    author: str,
    when: datetime,
    size: int,
    rng: random.Random,
) -> bytes:
    """A workbook: strings as shared strings (some inline), amounts as numbers; about `size`
    bytes with a picture."""
    strings: dict[str, int] = {}
    sheet_xml = []
    for _, table in sheets:
        rows = []
        for r, row in enumerate(table, 1):
            cells = []
            for c, cell in enumerate(row):
                ref = f"{_column_name(c)}{r}"
                if isinstance(cell, float):
                    cells.append(f'<c r="{ref}" s="1"><v>{number_text(cell)}</v></c>')
                elif not cell:
                    continue
                elif r > 1 and rng.random() < 0.1:  # some programs write inline strings
                    cells.append(f'<c r="{ref}" t="inlineStr"><is>{_t_plain(cell)}</is></c>')
                else:
                    index = strings.setdefault(cell, len(strings))
                    style = ' s="2"' if r == 1 else ""
                    cells.append(f'<c r="{ref}"{style} t="s"><v>{index}</v></c>')
            rows.append(f'<row r="{r}">{"".join(cells)}</row>')
        sheet_xml.append(
            f'{_XML}<worksheet xmlns="{_SS}" xmlns:r="{_REL}"><sheetData>{"".join(rows)}'
            "</sheetData></worksheet>"
        )
    shared = "".join(f"<si>{_t_plain(text)}</si>" for text in strings)
    count = len(strings)
    sst = f'{_XML}<sst xmlns="{_SS}" count="{count}" uniqueCount="{count}">{shared}</sst>'
    names = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{n}" r:id="rId{n}"/>'
        for n, (name, _) in enumerate(sheets, 1)
    )
    workbook = f'{_XML}<workbook xmlns="{_SS}" xmlns:r="{_REL}"><sheets>{names}</sheets></workbook>'
    workbook_rels = _rels(
        *((f"{_REL}/worksheet", f"worksheets/sheet{n}.xml") for n in range(1, len(sheets) + 1)),
        (f"{_REL}/sharedStrings", "sharedStrings.xml"),
        (f"{_REL}/styles", "styles.xml"),
    )
    overrides = [("xl/workbook.xml", f"{_CT}spreadsheetml.sheet.main+xml")]
    overrides += [
        (f"xl/worksheets/sheet{n}.xml", f"{_CT}spreadsheetml.worksheet+xml")
        for n in range(1, len(sheets) + 1)
    ]
    overrides += [
        ("xl/sharedStrings.xml", f"{_CT}spreadsheetml.sharedStrings+xml"),
        ("xl/styles.xml", f"{_CT}spreadsheetml.styles+xml"),
    ]
    members = [
        ("[Content_Types].xml", _types(overrides), True),
        ("_rels/.rels", _root_rels("xl/workbook.xml"), True),
        ("docProps/core.xml", _core(title, author, when), True),
        ("xl/workbook.xml", workbook.encode(), True),
        ("xl/_rels/workbook.xml.rels", workbook_rels, True),
        ("xl/styles.xml", _STYLES_XLSX.encode(), True),
        ("xl/sharedStrings.xml", sst.encode(), True),
    ]
    members += [
        (f"xl/worksheets/sheet{n}.xml", xml.encode(), True) for n, xml in enumerate(sheet_xml, 1)
    ]
    return zip_bytes(members, when, Picture("xl/media/image1.png", size, rng))


def _t_plain(text: str) -> str:
    space = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
    return f"<t{space}>{escape(text)}</t>"


# PPTX ---------------------------------------------------------------------------------------

_P = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    f'xmlns:r="{_REL}" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
_COLOURS = (
    ("dk1", "000000"), ("lt1", "FFFFFF"), ("dk2", "1F497D"), ("lt2", "EEECE1"),
    ("accent1", "4F81BD"), ("accent2", "C0504D"), ("accent3", "9BBB59"), ("accent4", "8064A2"),
    ("accent5", "4BACC6"), ("accent6", "F79646"), ("hlink", "0000FF"), ("folHlink", "800080"),
)  # fmt: skip
_THEME = (
    _XML + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'name="Office"><a:themeElements><a:clrScheme name="Office">'
    + "".join(f'<a:{n}><a:srgbClr val="{v}"/></a:{n}>' for n, v in _COLOURS)
    + '</a:clrScheme><a:fontScheme name="Office"><a:majorFont><a:latin typeface="Calibri"/>'
    '<a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont>'
    '<a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>'
    '</a:fontScheme><a:fmtScheme name="Office"><a:fillStyleLst>'
    + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
    + "</a:fillStyleLst><a:lnStyleLst>"
    + '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' * 3
    + "</a:lnStyleLst><a:effectStyleLst>"
    + "<a:effectStyle><a:effectLst/></a:effectStyle>" * 3
    + "</a:effectStyleLst><a:bgFillStyleLst>"
    + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
    + "</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>"
)
_EMPTY_TREE = (
    '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
    "</p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>"
)


def _shape(number: int, placeholder: str, lines: Sequence[str]) -> str:
    paragraphs = "".join(
        f'<a:p><a:r><a:rPr lang="de-DE"/><a:t>{escape(line)}</a:t></a:r></a:p>' for line in lines
    )
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{number}" name="{placeholder} {number}"/><p:cNvSpPr/>'
        f'<p:nvPr><p:ph type="{placeholder}"/></p:nvPr></p:nvSpPr><p:spPr/>'
        f"<p:txBody><a:bodyPr/><a:lstStyle/>{paragraphs}</p:txBody></p:sp>"
    )


def _slide(title: str, lines: Sequence[str]) -> str:
    shapes = _shape(2, "title", [title]) + (_shape(3, "body", lines) if lines else "")
    return (
        f'{_XML}<p:sld {_P}><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
        f"<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{shapes}</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
    )


def _notes(lines: Sequence[str]) -> str:
    shapes = _shape(2, "sldImg", []) + _shape(3, "body", lines)
    return (
        f'{_XML}<p:notes {_P}><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
        f"<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{shapes}</p:spTree></p:cSld>"
        "</p:notes>"
    )


def pptx(
    slides: Sequence[tuple[str, Sequence[str], Sequence[str]]],
    *,
    title: str,
    author: str,
    when: datetime,
    size: int,
    rng: random.Random,
) -> bytes:
    """A presentation of (title, bullet lines, notes lines) slides; about `size` bytes with its
    picture."""
    count = len(slides)
    ids = "".join(f'<p:sldId id="{255 + n}" r:id="rId{n + 1}"/>' for n in range(1, count + 1))
    presentation = (
        f'{_XML}<p:presentation {_P}><p:sldMasterIdLst><p:sldMasterId id="2147483648" '
        f'r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>{ids}</p:sldIdLst>'
        '<p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>"
    )
    rels = _rels(
        (f"{_REL}/slideMaster", "slideMasters/slideMaster1.xml"),
        *((f"{_REL}/slide", f"slides/slide{n}.xml") for n in range(1, count + 1)),
        (f"{_REL}/theme", "theme/theme1.xml"),
    )
    master = (
        f'{_XML}<p:sldMaster {_P}>{_EMPTY_TREE}<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" '
        'tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" '
        'accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        "</p:sldMaster>"
    )
    layout = (
        f'{_XML}<p:sldLayout {_P} type="obj">{_EMPTY_TREE}'
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>"
    )
    overrides = [
        ("ppt/presentation.xml", f"{_CT}presentationml.presentation.main+xml"),
        ("ppt/slideMasters/slideMaster1.xml", f"{_CT}presentationml.slideMaster+xml"),
        ("ppt/slideLayouts/slideLayout1.xml", f"{_CT}presentationml.slideLayout+xml"),
        ("ppt/theme/theme1.xml", f"{_CT}theme+xml"),
    ]
    members: list[tuple[str, bytes, bool]] = [
        ("_rels/.rels", _root_rels("ppt/presentation.xml"), True),
        ("docProps/core.xml", _core(title, author, when), True),
        ("ppt/presentation.xml", presentation.encode(), True),
        ("ppt/_rels/presentation.xml.rels", rels, True),
        ("ppt/slideMasters/slideMaster1.xml", master.encode(), True),
        (
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            _rels(
                (f"{_REL}/slideLayout", "../slideLayouts/slideLayout1.xml"),
                (f"{_REL}/theme", "../theme/theme1.xml"),
            ),
            True,
        ),
        ("ppt/slideLayouts/slideLayout1.xml", layout.encode(), True),
        (
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            _rels((f"{_REL}/slideMaster", "../slideMasters/slideMaster1.xml")),
            True,
        ),
        ("ppt/theme/theme1.xml", _THEME.encode(), True),
    ]
    for n, (heading, lines, notes) in enumerate(slides, 1):
        targets = [(f"{_REL}/slideLayout", "../slideLayouts/slideLayout1.xml")]
        if notes:
            targets.append((f"{_REL}/notesSlide", f"../notesSlides/notesSlide{n}.xml"))
            members.append((f"ppt/notesSlides/notesSlide{n}.xml", _notes(notes).encode(), True))
            members.append(
                (
                    f"ppt/notesSlides/_rels/notesSlide{n}.xml.rels",
                    _rels((f"{_REL}/slide", f"../slides/slide{n}.xml")),
                    True,
                )
            )
            overrides.append(
                (f"ppt/notesSlides/notesSlide{n}.xml", f"{_CT}presentationml.notesSlide+xml")
            )
        if n == 1:
            targets.append((f"{_REL}/image", "../media/image1.png"))
        members.append((f"ppt/slides/slide{n}.xml", _slide(heading, lines).encode(), True))
        members.append((f"ppt/slides/_rels/slide{n}.xml.rels", _rels(*targets), True))
        overrides.append((f"ppt/slides/slide{n}.xml", f"{_CT}presentationml.slide+xml"))
    members.insert(0, ("[Content_Types].xml", _types(overrides), True))
    return zip_bytes(members, when, Picture("ppt/media/image1.png", size, rng, 64))


# ODT ----------------------------------------------------------------------------------------

_ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" office:version="1.3"'
)
_ODT_MIME = "application/vnd.oasis.opendocument.text"


def _odf_text(text: str) -> str:
    """ODF paragraph content: tabs as text:tab."""
    return "<text:tab/>".join(escape(part) for part in text.split("\t"))


def odt(
    body: Sequence[Block],
    *,
    title: str,
    author: str,
    when: datetime,
    size: int,
    rng: random.Random,
) -> bytes:
    """An OpenDocument text: headings, paragraphs and tables; about `size` bytes with its
    picture."""
    parts = []
    for item in body:
        if isinstance(item, Para):
            if item.style == "text":
                parts.append(f"<text:p>{_odf_text(item.text)}</text:p>")
            else:
                level = 1 if item.style == "title" else 2
                parts.append(
                    f'<text:h text:outline-level="{level}">{_odf_text(item.text)}</text:h>'
                )
        else:
            rows = "".join(
                "<table:table-row>"
                + "".join(
                    f"<table:table-cell><text:p>{escape(cell_text(c))}</text:p></table:table-cell>"
                    for c in row
                )
                + "</table:table-row>"
                for row in item
            )
            parts.append(f'<table:table table:name="Tabelle{len(parts)}">{rows}</table:table>')
    content = (
        f"{_XML}<office:document-content {_ODF_NS}><office:body><office:text>"
        f"{''.join(parts)}</office:text></office:body></office:document-content>"
    )
    meta = (
        f"{_XML}<office:document-meta {_ODF_NS}><office:meta><dc:title>{escape(title)}</dc:title>"
        f"<meta:initial-creator>{escape(author)}</meta:initial-creator>"
        f"<meta:creation-date>{when:%Y-%m-%dT%H:%M:%S}</meta:creation-date></office:meta>"
        "</office:document-meta>"
    )
    styles = f"{_XML}<office:document-styles {_ODF_NS}/>"
    manifest = (
        f"{_XML}<manifest:manifest {_ODF_NS}>"
        f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{_ODT_MIME}"/>'
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
        '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
        '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>'
        '<manifest:file-entry manifest:full-path="Pictures/image1.png" '
        'manifest:media-type="image/png"/></manifest:manifest>'
    )
    members = [
        ("mimetype", _ODT_MIME.encode(), False),
        ("content.xml", content.encode(), True),
        ("styles.xml", styles.encode(), True),
        ("meta.xml", meta.encode(), True),
        ("META-INF/manifest.xml", manifest.encode(), True),
    ]
    return zip_bytes(members, when, Picture("Pictures/image1.png", size, rng, 64))


# Pictures and recordings --------------------------------------------------------------------

MEDIA_DIR = Path(__file__).with_name("media")  # recordings and photos, see media/README.md
_PHOTOS = 3  # media/jpeg-1.jpeg to jpeg-3.jpeg
_PICTURE_SIZES = ((320, 240), (400, 300), (480, 320), (240, 320), (160, 60))
_PNG_PADDING = b"paDd"  # a private ancillary chunk: decoders skip it
_COMMENT = 65533  # the largest JPEG comment segment


@functools.cache
def fixture(name: str) -> bytes:
    """A file of media/ by its name."""
    return (MEDIA_DIR / name).read_bytes()


def png(rng: random.Random, size: int, *, damaged: bool = False) -> bytes:
    """A PNG of coloured blocks on a gradient, about `size` bytes: noise in a chunk of its own
    between header and image data makes up the rest. A damaged one stops inside that chunk, so
    it has a size but no image."""
    width, height = rng.choice(_PICTURE_SIZES)
    top, bottom = rng.randbytes(3), rng.randbytes(3)
    rows = [
        bytearray(bytes(a + (b - a) * y // height for a, b in zip(top, bottom, strict=True)))
        * width
        for y in range(height)
    ]
    for _ in range(rng.randint(3, 8)):
        x0, y0 = rng.randrange(width), rng.randrange(height)
        x1, y1 = rng.randint(x0 + 1, width), rng.randint(y0 + 1, height)
        colour = rng.randbytes(3)
        for row in rows[y0:y1]:
            row[3 * x0 : 3 * x1] = colour * (x1 - x0)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    image = zlib.compress(b"".join(b"\x00" + row for row in rows), 9)
    used = 8 + 3 * 12 + len(header) + len(image) + 12
    noise = filler(rng, max(size - used, 64), b"")
    data = b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", header),
            _png_chunk(_PNG_PADDING, noise),
            _png_chunk(b"IDAT", image),
            _png_chunk(b"IEND", b""),
        )
    )
    return data[: rng.randint(41, 41 + len(noise))] if damaged else data


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(data, zlib.crc32(kind))
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def jpeg(rng: random.Random, size: int, *, damaged: bool = False, exif: bytes = b"") -> bytes:
    """A photo of media/ (made with ffmpeg) of about `size` bytes: comment segments of noise
    after its JFIF header (and its EXIF, exif_segment) make up the rest, so every photo has
    bytes of its own. A damaged one stops inside them, before the frame header."""
    photo = fixture(f"jpeg-{rng.randint(1, _PHOTOS)}.jpeg")
    start = 4 + int.from_bytes(photo[4:6], "big")  # behind SOI and APP0
    pad = max(size - len(photo) - len(exif), 64)
    noise = filler(rng, pad - 4 * -(-pad // (_COMMENT + 4)), b"")
    comments = b"".join(
        b"\xff\xfe" + struct.pack(">H", len(piece) + 2) + piece
        for piece in (noise[i : i + _COMMENT] for i in range(0, len(noise), _COMMENT))
    )
    if damaged:
        return photo[:start] + exif + comments[: rng.randint(5, len(comments) - 1)]
    return photo[:start] + exif + comments + photo[start:]


# EXIF (D241) --------------------------------------------------------------------------------

_BYTE, _ASCII, _LONG, _RATIONAL = 1, 2, 4, 5
_SIZES = {_BYTE: 1, _ASCII: 1, _LONG: 4, _RATIONAL: 8}
_Entry = tuple[int, int, bytes]  # tag, type, its values as written


def exif_segment(gps: PhotoGps) -> bytes:
    """The APP1 segment of a phone's or camera's photo: make and model (IFD0), the time taken
    and its UTC offset (Exif IFD), and the position as degrees, minutes and seconds with the
    altitude and the GPS time in UTC (GPS IFD), little-endian as phones write it."""
    utc = gps.taken - timedelta(hours=int(gps.offset[:3]), minutes=int(gps.offset[4:]))
    ifd0 = [_text(0x010F, gps.make), _text(0x0110, gps.model)]
    exif = [_text(0x9003, f"{gps.taken:%Y:%m:%d %H:%M:%S}"), _text(0x9011, gps.offset)]
    position = [
        (0x0000, _BYTE, bytes((2, 3, 0, 0))),
        _text(0x0001, "N" if gps.latitude >= 0 else "S"),
        (0x0002, _RATIONAL, _rationals(*_dms(gps.latitude))),
        _text(0x0003, "E" if gps.longitude >= 0 else "W"),
        (0x0004, _RATIONAL, _rationals(*_dms(gps.longitude))),
        (0x0005, _BYTE, b"\x00"),
        (0x0006, _RATIONAL, _rationals((round(gps.altitude * 10), 10))),
        (0x0007, _RATIONAL, _rationals((utc.hour, 1), (utc.minute, 1), (utc.second, 1))),
        _text(0x001D, f"{utc:%Y:%m:%d}"),
    ]
    body = b"Exif\x00\x00" + _tiff(ifd0, exif, position)
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def _dms(value: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Degrees, minutes and thousandths of seconds of a coordinate, without its sign."""
    thousandths = round(abs(value) * 3_600_000)
    degrees, rest = divmod(thousandths, 3_600_000)
    minutes, seconds = divmod(rest, 60_000)
    return (degrees, 1), (minutes, 1), (seconds, 1000)


def dms_degrees(value: float) -> float:
    """The coordinate as a reader computes it back from exif_segment's rationals, rounded to
    seven places as attachments.metadata.exif stores it, with its sign."""
    (degrees, _), (minutes, _), (seconds, scale) = _dms(value)
    found = round(degrees / 1 + minutes / 1 / 60 + seconds / scale / 3600, 7)
    return -found if value < 0 else found


def _text(tag: int, value: str) -> _Entry:
    return tag, _ASCII, value.encode("ascii") + b"\x00"


def _rationals(*pairs: tuple[int, int]) -> bytes:
    return b"".join(struct.pack("<II", numerator, denominator) for numerator, denominator in pairs)


def _tiff(ifd0: list[_Entry], exif: list[_Entry], gps: list[_Entry]) -> bytes:
    """A TIFF structure: IFD0 pointing to the Exif and GPS IFDs, then the values that do not fit
    into an entry."""

    def size(entries: list[_Entry]) -> int:
        return 2 + 12 * len(entries) + 4

    exif_at = 8 + size(ifd0) + 2 * 12
    gps_at = exif_at + size(exif)
    first = [*ifd0, (0x8769, _LONG, struct.pack("<I", exif_at)),
             (0x8825, _LONG, struct.pack("<I", gps_at))]  # fmt: skip
    data = bytearray()
    data_at = gps_at + size(gps)
    tables = bytearray()
    for entries in (first, exif, gps):
        tables += struct.pack("<H", len(entries))
        for tag, kind, value in sorted(entries):
            count = len(value) // _SIZES[kind]
            if len(value) <= 4:
                tables += struct.pack("<HHI", tag, kind, count) + value.ljust(4, b"\x00")
            else:
                tables += struct.pack("<HHII", tag, kind, count, data_at + len(data))
                data += value + b"\x00" * (len(value) % 2)  # values start on a word
        tables += struct.pack("<I", 0)
    return b"II*\x00" + struct.pack("<I", 8) + bytes(tables) + bytes(data)

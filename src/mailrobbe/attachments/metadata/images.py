"""Images (D167): where JPEG, PNG, WebP and TIFF keep their metadata, handed to exif and xmp.

JPEG: the APP1 segments before the first scan, "Exif\\0\\0" with a TIFF structure, the XMP
namespace with a packet. PNG: the chunks eXIf (a TIFF structure), tEXt, zTXt and iTXt (text
under a keyword such as Software, Author or Creation Time; iTXt XML:com.adobe.xmp is XMP) and
tIME (the last change, UTC). WebP: the RIFF chunks EXIF and "XMP ". TIFF is a TIFF structure
itself. Segments and chunks are walked by their lengths without reading the image data, at most
MAX_PARTS of them; a length beyond the end stops the walk and is noted. Compressed text is
inflated up to MAX_TEXT bytes.
"""

import struct
import zlib

from mailrobbe.attachments.metadata.exif import read_tiff
from mailrobbe.attachments.metadata.model import Collector, iso_date
from mailrobbe.attachments.metadata.xmp import read_xmp

MAX_PARTS = 10_000  # segments or chunks walked
MAX_TEXT = 64 * 1024  # bytes of one compressed text, inflated

_XMP_JPEG = b"http://ns.adobe.com/xap/1.0/\x00"
_XMP_PNG = "XML:com.adobe.xmp"
_NO_LENGTH = frozenset({0x01, *range(0xD0, 0xD9)})  # TEM, RSTn, SOI


def image_format(data: bytes) -> str | None:
    """jpeg, png, webp or tiff by the first bytes; None for an image of another format."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def read_image(data: bytes, out: Collector) -> None:
    match image_format(data):
        case "jpeg":
            _jpeg(data, out)
        case "png":
            _png(data, out)
        case "webp":
            _webp(data, out)
        case "tiff":
            read_tiff(data, out)


def _jpeg(data: bytes, out: Collector) -> None:
    position, parts, exif = 2, 0, False
    while position + 4 <= len(data) and parts < MAX_PARTS:
        if data[position] != 0xFF:
            out.damaged(f"JPEG: no marker at byte {position}")
            return
        marker = data[position + 1]
        if marker == 0xFF:  # fill byte
            position += 1
            continue
        if marker in _NO_LENGTH:
            position += 2
            continue
        if marker in (0xDA, 0xD9):  # the scan or the end: metadata stands before
            return
        (length,) = struct.unpack_from(">H", data, position + 2)
        end = position + 2 + length
        if length < 2 or end > len(data):
            out.damaged(f"JPEG: the segment at byte {position} runs beyond the end")
            return
        body = data[position + 4 : end]
        if marker == 0xE1 and body.startswith(b"Exif\x00\x00") and not exif:
            read_tiff(body[6:], out)
            exif = True
        elif marker == 0xE1 and body.startswith(_XMP_JPEG):
            read_xmp(body[len(_XMP_JPEG) :], out)
        position, parts = end, parts + 1


def _png(data: bytes, out: Collector) -> None:
    position, parts = 8, 0
    while position + 12 <= len(data) and parts < MAX_PARTS:
        length, kind = struct.unpack_from(">I4s", data, position)
        end = position + 12 + length
        if end > len(data):
            out.damaged(f"PNG: the chunk at byte {position} runs beyond the end")
            return
        body = data[position + 8 : end - 4]
        if kind == b"eXIf":
            read_tiff(body, out)
        elif kind == b"tEXt":
            keyword, _, value = body.partition(b"\x00")
            out.text("png", keyword.decode("latin-1"), value.decode("latin-1"))
        elif kind == b"zTXt":
            keyword, _, rest = body.partition(b"\x00")
            inflated = _inflate(rest[1:], out) if rest[:1] == b"\x00" else None
            if inflated is not None:
                out.text("png", keyword.decode("latin-1"), inflated.decode("latin-1"))
        elif kind == b"iTXt":
            _itxt(body, out)
        elif kind == b"tIME" and length == 7:
            year, *others = struct.unpack(">HBBBBB", body)
            month, day, hour, minute, second = (f"{n:02d}" for n in others)
            out.text(
                "png", "tIME", iso_date(f"{year:04d}", month, day, hour, minute, second, zone="Z")
            )
        elif kind == b"IEND":
            return
        position, parts = end, parts + 1


def _itxt(body: bytes, out: Collector) -> None:
    """keyword NUL, compression flag and method, language NUL, translated keyword NUL, text."""
    keyword, _, rest = body.partition(b"\x00")
    if len(rest) < 2:
        return
    compressed, method = rest[0], rest[1]
    _language, _, rest = rest[2:].partition(b"\x00")
    _translated, _, value = rest.partition(b"\x00")
    if compressed:
        inflated = _inflate(value, out) if method == 0 else None
        if inflated is None:
            return
        value = inflated
    name = keyword.decode("latin-1")
    if name == _XMP_PNG:
        read_xmp(value, out)
    else:
        out.text("png", name, value.decode("utf-8", "replace"))


def _inflate(data: bytes, out: Collector) -> bytes | None:
    try:
        return zlib.decompressobj().decompress(data, MAX_TEXT)
    except zlib.error as error:
        out.damaged(f"PNG: compressed text cannot be read ({error})")
        return None


def _webp(data: bytes, out: Collector) -> None:
    position, parts = 12, 0
    while position + 8 <= len(data) and parts < MAX_PARTS:
        kind, length = struct.unpack_from("<4sI", data, position)
        end = position + 8 + length
        if end > len(data):
            out.damaged(f"WebP: the chunk at byte {position} runs beyond the end")
            return
        body = data[position + 8 : end]
        if kind == b"EXIF":
            read_tiff(body.removeprefix(b"Exif\x00\x00"), out)
        elif kind == b"XMP ":
            read_xmp(body, out)
        position, parts = end + (length & 1), parts + 1  # chunks are padded to an even size

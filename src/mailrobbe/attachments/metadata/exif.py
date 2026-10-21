"""EXIF (D167): the fields of a TIFF structure, as JPEG APP1, PNG eXIf, WebP EXIF and TIFF files
hold it.

A TIFF structure is a header (byte order II or MM, 42, the offset of IFD0) and image file
directories: an entry count, 12-byte entries (tag, type, count, the value or its offset), the
offset of the next directory. read_tiff reads IFD0, its Exif IFD (0x8769) and its GPS IFD
(0x8825), nothing else (no thumbnail, MakerNote or interoperability IFD), each at most once.
Every offset must lie inside the buffer, a directory is read up to MAX_ENTRIES entries and a
value up to MAX_VALUE bytes, and an offset seen before ends the walk, so a hostile file can
neither loop nor make it read outside its bytes; a broken entry is skipped and noted.
"""

import re
import struct

from mailrobbe.attachments.metadata.model import Collector, DateParser, iso_date

MAX_ENTRIES = 512  # entries read of one directory
MAX_VALUE = 64 * 1024  # bytes of one value

_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
_EXIF_IFD, _GPS_IFD = 0x8769, 0x8825

# tag -> key of the texts (ASCII) read from IFD0 and the Exif IFD
_TEXTS = {
    0x010E: "image_description",
    0x010F: "make",
    0x0110: "model",
    0x0131: "software",
    0x013B: "artist",
    0x013C: "host_computer",
    0xA420: "image_unique_id",
    0xA430: "camera_owner_name",
    0xA431: "body_serial_number",
    0xA433: "lens_make",
    0xA434: "lens_model",
    0xA435: "lens_serial_number",
}
# Windows writes these in IFD0 as UTF-16LE bytes.
_XP = {
    0x9C9B: "xp_title",
    0x9C9C: "xp_comment",
    0x9C9D: "xp_author",
    0x9C9E: "xp_keywords",
    0x9C9F: "xp_subject",
}
# date tag -> (key, tag of its offset, OffsetTime*)
_DATES = {
    0x0132: ("datetime", 0x9010),
    0x9003: ("datetime_original", 0x9011),
    0x9004: ("datetime_digitized", 0x9012),
}
_COPYRIGHT, _USER_COMMENT = 0x8298, 0x9286

_DATE = DateParser(
    r"(?P<year>\d{4}):(?P<month>\d{2}):(?P<day>\d{2})"
    r"(?: (?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?)?"
    r"(?:\.(?P<fraction>\d+))?(?P<zone>Z|[+-]\d{2}:\d{2})?"
)
_ZONE = re.compile(r"[+-]\d{2}:\d{2}")  # OffsetTime*


class _Tiff:
    """The directories of one TIFF structure."""

    def __init__(self, data: bytes, out: Collector) -> None:
        self.data = data
        self.out = out
        self.endian = "<" if data[:2] == b"II" else ">"
        self._seen: set[int] = set()

    def directory(self, offset: int, what: str) -> dict[int, tuple[int, int, bytes]]:
        """tag -> (type, count, value bytes) of the directory at offset; {} where it cannot be."""
        data = self.data
        if offset in self._seen:
            self.out.damaged(f"EXIF: {what} at byte {offset} read before (a loop)")
            return {}
        self._seen.add(offset)
        if offset < 8 or offset + 2 > len(data):
            self.out.damaged(f"EXIF: {what} at byte {offset}, outside the data")
            return {}
        (count,) = struct.unpack_from(self.endian + "H", data, offset)
        room = (len(data) - offset - 2) // 12
        if count > room:
            self.out.damaged(f"EXIF: {what} has {count} entries, room for {room}")
        entries: dict[int, tuple[int, int, bytes]] = {}
        for index in range(min(count, room, MAX_ENTRIES)):
            position = offset + 2 + 12 * index
            tag, kind, number = struct.unpack_from(self.endian + "HHI", data, position)
            size = _SIZES.get(kind)
            if size is None or tag in entries:
                continue
            length = size * number
            if length > MAX_VALUE:
                continue
            if length <= 4:
                value = data[position + 8 : position + 8 + length]
            else:
                (at,) = struct.unpack_from(self.endian + "I", data, position + 8)
                if at + length > len(data):
                    self.out.damaged(f"EXIF: the value of tag {tag:#06x} lies outside the data")
                    continue
                value = data[at : at + length]
            entries[tag] = (kind, number, value)
        return entries

    def pointer(self, entries: dict[int, tuple[int, int, bytes]], tag: int) -> int | None:
        found = self.integers(entries.get(tag))
        return found[0] if found else None

    def integers(self, entry: tuple[int, int, bytes] | None) -> list[int]:
        if entry is None:
            return []
        kind, number, value = entry
        codes = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i"}
        code = codes.get(kind)
        return list(struct.unpack(f"{self.endian}{number}{code}", value)) if code else []

    def rationals(self, entry: tuple[int, int, bytes] | None) -> list[float] | None:
        """The values of a RATIONAL entry; None when it is none or divides by zero."""
        if entry is None or entry[0] not in (5, 10):
            return None
        kind, number, value = entry
        code = "I" if kind == 5 else "i"
        numbers = struct.unpack(f"{self.endian}{2 * number}{code}", value)
        pairs = list(zip(numbers[::2], numbers[1::2], strict=True))
        if any(denominator == 0 for _, denominator in pairs):
            return None
        return [numerator / denominator for numerator, denominator in pairs]


def text(value: bytes) -> str:
    """An ASCII value up to its NUL; UTF-8 where it is, else Latin-1."""
    raw = value.split(b"\x00", 1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_tiff(data: bytes, out: Collector) -> None:
    """The EXIF and GPS fields of a TIFF structure (see the module docstring)."""
    if len(data) < 8 or data[:4] not in (b"II*\x00", b"MM\x00*"):
        out.damaged("EXIF: no TIFF header")
        return
    tiff = _Tiff(data, out)
    (first,) = struct.unpack_from(tiff.endian + "I", data, 4)
    ifd0 = tiff.directory(first, "IFD0")
    exif_at = tiff.pointer(ifd0, _EXIF_IFD)
    exif = tiff.directory(exif_at, "the Exif IFD") if exif_at is not None else {}
    entries = {**exif, **ifd0}  # a tag in both: IFD0's, where TIFF puts it
    for tag, key in _TEXTS.items():
        entry = entries.get(tag)
        if entry is not None and entry[0] == 2:
            out.text("exif", key, text(entry[2]))
    for tag, key in _XP.items():
        entry = entries.get(tag)
        if entry is not None and entry[0] in (1, 7):
            out.text("exif", key, entry[2].decode("utf-16-le", "replace").split("\x00", 1)[0])
    copyright_ = entries.get(_COPYRIGHT)
    if copyright_ is not None and copyright_[0] == 2:  # photographer NUL editor
        parts = [text(part) for part in copyright_[2].split(b"\x00")]
        out.text("exif", "copyright", " / ".join(part.strip() for part in parts if part.strip()))
    comment = entries.get(_USER_COMMENT)
    if comment is not None and comment[0] == 7:
        out.text("exif", "user_comment", _user_comment(comment[2], tiff.endian))
    for tag, (key, offset_tag) in _DATES.items():
        entry = entries.get(tag)
        if entry is None or entry[0] != 2:
            continue
        found = text(entry[2]).strip()
        zone = entries.get(offset_tag)
        zone_text = text(zone[2]).strip() if zone is not None and zone[0] == 2 else ""
        if not _ZONE.fullmatch(zone_text):
            zone_text = ""
        out.date("exif", key, found + zone_text if _DATE(found) else found, _DATE)
    gps_at = tiff.pointer(ifd0, _GPS_IFD)
    if gps_at is not None:
        _read_gps(tiff, tiff.directory(gps_at, "the GPS IFD"), out)


def _user_comment(value: bytes, endian: str) -> str:
    """UserComment: an 8-byte character code, then the text."""
    code, body = value[:8], value[8:]
    if code.startswith(b"UNICODE"):
        return body.decode("utf-16-le" if endian == "<" else "utf-16-be", "replace")
    if code.startswith(b"ASCII") or code == b"\x00" * 8:
        return text(body)
    return ""  # JIS and other codes are not read


def _read_gps(tiff: _Tiff, entries: dict[int, tuple[int, int, bytes]], out: Collector) -> None:
    """Latitude and longitude with their references, altitude, the GPS date and time."""
    for key, ref_tag, tag, positive, negative, limit in (
        ("latitude", 1, 2, "N", "S", 90),
        ("longitude", 3, 4, "E", "W", 180),
    ):
        ref = entries.get(ref_tag)
        parts = tiff.rationals(entries.get(tag))
        direction = text(ref[2]).strip().upper() if ref is not None and ref[0] == 2 else ""
        if parts is None or len(parts) != 3 or direction not in (positive, negative):
            continue
        degrees = parts[0] + parts[1] / 60 + parts[2] / 3600
        if 0 <= degrees <= limit:
            out.number("gps", key, round(-degrees if direction == negative else degrees, 7))
    altitude = tiff.rationals(entries.get(6))
    if altitude is not None and len(altitude) == 1:
        below = tiff.integers(entries.get(5)) == [1]
        out.number("gps", "altitude", round(-altitude[0] if below else altitude[0], 2))
    stamp = entries.get(0x1D)
    clock = tiff.rationals(entries.get(7))
    if stamp is not None and stamp[0] == 2:
        day = text(stamp[2]).strip()
        ymd = day.split(":")
        if clock is not None and len(clock) == 3 and len(ymd) == 3:
            hour, minute, second = (f"{int(value):02d}" for value in clock)
            moment = iso_date(ymd[0], ymd[1], ymd[2], hour, minute, second, zone="Z")
            out.text("gps", "timestamp", moment or day)
        else:
            out.date("gps", "timestamp", day, _DATE)

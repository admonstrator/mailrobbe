"""Text formats (D71): plain text, CSV, HTML, XML, JSON, iCalendar and vCard.

Bytes become text as the importer reads mail text (importer.text): a byte order mark or UTF-16
without one is honoured, otherwise UTF-8, then cp1252, then latin-1. Only as many bytes are
decoded as max_chars characters can take. Plain text and CSV are written as they are (CSV is
not parsed, so every value stands as written). HTML gives the text a reader sees
(importer.text.html_to_text); XML the character data of its elements, one element per line
(entity declarations refused); JSON its string and number values as written, one per line, keys
left out; iCalendar and vCard their readable properties (summary, description, place, times,
organiser and attendees; names, organisation, phone numbers, mail and postal addresses, notes).
A JSON file that does not parse, and an XML file that is not well-formed before any text was
read, are read as plain text (XML without its tags).
"""

import json
import quopri
import re
from collections.abc import Iterator

from mailrobbe.attachments.extract.base import Sink
from mailrobbe.attachments.extract.packages import Malformed, parse_xml
from mailrobbe.enums import DocumentTextStatus
from mailrobbe.importer import text as mailtext
from mailrobbe.importer.model import Issue
from mailrobbe.importer.parse import cut_at_line

_BOMS = (
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)
_BYTES_PER_CHARACTER = 4  # UTF-8 at worst
_HTML_BYTES_PER_CHARACTER = 40  # markup takes most of an HTML file (as importer.parse)
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.I)
_TAG = re.compile(r"<[^>]*>")


def decode(data: bytes, charset: str | None = None) -> str:
    """Text of a file: BOM, UTF-16 by its zero bytes, the charset if given, else a guess."""
    for bom, codec in _BOMS:
        if data.startswith(bom):
            return data[len(bom) :].decode(codec, "replace")
    head = data[:4096]
    if len(head) >= 16 and head.count(0) > len(head) // 4:
        odd = head[1::2].count(0)
        even = head[0::2].count(0)
        return data.decode("utf-16-le" if odd > even else "utf-16-be", "replace")
    issues: list[Issue] = []
    return mailtext.decode_bytes(data, charset, "attachment", issues)


def _head(data: bytes, sink: Sink, per_character: int) -> tuple[bytes, bool]:
    """The bytes that can hold max_chars characters, and whether more were left out."""
    limit = per_character * sink.max_chars + 4
    cut = cut_at_line(data, limit)
    return cut, len(cut) < len(data)


def _write(sink: Sink, text: str, cut: bool) -> None:
    sink.text(text)
    sink.truncated = sink.truncated or cut


def extract_text(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    """Plain text and CSV, as written."""
    head, cut = _head(data, sink, _BYTES_PER_CHARACTER)
    _write(sink, decode(head), cut)
    return None


def extract_html(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    head, cut = _head(data, sink, _HTML_BYTES_PER_CHARACTER)
    match = _META_CHARSET.search(head[:4096])
    charset = match.group(1).decode("ascii") if match else None
    _write(sink, mailtext.html_to_text(decode(head, charset)), cut)
    return None


class _XmlText:
    """Character data of each element as a line."""

    def __init__(self, sink: Sink) -> None:
        self._sink = sink
        self._parts: list[str] = []

    def _flush(self) -> None:
        if self._parts:
            self._sink.text("".join(self._parts))
            self._parts.clear()

    def start(self, name: str, attrs: dict[str, str]) -> None:
        self._flush()

    def end(self, name: str) -> None:
        self._flush()

    def data(self, text: str) -> None:
        self._parts.append(text)


def extract_xml(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    try:
        parse_xml(_pieces(data), _XmlText(sink), "XML", doctype=True)
    except Malformed:
        if sink.has_text:
            return None  # the text up to the error
        head, cut = _head(data, sink, _BYTES_PER_CHARACTER)
        _write(sink, _TAG.sub(" ", decode(head)), cut)
    return None


def _pieces(data: bytes) -> Iterator[bytes]:
    for start in range(0, len(data), 1 << 20):
        yield data[start : start + (1 << 20)]


def extract_json(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    text = decode(data)
    try:
        value = json.loads(text, parse_float=str, parse_int=str, parse_constant=str)
    except json.JSONDecodeError:
        head, cut = _head(data, sink, _BYTES_PER_CHARACTER)
        _write(sink, decode(head), cut)
        return None
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))
        elif isinstance(item, str):
            sink.text(item)
        elif isinstance(item, bool):
            sink.line("true" if item else "false")
    return None


# iCalendar and vCard

_CALENDAR = frozenset(
    {
        *("SUMMARY", "DESCRIPTION", "LOCATION", "COMMENT", "CATEGORIES", "CONTACT"),
        *("RESOURCES", "ORGANIZER", "ATTENDEE", "DTSTART", "DTEND", "DUE"),
    }
)
_VCARD = frozenset(
    {
        *("FN", "N", "NICKNAME", "ORG", "TITLE", "ROLE", "TEL", "EMAIL", "ADR", "LABEL"),
        *("NOTE", "URL", "BDAY"),
    }
)
_DATE = re.compile(r"(\d{4})-?(\d\d)-?(\d\d)(?:T(\d\d):?(\d\d)(?::?\d\d)?(Z)?)?")
_ESCAPE = re.compile(r"\\(.)")
_ESCAPED = {"n": "\n", "N": "\n"}


def _unfold(text: str) -> Iterator[str]:
    """Logical lines: continuation lines (leading space or tab) and quoted-printable soft
    breaks joined."""
    current: str | None = None
    for line in text.splitlines():
        if current is not None and line[:1] in (" ", "\t"):
            current += line[1:]
        elif (
            current is not None
            and current.endswith("=")
            and "QUOTED-PRINTABLE" in (current.partition(":")[0].upper())
        ):
            current = current[:-1] + line
        else:
            if current is not None:
                yield current
            current = line
    if current is not None:
        yield current


def _parameters(head: str) -> tuple[str, dict[str, str]]:
    name, *params = head.split(";")
    found: dict[str, str] = {}
    for param in params:
        key, _, value = param.partition("=")
        found[key.strip().upper()] = value.strip().strip('"')
    return name.strip().upper().rpartition(".")[2], found  # "item1.TEL" -> "TEL"


def _value(name: str, raw: str, params: dict[str, str]) -> str:
    if params.get("ENCODING", "").upper() in ("QUOTED-PRINTABLE", "QP"):
        data = quopri.decodestring(raw.encode("latin-1", "replace"))
        raw = mailtext.decode_bytes(data, params.get("CHARSET") or "utf-8", "vCard", [])
    value = _ESCAPE.sub(lambda m: _ESCAPED.get(m.group(1), m.group(1)), raw)
    if name in ("N", "ADR"):
        value = " ".join(part.strip() for part in value.split(";") if part.strip())
    elif name in ("ORGANIZER", "ATTENDEE"):
        address = value[7:] if value.lower().startswith("mailto:") else value
        person = params.get("CN", "")
        value = f"{person} <{address}>" if person else address
    elif name in ("DTSTART", "DTEND", "DUE", "BDAY"):
        match = _DATE.fullmatch(value.strip())
        if match:
            year, month, day, hour, minute, utc = match.groups()
            value = f"{year}-{month}-{day}"
            if hour:
                value += f" {hour}:{minute}{' UTC' if utc else ''}"
    return value


def extract_calendar(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    """iCalendar and vCard: the readable properties of each entry, an entry per block."""
    for line in _unfold(decode(data)):
        head, colon, raw = line.partition(":")
        if not colon:
            continue
        name, params = _parameters(head)
        if name == "END":
            sink.block()
        elif name in _CALENDAR or name in _VCARD:
            sink.text(_value(name, raw, params))
    return None

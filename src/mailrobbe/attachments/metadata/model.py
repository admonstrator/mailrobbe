"""What a file says about itself (D167): the fields found, and the few the list and the mail
detail use. The contract between the readers, the phase, the API and the export.

Fields are grouped by where they stand in the file (source -> key -> value):

    exif        IFD0 and Exif IFD of a TIFF structure (JPEG APP1, PNG eXIf, WebP EXIF, TIFF)
    gps         its GPS IFD
    xmp         an XMP packet (images, PDF)
    png         PNG text chunks under their own keywords, and tIME
    pdf         the information dictionary, the PDF version, revisions and embedded files
    pdf_custom  the information dictionary's other entries, under their own names
    office      docProps of DOCX, XLSX and PPTX; comments and tracked changes of a DOCX
    odf         meta.xml of ODT, ODS and ODP

Keys are stable English snake_case names (png and pdf_custom keep the file's own). Values are
as found: text trimmed, control characters removed, at most VALUE_LIMIT characters; lists of at
most LIST_LIMIT texts; counts as integers. Dates are ISO 8601, with the offset the file gives
or none: a time without a zone stays without one, nothing is guessed; a date that cannot be
read stays the text as found. GPS coordinates are signed decimal degrees (south and west
negative), altitude metres (below sea level negative), the GPS time UTC as the format defines it.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from mailrobbe.attachments.kinds import classify
from mailrobbe.enums import DocumentKind, DocumentMetadataStatus

Value = str | int | float | list[str]
Fields = dict[str, dict[str, Value]]

VALUE_LIMIT = 1_000  # characters of a text value
LIST_LIMIT = 50  # texts of a list value
FIELD_LIMIT = 300  # fields of one document in all
KEY_LIMIT = 80  # characters of a key the file names itself

_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff﻿]")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Reading:
    """What reading one document's metadata gave (never pending, too_large: the phase decides
    those before reading)."""

    status: DocumentMetadataStatus
    fields: Fields = field(default_factory=dict)
    error: str | None = None  # English, one line: why failed, or the part found damaged


@dataclass(frozen=True, slots=True)
class Summary:
    """The fields the document list filters by and the mail detail shows (MetadataSummary)."""

    author: str | None = None
    modified_by: str | None = None
    program: str | None = None
    device: str | None = None
    created: datetime | None = None  # only a time the file states with its zone
    gps: bool = False


def clean(value: str) -> str:
    """A value as stored: control characters removed, whitespace collapsed, trimmed, capped."""
    text = _SPACES.sub(" ", _CONTROL.sub("", value)).strip()
    return text if len(text) <= VALUE_LIMIT else text[: VALUE_LIMIT - 1] + "…"


class Collector:
    """The fields of one document as the readers find them, within the limits above; the first
    damage a reader meets is kept as `problem`."""

    def __init__(self) -> None:
        self.fields: Fields = {}
        self.problem: str | None = None
        self._count = 0

    def text(self, source: str, key: str, value: str | None) -> None:
        if value is not None and (text := clean(value)):
            self._put(source, key, text)

    def number(self, source: str, key: str, value: int | float) -> None:
        self._put(source, key, value)

    def texts(self, source: str, key: str, values: Iterable[str]) -> None:
        """A list of texts, each once, in order."""
        found: list[str] = []
        for value in values:
            text = clean(value)
            if text and text not in found:
                found.append(text)
                if len(found) == LIST_LIMIT:
                    break
        if found:
            self._put(source, key, found)

    def date(self, source: str, key: str, value: str | None, parse: "DateParser") -> None:
        """A date as ISO 8601 when parse reads it, else the text as found."""
        if value is None or not (text := clean(value)):
            return
        self._put(source, key, parse(text) or text)

    def damaged(self, problem: str) -> None:
        if self.problem is None:
            self.problem = problem

    def has(self, source: str, key: str) -> bool:
        return key in self.fields.get(source, {})

    def _put(self, source: str, key: str, value: Value) -> None:
        key = clean(key)[:KEY_LIMIT]
        if not key or self.has(source, key) or self._count >= FIELD_LIMIT:
            return
        self.fields.setdefault(source, {})[key] = value
        self._count += 1


class DateParser:
    """Turns a date of one notation into ISO 8601; None when it cannot be read."""

    def __init__(self, pattern: str) -> None:
        self._pattern = re.compile(pattern)

    def __call__(self, text: str) -> str | None:
        match = self._pattern.fullmatch(text)
        if match is None:
            return None
        parts = match.groupdict()
        return iso_date(
            parts["year"],
            parts.get("month"),
            parts.get("day"),
            parts.get("hour"),
            parts.get("minute"),
            parts.get("second"),
            parts.get("fraction"),
            parts.get("zone"),
        )


def iso_date(
    year: str,
    month: str | None = None,
    day: str | None = None,
    hour: str | None = None,
    minute: str | None = None,
    second: str | None = None,
    fraction: str | None = None,
    zone: str | None = None,
) -> str | None:
    """ISO 8601 from the parts a file gives, as far as it gives them; None for an impossible
    date or one of all zeros (EXIF's "unknown")."""
    try:
        datetime(int(year), int(month or 1), int(day or 1), int(hour or 0), int(minute or 0))
    except ValueError:
        return None
    if int(second or 0) > 60 or int(year) == 0:
        return None
    text = year
    for separator, part in (("-", month), ("-", day), ("T", hour), (":", minute)):
        if part is None:
            return text
        text += separator + part
    text += f":{second or '00'}"
    if fraction:
        text += "." + fraction[:6]
    return text + offset(zone) if zone else text


def offset(zone: str) -> str:
    """ "Z" or "+HH:MM" from the notations of PDF ("+02'00'"), EXIF and W3CDTF."""
    if zone in ("Z", "z"):
        return "Z"
    digits = re.sub(r"\D", "", zone)
    return f"{zone[0]}{digits[:2]}:{(digits[2:4] or '00')}"


def parse_iso(value: Value | None) -> datetime | None:
    """A stored ISO 8601 date with its zone as a datetime; None without a zone or unreadable."""
    if not isinstance(value, str) or not re.search(r"(Z|[+-]\d{2}:\d{2})$", value):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# What the summary takes, in order: the first field found wins.
_AUTHORS = (
    ("exif", "artist"),
    ("exif", "xp_author"),
    ("pdf", "author"),
    ("xmp", "creator"),
    ("office", "creator"),
    ("odf", "initial_creator"),
    ("png", "Author"),
)
_MODIFIERS = (("office", "last_modified_by"), ("odf", "creator"))
_PROGRAMS = (
    ("exif", "software"),
    ("pdf", "creator"),
    ("xmp", "creator_tool"),
    ("pdf", "producer"),
    ("xmp", "producer"),
    ("office", "application"),
    ("odf", "generator"),
    ("png", "Software"),
)
_CREATED = (
    ("exif", "datetime_original"),
    ("exif", "datetime_digitized"),
    ("xmp", "create_date"),
    ("pdf", "creation_date"),
    ("office", "created"),
    ("odf", "creation_date"),
)


def summarize(fields: Fields) -> Summary:
    """The summary of a document's fields (see the orders above); the device is the camera or
    scanner, Make and Model, the make once when the model already names it."""

    def first(keys: Iterable[tuple[str, str]]) -> Value | None:
        for source, key in keys:
            value = fields.get(source, {}).get(key)
            if value:
                return value
        return None

    def text(keys: Iterable[tuple[str, str]]) -> str | None:
        value = first(keys)
        if isinstance(value, list):
            return ", ".join(value) or None
        return None if value is None else str(value)

    exif = fields.get("exif", {})
    make, model = (str(exif.get(key, "")) for key in ("make", "model"))
    device = model if make.lower() in model.lower() else f"{make} {model}"
    created = next(
        (date for source, key in _CREATED if (date := parse_iso(fields.get(source, {}).get(key)))),
        None,
    )
    gps = fields.get("gps", {})
    return Summary(
        author=text(_AUTHORS),
        modified_by=text(_MODIFIERS),
        program=text(_PROGRAMS),
        device=device.strip() or None,
        created=created,
        gps="latitude" in gps and "longitude" in gps,
    )


# Formats whose metadata is read (metadata.READERS), by the name kinds.classify gives them.
OFFICE_FORMATS = frozenset({"docx", "xlsx", "pptx", "odt", "ods", "odp"})


def may_carry(kind: DocumentKind | None, name: str | None, mime_type: str) -> bool:
    """Whether a document may carry metadata Mailrobbe reads, before reading it: images and PDFs
    by their kind (which the extraction confirms by the first bytes), office files by name or
    type. The reader decides by the first bytes again."""
    if kind in (DocumentKind.IMAGE, DocumentKind.PDF):
        return True
    if kind not in (DocumentKind.DOCUMENT, DocumentKind.SPREADSHEET, DocumentKind.PRESENTATION):
        return False
    return classify(name, mime_type).name in OFFICE_FORMATS

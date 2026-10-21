"""iCalendar parts as the calendar phase reads them (D154): every VEVENT of every VCALENDAR.

The content lines go through the helpers of the text extraction (attachments.extract.plain:
unfold, parameters, property_value), so one reading of iCalendar exists. parse_calendar reads one
iCalendar text; message_events walks a mail's MIME tree, attached mails included, and parses its
calendar parts: text/calendar and application/ics parts, inline in a multipart/alternative as
Outlook sends them or attached, files named .ics or .vcs, and text parts holding a calendar.

Nothing here raises on bad input: folded lines, quoted parameters, unknown charsets, missing END
lines and garbage give the events that could be read. Only the properties of the VEVENT itself
count (a VALARM's DESCRIPTION does not), and a calendar's METHOD holds for all its events.

Times are kept as written (wall time and TZID) and, when the zone is known, as an instant in
UTC: a time ending in Z, a TZID that is an IANA name (also behind a path such as Lightning's
"/mozilla.org/20070129_1/Europe/Berlin"), a Windows zone name ("W. Europe Standard Time") or an
Outlook display name ("(UTC+01:00) Amsterdam, Berlin, ..."). A VTIMEZONE is not evaluated: a zone
no table knows gives no instant. All-day events (VALUE=DATE) have no instant.
"""

import email.parser
import email.policy
import functools
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import Message
from zoneinfo import ZoneInfo

from mailrobbe.attachments.extract.plain import parameters, property_value, unfold
from mailrobbe.ical.model import (
    ATTENDEE_LIMIT,
    CALENDAR_MARK,
    CALENDAR_SUFFIXES,
    CALENDAR_TYPES,
    DESCRIPTION_LIMIT,
    EVENT_LIMIT,
    TEXT_LIMIT,
    EventKind,
    event_kind,
)
from mailrobbe.importer import text as mailtext
from mailrobbe.importer.parse import part_payload

_PARSER = email.parser.BytesParser(policy=email.policy.compat32)
_TIME = re.compile(r"(\d{4})-?(\d\d)-?(\d\d)(?:[T ](\d\d):?(\d\d)(?::?(\d\d))?(?:\.\d+)?(Z)?)?")
_DURATION = re.compile(
    r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", re.IGNORECASE
)
_INTEGER = re.compile(r"[+-]?\d{1,9}")  # fits calendar_event.sequence
_DISPLAY_NAME = re.compile(r"\((?:UTC|GMT)[^)]*\)\s*([^,]+)")


@dataclass(frozen=True, slots=True)
class ParsedAttendee:
    """An ORGANIZER or ATTENDEE as the part names it."""

    email: str | None  # lower case, from mailto: (else the EMAIL parameter); None: no address
    name: str | None  # CN, unless it only repeats the address
    role: str | None  # ROLE, upper case
    partstat: str | None  # PARTSTAT, upper case


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    """One VEVENT (D154), the columns of calendar_event and its attendees."""

    method: str | None  # METHOD of its calendar, upper case
    uid: str | None
    sequence: int | None
    status: str | None  # upper case
    summary: str | None
    location: str | None
    description: str | None  # at most DESCRIPTION_LIMIT characters
    starts_local: datetime | None  # wall time as written; midnight of an all-day date
    ends_local: datetime | None  # DTEND, else DTSTART plus DURATION
    time_zone: str | None  # TZID as written; "UTC" for a time ending in Z
    starts_at: datetime | None  # the instant in UTC; None: floating, all day or zone unknown
    ends_at: datetime | None
    all_day: bool
    recurrence: str | None  # RRULE as written
    organizer: ParsedAttendee | None
    attendees: tuple[ParsedAttendee, ...]

    @property
    def kind(self) -> EventKind:
        return event_kind(self.method, self.status)


def parse_calendar(data: bytes | str) -> list[ParsedEvent]:
    """Every VEVENT of every VCALENDAR in an iCalendar text; bytes are read as UTF-8, invalid
    sequences replaced. At most EVENT_LIMIT events."""
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    reader = _Reader()
    for line in unfold(text.removeprefix("﻿")):
        split = _content_line(line)
        if split is not None:
            reader.line(*split)
    return reader.finish()[:EVENT_LIMIT]


def message_events(message: bytes) -> list[ParsedEvent]:
    """The events of a mail's calendar parts in document order, an event that two parts both
    carry (an inline part and its invite.ics) once. At most EVENT_LIMIT events."""
    found: dict[ParsedEvent, None] = {}
    for part in _PARSER.parsebytes(message).walk():
        if part.is_multipart() or not _calendar_part(part):
            continue
        data = part_payload(part, "calendar part", [])
        if part.get_content_type() == "text/plain" and CALENDAR_MARK.encode() not in data.upper():
            continue
        charset = part.get_content_charset()
        calendar: bytes | str = data
        if charset and charset.replace("-", "").lower() != "utf8":  # else UTF-8, as RFC 5545
            calendar = mailtext.decode_bytes(data, charset, "calendar part", [])
        for event in parse_calendar(calendar):
            found.setdefault(event)
            if len(found) >= EVENT_LIMIT:
                return list(found)
    return list(found)


def _calendar_part(part: Message) -> bool:
    if part.get_content_type() in (*CALENDAR_TYPES, "text/plain"):
        return True
    name = part.get_filename()
    return name is not None and name.strip().lower().endswith(CALENDAR_SUFFIXES)


def _content_line(line: str) -> tuple[str, dict[str, str], str] | None:
    """Name, parameters and raw value of a content line; the value starts at the first colon
    outside quotes, so a quoted TZID or SENT-BY may hold one."""
    quoted = False
    for at, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == ":" and not quoted:
            name, params = parameters(line[:at])
            return name, params, line[at + 1 :]
    return None


class _Reader:
    """The components of a text as they open and close; events collected per calendar."""

    def __init__(self) -> None:
        self.events: list[ParsedEvent] = []
        self.stack: list[str] = []  # open components, outermost first
        self.method: str | None = None
        self.pending: list[_Event] = []  # events of the open calendar, until its METHOD is known
        self.event: _Event | None = None

    def line(self, name: str, params: dict[str, str], raw: str) -> None:
        if name == "BEGIN":
            self._begin(raw.strip().upper())
        elif name == "END":
            self._end(raw.strip().upper())
        elif self.event is not None and self.stack[-1:] == ["VEVENT"]:
            self.event.add(name, params, raw)
        elif name == "METHOD" and self.stack[-1:] == ["VCALENDAR"]:
            self.method = _clean(raw).strip().upper() or None

    def finish(self) -> list[ParsedEvent]:
        self._close_calendar()
        return self.events

    def _begin(self, component: str) -> None:
        if component == "VCALENDAR":
            self._close_calendar()
            self.stack = ["VCALENDAR"]
        elif component == "VEVENT":
            self._close_event()
            self.stack = ["VCALENDAR", "VEVENT"] if "VCALENDAR" in self.stack else ["VEVENT"]
            self.event = _Event()
        else:
            self.stack.append(component)

    def _end(self, component: str) -> None:
        if component not in self.stack:
            return
        while self.stack:
            if self.stack.pop() == component:
                break
        if component == "VEVENT":
            self._close_event()
        elif component == "VCALENDAR":
            self._close_calendar()

    def _close_event(self) -> None:
        if self.event is not None:
            self.pending.append(self.event)
            self.event = None

    def _close_calendar(self) -> None:
        self._close_event()
        self.events += [event.parsed(self.method) for event in self.pending]
        self.pending = []
        self.method = None
        self.stack = []


class _Event:
    """The properties of one VEVENT as they come; the first of each kind counts."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[dict[str, str], str]] = {}
        self.attendees: list[ParsedAttendee] = []

    def add(self, name: str, params: dict[str, str], raw: str) -> None:
        if name == "ATTENDEE":
            if len(self.attendees) < ATTENDEE_LIMIT:
                self.attendees.append(_attendee(params, raw))
        else:
            self.values.setdefault(name, (params, raw))

    def parsed(self, method: str | None) -> ParsedEvent:
        start = self._time("DTSTART")
        end = self._time("DTEND")
        if start is not None and end is None:
            end = start.after(self._duration())
        organizer = self.values.get("ORGANIZER")
        return ParsedEvent(
            method=method,
            uid=self._text("UID"),
            sequence=self._integer("SEQUENCE"),
            status=(self._text("STATUS") or "").upper() or None,
            summary=self._text("SUMMARY"),
            location=self._text("LOCATION"),
            description=self._text("DESCRIPTION", DESCRIPTION_LIMIT),
            starts_local=start.local if start else None,
            ends_local=end.local if end else None,
            time_zone=start.zone if start else None,
            starts_at=start.instant if start else None,
            ends_at=end.instant if end else None,
            all_day=start.all_day if start else False,
            recurrence=self._text("RRULE", raw=True),
            organizer=_attendee(*organizer) if organizer else None,
            attendees=tuple(self.attendees),
        )

    def _text(self, name: str, limit: int = TEXT_LIMIT, raw: bool = False) -> str | None:
        found = self.values.get(name)
        if found is None:
            return None
        params, value = found
        value = _clean(value if raw else property_value(name, value, params)).strip()
        return value[:limit].rstrip() or None

    def _integer(self, name: str) -> int | None:
        value = (self._text(name, raw=True) or "").strip()
        return int(value) if _INTEGER.fullmatch(value) else None

    def _time(self, name: str) -> "_Time | None":
        found = self.values.get(name)
        return None if found is None else _time(*found)

    def _duration(self) -> timedelta | None:
        value = (self._text("DURATION", raw=True) or "").strip()
        match = _DURATION.fullmatch(value)
        if not match or not any(match.groups()[1:]):
            return None
        sign, weeks, days, hours, minutes, seconds = match.groups()
        amounts = [int(amount or 0) for amount in (weeks, days, hours, minutes, seconds)]
        try:
            span = timedelta(
                weeks=amounts[0],
                days=amounts[1],
                hours=amounts[2],
                minutes=amounts[3],
                seconds=amounts[4],
            )
        except OverflowError:
            return None
        return -span if sign == "-" else span


@dataclass(frozen=True, slots=True)
class _Time:
    local: datetime  # naive wall time
    zone: str | None
    instant: datetime | None
    all_day: bool

    def after(self, span: timedelta | None) -> "_Time | None":
        if span is None:
            return None
        try:
            local = self.local + span
            instant = None if self.instant is None else self.instant + span
        except OverflowError:
            return None
        return _Time(local, self.zone, instant, self.all_day)


def _time(params: dict[str, str], raw: str) -> _Time | None:
    """A DTSTART or DTEND: wall time, zone and instant (module docstring)."""
    match = _TIME.fullmatch(_clean(raw).strip())
    if not match:
        return None
    year, month, day, hour, minute, second, utc = match.groups()
    all_day = hour is None or params.get("VALUE", "").upper() == "DATE"
    try:
        local = datetime(int(year), int(month), int(day))
        if not all_day:
            local = local.replace(
                hour=int(hour), minute=int(minute), second=min(59, int(second or 0))
            )
    except ValueError:
        return None
    if all_day:
        return _Time(local, None, None, True)
    if utc:
        return _Time(local, "UTC", local.replace(tzinfo=UTC), False)
    name = _clean(params.get("TZID", "")).strip()[:TEXT_LIMIT] or None
    found = zone(name) if name else None
    instant = None
    if found is not None:
        try:
            instant = local.replace(tzinfo=found).astimezone(UTC)
        except (OverflowError, ValueError):
            instant = None
    return _Time(local, name, instant, False)


@functools.lru_cache(maxsize=256)
def zone(name: str) -> ZoneInfo | None:
    """The zone a TZID names (module docstring); None when no table knows it."""
    key = name.strip().strip('"')
    windows = WINDOWS_ZONES.get(key.lower())
    if windows is not None:
        return _zone_info(windows)
    display = _DISPLAY_NAME.match(key)
    if display is not None:
        city = display.group(1).strip().lower()
        return _zone_info(DISPLAY_CITIES[city]) if city in DISPLAY_CITIES else None
    if key.upper() in ("UTC", "GMT", "Z", "ETC/UTC"):
        return _zone_info("UTC")
    parts = [part for part in key.split("/") if part]
    for start in range(max(0, len(parts) - 3), len(parts)):  # a path ending in an IANA name
        found = _zone_info("/".join(parts[start:]))
        if found is not None:
            return found
    return None


def _zone_info(key: str) -> ZoneInfo | None:
    if not key or len(key) > 64 or not key.isascii() or key.startswith("."):
        return None
    try:
        return ZoneInfo(key)
    except (KeyError, ValueError, OSError):  # ZoneInfoNotFoundError is a KeyError
        return None


def _attendee(params: dict[str, str], raw: str) -> ParsedAttendee:
    value = _clean(raw).strip()
    if value.lower().startswith("mailto:"):
        address = value[7:]
    elif "@" in value and ":" not in value:
        address = value
    else:
        address = params.get("EMAIL", "")
    address = _clean(address).strip().strip("<>").lower()
    email = address[:TEXT_LIMIT] if "@" in address and " " not in address else None
    name = _clean(params.get("CN", "")).strip()[:TEXT_LIMIT] or None
    if name is not None and email is not None and name.lower() in (email, f"mailto:{email}"):
        name = None
    role = _clean(params.get("ROLE", "")).strip().upper()[:TEXT_LIMIT] or None
    partstat = _clean(params.get("PARTSTAT", "")).strip().upper()[:TEXT_LIMIT] or None
    return ParsedAttendee(email, name, role, partstat)


def _clean(value: str) -> str:
    return mailtext.clean(value)


# Windows zone names (as Outlook and Exchange write TZID) of Europe and the common ones elsewhere,
# lower case, with the IANA zone of their main city (CLDR's windowsZones).
WINDOWS_ZONES = {
    "w. europe standard time": "Europe/Berlin",
    "romance standard time": "Europe/Paris",
    "central europe standard time": "Europe/Budapest",
    "central european standard time": "Europe/Warsaw",
    "gmt standard time": "Europe/London",
    "greenwich standard time": "Atlantic/Reykjavik",
    "e. europe standard time": "Europe/Chisinau",
    "fle standard time": "Europe/Kiev",
    "gtb standard time": "Europe/Bucharest",
    "russian standard time": "Europe/Moscow",
    "kaliningrad standard time": "Europe/Kaliningrad",
    "belarus standard time": "Europe/Minsk",
    "turkey standard time": "Europe/Istanbul",
    "israel standard time": "Asia/Jerusalem",
    "egypt standard time": "Africa/Cairo",
    "south africa standard time": "Africa/Johannesburg",
    "w. central africa standard time": "Africa/Lagos",
    "morocco standard time": "Africa/Casablanca",
    "arabian standard time": "Asia/Dubai",
    "arab standard time": "Asia/Riyadh",
    "india standard time": "Asia/Kolkata",
    "china standard time": "Asia/Shanghai",
    "singapore standard time": "Asia/Singapore",
    "tokyo standard time": "Asia/Tokyo",
    "korea standard time": "Asia/Seoul",
    "aus eastern standard time": "Australia/Sydney",
    "e. australia standard time": "Australia/Brisbane",
    "w. australia standard time": "Australia/Perth",
    "new zealand standard time": "Pacific/Auckland",
    "eastern standard time": "America/New_York",
    "central standard time": "America/Chicago",
    "mountain standard time": "America/Denver",
    "pacific standard time": "America/Los_Angeles",
    "atlantic standard time": "America/Halifax",
    "e. south america standard time": "America/Sao_Paulo",
    "argentina standard time": "America/Argentina/Buenos_Aires",
    "utc": "UTC",
    "coordinated universal time": "UTC",
}

# The first city of Outlook's display names of the European zones ("(UTC+01:00) Amsterdam,
# Berlin, Bern, Rom, Stockholm, Wien"), German and English, lower case.
DISPLAY_CITIES = {
    "amsterdam": "Europe/Berlin",
    "brüssel": "Europe/Paris",
    "brussels": "Europe/Paris",
    "belgrad": "Europe/Budapest",
    "belgrade": "Europe/Budapest",
    "sarajevo": "Europe/Warsaw",
    "dublin": "Europe/London",
    "athen": "Europe/Bucharest",
    "athens": "Europe/Bucharest",
    "helsinki": "Europe/Kiev",
    "moskau": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "istanbul": "Europe/Istanbul",
}

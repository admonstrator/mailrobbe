"""Calendar invitations (D154): the meetings some personal mails invite to, and the answers,
updates and cancellations that follow in their threads, written as Outlook, a web calendar and
Apple Calendar write them.

The planner decides with a random stream of its own (meeting, moved, PARTSTATS and the shares)
and dresses mails it has made; its own draws keep reading them as made, so every other mail of
the plan is the same with or without invitations. A second stream of its own (addressed) gives
some meetings an address instead of a room: a postcode and its town, or a town alone (D243).
What a mail carries is PlannedMail.calendar (model.Invitation). Everything else is a pure
function of the plan, for the planner (subject, files) and the renderer (body_lines,
calendar_part, has_inline_part, truth):

    outlook  the text with "Wann:", "Ort:" and Outlook's rule, in multipart/alternative with an
             inline text/calendar part: the method as a parameter, the TZID a Windows zone name
             with its VTIMEZONE
    web      a text, the same inline part and an invite.ics attachment of the same calendar;
             times in UTC, a recurring meeting in its IANA zone; the organiser is an attendee
    apple    a short text and an invite.ics attachment; the TZID the IANA zone with VTIMEZONE

Calendar parts are 7bit or quoted-printable, never base64, so the invalid_base64 fault never
hits them. truth() is what the calendar phase must store for the event (model.EventTruth).
"""

import binascii
import random
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

from mailrobbe.generator import vocabulary as vocab
from mailrobbe.generator.model import (
    Address,
    AttachmentSpec,
    EventTruth,
    Invitation,
    Meeting,
    PlannedMail,
)
from mailrobbe.generator.population import ZONES, utc_offset

INVITATION_SHARE = 0.03  # new personal mails that invite to a meeting
ANSWER_SHARE = 0.75  # an attendee's mail in the thread answers the invitation
UPDATE_SHARE = 0.35  # the organiser's mail in the thread moves the meeting
CANCEL_SHARE = 0.25  # or cancels it; the thread then goes on without calendar parts
PARTSTATS = (("ACCEPTED", 0.6), ("DECLINED", 0.2), ("TENTATIVE", 0.2))
INVITE_FILE = "invite.ics"
OUTLOOK_RULE = "*~*~*~*~*~*~*~*~*~*"

_ALL_DAY_SHARE = 0.1
_RECURRING_SHARE = 0.15
_ROOM_SHARE = 0.3  # meetings of insiders that book a room
_ADDRESS_SHARE = 0.2  # meetings without a room at an address with its postcode and town
_TOWN_SHARE = 0.15  # or at a place in a town without a postcode

# The subject prefix of each kind of mail, German and English; the outlook style writes it into
# SUMMARY too, for answers and cancellations.
SUBJECT_PREFIXES = {
    "invitation": ("Einladung", "Invitation"),
    "update": ("Aktualisierte Einladung", "Updated invitation"),
    "cancel": ("Abgesagt", "Canceled"),
    "ACCEPTED": ("Angenommen", "Accepted"),
    "DECLINED": ("Abgelehnt", "Declined"),
    "TENTATIVE": ("Mit Vorbehalt angenommen", "Tentative"),
}
_KINDS = {"REQUEST": "request", "REPLY": "reply", "CANCEL": "cancel"}
_PRODIDS = {
    "outlook": "Microsoft Exchange Server 2010",
    "web": "-//Kalender//Webkalender 1.0//DE",
    "apple": "-//Apple Inc.//macOS 14.5//EN",
}
# Windows names of the population's zones, and their display names in Outlook's texts.
_WINDOWS = {
    "Europe/Berlin": (
        "W. Europe Standard Time",
        "Amsterdam, Berlin, Bern, Rom, Stockholm, Wien",
        "Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna",
    ),
    "Europe/London": (
        "GMT Standard Time",
        "Dublin, Edinburgh, Lissabon, London",
        "Dublin, Edinburgh, Lisbon, London",
    ),
    "America/New_York": (
        "Eastern Standard Time",
        "Eastern Time (USA und Kanada)",
        "Eastern Time (US & Canada)",
    ),
    "Asia/Kolkata": (
        "India Standard Time",
        "Chennai, Kolkata, Mumbai, New Delhi",
        "Chennai, Kolkata, Mumbai, New Delhi",
    ),
    "Asia/Tokyo": ("Tokyo Standard Time", "Osaka, Sapporo, Tokio", "Osaka, Sapporo, Tokyo"),
    "UTC": ("UTC", "Koordinierte Weltzeit", "Coordinated Universal Time"),
}
_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_TITLES_DE = (
    "Teamrunde", "Jour fixe", "Lenkungskreis {project}", "Projektrunde {project}",
    "Abteilungsrunde", "Abstimmung {project}", "Vorstandssitzung", "Budgetgespräch",
    "Kick-off {project}", "Statusbesprechung {project}",
)  # fmt: skip
_TITLES_EN = (
    "Team meeting", "Steering committee {project}", "Project meeting {project}", "Weekly sync",
    "Budget review", "Kick-off {project}", "Status call {project}",
)  # fmt: skip
_ALL_DAY_DE = (
    "Klausurtagung",
    "Sommerfest",
    "Strategietag",
    "Schulung",
    "Messe",
    "Betriebsausflug",
)
_ALL_DAY_EN = ("Offsite", "Summer party", "Strategy day", "Training", "Trade fair")
_PLACES_DE = (
    "Besprechungsraum {n}", "Raum {n}.{m}", "Videokonferenz", "Kantine, 1. OG",
    "Großer Saal", "Telefonkonferenz; Einwahl folgt",
)  # fmt: skip
_PLACES_EN = ("Meeting room {n}", "Room {n}.{m}", "Video call", "Board room", "Conference call")
# Towns of addresses with a postcode of their centre (GeoNames postal codes, D243).
_POSTCODES = (
    ("20095", "Hamburg"), ("28195", "Bremen"), ("30159", "Hannover"), ("10117", "Berlin"),
    ("04109", "Leipzig"), ("01067", "Dresden"), ("50667", "Köln"), ("40213", "Düsseldorf"),
    ("60311", "Frankfurt am Main"), ("70173", "Stuttgart"), ("80331", "München"),
    ("90403", "Nürnberg"), ("24103", "Kiel"), ("23552", "Lübeck"), ("48143", "Münster"),
    ("99423", "Weimar"), ("1010", "Wien"), ("8001", "Zürich"), ("3011", "Bern"), ("9490", "Vaduz"),
)  # fmt: skip
_VENUES = (
    "Rathaus", "Stadthalle", "Bürgerhaus", "Geschäftsstelle", "Tagungszentrum", "Hotel am Markt",
    "Gemeindesaal", "Vereinsheim",
)  # fmt: skip
_STREETS = ("Marktplatz", "Bahnhofstraße", "Hauptstraße", "Lindenallee", "Schillerstraße")
_AGENDA_DE = (
    "Rückblick, offene Punkte", "Stand der Arbeiten", "Budget; Freigaben", "Zeitplan",
    "Personal", "Termine und Fristen", "Risiken",
)  # fmt: skip
_AGENDA_EN = ("Review, open items", "Progress", "Budget; approvals", "Schedule", "Risks")
_COMMENTS = {
    "ACCEPTED": (("Ich komme gern.", "Bin dabei."), ("See you there.", "Works for me.")),
    "DECLINED": (("Leider kann ich an dem Termin nicht.",), ("Sorry, I cannot make it.",)),
    "TENTATIVE": (("Ich versuche, es einzurichten.",), ("I will try to make it.",)),
}
_WEEKDAYS_SHORT_DE = ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")


# Planning (the planner's random stream) ---------------------------------------------------------


def style(client: str) -> str:
    """How the mail program of a mail writes calendar parts."""
    if client == "outlook":
        return "outlook"
    return "apple" if client in ("apple", "mobile") else "web"


def meeting(
    rng: random.Random, mail: PlannedMail, organizer: int, zone: str, room_domain: str | None
) -> Meeting:
    """A meeting the new mail invites its recipients to, one to three weeks after it is sent,
    on a working day; `room_domain` is the organisation's domain when a room may be booked."""
    german = mail.language == "de"
    all_day = rng.random() < _ALL_DAY_SHARE
    if all_day:
        title = rng.choice(_ALL_DAY_DE if german else _ALL_DAY_EN)
    else:
        title = rng.choice(_TITLES_DE if german else _TITLES_EN)
        title = title.format(project=rng.choice(vocab.PROJECTS))
    day = mail.date.date() + timedelta(days=rng.randint(7, 21))
    if day.weekday() >= 5:
        day += timedelta(days=7 - day.weekday())
    rule = None
    if all_day:
        start = datetime.combine(day, time())
        end = start + timedelta(days=rng.choice((1, 1, 2)))
    else:
        start = datetime.combine(day, time(rng.randint(8, 16), rng.choice((0, 0, 0, 15, 30))))
        end = start + timedelta(minutes=rng.choice((30, 45, 60, 60, 90, 120)))
        if rng.random() < _RECURRING_SHARE:
            rule = _rule(rng, start)
    number = rng.randint(1, 9)
    place = rng.choice(_PLACES_DE if german else _PLACES_EN)
    location = place.format(n=number, m=rng.randint(1, 20))
    rooms: tuple[Address, ...] = ()
    if room_domain is not None and rng.random() < _ROOM_SHARE:
        name = f"Besprechungsraum {number}" if german else f"Meeting room {number}"
        rooms, location = (Address(f"raum.{number}@{room_domain}", name),), name
    return Meeting(
        uid=_uid(rng, style(mail.client)),
        title=title,
        location=location,
        description=_description(rng, title, mail.sender, german),
        zone=zone,
        start=start,
        end=end,
        all_day=all_day,
        rule=rule,
        organizer=mail.sender,
        organizer_person=organizer,
        attendees=(*mail.to, *mail.cc),
        rooms=rooms,
    )


def addressed(rng: random.Random, meeting: Meeting) -> Meeting:
    """The meeting at an address (_ADDRESS_SHARE: venue, street, postcode and town) or at a
    place in a town (_TOWN_SHARE), unless it books a room; else as it is."""
    draw = rng.random()
    if meeting.rooms or draw >= _ADDRESS_SHARE + _TOWN_SHARE:
        return meeting
    venue = rng.choice(_VENUES)
    postcode, town = rng.choice(_POSTCODES)
    if draw < _ADDRESS_SHARE:
        location = f"{venue}, {rng.choice(_STREETS)} {rng.randint(1, 60)}, {postcode} {town}"
    else:
        location = f"{venue}, {town}" if rng.random() < 0.5 else f"{venue} {town}"
    return replace(meeting, location=location, place=town)


def moved(rng: random.Random, meeting: Meeting) -> Meeting:
    """The meeting moved to another day or hour, as an update (SEQUENCE one higher) sends it."""
    if meeting.all_day or rng.random() < 0.5:
        shift = timedelta(days=rng.choice((-2, -1, 1, 2, 7)))
    else:
        shift = timedelta(minutes=rng.choice((-60, -30, 30, 60, 120)))
    return replace(
        meeting,
        start=meeting.start + shift,
        end=meeting.end + shift,
        sequence=meeting.sequence + 1,
    )


def _rule(rng: random.Random, start: datetime) -> str:
    day = _DAYS[start.weekday()]
    return rng.choice(
        (
            f"FREQ=WEEKLY;BYDAY={day}",
            f"FREQ=WEEKLY;BYDAY={day};COUNT={rng.randint(4, 12)}",
            f"FREQ=WEEKLY;INTERVAL=2;BYDAY={day}",
            f"FREQ=MONTHLY;BYMONTHDAY={start.day};COUNT=6",
        )
    )


def _uid(rng: random.Random, written_by: str) -> str:
    if written_by == "outlook":
        return f"040000008200E00074C5B7101A82E00800000000{rng.getrandbits(192):048X}"
    if written_by == "apple":
        text = f"{rng.getrandbits(128):032X}"
        return f"{text[:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:]}"
    return f"{rng.getrandbits(104):026x}@kalender.example"


def _description(rng: random.Random, title: str, organizer: Address, german: bool) -> str:
    items = rng.sample(_AGENDA_DE if german else _AGENDA_EN, 2)
    name = (organizer.display_name or organizer.email).split(", ")[-1].split()[0]
    if german:
        return (
            f"Hallo zusammen,\n\nanbei die Einladung zum Termin „{title}“.\n\nTagesordnung:\n"
            f"1. {items[0]}\n2. {items[1]}\n3. Verschiedenes\n\nViele Grüße\n{name}"
        )
    return (
        f"Hi all,\n\nplease find the invitation to “{title}”.\n\nAgenda:\n"
        f"1. {items[0]}\n2. {items[1]}\n3. Any other business\n\nBest regards\n{name}"
    )


# What a mail carries ------------------------------------------------------------------------


def subject(invitation: Invitation, language: str) -> str:
    return f"{_prefix(invitation, language)}: {invitation.meeting.title}"


def files(mail: PlannedMail) -> tuple[AttachmentSpec, ...]:
    """The invite.ics a web calendar or Apple Calendar attaches; Outlook attaches none."""
    if mail.calendar is None or mail.calendar.style == "outlook":
        return ()
    data = calendar_text(mail).encode()
    return (AttachmentSpec(INVITE_FILE, "application/ics", len(data), content=data),)


def has_inline_part(invitation: Invitation) -> bool:
    """Whether the text and the calendar are alternatives of the body (Outlook, web)."""
    return invitation.style != "apple"


def calendar_part(mail: PlannedMail) -> tuple[str, str, bytes]:
    """The inline text/calendar part: its method, transfer encoding and body."""
    assert mail.calendar is not None
    encoding, body = encoded(calendar_text(mail))
    return mail.calendar.method, encoding, body


def encoded(text: str) -> tuple[str, bytes]:
    """A calendar as a part body: 7bit, or quoted-printable when it is not ASCII."""
    data = text.encode()
    if data.isascii():
        return "7bit", data
    return "quoted-printable", binascii.b2a_qp(data)


def truth(mail: PlannedMail) -> EventTruth:
    invitation = mail.calendar
    assert invitation is not None
    meeting = invitation.meeting
    if meeting.all_day:
        start = meeting.start.date().isoformat()
    else:
        start = _instant(meeting.zone, meeting.start).isoformat()
    return EventTruth(
        method=invitation.method,
        uid=meeting.uid,
        sequence=meeting.sequence,
        kind=_KINDS[invitation.method],
        summary=_summary(invitation, mail.language),
        start=start,
        attendees=len(_attendees(invitation)),
        place=None if invitation.method == "REPLY" else meeting.place,  # a reply has no LOCATION
    )


def _prefix(invitation: Invitation, language: str) -> str:
    if invitation.method == "REPLY":
        key = invitation.partstat or "ACCEPTED"
    elif invitation.method == "CANCEL":
        key = "cancel"
    else:
        key = "update" if invitation.meeting.sequence else "invitation"
    german, english = SUBJECT_PREFIXES[key]
    return german if language == "de" else english


def _summary(invitation: Invitation, language: str) -> str:
    if invitation.style == "outlook" and invitation.method != "REQUEST":
        return subject(invitation, language)
    return invitation.meeting.title


def _instant(zone: str, wall: datetime) -> datetime:
    """The UTC instant of a wall time in a zone (meetings never start in a skipped hour)."""
    local = wall.replace(tzinfo=UTC)
    return local - utc_offset(zone, local - timedelta(minutes=ZONES[zone].base))


# iCalendar ----------------------------------------------------------------------------------


def calendar_text(mail: PlannedMail) -> str:
    """The calendar of the mail as its program writes it, LF line ends, folded at 75."""
    invitation = mail.calendar
    assert invitation is not None
    meeting, written_by, method = invitation.meeting, invitation.style, invitation.method
    outlook = written_by == "outlook"
    lines = ["BEGIN:VCALENDAR"]
    if outlook:
        lines += [f"METHOD:{method}", f"PRODID:{_PRODIDS[written_by]}", "VERSION:2.0"]
    else:
        lines += [f"PRODID:{_PRODIDS[written_by]}", "VERSION:2.0", "CALSCALE:GREGORIAN"]
        lines.append(f"METHOD:{method}")
    tzid = _tzid(invitation)
    if tzid is not None:
        lines += _vtimezone(tzid, meeting.zone)
    language = ";LANGUAGE=de-DE" if outlook and mail.language == "de" else ""
    lines += ["BEGIN:VEVENT", _address("ORGANIZER", meeting.organizer, outlook, "")]
    lines += _attendees(invitation)
    if method == "REQUEST":
        lines.append(f"DESCRIPTION{language}:{_text(meeting.description)}")
    lines += [
        f"UID:{meeting.uid}",
        f"SUMMARY{language}:{_text(_summary(invitation, mail.language))}",
        *_times(meeting, tzid),
    ]
    if meeting.rule is not None:
        lines.append(f"RRULE:{meeting.rule}")
    lines.append(f"SEQUENCE:{meeting.sequence}")
    if method != "REPLY":
        lines.append(f"STATUS:{'CANCELLED' if method == 'CANCEL' else 'CONFIRMED'}")
        lines.append(f"LOCATION{language}:{_text(meeting.location)}")
    lines.append(f"DTSTAMP:{mail.date.astimezone(UTC):%Y%m%dT%H%M%SZ}")
    if outlook:
        lines.append(f"X-MICROSOFT-CDO-ALLDAYEVENT:{'TRUE' if meeting.all_day else 'FALSE'}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "".join(_fold(line) + "\n" for line in lines)


def _attendees(invitation: Invitation) -> list[str]:
    """The ATTENDEE lines: the one who answers in a reply, else everybody invited."""
    outlook = invitation.style == "outlook"
    if invitation.method == "REPLY":
        assert invitation.answer is not None
        return [_address("ATTENDEE", invitation.answer, outlook, f"PARTSTAT={invitation.partstat}")]
    meeting = invitation.meeting
    lines = []
    if invitation.style == "web":  # the web calendar lists the organiser, who goes
        params = "CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;RSVP=TRUE"
        lines.append(_address("ATTENDEE", meeting.organizer, False, params))
    for attendee in meeting.attendees:
        params = "ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE"
        lines.append(_address("ATTENDEE", attendee, outlook, params))
    for room in meeting.rooms:
        params = "CUTYPE=ROOM;ROLE=NON-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE"
        lines.append(_address("ATTENDEE", room, outlook, params))
    return lines


def _address(name: str, address: Address, outlook: bool, params: str) -> str:
    """ORGANIZER or ATTENDEE with CN (quoted where it must be) and the mailto address."""
    cn = (address.display_name or address.email).replace('"', "")
    if any(char in cn for char in ",;:"):
        cn = f'"{cn}"'
    head = ";".join(part for part in (name, params, f"CN={cn}") if part)
    return f"{head}:{'MAILTO' if outlook else 'mailto'}:{address.email}"


def _tzid(invitation: Invitation) -> str | None:
    """The TZID the times are written in; None for dates and times in UTC."""
    meeting = invitation.meeting
    if meeting.all_day or (invitation.style == "web" and meeting.rule is None):
        return None
    if invitation.style == "outlook":
        return _WINDOWS[meeting.zone][0]
    return meeting.zone


def _times(meeting: Meeting, tzid: str | None) -> list[str]:
    if meeting.all_day:
        return [
            f"DTSTART;VALUE=DATE:{meeting.start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{meeting.end:%Y%m%d}",
        ]
    if tzid is None:
        start, end = _instant(meeting.zone, meeting.start), _instant(meeting.zone, meeting.end)
        return [f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}"]
    return [
        f"DTSTART;TZID={tzid}:{meeting.start:%Y%m%dT%H%M%S}",
        f"DTEND;TZID={tzid}:{meeting.end:%Y%m%dT%H%M%S}",
    ]


def _vtimezone(tzid: str, zone: str) -> list[str]:
    """The zone's definition with the rules population.utc_offset applies."""
    spec = ZONES[zone]
    standard, daylight = _offset(spec.base), _offset(spec.base + 60)
    lines = ["BEGIN:VTIMEZONE", f"TZID:{tzid}"]
    if not spec.dst:
        lines += ["BEGIN:STANDARD", "DTSTART:16010101T000000"]
        lines += [f"TZOFFSETFROM:{standard}", f"TZOFFSETTO:{standard}", "END:STANDARD"]
        return [*lines, "END:VTIMEZONE"]
    if spec.dst == "eu":
        back, forward = ("19701025T030000", "10;BYDAY=-1SU"), ("19700329T020000", "3;BYDAY=-1SU")
    else:
        back, forward = ("19701101T020000", "11;BYDAY=1SU"), ("19700308T020000", "3;BYDAY=2SU")
    for kind, (start, rule), before, after in (
        ("STANDARD", back, daylight, standard),
        ("DAYLIGHT", forward, standard, daylight),
    ):
        lines += [f"BEGIN:{kind}", f"DTSTART:{start}", f"TZOFFSETFROM:{before}"]
        lines += [f"TZOFFSETTO:{after}", f"RRULE:FREQ=YEARLY;BYMONTH={rule}", f"END:{kind}"]
    return [*lines, "END:VTIMEZONE"]


def _offset(minutes: int) -> str:
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}{rest:02d}"


def _text(value: str) -> str:
    """An iCalendar text value: backslash, semicolon, comma and line breaks escaped."""
    escaped = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return escaped.replace("\n", "\\n")


def _fold(line: str) -> str:
    if len(line) <= 75:
        return line
    return "\n ".join([line[:75], *(line[i : i + 74] for i in range(75, len(line), 74))])


# The text of the mail -----------------------------------------------------------------------


def body_lines(mail: PlannedMail, rng: random.Random) -> list[str]:
    """The text part of a calendar mail as its program writes it."""
    invitation = mail.calendar
    assert invitation is not None
    german = mail.language == "de"
    if invitation.style == "outlook":
        return _outlook_text(invitation, german, rng)
    if invitation.style == "web":
        return _web_text(invitation, german)
    return _apple_text(invitation, german)


def _outlook_text(invitation: Invitation, german: bool, rng: random.Random) -> list[str]:
    meeting = invitation.meeting
    if invitation.method == "REPLY":
        assert invitation.partstat is not None
        comments = _COMMENTS[invitation.partstat][0 if german else 1]
        return [rng.choice(comments)]  # never empty: every generated mail has a text
    lines = [
        f"{'Wann' if german else 'When'}: {_outlook_when(meeting, german)}",
        f"{'Ort' if german else 'Where'}: {meeting.location}",
        "",
        OUTLOOK_RULE,
        "",
    ]
    if invitation.method == "CANCEL":
        return [*lines, "Der Termin wurde abgesagt." if german else "The meeting was canceled."]
    return [*lines, *meeting.description.split("\n")]


def _outlook_when(meeting: Meeting, german: bool) -> str:
    names = _WINDOWS[meeting.zone]
    base = ZONES[meeting.zone].base
    hours, minutes = divmod(abs(base), 60)
    offset = (
        "UTC"
        if meeting.zone == "UTC"
        else f"UTC{'-' if base < 0 else '+'}{hours:02d}:{minutes:02d}"
    )
    zone = f"({offset}) {names[1] if german else names[2]}"
    start, end = meeting.start, meeting.end
    if meeting.all_day:
        return f"{_long_date(start, german)} ({'ganztägig' if german else 'all day'}). {zone}"
    span = f"{start:%H:%M}-{end:%H:%M}"
    if meeting.rule is None:
        return f"{_long_date(start, german)} {span} {zone}."
    weekday = (vocab.WEEKDAYS_DE if german else vocab.WEEKDAYS_EN)[start.weekday()]
    if german:
        every = "Alle 2 Wochen" if "INTERVAL=2" in meeting.rule else "Wöchentlich"
        if meeting.rule.startswith("FREQ=MONTHLY"):
            return f"Monatlich am {start.day}. von {span} ab {start:%d.%m.%Y}. {zone}"
        return f"{every} am {weekday} von {span} ab {start:%d.%m.%Y}. {zone}"
    if meeting.rule.startswith("FREQ=MONTHLY"):
        return f"Occurs day {start.day} of every month {span} from {start:%Y-%m-%d}. {zone}"
    every = "every 2 weeks on" if "INTERVAL=2" in meeting.rule else "every"
    return f"Occurs {every} {weekday} {span} from {start:%Y-%m-%d}. {zone}"


def _long_date(day: datetime, german: bool) -> str:
    if german:
        weekday = vocab.WEEKDAYS_DE[day.weekday()]
        return f"{weekday}, {day.day}. {vocab.MONTHS_DE[day.month - 1]} {day.year}"
    weekday = vocab.WEEKDAYS_EN[day.weekday()]
    return f"{weekday}, {vocab.MONTHS_EN[day.month - 1]} {day.day}, {day.year}"


def _web_text(invitation: Invitation, german: bool) -> list[str]:
    meeting = invitation.meeting
    if invitation.method == "REPLY":
        assert invitation.answer is not None and invitation.partstat is not None
        name = invitation.answer.display_name or invitation.answer.email
        done = {
            "ACCEPTED": ("angenommen", "accepted"),
            "DECLINED": ("abgelehnt", "declined"),
            "TENTATIVE": ("mit Vorbehalt angenommen", "tentatively accepted"),
        }[invitation.partstat]
        intro = (
            f"{name} hat diese Einladung {done[0]}."
            if german
            else f"{name} has {done[1]} this invitation."
        )
    elif invitation.method == "CANCEL":
        intro = (
            "Dieser Termin wurde abgesagt und aus Ihrem Kalender entfernt."
            if german
            else "This event has been canceled and removed from your calendar."
        )
    elif meeting.sequence:
        intro = "Dieser Termin wurde geändert." if german else "This event has been changed."
    else:
        intro = (
            "Sie wurden zu folgendem Termin eingeladen."
            if german
            else "You have been invited to the following event."
        )
    start, end = meeting.start, meeting.end
    if meeting.all_day:
        when = _short_date(start, german)
    else:
        when = f"{_short_date(start, german)} {start:%H:%M} - {end:%H:%M} ({meeting.zone})"
    guests = [
        f"* {meeting.organizer.display_name or meeting.organizer.email} - "
        + ("Organisator" if german else "organizer"),
        *(f"* {a.display_name or a.email}" for a in (*meeting.attendees, *meeting.rooms)),
    ]
    lines = [
        intro,
        "",
        meeting.title,
        f"{'Wann' if german else 'When'}: {when}",
        f"{'Wo' if german else 'Where'}: {meeting.location}",
        "Teilnehmer:" if german else "Guests:",
        *guests,
    ]
    if invitation.method == "REQUEST":
        lines += ["", *meeting.description.split("\n")]
    footer = "Einladung von Kalender" if german else "Invitation from Calendar"
    return [*lines, "", footer]


def _short_date(day: datetime, german: bool) -> str:
    if german:
        weekday = _WEEKDAYS_SHORT_DE[day.weekday()]
        return f"{weekday} {day.day}. {vocab.MONTHS_DE[day.month - 1]} {day.year}"
    weekday = vocab.WEEKDAYS_EN[day.weekday()][:3]
    return f"{weekday} {vocab.MONTHS_EN[day.month - 1][:3]} {day.day}, {day.year}"


def _apple_text(invitation: Invitation, german: bool) -> list[str]:
    meeting = invitation.meeting
    title = f"„{meeting.title}“" if german else f"“{meeting.title}”"
    if invitation.method == "REPLY":
        assert invitation.answer is not None and invitation.partstat is not None
        name = invitation.answer.display_name or invitation.answer.email
        if german:
            done = {"ACCEPTED": "angenommen", "DECLINED": "abgelehnt"}.get(
                invitation.partstat, "vorläufig angenommen"
            )
            return [f"{name} hat die Einladung zu {title} {done}."]
        done = {"ACCEPTED": "accepted", "DECLINED": "declined"}.get(
            invitation.partstat, "tentatively accepted"
        )
        return [f"{name} has {done} the invitation to {title}."]
    if invitation.method == "CANCEL":
        return [f"{title} wurde abgesagt." if german else f"{title} has been canceled."]
    name = meeting.organizer.display_name or meeting.organizer.email
    when = _long_date(meeting.start, german)
    if not meeting.all_day:
        when += f", {meeting.start:%H:%M}"
    if german:
        return [f"{name} hat Sie zu {title} eingeladen.", "", when, meeting.location]
    return [f"{name} has invited you to {title}.", "", when, meeting.location]

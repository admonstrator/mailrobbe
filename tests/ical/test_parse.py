"""The iCalendar reader of the calendar phase (D154) on parts shaped like those real clients send:
Outlook (Windows zone names, X-MICROSOFT fields, MAILTO in capitals, a VALARM), a web calendar
(times in UTC, CN repeating the address, folded lines), Apple Calendar (IANA zones, quoted
names, the EMAIL parameter), answers, cancellations, all-day and recurring events, and broken
input that must not raise."""

import base64
from datetime import UTC, datetime

import pytest

from mailrobbe.ical.model import DESCRIPTION_LIMIT, EVENT_LIMIT
from mailrobbe.ical.parse import (
    ParsedAttendee,
    ParsedEvent,
    message_events,
    parse_calendar,
    zone,
)

OUTLOOK = """BEGIN:VCALENDAR
METHOD:REQUEST
PRODID:Microsoft Exchange Server 2010
VERSION:2.0
BEGIN:VTIMEZONE
TZID:W. Europe Standard Time
BEGIN:STANDARD
DTSTART:16010101T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
ORGANIZER;CN="Müller, Hans":MAILTO:Hans.Mueller@nordlicht-gmbh.example
ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE;CN=Anna Keller:
 MAILTO:anna.keller@nordlicht-gmbh.example
ATTENDEE;ROLE=OPT-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE;CN=jonas@elbtal
 .example:MAILTO:jonas@elbtal.example
DESCRIPTION;LANGUAGE=de-DE:Hallo zusammen\\,\\n\\nbitte bringt die Zahlen mit\\; d
 anke.\\n
UID:040000008200E00074C5B7101A82E00800000000F0C1A7B2D35BDA01000000000000000010
 000000C1D3A7F38A0B5D4FBA2C0E3D5E1F8A11
SUMMARY;LANGUAGE=de-DE:Vorstandssitzung
DTSTART;TZID=W. Europe Standard Time:20240715T100000
DTEND;TZID=W. Europe Standard Time:20240715T113000
CLASS:PUBLIC
PRIORITY:5
DTSTAMP:20240708T091500Z
TRANSP:OPAQUE
STATUS:CONFIRMED
SEQUENCE:0
LOCATION;LANGUAGE=de-DE:Besprechungsraum 2
X-MICROSOFT-CDO-APPT-SEQUENCE:0
X-MICROSOFT-CDO-BUSYSTATUS:TENTATIVE
X-MICROSOFT-CDO-ALLDAYEVENT:FALSE
X-MS-OLK-CONFTYPE:0
BEGIN:VALARM
DESCRIPTION:REMINDER
TRIGGER;RELATED=START:-PT15M
ACTION:DISPLAY
END:VALARM
END:VEVENT
END:VCALENDAR
"""

WEB = (
    "BEGIN:VCALENDAR\r\nPRODID:-//Web Calendar//Calendar 70.9054//EN\r\nVERSION:2.0\r\n"
    "CALSCALE:GREGORIAN\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\n"
    "DTSTART:20240115T090000Z\r\nDTEND:20240115T100000Z\r\nDTSTAMP:20240110T120000Z\r\n"
    "ORGANIZER;CN=Hans Müller:mailto:hans@nordlicht-gmbh.example\r\n"
    "UID:5f3b2c1a9e7d@kalender.example\r\n"
    "ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;RSVP=TRUE\r\n"
    " ;CN=hans@nordlicht-gmbh.example;X-NUM-GUESTS=0:mailto:hans@nordlicht-gmbh.example\r\n"
    "ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=\r\n"
    " TRUE;CN=Anna Keller;X-NUM-GUESTS=0:mailto:anna@post.example\r\n"
    "CREATED:20240110T115900Z\r\nDESCRIPTION:Agenda folgt.\r\nLAST-MODIFIED:20240110T120000Z\r\n"
    "LOCATION:Hafenweg 12\\, 20457 Hamburg\r\nSEQUENCE:0\r\nSTATUS:CONFIRMED\r\n"
    "SUMMARY:Kick-off Nordlicht\r\nTRANSP:OPAQUE\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)

APPLE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Apple Inc.//macOS 14.2//EN
METHOD:REQUEST
CALSCALE:GREGORIAN
BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
DTSTART:19810329T020000
TZNAME:MESZ
TZOFFSETTO:+0200
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
TRANSP:OPAQUE
DTEND;TZID=Europe/Berlin:20240112T150000
UID:7A1E2B3C-4D5E-6F70-8192-A3B4C5D6E7F8
DTSTAMP:20240105T080000Z
LOCATION:Café am Markt
DESCRIPTION:
SEQUENCE:1
X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC
SUMMARY:Jour fixe
LAST-MODIFIED:20240105T080000Z
DTSTART;TZID=Europe/Berlin:20240112T140000
CREATED:20240105T075900Z
ORGANIZER;CN="Keller, Anna";EMAIL="anna@post.example":urn:uuid:
 0A1B2C3D-0000-1111-2222-333344445555
ATTENDEE;CN="Jonas Brandt";CUTYPE=INDIVIDUAL;EMAIL="jonas@elbtal.example";PARTS
 TAT=NEEDS-ACTION;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:jonas@elbtal.example
END:VEVENT
END:VCALENDAR
"""

REPLY = """BEGIN:VCALENDAR
METHOD:REPLY
PRODID:Microsoft Exchange Server 2010
VERSION:2.0
BEGIN:VEVENT
ATTENDEE;PARTSTAT=ACCEPTED;CN=Anna Keller:MAILTO:anna.keller@nordlicht-gmbh.example
COMMENT;LANGUAGE=de-DE:\\n
SUMMARY;LANGUAGE=de-DE:Angenommen: Vorstandssitzung
DTSTART;TZID=W. Europe Standard Time:20240715T100000
DTEND;TZID=W. Europe Standard Time:20240715T113000
UID:040000008200E00074C5B7101A82E00800000000F0C1A7B2D35BDA01000000000000000010
 000000C1D3A7F38A0B5D4FBA2C0E3D5E1F8A11
SEQUENCE:0
ORGANIZER;CN="Müller, Hans":MAILTO:Hans.Mueller@nordlicht-gmbh.example
END:VEVENT
END:VCALENDAR
"""

CANCEL = """BEGIN:VCALENDAR
METHOD:CANCEL
VERSION:2.0
BEGIN:VEVENT
UID:abc-1@kalender.example
SEQUENCE:2
STATUS:CANCELLED
SUMMARY:Abgesagt: Kassenprüfung
DTSTART;TZID="(UTC+01:00) Amsterdam, Berlin, Bern, Rom, Stockholm, Wien":20240305T090000
DURATION:PT2H
ORGANIZER;CN=Kasse;SENT-BY="mailto:assistenz@verein.example":mailto:kasse@verein.example
END:VEVENT
END:VCALENDAR
"""

ALL_DAY_RECURRING = """BEGIN:VCALENDAR
VERSION:2.0
METHOD:PUBLISH
BEGIN:VEVENT
UID:fest@verein.example
SUMMARY:Sommerfest
DTSTART;VALUE=DATE:20240720
DTEND;VALUE=DATE:20240721
END:VEVENT
BEGIN:VEVENT
UID:runde@verein.example
SUMMARY:Teamrunde
DTSTART;TZID=/mozilla.org/20070129_1/Europe/Berlin:20240108T090000
DTEND;TZID=/mozilla.org/20070129_1/Europe/Berlin:20240108T093000
RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10
END:VEVENT
END:VCALENDAR
"""


def _one(text: str | bytes) -> ParsedEvent:
    events = parse_calendar(text)
    assert len(events) == 1
    return events[0]


def test_an_outlook_invitation() -> None:
    [event] = parse_calendar(OUTLOOK)
    assert (event.method, event.kind, event.sequence, event.status) == (
        "REQUEST",
        "request",
        0,
        "CONFIRMED",
    )
    assert event.uid is not None and event.uid.startswith("040000008200E000")
    assert event.uid.endswith("C1D3A7F38A0B5D4FBA2C0E3D5E1F8A11")  # folded, joined again
    assert event.summary == "Vorstandssitzung"
    assert event.location == "Besprechungsraum 2"
    assert event.description == "Hallo zusammen,\n\nbitte bringt die Zahlen mit; danke."
    assert event.starts_local == datetime(2024, 7, 15, 10, 0)
    assert event.ends_local == datetime(2024, 7, 15, 11, 30)
    assert event.time_zone == "W. Europe Standard Time"
    assert event.starts_at == datetime(2024, 7, 15, 8, 0, tzinfo=UTC)  # summer time
    assert event.ends_at == datetime(2024, 7, 15, 9, 30, tzinfo=UTC)
    assert not event.all_day and event.recurrence is None
    assert event.organizer == ParsedAttendee(
        "hans.mueller@nordlicht-gmbh.example", "Müller, Hans", None, None
    )
    assert event.attendees == (
        ParsedAttendee(
            "anna.keller@nordlicht-gmbh.example", "Anna Keller", "REQ-PARTICIPANT", "NEEDS-ACTION"
        ),
        ParsedAttendee("jonas@elbtal.example", None, "OPT-PARTICIPANT", "NEEDS-ACTION"),
    )


def test_a_web_calendar_invitation_in_utc() -> None:
    [event] = parse_calendar(WEB.encode())
    assert (event.kind, event.uid, event.summary) == (
        "request",
        "5f3b2c1a9e7d@kalender.example",
        "Kick-off Nordlicht",
    )
    assert event.time_zone == "UTC"
    assert event.starts_local == datetime(2024, 1, 15, 9, 0)
    assert event.starts_at == datetime(2024, 1, 15, 9, 0, tzinfo=UTC)
    assert event.location == "Hafenweg 12, 20457 Hamburg"
    assert event.organizer is not None and event.organizer.name == "Hans Müller"
    assert [(a.email, a.name, a.partstat) for a in event.attendees] == [
        ("hans@nordlicht-gmbh.example", None, "ACCEPTED"),  # CN only repeated the address
        ("anna@post.example", "Anna Keller", "NEEDS-ACTION"),
    ]


def test_an_apple_invitation() -> None:
    [event] = parse_calendar(APPLE)
    assert (event.sequence, event.summary, event.location) == (1, "Jour fixe", "Café am Markt")
    assert event.description is None
    assert event.time_zone == "Europe/Berlin"
    assert event.starts_at == datetime(2024, 1, 12, 13, 0, tzinfo=UTC)  # winter time
    assert event.ends_at == datetime(2024, 1, 12, 14, 0, tzinfo=UTC)
    # no mailto: the EMAIL parameter names the address
    assert event.organizer == ParsedAttendee("anna@post.example", "Keller, Anna", None, None)
    assert event.attendees == (
        ParsedAttendee("jonas@elbtal.example", "Jonas Brandt", "REQ-PARTICIPANT", "NEEDS-ACTION"),
    )


def test_a_reply_with_one_attendee() -> None:
    [event] = parse_calendar(REPLY)
    assert (event.method, event.kind) == ("REPLY", "reply")
    assert event.summary == "Angenommen: Vorstandssitzung"
    assert [(a.email, a.partstat) for a in event.attendees] == [
        ("anna.keller@nordlicht-gmbh.example", "ACCEPTED")
    ]


def test_a_cancellation_with_a_display_name_zone_and_a_duration() -> None:
    [event] = parse_calendar(CANCEL)
    assert (event.method, event.status, event.kind, event.sequence) == (
        "CANCEL",
        "CANCELLED",
        "cancel",
        2,
    )
    assert event.time_zone == "(UTC+01:00) Amsterdam, Berlin, Bern, Rom, Stockholm, Wien"
    assert event.starts_at == datetime(2024, 3, 5, 8, 0, tzinfo=UTC)
    assert event.ends_local == datetime(2024, 3, 5, 11, 0)
    assert event.ends_at == datetime(2024, 3, 5, 10, 0, tzinfo=UTC)
    # the quoted SENT-BY holds a colon: the organizer is still its own address
    assert event.organizer == ParsedAttendee("kasse@verein.example", "Kasse", None, None)


def test_all_day_and_recurring_events_of_one_calendar() -> None:
    fest, runde = parse_calendar(ALL_DAY_RECURRING)
    assert (fest.method, fest.kind, fest.all_day) == ("PUBLISH", "request", True)
    assert (fest.starts_local, fest.ends_local) == (datetime(2024, 7, 20), datetime(2024, 7, 21))
    assert (fest.time_zone, fest.starts_at) == (None, None)
    assert runde.recurrence == "FREQ=WEEKLY;BYDAY=MO;COUNT=10"
    assert runde.time_zone == "/mozilla.org/20070129_1/Europe/Berlin"
    assert runde.starts_at == datetime(2024, 1, 8, 8, 0, tzinfo=UTC)


def test_several_calendars_each_with_its_method() -> None:
    events = parse_calendar(REPLY + CANCEL + OUTLOOK)
    assert [event.kind for event in events] == ["reply", "cancel", "request"]


def test_a_method_written_after_the_events_holds_for_them() -> None:
    text = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nEND:VEVENT\nMETHOD:CANCEL\nEND:VCALENDAR\n"
    assert [(e.uid, e.kind) for e in parse_calendar(text)] == [("x", "cancel")]


@pytest.mark.parametrize(
    ("tzid", "expected"),
    [
        ("W. Europe Standard Time", "Europe/Berlin"),
        ("Romance Standard Time", "Europe/Paris"),
        ("GMT Standard Time", "Europe/London"),
        ("Eastern Standard Time", "America/New_York"),
        ('"W. Europe Standard Time"', "Europe/Berlin"),
        ("Europe/Vienna", "Europe/Vienna"),
        ("(UTC+01:00) Brüssel, Kopenhagen, Madrid, Paris", "Europe/Paris"),
        ("UTC", "UTC"),
        ("Mitteleuropäische Zeit", None),
        ("Customized Time Zone", None),
        ("../../etc/passwd", None),
        ("", None),
    ],
)
def test_zones(tzid: str, expected: str | None) -> None:
    found = zone(tzid)
    assert (None if found is None else found.key) == expected


def test_an_unknown_zone_keeps_the_wall_time_without_an_instant() -> None:
    text = OUTLOOK.replace("W. Europe Standard Time", "Customized Time Zone")
    [event] = parse_calendar(text)
    assert event.time_zone == "Customized Time Zone"
    assert event.starts_local == datetime(2024, 7, 15, 10, 0)
    assert event.starts_at is None and event.ends_at is None


def test_floating_times_have_no_zone() -> None:
    [event] = parse_calendar("BEGIN:VEVENT\nDTSTART:20190304T090000\nSUMMARY:Abstimmung\n")
    assert (event.method, event.time_zone, event.starts_at) == (None, None, None)
    assert event.starts_local == datetime(2019, 3, 4, 9, 0)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "garbage\x00\xff without any structure",
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Ohne Ende",
        "END:VEVENT\nEND:VCALENDAR\nBEGIN:VEVENT\n",
        "BEGIN:VEVENT\nDTSTART:20241345T999999\nDTEND:nonsense\nSEQUENCE:12345678901\n"
        "DURATION:P99999999999W\nATTENDEE:invalid:nomail\nORGANIZER;CN=:\nEND:VEVENT\n",
        "BEGIN:VEVENT\nDTSTART;TZID=Europe/Berlin:00010101T000000\nEND:VEVENT\n",
        'BEGIN:VEVENT\nATTENDEE;CN="unclosed:mailto:a@b.example\nEND:VEVENT\n',
    ],
)
def test_broken_input_never_raises(text: str) -> None:
    for event in parse_calendar(text.encode("utf-8", "surrogateescape")):
        assert event.sequence is None or abs(event.sequence) < 2**31


def test_a_broken_calendar_gives_the_events_that_could_be_read() -> None:
    text = "BEGIN:VCALENDAR\nMETHOD:REQUEST\nBEGIN:VEVENT\nUID:a\nBEGIN:VEVENT\nUID:b\n\x00\x01"
    assert [(e.uid, e.method) for e in parse_calendar(text)] == [
        ("a", "REQUEST"),
        ("b", "REQUEST"),
    ]


def test_bytes_are_utf8_with_replacements_and_a_byte_order_mark_is_dropped() -> None:
    data = b"\xef\xbb\xbfBEGIN:VEVENT\nSUMMARY:Gr\xfc\xdfe aus K\xc3\xb6ln\nEND:VEVENT\n"
    assert _one(data) == parse_calendar("BEGIN:VEVENT\nSUMMARY:Gr\ufffd\ufffde aus Köln\n")[0]


def test_long_values_are_cut() -> None:
    text = f"BEGIN:VEVENT\nDESCRIPTION:{'x' * 5000}\nSUMMARY:{'y' * 5000}\nEND:VEVENT\n"
    [event] = parse_calendar(text)
    assert event.description is not None and len(event.description) == DESCRIPTION_LIMIT
    assert event.summary is not None and len(event.summary) < 1000


def test_at_most_event_limit_events() -> None:
    text = "BEGIN:VCALENDAR\n" + "BEGIN:VEVENT\nUID:x\nEND:VEVENT\n" * (EVENT_LIMIT + 5)
    assert len(parse_calendar(text)) == EVENT_LIMIT


# Mails ----------------------------------------------------------------------------------------


def _b64(text: str) -> str:
    return base64.encodebytes(text.encode()).decode()


def test_an_outlook_mail_with_its_inline_part() -> None:
    message = (
        "From: Hans <hans@nordlicht-gmbh.example>\nSubject: Vorstandssitzung\n"
        "MIME-Version: 1.0\nContent-Type: multipart/alternative; boundary=b\n\n"
        "--b\nContent-Type: text/plain; charset=utf-8\n\nWann: Montag ...\n"
        '--b\nContent-Type: text/calendar; charset="utf-8"; method=REQUEST\n'
        f"Content-Transfer-Encoding: base64\n\n{_b64(OUTLOOK)}--b--\n"
    ).encode()
    [event] = message_events(message)
    assert (event.summary, event.time_zone) == ("Vorstandssitzung", "W. Europe Standard Time")


def test_an_inline_part_and_its_invite_ics_give_one_event() -> None:
    message = (
        "Subject: Einladung: Kick-off\nMIME-Version: 1.0\n"
        "Content-Type: multipart/mixed; boundary=m\n\n--m\n"
        "Content-Type: multipart/alternative; boundary=a\n\n--a\n"
        "Content-Type: text/plain\n\nSie wurden eingeladen.\n--a\n"
        f"Content-Type: text/calendar; method=REQUEST\n\n{WEB}--a--\n--m\n"
        'Content-Type: application/ics; name="invite.ics"\n'
        'Content-Disposition: attachment; filename="invite.ics"\n'
        f"Content-Transfer-Encoding: base64\n\n{_b64(WEB)}--m--\n"
    ).encode()
    assert [event.uid for event in message_events(message)] == ["5f3b2c1a9e7d@kalender.example"]


def test_attached_mails_files_by_name_and_calendars_in_text() -> None:
    inner = (
        "Subject: Termin\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=i\n\n"
        "--i\nContent-Type: text/plain\n\nAnbei.\n--i\n"
        'Content-Type: application/octet-stream; name="Termin.ICS"\n'
        f"Content-Transfer-Encoding: base64\n\n{_b64(CANCEL)}--i--\n"
    )
    message = (
        "Subject: WG: Termin\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=o\n\n"
        f"--o\nContent-Type: text/plain\n\nHier der Termin:\n\n{REPLY}\n"
        f"--o\nContent-Type: message/rfc822\n\n{inner}--o--\n"
    ).encode()
    assert [event.kind for event in message_events(message)] == ["reply", "cancel"]


def test_a_declared_charset_is_honoured() -> None:
    calendar = "BEGIN:VEVENT\nSUMMARY:Übergabe\nEND:VEVENT\n".encode("latin-1")
    message = (
        b"Subject: x\nMIME-Version: 1.0\n"
        b'Content-Type: text/calendar; charset="iso-8859-1"\n\n' + calendar
    )
    assert [event.summary for event in message_events(message)] == ["Übergabe"]


def test_mails_without_a_calendar() -> None:
    message = b"Subject: Einladung: Sommerfest\n\nWann: Samstag\nOrt: Garten\n"
    assert message_events(message) == []
    assert message_events(b"\x00\xff garbage") == []

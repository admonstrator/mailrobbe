"""Calendar invitations of the generator (D154): planned for some personal mails and the
threads that follow them, written as Outlook, a web calendar and Apple Calendar write them, and
stated in the manifest as the calendar phase must read them."""

import email.policy
import itertools
import random
from collections import Counter
from datetime import UTC, datetime
from email.message import Message
from email.parser import BytesParser
from typing import Any

import pytest

from mailrobbe.generator import invitations
from mailrobbe.generator.faults import inject_fault
from mailrobbe.generator.model import (
    Address,
    AttachmentSpec,
    DocumentSpec,
    EventTruth,
    Fault,
    MailKind,
    PlannedMail,
    RenderedMail,
)
from mailrobbe.generator.population import Population
from mailrobbe.generator.render import render
from mailrobbe.generator.writer import manifest_record
from mailrobbe.ical.parse import ParsedEvent, message_events

_PARSER = BytesParser(policy=email.policy.compat32)
WHEN = datetime(2021, 5, 4, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def calendar_mails(gen_plan: list[PlannedMail]) -> list[PlannedMail]:
    return [mail for mail in gen_plan if mail.calendar is not None]


@pytest.fixture(scope="module")
def rendered(calendar_mails: list[PlannedMail]) -> list[RenderedMail]:
    return [render(mail) for mail in calendar_mails]


def _owners(population: Population) -> dict[str, int]:
    return {
        variants[0].email: person.index
        for person in population.persons
        for variants in person.mailboxes
    }


def test_some_personal_mails_invite_to_meetings(
    gen_plan: list[PlannedMail], calendar_mails: list[PlannedMail], gen_population: Population
) -> None:
    assert 0.008 < len(calendar_mails) / len(gen_plan) < 0.025  # about 1 to 2 percent
    methods = Counter(
        (mail.calendar.method, mail.calendar.meeting.sequence > 0)
        for mail in calendar_mails
        if mail.calendar is not None
    )
    assert methods.keys() >= {("REQUEST", False), ("REQUEST", True), ("REPLY", False)}
    assert methods[("CANCEL", True)] > 0
    styles = Counter(mail.calendar.style for mail in calendar_mails if mail.calendar)
    assert styles.keys() == {"outlook", "web", "apple"}
    meetings = [
        mail.calendar.meeting
        for mail in calendar_mails
        if mail.calendar is not None and mail.kind is MailKind.PERSONAL
    ]
    assert any(m.all_day for m in meetings) and any(m.rule for m in meetings)
    assert any(m.rooms for m in meetings)
    owners = _owners(gen_population)
    persons = gen_population.persons
    attendees = [a for m in meetings for a in m.attendees]
    assert all(a.email in owners for a in attendees)  # persons of the population
    assert any(not persons[owners[a.email]].internal for a in attendees)  # outsiders too
    rooms = [room.email for m in meetings for room in m.rooms]
    assert not set(rooms) & owners.keys()  # rooms are attendees no mail reaches


def test_answers_updates_and_cancellations_follow_their_invitation(
    gen_plan: list[PlannedMail], gen_population: Population
) -> None:
    owners = _owners(gen_population)
    state: dict[str, tuple[int, bool]] = {}  # uid: latest sequence, cancelled
    plain = 0
    for mail in gen_plan:
        root = gen_plan[mail.thread_index] if mail.thread_index is not None else None
        invitation = mail.calendar
        if invitation is None:
            plain += root is not None and root.calendar is not None and mail is not root
            continue
        meeting = invitation.meeting
        german = mail.language == "de"
        if mail.kind is MailKind.PERSONAL:
            assert (invitation.method, meeting.sequence) == ("REQUEST", 0)
            assert mail.subject == f"{'Einladung' if german else 'Invitation'}: {meeting.title}"
            assert meeting.organizer == mail.sender
            assert meeting.attendees == (*mail.to, *mail.cc) and not mail.bcc
            state[meeting.uid] = (0, False)
            continue
        assert mail.kind is MailKind.REPLY and root is not None and root.calendar is not None
        assert root.calendar.meeting.uid == meeting.uid
        sequence, cancelled = state[meeting.uid]
        assert not cancelled  # after a cancellation the thread goes on in plain mails
        assert not mail.cc and not mail.bcc
        if invitation.method == "REPLY":
            assert meeting.sequence == sequence
            assert mail.to == (meeting.organizer,)
            assert invitation.answer == mail.sender
            assert invitation.partstat in ("ACCEPTED", "DECLINED", "TENTATIVE")
            assert owners[mail.sender.email] != meeting.organizer_person
        else:
            assert meeting.sequence == sequence + 1
            assert owners[mail.sender.email] == meeting.organizer_person
            assert mail.to == meeting.attendees
            state[meeting.uid] = (meeting.sequence, invitation.method == "CANCEL")
        assert mail.subject == invitations.subject(invitation, mail.language)
    assert plain > 0  # "AW: Einladung: ..." without a calendar part
    assert any(cancelled for _, cancelled in state.values())


def _parts(message: Message) -> list[tuple[Message, Message | None]]:
    """Every leaf part with the multipart around it."""
    found: list[tuple[Message, Message | None]] = []

    def walk(part: Message, parent: Message | None) -> None:
        if part.is_multipart():
            for child in part.get_payload():
                walk(child, part)
        else:
            found.append((part, parent))

    walk(message, None)
    return found


def test_each_program_writes_its_parts(rendered: list[RenderedMail]) -> None:
    for mail in rendered:
        invitation = mail.planned.calendar
        assert invitation is not None
        parts = _parts(_PARSER.parsebytes(mail.raw))
        inline = [(p, up) for p, up in parts if p.get_content_type() == "text/calendar"]
        files = [p for p, _ in parts if p.get_filename() == invitations.INVITE_FILE]
        assert len(inline) == (0 if invitation.style == "apple" else 1)
        assert len(files) == (0 if invitation.style == "outlook" else 1)
        for part in [*(p for p, _ in inline), *files]:
            assert part["Content-Transfer-Encoding"] in ("7bit", "quoted-printable")
        for part, around in inline:
            assert around is not None and around.get_content_type() == "multipart/alternative"
            assert part.get_param("method") == invitation.method
        data = (inline[0][0] if inline else files[0]).get_payload(decode=True)
        assert isinstance(data, bytes)
        if files:
            assert files[0].get_payload(decode=True) == data
        meeting = invitation.meeting
        text = data.decode()
        if invitation.style != "web" and not meeting.all_day:
            assert "BEGIN:VTIMEZONE" in text and "DTSTART;TZID=" in text
        if invitation.style == "web" and not meeting.all_day and meeting.rule is None:
            assert "BEGIN:VTIMEZONE" not in text and "Z\nDTEND:" in text
        body = mail.raw.decode("utf-8", "replace")
        if invitation.style == "outlook" and invitation.method != "REPLY":
            assert invitations.OUTLOOK_RULE in body


def _read(event: ParsedEvent) -> tuple[Any, ...]:
    if event.all_day:
        assert event.starts_local is not None
        start = event.starts_local.date().isoformat()
    elif event.starts_at is not None:
        start = event.starts_at.isoformat()
    else:
        assert event.starts_local is not None
        start = event.starts_local.isoformat()
    count = len(event.attendees)
    return (event.method, event.uid, event.sequence, event.kind, event.summary, start, count)


def _truth(truth: EventTruth) -> tuple[Any, ...]:
    return (truth.method, truth.uid, truth.sequence, truth.kind, truth.summary, truth.start,
            truth.attendees)  # fmt: skip


def test_the_truth_is_what_the_calendar_phase_reads(gen_plan: list[PlannedMail]) -> None:
    """Calendar mails and mails with .ics documents: RenderedMail.calendar lists their
    events, the calendar part's first; times in a zone as their instant."""
    documents = [
        mail
        for mail in gen_plan
        if any(a.document is not None and a.document.form == "ics" for a in mail.attachments)
    ]
    assert documents
    for planned in itertools.chain(documents, (m for m in gen_plan if m.calendar)):
        mail = render(planned)
        assert mail.calendar is not None
        assert sorted(map(_read, message_events(mail.raw))) == sorted(map(_truth, mail.calendar))
        if planned.calendar is not None:
            assert mail.calendar[0] == invitations.truth(planned)


def test_manifest_lists_the_events(rendered: list[RenderedMail]) -> None:
    mail = rendered[0]
    assert mail.calendar
    record = manifest_record(0, mail, "mbox-0001.mbox", 0, len(mail.raw))
    assert record.calendar == [truth.as_json() for truth in mail.calendar]
    assert set(record.calendar[0]) == {
        "method", "uid", "sequence", "kind", "summary", "start", "attendees",
    }  # fmt: skip
    plain = render(PlannedMail(
        index=1, seed=9, date=WHEN, sender=Address("a@x.example"), to=(Address("b@x.example"),),
        subject="Hallo", message_id="<2@x.example>", client="outlook",
    ))  # fmt: skip
    assert manifest_record(1, plain, "mbox-0001.mbox", 0, 1).calendar == []


def test_a_broken_ics_document_leaves_the_events_unknown() -> None:
    document = DocumentSpec(7, "ics", "calendar", WHEN)
    spec = AttachmentSpec("Einladung.ics", "text/calendar", 2_000, document=document)
    mail = render(PlannedMail(
        index=0, seed=5, date=WHEN, sender=Address("a@x.example"), to=(Address("b@x.example"),),
        subject="Termin", message_id="<1@x.example>", attachments=(spec,), client="outlook",
    ))  # fmt: skip
    assert mail.calendar is not None
    assert [truth.uid for truth in mail.calendar] == [f"{7:016x}@kalender.example"]
    assert inject_fault(mail, Fault.BROKEN_ENCODING, "invalid_base64", random.Random(1))
    assert mail.documents[0].sha256 is None
    assert mail.calendar is None
    assert manifest_record(0, mail, "mbox-0001.mbox", 0, 1).calendar is None


def test_calendar_parts_survive_the_byte_faults(calendar_mails: list[PlannedMail]) -> None:
    for planned in calendar_mails:
        mail = render(planned)
        events = message_events(mail.raw)
        inject_fault(mail, Fault.BROKEN_ENCODING, "invalid_base64", random.Random(3))
        assert mail.calendar is not None
        assert message_events(mail.raw) == events

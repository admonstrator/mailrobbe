"""Calendar events (D155): of a mail in its detail, of the mails of a list page, and of a
person: GET /api/persons/{id}/events.

Organisers and attendees are addresses of the iCalendar part, no participants; an address the
archive knows (person_email) is shown as its person. A person's events are grouped by UID (an
event without one stands alone); each group shows its latest invitation, update or cancellation
(by SEQUENCE, then mail date), an answer only when the archive holds nothing else of it.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import APIRouter
from sqlalchemy import BigInteger, Text, any_, cast, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api import detail
from mailrobbe.api.deps import Session, api_error
from mailrobbe.api.persons import PersonId
from mailrobbe.api.schemas import (
    PERSON_EVENT_LIMIT,
    CalendarAttendee,
    CalendarEventInfo,
    EventKey,
    PersonEvent,
    PersonEvents,
    PersonRef,
    ThreadMail,
)
from mailrobbe.db.models import CalendarAttendee as AttendeeRow
from mailrobbe.db.models import CalendarEvent, Mail, Person, PersonEmail
from mailrobbe.ical.model import EVENT_KINDS
from mailrobbe.persons.labels import attach_labels
from mailrobbe.persons.roots import member_ids, resolve_root

router = APIRouter(prefix="/api", tags=["events"])


async def event_kinds(session: AsyncSession, mail_ids: Sequence[int]) -> dict[int, EventKey]:
    """For the mails of a list page: the kind of each one's first event; mails without one are
    left out."""
    if not mail_ids:
        return {}
    rows = await session.execute(
        select(CalendarEvent.mail_id, CalendarEvent.kind)
        .where(CalendarEvent.mail_id == any_(cast(list(mail_ids), postgresql.ARRAY(BigInteger))))
        .order_by(CalendarEvent.mail_id, CalendarEvent.position)
        .ext(postgresql.distinct_on(CalendarEvent.mail_id))
    )
    return {mail_id: _kind(kind) for mail_id, kind in rows}


def _kind(value: str) -> EventKey:
    """calendar_event.kind, which the table's check constraint keeps to the event keys."""
    return next(kind for kind in EVENT_KINDS if kind == value)


async def mail_events(session: AsyncSession, mail_id: int) -> list[CalendarEventInfo]:
    """The events of one mail in mail order, with their attendees and persons."""
    rows = (
        await session.execute(
            select(CalendarEvent)
            .where(CalendarEvent.mail_id == mail_id)
            .order_by(CalendarEvent.position)
        )
    ).scalars()
    return await _infos(session, list(rows))


async def _infos(session: AsyncSession, rows: list[CalendarEvent]) -> list[CalendarEventInfo]:
    """The events with their attendees, persons and mails per UID, in four queries."""
    if not rows:
        return []
    ids = [row.id for row in rows]
    attendees: dict[int, list[AttendeeRow]] = {}
    for attendee in await session.scalars(
        select(AttendeeRow)
        .where(AttendeeRow.event_id == any_(cast(ids, postgresql.ARRAY(BigInteger))))
        .order_by(AttendeeRow.event_id, AttendeeRow.position)
    ):
        attendees.setdefault(attendee.event_id, []).append(attendee)
    emails = {row.organizer_email for row in rows} | {
        attendee.email for found in attendees.values() for attendee in found
    }
    persons = await _persons(session, {email for email in emails if email})
    uids = sorted({row.uid for row in rows if row.uid is not None})
    uid_mails: dict[str, int] = {}
    if uids:
        uid_mails = {
            uid: count
            for uid, count in await session.execute(
                select(CalendarEvent.uid, func.count(func.distinct(CalendarEvent.mail_id)))
                .where(CalendarEvent.uid == any_(cast(uids, postgresql.ARRAY(Text))))
                .group_by(CalendarEvent.uid)
            )
            if uid is not None
        }

    def person(email: str | None, name: str | None) -> PersonRef | None:
        found = persons.get(email) if email else None
        if found is None:
            return None
        return found.model_copy(update={"name": name or found.name})

    def entry(email: str | None, name: str | None, role: Any, partstat: Any) -> CalendarAttendee:
        return CalendarAttendee(
            email=email, name=name, role=role, partstat=partstat, person=person(email, name)
        )

    return [
        CalendarEventInfo(
            id=row.id,
            mail_id=row.mail_id,
            kind=_kind(row.kind),
            method=row.method,
            uid=row.uid,
            sequence=row.sequence,
            status=row.status,
            summary=row.summary,
            location=row.location,
            description=row.description,
            starts_local=row.starts_local,
            ends_local=row.ends_local,
            time_zone=row.time_zone,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            all_day=row.all_day,
            recurrence=row.recurrence,
            organizer=None
            if row.organizer_email is None and row.organizer_name is None
            else entry(row.organizer_email, row.organizer_name, None, None),
            attendees=[
                entry(a.email, a.name, a.role, a.partstat) for a in attendees.get(row.id, [])
            ],
            uid_mails=0 if row.uid is None else uid_mails.get(row.uid, 0),
        )
        for row in rows
    ]


async def _persons(session: AsyncSession, emails: Iterable[str]) -> dict[str, PersonRef]:
    """The archive's person of each address it knows (person_email), in one query."""
    wanted = sorted(emails)
    if not wanted:
        return {}
    rows = await session.execute(
        select(PersonEmail.email, Person.id, Person.canonical_email, Person.display_name)
        .join(Person, Person.id == PersonEmail.person_id)
        .where(PersonEmail.email == any_(cast(wanted, postgresql.ARRAY(Text))))
    )
    return {
        email: PersonRef(person_id=person_id, email=canonical, name=name)
        for email, person_id, canonical, name in rows
    }


# The events of a person's addresses (organiser: ix_calendar_event_organizer_email, attendee:
# ix_calendar_attendee_email), grouped by UID; each group's events by ix_calendar_event_uid.
# Mails that are duplicates (D16) are left out.
_PERSON_EVENTS = text("""
    WITH involved AS (
        SELECT e.id, e.uid FROM calendar_event e
        WHERE e.organizer_email = ANY(CAST(:emails AS text[]))
        UNION
        SELECT e.id, e.uid FROM calendar_attendee a JOIN calendar_event e ON e.id = a.event_id
        WHERE a.email = ANY(CAST(:emails AS text[]))
    ),
    grouped AS (
        SELECT e.*, m.date_utc AS mail_date, COALESCE(e.uid, '#' || e.id) AS group_key
        FROM calendar_event e JOIN mail m ON m.id = e.mail_id
        WHERE m.is_duplicate_of IS NULL AND (
            e.uid IN (SELECT uid FROM involved WHERE uid IS NOT NULL)
            OR e.id IN (SELECT id FROM involved WHERE uid IS NULL))
    ),
    answers AS (  -- the person's answer per group: its latest reply, else what an event says
        SELECT DISTINCT ON (g.group_key) g.group_key, a.partstat
        FROM grouped g JOIN calendar_attendee a ON a.event_id = g.id
        WHERE a.email = ANY(CAST(:emails AS text[])) AND a.partstat IS NOT NULL
        ORDER BY g.group_key, g.kind = 'reply' DESC, g.sequence DESC NULLS LAST,
            g.mail_date DESC NULLS LAST, g.id DESC
    ),
    shown AS (
        SELECT DISTINCT ON (g.group_key) g.id, g.group_key,
            COALESCE(g.starts_at, g.starts_local AT TIME ZONE 'UTC') AS starts
        FROM grouped g
        ORDER BY g.group_key, g.kind = 'reply', g.sequence DESC NULLS LAST,
            g.mail_date DESC NULLS LAST, g.id DESC
    ),
    organised AS (
        SELECT g.group_key FROM grouped g
        WHERE g.organizer_email = ANY(CAST(:emails AS text[])) GROUP BY g.group_key
    )
    SELECT s.id, o.group_key IS NOT NULL AS organizer, a.partstat, count(*) OVER () AS total
    FROM shown s
        LEFT JOIN organised o ON o.group_key = s.group_key
        LEFT JOIN answers a ON a.group_key = s.group_key
    ORDER BY s.starts DESC NULLS LAST, s.id DESC
    LIMIT :limit
""")


@router.get("/persons/{person_id}/events")
async def person_events(person_id: PersonId, session: Session) -> PersonEvents:
    """The events the person (its root and aliases) organised or was invited to."""
    root = await resolve_root(session, person_id)
    if root is None:
        raise api_error(404, "not_found", f"no person with id {person_id}")
    members = await member_ids(session, root)
    emails = list(
        await session.scalars(
            select(PersonEmail.email).where(
                PersonEmail.person_id == any_(cast(members, postgresql.ARRAY(BigInteger)))
            )
        )
    )
    if not emails:
        return PersonEvents(items=[], total=0)
    shown = (
        await session.execute(_PERSON_EVENTS, {"emails": emails, "limit": PERSON_EVENT_LIMIT})
    ).all()
    if not shown:
        return PersonEvents(items=[], total=0)
    rows = {
        row.id: row
        for row in await session.scalars(
            select(CalendarEvent).where(
                CalendarEvent.id
                == any_(cast([row.id for row in shown], postgresql.ARRAY(BigInteger)))
            )
        )
    }
    infos = {info.id: info for info in await _infos(session, list(rows.values()))}
    mail_ids = sorted({info.mail_id for info in infos.values()})
    mails = {
        row.id: row
        for row in await session.execute(
            select(Mail.id, Mail.date_utc, Mail.subject, Mail.dkim_status).where(
                Mail.id == any_(cast(mail_ids, postgresql.ARRAY(BigInteger)))
            )
        )
    }
    senders = await detail.mail_senders(session, mail_ids)
    response = PersonEvents(
        items=[
            PersonEvent(
                event=infos[row.id],
                organizer=row.organizer,
                partstat=row.partstat,
                mail=_thread_mail(mails[infos[row.id].mail_id], senders),
            )
            for row in shown
        ],
        total=shown[0].total,
    )
    await attach_labels(session, response)
    return response


def _thread_mail(row: Any, senders: dict[int, PersonRef]) -> ThreadMail:
    return ThreadMail(
        id=row.id,
        date=row.date_utc,
        subject=row.subject,
        sender=senders.get(row.id),
        dkim_status=row.dkim_status,
    )

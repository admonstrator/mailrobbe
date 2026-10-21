"""The calendar phase of an import (D154): the candidates among the mails not looked at yet are
read from their MBOX files, and the events of their iCalendar parts stored.

    work list   mails without a calendar_scan row of the current CALENDAR_VERSION, by id;
                waiting() counts them for the import's step
    pages       PAGE mails at a time; one query finds the page's candidates (model's candidate
                rule: an iCalendar attachment by type or name, a subject or text of invitations),
                in file and offset order, so every file is read front to back
    read        each candidate by read_verified and parse.message_events: every calendar part,
                attached mails included. Chunks of READ_CHUNK candidates go to spawned worker
                processes, as many as the import has, once a page has more than one chunk;
                otherwise a thread reads them.
    store       per page one transaction: the events and attendees of its mails replaced, their
                calendar_scan rows written (read: the mail was a candidate and was read), the
                step advanced by the page; at the end the figures in global_stats 'calendar'
                (events, and per kind the mails that are no duplicates). A page the database
                refuses is stored again mail by mail, and a mail whose events it cannot take
                keeps none (logged), so one mail never stops the step.

A stop (D46) ends the phase between two pages: the stored pages stay, the rest waits for the next
import. A candidate whose MBOX file is missing or changed gets no scan row and keeps the events
found before; it is tried again at the next import. Duplicates (D16) are read like every mail.
Organisers and attendees are no participants: no person is created for them (D155).
"""

import asyncio
import logging
import multiprocessing
import time
from array import array
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.db.models import CALENDAR_VERSION
from mailrobbe.ical.model import (
    CALENDAR_MARK,
    CALENDAR_SUFFIXES,
    CALENDAR_TYPES,
    EVENT_KINDS,
    OUTLOOK_RULE,
    SUBJECT_MARKS,
    WHEN_MARKS,
    WHERE_MARKS,
    CalendarFigures,
    write_figures,
)
from mailrobbe.ical.parse import ParsedEvent, message_events
from mailrobbe.jobrun import Step, describe, ignore_interrupts, spawning_workers
from mailrobbe.mbox import read_verified

log = logging.getLogger(__name__)

PAGE = 2_000  # mails looked at per transaction
READ_CHUNK = 25  # candidates per task of a worker process

_NOT_SCANNED = """
    NOT EXISTS (SELECT 1 FROM calendar_scan s WHERE s.mail_id = m.id AND s.version = :version)
"""
_COUNT = text(f"SELECT count(*) FROM mail m WHERE {_NOT_SCANNED}")
_WORK = text(f"SELECT m.id FROM mail m WHERE {_NOT_SCANNED} ORDER BY m.id")


def _any_of(words: Sequence[str]) -> str:
    return "|".join(word.lower().replace(" ", r"\s+") for word in words)


# The candidate rule (model) in SQL: subjects after reply and forward prefixes and tags in
# brackets ("[EXTERN]" of a gateway), Outlook's lines.
_SUBJECT = (
    r"^\s*(((re|aw|antw|wg|fw|fwd|sv)(\[\d+\])?\s*:|\[[^]]*\])\s*)*"
    rf"({_any_of(SUBJECT_MARKS)})\s*:"
)
_LINE = r"(^|\n)[ \t]*({})[ \t]*:"
_CANDIDATES = text("""
    SELECT m.id, f.path, m.byte_offset, m.byte_length, m.raw_sha256
    FROM mail m JOIN mbox_file f ON f.id = m.mbox_file_id
    WHERE m.id = ANY(CAST(:ids AS bigint[])) AND (
        EXISTS (
            SELECT 1 FROM attachment a WHERE a.mail_id = m.id AND (
                lower(a.mime_type) = ANY(CAST(:types AS text[]))
                OR lower(right(a.filename, 4)) = ANY(CAST(:suffixes AS text[]))))
        OR m.subject ~* :subject
        OR strpos(m.body_text, :rule) > 0
        OR strpos(m.body_text, :mark) > 0
        OR (m.body_text ~ :when AND m.body_text ~ :where))
    ORDER BY f.path COLLATE "C", m.byte_offset
""")
_CANDIDATE_PARAMETERS = {
    "types": list(CALENDAR_TYPES),
    "suffixes": list(CALENDAR_SUFFIXES),
    "subject": _SUBJECT,
    "rule": OUTLOOK_RULE,
    "mark": CALENDAR_MARK,
    "when": _LINE.format("|".join(WHEN_MARKS)),
    "where": _LINE.format("|".join(WHERE_MARKS)),
}
_FORGET = text("DELETE FROM calendar_event WHERE mail_id = ANY(CAST(:ids AS bigint[]))")
_EVENTS = text("""
    INSERT INTO calendar_event (mail_id, position, kind, method, uid, sequence, status, summary,
        location, description, starts_local, ends_local, time_zone, starts_at, ends_at, all_day,
        recurrence, organizer_email, organizer_name)
    SELECT * FROM unnest(CAST(:mail_ids AS bigint[]), CAST(:positions AS smallint[]),
        CAST(:kinds AS text[]), CAST(:methods AS text[]), CAST(:uids AS text[]),
        CAST(:sequences AS integer[]), CAST(:statuses AS text[]), CAST(:summaries AS text[]),
        CAST(:locations AS text[]), CAST(:descriptions AS text[]),
        CAST(:starts_local AS timestamp[]), CAST(:ends_local AS timestamp[]),
        CAST(:zones AS text[]), CAST(:starts_at AS timestamptz[]), CAST(:ends_at AS timestamptz[]),
        CAST(:all_day AS boolean[]), CAST(:recurrences AS text[]),
        CAST(:organizer_emails AS text[]), CAST(:organizer_names AS text[]))
    RETURNING id, mail_id, position
""")
_ATTENDEES = text("""
    INSERT INTO calendar_attendee (event_id, position, email, name, role, partstat)
    SELECT * FROM unnest(CAST(:event_ids AS bigint[]), CAST(:positions AS smallint[]),
        CAST(:emails AS text[]), CAST(:names AS text[]), CAST(:roles AS text[]),
        CAST(:partstats AS text[]))
""")
_SCANNED = text("""
    INSERT INTO calendar_scan (mail_id, version, read, events)
    SELECT u.id, :version, u.read, u.events
    FROM unnest(CAST(:ids AS bigint[]), CAST(:read AS boolean[]), CAST(:events AS smallint[]))
        AS u(id, read, events)
    ON CONFLICT (mail_id) DO UPDATE
    SET version = EXCLUDED.version, read = EXCLUDED.read, events = EXCLUDED.events
""")
_EVENT_COUNT = text("SELECT count(*) FROM calendar_event")
_MAILS_PER_KIND = text("""
    SELECT e.kind, count(DISTINCT e.mail_id) FROM calendar_event e JOIN mail m ON m.id = e.mail_id
    WHERE m.is_duplicate_of IS NULL GROUP BY e.kind
""")


async def waiting(session: AsyncSession) -> int:
    """Mails without a calendar_scan row of the current CALENDAR_VERSION."""
    return await session.scalar(_COUNT, {"version": CALENDAR_VERSION}) or 0


@dataclass(frozen=True, slots=True)
class _Candidate:
    mail_id: int
    path: str  # of the MBOX file, relative to the MBOX directory
    byte_offset: int
    byte_length: int
    raw_sha256: str


# What reading a candidate gave: its events, or None when its MBOX file is missing or changed.
_Read = tuple[int, list[ParsedEvent] | None]


def _read(mbox_dir: str, candidates: list[_Candidate]) -> list[_Read]:
    """Read and parse candidates, in a worker process or a thread."""
    found: list[_Read] = []
    for candidate in candidates:
        try:
            message = read_verified(
                Path(mbox_dir) / candidate.path,
                candidate.byte_offset,
                candidate.byte_length,
                candidate.raw_sha256,
            )
        except OSError:
            message = None
        if message is None:
            found.append((candidate.mail_id, None))
            continue
        try:
            events = message_events(message)
        except Exception as error:  # message_events never raises: a bug, for this mail alone
            log.warning("calendar: mail %d: %s", candidate.mail_id, describe(error))
            events = []
        found.append((candidate.mail_id, events))
    return found


@dataclass(slots=True)
class _Result:
    mails: int = 0  # looked at and stored
    read: int = 0  # candidates read
    unreadable: int = 0  # candidates whose MBOX file is missing or changed
    events: int = 0  # stored


async def scan_calendar(
    sessionmaker: async_sessionmaker[AsyncSession],
    mbox_dir: Path,
    workers: int,
    stop: asyncio.Event,
    step: Step,
) -> int:
    """The step calendar: look at the waiting mails; the events stored in this run."""
    started = time.monotonic()
    async with sessionmaker() as session:
        work = array("q", await session.scalars(_WORK, {"version": CALENDAR_VERSION}))
    log.info("calendar: looking at %d mails", len(work))
    result = _Result()
    pool: ProcessPoolExecutor | None = None
    try:
        for start in range(0, len(work), PAGE):
            if stop.is_set():
                break
            ids = work[start : start + PAGE].tolist()
            async with sessionmaker() as session:
                rows = await session.execute(_CANDIDATES, {"ids": ids, **_CANDIDATE_PARAMETERS})
                candidates = [_Candidate(*row) for row in rows]
            if len(candidates) > READ_CHUNK and workers > 1 and pool is None:
                with spawning_workers():
                    pool = ProcessPoolExecutor(
                        workers,
                        mp_context=multiprocessing.get_context("spawn"),
                        initializer=ignore_interrupts,
                    )
            found = await _read_all(pool, str(mbox_dir), candidates)
            async with sessionmaker() as session, session.begin():
                try:
                    async with session.begin_nested():
                        await _store(session, ids, found, result)
                except DBAPIError:
                    await _store_alone(session, ids, found, result)
            step.advance(len(ids))
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
    async with sessionmaker() as session, session.begin():
        await _write_figures(session)
    log.info(
        "calendar: %d mails looked at, %d read, %d unreadable, %d events stored%s (%.1f s)",
        result.mails,
        result.read,
        result.unreadable,
        result.events,
        ", stopped" if stop.is_set() else "",
        time.monotonic() - started,
    )
    return result.events


async def _read_all(
    pool: ProcessPoolExecutor | None, mbox_dir: str, candidates: list[_Candidate]
) -> list[_Read]:
    if not candidates:
        return []
    if pool is None:
        return await asyncio.to_thread(_read, mbox_dir, candidates)
    loop = asyncio.get_running_loop()
    chunks = [candidates[at : at + READ_CHUNK] for at in range(0, len(candidates), READ_CHUNK)]
    with spawning_workers():
        futures = [loop.run_in_executor(pool, _read, mbox_dir, chunk) for chunk in chunks]
    return [read for chunk in await asyncio.gather(*futures) for read in chunk]


async def _store(
    session: AsyncSession, ids: list[int], found: list[_Read], result: _Result
) -> None:
    """One page in one transaction: its mails' events replaced and their scans recorded; a
    candidate that could not be read keeps its events and gets no scan row."""
    events = {mail_id: parsed for mail_id, parsed in found if parsed is not None}
    unreadable = {mail_id for mail_id, parsed in found if parsed is None}
    looked = [mail_id for mail_id in ids if mail_id not in unreadable]
    await session.execute(_FORGET, {"ids": looked})
    rows = [
        (mail_id, at, event)
        for mail_id, parsed in events.items()
        for at, event in enumerate(parsed)
    ]
    if rows:
        inserted = await session.execute(_EVENTS, _event_parameters(rows))
        positions = {(mail_id, at): event_id for event_id, mail_id, at in inserted}
        attendees = [
            (positions[mail_id, at], number, attendee)
            for mail_id, at, event in rows
            for number, attendee in enumerate(event.attendees)
        ]
        if attendees:
            await session.execute(
                _ATTENDEES,
                {
                    "event_ids": [event_id for event_id, _, _ in attendees],
                    "positions": [number for _, number, _ in attendees],
                    "emails": [a.email for _, _, a in attendees],
                    "names": [a.name for _, _, a in attendees],
                    "roles": [a.role for _, _, a in attendees],
                    "partstats": [a.partstat for _, _, a in attendees],
                },
            )
    await session.execute(
        _SCANNED,
        {
            "version": CALENDAR_VERSION,
            "ids": looked,
            "read": [mail_id in events for mail_id in looked],
            "events": [len(events.get(mail_id, ())) for mail_id in looked],
        },
    )
    result.mails += len(looked)
    result.read += len(events)
    result.unreadable += len(unreadable)
    result.events += len(rows)


async def _store_alone(
    session: AsyncSession, ids: list[int], found: list[_Read], result: _Result
) -> None:
    """A page the database refused, again: the mails that were no candidates at once, then every
    candidate by itself; one whose events are refused is stored without them."""
    candidates = {mail_id for mail_id, _ in found}
    await _store(session, [mail_id for mail_id in ids if mail_id not in candidates], [], result)
    for mail_id, events in found:
        try:
            async with session.begin_nested():
                await _store(session, [mail_id], [(mail_id, events)], result)
        except DBAPIError as error:
            log.warning("calendar: mail %d: events not stored: %s", mail_id, describe(error))
            await _store(session, [mail_id], [(mail_id, [])], result)


def _event_parameters(rows: list[tuple[int, int, ParsedEvent]]) -> dict[str, Any]:
    events = [event for _, _, event in rows]
    organizers = [event.organizer for event in events]
    return {
        "mail_ids": [mail_id for mail_id, _, _ in rows],
        "positions": [at for _, at, _ in rows],
        "kinds": [event.kind for event in events],
        "methods": [event.method for event in events],
        "uids": [event.uid for event in events],
        "sequences": [event.sequence for event in events],
        "statuses": [event.status for event in events],
        "summaries": [event.summary for event in events],
        "locations": [event.location for event in events],
        "descriptions": [event.description for event in events],
        "starts_local": [event.starts_local for event in events],
        "ends_local": [event.ends_local for event in events],
        "zones": [event.time_zone for event in events],
        "starts_at": [event.starts_at for event in events],
        "ends_at": [event.ends_at for event in events],
        "all_day": [event.all_day for event in events],
        "recurrences": [event.recurrence for event in events],
        "organizer_emails": [None if o is None else o.email for o in organizers],
        "organizer_names": [None if o is None else o.name for o in organizers],
    }


async def _write_figures(session: AsyncSession) -> None:
    events = await session.scalar(_EVENT_COUNT) or 0
    mails = {kind: 0 for kind in EVENT_KINDS}
    for kind, count in await session.execute(_MAILS_PER_KIND):
        mails[kind] = count
    await write_figures(session, CalendarFigures(datetime.now(UTC), events, mails))

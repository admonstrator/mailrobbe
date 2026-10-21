"""Ground truth: the calendar phase of an import of the generated archive stores exactly the
events manifest.jsonl lists for each mail (D154, D155): Outlook's inline parts, the invite.ics
of web calendars and Apple Calendar, the .ics documents, answers, updates and cancellations,
duplicates included; the figures count the mails that are no duplicates."""

import asyncio
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.config import Settings
from mailrobbe.db.models import CALENDAR_VERSION
from mailrobbe.ical.model import CalendarFigures, read_figures
from mailrobbe.importer.cli import run_import
from tests.conftest import GeneratedArchive, _temporary_database

pytestmark = [pytest.mark.db, pytest.mark.slow]


@dataclass(frozen=True, slots=True)
class Stored:
    mail_ids: dict[tuple[str, int], int]  # (file, offset) -> mail id
    events: dict[int, list[dict[str, Any]]]  # mail id -> its events by position
    scans: dict[int, tuple[int, bool, int]]  # mail id -> version, read, events
    figures: CalendarFigures | None
    persons: set[str]  # every address the archive knows
    addresses: set[str]  # of organisers and attendees


@pytest.fixture(scope="module")
def stored(database_server_url: str, generated_archive: GeneratedArchive) -> Iterator[Stored]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(database_url=url, dkim_dns_override=generated_archive.dns_override)
        assert asyncio.run(run_import(settings, generated_archive.mbox_dir, 2)) == 0
        yield asyncio.run(_load(url))


async def _load(url: str) -> Stored:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:

        async def rows(sql: str) -> list[Any]:
            return list(await connection.execute(text(sql)))

        mail_ids = {
            (row.path, row.byte_offset): row.id
            for row in await rows(
                "SELECT m.id, f.path, m.byte_offset FROM mail m "
                "JOIN mbox_file f ON f.id = m.mbox_file_id"
            )
        }
        events: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in await rows(
            "SELECT e.*, (SELECT count(*) FROM calendar_attendee a WHERE a.event_id = e.id) "
            "AS attendees FROM calendar_event e ORDER BY e.mail_id, e.position"
        ):
            events[row.mail_id].append(row._asdict())
        scans = {
            row.mail_id: (row.version, row.read, row.events)
            for row in await rows("SELECT * FROM calendar_scan")
        }
        persons = {row.email for row in await rows("SELECT email FROM person_email")}
        addresses = {
            row.email
            for row in await rows(
                "SELECT organizer_email AS email FROM calendar_event "
                "UNION SELECT email FROM calendar_attendee"
            )
            if row.email is not None
        }
        figures = await read_figures(connection)
    await engine.dispose()
    return Stored(mail_ids, events, scans, figures, persons, addresses)


def _start(row: dict[str, Any], truth: str) -> bool:
    """Whether the stored start is the truth's: a date, an instant, or a floating time."""
    local: datetime = row["starts_local"]
    instant: datetime | None = row["starts_at"]
    if row["all_day"]:
        return local.date() == date.fromisoformat(truth)
    expected = datetime.fromisoformat(truth)
    if expected.tzinfo is None:
        return instant is None and local == expected
    return instant == expected


def _key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (item["uid"], item["method"], item["sequence"] or 0, item["kind"])


def test_every_event_of_the_manifest_is_stored(
    stored: Stored, generated_archive: GeneratedArchive
) -> None:
    checked = Counter[str]()
    for record in generated_archive.manifest:
        mail_id = stored.mail_ids[record["file"], record["offset"]]
        truths = record["calendar"]
        if truths is None:  # a byte fault broke an .ics document: its event is unknown
            continue
        rows = stored.events.get(mail_id, [])
        assert sorted(map(_key, rows)) == sorted(map(_key, truths)), record["index"]
        by_key = {_key(row): row for row in rows}
        for truth in truths:
            row = by_key[_key(truth)]
            assert row["attendees"] == truth["attendees"], record["index"]
            assert _start(row, truth["start"]), (record["index"], row, truth)
            if record["faults"].get("broken_encoding") != "wrong_charset":
                assert row["summary"] == truth["summary"], record["index"]
            checked[truth["kind"]] += 1
        version, read, events = stored.scans[mail_id]
        assert version == CALENDAR_VERSION and events == len(truths)
        assert read or not truths
    # invitations and answers; the small archive has no cancellation (tests/ical/test_parse.py
    # and the generator's tests on a larger plan have them)
    assert checked["request"] and checked["reply"]
    assert len(stored.scans) == len(stored.mail_ids)  # every mail looked at once


def test_the_figures_count_the_mails_that_are_no_duplicates(
    stored: Stored, generated_archive: GeneratedArchive
) -> None:
    mails: Counter[str] = Counter()
    events = 0
    for record in generated_archive.manifest:
        mail_id = stored.mail_ids[record["file"], record["offset"]]
        kinds = {row["kind"] for row in stored.events.get(mail_id, [])}
        events += len(stored.events.get(mail_id, []))
        if record["duplicate_of"] is None:
            mails.update(kinds)
    assert stored.figures is not None
    assert stored.figures.events == events
    assert stored.figures.mails == {kind: mails[kind] for kind in ("request", "reply", "cancel")}


def test_organisers_and_attendees_are_no_persons(
    stored: Stored, generated_archive: GeneratedArchive
) -> None:
    """An address only an event names (the organiser of an .ics document) stays an address of
    the event: the phase creates no person (D155)."""
    participants = {
        email
        for record in generated_archive.manifest
        for email in (record["sender"], *record["to"], *record["cc"], *record["bcc"])
    }
    only_events = stored.addresses - participants
    assert only_events  # vorstand@verein.example of the .ics documents
    assert not only_events & stored.persons

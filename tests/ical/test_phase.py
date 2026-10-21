"""The calendar phase of an import (D154, D158): only candidates are read, their events stored
per mail, every mail looked at once per CALENDAR_VERSION; an archive imported before gets its
events at the next import, and a second import reads only new mails."""

import asyncio
import base64
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from mailrobbe import migrate
from mailrobbe.config import Settings
from mailrobbe.db.models import CALENDAR_VERSION
from mailrobbe.ical import phase
from mailrobbe.ical.model import read_figures
from mailrobbe.importer.cli import run_import
from mailrobbe.jobrun import Step
from mailrobbe.jobs import ImportProgress
from tests.ical.test_parse import OUTLOOK, REPLY, WEB
from tests.importer.doubles import write_mbox

pytestmark = [pytest.mark.db, pytest.mark.slow]

ORGANIZER = "hans.mueller@nordlicht-gmbh.example"
ANNA = "anna.keller@nordlicht-gmbh.example"


def _mail(number: int, subject: str, body: str, *parts: str, sender: str = ORGANIZER) -> bytes:
    """A mail with a text part and, when given, more MIME parts (header lines, blank, body)."""
    head = (
        f"From: {sender}\nTo: {ANNA}\nSubject: {subject}\n"
        f"Date: Mon, {number + 1} Jul 2024 09:00:00 +0200\n"
        f"Message-ID: <m{number}@nordlicht-gmbh.example>\nMIME-Version: 1.0\n"
    )
    if not parts:
        return f"{head}Content-Type: text/plain; charset=utf-8\n\n{body}\n".encode()
    text_part = f"Content-Type: text/plain; charset=utf-8\n\n{body}\n"
    joined = "".join(f"--b{number}\n{part}" for part in (text_part, *parts))
    return (
        f"{head}Content-Type: multipart/mixed; boundary=b{number}\n\n{joined}--b{number}--\n"
    ).encode()


def _inline(calendar: str, method: str) -> str:
    """An inline calendar part as Outlook sends it: no name, base64."""
    data = base64.encodebytes(calendar.encode()).decode()
    return (
        f'Content-Type: text/calendar; charset="utf-8"; method={method}\n'
        f"Content-Transfer-Encoding: base64\n\n{data}"
    )


def _invite_ics(calendar: str) -> str:
    data = base64.encodebytes(calendar.encode()).decode()
    return (
        'Content-Type: application/ics; name="invite.ics"\n'
        'Content-Disposition: attachment; filename="invite.ics"\n'
        f"Content-Transfer-Encoding: base64\n\n{data}"
    )


OUTLOOK_TEXT = (
    "Wann: Montag, 15. Juli 2024 10:00-11:30 (UTC+01:00) Amsterdam, Berlin, Bern, Rom.\n"
    "Ort: Besprechungsraum 2\n\n*~*~*~*~*~*~*~*~*~*\n\nHallo zusammen"
)
MAILS = [
    # 0: Outlook's inline invitation, found by the lines of its text
    _mail(0, "Vorstandssitzung", OUTLOOK_TEXT, _inline(OUTLOOK, "REQUEST")),
    # 1: the answer, found by its subject (Outlook writes no text)
    _mail(1, "Angenommen: Vorstandssitzung", "", _inline(REPLY, "REPLY"), sender=ANNA),
    # 2: a web calendar's invitation, found by its attachment
    _mail(2, "Kick-off Nordlicht", "Sie wurden eingeladen.", _invite_ics(WEB)),
    # 3: no candidate
    _mail(3, "Einladung zum Sommerfest", "Wir feiern am Samstag im Garten."),
    # 4: a candidate by its subject without a calendar part
    _mail(4, "AW: Einladung: Grillen", "Ich komme gern."),
]


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    migrate.upgrade("head", empty_database_url)
    return empty_database_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    yield engine
    await engine.dispose()


def _archive(directory: Path, files: dict[str, Sequence[bytes]]) -> Path:
    directory.mkdir(exist_ok=True)
    for name, messages in files.items():
        write_mbox(directory / name, messages)
    return directory


async def _rows(engine: AsyncEngine, sql: str, **params: Any) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        return [dict(row._mapping) for row in await connection.execute(text(sql), params)]


async def _scans(engine: AsyncEngine) -> dict[str, tuple[bool, int]]:
    rows = await _rows(
        engine,
        "SELECT m.subject, s.read, s.events, s.version FROM calendar_scan s "
        "JOIN mail m ON m.id = s.mail_id",
    )
    assert all(row["version"] == CALENDAR_VERSION for row in rows)
    return {row["subject"]: (row["read"], row["events"]) for row in rows}


async def _events(engine: AsyncEngine) -> list[dict[str, Any]]:
    return await _rows(
        engine,
        "SELECT m.subject AS mail, e.position, e.kind, e.method, e.summary, e.time_zone, "
        "e.starts_at, e.organizer_email, e.organizer_name, "
        "array(SELECT a.email || ' ' || coalesce(a.partstat, '-') FROM calendar_attendee a "
        "      WHERE a.event_id = e.id ORDER BY a.position) AS attendees "
        "FROM calendar_event e JOIN mail m ON m.id = e.mail_id ORDER BY m.id, e.position",
    )


async def _step(engine: AsyncEngine) -> Any:
    [row] = await _rows(engine, "SELECT progress FROM job ORDER BY id DESC LIMIT 1")
    steps = ImportProgress.model_validate(row["progress"]).steps
    return next(step for step in steps if step.key == "calendar")


async def test_candidates_are_read_and_their_events_stored(
    database_url: str, engine: AsyncEngine, tmp_path: Path
) -> None:
    mbox_dir = _archive(tmp_path / "mbox", {"a.mbox": MAILS})
    assert await run_import(Settings(database_url=database_url), mbox_dir, 2) == 0

    assert await _scans(engine) == {
        "Vorstandssitzung": (True, 1),
        "Angenommen: Vorstandssitzung": (True, 1),
        "Kick-off Nordlicht": (True, 1),
        "Einladung zum Sommerfest": (False, 0),
        "AW: Einladung: Grillen": (True, 0),
    }
    events = await _events(engine)
    assert [(e["mail"], e["kind"], e["summary"]) for e in events] == [
        ("Vorstandssitzung", "request", "Vorstandssitzung"),
        ("Angenommen: Vorstandssitzung", "reply", "Angenommen: Vorstandssitzung"),
        ("Kick-off Nordlicht", "request", "Kick-off Nordlicht"),
    ]
    invitation = events[0]
    assert (invitation["organizer_email"], invitation["organizer_name"]) == (
        ORGANIZER,
        "Müller, Hans",
    )
    assert invitation["time_zone"] == "W. Europe Standard Time"
    assert invitation["starts_at"].isoformat() == "2024-07-15T08:00:00+00:00"
    assert invitation["attendees"] == [f"{ANNA} NEEDS-ACTION", "jonas@elbtal.example NEEDS-ACTION"]
    assert events[1]["attendees"] == [f"{ANNA} ACCEPTED"]
    # organiser and attendees are no participants: only the senders and Anna are persons
    persons = await _rows(engine, "SELECT canonical_email FROM person ORDER BY 1")
    assert [row["canonical_email"] for row in persons] == [ANNA, ORGANIZER]

    async with engine.connect() as connection:
        figures = await read_figures(connection)
    assert figures is not None
    assert (figures.events, figures.mails) == (3, {"request": 2, "reply": 1, "cancel": 0})
    step = await _step(engine)
    assert (step.status, step.unit, step.done, step.total) == ("done", "mails", 5, 5)


async def test_a_second_import_looks_only_at_new_mails(
    database_url: str, engine: AsyncEngine, tmp_path: Path
) -> None:
    mbox_dir = _archive(tmp_path / "mbox", {"a.mbox": MAILS})
    settings = Settings(database_url=database_url)
    assert await run_import(settings, mbox_dir, 2) == 0
    before = await _events(engine)

    assert await run_import(settings, mbox_dir, 2) == 0
    assert (await _step(engine)).status == "skipped"
    assert await _events(engine) == before

    cancel = OUTLOOK.replace("METHOD:REQUEST", "METHOD:CANCEL").replace("SEQUENCE:0", "SEQUENCE:1")
    _archive(
        mbox_dir,
        {"b.mbox": [_mail(5, "Abgesagt: Vorstandssitzung", "", _inline(cancel, "CANCEL"))]},
    )
    assert await run_import(settings, mbox_dir, 2) == 0
    step = await _step(engine)
    assert (step.status, step.done, step.total) == ("done", 1, 1)
    events = await _events(engine)
    assert events[:3] == before
    assert [(e["mail"], e["kind"]) for e in events[3:]] == [
        ("Abgesagt: Vorstandssitzung", "cancel")
    ]
    async with engine.connect() as connection:
        figures = await read_figures(connection)
    assert figures is not None and figures.mails == {"request": 2, "reply": 1, "cancel": 1}


async def test_an_archive_imported_before_gets_its_events_and_a_new_version_replaces_them(
    database_url: str, engine: AsyncEngine, tmp_path: Path
) -> None:
    mbox_dir = _archive(tmp_path / "mbox", {"a.mbox": MAILS})
    assert await run_import(Settings(database_url=database_url), mbox_dir, 2) == 0
    before = await _events(engine)
    async with engine.begin() as connection:  # as before milestone 14: nothing looked at
        await connection.execute(text("DELETE FROM calendar_scan"))
        await connection.execute(text("DELETE FROM calendar_event"))
        await connection.execute(text("DELETE FROM global_stats WHERE key = 'calendar'"))
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        assert await phase.waiting(session) == len(MAILS)
    step = Step("mails", len(MAILS))
    stored = await phase.scan_calendar(sessionmaker, mbox_dir, 1, _never(), step)
    assert (stored, step.done) == (3, len(MAILS))
    assert await _events(engine) == before

    async with engine.begin() as connection:  # an older version: every mail again
        await connection.execute(text("UPDATE calendar_scan SET version = version - 1"))
    assert await phase.scan_calendar(sessionmaker, mbox_dir, 1, _never(), Step()) == 3
    assert await _events(engine) == before  # replaced, not added
    async with sessionmaker() as session:
        assert await phase.waiting(session) == 0


async def test_a_changed_file_keeps_the_events_and_is_tried_again(
    database_url: str, engine: AsyncEngine, tmp_path: Path
) -> None:
    mbox_dir = _archive(tmp_path / "mbox", {"a.mbox": MAILS})
    assert await run_import(Settings(database_url=database_url), mbox_dir, 2) == 0
    before = await _events(engine)
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE calendar_scan SET version = version - 1"))
    data = (mbox_dir / "a.mbox").read_bytes()
    (mbox_dir / "a.mbox").write_bytes(data.replace(b"Hallo zusammen", b"Hallo Zusammen"))

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    assert await phase.scan_calendar(sessionmaker, mbox_dir, 1, _never(), Step()) == 2
    assert await _events(engine) == before
    async with sessionmaker() as session:
        assert await phase.waiting(session) == 1  # the changed candidate
    rows = await _rows(engine, "SELECT version FROM calendar_scan ORDER BY mail_id")
    assert [row["version"] for row in rows] == [CALENDAR_VERSION - 1] + [CALENDAR_VERSION] * 4


async def test_worker_processes_read_large_pages(
    database_url: str, engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mbox_dir = _archive(tmp_path / "mbox", {"a.mbox": MAILS})
    assert await run_import(Settings(database_url=database_url), mbox_dir, 2) == 0
    before = await _events(engine)
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE calendar_scan SET version = version - 1"))
    monkeypatch.setattr(phase, "READ_CHUNK", 1)
    monkeypatch.setattr(phase, "PAGE", 3)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    step = Step("mails", len(MAILS))
    assert await phase.scan_calendar(sessionmaker, mbox_dir, 2, _never(), step) == 3
    assert step.done == len(MAILS)
    assert await _events(engine) == before


async def test_a_stop_ends_the_phase_between_pages(
    database_url: str, engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mbox_dir = _archive(tmp_path / "mbox", {"a.mbox": MAILS})
    assert await run_import(Settings(database_url=database_url), mbox_dir, 2) == 0
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE calendar_scan SET version = version - 1"))
    monkeypatch.setattr(phase, "PAGE", 2)
    stop = _never()

    class Stopping(Step):
        def advance(self, count: int = 1) -> None:
            super().advance(count)
            stop.set()

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    step = Stopping("mails", len(MAILS))
    await phase.scan_calendar(sessionmaker, mbox_dir, 1, stop, step)
    assert step.done == 2
    async with sessionmaker() as session:
        assert await phase.waiting(session) == len(MAILS) - 2


def _never() -> asyncio.Event:
    return asyncio.Event()

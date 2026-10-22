"""The step places (D242, D243) on hand-made rows: place entities and invitation locations get
their points, a second step has nothing to do, new rows alone are looked at, new lists look at
everything again, a stop keeps what is stored, and a row the rules fail on fails alone."""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mailrobbe import migrate
from mailrobbe.jobrun import Step
from mailrobbe.places import gazetteer, phase
from mailrobbe.places.model import read_figures
from tests.conftest import _temporary_database

pytestmark = pytest.mark.db

# label, detail of the place entities
PLACES = [
    ("Frankfurt am Main", "city"),
    ("Neustadt", "city"),
    ("Entenhausen", "city"),
    ("Schweiz", "country"),
]
LOCATIONS = [
    "Rathaus, Marktplatz 1, 99423 Weimar",
    "Raum 3.14",
    None,  # no location: not looked at
    "   ",
    "Stadthalle Neustadt",
]


@asynccontextmanager
async def sessions(url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def execute(url: str, query: str, **parameters: Any) -> list[Any]:
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        result = await session.execute(text(query), parameters)
        return list(result) if result.returns_rows else []


async def add_places(url: str, places: list[tuple[str, str]]) -> None:
    for label, detail in places:
        await execute(
            url,
            "INSERT INTO entity (kind, key, label, detail) VALUES ('place', :key, :label, :detail)",
            key=gazetteer.fold(label),
            label=label,
            detail=detail,
        )


async def add_events(url: str, locations: list[str | None]) -> None:
    [(mail_id,)] = await execute(url, "SELECT min(id) FROM mail")
    [(position,)] = await execute(url, "SELECT count(*) FROM calendar_event")
    for number, location in enumerate(locations, start=position):
        await execute(
            url,
            "INSERT INTO calendar_event (mail_id, position, kind, location) "
            "VALUES (:mail, :position, 'request', :location)",
            mail=mail_id,
            position=number,
            location=location,
        )


@pytest.fixture(scope="module")
def places_template_url(database_server_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)

        async def fill() -> None:
            await execute(url, "INSERT INTO mbox_file (path, size_bytes) VALUES ('a.mbox', 0)")
            await execute(
                url,
                "INSERT INTO mail (mbox_file_id, byte_offset, byte_length, raw_sha256) "
                "SELECT id, 0, 100, 'a' FROM mbox_file",
            )
            await add_places(url, PLACES)
            await execute(
                url,
                "INSERT INTO entity (kind, key, label) VALUES ('organization', 'acme', 'ACME')",
            )
            await add_events(url, LOCATIONS)

        asyncio.run(fill())
        yield url


@pytest.fixture
def url(database_server_url: str, places_template_url: str) -> Iterator[str]:
    template = make_url(places_template_url).database
    with _temporary_database(database_server_url, template) as copy:
        yield copy


async def run(url: str, stop: asyncio.Event | None = None) -> tuple[phase.Waiting, Step]:
    """The step as the import runs it (importer.cli._locate_places): what waited, the step."""
    stop = stop or asyncio.Event()
    async with sessions(url) as sessionmaker:
        async with sessionmaker() as session:
            plan = await phase.waiting(session)
        step = Step("places", plan.rows)
        if plan.outdated or plan.rows:
            await phase.locate_places(sessionmaker, plan, stop, step)
    return plan, step


async def entities(url: str) -> dict[str, tuple[Any, ...]]:
    rows = await execute(
        url, "SELECT label, place_status, place_label, latitude, longitude FROM entity"
    )
    return {row.label: tuple(row)[1:] for row in rows}


async def events(url: str) -> list[tuple[Any, ...]]:
    rows = await execute(
        url,
        "SELECT location, place_status, place_label, latitude, longitude FROM calendar_event "
        "ORDER BY position",
    )
    return [tuple(row) for row in rows]


async def version(url: str) -> str | None:
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        figures = await read_figures(session)
    return None if figures is None else figures.version


async def test_the_step_gives_places_and_locations_their_points(url: str) -> None:
    plan, step = await run(url)

    assert plan == phase.Waiting(outdated=True, entities=4, events=3)
    assert (step.done, step.total) == (7, 7)
    found = await entities(url)
    status, label, latitude, longitude = found["Frankfurt am Main"]
    assert (status, label) == ("found", "Frankfurt am Main, Hessen, Deutschland")
    assert latitude == pytest.approx(50.11, abs=0.01) and longitude == pytest.approx(8.68, abs=0.01)
    assert found["Neustadt"] == ("ambiguous", None, None, None)
    assert found["Entenhausen"] == ("unknown", None, None, None)
    assert found["Schweiz"][:2] == ("found", "Schweiz")
    assert found["ACME"] == (None, None, None, None)  # no place
    weimar, room, nothing, blanks, neustadt = await events(url)
    assert weimar[1:3] == ("found", "Weimar, Thüringen, Deutschland")
    assert weimar[3] == pytest.approx(50.98, abs=0.01)
    assert room[1:] == ("unknown", None, None, None)
    assert nothing[1:] == blanks[1:] == (None, None, None, None)  # nothing names a place
    assert neustadt[1:] == ("ambiguous", None, None, None)
    assert await version(url) == gazetteer.places_version()

    # A second step has nothing to do: the import skips it.
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        assert await phase.waiting(session) == phase.Waiting(False, 0, 0)


async def test_only_new_rows_are_looked_at(url: str) -> None:
    await run(url)
    await execute(url, "UPDATE entity SET place_label = 'kept' WHERE label = 'Frankfurt am Main'")
    await add_places(url, [("München", "city")])
    await add_events(url, ["1010 Wien"])

    plan, step = await run(url)

    assert plan == phase.Waiting(False, 1, 1)
    assert step.done == 2
    found = await entities(url)
    assert found["München"][:2] == ("found", "München, Bayern, Deutschland")
    assert found["Frankfurt am Main"][1] == "kept"  # not looked at again
    assert (await events(url))[-1][1:3] == ("found", "Wien, Österreich")


async def test_new_lists_look_at_everything_again(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run(url)
    await execute(url, "UPDATE entity SET place_label = 'old' WHERE label = 'Frankfurt am Main'")
    await execute(url, "UPDATE calendar_event SET place_status = 'found' WHERE location = '   '")
    monkeypatch.setattr(phase, "places_version", lambda: "other")

    plan, _ = await run(url)

    assert plan == phase.Waiting(True, 4, 3)
    found = await entities(url)
    assert found["Frankfurt am Main"][1] == "Frankfurt am Main, Hessen, Deutschland"
    assert (await events(url))[3][1] is None  # reset, and not looked at
    assert await version(url) == "other"


async def test_a_stop_keeps_what_is_stored_and_the_next_step_goes_on(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(phase, "BATCH", 1)
    stop = asyncio.Event()

    class Stopping(Step):
        def advance(self, count: int = 1) -> None:
            super().advance(count)
            stop.set()

    async with sessions(url) as sessionmaker:
        async with sessionmaker() as session:
            plan = await phase.waiting(session)
        step = Stopping("places", plan.rows)
        await phase.locate_places(sessionmaker, plan, stop, step)

    assert step.done == 1
    statuses = [row[0] for row in (await entities(url)).values()]
    assert statuses.count(None) == 4  # three places and the organisation
    # The reset recorded the new version, so the next step goes on where this one stopped.
    plan, step = await run(url)
    assert plan == phase.Waiting(False, 3, 3)
    assert step.done == 6


async def test_a_row_the_rules_fail_on_fails_alone(
    url: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    real = phase.locate_name

    def locate(label: str, detail: str | None) -> gazetteer.Located:
        if label == "Schweiz":
            raise ValueError("broken")
        return real(label, detail)

    monkeypatch.setattr(phase, "locate_name", locate)

    await run(url)

    found = await entities(url)
    assert found["Schweiz"] == ("unknown", None, None, None)
    assert found["Frankfurt am Main"][0] == "found"
    assert "ValueError: broken" in caplog.text
    assert "places done in " in caplog.text
    assert "place names found 1, ambiguous 1, unknown 2" in caplog.text

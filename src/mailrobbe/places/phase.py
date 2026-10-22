"""The step places of an import (D242, D243), from the database alone; nothing is read from the
MBOX files.

    outdated  when no step ran yet, or the last one used other lists or rules (PlaceFigures
              against gazetteer.places_version()), every place entity and every invitation
              loses its point and status, one statement each; the new version goes to
              global_stats 'places' in the same transaction, so a stopped step goes on where it
              stopped
    entities  every place entity (kind place) without a status, by its label and detail
              (gazetteer.locate_name), in batches of BATCH by id, one transaction each
    events    every calendar event without a status whose location says something, by its
              location (gazetteer.locate_location); an event without a location, or with blanks
              only, is not looked at and keeps no status (NULL), as nothing names a place

Each row gets found with its point and label, ambiguous or unknown; a row the rules fail on
(a bug) gets unknown and a log line, so one row never stops the step. The entities phase may
make place entities again (D84): they come without a status and wait for the next step. A stop
(D46) ends the step between two batches; what is stored stays.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.jobrun import Step, describe
from mailrobbe.places.gazetteer import (
    UNKNOWN,
    Located,
    locate_location,
    locate_name,
    places_version,
)
from mailrobbe.places.model import PlaceFigures, read_figures, write_figures

log = logging.getLogger(__name__)

STEP = "places"
BATCH = 2000  # rows per read and transaction

_ENTITIES = "FROM entity WHERE kind = 'place'"
_EVENTS = "FROM calendar_event WHERE btrim(coalesce(location, '')) <> ''"
_RESET_ENTITIES = text("""
    UPDATE entity SET latitude = NULL, longitude = NULL, place_status = NULL, place_label = NULL
    WHERE kind = 'place' AND place_status IS NOT NULL
""")
_RESET_EVENTS = text("""
    UPDATE calendar_event
    SET latitude = NULL, longitude = NULL, place_status = NULL, place_label = NULL
    WHERE place_status IS NOT NULL
""")
_COUNT = text(f"""
    SELECT (SELECT count(*) {_ENTITIES} AND (:every OR place_status IS NULL)),
           (SELECT count(*) {_EVENTS} AND (:every OR place_status IS NULL))
""")
_ENTITY_ROWS = text(f"""
    SELECT id, label, detail {_ENTITIES} AND place_status IS NULL AND id > :after
    ORDER BY id LIMIT :limit
""")
_EVENT_ROWS = text(f"""
    SELECT id, location {_EVENTS} AND place_status IS NULL AND id > :after
    ORDER BY id LIMIT :limit
""")
_STORE = """
    UPDATE {table} t SET latitude = u.latitude, longitude = u.longitude,
        place_status = u.status, place_label = u.label
    FROM unnest(CAST(:ids AS bigint[]), CAST(:latitudes AS float8[]),
                CAST(:longitudes AS float8[]), CAST(:statuses AS text[]),
                CAST(:labels AS text[]))
        AS u(id, latitude, longitude, status, label)
    WHERE t.id = u.id
"""
_STORE_ENTITIES = text(_STORE.format(table="entity"))
_STORE_EVENTS = text(_STORE.format(table="calendar_event"))


@dataclass(frozen=True, slots=True)
class Waiting:
    """What the next step places has to do."""

    outdated: bool  # the lists or rules changed, or no step ran: everything again
    entities: int  # place entities to look at
    events: int  # calendar events with a location to look at

    @property
    def rows(self) -> int:
        return self.entities + self.events


@dataclass(frozen=True, slots=True)
class PlacesResult:
    """What one step stored, by status, per kind of row."""

    entities: dict[str, int]
    events: dict[str, int]
    seconds: float


async def waiting(session: AsyncSession) -> Waiting:
    """The rows the step would look at; none and not outdated: the step is skipped."""
    figures = await read_figures(session)
    outdated = figures is None or figures.version != places_version()
    entities, events = (await session.execute(_COUNT, {"every": outdated})).one()
    return Waiting(outdated, int(entities), int(events))


async def locate_places(
    sessionmaker: async_sessionmaker[AsyncSession],
    plan: Waiting,
    stop: asyncio.Event,
    step: Step,
) -> PlacesResult:
    """The step places: reset when outdated, then the entities, then the events."""
    started = datetime.now(UTC)
    version = places_version()
    if plan.outdated:
        async with sessionmaker() as session, session.begin():
            await session.execute(_RESET_ENTITIES)
            await session.execute(_RESET_EVENTS)
            await write_figures(session, PlaceFigures(started, version))
    entities = await _locate(sessionmaker, _ENTITY_ROWS, _STORE_ENTITIES, _entity, stop, step)
    events: dict[str, int] = {}
    if not stop.is_set():
        events = await _locate(sessionmaker, _EVENT_ROWS, _STORE_EVENTS, _event, stop, step)
    if not stop.is_set():
        async with sessionmaker() as session, session.begin():
            await write_figures(session, PlaceFigures(datetime.now(UTC), version))
    seconds = (datetime.now(UTC) - started).total_seconds()
    result = PlacesResult(entities, events, seconds)
    log.info(
        "places %s in %.1f s: place names %s; invitation locations %s",
        "stopped" if stop.is_set() else "done",
        seconds,
        _counts(result.entities),
        _counts(result.events),
    )
    return result


def _entity(row: Any) -> Located:
    return locate_name(row.label, row.detail)


def _event(row: Any) -> Located:
    return locate_location(row.location)


async def _locate(
    sessionmaker: async_sessionmaker[AsyncSession],
    rows_statement: TextClause,
    store: TextClause,
    rule: Callable[[Any], Located],
    stop: asyncio.Event,
    step: Step,
) -> dict[str, int]:
    """Look at the waiting rows of one table in batches; the rows stored by status."""
    counts: dict[str, int] = {}
    after = 0
    while not stop.is_set():
        async with sessionmaker() as session, session.begin():
            parameters = {"after": after, "limit": BATCH}
            rows = (await session.execute(rows_statement, parameters)).all()
            if not rows:
                break
            found = await asyncio.to_thread(_apply, rule, rows)
            await session.execute(store, _parameters(rows, found))
        for located in found:
            counts[located.status.value] = counts.get(located.status.value, 0) + 1
        step.advance(len(rows))
        after = rows[-1].id
    return counts


def _apply(rule: Callable[[Any], Located], rows: Sequence[Any]) -> list[Located]:
    found: list[Located] = []
    for row in rows:
        try:
            found.append(rule(row))
        except Exception as error:  # the rules never raise: a bug, for this row alone
            log.warning("places: row %d: %s", row.id, describe(error))
            found.append(UNKNOWN)
    return found


def _parameters(rows: Sequence[Any], found: Sequence[Located]) -> dict[str, Any]:
    return {
        "ids": [row.id for row in rows],
        "latitudes": [located.latitude for located in found],
        "longitudes": [located.longitude for located in found],
        "statuses": [located.status.value for located in found],
        "labels": [located.label for located in found],
    }


def _counts(counts: dict[str, int]) -> str:
    """ "found 3, ambiguous 1" in the order of the statuses; "none" without rows."""
    order = ("found", "ambiguous", "unknown")
    return ", ".join(f"{status} {counts[status]}" for status in order if counts.get(status)) or (
        "none"
    )

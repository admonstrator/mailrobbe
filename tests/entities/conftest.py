"""Database fixtures of the entity tests: the generated archive imported as in tests/api, its
entities scanned once for the tests that only read, and copies for the tests that change it.

The copies start from no scan at all whether or not the import ran the entities phase, so that
every test sees the work of a whole phase.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mailrobbe.entities.phase import EntityPhaseResult, Extractor, scan_entities
from tests.api.conftest import imported_database_url  # noqa: F401  (a fixture)
from tests.conftest import _temporary_database


class Step:
    """Stands in for the import's jobrun.Step: what the phase counted."""

    def __init__(self, stop: asyncio.Event | None = None) -> None:
        self.done = 0
        self.calls = 0
        self.stop = stop  # set at the first advance: a stop after the first stored batch

    def advance(self, count: int = 1) -> None:
        self.done += count
        self.calls += 1
        if self.stop is not None:
            self.stop.set()


@asynccontextmanager
async def sessions(url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def scan(
    url: str,
    workers: int = 2,
    *,
    step: Step | None = None,
    stop: asyncio.Event | None = None,
    extract: Extractor | None = None,
) -> EntityPhaseResult:
    """One entities phase over the database at `url`."""
    async with sessions(url) as sessionmaker:
        options = {} if extract is None else {"extract": extract}
        return await scan_entities(
            sessionmaker, workers, stop or asyncio.Event(), step or Step(), **options
        )


async def execute(url: str, statement: str, **parameters: object) -> None:
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        await session.execute(text(statement), parameters)


async def rows(url: str, query: str, **parameters: object) -> list[tuple[Any, ...]]:
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        return [tuple(row) for row in await session.execute(text(query), parameters)]


async def value(url: str, query: str, **parameters: object) -> Any:
    [(result,)] = await rows(url, query, **parameters)
    return result


async def entities_now(url: str) -> dict[str, list[tuple[Any, ...]]]:
    """The entity tables, in id order: what two scans of the same archive must agree on."""
    return {
        "entity": await rows(
            url,
            """SELECT id, kind::text, key, label, value, currency, detail, mails, documents,
                      first_date, last_date
               FROM entity ORDER BY id""",
        ),
        "mail_entity": await rows(
            url,
            """SELECT mail_id, entity_id, occurrences, context, position
               FROM mail_entity ORDER BY mail_id, entity_id""",
        ),
        "document_entity": await rows(
            url,
            """SELECT document_id, entity_id, occurrences, context, position
               FROM document_entity ORDER BY document_id, entity_id""",
        ),
    }


async def forget_entities(url: str) -> None:
    """No entity and no scan, as before the first entities phase."""
    for table in ("mail_entity_scan", "document_entity_scan", "entity"):
        await execute(url, f"DELETE FROM {table}")


@pytest.fixture(scope="session")
def scanned_database_url(
    database_server_url: str,
    imported_database_url: str,  # noqa: F811  (the fixture imported above)
) -> Iterator[str]:
    """The imported archive with its entities scanned by two workers; tests must not change it."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        asyncio.run(forget_entities(url))
        asyncio.run(scan(url))
        yield url


@pytest.fixture
def unscanned_url(
    database_server_url: str,
    imported_database_url: str,  # noqa: F811
) -> Iterator[str]:
    """A copy of the imported archive without entities, for one test."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        asyncio.run(forget_entities(url))
        yield url


@pytest.fixture
def scanned_url(database_server_url: str, scanned_database_url: str) -> Iterator[str]:
    """A copy of the scanned archive, for one test that changes it."""
    template = make_url(scanned_database_url).database
    with _temporary_database(database_server_url, template) as url:
        yield url

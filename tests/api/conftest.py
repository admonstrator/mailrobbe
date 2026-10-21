"""API test fixtures: the generated archive imported once, and HTTP clients against it.

client reads the shared database and must not change it; tests that write (note, DKIM recheck)
use mutable_client, whose database is a fresh copy made from the imported one as a template.
DKIM keys come from the generator's override table, so nothing queries real DNS.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import make_url

from mailrobbe import migrate
from mailrobbe.api.app import create_app
from mailrobbe.config import Settings
from mailrobbe.importer.cli import run_import
from tests.conftest import GeneratedArchive, _temporary_database


@pytest.fixture(scope="session")
def imported_database_url(
    database_server_url: str, generated_archive: GeneratedArchive
) -> Iterator[str]:
    """The 600 generated mails imported (with DKIM checks and finalize) into a fresh database."""
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(database_url=url, dkim_dns_override=generated_archive.dns_override)
        assert asyncio.run(run_import(settings, generated_archive.mbox_dir, 2)) == 0
        yield url


@pytest.fixture
def mutable_database_url(database_server_url: str, imported_database_url: str) -> Iterator[str]:
    """A copy of the imported database for one test; needs no open connection to the original."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        yield url


def api_settings(database_url: str, archive: GeneratedArchive, frontend_dir: Path) -> Settings:
    return Settings(
        database_url=database_url,
        mbox_dir=archive.mbox_dir,
        dkim_dns_override=archive.dns_override,
        frontend_dir=frontend_dir,
    )


async def _client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    # ASGITransport does not run the lifespan; enter it so the engine is disposed afterwards.
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def client(
    imported_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Client on the shared imported database, without a built frontend. Read only."""
    settings = api_settings(imported_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


@pytest.fixture
async def mutable_client(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Client on this test's own copy of the imported database."""
    settings = api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http

"""Graph test fixtures: the generated archive imported once (finalize fills edge and person.kind),
and a copy of it for tests that write.
"""

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import make_url

from mailrobbe import migrate
from mailrobbe.config import Settings
from mailrobbe.importer.cli import run_import
from tests.conftest import GeneratedArchive, _temporary_database


@pytest.fixture(scope="session")
def graph_database_url(
    database_server_url: str, generated_archive: GeneratedArchive
) -> Iterator[str]:
    """The 600 generated mails imported into a fresh database. Read only."""
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(database_url=url, dkim_dns_override=generated_archive.dns_override)
        assert asyncio.run(run_import(settings, generated_archive.mbox_dir, 2)) == 0
        yield url


@pytest.fixture
def graph_copy_url(database_server_url: str, graph_database_url: str) -> Iterator[str]:
    """A copy of the imported database for one test."""
    template = make_url(graph_database_url).database
    with _temporary_database(database_server_url, template) as url:
        yield url

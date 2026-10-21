"""Fixtures of the persons tests: edges standing in for milestone 6, and the generated archive.

archive_database_url holds the 600 generated mails imported once (with finalize, hence the
person figures and suggestions); tests read it only. archive_copy_url is a fresh copy for a
test that merges or holds locks across connections.
"""

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import make_url

from mailrobbe import aggregates, migrate
from mailrobbe.config import Settings
from mailrobbe.importer.cli import run_import
from tests.conftest import GeneratedArchive, _temporary_database
from tests.persons.helpers import refresh_test_edges


@pytest.fixture
def edges(monkeypatch: pytest.MonkeyPatch) -> None:
    """refresh_aggregates computes edges between roots (tests.persons.helpers._EDGES)."""
    monkeypatch.setattr(aggregates, "refresh_edges", refresh_test_edges)


@pytest.fixture(scope="session")
def archive_database_url(
    database_server_url: str, generated_archive: GeneratedArchive
) -> Iterator[str]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(database_url=url, dkim_dns_override=generated_archive.dns_override)
        assert asyncio.run(run_import(settings, generated_archive.mbox_dir, 2)) == 0
        yield url


@pytest.fixture
def archive_copy_url(database_server_url: str, archive_database_url: str) -> Iterator[str]:
    template = make_url(archive_database_url).database
    with _temporary_database(database_server_url, template) as url:
        yield url

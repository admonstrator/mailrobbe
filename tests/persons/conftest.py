"""Fixtures of the persons tests: the generated archive.

archive_database_url holds the 600 generated mails imported once (with finalize, hence the
person figures and suggestions); tests read it only. archive_copy_url is a fresh copy for a
test that merges or holds locks across connections.
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

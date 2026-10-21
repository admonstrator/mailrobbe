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
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.api.app import create_app
from mailrobbe.config import Settings
from mailrobbe.entities.model import scan_version
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


# Entities (milestone 10) ---------------------------------------------------------------------
#
# A known set of entities over a copy of the imported archive, written in SQL, so that the
# entity API and the mail list's entity filters are tested without the extraction. Mails are
# numbered by id (n), among the originals or among the duplicates by id (k), and in list order,
# oldest first (r); documents with text by the mails carrying them (d). Positions point into the
# mails' scanned text (entities.model.scanned_text: subject, line break, stored text) and into
# the documents' texts, so that snippets can be checked. The figures are set as the entities
# phase sets them (D85). Mail k=10 loses its date, and the person of the second-lowest id is
# merged into the one of the lowest, so that undated mails and root persons have cases.
ENTITY_ROWS = [
    "DELETE FROM entity",  # the import may have scanned the archive already
    "DELETE FROM mail_entity_scan",
    "DELETE FROM document_entity_scan",
    """CREATE TEMP TABLE m AS SELECT id, row_number() OVER (ORDER BY id) AS n,
        row_number() OVER (PARTITION BY is_duplicate_of IS NULL ORDER BY id) AS k,
        is_duplicate_of IS NOT NULL AS dup, length(coalesce(subject, '')) AS head,
        length(coalesce(body_text, '')) AS body
        FROM mail""",
    "UPDATE mail SET date_utc = NULL WHERE id = (SELECT id FROM m WHERE NOT dup AND k = 10)",
    """CREATE TEMP TABLE r AS SELECT id,
        row_number() OVER (ORDER BY coalesce(date_utc, '-infinity'), id) AS r FROM mail""",
    """CREATE TEMP TABLE d AS SELECT id, row_number() OVER (ORDER BY mails DESC, id) AS d,
        length(extracted_text) AS body
        FROM document WHERE text_status = 'text' AND length(extracted_text) > 200""",
    """UPDATE person SET merged_into = (SELECT min(id) FROM person)
        WHERE id = (SELECT id FROM person ORDER BY id OFFSET 1 LIMIT 1)""",
    """INSERT INTO entity (id, kind, key, label, value, currency, detail) OVERRIDING SYSTEM VALUE
        VALUES (1, 'amount', 'EUR 5000.00', '5.000,00 EUR', 5000, 'EUR', NULL),
               (2, 'amount', 'EUR 1234.56', '1.234,56 EUR', 1234.56, 'EUR', NULL),
               (3, 'amount', 'USD 250.00', '250,00 USD', 250, 'USD', NULL),
               (4, 'amount', 'DEM 10000.00', '10.000,00 DEM', 10000, 'DEM', NULL),
               (5, 'iban', 'DE89370400440532013000', 'DE89 3704 0044 0532 0130 00', NULL,
                NULL, 'DE'),
               (6, 'organization', 'muster gmbh', 'Muster GmbH', NULL, NULL, NULL),
               (10, 'place', 'köln', 'Köln', NULL, NULL, 'city'),
               (11, 'term', 'spenden/spende', 'Spende', NULL, NULL, 'spenden'),
               (12, 'date', '2024-01-15', '15.01.2024', NULL, NULL, NULL),
               (13, 'domain', 'muster.example', 'muster.example', NULL, NULL, NULL),
               (14, 'phone', '+493023125123', '+49 30 23125-123', NULL, NULL, 'DE'),
               (15, 'url', 'https://www.muster.example/', 'www.muster.example', NULL, NULL,
                'www.muster.example'),
               (16, 'organization', 'selten ag', 'Selten AG', NULL, NULL, NULL),
               (17, 'amount', 'EUR 0.50', '0,50 EUR', 0.5, 'EUR', NULL),
               (18, 'account', '1234567', 'Konto 1234567', NULL, NULL, NULL),
               (19, 'term', 'gewalt/angriff', 'Angriff', NULL, NULL, 'gewalt')""",
    # a person's name that exactly one root person has, in other case; one that several have
    """INSERT INTO entity (id, kind, key, label) OVERRIDING SYSTEM VALUE
        SELECT 7, 'person', lower(display_name), upper(display_name) FROM person p
        WHERE merged_into IS NULL AND display_name ~ '^[A-Za-z]+ [A-Za-z]+$'
            AND (SELECT count(*) FROM person q WHERE q.merged_into IS NULL
                AND lower(q.display_name) = lower(p.display_name)) = 1
        ORDER BY id LIMIT 1""",
    """INSERT INTO entity (id, kind, key, label) OVERRIDING SYSTEM VALUE
        SELECT 8, 'person', lower(display_name), display_name FROM person p
        WHERE merged_into IS NULL AND (SELECT count(*) FROM person q
            WHERE q.merged_into IS NULL AND lower(q.display_name) = lower(p.display_name)) > 1
        ORDER BY lower(display_name) COLLATE "C", id LIMIT 1""",
    # the address of the merged person
    """INSERT INTO entity (id, kind, key, label) OVERRIDING SYSTEM VALUE
        SELECT 9, 'email', canonical_email, canonical_email FROM person
        WHERE merged_into IS NOT NULL ORDER BY id LIMIT 1""",
    # (entity, mails, position, occurrences, context) in the mails' own texts
    """INSERT INTO mail_entity (entity_id, mail_id, position, occurrences, context)
        SELECT 6, id, head + 1, 1 + n % 2, 0 FROM m WHERE n % 3 = 0
        UNION ALL SELECT 1, id, 0, 1, (CASE WHEN n % 20 = 1 THEN 2 ELSE 0 END)
            | (CASE WHEN n % 30 = 1 THEN 1 ELSE 0 END) FROM m WHERE n % 10 = 1
        UNION ALL SELECT 3, id, CASE WHEN body > 400 THEN head + 301 ELSE head + 1 END, 2, 1
            FROM m WHERE n % 50 = 7
        UNION ALL SELECT 5, id, head + 1, 1, 6 FROM m WHERE n % 40 = 3
        UNION ALL SELECT 7, id, 0, 1, 0 FROM m WHERE NOT dup AND k IN (10, 20, 30)
        UNION ALL SELECT 8, id, 0, 1, 0 FROM m WHERE NOT dup AND k = 11
        UNION ALL SELECT 9, id, head + 1, 1, 0 FROM m WHERE NOT dup AND k IN (12, 13)
        UNION ALL SELECT 10, id, head + 1, 1, 0 FROM m WHERE n % 25 = 0
        UNION ALL SELECT 11, id, 0, 3, 0 FROM m WHERE n % 15 = 0
        UNION ALL SELECT 12, id, head + 1, 1, 0 FROM m WHERE n % 100 = 5
        UNION ALL SELECT 13, id, head + 1, 2, 0 FROM m WHERE n % 4 = 0
        UNION ALL SELECT 14, id, head + 1, 1, 0 FROM m WHERE n % 60 = 2
        UNION ALL SELECT 15, id, head + 1, 1, 0 FROM m WHERE n % 60 = 2
        UNION ALL SELECT 16, m.id, 0, 1, 0 FROM m JOIN r ON r.id = m.id WHERE r.r <= 3
        UNION ALL SELECT 17, id, 0, 1, 0 FROM m WHERE dup AND k = 1""",
    # in the documents' texts: d=1 is carried by most mails, duplicates among them
    """INSERT INTO document_entity (entity_id, document_id, position, occurrences, context)
        SELECT 2, id, 0, 1, 4 FROM d WHERE d = 1
        UNION ALL SELECT 6, id, 10, 2, 0 FROM d WHERE d = 1
        UNION ALL SELECT 11, id, 40, 1, 0 FROM d WHERE d = 2
        UNION ALL SELECT 1, id, 40, 1, 1 FROM d WHERE d = 2
        UNION ALL SELECT 4, id, CASE WHEN body > 400 THEN 300 ELSE 0 END, 1, 6 FROM d
            WHERE d = 3
        UNION ALL SELECT 18, id, 0, 1, 0 FROM d WHERE d = 3""",
    # the figures (D85): over the mentioning mails that are no duplicates
    """UPDATE entity e SET mails = f.mails, first_date = f.first_date, last_date = f.last_date
        FROM (SELECT x.entity_id, count(DISTINCT x.mail_id) AS mails,
                min(mail.date_utc) AS first_date, max(mail.date_utc) AS last_date
            FROM (SELECT entity_id, mail_id FROM mail_entity
                UNION ALL SELECT de.entity_id, a.mail_id FROM document_entity de
                JOIN attachment a ON a.document_id = de.document_id) x
            JOIN mail ON mail.id = x.mail_id AND mail.is_duplicate_of IS NULL
            GROUP BY x.entity_id) f
        WHERE f.entity_id = e.id""",
    """UPDATE entity e SET documents = (SELECT count(*) FROM document_entity de
        WHERE de.entity_id = e.id)""",
    # what the entities phase scanned: some mails and texts by an older version, a text
    # extracted again since its scan
    """INSERT INTO mail_entity_scan (mail_id, version)
        SELECT id, CASE WHEN n % 7 = 0 THEN -1 ELSE :version END FROM m WHERE n % 5 <> 0""",
    """INSERT INTO document_entity_scan (document_id, version, extracted_at)
        SELECT id, CASE WHEN id % 6 = 2 THEN -1 ELSE :version END,
            CASE WHEN id % 6 = 5 THEN extracted_at - interval '1 day' ELSE extracted_at END
        FROM document WHERE id % 3 <> 0""",
    "ANALYZE",
]


async def _execute(url: str, statements: list[str], **params: object) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement), params)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def entity_database_url(database_server_url: str, imported_database_url: str) -> Iterator[str]:
    """A copy of the imported archive with the entities of ENTITY_ROWS. Read only."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        asyncio.run(_execute(url, ENTITY_ROWS, version=scan_version()))
        yield url


@pytest.fixture
async def entity_client(
    entity_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Client on the archive with entities. Read only."""
    settings = api_settings(entity_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http

"""API test fixtures: the generated archive imported once, and HTTP clients against it.

client reads the shared database and must not change it; tests that write (note, DKIM recheck)
use mutable_client, whose database is a fresh copy made from the imported one as a template.
DKIM keys come from the generator's override table, so nothing queries real DNS.
"""

import asyncio
import json
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
from mailrobbe.signals.model import rules
from tests.api.search_cases import write_search_cases
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


# Signals (milestone 12) ----------------------------------------------------------------------
#
# Known signals over a copy of the imported archive, written in SQL as the signals phase stores
# them (D132 to D135), so that the API is tested apart from the phase. Internal is the domain
# with most persons (SIGNAL_INTERNAL), private are the generator's freemail providers
# (SIGNAL_FREEMAIL); many recipients are five here, as no generated mail has 25. Originals are
# numbered by id (k): k=3 gets a forward prefix, k=4 two attached mails, k=5 an unnamed one,
# k=6 and k=7 a Saturday evening in summer and in winter; the first original carrying a document
# with text mentions "unter uns" in its own text and "Diskretion" in that document. Forwards
# going outside are k=3, the first mail from inside to an external recipient and the first from
# outside to a private one. Before the
# rows are written, the private address of an open alias suggestion with an internal person is
# merged into that person; after them, the busiest sender at night is merged into the person of
# the lowest id, so that the overview has a person merged since the phase. Five persons are
# silent, that sender among them. The figures are those the rules of the default settings
# store (signals.model.SignalFigures).
SIGNAL_FREEMAIL = (
    r"^(webpost|netzpost|briefkasten|postfach|mailo|inbox|postamt|fernpost)\.(example|test)$"
)
SIGNAL_INTERNAL = "SELECT domain FROM person GROUP BY domain ORDER BY count(*) DESC, domain LIMIT 1"
SIGNAL_COMPUTED_AT = "2026-10-01T12:00:00+00:00"
SIGNAL_ROWS = [
    "DELETE FROM mail_signal",  # the import may have run the signals phase already
    "DELETE FROM person_signal",
    "DELETE FROM global_stats WHERE key = 'signals'",
    """CREATE TEMP TABLE m AS SELECT id, row_number() OVER (ORDER BY id) AS k FROM mail
        WHERE is_duplicate_of IS NULL""",
    """UPDATE mail SET subject = 'AW: WG: ' || coalesce(subject, '')
        WHERE id = (SELECT id FROM m WHERE k = 3)""",
    """INSERT INTO attachment (mail_id, filename, mime_type, size_bytes, position)
        SELECT id, CASE k WHEN 4 THEN 'Weitergeleitet.eml' END, 'message/rfc822', 2048, 90
        FROM m WHERE k IN (4, 5)
        UNION ALL SELECT id, 'Zweite.eml', 'message/rfc822', 1024, 91 FROM m WHERE k = 4""",
    "UPDATE mail SET has_attachments = true WHERE id IN (SELECT id FROM m WHERE k IN (4, 5))",
    "UPDATE mail SET date_utc = '2021-07-03 21:30:00+00' WHERE id = (SELECT id FROM m WHERE k = 6)",
    "UPDATE mail SET date_utc = '2021-01-09 22:15:00+00' WHERE id = (SELECT id FROM m WHERE k = 7)",
    """INSERT INTO entity (kind, key, label, detail)
        VALUES ('term', 'verschleierung:unter uns', 'unter uns', 'verschleierung'),
               ('term', 'verschleierung:diskretion', 'Diskretion', 'verschleierung')
        ON CONFLICT (kind, key) DO NOTHING""",
    """CREATE TEMP TABLE t AS SELECT a.mail_id, a.document_id FROM attachment a
        JOIN m ON m.id = a.mail_id JOIN document d ON d.id = a.document_id
        WHERE d.text_status = 'text' ORDER BY a.mail_id, a.document_id LIMIT 1""",
    """INSERT INTO mail_entity (entity_id, mail_id, position, occurrences, context)
        SELECT e.id, t.mail_id, 0, 1, 0 FROM entity e, t
        WHERE e.key = 'verschleierung:unter uns'""",
    """INSERT INTO document_entity (entity_id, document_id, position, occurrences, context)
        SELECT e.id, t.document_id, 0, 1, 0 FROM entity e, t
        WHERE e.key = 'verschleierung:diskretion'""",
    f"""CREATE TEMP TABLE c AS SELECT p.id, CASE
            WHEN p.domain = i.domain OR p.domain LIKE '%.' || i.domain THEN 'internal'
            WHEN p.domain ~ :freemail THEN 'private' ELSE 'external' END AS class
        FROM person p, ({SIGNAL_INTERNAL}) i""",
    """CREATE TEMP TABLE alias AS SELECT
            CASE WHEN a.class = 'private' THEN s.person_a ELSE s.person_b END AS id,
            CASE WHEN a.class = 'private' THEN s.person_b ELSE s.person_a END AS root
        FROM alias_suggestion s JOIN c a ON a.id = s.person_a JOIN c b ON b.id = s.person_b
            JOIN person pa ON pa.id = s.person_a JOIN person pb ON pb.id = s.person_b
        WHERE (a.class, b.class) IN (('internal', 'private'), ('private', 'internal'))
        ORDER BY greatest(pa.canonical_email COLLATE "C", pb.canonical_email COLLATE "C") DESC
        LIMIT 1""",
    "UPDATE person SET merged_into = alias.root FROM alias WHERE person.id = alias.id",
    """DELETE FROM alias_suggestion
        WHERE person_a IN (SELECT id FROM alias) OR person_b IN (SELECT id FROM alias)""",
    # every participant with the class of its address and its root person
    """CREATE TEMP TABLE pa AS SELECT pa.mail_id, pa.role, c.id, c.class,
            coalesce(p.merged_into, p.id) AS root
        FROM participation pa JOIN c ON c.id = pa.person_id JOIN person p ON p.id = c.id""",
    """INSERT INTO mail_signal (signal, mail_id)
        SELECT 'private', mail_id FROM pa WHERE class = 'private'
        UNION SELECT 'internal_to_private', s.mail_id FROM pa s JOIN pa r USING (mail_id)
            WHERE s.role = 'from' AND r.role <> 'from' AND s.class = 'internal'
                AND r.class = 'private'
        UNION SELECT 'private_to_internal', s.mail_id FROM pa s JOIN pa r USING (mail_id)
            WHERE s.role = 'from' AND r.role <> 'from' AND s.class = 'private'
                AND r.class = 'internal'
        UNION SELECT 'private_alias', x.mail_id FROM pa x WHERE x.class = 'private' AND (
            EXISTS (SELECT 1 FROM pa o WHERE o.root = x.root AND o.class = 'internal')
            OR EXISTS (SELECT 1 FROM alias_suggestion s JOIN c o
                ON o.id = CASE WHEN s.person_a = x.root THEN s.person_b ELSE s.person_a END
                WHERE x.root IN (s.person_a, s.person_b) AND o.class = 'internal'))
        UNION SELECT 'bcc', mail_id FROM pa WHERE role = 'bcc'
        UNION SELECT 'many_recipients', mail_id FROM pa WHERE role <> 'from'
            GROUP BY mail_id HAVING count(DISTINCT id) >= 5
        UNION SELECT 'forward', id FROM m WHERE k IN (4, 5)
        UNION SELECT f.signal, x.mail_id FROM (VALUES ('forward'), ('forward_out')) AS f (signal),
            (SELECT id AS mail_id FROM m WHERE k = 3
                UNION SELECT min(s.mail_id) FROM pa s JOIN pa r USING (mail_id)
                WHERE s.role = 'from' AND r.role <> 'from' AND s.class = 'internal'
                    AND r.class = 'external'
                UNION SELECT min(s.mail_id) FROM pa s JOIN pa r USING (mail_id)
                WHERE s.role = 'from' AND r.role <> 'from' AND s.class = 'external'
                    AND r.class = 'private') x
        UNION SELECT 'night', id FROM mail
            WHERE extract(hour FROM timezone('Europe/Berlin', date_utc)) NOT BETWEEN 6 AND 21
        UNION SELECT 'weekend', id FROM mail
            WHERE extract(isodow FROM timezone('Europe/Berlin', date_utc)) >= 6
        UNION SELECT 'term:' || e.detail, x.mail_id FROM (
                SELECT entity_id, mail_id FROM mail_entity
                UNION ALL SELECT de.entity_id, a.mail_id FROM document_entity de
                JOIN attachment a ON a.document_id = de.document_id) x
            JOIN entity e ON e.id = x.entity_id WHERE e.kind = 'term'""",
    # per root person the mails it sent with each signal, no duplicates; then the silent ones
    """INSERT INTO person_signal (signal, person_id, mails)
        SELECT ms.signal, pa.root, count(DISTINCT ms.mail_id) FROM mail_signal ms
        JOIN mail ON mail.id = ms.mail_id AND mail.is_duplicate_of IS NULL
        JOIN pa ON pa.mail_id = ms.mail_id AND pa.role = 'from'
        GROUP BY ms.signal, pa.root""",
    """CREATE TEMP TABLE night AS SELECT person_id AS id FROM person_signal
        WHERE signal = 'night' ORDER BY mails DESC, person_id DESC LIMIT 1""",
    """INSERT INTO person_signal (signal, person_id, mails, since)
        SELECT 'silent', id, 50, timestamptz '2021-05-01 00:00+00' FROM night
        UNION ALL SELECT 'silent', id, (ARRAY[9, 9, 7, 5])[n],
            (ARRAY[timestamptz '2021-03-01 00:00+00', '2021-04-01 00:00+00',
                '2020-11-01 00:00+00', '2021-02-01 00:00+00'])[n]
        FROM (SELECT id, row_number() OVER (ORDER BY id) AS n FROM person
            WHERE merged_into IS NULL AND kind IS NULL AND id NOT IN (SELECT id FROM night)
            ORDER BY id LIMIT 4) x""",
    """INSERT INTO global_stats (key, value) SELECT 'signals', jsonb_build_object(
        'computed_at', CAST(:computed_at AS text),
        'rules', CAST(:rules AS jsonb),
        'mails', (SELECT count(*) FROM mail WHERE is_duplicate_of IS NULL),
        'signals', (SELECT jsonb_object_agg(k.key, coalesce(n.mails, 0))
            FROM unnest(CAST(:keys AS text[])) AS k (key) LEFT JOIN (
                SELECT ms.signal, count(*) AS mails FROM mail_signal ms
                JOIN mail ON mail.id = ms.mail_id AND mail.is_duplicate_of IS NULL
                GROUP BY ms.signal) n ON n.signal = k.key),
        'persons', (SELECT jsonb_object_agg(signal, n) FROM
            (SELECT signal, count(*) AS n FROM person_signal GROUP BY signal) x))""",
    # merged since the phase: the busiest sender at night, and its aliases
    """CREATE TEMP TABLE target AS SELECT min(id) AS id FROM person
        WHERE merged_into IS NULL AND id NOT IN (SELECT id FROM night)""",
    """UPDATE person SET merged_into = (SELECT id FROM target)
        WHERE id IN (SELECT id FROM night) OR merged_into IN (SELECT id FROM night)""",
    """DELETE FROM alias_suggestion
        WHERE person_a IN (SELECT id FROM night) OR person_b IN (SELECT id FROM night)""",
    "ANALYZE",
]


@pytest.fixture(scope="session")
def signal_database_url(
    database_server_url: str, imported_database_url: str, generated_archive: GeneratedArchive
) -> Iterator[str]:
    """A copy of the imported archive with the signals of SIGNAL_ROWS. Read only."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        defaults = rules(api_settings(url, generated_archive, Path("no-frontend")))
        asyncio.run(
            _execute(
                url,
                SIGNAL_ROWS,
                freemail=SIGNAL_FREEMAIL,
                computed_at=SIGNAL_COMPUTED_AT,
                rules=json.dumps(defaults.snapshot()),
                keys=list(defaults.keys),
            )
        )
        yield url


@pytest.fixture
async def signal_client(
    signal_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Client on the archive with signals, under the default settings. Read only."""
    settings = api_settings(signal_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


# Search cases (D170 to D176) -----------------------------------------------------------------
#
# The ten mails of tests/api/search_cases.py imported into a database of their own, read only.


@pytest.fixture(scope="session")
def search_archive(tmp_path_factory: pytest.TempPathFactory) -> Path:
    mbox_dir = tmp_path_factory.mktemp("search") / "mbox"
    mbox_dir.mkdir()
    write_search_cases(mbox_dir / "faelle.mbox")
    return mbox_dir


@pytest.fixture(scope="session")
def search_database_url(database_server_url: str, search_archive: Path) -> Iterator[str]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        assert asyncio.run(run_import(Settings(database_url=url), search_archive, 1)) == 0
        yield url


@pytest.fixture
async def search_client(
    search_database_url: str, search_archive: Path, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Client on the search cases' database. Read only."""
    settings = Settings(
        database_url=search_database_url,
        mbox_dir=search_archive,
        frontend_dir=tmp_path / "no-frontend",
    )
    async for http in _client(settings):
        yield http


async def search_ids(client: httpx.AsyncClient) -> dict[int, int]:
    """Mail id by case index (search_cases.message_id)."""
    page = (await client.get("/api/mails", params={"sort": "date_asc"})).json()
    found = {}
    for item in page["items"]:
        detail = (await client.get(f"/api/mails/{item['id']}")).json()
        found[int(detail["message_id"].split("-")[1].split("@")[0])] = item["id"]
    return found

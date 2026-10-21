"""Fixtures of the topics phase tests: a small hand-made archive whose every figure is known.

SAMPLE is 49 mails that are no duplicates (39 in 2023, 9 in the first quarter of 2024, one
undated) and one duplicate. Every mail is signed by its sender, "Wilhelmine"; the words placed in
it test one rule each (the comments of sample()). The themes and the ignore list are replaced by
SAMPLE_THEMES and SAMPLE_IGNORE (fixture sample_themes), so the tests do not depend on themes.toml.

topics_template_url is the migrated schema with SAMPLE and its persons, not computed; computed_url
a copy with the topics computed once, for tests that only read; sample_url and computed_copy_url
are copies for one test that changes them.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mailrobbe import migrate, themes
from mailrobbe.jobrun import Steps
from mailrobbe.themes import Theme
from mailrobbe.topics.phase import TopicsResult, compute_topics, waiting
from tests.conftest import _temporary_database

SAMPLE_IGNORE = ("Besprechung",)
SAMPLE_THEMES = (
    Theme("spenden", "Spenden", "amber", "", ("Spende", "in bar"), ()),
    Theme("geld", "Geld", "green", "", ("Kasse", "Spenden"), ()),
)


def use_sample_themes(monkeypatch: pytest.MonkeyPatch) -> None:
    """SAMPLE_THEMES and SAMPLE_IGNORE in place of themes.toml."""
    monkeypatch.setattr(themes, "load_themes", lambda: SAMPLE_THEMES)
    monkeypatch.setattr(themes, "load_topic_ignore", lambda: SAMPLE_IGNORE)


@dataclass(frozen=True, slots=True)
class M:
    """A mail of a sample archive."""

    body: str
    day: date | None
    subject: str = "Vereinsnachricht"
    duplicate_of: int | None = None  # index of the original in the list


_KASSENWART = (
    "Der Kassenwart (kassenwart@verein.example, Kopie an <kassenwart@verein.example>) "
    "schreibt unter https://verein.example/kassenwart/kassenwart"
)


def sample() -> list[M]:
    """SAMPLE (module docstring): three mails in every month of 2023 and three more in July,
    three in every month of the first quarter of 2024, one undated mail and one duplicate."""
    days = [date(2023, month, 3 + 9 * k) for month in range(1, 13) for k in range(3)]
    days += [date(2023, 7, 4 + 9 * k) for k in range(3)]
    days += [date(2024, month, 3 + 9 * k) for month in range(1, 4) for k in range(3)]
    extra: dict[tuple[int, int, int], str] = {
        # Labels: the umlaut restored, the spelling written most, equally often, addresses.
        (2023, 2, 0): "Wir warten auf Ihre Rückmeldung.",
        (2023, 5, 0): "Danke für die Rückmeldung.",
        (2023, 9, 0): "Alle Rückmeldungen liegen vor.",
        (2023, 3, 0): "Die Spenden sind da.",
        (2023, 4, 0): "Weitere Spenden folgen.",
        (2023, 10, 0): "Spenden zählen.",
        (2023, 11, 0): "Spenden zählen wieder.",
        (2023, 6, 0): "Eine Spende kam.",
        (2023, 12, 0): "Noch eine Spende.",
        (2023, 1, 1): "Die Kasse stimmt.",
        (2023, 2, 1): "Die Kasse ist voll.",
        (2023, 3, 1): "Wer hat die kasse?",
        (2023, 4, 1): "Die kasse ist leer.",
        (2023, 5, 1): _KASSENWART,
        (2023, 6, 1): _KASSENWART,
        (2023, 8, 1): _KASSENWART,
        # Vocabulary: numbers, an English stop word, an ignored word in another form, a name
        # of a correspondent (Oberhuber), a name only mentioned (Brunhilde), and a word whose
        # third mail is a duplicate (Zwillingswort).
        (2023, 1, 2): "Nummer 4711 covid19",
        (2023, 2, 2): "Nummer 4711 covid19",
        (2023, 3, 2): "Nummer 4711 covid19",
        (2023, 4, 2): "About which",
        (2023, 5, 2): "About which",
        (2023, 6, 2): "About which",
        (2023, 8, 2): "Besprechungen",
        (2023, 9, 2): "Besprechungen",
        (2023, 10, 2): "Besprechungen",
        (2023, 11, 1): "Frau Oberhuber",
        (2023, 11, 2): "Frau Oberhuber",
        (2023, 12, 1): "Frau Oberhuber",
        (2023, 10, 1): "Brunhilde",
        (2023, 12, 2): "Brunhilde",
        (2023, 8, 0): "Zwillingswort",
        (2023, 9, 1): "Zwillingswort",
    }
    mails = []
    seen: dict[tuple[int, int], int] = {}
    for day in days:
        index = seen.get((day.year, day.month), 0)
        seen[day.year, day.month] = index + 1
        # Periods: Jahresmotto in every mail of 2023 (common in the year), Umzug in every mail
        # of 2024, Sommerfest in the six July mails only.
        words = ["Jahresmotto" if day.year == 2023 else "Umzug", "Verein"]
        if day.month == 7 and day.year == 2023:
            words.append("Sommerfest")
        words.append(extra.get((day.year, day.month, index), ""))
        mails.append(M(" ".join(words) + "\n\nWilhelmine", day))
    mails.append(M("Verein Brunhilde\n\nWilhelmine", None))
    original = next(i for i, mail in enumerate(mails) if "Zwillingswort" in mail.body)
    mails.append(M(mails[original].body, mails[original].day, duplicate_of=original))
    return mails


SAMPLE = sample()
SAMPLE_TOTAL = sum(1 for mail in SAMPLE if mail.duplicate_of is None)  # N


async def insert_mails(url: str, mails: list[M], *, path: str = "sample.mbox") -> list[int]:
    """The mails into the database at url, in one new file; their ids."""
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        file_id = await session.scalar(
            text("INSERT INTO mbox_file (path, size_bytes) VALUES (:path, 0) RETURNING id"),
            {"path": path},
        )
        ids: list[int] = []
        for index, mail in enumerate(mails):
            moment = None if mail.day is None else datetime.combine(mail.day, time(12), UTC)
            mail_id = await session.scalar(
                text("""
                    INSERT INTO mail (mbox_file_id, byte_offset, byte_length, raw_sha256,
                        subject, body_text, date_utc, is_duplicate_of)
                    VALUES (:file, :offset, 100, :sha, :subject, :body, :date, :original)
                    RETURNING id
                """),
                {
                    "file": file_id,
                    "offset": index * 100,
                    "sha": f"{path}-{index}",
                    "subject": mail.subject,
                    "body": mail.body,
                    "date": moment,
                    "original": None if mail.duplicate_of is None else ids[mail.duplicate_of],
                },
            )
            ids.append(int(mail_id))
    return ids


async def insert_persons(url: str) -> None:
    """The correspondents: one named on the person, one only in the names of an address."""
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        for email, name, names in (
            ("wilhelmine@verein.example", "Wilhelmine Oberhuber", '{"W. Oberhuber": 3}'),
            ("paula@verein.example", None, '{"Paula Spender": 2}'),
        ):
            person = await session.scalar(
                text("""
                    INSERT INTO person (canonical_email, display_name, domain)
                    VALUES (:email, :name, 'verein.example') RETURNING id
                """),
                {"email": email, "name": name},
            )
            await session.execute(
                text("""
                    INSERT INTO person_email (email, person_id, display_names)
                    VALUES (:email, :person, CAST(:names AS jsonb))
                """),
                {"email": email, "person": person, "names": names},
            )


@asynccontextmanager
async def sessions(url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def fingerprint_now(url: str) -> str | None:
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        return await waiting(session)


async def compute(
    url: str,
    *,
    stop: asyncio.Event | None = None,
    steps: Steps | None = None,
    fingerprint: str | None = None,
) -> TopicsResult | None:
    """One topics phase over the database at url, as the import runs it; with a fingerprint
    given, also when nothing changed."""
    fingerprint = fingerprint or await fingerprint_now(url)
    assert fingerprint is not None
    stop = stop or asyncio.Event()
    async with sessions(url) as sessionmaker:
        return await compute_topics(sessionmaker, fingerprint, stop, steps or Steps(stop))


async def rows(url: str, query: str, **parameters: object) -> list[tuple[Any, ...]]:
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        return [tuple(row) for row in await session.execute(text(query), parameters)]


async def value(url: str, query: str, **parameters: object) -> Any:
    [(result,)] = await rows(url, query, **parameters)
    return result


async def stored(url: str) -> dict[str, list[tuple[Any, ...]]]:
    """Every stored topic table, by lexeme and rank rather than ids where they have them."""
    return {
        "state": await rows(url, "SELECT id, fingerprint, computed_at, mails FROM topic_state"),
        "terms": await rows(
            url,
            'SELECT id, lexeme, label, mails, themes FROM topic_term ORDER BY lexeme COLLATE "C"',
        ),
        "periods": await rows(
            url, "SELECT unit, period_start, mails FROM topic_period ORDER BY unit, period_start"
        ),
        "period_terms": await rows(
            url,
            """SELECT unit, period_start, rank, term_id, mails, score FROM topic_period_term
               ORDER BY unit, period_start, rank""",
        ),
        "clusters": await rows(url, "SELECT * FROM topic_cluster ORDER BY rank"),
        "cluster_terms": await rows(
            url, "SELECT * FROM topic_cluster_term ORDER BY cluster_id, rank"
        ),
        "cluster_months": await rows(
            url, "SELECT * FROM topic_cluster_month ORDER BY cluster_id, month"
        ),
    }


@pytest.fixture(scope="session")
def topics_template_url(database_server_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        asyncio.run(insert_mails(url, SAMPLE))
        asyncio.run(insert_persons(url))
        yield url


@pytest.fixture
def sample_themes(monkeypatch: pytest.MonkeyPatch) -> None:
    use_sample_themes(monkeypatch)


@pytest.fixture(scope="session")
def computed_url(database_server_url: str, topics_template_url: str) -> Iterator[str]:
    """SAMPLE with its topics computed once; tests must not change it."""
    template = make_url(topics_template_url).database
    with _temporary_database(database_server_url, template) as url:
        with pytest.MonkeyPatch.context() as monkeypatch:  # not beyond the computation
            use_sample_themes(monkeypatch)
            assert asyncio.run(compute(url)) is not None
        yield url


@pytest.fixture
def sample_url(
    database_server_url: str, topics_template_url: str, sample_themes: None
) -> Iterator[str]:
    """A copy of SAMPLE without topics, for one test."""
    template = make_url(topics_template_url).database
    with _temporary_database(database_server_url, template) as url:
        yield url


@pytest.fixture
def computed_copy_url(
    database_server_url: str, computed_url: str, sample_themes: None
) -> Iterator[str]:
    """A copy of the computed SAMPLE, for one test."""
    template = make_url(computed_url).database
    with _temporary_database(database_server_url, template) as url:
        yield url

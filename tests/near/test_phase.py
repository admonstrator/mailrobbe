"""The near phase (D152, D153, D158) on a small hand-made archive: fingerprints of the mails
without one, groups with their duplicates, the figures, a second run, new mails, an older
version, a stop and a deleted mail."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mailrobbe import migrate
from mailrobbe.db.models import NEAR_VERSION
from mailrobbe.jobrun import Step
from mailrobbe.near import phase
from mailrobbe.near.model import NearFigures, fingerprint, read_figures
from tests.conftest import _temporary_database

pytestmark = pytest.mark.db

TEXT = (
    "{greeting}\n\nkurze Rückfrage zu unserem Telefonat von gestern. Hast du die Zahlen schon "
    "an die Geschäftsführung weitergegeben? Ich bräuchte sie bis Montag.\n\nDoris"
)
OTHER = "Hallo,\n\ndie Ware ist ab Lager verfügbar und geht morgen an Sie raus, mit Rechnung."


@dataclass(frozen=True, slots=True)
class M:
    body: str | None
    day: int  # of January 2024
    subject: str = "Kurze Rückfrage"
    duplicate_of: str | None = None  # name of the original


# name -> mail; the names sort as the ids are given (insertion order)
ARCHIVE = {
    "a1": M(TEXT.format(greeting="Hallo Martin,"), 5),
    "a2": M(TEXT.format(greeting="Guten Tag Frau Vogt,"), 3, subject="AW: Kurze Rückfrage"),
    "a1_copy": M(None, 5, duplicate_of="a1"),  # a duplicate whose text was not read
    "short": M("Danke!", 6),
    "alone": M(OTHER, 7, subject="Lieferung"),
    "single": M(OTHER, 8, subject="Bestellung"),
    "single_copy": M(OTHER, 8, subject="Bestellung", duplicate_of="single"),  # no group alone
    "a3": M(TEXT.format(greeting="Hi,"), 9, subject="[liste] Kurze Rückfrage"),
}


@asynccontextmanager
async def sessions(url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def rows(url: str, query: str, **parameters: object) -> list[Any]:
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        return list(await session.execute(text(query), parameters))


async def insert(
    url: str, mails: dict[str, M], ids: dict[str, int] | None = None
) -> dict[str, int]:
    """The mails into one new file; their ids by name, with those of ids."""
    ids = dict(ids or {})
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        file_id = await session.scalar(
            text("INSERT INTO mbox_file (path, size_bytes) VALUES (:path, 0) RETURNING id"),
            {"path": f"file-{len(ids)}.mbox"},
        )
        for index, (name, mail) in enumerate(mails.items()):
            ids[name] = await session.scalar(
                text("""
                    INSERT INTO mail (mbox_file_id, byte_offset, byte_length, raw_sha256,
                        subject, body_text, date_utc, is_duplicate_of)
                    VALUES (:file, :offset, 100, :sha, :subject, :body, :date, :original)
                    RETURNING id
                """),
                {
                    "file": file_id,
                    "offset": index * 100,
                    "sha": name,
                    "subject": mail.subject,
                    "body": mail.body,
                    "date": datetime(2024, 1, mail.day, 12, tzinfo=UTC),
                    "original": None if mail.duplicate_of is None else ids[mail.duplicate_of],
                },
            )
    return ids


@pytest.fixture(scope="module")
def near_template_url(database_server_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        yield url


@pytest.fixture
def url(database_server_url: str, near_template_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url, make_url(near_template_url).database) as copy:
        yield copy


async def run(url: str, stop: asyncio.Event | None = None) -> tuple[int, int, Step]:
    """Both steps as the import runs them (importer.cli._find_near): (waiting, stored, step)."""
    stop = stop or asyncio.Event()
    async with sessions(url) as sessionmaker:
        async with sessionmaker() as session:
            waiting = await phase.waiting(session)
        step = Step("mails", waiting)
        stored = await phase.fingerprint_mails(sessionmaker, stop, step) if waiting else 0
        if not stop.is_set():
            await phase.group_mails(sessionmaker, stop, Step())
    return waiting, stored, step


async def groups(url: str, ids: dict[str, int]) -> dict[str, str | None]:
    """The group of every mail by name: the name of the group's id."""
    names = {mail_id: name for name, mail_id in ids.items()}
    found = await rows(url, "SELECT mail_id, group_id FROM mail_near")
    return {names[row.mail_id]: names.get(row.group_id) for row in found}


async def figures(url: str) -> tuple[int, int, int]:
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        stored = await read_figures(session)
    assert isinstance(stored, NearFigures)
    return stored.groups, stored.mails, stored.hidden


GROUPED = {
    "a1": "a1",
    "a2": "a1",  # the smallest id that is no duplicate, not the earliest date
    "a1_copy": "a1",  # its original's group, without a fingerprint of its own
    "short": None,
    "alone": None,
    "single": None,
    "single_copy": None,
    "a3": "a1",
}


async def test_an_archive_imported_before_gets_fingerprints_and_groups(url: str) -> None:
    ids = await insert(url, ARCHIVE)
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        assert await read_figures(session) is None
    waiting, stored, step = await run(url)
    assert (waiting, stored, step.done) == (8, 8, 8)
    found = await rows(url, "SELECT mail_id, version, fingerprint FROM mail_near ORDER BY mail_id")
    assert [(row.mail_id, row.version) for row in found] == [
        (mail_id, NEAR_VERSION) for mail_id in sorted(ids.values())
    ]
    prints = {row.mail_id: row.fingerprint for row in found}
    for name, mail in ARCHIVE.items():
        assert prints[ids[name]] == fingerprint(mail.subject, mail.body), name
    assert prints[ids["short"]] is None and prints[ids["a1_copy"]] is None
    assert await groups(url, ids) == GROUPED
    # one group of three mails and the duplicate; collapsed, one of the four shows
    assert await figures(url) == (1, 3, 3)


async def test_a_second_run_changes_nothing(url: str) -> None:
    ids = await insert(url, ARCHIVE)
    await run(url)
    before = await rows(url, "SELECT mail_id, xmin::text AS version, group_id FROM mail_near")
    waiting, stored, _ = await run(url)
    assert (waiting, stored) == (0, 0)
    after = await rows(url, "SELECT mail_id, xmin::text AS version, group_id FROM mail_near")
    assert sorted(after) == sorted(before)  # no row written again
    assert await groups(url, ids) == GROUPED


async def test_new_mails_an_older_version_and_a_deleted_mail(url: str) -> None:
    ids = await insert(url, ARCHIVE)
    await run(url)
    later = {"alone_again": M(OTHER.replace("Hallo,", "Moin,"), 10, subject="Re: Lieferung")}
    ids = await insert(url, later, ids)
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        await session.execute(
            text("UPDATE mail_near SET version = 0, fingerprint = NULL WHERE mail_id = :id"),
            {"id": ids["a3"]},
        )
    waiting, stored, _ = await run(url)
    assert (waiting, stored) == (2, 2)  # the new mail and the one of an older version
    assert await groups(url, ids) == GROUPED | {"alone": "alone", "alone_again": "alone"}
    assert await figures(url) == (2, 5, 4)

    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        await session.execute(text("DELETE FROM mail WHERE id = :id"), {"id": ids["alone"]})
    del ids["alone"]
    waiting, stored, _ = await run(url)
    assert (waiting, stored) == (0, 0)
    assert (await groups(url, ids))["alone_again"] is None  # alone again; its row stays
    assert await figures(url) == (1, 3, 3)


async def test_a_stop_ends_the_fingerprints_between_two_batches(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await insert(url, ARCHIVE)
    monkeypatch.setattr(phase, "BATCH", 3)
    stop = asyncio.Event()

    class Stopping(Step):
        def advance(self, count: int = 1) -> None:
            super().advance(count)
            stop.set()

    async with sessions(url) as sessionmaker:
        stored = await phase.fingerprint_mails(sessionmaker, stop, Stopping("mails", 8))
    assert stored == 3
    assert [row.mail_id for row in await rows(url, "SELECT mail_id FROM mail_near")] == sorted(
        ids.values()
    )[:3]
    waiting, stored, _ = await run(url)  # the next import goes on
    assert (waiting, stored) == (5, 5)
    assert await groups(url, ids) == GROUPED

"""The steps paragraphs and blocks (D224, D225) on a small hand-made archive: the split, the
detection with its threshold and its rule per sender, the team's choices both ways, the ranges
and weights applied to mail, the entity scans taken back, a second run, a stop, a mail the rule
fails on and an older version."""

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
from mailrobbe.blocks import phase
from mailrobbe.blocks.model import BlockFigures, paragraph_hash, paragraphs, read_figures
from mailrobbe.config import Settings
from mailrobbe.db.models import PARAGRAPH_VERSION
from mailrobbe.jobrun import Step
from tests.conftest import _temporary_database

pytestmark = pytest.mark.db

NOTICE = "Diese Nachricht ist vertraulich und nur für den Empfänger bestimmt."
CALL = "Bitte unterstützen Sie den Aufruf zur Spende für den Rat der Stadt."
SIGNATURE = "Carl Brandt\nStadtwerke Hallenau, Abteilung Netze"
LETTER = "Wir bitten um eine Spende für den Wochenrückblick des Vereins bis Mai."


@dataclass(frozen=True, slots=True)
class M:
    sender: str
    body: str
    day: int  # of March 2024
    duplicate_of: str | None = None  # name of the original


def own(name: str) -> str:
    return f"Kurze Nachricht {name} zum Stand der Dinge, bitte bis Freitag ansehen."


# Anna ends three mails with the notice, Ben quotes it once; three people end a mail with the
# same call (one mail each, so no standard block); Carl signs two mails and a copy of one; four
# mails open with the same letter, which is never the tail.
ARCHIVE = {
    **{
        f"a{n}": M("anna@nordlicht.example", f"Hallo,\n\n{own(f'a{n}')}\n\n{NOTICE}\n", n)
        for n in (1, 2, 3)
    },
    "r1": M(
        "ben@elbtal.example",
        f"Danke, das passt so.\n\nAm 1.3.2024 schrieb Anna:\n> {own('a1')}\n>\n> {NOTICE}\n",
        4,
    ),
    **{
        f"b{n}": M(f"b{n}@verein.example", f"Hallo,\n\n{own(f'b{n}')}\n\n{CALL}\n", 4 + n)
        for n in (1, 2, 3)
    },
    "c1": M("carl@stadtwerke.example", f"{own('c1')}\n\n-- \n{SIGNATURE}\n", 8),
    "c2": M("carl@stadtwerke.example", f"{own('c2')}\n\n{SIGNATURE}\n", 9),
    "c1_copy": M("carl@stadtwerke.example", f"{own('c1')}\n\n-- \n{SIGNATURE}\n", 8, "c1"),
    **{
        f"d{n}": M(f"d{n}@verein.example", f"{LETTER}\n\n{own(f'd{n}')}\n", 10 + n)
        for n in (1, 2, 3, 4)
    },
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


async def execute(url: str, *statements: str, **parameters: object) -> None:
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        for statement in statements:
            await session.execute(text(statement), parameters)


async def insert(url: str, mails: dict[str, M]) -> dict[str, int]:
    """The mails into one file, each with its sender and a scan of the entities phase; their
    ids by name."""
    ids: dict[str, int] = {}
    persons: dict[str, int] = {}
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        file_id = await session.scalar(
            text("INSERT INTO mbox_file (path, size_bytes) VALUES ('a.mbox', 0) RETURNING id")
        )
        for index, (name, mail) in enumerate(mails.items()):
            if mail.sender not in persons:
                persons[mail.sender] = await session.scalar(
                    text(
                        "INSERT INTO person (canonical_email, domain) VALUES (:email, :domain) "
                        "RETURNING id"
                    ),
                    {"email": mail.sender, "domain": mail.sender.partition("@")[2]},
                )
            ids[name] = await session.scalar(
                text("""
                    INSERT INTO mail (mbox_file_id, byte_offset, byte_length, raw_sha256,
                        subject, body_text, date_utc, is_duplicate_of)
                    VALUES (:file, :offset, 100, :sha, 'Spende', :body, :date, :original)
                    RETURNING id
                """),
                {
                    "file": file_id,
                    "offset": index * 100,
                    "sha": name,
                    "body": mail.body,
                    "date": datetime(2024, 3, mail.day, 12, tzinfo=UTC),
                    "original": None if mail.duplicate_of is None else ids[mail.duplicate_of],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO participation (mail_id, person_id, role) VALUES (:m, :p, 'from')"
                ),
                {"m": ids[name], "p": persons[mail.sender]},
            )
            await session.execute(
                text("INSERT INTO mail_entity_scan (mail_id, version) VALUES (:m, 1)"),
                {"m": ids[name]},
            )
    return ids


@pytest.fixture(scope="module")
def blocks_template_url(database_server_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        yield url


@pytest.fixture
def url(database_server_url: str, blocks_template_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url, make_url(blocks_template_url).database) as copy:
        yield copy


async def run(
    url: str, min_mails: int = 3, stop: asyncio.Event | None = None
) -> tuple[int, int, int]:
    """Both steps as the import runs them (importer.cli._find_blocks): (waiting, split,
    changed)."""
    stop = stop or asyncio.Event()
    settings = Settings(database_url=url, block_min_mails=min_mails)
    async with sessions(url) as sessionmaker:
        async with sessionmaker() as session:
            waiting = await phase.waiting(session)
        split = await phase.split_mails(sessionmaker, stop, Step("mails", waiting))
        changed = await phase.find_blocks(sessionmaker, settings, stop, Step())
    return waiting, split, changed


async def blocks(url: str) -> dict[int, tuple[bool, bool, int, int]]:
    """paragraph_block by hash: (standard, detected, mails, senders)."""
    found = await rows(url, "SELECT hash, standard, detected, mails, senders FROM paragraph_block")
    return {row.hash: (row.standard, row.detected, row.mails, row.senders) for row in found}


async def ranges(url: str, ids: dict[str, int]) -> dict[str, tuple[str | None, str | None]]:
    """mail.history and mail.blocks by name, as text."""
    names = {mail_id: name for name, mail_id in ids.items()}
    found = await rows(url, "SELECT id, history::text, blocks::text FROM mail")
    return {names[row.id]: (row.history, row.blocks) for row in found}


async def figures(url: str) -> BlockFigures | None:
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        return await read_figures(session)


async def rescanned(url: str, ids: dict[str, int]) -> set[str]:
    """The mails without a mail_entity_scan row: the next entities phase scans them."""
    names = {mail_id: name for name, mail_id in ids.items()}
    kept = {row.mail_id for row in await rows(url, "SELECT mail_id FROM mail_entity_scan")}
    return {name for mail_id, name in names.items() if mail_id not in kept}


def span(body: str, part: str) -> str:
    start = body.index(part)
    return f"{{[{start},{start + len(part)})}}"


def hashed(paragraph: str) -> int:
    value = paragraph_hash(paragraph)
    assert value is not None
    return value


async def test_an_archive_imported_before_is_split_and_gets_its_blocks(url: str) -> None:
    ids = await insert(url, ARCHIVE)
    assert await figures(url) is None
    waiting, split, changed = await run(url)
    assert (waiting, split) == (len(ARCHIVE), len(ARCHIVE))  # the duplicate too
    scans = await rows(url, "SELECT mail_id, version FROM mail_paragraph_scan ORDER BY mail_id")
    assert [(row.mail_id, row.version) for row in scans] == [
        (mail_id, PARAGRAPH_VERSION) for mail_id in sorted(ids.values())
    ]
    stored = await rows(
        url,
        "SELECT position, hash, lower(span) AS start, upper(span) AS end, quoted, tail "
        "FROM mail_paragraph WHERE mail_id = :id ORDER BY position",
        id=ids["r1"],
    )
    body = ARCHIVE["r1"].body
    assert [(row.position, body[row.start : row.end], row.quoted, row.tail) for row in stored] == [
        (0, f"Am 1.3.2024 schrieb Anna:\n> {own('a1')}", True, False),
        (1, f"> {NOTICE}", True, False),
    ]
    assert stored[1].hash == hashed(NOTICE)

    # Only Anna's notice: the call has three senders for three mails, Carl's signature two
    # mails besides the copy, the letter never stands in the tail.
    assert await blocks(url) == {hashed(NOTICE): (True, True, 4, 2)}
    block = (await rows(url, "SELECT * FROM paragraph_block"))[0]
    assert block.sample == NOTICE  # unquoted, as written
    assert (block.first_date.day, block.last_date.day) == (1, 4)

    applied = await ranges(url, ids)
    assert applied["a1"] == (None, span(ARCHIVE["a1"].body, NOTICE))
    quote = body.index("Am 1.3.2024")
    assert applied["r1"] == (f"{{[{quote},{len(body)})}}", span(body, f"> {NOTICE}"))
    assert all(applied[name] == (None, None) for name in ("b1", "c1", "c1_copy", "d1"))
    assert changed == 4
    assert await rescanned(url, ids) == {"a1", "a2", "a3", "r1"}

    # weighed by the trigger (D226): A the subject, B the own words, C the quote without the
    # notice, D (shown without a letter) the notice
    tsv = (await rows(url, "SELECT tsv::text FROM mail WHERE id = :id", id=ids["r1"]))[0].tsv
    assert tsv == (
        "'1.3.2024':6C 'a1':11C 'anna':8C 'anseh':19C 'bestimmt':29 'bitt':16C 'dank':2B "
        "'ding':15C 'empfang':28 'freitag':18C 'kurz':9C 'nachricht':10C,21 'passt':4B "
        "'schrieb':7C 'spend':1A 'stand':13C 'vertraulich':23"
    )

    computed = await figures(url)
    assert computed is not None
    assert (
        computed.blocks,
        computed.detected,
        computed.marked,
        computed.dismissed,
        computed.mails,
    ) == (
        1,
        1,
        0,
        0,
        4,
    )


async def test_the_threshold_counts_mails_that_are_no_duplicates(url: str) -> None:
    ids = await insert(url, ARCHIVE)
    await run(url, min_mails=2)
    found = await blocks(url)
    assert found[hashed(SIGNATURE)] == (True, True, 2, 1)  # without the copy
    assert hashed(CALL) not in found  # three senders for three mails
    assert hashed(LETTER) not in found
    # the copy holds the signature as its original does
    applied = await ranges(url, ids)
    assert applied["c1_copy"] == applied["c1"] == (None, span(ARCHIVE["c1"].body, SIGNATURE))
    await run(url, min_mails=4)
    assert await blocks(url) == {}  # Ben's quote counts in the figures, not for detection
    assert (await ranges(url, ids))["c1"] == (None, None)


async def test_the_team_marks_and_takes_back_paragraphs(url: str) -> None:
    ids = await insert(url, ARCHIVE)
    await run(url)
    gone = "Ein Rechtshinweis, den keine Mail des Archivs mehr enthält."
    await execute(
        url,
        "INSERT INTO paragraph_override (hash, standard, sample) VALUES "
        "(:notice, false, :notice_text), (:letter, true, :letter_text), (:gone, true, :gone_text)",
        notice=hashed(NOTICE),
        notice_text=NOTICE,
        letter=hashed(LETTER),
        letter_text=LETTER,
        gone=hashed(gone),
        gone_text=gone,
    )
    await execute(url, "INSERT INTO mail_entity_scan SELECT id, 1 FROM mail ON CONFLICT DO NOTHING")
    _, split, changed = await run(url)
    assert split == 0
    assert await blocks(url) == {
        hashed(NOTICE): (False, True, 4, 2),  # detected and taken back
        hashed(LETTER): (True, False, 4, 4),  # in the middle of mails: by hand only
        hashed(gone): (True, False, 0, 0),
    }
    samples = await rows(url, "SELECT hash, sample FROM paragraph_block")
    assert {row.hash: row.sample for row in samples}[hashed(gone)] == gone
    applied = await ranges(url, ids)
    assert applied["a1"] == (None, None)
    assert applied["d1"] == (None, span(ARCHIVE["d1"].body, LETTER))
    assert changed == 8  # four lost the notice, four got the letter
    assert await rescanned(url, ids) == {"a1", "a2", "a3", "r1", "d1", "d2", "d3", "d4"}
    stored = await figures(url)
    assert stored is not None
    assert (stored.blocks, stored.detected, stored.marked, stored.dismissed, stored.mails) == (
        2,
        0,
        2,
        1,
        4,
    )


async def test_a_second_run_changes_nothing(url: str) -> None:
    ids = await insert(url, ARCHIVE)
    await run(url)
    before = await rows(url, "SELECT id, xmin::text AS version FROM mail")
    scans = await rows(url, "SELECT mail_id FROM mail_entity_scan")
    waiting, split, changed = await run(url)
    assert (waiting, split, changed) == (0, 0, 0)
    assert sorted(await rows(url, "SELECT id, xmin::text AS version FROM mail")) == sorted(before)
    assert sorted(await rows(url, "SELECT mail_id FROM mail_entity_scan")) == sorted(scans)
    assert await blocks(url) == {hashed(NOTICE): (True, True, 4, 2)}
    assert len(await ranges(url, ids)) == len(ARCHIVE)


async def test_a_stop_ends_both_steps_between_two_batches(
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
        assert await phase.split_mails(sessionmaker, stop, Stopping("mails", len(ARCHIVE))) == 3
    first = sorted(ids.values())[:3]
    assert [row.mail_id for row in await rows(url, "SELECT mail_id FROM mail_paragraph_scan")] == (
        first
    )
    waiting, split, _ = await run(url)  # the next import goes on
    assert (waiting, split) == (len(ARCHIVE) - 3, len(ARCHIVE) - 3)

    await execute(url, "UPDATE mail SET history = NULL, blocks = NULL")
    stop.clear()
    settings = Settings(database_url=url, block_min_mails=3)
    async with sessions(url) as sessionmaker:
        step = Stopping()
        assert await phase.find_blocks(sessionmaker, settings, stop, step) == 3  # a1 to a3
    assert (step.done, step.unit, step.total) == (3, "mails", len(ARCHIVE))
    assert (await ranges(url, ids))["r1"] == (None, None)  # in the next batch
    computed = await figures(url)
    _, _, changed = await run(url)
    assert changed == 1  # r1
    assert (await ranges(url, ids))["r1"][1] is not None
    later = await figures(url)
    assert later is not None and (computed is None or later.computed_at > computed.computed_at)


async def test_a_text_the_rule_fails_on_gets_a_scan_without_paragraphs(
    url: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ids = await insert(url, ARCHIVE)
    real = paragraphs

    def failing(text: str, segments: Any = None) -> Any:
        if "a2" in text:
            raise ValueError("a text the rule cannot take")
        return real(text, segments)

    monkeypatch.setattr(phase, "paragraphs", failing)
    waiting, split, _ = await run(url, min_mails=2)
    assert (waiting, split) == (len(ARCHIVE), len(ARCHIVE))
    held = await rows(
        url, "SELECT count(*) AS n FROM mail_paragraph WHERE mail_id = :id", id=ids["a2"]
    )
    assert held[0].n == 0
    assert f"mail {ids['a2']}: ValueError: a text the rule cannot take" in caplog.text
    assert (await blocks(url))[hashed(NOTICE)] == (True, True, 3, 2)  # a1, a3 and Ben's quote


async def test_mails_of_an_older_version_and_new_mails_are_split_again(url: str) -> None:
    ids = await insert(url, ARCHIVE)
    await run(url)
    await execute(
        url,
        "UPDATE mail_paragraph_scan SET version = 0 WHERE mail_id = :id",
        "DELETE FROM mail_paragraph WHERE mail_id = :id",
        id=ids["a3"],
    )
    assert (await ranges(url, ids))["a3"][1] is not None
    waiting, split, changed = await run(url)
    assert (waiting, split, changed) == (1, 1, 0)  # split again, the same ranges
    assert (
        len(await rows(url, "SELECT 1 FROM mail_paragraph WHERE mail_id = :id", id=ids["a3"])) == 2
    )

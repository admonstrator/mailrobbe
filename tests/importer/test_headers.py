"""The headers phase (D52): list_id and automated of older imports read again from the files."""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mailrobbe import migrate
from mailrobbe.config import Settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.importer import headers
from mailrobbe.importer.cli import run_import
from mailrobbe.importer.parse import parse_record
from mailrobbe.importer.split import MboxRecord
from mailrobbe.jobrun import Step
from mailrobbe.jobs import ImportProgress
from tests.importer.doubles import PIPELINE, message, write_mbox

pytestmark = pytest.mark.db

PAD = b"X-Pad: " + b"x" * 600 + b"\n"  # pushes the header block beyond a small HEAD_SIZE
EXTRA_HEADERS = [
    b"",
    b"List-Id: Team list <Team.Lists.Example>\n",
    b"Auto-Submitted: auto-generated\n",
    b"Precedence: bulk\n",
    b"Precedence: list\nList-Id: <news.example>\n",
    PAD + b"List-Id: <late.example>\nAuto-Submitted: auto-replied\n",
    b"Auto-Submitted: no\n",
]


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    migrate.upgrade("head", empty_database_url)
    return empty_database_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture(autouse=True)
def small_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Heads of 256 bytes, read 1 KiB at a time, 3 mails a page: every path is taken."""
    monkeypatch.setattr(headers, "HEAD_SIZE", 256)
    monkeypatch.setattr(headers, "READ_SPAN", 1024)
    monkeypatch.setattr(headers, "PAGE", 3)


def _messages() -> list[bytes]:
    return [message(index, extra_headers=extra) for index, extra in enumerate(EXTRA_HEADERS)]


def _expected(records: Sequence[MboxRecord]) -> list[tuple[str | None, bool]]:
    """What an import stores: parse_record on the whole message."""
    mails = [parse_record(record, attachment_hash_limit=0) for record in records]
    return [(mail.list_id, mail.automated) for mail in mails]


async def _older_file(
    sessionmaker: async_sessionmaker[AsyncSession], path: str, records: Sequence[MboxRecord]
) -> int:
    """An mbox_file row of an import before D52: its mails without list_id and automated."""
    async with sessionmaker() as session, session.begin():
        file_id = await session.scalar(
            text(
                "INSERT INTO mbox_file (path, size_bytes, header_version) "
                "VALUES (:path, :size, 0) RETURNING id"
            ),
            {"path": path, "size": sum(record.byte_length for record in records)},
        )
        for record in records:
            await session.execute(
                text(
                    "INSERT INTO mail (mbox_file_id, byte_offset, byte_length, raw_sha256) "
                    "VALUES (:id, :offset, :length, :sha)"
                ),
                {
                    "id": file_id,
                    "offset": record.byte_offset,
                    "length": record.byte_length,
                    "sha": record.raw_sha256,
                },
            )
    assert file_id is not None
    return int(file_id)


async def _query(
    sessionmaker: async_sessionmaker[AsyncSession], sql: str, **params: Any
) -> list[tuple[Any, ...]]:
    async with sessionmaker() as session:
        return [tuple(row) for row in await session.execute(text(sql), params)]


async def _execute(sessionmaker: async_sessionmaker[AsyncSession], sql: str) -> None:
    async with sessionmaker() as session, session.begin():
        await session.execute(text(sql))


async def _fields(
    sessionmaker: async_sessionmaker[AsyncSession], file_id: int
) -> list[tuple[str | None, bool]]:
    rows = await _query(
        sessionmaker,
        "SELECT list_id, automated FROM mail WHERE mbox_file_id = :id ORDER BY byte_offset",
        id=file_id,
    )
    return [(list_id, automated) for list_id, automated in rows]


async def _version(sessionmaker: async_sessionmaker[AsyncSession], file_id: int) -> int:
    [(version,)] = await _query(
        sessionmaker, "SELECT header_version FROM mbox_file WHERE id = :id", id=file_id
    )
    return int(version)


async def _refresh(
    sessionmaker: async_sessionmaker[AsyncSession],
    mbox_dir: Path,
    stop: asyncio.Event | None = None,
) -> Step:
    step = Step("mails")
    async with sessionmaker() as session:
        files = await headers.outdated_files(session)
    await headers.refresh_headers(sessionmaker, mbox_dir, files, stop or asyncio.Event(), step)
    return step


async def test_older_files_get_the_header_fields_an_import_stores(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    records = write_mbox(tmp_path / "a.mbox", _messages())
    file_id = await _older_file(sessionmaker, "a.mbox", records)
    async with sessionmaker() as session:
        assert await headers.outdated_files(session) == [
            headers.OutdatedFile(file_id, "a.mbox", len(records))
        ]

    step = await _refresh(sessionmaker, tmp_path)
    assert (
        await _fields(sessionmaker, file_id)
        == _expected(records)
        == [
            (None, False),
            ("team.lists.example", False),
            (None, True),
            (None, True),
            ("news.example", False),  # Precedence list: a person posting to a list
            ("late.example", True),  # found by reading further than HEAD_SIZE
            (None, False),
        ]
    )
    assert await _version(sessionmaker, file_id) == 1
    assert step.done == len(records)
    async with sessionmaker() as session:
        assert await headers.outdated_files(session) == []
    assert "headers of a.mbox read again: 7 mails, 5 changed in " in caplog.text


async def test_rows_whose_fields_are_right_are_not_written(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    records = write_mbox(tmp_path / "a.mbox", _messages())
    file_id = await _older_file(sessionmaker, "a.mbox", records)
    await _refresh(sessionmaker, tmp_path)
    await _execute(sessionmaker, "UPDATE mbox_file SET header_version = 0")
    # one row wrong again
    await _execute(
        sessionmaker, "UPDATE mail SET list_id = NULL WHERE list_id = 'team.lists.example'"
    )
    sql = "SELECT byte_offset, xmin::text FROM mail WHERE mbox_file_id = :id ORDER BY 1"
    before = dict(await _query(sessionmaker, sql, id=file_id))

    await _refresh(sessionmaker, tmp_path)
    after = dict(await _query(sessionmaker, sql, id=file_id))
    written = [offset for offset in before if before[offset] != after[offset]]
    assert written == [records[1].byte_offset]
    assert await _fields(sessionmaker, file_id) == _expected(records)
    assert await _version(sessionmaker, file_id) == 1


async def test_a_stop_between_pages_leaves_the_version(
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = write_mbox(tmp_path / "a.mbox", _messages())
    file_id = await _older_file(sessionmaker, "a.mbox", records)
    stop = asyncio.Event()
    read_page = headers._read_page

    def read_and_stop(*args: Any) -> Any:  # the dashboard's request, while the first page is read
        stop.set()
        return read_page(*args)

    monkeypatch.setattr(headers, "_read_page", read_and_stop)
    step = await _refresh(sessionmaker, tmp_path, stop)
    assert step.done == headers.PAGE
    expected = _expected(records)
    assert await _fields(sessionmaker, file_id) == [*expected[:3], *[(None, False)] * 4]
    assert await _version(sessionmaker, file_id) == 0

    monkeypatch.setattr(headers, "_read_page", read_page)
    await _refresh(sessionmaker, tmp_path)  # the next import starts the file again
    assert await _fields(sessionmaker, file_id) == expected
    assert await _version(sessionmaker, file_id) == 1


async def test_files_that_vanished_or_changed_keep_their_version(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    records = write_mbox(tmp_path / "gone.mbox", _messages())
    gone = await _older_file(sessionmaker, "gone.mbox", records)
    (tmp_path / "gone.mbox").unlink()
    records = write_mbox(tmp_path / "moved.mbox", _messages())
    moved = await _older_file(sessionmaker, "moved.mbox", records)
    data = (tmp_path / "moved.mbox").read_bytes()  # a byte more in front of the fifth mail
    offset = records[4].byte_offset
    (tmp_path / "moved.mbox").write_bytes(data[:offset] + b"\n" + data[offset:])
    records = write_mbox(tmp_path / "short.mbox", _messages())
    short = await _older_file(sessionmaker, "short.mbox", records)
    with (tmp_path / "short.mbox").open("r+b") as handle:
        handle.truncate(records[-1].byte_offset + 10)
    empty = await _older_file(sessionmaker, "empty.mbox", [])  # no mails, no file

    await _refresh(sessionmaker, tmp_path)
    assert "headers of gone.mbox not read again: No such file or directory" in caplog.text
    assert (
        "headers of moved.mbox: 3 of 7 mails are no longer at their offsets (the first at byte "
        f"{offset}); its mails keep their header fields until the next import"
    ) in caplog.text
    assert "headers of short.mbox: 1 of 7 mails are no longer at their offsets" in caplog.text
    versions = {
        file_id: await _version(sessionmaker, file_id) for file_id in (gone, moved, short, empty)
    }
    assert versions == {gone: 0, moved: 0, short: 0, empty: 1}
    expected = _expected(records)
    assert await _fields(sessionmaker, gone) == [(None, False)] * 7  # left as they are
    assert await _fields(sessionmaker, moved) == [*expected[:4], *[(None, False)] * 3]
    assert await _fields(sessionmaker, short) == [*expected[:6], (None, False)]


async def test_an_import_reads_the_headers_of_older_files_first(
    database_url: str, sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    mbox_dir = tmp_path / "mbox"
    mbox_dir.mkdir()
    automated = b"Auto-Submitted: auto-generated\n"
    write_mbox(mbox_dir / "a.mbox", _messages())
    write_mbox(
        mbox_dir / "b.mbox",
        [message(10 + i, sender="news@b.example", extra_headers=automated) for i in range(3)],
    )
    settings = Settings(database_url=database_url)
    # The test pipeline parses no list headers, like the importer before D39.
    assert await run_import(settings, mbox_dir, 2, pipeline=PIPELINE) == 0
    kinds = "SELECT kind::text FROM person WHERE canonical_email = 'news@b.example'"
    assert await _query(sessionmaker, kinds) == [(None,)]
    await _execute(sessionmaker, "UPDATE mbox_file SET header_version = 0")

    assert await run_import(settings, mbox_dir, 2, pipeline=PIPELINE) == 0
    rows = await _query(
        sessionmaker, "SELECT count(list_id), count(*) FILTER (WHERE automated) FROM mail"
    )
    assert rows == [(3, 6)]
    assert await _query(sessionmaker, "SELECT DISTINCT header_version FROM mbox_file") == [(1,)]
    assert await _query(sessionmaker, kinds) == [("automated",)]  # the finalize after it
    [(progress,)] = await _query(sessionmaker, "SELECT progress FROM job ORDER BY id DESC LIMIT 1")
    figures = ImportProgress.model_validate(progress)
    [step] = [step for step in figures.steps if step.key == "headers"]
    assert (step.status, step.total, step.done, figures.files_queued) == ("done", 10, 10, 0)

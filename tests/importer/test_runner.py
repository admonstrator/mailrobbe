"""The worker pool with real worker processes and the test doubles for reading and parsing.

Every test gets a fresh migrated database: worker processes need committed data. The shared
generator archive is copied first and asserted against its manifest.
"""

import asyncio
import multiprocessing
import os
import signal
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mailrobbe import migrate
from mailrobbe.config import Settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.enums import ImportErrorKind, MboxStatus
from mailrobbe.importer.model import Issue
from mailrobbe.importer.runner import FileOutcome, Pipeline, _Worker, run_files
from mailrobbe.importer.scan import ScanReport, scan
from tests.conftest import GeneratedArchive
from tests.importer.doubles import (
    PARSE_ERROR_HEADER,
    PIPELINE,
    READ_ERROR_HEADER,
    SLOW_PIPELINE,
    copy_archive,
    make_record,
    message,
    start_import,
    wait_until,
    write_mbox,
)

pytestmark = [pytest.mark.db, pytest.mark.slow]


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    migrate.upgrade("head", empty_database_url)
    return empty_database_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url)
    yield engine
    await engine.dispose()


async def _import(
    engine: AsyncEngine,
    mbox_dir: Path,
    *,
    workers: int = 2,
    pipeline: Pipeline = PIPELINE,
    stop: asyncio.Event | None = None,
) -> tuple[ScanReport, list[FileOutcome]]:
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        report = await scan(session, mbox_dir)
    settings = Settings(database_url=engine.url.render_as_string(hide_password=False))
    outcomes = await run_files(
        sessionmaker,
        settings,
        mbox_dir,
        report.files,
        workers,
        stop or asyncio.Event(),
        pipeline=pipeline,
    )
    return report, outcomes


async def _query(engine: AsyncEngine, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async with engine.connect() as connection:
        return [tuple(row) for row in await connection.execute(text(sql), params)]


async def _stored_records(engine: AsyncEngine) -> Counter[tuple[str, int, int, str]]:
    rows = await _query(
        engine,
        "SELECT f.path, m.byte_offset, m.byte_length, m.raw_sha256 FROM mail m "
        "JOIN mbox_file f ON f.id = m.mbox_file_id",
    )
    return Counter(
        (str(path), int(offset), int(length), str(sha)) for path, offset, length, sha in rows
    )


def _manifest_records(archive: GeneratedArchive) -> Counter[tuple[str, int, int, str]]:
    return Counter(
        (record["file"], record["offset"], record["length"], record["sha256"])
        for record in archive.manifest
    )


async def test_files_are_imported_in_parallel(
    engine: AsyncEngine, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    mbox_dir = copy_archive(generated_archive.mbox_dir, tmp_path / "mbox")
    report, outcomes = await _import(engine, mbox_dir, workers=3, pipeline=SLOW_PIPELINE)

    assert len(report.files) == len(list(mbox_dir.glob("*.mbox"))) > 3
    assert {outcome.status for outcome in outcomes} == {MboxStatus.DONE}
    assert await _stored_records(engine) == _manifest_records(generated_archive)
    per_file = Counter(record["file"] for record in generated_archive.manifest)
    rows = await _query(
        engine,
        "SELECT path, status::text, size_bytes, bytes_done, mails_parsed, worker_id, "
        "started_at < finished_at FROM mbox_file",
    )
    for path, status, size, done, mails, worker_id, ordered in rows:
        assert (status, done, mails, worker_id, ordered) == (
            "done",
            (mbox_dir / path).stat().st_size,
            per_file[path],
            None,
            True,
        )
        assert size == done
    # the largest files went first and ran at the same time
    largest = sorted(report.files, key=lambda file: -file.size_bytes)[:3]
    spans = await _query(
        engine,
        "SELECT max(started_at) < min(finished_at) FROM mbox_file WHERE path = ANY(:paths)",
        paths=[file.path for file in largest],
    )
    assert spans == [(True,)]


async def test_an_interrupted_import_resumes_without_losing_or_repeating_mails(
    engine: AsyncEngine, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    mbox_dir = copy_archive(generated_archive.mbox_dir, tmp_path / "mbox")
    stop = asyncio.Event()
    run = asyncio.create_task(_import(engine, mbox_dir, pipeline=SLOW_PIPELINE, stop=stop))
    await wait_until(engine, "SELECT count(*) = 2 FROM mbox_file WHERE status = 'running'")
    await asyncio.sleep(0.3)
    stop.set()
    _, outcomes = await run

    assert {outcome.status for outcome in outcomes} == {MboxStatus.PAUSED}
    rows = await _query(
        engine,
        "SELECT f.status::text, f.bytes_done, f.size_bytes, f.mails_parsed, f.worker_id, "
        "count(m.id), COALESCE(max(m.byte_offset + m.byte_length), 0) "
        "FROM mbox_file f LEFT JOIN mail m ON m.mbox_file_id = f.id GROUP BY f.id",
    )
    statuses = Counter(row[0] for row in rows)
    assert statuses == {"paused": 2, "pending": len(rows) - 2}
    for status, done, size, mails, worker_id, stored, end in rows:
        assert (mails, done, worker_id) == (stored, end, None)  # progress matches the mails
        if status == "paused":
            assert 0 < done < size

    _, outcomes = await _import(engine, mbox_dir)
    assert {outcome.status for outcome in outcomes} == {MboxStatus.DONE}
    assert len(outcomes) == len(rows)
    assert await _stored_records(engine) == _manifest_records(generated_archive)


async def test_a_killed_import_resumes_without_losing_or_repeating_mails(
    engine: AsyncEngine, database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    mbox_dir = copy_archive(generated_archive.mbox_dir, tmp_path / "mbox")
    process = start_import(database_url, mbox_dir, "slow")
    try:
        await wait_until(
            engine, "SELECT count(*) > 0 FROM mbox_file WHERE status = 'done'", process
        )
        await wait_until(
            engine, "SELECT count(*) > 0 FROM mbox_file WHERE status = 'running'", process
        )
    finally:
        os.killpg(process.pid, signal.SIGKILL)  # main process and workers, at any moment
        process.wait()
    statuses = Counter(row[0] for row in await _query(engine, "SELECT status FROM mbox_file"))
    assert statuses["done"] > 0 and statuses["running"] > 0

    _, outcomes = await _import(engine, mbox_dir)
    assert {outcome.status for outcome in outcomes} == {MboxStatus.DONE}
    assert await _stored_records(engine) == _manifest_records(generated_archive)


async def test_an_unreadable_file_ends_in_error_while_the_others_finish(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    mbox_dir = tmp_path / "mbox"
    mbox_dir.mkdir()
    good = write_mbox(mbox_dir / "good.mbox", [message(index) for index in range(50)])
    broken = [
        message(index, extra_headers=READ_ERROR_HEADER + b"\n") if index == 7 else message(index)
        for index in range(20)
    ]
    read_error = write_mbox(mbox_dir / "broken.mbox", broken)
    unparsable = write_mbox(
        mbox_dir / "unparsable.mbox",
        [message(1), message(2, extra_headers=PARSE_ERROR_HEADER + b"\n")],
    )
    vanished = mbox_dir / "vanished.mbox"
    write_mbox(vanished, [message(1)])

    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        report = await scan(session, mbox_dir)
    vanished.unlink()  # between the scan and its worker
    settings = Settings(database_url=engine.url.render_as_string(hide_password=False))
    outcomes = await run_files(
        sessionmaker, settings, mbox_dir, report.files, 2, asyncio.Event(), pipeline=PIPELINE
    )

    statuses = {outcome.path: outcome.status for outcome in outcomes}
    assert statuses == {
        "good.mbox": MboxStatus.DONE,
        "broken.mbox": MboxStatus.ERROR,
        "unparsable.mbox": MboxStatus.DONE,
        "vanished.mbox": MboxStatus.ERROR,
    }
    rows = await _query(
        engine,
        "SELECT f.path, f.status::text, f.bytes_done, f.mails_parsed, f.error_count "
        "FROM mbox_file f ORDER BY 1",
    )
    offset = read_error[7].byte_offset
    assert rows == [
        ("broken.mbox", "error", offset, 7, 1),
        ("good.mbox", "done", good[-1].byte_offset + good[-1].byte_length, 50, 0),
        ("unparsable.mbox", "done", (mbox_dir / "unparsable.mbox").stat().st_size, 2, 1),
        ("vanished.mbox", "error", 0, 0, 1),
    ]
    errors = await _query(
        engine,
        "SELECT f.path, e.byte_offset, e.kind, e.message FROM import_error e "
        "JOIN mbox_file f ON f.id = e.mbox_file_id ORDER BY 1",
    )
    assert errors == [
        ("broken.mbox", offset, "io", "cannot read broken.mbox: Input/output error"),
        (
            "unparsable.mbox",
            unparsable[1].byte_offset,
            "parse",
            "parser failed: ValueError: double parser failure",
        ),
        ("vanished.mbox", 0, "io", "cannot read vanished.mbox: No such file or directory"),
    ]
    stored = await _query(
        engine,
        "SELECT message_id FROM mail m JOIN mbox_file f ON f.id = m.mbox_file_id "
        "WHERE f.path = 'unparsable.mbox' ORDER BY byte_offset",
    )
    assert stored == [("<1@a.example>",), (None,)]  # stored with what is known


class _RaisingChecker:
    def check(self, raw: bytes) -> Any:
        raise RuntimeError("no luck")

    def take_new_answers(self) -> list[Any]:
        return []


def test_a_failing_dkim_check_becomes_an_issue(tmp_path: Path) -> None:
    stop = multiprocessing.get_context("spawn").Event()
    worker = _Worker(Settings(), (), tmp_path, PIPELINE, 1, stop)
    worker.checker = _RaisingChecker()
    mail, verdict, issues = worker.examine(make_record(0, message(1)))
    assert mail.message_id == "<1@a.example>"
    assert verdict is None
    assert issues == [Issue(ImportErrorKind.DKIM, "DKIM check failed: RuntimeError: no luck")]
    _, verdict, issues = worker.examine(make_record(0, message(1), truncated=True))
    assert (verdict, issues) == (None, [])  # truncated records are not checked

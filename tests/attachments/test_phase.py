"""The attachments phase of an import (D72): each document waiting for its text is read once, in
file order, by spawned workers; results in batches; stop and resume; figures in the job row."""

import asyncio
import logging
import os
import signal
import time
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import ByteSize
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mailrobbe import jobrun, jobs, migrate
from mailrobbe.attachments import phase
from mailrobbe.config import Settings
from mailrobbe.db.models import EXTRACTOR_VERSION
from mailrobbe.enums import JobKind
from mailrobbe.importer.cli import run_import
from mailrobbe.jobs import ImportProgress
from tests.attachments.doubles import (
    CALLS_ENV,
    DIE,
    FAIL,
    FAST_ENV,
    HANG,
    HUGE,
    HUGE_LENGTH,
    PIDS_ENV,
    SCAN,
    SLOW,
    TIME,
    Attached,
    alive,
    attachment_mail,
    digest,
    fake_extract,
    recorded,
    start_import,
)
from tests.importer.doubles import wait_until, write_mbox

pytestmark = [pytest.mark.db, pytest.mark.slow]

NOTES = b"Spendenliste 2023\nIBAN DE89 3704 0044 0532 0130 00\nBetrag 1.500,00 EUR\n"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 200


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    migrate.upgrade("head", empty_database_url)
    return empty_database_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The file fake_extract records the content of each of its calls in."""
    path = tmp_path / "calls"
    monkeypatch.setenv(CALLS_ENV, str(path))
    return path


def _mbox(directory: Path, name: str, mails: Sequence[Sequence[Attached]], first: int = 0) -> Path:
    directory.mkdir(exist_ok=True)
    messages = [attachment_mail(first + index, files) for index, files in enumerate(mails)]
    write_mbox(directory / name, messages)
    return directory


async def _import(url: str, mbox_dir: Path, workers: int = 2, **settings: Any) -> int:
    return await run_import(
        Settings(database_url=url, **settings), mbox_dir, workers, extract=fake_extract
    )


async def _rows(engine: AsyncEngine, sql: str, **params: Any) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        return [dict(row._mapping) for row in await connection.execute(text(sql), params)]


async def _documents(engine: AsyncEngine) -> dict[str | None, dict[str, Any]]:
    """Documents by their file name used most."""
    rows = await _rows(
        engine,
        "SELECT id, name, kind::text, text_status::text AS status, extracted_text, "
        "text_truncated, text_error, pages, extractor_version, extracted_at, size_bytes, sha256 "
        "FROM document",
    )
    return {row["name"]: row for row in rows}


async def _jobs(engine: AsyncEngine) -> list[dict[str, Any]]:
    return await _rows(engine, "SELECT * FROM job ORDER BY id")


async def test_each_document_is_extracted_once_and_stored_as_the_extraction_gives_it(
    database_url: str,
    engine: AsyncEngine,
    tmp_path: Path,
    calls: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    notes: Attached = ("Spenden.txt", "text/plain", NOTES)
    mbox_dir = _mbox(
        tmp_path / "mbox",
        "a.mbox",
        [
            [notes, ("leer.txt", "text/plain", b"  \n"), ("Foto.jpg", "image/jpeg", JPEG)],
            [("Protokoll.pdf", "application/pdf", FAIL + b" rest")],
            [("Scan.pdf", "application/pdf", SCAN), ("Lang.pdf", "application/pdf", TIME)],
            [("Spendenliste_final.txt", "text/plain", NOTES)],  # the same content again
        ],
    )
    assert await _import(database_url, mbox_dir) == 0

    documents = await _documents(engine)
    assert set(documents) == {
        "Spenden.txt",
        "leer.txt",
        "Foto.jpg",
        "Protokoll.pdf",
        "Scan.pdf",
        "Lang.pdf",
    }
    shown = {
        name: (
            row["status"],
            row["extracted_text"],
            row["text_truncated"],
            row["text_error"],
            row["pages"],
            row["kind"],
        )
        for name, row in documents.items()
    }
    assert shown == {
        "Spenden.txt": ("text", NOTES.decode().strip(), False, None, None, "text"),
        "leer.txt": ("empty", None, False, None, None, "text"),
        "Foto.jpg": ("unsupported", None, False, None, None, "image"),  # by kind, finalize
        "Protokoll.pdf": ("failed", None, False, "damaged file", None, "pdf"),
        "Scan.pdf": ("scanned", None, False, None, 2, "pdf"),
        "Lang.pdf": ("timeout", "Seite eins", True, "stopped after 60 s", None, "pdf"),
    }
    versions = {name: row["extractor_version"] for name, row in documents.items()}
    assert versions == dict.fromkeys(documents, EXTRACTOR_VERSION) | {"Foto.jpg": 0}
    assert documents["Foto.jpg"]["extracted_at"] is None
    assert all(row["extracted_at"] for name, row in documents.items() if name != "Foto.jpg")
    # One read per content, none of the image finalize found unsupported.
    contents = [NOTES, b"  \n", FAIL + b" rest", SCAN, TIME]
    assert sorted(recorded(calls)) == sorted(digest(content) for content in contents)

    out = capsys.readouterr().out
    assert "documents:     6 (2 with text, 0 waiting; 5 stored in this run)" in out
    assert "extracting the text of 5 documents (0.0 MB) with 2 workers" in caplog.text
    assert "attachments done: 5 of 5 documents stored in " in caplog.text
    [job] = await _jobs(engine)
    assert (job["status"], job["phase"]) == ("done", "entities")  # after the attachments
    assert (
        "; 4 mails, 0 import errors; 2 of 6 documents with text, 0 waiting; files: "
        in (job["message"])
    )
    progress = ImportProgress.model_validate(job["progress"])
    [step] = [step for step in progress.steps if step.key == "attachments"]
    assert (step.status, step.unit, step.total, step.done) == ("done", "documents", 5, 5)
    assert progress.workers == 0

    # Nothing waits any more: the next import reads nothing and stays in finalize.
    assert await _import(database_url, mbox_dir) == 0
    assert len(recorded(calls)) == len(contents)
    assert (await _jobs(engine))[-1]["phase"] == "finalize"


async def test_documents_above_the_size_limit_are_read_once_the_limit_admits_them(
    database_url: str, engine: AsyncEngine, tmp_path: Path, calls: Path
) -> None:
    large = b"Kassenbuch " * 50
    mbox_dir = _mbox(
        tmp_path / "mbox",
        "a.mbox",
        [[("klein.txt", "text/plain", NOTES), ("gross.txt", "text/plain", large)]],
    )
    limit = ByteSize(len(NOTES) + 1)
    assert await _import(database_url, mbox_dir, attachment_text_max_size=limit) == 0
    documents = await _documents(engine)
    assert documents["gross.txt"]["status"] == "too_large"
    assert documents["gross.txt"]["extracted_text"] is None
    assert recorded(calls) == [digest(NOTES)]  # the large one was not read

    # The same limit: it stays as it is.
    assert await _import(database_url, mbox_dir, attachment_text_max_size=limit) == 0
    assert len(recorded(calls)) == 1
    assert await _import(database_url, mbox_dir, attachment_text_max_size=ByteSize(len(large))) == 0
    documents = await _documents(engine)
    assert (documents["gross.txt"]["status"], documents["gross.txt"]["extracted_text"]) == (
        "text",
        large.decode().strip(),
    )
    assert recorded(calls) == [digest(NOTES), digest(large)]


async def test_an_unreadable_source_is_tried_again_at_the_next_import(
    database_url: str,
    engine: AsyncEngine,
    tmp_path: Path,
    calls: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mbox_dir = tmp_path / "mbox"
    _mbox(mbox_dir, "a.mbox", [[("a.txt", "text/plain", b"Erste Notiz")]])
    _mbox(mbox_dir, "b.mbox", [[("b.txt", "text/plain", b"Zweite Notiz")]], first=1)
    _mbox(mbox_dir, "c.mbox", [[("c.txt", "text/plain", b"Dritte Notiz")]], first=2)
    assert await _import(database_url, mbox_dir) == 0
    # As after the first import of an archive imported before milestone 9: waiting documents.
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE document SET text_status = 'pending', extracted_text = NULL, "
                "extractor_version = 0, extracted_at = NULL"
            )
        )
        # c.mbox still holds its mail, but not as it was imported.
        await connection.execute(
            text(
                "UPDATE mail SET raw_sha256 = repeat('0', 64) FROM mbox_file f "
                "WHERE f.id = mail.mbox_file_id AND f.path = 'c.mbox'"
            )
        )
    (mbox_dir / "b.mbox").rename(tmp_path / "b.mbox")

    caplog.set_level(logging.WARNING, logger="mailrobbe")
    assert await _import(database_url, mbox_dir) == 0
    documents = await _documents(engine)
    assert documents["a.txt"]["status"] == "text"
    for name, why in (("b.txt", "FileNotFoundError"), ("c.txt", "AttachmentChanged")):
        assert documents[name]["status"] == "unreadable"
        assert documents[name]["text_error"].startswith(why)
    assert "attachments in b.mbox not read: 1 documents, the first in the mail at byte 0: " in (
        caplog.text
    )
    assert "they are tried again at the next import" in caplog.text

    (tmp_path / "b.mbox").rename(mbox_dir / "b.mbox")
    assert await _import(database_url, mbox_dir) == 0
    documents = await _documents(engine)
    assert (documents["b.txt"]["status"], documents["b.txt"]["extracted_text"]) == (
        "text",
        "Zweite Notiz",
    )
    assert documents["c.txt"]["status"] == "unreadable"  # still changed
    assert recorded(calls).count(digest(b"Zweite Notiz")) == 2  # first import, then again


async def test_a_new_extractor_version_extracts_again_and_an_unreadable_file_keeps_the_text(
    database_url: str,
    engine: AsyncEngine,
    tmp_path: Path,
    calls: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mbox_dir = tmp_path / "mbox"
    _mbox(
        mbox_dir,
        "a.mbox",
        [[("a.txt", "text/plain", NOTES), ("Foto.jpg", "image/jpeg", JPEG)]],
    )
    _mbox(mbox_dir, "b.mbox", [[("Protokoll.pdf", "application/pdf", FAIL)]], first=1)
    _mbox(mbox_dir, "c.mbox", [[("c.txt", "text/plain", b"Dritte Notiz")]], first=2)
    assert await _import(database_url, mbox_dir) == 0
    assert len(recorded(calls)) == 3
    (mbox_dir / "c.mbox").unlink()

    monkeypatch.setattr(phase, "EXTRACTOR_VERSION", EXTRACTOR_VERSION + 1)
    assert await _import(database_url, mbox_dir) == 0
    documents = await _documents(engine)
    version = {name: row["extractor_version"] for name, row in documents.items()}
    assert version == {
        "a.txt": EXTRACTOR_VERSION + 1,
        "Protokoll.pdf": EXTRACTOR_VERSION + 1,  # failed came from an extractor too
        "Foto.jpg": 0,  # unsupported by its kind: never read
        "c.txt": EXTRACTOR_VERSION,  # its file is gone: the older text stays, tried again
    }
    assert (documents["c.txt"]["status"], documents["c.txt"]["extracted_text"]) == (
        "text",
        "Dritte Notiz",
    )
    assert sorted(recorded(calls)) == sorted(
        digest(content) for content in (NOTES, FAIL, b"Dritte Notiz", NOTES, FAIL)
    )


async def test_a_text_whose_tsvector_is_too_long_is_halved_alone(
    database_url: str,
    engine: AsyncEngine,
    tmp_path: Path,
    calls: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    mbox_dir = _mbox(
        tmp_path / "mbox",
        "a.mbox",
        [[("riesig.txt", "text/plain", HUGE), ("a.txt", "text/plain", NOTES)]],
    )
    assert await _import(database_url, mbox_dir, 1) == 0  # one worker: one batch
    documents = await _documents(engine)
    assert documents["a.txt"]["extracted_text"] == NOTES.decode().strip()
    huge = documents["riesig.txt"]
    assert (huge["status"], huge["text_truncated"]) == ("text", True)
    assert len(huge["extracted_text"]) == HUGE_LENGTH // 2
    assert f"document {huge['id']}: the tsvector of its text is above PostgreSQL's limit" in (
        caplog.text
    )
    found = await _rows(
        engine,
        "SELECT name FROM document WHERE tsv @@ websearch_to_tsquery('german', :word)",
        word=huge["extracted_text"][:2],
    )
    assert found == [{"name": "riesig.txt"}]


async def test_a_worker_that_dies_fails_only_the_document_that_killed_it(
    database_url: str,
    engine: AsyncEngine,
    tmp_path: Path,
    calls: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    files = [(f"{index}.txt", "text/plain", f"Notiz {index}".encode()) for index in range(6)]
    files.insert(2, ("kaputt.pdf", "application/pdf", DIE))
    mbox_dir = _mbox(tmp_path / "mbox", "a.mbox", [[file] for file in files])
    assert await _import(database_url, mbox_dir, 2) == 0
    documents = await _documents(engine)
    statuses = {name: (row["status"], row["text_error"]) for name, row in documents.items()}
    assert statuses == {
        **{name: ("text", None) for name, _, _ in files if name != "kaputt.pdf"},
        "kaputt.pdf": ("failed", "the worker process died while extracting it"),
    }
    assert "a worker process died; " in caplog.text
    assert recorded(calls).count(digest(DIE)) == 2  # with the others, then alone


async def _wait_for_progress(engine: AsyncEngine, done: int) -> None:
    sql = (
        "SELECT count(*) = 1 FROM job, jsonb_array_elements(progress -> 'steps') AS step "
        f"WHERE step ->> 'key' = 'attachments' AND (step ->> 'done')::int >= {done}"
    )
    await wait_until(engine, sql)


def _pids(path: Path) -> list[int]:
    return [int(line.split()[1]) for line in recorded(path)]


def _slow_archive(directory: Path) -> Path:
    """One document that hangs in its worker, then 30 that take SLOW_SECONDS each."""
    mails: list[list[Attached]] = [[("haengt.pdf", "application/pdf", HANG)]]
    mails += [[(f"{n}.txt", "text/plain", SLOW + f" Notiz {n}".encode())] for n in range(30)]
    return _mbox(directory, "a.mbox", mails)


async def test_a_stop_request_ends_the_phase_within_seconds_and_the_next_import_continues(
    database_url: str,
    engine: AsyncEngine,
    tmp_path: Path,
    calls: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    monkeypatch.setattr(jobrun, "REPORT_SECONDS", 0.1)
    pids = tmp_path / "pids"
    monkeypatch.setenv(PIDS_ENV, str(pids))
    mbox_dir = _slow_archive(tmp_path / "mbox")
    run = asyncio.create_task(_import(database_url, mbox_dir, 3))
    try:
        await _wait_for_progress(engine, 4)
        [job] = await _jobs(engine)
        progress = ImportProgress.model_validate(job["progress"])
        [step] = [step for step in progress.steps if step.key == "attachments"]
        assert (step.status, step.total, progress.workers) == ("running", 31, 3)
        assert step.rate is not None and step.rate > 0
        async with engine.begin() as connection:  # what the dashboard's pause does
            assert await jobs.request_stop(connection, JobKind.IMPORT) is not None
        asked = time.monotonic()
        assert await asyncio.wait_for(run, 30) == 130
        assert time.monotonic() - asked < 5
    finally:
        run.cancel()
    assert "stop requested from the dashboard" in caplog.text
    assert "attachments stopped: " in caplog.text
    started = _pids(pids)
    assert started and not any(alive(pid) for pid in started), recorded(pids)
    assert any(line.startswith("child ") for line in recorded(pids))

    [job] = await _jobs(engine)
    assert (job["status"], job["phase"], job["stop_requested"]) == ("stopped", "attachments", True)
    progress = ImportProgress.model_validate(job["progress"])
    statuses = {
        row["status"]: row["count"]
        for row in await _rows(
            engine, "SELECT text_status::text AS status, count(*) FROM document GROUP BY 1"
        )
    }
    [step] = [step for step in progress.steps if step.key == "attachments"]
    assert step.status == "stopped"
    assert statuses["text"] == step.done >= 4  # what was stored stays
    assert statuses["pending"] == 31 - statuses["text"] > 0
    assert (
        f"{statuses['text']} of 31 documents with text, {statuses['pending']} waiting"
        in (job["message"])
    )
    stored = {
        row["sha256"]
        for row in await _rows(engine, "SELECT sha256 FROM document WHERE text_status = 'text'")
    }
    before = len(recorded(calls))

    monkeypatch.setenv(FAST_ENV, "1")
    assert await _import(database_url, mbox_dir, 3) == 0
    again = recorded(calls)[before:]
    assert not stored & set(again)  # nothing stored before is read again
    assert len(again) == statuses["pending"]
    documents = await _documents(engine)
    assert {row["status"] for row in documents.values()} == {"text"}


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
async def test_ctrl_c_and_sigterm_stop_the_phase_and_its_workers(
    database_url: str,
    engine: AsyncEngine,
    tmp_path: Path,
    calls: Path,
    monkeypatch: pytest.MonkeyPatch,
    signum: signal.Signals,
) -> None:
    pids = tmp_path / "pids"
    monkeypatch.setenv(PIDS_ENV, str(pids))
    mbox_dir = _slow_archive(tmp_path / "mbox")
    process = start_import(database_url, mbox_dir, 3)
    try:
        await _wait_for_progress(engine, 2)
        if signum is signal.SIGINT:  # as a terminal does: the whole process group
            os.killpg(process.pid, signum)
        else:
            os.kill(process.pid, signum)
        asked = time.monotonic()
        output = process.communicate(timeout=60)[0]
        assert process.returncode == 130, output
        assert time.monotonic() - asked < 5, output
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
    assert "attachments stopped: " in output
    assert "interrupted: run `mailrobbe import` again to continue" in output
    assert "Traceback" not in output
    started = _pids(pids)
    assert started and not any(alive(pid) for pid in started), recorded(pids)
    [job] = await _jobs(engine)
    assert (job["status"], job["phase"]) == ("stopped", "attachments")

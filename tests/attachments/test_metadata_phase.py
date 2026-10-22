"""The metadata of attachments in an import (D167): read with the text where the text is read,
the rest in the metadata step; a newer reader reads again; a file that cannot be read now leaves
the metadata as it was, tried again at the next import; a document PostgreSQL refuses fails
alone."""

import logging
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ByteSize
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mailrobbe import migrate
from mailrobbe.attachments import phase
from mailrobbe.attachments.metadata import METADATA_VERSION
from mailrobbe.attachments.metadata.model import Fields, Summary, summarize
from mailrobbe.config import Settings
from mailrobbe.importer.cli import run_import
from mailrobbe.jobs import ImportProgress
from tests.attachments.doubles import CALLS_ENV, Attached, attachment_mail, fake_extract
from tests.attachments.metadata import samples
from tests.importer.doubles import write_mbox

pytestmark = [pytest.mark.db, pytest.mark.slow]

PHOTO = samples.jpeg(samples.exif_segment(samples.camera_tiff()))
DOCX = samples.docx("<w:p/>", comments=["Anna Berg"])
PDF = samples.pdf("/Author (Carl Diehl) /Producer (Ghostscript 10.02)")


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    migrate.upgrade("head", empty_database_url)
    return empty_database_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "calls"
    monkeypatch.setenv(CALLS_ENV, str(path))
    return path


def _mbox(directory: Path, name: str, mails: Sequence[Sequence[Attached]], first: int = 0) -> None:
    directory.mkdir(exist_ok=True)
    messages = [attachment_mail(first + index, files) for index, files in enumerate(mails)]
    write_mbox(directory / name, messages)


async def _import(url: str, mbox_dir: Path, **settings: Any) -> int:
    return await run_import(
        Settings(database_url=url, **settings), mbox_dir, 2, extract=fake_extract
    )


async def _metadata(engine: AsyncEngine) -> dict[str, dict[str, Any]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT name, metadata_status::text AS status, metadata_version AS version, "
                "metadata_error AS error, metadata_fields AS fields, metadata_author AS author, "
                "metadata_modified_by AS modified_by, metadata_program AS program, "
                "metadata_device AS device, metadata_created AS created, metadata_gps AS gps, "
                "metadata_latitude AS latitude, metadata_longitude AS longitude, "
                "metadata_gps_time AS gps_time FROM document"
            )
        )
        return {row.name: dict(row._mapping) for row in rows}


async def _metadata_step(engine: AsyncEngine) -> tuple[str, int | None, int]:
    async with engine.connect() as connection:
        progress = (await connection.execute(text("SELECT progress FROM job ORDER BY id"))).all()
    steps = ImportProgress.model_validate(progress[-1][0]).steps
    [step] = [step for step in steps if step.key == "metadata"]
    return step.status, step.total, step.done


async def test_metadata_is_read_once_then_again_by_a_newer_reader(
    database_url: str,
    engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    mbox_dir = tmp_path / "mbox"
    _mbox(
        mbox_dir,
        "a.mbox",
        [[("Foto.jpg", "image/jpeg", PHOTO), ("Protokoll.docx", "application/octet-stream", DOCX)]],
    )
    _mbox(mbox_dir, "b.mbox", [[("Liste.pdf", "application/pdf", PDF)]], first=1)
    _mbox(mbox_dir, "c.mbox", [[("notiz.txt", "text/plain", b"Hallo")]], first=2)

    assert await _import(database_url, mbox_dir) == 0

    documents = await _metadata(engine)
    photo, docx, pdf, notes = (
        documents[name] for name in ("Foto.jpg", "Protokoll.docx", "Liste.pdf", "notiz.txt")
    )
    assert {name: row["version"] for name, row in documents.items()} == dict.fromkeys(
        documents, METADATA_VERSION
    )
    assert (photo["status"], photo["error"]) == ("found", None)
    assert photo["fields"]["gps"]["latitude"] == 52.5200833
    assert (photo["author"], photo["program"], photo["device"], photo["gps"]) == (
        "Peter Hofmann",
        "Firmware 1.8.1",
        "Canon EOS R6",
        True,
    )
    assert photo["created"] == datetime(2024, 5, 6, 8, 9, 10, tzinfo=UTC)
    assert (photo["latitude"], photo["longitude"]) == (52.5200833, 13.41)  # D241
    assert photo["gps_time"] == datetime(2024, 5, 6, 8, 9, 10, tzinfo=UTC)
    assert (pdf["latitude"], pdf["longitude"], pdf["gps_time"]) == (None, None, None)
    assert (docx["status"], docx["author"], docx["modified_by"], docx["program"]) == (
        "found",
        "Peter Hofmann",
        "Anna Berg",
        "Microsoft Office Word",
    )
    assert docx["fields"]["office"]["comments"] == 1
    assert (pdf["author"], pdf["program"], pdf["gps"]) == ("Carl Diehl", "Ghostscript 10.02", False)
    assert (notes["status"], notes["fields"], notes["author"]) == ("unsupported", None, None)
    # The text phase read the others with their text; only the image was left for the step.
    assert await _metadata_step(engine) == ("done", 1, 1)
    assert "metadata done: 1 of 1 documents stored in " in caplog.text
    assert ": found 1" in caplog.text

    # Nothing waits: the step is skipped.
    assert await _import(database_url, mbox_dir) == 0
    assert (await _metadata_step(engine))[0] == "skipped"

    # A newer reader reads every document again; the one in a missing file keeps what it had.
    monkeypatch.setattr(phase, "METADATA_VERSION", METADATA_VERSION + 1)
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE document SET metadata_author = 'alt', metadata_fields = '{}'")
        )
    (mbox_dir / "b.mbox").rename(tmp_path / "b.mbox")
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="mailrobbe")

    assert await _import(database_url, mbox_dir) == 0

    documents = await _metadata(engine)
    assert {name: (row["version"], row["author"]) for name, row in documents.items()} == {
        "Foto.jpg": (METADATA_VERSION + 1, "Peter Hofmann"),
        "Protokoll.docx": (METADATA_VERSION + 1, "Peter Hofmann"),
        "Liste.pdf": (METADATA_VERSION, "alt"),  # not read: tried again at the next import
        "notiz.txt": (METADATA_VERSION + 1, None),
    }
    assert documents["Foto.jpg"]["fields"] == photo["fields"]
    assert await _metadata_step(engine) == ("done", 4, 4)
    assert "metadata of attachments in b.mbox not read: 1 documents" in caplog.text

    (tmp_path / "b.mbox").rename(mbox_dir / "b.mbox")
    assert await _import(database_url, mbox_dir) == 0
    documents = await _metadata(engine)
    assert (documents["Liste.pdf"]["version"], documents["Liste.pdf"]["author"]) == (
        METADATA_VERSION + 1,
        "Carl Diehl",
    )
    assert await _metadata_step(engine) == ("done", 1, 1)


async def test_documents_above_the_size_limit_are_read_once_the_limit_admits_them(
    database_url: str, engine: AsyncEngine, tmp_path: Path
) -> None:
    mbox_dir = tmp_path / "mbox"
    _mbox(mbox_dir, "a.mbox", [[("Foto.jpg", "image/jpeg", PHOTO)]])

    assert await _import(database_url, mbox_dir, attachment_text_max_size=ByteSize(100)) == 0
    photo = (await _metadata(engine))["Foto.jpg"]
    assert (photo["status"], photo["fields"], photo["version"]) == (
        "too_large",
        None,
        METADATA_VERSION,
    )

    assert await _import(database_url, mbox_dir) == 0
    photo = (await _metadata(engine))["Foto.jpg"]
    assert (photo["status"], photo["author"]) == ("found", "Peter Hofmann")


async def test_a_date_beyond_utc_is_left_out_and_a_refused_document_fails_alone(
    database_url: str,
    engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Year 1 at +01:00 is year 0 in UTC: it broke the whole batch before.
    year_one = samples.pdf("/Author (Erika Alt) /CreationDate (D:00010101000000+01'00')")
    refused = samples.pdf("/Author (Bruno Bad)")
    mbox_dir = tmp_path / "mbox"
    _mbox(
        mbox_dir,
        "a.mbox",
        [
            [("Alt.pdf", "application/pdf", year_one), ("Foto.jpg", "image/jpeg", PHOTO)],
            [("Kaputt.pdf", "application/pdf", refused), ("Liste.pdf", "application/pdf", PDF)],
        ],
    )

    def summary(fields: Fields) -> Summary:  # a value PostgreSQL refuses, whatever comes next
        if fields.get("pdf", {}).get("author") == "Bruno Bad":
            return Summary(created=datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))))
        return summarize(fields)

    monkeypatch.setattr(phase, "summarize", summary)
    caplog.set_level(logging.WARNING, logger="mailrobbe")

    assert await _import(database_url, mbox_dir) == 0

    documents = await _metadata(engine)
    old = documents["Alt.pdf"]
    assert (old["status"], old["author"], old["created"]) == ("found", "Erika Alt", None)
    assert old["fields"]["pdf"]["creation_date"] == "0001-01-01T00:00:00+01:00"  # as found
    bad = documents["Kaputt.pdf"]
    assert (bad["status"], bad["fields"], bad["author"], bad["version"]) == (
        "failed",
        None,
        None,
        METADATA_VERSION,
    )
    assert bad["error"].startswith("cannot be stored: ")
    assert {name: row["status"] for name, row in documents.items()} == {
        "Alt.pdf": "found",
        "Foto.jpg": "found",
        "Kaputt.pdf": "failed",
        "Liste.pdf": "found",
    }
    assert documents["Liste.pdf"]["author"] == "Carl Diehl"
    assert await _metadata_step(engine) == ("done", 1, 1)
    assert "its metadata cannot be stored" in caplog.text

"""scan: which files are MBOX files, and what happens to known, grown, replaced and missing ones."""

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.enums import MboxStatus
from mailrobbe.importer.scan import HEAD_SIZE, find_mbox_files, scan
from tests.importer.doubles import fetch, message, write_mbox

pytestmark = pytest.mark.db


def _mbox(path: Path, mails: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_mbox(path, (message(index) for index in range(mails)))
    return path


async def _file_rows(session: AsyncSession) -> dict[str, tuple[object, ...]]:
    rows = await fetch(
        session,
        "SELECT path, status::text, size_bytes, bytes_done, mails_parsed, error_count "
        "FROM mbox_file",
    )
    return {str(row[0]): row[1:] for row in rows}


async def _progress(session: AsyncSession, path: str, status: MboxStatus, bytes_done: int) -> None:
    await session.execute(
        text(
            "UPDATE mbox_file SET status = CAST(:status AS mbox_status), bytes_done = :done, "
            "mails_parsed = 2, error_count = 1, worker_id = 3 WHERE path = :path"
        ),
        {"status": status, "done": bytes_done, "path": path},
    )
    await session.commit()


def test_mbox_files_are_found_by_content(tmp_path: Path) -> None:
    _mbox(tmp_path / "b.mbox")
    _mbox(tmp_path / "sub" / "deeper" / "archive.txt")  # any name
    _mbox(tmp_path / "a-no-extension")
    _mbox(tmp_path / ".hidden.mbox")
    _mbox(tmp_path / ".cache" / "x.mbox")
    _mbox(tmp_path / "_generator" / "x.mbox")
    _mbox(tmp_path / "sub" / "_generator" / "y.mbox")
    (tmp_path / "notes.txt").write_text("Fromage\nFrom a@b Mon Jan  1 00:00:00 2024\n")
    (tmp_path / "readme").write_text("Hello\nFrom a@b Mon Jan  1 00:00:00 2024\n")
    (tmp_path / "empty.mbox").write_bytes(b"")
    (tmp_path / "link.mbox").symlink_to(tmp_path / "b.mbox")
    found, unreadable = find_mbox_files(tmp_path)
    assert [file.path for file in found] == [
        "a-no-extension",
        "b.mbox",
        "sub/deeper/archive.txt",
    ]
    assert unreadable == []
    b = found[1]
    data = (tmp_path / "b.mbox").read_bytes()
    assert (b.size_bytes, b.sha256_head) == (len(data), hashlib.sha256(data).hexdigest())


async def test_new_files_are_pending(db_session: AsyncSession, tmp_path: Path) -> None:
    _mbox(tmp_path / "a.mbox")
    _mbox(tmp_path / "sub" / "b.mbox")
    report = await scan(db_session, tmp_path)
    assert report.new == ("a.mbox", "sub/b.mbox")
    assert [file.path for file in report.pending] == ["a.mbox", "sub/b.mbox"]
    assert (report.replaced, report.missing) == ((), ())
    size = (tmp_path / "a.mbox").stat().st_size
    rows = await _file_rows(db_session)
    assert rows["a.mbox"] == ("pending", size, 0, 0, 0)
    versions = await fetch(db_session, "SELECT DISTINCT header_version FROM mbox_file")
    assert versions == [(1,)]


async def test_the_files_can_be_examined_beforehand(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _mbox(tmp_path / "a.mbox")
    _mbox(tmp_path / "b.mbox")
    found = find_mbox_files(tmp_path)  # what the API does in a thread
    (tmp_path / "b.mbox").unlink()
    report = await scan(db_session, tmp_path, found)
    assert report.new == ("a.mbox", "b.mbox")  # as found, not as now


async def test_known_files_keep_their_progress(db_session: AsyncSession, tmp_path: Path) -> None:
    done = _mbox(tmp_path / "done.mbox")
    grown = _mbox(tmp_path / "grown.mbox")
    stopped = _mbox(tmp_path / "stopped.mbox")
    failed = _mbox(tmp_path / "failed.mbox")
    await scan(db_session, tmp_path)
    await _progress(db_session, "done.mbox", MboxStatus.DONE, done.stat().st_size)
    grown_size = grown.stat().st_size
    await _progress(db_session, "grown.mbox", MboxStatus.DONE, grown_size)
    await _progress(db_session, "stopped.mbox", MboxStatus.RUNNING, 100)
    await _progress(db_session, "failed.mbox", MboxStatus.ERROR, failed.stat().st_size - 10)
    with grown.open("ab") as handle:
        handle.write(b"From x@y Mon Jan  1 00:00:00 2024\nSubject: more\n\nmore\n\n")

    report = await scan(db_session, tmp_path)
    assert (report.new, report.replaced, report.missing) == ((), (), ())
    assert [file.path for file in report.pending] == ["failed.mbox", "grown.mbox", "stopped.mbox"]
    rows = await _file_rows(db_session)
    assert rows["done.mbox"] == ("done", done.stat().st_size, done.stat().st_size, 2, 1)
    assert rows["grown.mbox"] == ("pending", grown.stat().st_size, grown_size, 2, 1)
    assert rows["stopped.mbox"] == ("pending", stopped.stat().st_size, 100, 2, 1)
    assert rows["failed.mbox"][:2] == ("pending", failed.stat().st_size)
    assert await fetch(
        db_session, "SELECT count(*) FROM mbox_file WHERE worker_id IS NOT NULL"
    ) == [(0,)]


async def test_a_large_file_that_grew_behind_its_head(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    path = tmp_path / "large.mbox"
    write_mbox(path, [message(0, extra_headers=b"X-Pad: " + b"x" * HEAD_SIZE + b"\n")])
    await scan(db_session, tmp_path)
    await _progress(db_session, "large.mbox", MboxStatus.DONE, path.stat().st_size)
    with path.open("ab") as handle:
        handle.write(b"From x@y Mon Jan  1 00:00:00 2024\nSubject: more\n\nmore\n\n")
    report = await scan(db_session, tmp_path)
    assert report.replaced == ()
    assert [file.path for file in report.pending] == ["large.mbox"]


async def test_replaced_and_shrunk_files_start_again(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    replaced = _mbox(tmp_path / "replaced.mbox")
    shrunk = _mbox(tmp_path / "shrunk.mbox")
    kept = _mbox(tmp_path / "kept.mbox")
    report = await scan(db_session, tmp_path)
    ids = {file.path: file.id for file in report.files}
    for path in ids:
        await _progress(db_session, path, MboxStatus.DONE, (tmp_path / path).stat().st_size)
    for file_id in ids.values():
        await db_session.execute(
            text(
                "INSERT INTO mail (mbox_file_id, byte_offset, byte_length, raw_sha256) "
                "VALUES (:id, 0, 10, 'x')"
            ),
            {"id": file_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO import_error (mbox_file_id, byte_offset, kind, message) "
                "VALUES (:id, 0, 'date', 'bad')"
            ),
            {"id": file_id},
        )
    await db_session.execute(text("UPDATE mbox_file SET header_version = 0"))  # imported long ago
    await db_session.commit()
    replaced.write_bytes(replaced.read_bytes().replace(b"Mail 0", b"Mail X"))  # same size
    shrunk.write_bytes(shrunk.read_bytes()[:-20])

    report = await scan(db_session, tmp_path)
    assert report.replaced == (
        ("replaced.mbox", "first MiB changed"),
        (
            "shrunk.mbox",
            f"shrank to {shrunk.stat().st_size} bytes, below its progress of "
            f"{shrunk.stat().st_size + 20}",
        ),
    )
    assert [file.path for file in report.pending] == ["replaced.mbox", "shrunk.mbox"]
    rows = await _file_rows(db_session)
    assert rows["replaced.mbox"] == ("pending", replaced.stat().st_size, 0, 0, 0)
    assert rows["shrunk.mbox"] == ("pending", shrunk.stat().st_size, 0, 0, 0)
    assert rows["kept.mbox"] == ("done", kept.stat().st_size, kept.stat().st_size, 2, 1)
    remaining = await fetch(
        db_session,
        "SELECT f.path, count(DISTINCT m.id), count(DISTINCT e.id) FROM mbox_file f "
        "LEFT JOIN mail m ON m.mbox_file_id = f.id LEFT JOIN import_error e "
        "ON e.mbox_file_id = f.id GROUP BY f.path ORDER BY 1",
    )
    assert remaining == [("kept.mbox", 1, 1), ("replaced.mbox", 0, 0), ("shrunk.mbox", 0, 0)]
    head = await fetch(db_session, "SELECT sha256_head FROM mbox_file WHERE path = 'replaced.mbox'")
    assert head == [(hashlib.sha256(replaced.read_bytes()).hexdigest(),)]
    # Imported again from scratch, its mails get every header field: no header refresh (D52).
    versions = await fetch(db_session, "SELECT path, header_version FROM mbox_file ORDER BY 1")
    assert versions == [("kept.mbox", 0), ("replaced.mbox", 1), ("shrunk.mbox", 1)]


async def test_missing_files_are_left_untouched(db_session: AsyncSession, tmp_path: Path) -> None:
    gone = _mbox(tmp_path / "gone.mbox")
    _mbox(tmp_path / "here.mbox")
    await scan(db_session, tmp_path)
    await _progress(db_session, "gone.mbox", MboxStatus.PAUSED, 50)
    size = gone.stat().st_size
    gone.unlink()
    report = await scan(db_session, tmp_path)
    assert report.missing == ("gone.mbox",)
    assert [file.path for file in report.files] == ["here.mbox"]
    rows = await _file_rows(db_session)
    assert rows["gone.mbox"] == ("paused", size, 50, 2, 1)

"""`mailrobbe import`: options, exit status, the advisory lock, the schema check, Ctrl-C."""

import asyncio
import logging
import os
import shutil
import signal
from pathlib import Path

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import cli as main_cli
from mailrobbe import migrate
from mailrobbe.config import Settings
from mailrobbe.importer.cli import IMPORT_LOCK_KEY, run_import
from tests.conftest import GeneratedArchive
from tests.importer.doubles import (
    PIPELINE,
    READ_ERROR_HEADER,
    copy_archive,
    message,
    start_import,
    wait_until,
    write_mbox,
)


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    migrate.upgrade("head", empty_database_url)
    return empty_database_url


@pytest.fixture
def mbox_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "mbox"
    directory.mkdir()
    write_mbox(directory / "a.mbox", [message(index) for index in range(30)])
    write_mbox(directory / "b.mbox", [message(index) for index in range(100, 120)])
    return directory


def _import(url: str, mbox_dir: Path, workers: int = 2) -> int:
    return asyncio.run(run_import(Settings(database_url=url), mbox_dir, workers, pipeline=PIPELINE))


def test_options() -> None:
    parser = main_cli.build_parser()
    args = parser.parse_args(["import", "--dir", "/srv/mbox", "--workers", "3"])
    assert (args.dir, args.workers) == (Path("/srv/mbox"), 3)
    args = parser.parse_args(["import"])
    assert (args.dir, args.workers) == (None, None)
    with pytest.raises(SystemExit):
        parser.parse_args(["import", "--workers", "0"])


@pytest.mark.db
@pytest.mark.slow
def test_an_import_exits_0_and_a_second_run_finds_nothing_to_do(
    database_url: str,
    mbox_dir: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    assert _import(database_url, mbox_dir) == 0
    out = capsys.readouterr().out
    assert "2 MBOX files, 2 new, 2 to import" in caplog.text
    assert "done a.mbox: 30 mails, 0 import errors" in caplog.text
    assert "files:         2 done, 0 error, 0 missing" in out
    assert "mails:         50 (50 imported in this run)" in out
    assert "persons:       2" in out

    caplog.clear()
    assert _import(database_url, mbox_dir) == 0
    out = capsys.readouterr().out
    assert "2 MBOX files, 0 new, 0 to import" in caplog.text
    assert "updated duplicates, threads and display names" in caplog.text
    assert "mails:         50 (0 imported in this run)" in out


@pytest.mark.db
@pytest.mark.slow
def test_a_file_in_error_exits_1(
    database_url: str,
    mbox_dir: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    write_mbox(mbox_dir / "c.mbox", [message(1, extra_headers=READ_ERROR_HEADER + b"\n")])
    assert _import(database_url, mbox_dir) == 1
    out = capsys.readouterr().out
    assert "error c.mbox at byte 0: cannot read c.mbox: Input/output error" in caplog.text
    assert "files:         2 done, 1 error, 0 missing" in out
    assert "import errors: 1 (io 1)" in out


@pytest.mark.db
async def test_a_second_import_is_refused(
    database_url: str, mbox_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    async with engine.connect() as other:
        await other.execute(text("SELECT pg_advisory_lock(:key)"), {"key": IMPORT_LOCK_KEY})
        settings = Settings(database_url=database_url)
        assert await run_import(settings, mbox_dir, 1, pipeline=PIPELINE) == 1
    await engine.dispose()
    assert "another import is running" in caplog.text
    async with create_async_engine(database_url, poolclass=pool.NullPool).connect() as check:
        assert await check.scalar(text("SELECT count(*) FROM mbox_file")) == 0


@pytest.mark.db
def test_an_outdated_schema_is_refused(
    empty_database_url: str, mbox_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert _import(empty_database_url, mbox_dir) == 1
    assert "schema is at revision none, not at 0002: run `mailrobbe migrate` first" in caplog.text
    migrate.upgrade("0001", empty_database_url)
    assert _import(empty_database_url, mbox_dir) == 1
    assert "schema is at revision 0001, not at 0002" in caplog.text


def test_a_missing_directory_is_refused(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert _import("postgresql+asyncpg://nobody@127.0.0.1:1/none", tmp_path / "nothing") == 1
    assert "is not a directory" in caplog.text


def test_an_unreachable_database_is_reported(
    mbox_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert _import("postgresql+asyncpg://nobody@127.0.0.1:1/none", mbox_dir) == 1
    assert "cannot connect to the database" in caplog.text


@pytest.mark.db
def test_the_command_reads_its_defaults_from_the_settings(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILROBBE_DATABASE_URL", database_url)
    monkeypatch.setenv("MAILROBBE_MBOX_DIR", str(tmp_path))  # no MBOX files: no worker needed
    assert main_cli.main(["import"]) == 0


@pytest.mark.db
@pytest.mark.slow
async def test_dkim_keys_come_from_the_generator_table_below_the_imported_directory(
    database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    mbox_dir = copy_archive(generated_archive.mbox_dir, tmp_path / "mbox")
    (mbox_dir / "_generator").mkdir()
    shutil.copyfile(generated_archive.dns_override, mbox_dir / "_generator" / "dns_override.json")
    settings = Settings(database_url=database_url)  # mbox_dir is not the imported directory
    assert await run_import(settings, mbox_dir, 2, pipeline=PIPELINE) == 0
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT DISTINCT dkim_status::text FROM mail"))
        statuses = {status for (status,) in rows}
    await engine.dispose()
    assert "pass" in statuses  # without the table every key of a reserved TLD is missing


@pytest.mark.db
@pytest.mark.slow
async def test_ctrl_c_pauses_the_running_files_and_exits_130(
    database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    mbox_dir = copy_archive(generated_archive.mbox_dir, tmp_path / "mbox")
    process = start_import(database_url, mbox_dir, "slow")
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    try:
        sql = "SELECT count(*) = 2 FROM mbox_file WHERE status = 'running'"
        await wait_until(engine, sql, process)
        os.killpg(process.pid, signal.SIGINT)  # what a terminal does: the whole process group
        output = process.communicate(timeout=60)[0]
        assert process.returncode == 130, output
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT status::text, count(*) FROM mbox_file GROUP BY 1")
            )
            statuses: dict[str, int] = {status: count for status, count in rows}
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        await engine.dispose()
    assert "stopping: 2 workers store their current batch" in output
    assert output.count("\npaused ") == 2, output
    assert "interrupted: run `mailrobbe import` again to continue" in output
    assert statuses["paused"] == 2
    assert set(statuses) <= {"paused", "pending", "done"}

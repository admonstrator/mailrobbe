"""`mailrobbe import`: options, exit status, the advisory lock, the schema check, the job row
(D47), stopping by Ctrl-C, SIGTERM and the dashboard."""

import asyncio
import logging
import os
import re
import shutil
import signal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ByteSize
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import cli as main_cli
from mailrobbe import jobrun, jobs, migrate
from mailrobbe.config import Settings
from mailrobbe.enums import JobKind, JobOrigin
from mailrobbe.importer.cli import run_import
from mailrobbe.jobs import IMPORT_LOCK_KEY, ImportOptions, ImportProgress
from tests.conftest import GeneratedArchive
from tests.importer.doubles import (
    PIPELINE,
    READ_ERROR_HEADER,
    SLOW_PIPELINE,
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


async def _jobs(url: str) -> list[dict[str, Any]]:
    """The job rows, oldest first."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT * FROM job ORDER BY id"))
        found = [dict(row._mapping) for row in rows]
    await engine.dispose()
    return found


def test_options(capsys: pytest.CaptureFixture[str]) -> None:
    parser = main_cli.build_parser()
    args = parser.parse_args(["import", "--dir", "/srv/mbox", "--workers", "3"])
    assert (args.dir, args.workers, args.origin) == (Path("/srv/mbox"), 3, JobOrigin.CLI)
    args = parser.parse_args(["import"])
    assert (args.dir, args.workers) == (None, None)
    assert parser.parse_args(["import", "--origin", "ui"]).origin is JobOrigin.UI
    for wrong in (["--workers", "0"], ["--origin", "cron"]):
        with pytest.raises(SystemExit):
            parser.parse_args(["import", *wrong])
    with pytest.raises(SystemExit):
        parser.parse_args(["import", "--help"])
    assert "--origin" not in capsys.readouterr().out  # for the dashboard's API only


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
    assert "documents:     0 (0 with text, 0 waiting; 0 stored in this run)" in out
    assert "computed the topics in " in caplog.text
    assert re.search(r"topics: +\d+ terms, 3 periods, 0 clusters \(\d+\.\d s\)", out)

    caplog.clear()
    assert _import(database_url, mbox_dir) == 0
    out = capsys.readouterr().out
    assert "2 MBOX files, 0 new, 0 to import" in caplog.text
    assert "updated duplicates, threads, display names and aggregates" in caplog.text
    assert "mails:         50 (0 imported in this run)" in out
    assert "topics:        unchanged" in out  # the same archive (D146)
    second = ImportProgress.model_validate(asyncio.run(_jobs(database_url))[-1]["progress"])
    assert {step.key: step.status for step in second.steps if step.key.startswith("topic_")} == {
        "topic_terms": "skipped",
        "topic_labels": "skipped",
        "topic_periods": "skipped",
        "topic_clusters": "skipped",
    }


@pytest.mark.db
@pytest.mark.slow
async def test_an_import_records_its_run(database_url: str, mbox_dir: Path) -> None:
    settings = Settings(database_url=database_url, import_attachment_hash_limit=ByteSize(1000))
    assert await run_import(settings, mbox_dir, 3, pipeline=PIPELINE, origin=JobOrigin.UI) == 0
    [job] = await _jobs(database_url)
    assert (job["kind"], job["origin"], job["status"]) == (JobKind.IMPORT, "ui", "done")
    assert job["phase"] == "topics"  # the last phase (D146)
    assert job["message"].startswith("50 mails imported in ")
    assert job["message"].endswith(
        "s; 50 mails, 0 import errors; 0 of 0 documents with text, 0 waiting; "
        "files: 2 done, 0 error, 0 missing"
    )
    options = ImportOptions.model_validate(job["options"])
    assert (options.workers, options.attachment_hash_limit) == (3, 1000)
    assert options.mbox_dir == str(mbox_dir)  # the directory imported, not the settings' one
    progress = ImportProgress.model_validate(job["progress"])
    size = sum(path.stat().st_size for path in mbox_dir.iterdir())
    assert progress.model_dump(include={"workers", "files_queued", "files_finished"}) == {
        "workers": 0,
        "files_queued": 2,
        "files_finished": 2,
    }
    assert (progress.mails_imported, progress.bytes_imported) == (50, size)
    assert progress.mails_per_second > 0 and progress.bytes_per_second > 0
    assert progress.dkim_per_second == progress.mails_per_second  # all checked: unsigned
    assert progress.eta_seconds == 0
    steps = {step.key: step for step in progress.steps}
    assert steps["headers"].status == "skipped"  # no older files
    assert (steps["import"].unit, steps["import"].done, steps["import"].total) == (
        "bytes",
        size,
        size,
    )
    assert all(steps[key].status == "done" for key in ("scan", "import", "edges", "global_stats"))
    assert all(
        step.seconds >= 0 and step.started_at for step in steps.values() if step.status == "done"
    )
    assert job["finished_at"] >= job["started_at"]


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
    [job] = asyncio.run(_jobs(database_url))
    assert job["status"] == "failed"
    assert job["message"].endswith(
        "files: 2 done, 1 error, 0 missing; c.mbox: cannot read c.mbox: Input/output error"
    )


@pytest.mark.db
@pytest.mark.slow
async def test_a_stop_request_pauses_the_import(
    database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    monkeypatch.setattr(jobrun, "REPORT_SECONDS", 0.1)
    mbox_dir = copy_archive(generated_archive.mbox_dir, tmp_path / "mbox")
    settings = Settings(database_url=database_url)
    run = asyncio.create_task(run_import(settings, mbox_dir, 2, pipeline=SLOW_PIPELINE))
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    try:
        sql = (
            "SELECT count(*) = 1 FROM job WHERE phase = 'import' "
            "AND (progress->>'mails_imported')::int > 0 AND (progress->>'workers')::int = 2"
        )
        await wait_until(engine, sql)
        async with engine.begin() as connection:  # what the dashboard's pause does
            assert await jobs.request_stop(connection, JobKind.IMPORT) is not None
        assert await asyncio.wait_for(run, 30) == 130
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT status::text, count(*) FROM mbox_file GROUP BY 1")
            )
            statuses: dict[str, int] = {status: count for status, count in rows}
            mails = await connection.scalar(text("SELECT count(*) FROM mail"))
            counted = await connection.scalar(
                text("SELECT value FROM global_stats WHERE key = 'mails'")
            )
    finally:
        run.cancel()
        await engine.dispose()
    assert counted == mails  # the header's figures include the mails stored before the pause
    assert "stop requested from the dashboard" in caplog.text
    assert "stopping: 2 workers store their current batch" in caplog.text
    # The two running files pause, or end when their current batch was their last one.
    assert set(statuses) <= {"paused", "pending", "done"}
    assert statuses["pending"] > 0  # no file started after the stop
    assert "updated duplicates" not in caplog.text  # no finalize, as after Ctrl-C
    [job] = await _jobs(database_url)
    assert (job["status"], job["phase"], job["stop_requested"]) == ("stopped", "import", True)
    progress = ImportProgress.model_validate(job["progress"])
    assert progress.mails_imported == mails > 0
    finished = statuses.get("done", 0) + statuses.get("paused", 0)
    assert (progress.workers, progress.files_finished) == (0, finished)


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
    assert "schema is at revision none, not at 0012: run `mailrobbe migrate` first" in caplog.text
    migrate.upgrade("0001", empty_database_url)
    assert _import(empty_database_url, mbox_dir) == 1
    assert "schema is at revision 0001, not at 0012" in caplog.text


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
@pytest.mark.parametrize(
    ("signum", "deliveries"),
    [
        (signal.SIGINT, 1),
        # Twice: `uv run` forwards the terminal's Ctrl-C, so the import gets it twice at once.
        (signal.SIGINT, 2),
        # The API server stopping: SIGTERM to the import process alone (D46).
        (signal.SIGTERM, 1),
    ],
)
async def test_a_signal_pauses_the_running_files_and_exits_130(
    database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
    signum: signal.Signals,
    deliveries: int,
) -> None:
    mbox_dir = copy_archive(generated_archive.mbox_dir, tmp_path / "mbox")
    process = start_import(database_url, mbox_dir, "slow")
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    try:
        sql = "SELECT count(*) = 2 FROM mbox_file WHERE status = 'running'"
        await wait_until(engine, sql, process)
        for _ in range(deliveries):
            if signum is signal.SIGINT:  # as a terminal does: the whole process group
                os.killpg(process.pid, signum)
            else:
                os.kill(process.pid, signum)
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
    assert "Traceback" not in output
    assert statuses["paused"] == 2
    assert set(statuses) <= {"paused", "pending", "done"}
    [job] = await _jobs(database_url)
    assert (job["status"], job["phase"], job["stop_requested"]) == ("stopped", "import", False)

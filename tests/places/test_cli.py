"""`mailrobbe map`: the download as a run of kind map (D246), its stop and continuation, the
switch, status and delete. The source is the synthetic one of map_source.py."""

import asyncio
import json
import logging
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, pool, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import cli as main_cli
from mailrobbe import jobrun, jobs, migrate
from mailrobbe.config import Settings
from mailrobbe.enums import JobKind, JobOrigin
from mailrobbe.jobs import MAP_LOCK_KEY
from mailrobbe.places import cli as map_cli
from mailrobbe.places import tiles
from mailrobbe.places.model import BBox, MapOptions, MapProgress
from tests.conftest import _temporary_database
from tests.places.map_source import (
    WORLD_MAX_ZOOM,
    MapSource,
    read_tiles,
    serving,
    world,
    world_tiles,
)

SWISS: BBox = (5.96, 45.82, 10.49, 47.81)


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> Iterator[MapSource]:
    with serving(monkeypatch) as served:
        yield served


@pytest.fixture(scope="module")
def database_url(database_server_url: str) -> Iterator[str]:
    """One migrated database for the module: every test reads the job rows it adds."""
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        yield url


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobrun, "REPORT_SECONDS", 0.05)
    monkeypatch.setattr(tiles, "PARALLEL", 1)
    monkeypatch.setattr(tiles, "REQUEST_BYTES", 2048)  # several requests


def expected_tiles(bbox: BBox) -> dict[int, bytes]:
    every = world_tiles()
    found = {}
    for z in range(WORLD_MAX_ZOOM + 1):
        first_x, first_y, last_x, last_y = tiles.tile_box(bbox, z)
        for x in range(first_x, last_x + 1):
            for y in range(first_y, last_y + 1):
                if (key := tiles.tile_id(z, x, y)) in every:
                    found[key] = every[key]
    return found


async def latest_job(url: str) -> dict[str, Any]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT * FROM job ORDER BY id DESC LIMIT 1"))
        found = dict(rows.one()._mapping)
    await engine.dispose()
    return found


def settings_for(url: str, map_dir: Path, source: str) -> Settings:
    return Settings(database_url=url, map_dir=map_dir, map_source=source)


def set_environment(monkeypatch: pytest.MonkeyPatch, **values: str | Path) -> None:
    for name, value in values.items():
        monkeypatch.setenv(f"MAILROBBE_{name.upper()}", str(value))


# Options and the switch ------------------------------------------------------------------------


def test_options(capsys: pytest.CaptureFixture[str]) -> None:
    parser = main_cli.build_parser()
    args = parser.parse_args(
        [
            "map",
            "download",
            "--region",
            "view",
            "--detail",
            "full",
            "--bbox",
            "9.47,47.04,9.64,47.27",
        ]
    )
    assert (args.task, args.region, args.detail, args.bbox, args.origin) == (
        "download",
        "view",
        "full",
        (9.47, 47.04, 9.64, 47.27),
        JobOrigin.CLI,
    )
    # As the dashboard's API starts it (processes.Runs.start)
    args = parser.parse_args(
        ["map", "--origin", "ui", "download", "--region=ch", "--detail=overview"]
    )
    assert (args.origin, args.region, args.bbox) == (JobOrigin.UI, "ch", None)
    assert parser.parse_args(["map", "status"]).task == "status"
    assert parser.parse_args(["map", "delete"]).task == "delete"
    for wrong in (
        ["download", "--region", "fr", "--detail", "full"],
        ["download", "--region", "de", "--detail", "streets2"],
        ["download", "--region", "view", "--detail", "full", "--bbox", "9.64,47.04,9.47,47.27"],
        ["download", "--region", "view", "--detail", "full", "--bbox", "9,47"],
        ["download", "--detail", "full"],
        [],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(["map", *wrong])
    capsys.readouterr()
    with pytest.raises(SystemExit):
        parser.parse_args(["map", "download", "--help"])
    out = capsys.readouterr().out
    assert "--origin" not in out and "W,S,E,N" in out


def test_a_download_is_refused_when_the_map_is_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    set_environment(monkeypatch, map_dir=tmp_path, map_source="off")
    command = ["map", "download", "--region", "ch", "--detail", "overview"]
    assert main_cli.main(command) == map_cli.EXIT_FAILED
    assert "the detail map is switched off (MAILROBBE_MAP_SOURCE=off)" in caplog.messages
    set_environment(monkeypatch, map_source="ftp://maps.example/planet.pmtiles")
    assert main_cli.main(command) == map_cli.EXIT_USAGE
    set_environment(monkeypatch, map_source="protomaps")
    assert main_cli.main(["map", "download", "--region", "view", "--detail", "full"]) == 2
    assert "region view needs a bbox" in caplog.messages[-1]
    assert list(tmp_path.iterdir()) == []


async def test_status_tells_what_is_there(
    source: MapSource,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url = source.put("/world.pmtiles", world())
    set_environment(monkeypatch, map_dir=tmp_path, map_source=url)
    assert await asyncio.to_thread(main_cli.main, ["map", "status"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert isinstance(printed.pop("free_bytes"), int)
    assert printed == {
        "source": url,
        "offered": True,
        "source_host": "127.0.0.1",
        "map_dir": str(tmp_path),
        "detail_map": None,
        "partial": None,
    }
    options = tiles.map_options("view", "full", SWISS, url)
    prepared = tiles.prepare(tmp_path, options, 5.0)
    assert prepared is not None
    assert await tiles.download(prepared, tmp_path, asyncio.Event(), lambda count: None)
    facts = tiles.finish(tmp_path, prepared.plan)
    prepared = tiles.prepare(tmp_path, options.model_copy(update={"detail": "overview"}), 5.0)
    assert prepared is not None
    stop = asyncio.Event()
    assert not await tiles.download(prepared, tmp_path, stop, lambda count: stop.set())
    set_environment(monkeypatch, map_source="off")
    assert await asyncio.to_thread(main_cli.main, ["map", "status"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["offered"], printed["source_host"]) == (False, None)
    assert printed["detail_map"] == facts.model_dump(mode="json")
    partial = printed["partial"]
    assert (partial["options"]["detail"], partial["source_url"], partial["build"]) == (
        "overview",
        url,
        None,
    )
    assert 0 < partial["bytes_done"] < partial["tile_bytes"]
    assert "done" not in partial


# Runs ------------------------------------------------------------------------------------------


@pytest.mark.db
async def test_a_download_is_a_run_of_kind_map(
    source: MapSource, tmp_path: Path, database_url: str
) -> None:
    url = source.put("/world.pmtiles", world())
    options = tiles.map_options("view", "full", SWISS, url)
    result = await map_cli.run_download(settings_for(database_url, tmp_path, url), options)
    assert result.exit_code == 0
    summary = result.summary
    assert (summary.status, summary.message, summary.restart) == ("done", None, None)
    assert summary.file is not None
    data = (tmp_path / summary.file).read_bytes()
    assert read_tiles(data) == expected_tiles(SWISS)
    assert summary.size == len(data)
    assert summary.bytes_done == summary.bytes_total == summary.tile_bytes > 0
    assert summary.continued_bytes == 0
    assert summary.requests == len(source.requests)
    plan = tiles.plan_extract(tiles.Source(url, None, 5.0), options)
    assert plan is not None
    assert summary.extra_bytes == plan.fetch_bytes - plan.tile_bytes
    assert summary.directory_bytes > 0

    job = await latest_job(database_url)
    assert (job["kind"], job["origin"], job["status"], job["phase"]) == (
        JobKind.MAP,
        "cli",
        "done",
        "finish",
    )
    assert MapOptions.model_validate(job["options"]) == options
    progress = MapProgress.model_validate(job["progress"])
    assert (progress.source_url, progress.build, progress.tiles) == (url, None, summary.tiles)
    assert progress.bytes_done == progress.bytes_total == summary.bytes_total
    steps = {step.key: step for step in progress.steps}
    assert list(steps) == ["directories", "tiles", "finish"]
    assert {step.status for step in steps.values()} == {"done"}
    assert (steps["tiles"].unit, steps["tiles"].done, steps["tiles"].total) == (
        "bytes",
        summary.bytes_total,
        summary.bytes_total,
    )
    assert job["message"].startswith(f"view, full: {tiles.megabytes(summary.size)}, ")
    assert f"in {summary.file}; {summary.requests} requests" in job["message"]


@pytest.mark.db
async def test_a_stopped_run_is_continued_by_the_next(
    source: MapSource, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = source.put("/world.pmtiles", world())
    options = tiles.map_options("view", "full", SWISS, url)
    settings = settings_for(database_url, tmp_path, url)

    async def stopping(
        prepared: tiles.Prepared,
        directory: Path,
        stop: asyncio.Event,
        advance: Callable[[int], None],
    ) -> bool:
        def first(count: int) -> None:
            advance(count)
            stop.set()  # as Ctrl-C does

        return await tiles.download(prepared, directory, stop, first)

    monkeypatch.setattr(map_cli, "download", stopping)
    first = await map_cli.run_download(settings, options)
    assert first.exit_code == jobrun.EXIT_INTERRUPTED
    assert first.summary.status == "stopped" and first.summary.file is None
    assert 0 < first.summary.bytes_done < first.summary.bytes_total
    job = await latest_job(database_url)
    assert (job["status"], job["phase"]) == ("stopped", "download")
    assert job["message"].startswith("view, full: stopped with ")
    assert tiles.read_detail(tmp_path) is None

    monkeypatch.setattr(map_cli, "download", tiles.download)
    second = await map_cli.run_download(settings, options, origin=JobOrigin.UI)
    assert second.exit_code == 0
    summary = second.summary
    assert summary.continued_bytes == first.summary.bytes_done
    assert summary.tile_bytes == summary.bytes_total - summary.continued_bytes
    assert summary.restart is None
    job = await latest_job(database_url)
    assert (job["status"], job["origin"]) == ("done", "ui")
    progress = MapProgress.model_validate(job["progress"])
    assert progress.continued_bytes == first.summary.bytes_done
    assert progress.bytes_done == progress.bytes_total
    tiles_step = next(step for step in progress.steps if step.key == "tiles")
    assert tiles_step.done == tiles_step.total == summary.tile_bytes  # this run's bytes
    assert summary.file is not None
    assert read_tiles((tmp_path / summary.file).read_bytes()) == expected_tiles(SWISS)


@pytest.mark.db
async def test_the_dashboard_stops_a_download(
    source: MapSource, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = source.put("/world.pmtiles", world())
    options = tiles.map_options("view", "overview", SWISS, url)

    async def waiting(
        prepared: tiles.Prepared,
        directory: Path,
        stop: asyncio.Event,
        advance: Callable[[int], None],
    ) -> bool:
        await stop.wait()  # until the request of the dashboard arrives
        return await tiles.download(prepared, directory, stop, advance)

    monkeypatch.setattr(map_cli, "download", waiting)
    run = asyncio.create_task(
        map_cli.run_download(settings_for(database_url, tmp_path, url), options)
    )
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            async with asyncio.timeout(10):
                while (await latest_job(database_url))["phase"] != "download":
                    await asyncio.sleep(0.02)
            assert await jobs.job_alive(connection, JobKind.MAP)
            assert await jobs.request_stop(connection, JobKind.MAP) is not None
            await connection.commit()
        result = await asyncio.wait_for(run, 10)
    finally:
        await engine.dispose()
    assert result.exit_code == jobrun.EXIT_INTERRUPTED
    assert (await latest_job(database_url))["status"] == "stopped"
    partial = tiles.read_partial(tmp_path)
    assert partial is not None and partial.done == []


@pytest.mark.db
async def test_too_little_space_fails_the_run_before_any_tile(
    source: MapSource, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = source.put("/world.pmtiles", world())
    options = tiles.map_options("view", "full", SWISS, url)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage._replace(free=100))
    result = await map_cli.run_download(settings_for(database_url, tmp_path, url), options)
    assert result.exit_code == map_cli.EXIT_FAILED
    assert result.summary.message is not None
    assert result.summary.message.startswith(f"not enough free space in {tmp_path}: ")
    assert result.summary.tile_bytes == 0
    job = await latest_job(database_url)
    assert (job["status"], job["phase"]) == ("failed", "plan")
    assert job["message"] == f"view, full: {result.summary.message}"
    assert result.summary.requests == len(source.requests)  # the directories only


@pytest.mark.db
async def test_a_source_failing_for_good_fails_the_run(
    source: MapSource, tmp_path: Path, database_url: str
) -> None:
    url = source.put("/world.pmtiles", world())
    options = tiles.map_options("view", "full", SWISS, url)
    source.failing = 100
    result = await map_cli.run_download(settings_for(database_url, tmp_path, url), options)
    assert result.exit_code == map_cli.EXIT_FAILED
    assert result.summary.message == "HTTP 503 (tried 4 times)"
    job = await latest_job(database_url)
    assert job["status"] == "failed"
    progress = MapProgress.model_validate(job["progress"])
    assert [step.status for step in progress.steps] == ["failed", "waiting", "waiting"]


@pytest.mark.db
def test_delete_removes_the_files_unless_a_download_runs(
    source: MapSource, tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = source.put("/world.pmtiles", world())
    options = tiles.map_options("view", "full", SWISS, url)
    assert (
        asyncio.run(
            map_cli.run_download(settings_for(database_url, tmp_path, url), options)
        ).exit_code
        == 0
    )
    set_environment(monkeypatch, database_url=database_url, map_dir=tmp_path, map_source=url)

    async def holding() -> int:
        engine = create_async_engine(database_url, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                assert await connection.scalar(select(func.pg_try_advisory_lock(MAP_LOCK_KEY)))
                code = await asyncio.to_thread(main_cli.main, ["map", "delete"])
                await connection.execute(select(func.pg_advisory_unlock(MAP_LOCK_KEY)))
                return code
        finally:
            await engine.dispose()

    assert asyncio.run(holding()) == map_cli.EXIT_FAILED
    assert tiles.read_detail(tmp_path) is not None
    assert main_cli.main(["map", "delete"]) == 0
    assert list(tmp_path.iterdir()) == []
    assert main_cli.main(["map", "delete"]) == 0  # nothing to remove

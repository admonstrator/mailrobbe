"""The maps API (D244 to D246): the overview map's towns, the detail map's status, its download as
a child process beside the dashboard's other runs, stopping and deleting it, and its file served
by range requests.

Runs are tests/api/fake_run.py in place of `mailrobbe map` (processes.CLI), as in
test_imports.py; the files of a detail map come from the synthetic source of
tests/places/map_source.py. Nothing goes to the internet.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, pool, select
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.api import maps
from mailrobbe.config import Settings
from mailrobbe.enums import JobKind
from mailrobbe.jobs import MAP_LOCK_KEY
from mailrobbe.places import tiles
from mailrobbe.places.gazetteer import Town
from mailrobbe.places.model import MAX_ZOOMS, REGIONS, SIZE_HINTS, SIZE_HINTS_BUILD
from tests.api.test_imports import (
    Dashboard,
    error_code,
    fake,
    holding,
    post,
    reaped,
    serve,
    until,
)
from tests.api.test_mails import get, rows
from tests.conftest import _temporary_database
from tests.places.map_source import WORLD_MAX_ZOOM, MapSource, serving, world

pytestmark = pytest.mark.db

SOURCE = "https://maps.example/planet.pmtiles"
SWISS = (5.96, 45.82, 10.49, 47.81)
LIECHTENSTEIN = [9.47, 47.04, 9.64, 47.27]


@pytest.fixture(scope="module")
def database_url(database_server_url: str) -> Iterator[str]:
    """A migrated database for the module; each test starts without job rows."""
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        yield url


def map_settings(url: str, tmp_path: Path, source: str = SOURCE) -> Settings:
    (tmp_path / "mbox").mkdir(exist_ok=True)
    return Settings(
        database_url=url,
        mbox_dir=tmp_path / "mbox",
        map_dir=tmp_path / "maps",
        map_source=source,
        frontend_dir=tmp_path / "no-frontend",
    )


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return map_settings(database_url, tmp_path)


@pytest.fixture
async def dashboard(settings: Settings) -> AsyncIterator[Dashboard]:
    await rows(settings.database_url, "DELETE FROM job")
    async with serve(settings) as dashboard:
        yield dashboard


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> Iterator[MapSource]:
    with serving(monkeypatch) as served:
        yield served


async def detail_map(source: MapSource, directory: Path) -> tiles.DetailFacts:
    """A detail map of Switzerland in directory, from the synthetic source."""
    url = source.put("/world.pmtiles", world())
    prepared = tiles.prepare(directory, tiles.map_options("ch", "full", None, url), 5.0)
    assert prepared is not None
    assert await tiles.download(prepared, directory, asyncio.Event(), lambda count: None)
    return tiles.finish(directory, prepared.plan)


async def stopped_download(source: MapSource, directory: Path) -> tiles.Partial:
    """A download of Liechtenstein stopped after its first request."""
    url = source.put("/world.pmtiles", world())
    options = tiles.map_options("view", "overview", LIECHTENSTEIN, url)
    prepared = tiles.prepare(directory, options, 5.0)
    assert prepared is not None
    stop = asyncio.Event()
    assert not await tiles.download(prepared, directory, stop, lambda count: stop.set())
    partial = tiles.read_partial(directory)
    assert partial is not None
    return partial


async def map_job(dashboard: Dashboard) -> Any:
    return (await get(dashboard.client, "/api/map/status"))["job"]


async def map_ended(dashboard: Dashboard) -> Any:
    """The latest map run once it ended and was reaped."""

    async def ended() -> bool:
        job = await map_job(dashboard)
        return bool(job["status"] != "running" and not dashboard.runs.children)

    await until(ended)
    return await map_job(dashboard)


# Towns -----------------------------------------------------------------------------------------


@pytest.fixture
def towns(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Town]]:
    found = [
        Town("Berlin", "Berlin", "DE", 52.52437, 13.41053, 3_426_354, True),
        Town("Vaduz", None, "LI", 47.14151, 9.52154, 5_197, True),
    ]
    monkeypatch.setattr(maps, "label_towns", lambda: tuple(found))
    maps._towns.cache_clear()
    yield found
    maps._towns.cache_clear()


async def test_the_towns_are_read_once_and_cached_for_a_day(
    dashboard: Dashboard, towns: list[Town]
) -> None:
    response = await dashboard.client.get("/api/map/towns")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=86400"
    assert response.headers["content-type"] == "application/json"
    expected = [
        {
            "name": "Berlin",
            "lat": 52.52437,
            "lon": 13.41053,
            "population": 3_426_354,
            "country": "DE",
            "capital": True,
        },
        {
            "name": "Vaduz",
            "lat": 47.14151,
            "lon": 9.52154,
            "population": 5_197,
            "country": "LI",
            "capital": True,
        },
    ]
    assert response.json() == expected
    towns.clear()  # the lists are read once per process
    assert await get(dashboard.client, "/api/map/towns") == expected


# Status ----------------------------------------------------------------------------------------


async def test_the_status_offers_the_regions_and_details(dashboard: Dashboard) -> None:
    status = await get(dashboard.client, "/api/map/status")
    assert isinstance(status.pop("free_bytes"), int)  # of the directory map_dir would be in
    assert status == {
        "offered": True,
        "source_host": "maps.example",
        "detail_map": None,
        "partial": None,
        "regions": [
            {"key": key, "bbox": list(bbox), "sizes": SIZE_HINTS[key]}
            for key, bbox in REGIONS.items()
        ],
        "details": [{"key": key, "max_zoom": zoom} for key, zoom in MAX_ZOOMS.items()],
        "size_hints_build": SIZE_HINTS_BUILD,
        "job": None,
    }


@pytest.mark.parametrize("value", ["off", "ftp://maps.example/planet.pmtiles"])
async def test_no_download_is_offered_when_the_map_is_off_or_its_source_unusable(
    database_url: str, tmp_path: Path, value: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    async with serve(map_settings(database_url, tmp_path, value)) as dashboard:
        status = await get(dashboard.client, "/api/map/status")
        assert (status["offered"], status["source_host"]) == (False, None)
        body = {"region": "ch", "detail": "overview"}
        assert await error_code(dashboard.client, "/api/map/download", body, 409) == "map_off"
    assert ("no detail map is offered" in caplog.text) is (value != "off")


async def test_the_status_shows_the_detail_map_and_a_stopped_download(
    dashboard: Dashboard, settings: Settings, source: MapSource
) -> None:
    facts = await detail_map(source, settings.map_dir)
    partial = await stopped_download(source, settings.map_dir)
    status = await get(dashboard.client, "/api/map/status")
    assert status["detail_map"] == {
        "url": f"/api/map/tiles/{facts.file}",
        "region": "ch",
        "bbox": list(SWISS),
        "detail": "full",
        "max_zoom": WORLD_MAX_ZOOM,  # the source has no more
        "build": None,
        "source_url": facts.source_url,
        "size": facts.size,
        "tiles": facts.tiles,
        "downloaded_at": facts.downloaded_at.isoformat().replace("+00:00", "Z"),
    }
    assert status["partial"] == {
        "region": "view",
        "bbox": LIECHTENSTEIN,
        "detail": "overview",
        "build": None,
        "bytes_done": partial.bytes_done,
        "bytes_total": partial.tile_bytes,
    }
    assert 0 < partial.bytes_done < partial.tile_bytes


# The tiles file --------------------------------------------------------------------------------


async def test_the_detail_map_is_served_by_range_requests(
    dashboard: Dashboard, settings: Settings, source: MapSource
) -> None:
    facts = await detail_map(source, settings.map_dir)
    data = (settings.map_dir / facts.file).read_bytes()
    path = f"/api/map/tiles/{facts.file}"
    whole = await dashboard.client.get(path)
    assert whole.status_code == 200
    assert whole.content == data
    headers = whole.headers
    assert headers["content-type"] == "application/vnd.pmtiles"
    assert headers["accept-ranges"] == "bytes"
    assert headers["cache-control"] == "no-cache"
    assert headers["x-content-type-options"] == "nosniff"
    etag = headers["etag"]

    first = await dashboard.client.get(path, headers={"Range": "bytes=0-126"})
    assert first.status_code == 206
    assert first.headers["content-range"] == f"bytes 0-126/{len(data)}"
    assert first.headers["etag"] == etag
    assert tiles.Header.from_bytes(first.content).tile_data_length == facts.size - (
        tiles.Header.from_bytes(data).tile_data_offset
    )
    last = await dashboard.client.get(path, headers={"Range": f"bytes={len(data) - 10}-"})
    assert (last.status_code, last.content) == (206, data[-10:])
    beyond = await dashboard.client.get(path, headers={"Range": f"bytes={len(data)}-"})
    assert beyond.status_code == 416

    for other in ("detail.json", "download.part", "osm-ch-full-20990101000000.pmtiles"):
        response = await dashboard.client.get(f"/api/map/tiles/{other}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"
    assert (await dashboard.client.get("/api/map/tiles/..%2Fdetail.json")).status_code == 404


async def test_no_file_is_served_without_a_detail_map(dashboard: Dashboard) -> None:
    response = await dashboard.client.get("/api/map/tiles/osm-ch-full-20261022000000.pmtiles")
    assert response.status_code == 404


# Download, stop, delete ------------------------------------------------------------------------


async def test_a_download_starts_a_run_of_mailrobbe_map(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    job = await post(
        dashboard.client, "/api/map/download", {"region": "ch", "detail": "overview"}, 202
    )
    assert (job["kind"], job["origin"], job["status"], job["alive"]) == (
        "map",
        "ui",
        "running",
        True,
    )
    assert job["options"] == {
        "region": "ch",
        "detail": "overview",
        "bbox": list(SWISS),
        "max_zoom": MAX_ZOOMS["overview"],
        "source": SOURCE,
    }
    assert job["progress"]["bytes_done"] == 0
    status = await get(dashboard.client, "/api/map/status")
    assert (status["job"]["id"], status["job"]["options"]) == (job["id"], job["options"])
    assert status["partial"] is None  # while a run is alive, it shows its own progress
    body = {"region": "de", "detail": "streets"}
    assert await error_code(dashboard.client, "/api/map/download", body, 409) == "job_running"

    stopped = await post(dashboard.client, "/api/map/download/stop", {})
    assert (stopped["id"], stopped["stop_requested"]) == (job["id"], True)
    ended = await map_ended(dashboard)
    assert (ended["status"], ended["message"]) == ("stopped", "stop requested")
    assert await error_code(dashboard.client, "/api/map/download/stop", {}, 409) == "no_job"


async def test_a_download_of_the_view_passes_its_bbox(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "done")
    body = {"region": "view", "detail": "full", "bbox": [-1.25, 47.04, 9.64, 47.27]}
    job = await post(dashboard.client, "/api/map/download", body, 202)
    assert job["options"]["bbox"] == [-1.25, 47.04, 9.64, 47.27]
    assert job["options"]["max_zoom"] == MAX_ZOOMS["full"]
    await reaped(dashboard)
    assert (await map_job(dashboard))["status"] == "done"


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"region": "view", "detail": "full"}, 400, "invalid_option"),
        ({"region": "ch", "detail": "full", "bbox": LIECHTENSTEIN}, 400, "invalid_option"),
        (
            {"region": "view", "detail": "full", "bbox": [9.64, 47.04, 9.47, 47.27]},
            400,
            "invalid_option",
        ),
        (
            {"region": "view", "detail": "full", "bbox": [9.47, 47.04, 9.64, 95]},
            400,
            "invalid_option",
        ),
        ({"region": "fr", "detail": "full"}, 422, None),
        ({"region": "ch", "detail": "huge"}, 422, None),
        ({"region": "ch"}, 422, None),
    ],
)
async def test_a_download_of_unusable_options_is_refused(
    dashboard: Dashboard,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
    status: int,
    code: str | None,
) -> None:
    fake(monkeypatch, "done")
    answer = await post(dashboard.client, "/api/map/download", body, status)
    if code is not None:
        assert answer["detail"]["code"] == code
    assert dashboard.runs.children == []
    assert await map_job(dashboard) is None


async def test_a_download_needs_no_mbox_directory(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "done")
    await rows(database_url, "DELETE FROM job")
    settings = map_settings(database_url, tmp_path).model_copy(
        update={"mbox_dir": tmp_path / "missing"}
    )
    async with serve(settings) as dashboard:
        assert await error_code(dashboard.client, "/api/import/start", {}, 409) == (
            "mbox_dir_missing"
        )
        await post(dashboard.client, "/api/map/download", {"region": "at", "detail": "full"}, 202)
        await reaped(dashboard)


async def test_a_map_download_and_an_import_run_side_by_side(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    await post(dashboard.client, "/api/map/download", {"region": "ch", "detail": "full"}, 202)
    # An import and a DKIM check start while the download is alive ...
    imported = await post(dashboard.client, "/api/import/start", {}, 202)
    assert imported["alive"] is True
    assert await error_code(dashboard.client, "/api/dkim/recheck", {}, 409) == "job_running"
    assert len(dashboard.runs.children) == 2
    await post(dashboard.client, "/api/import/pause", {})

    async def import_ended() -> bool:
        job = (await get(dashboard.client, "/api/import/status"))["import_job"]
        return bool(job["status"] != "running" and len(dashboard.runs.children) == 1)

    await until(import_ended)
    fake(monkeypatch, "done")
    await post(dashboard.client, "/api/dkim/recheck", {}, 202)
    assert (await map_job(dashboard))["alive"] is True
    await post(dashboard.client, "/api/map/download/stop", {})
    await map_ended(dashboard)

    # ... and a download starts while an import is alive.
    fake(monkeypatch, "wait")
    await post(dashboard.client, "/api/import/start", {}, 202)
    job = await post(
        dashboard.client, "/api/map/download", {"region": "at", "detail": "overview"}, 202
    )
    assert job["alive"] is True
    await post(dashboard.client, "/api/map/download/stop", {})
    await post(dashboard.client, "/api/import/pause", {})
    await reaped(dashboard)


@pytest.mark.parametrize("kind", [JobKind.IMPORT, JobKind.DKIM, JobKind.DKIM_KEYS])
async def test_a_run_from_a_command_line_does_not_keep_a_download_from_starting(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch, kind: JobKind
) -> None:
    fake(monkeypatch, "done")
    async with holding(dashboard.url, kind):
        await post(dashboard.client, "/api/map/download", {"region": "ch", "detail": "full"}, 202)
        await reaped(dashboard)


async def test_a_download_from_a_command_line_keeps_another_from_starting(
    dashboard: Dashboard, settings: Settings, monkeypatch: pytest.MonkeyPatch, source: MapSource
) -> None:
    fake(monkeypatch, "done")
    await detail_map(source, settings.map_dir)
    async with holding(dashboard.url, JobKind.MAP):
        body = {"region": "ch", "detail": "full"}
        assert await error_code(dashboard.client, "/api/map/download", body, 409) == "job_running"
        response = await dashboard.client.delete("/api/map/detail")
        assert (response.status_code, response.json()["detail"]["code"]) == (409, "job_running")
        # It holds the lock but has recorded no row yet: nothing to stop.
        assert await error_code(dashboard.client, "/api/map/download/stop", {}, 409) == "no_job"
        await post(dashboard.client, "/api/import/start", {}, 202)
    assert tiles.read_detail(settings.map_dir) is not None
    await reaped(dashboard)


async def test_deleting_removes_the_detail_map_unless_a_download_runs(
    dashboard: Dashboard, settings: Settings, monkeypatch: pytest.MonkeyPatch, source: MapSource
) -> None:
    await detail_map(source, settings.map_dir)
    await stopped_download(source, settings.map_dir)
    fake(monkeypatch, "wait")
    await post(dashboard.client, "/api/map/download", {"region": "ch", "detail": "full"}, 202)
    response = await dashboard.client.delete("/api/map/detail")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "job_running")
    await post(dashboard.client, "/api/map/download/stop", {})
    await map_ended(dashboard)

    response = await dashboard.client.delete("/api/map/detail")
    assert response.status_code == 204
    assert list(settings.map_dir.iterdir()) == []
    status = await get(dashboard.client, "/api/map/status")
    assert (status["detail_map"], status["partial"]) == (None, None)
    assert (await dashboard.client.delete("/api/map/detail")).status_code == 204


async def test_a_server_stopping_stops_its_download(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    await rows(settings.database_url, "DELETE FROM job")
    async with serve(settings) as dashboard:
        await post(dashboard.client, "/api/map/download", {"region": "ch", "detail": "full"}, 202)
        await post(dashboard.client, "/api/import/start", {}, 202)
    ended = await rows(
        settings.database_url, "SELECT kind::text, status::text, message FROM job ORDER BY id"
    )
    assert [tuple(row) for row in ended] == [
        ("map", "stopped", "SIGTERM"),
        ("import", "stopped", "SIGTERM"),
    ]
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:  # the lock is free again
        assert await connection.scalar(select(func.pg_try_advisory_lock(MAP_LOCK_KEY)))
    await engine.dispose()

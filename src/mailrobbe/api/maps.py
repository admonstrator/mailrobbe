"""Maps (milestone 20, D244 to D246): the overview map's town labels and the detail map, its
download as a run of `mailrobbe map download` and its PMTiles file.

The towns come from the shipped lists (places.gazetteer), read once per process and cached by
the browser for a day. The status reads the files in MAILROBBE_MAP_DIR (places.tiles) and the
latest job row of kind map; it is polled while a download runs, so it reads nothing else. A
download starts as a child process like the dashboard's other runs (processes.py), beside an
import or DKIM run; only another map download, alive or starting, keeps it from starting. The
detail map's file is served by name with range requests (Starlette's FileResponse: 206, 416,
ETag), revalidated on every use (no-cache), so the browser sees a new map at once; nothing else
in the directory is served.
"""

import asyncio
import functools
import logging
from typing import get_args

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse
from pydantic import TypeAdapter

from mailrobbe import jobs
from mailrobbe.api import processes
from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.imports import JSON_BODY, NoOptions, Runs, _job_fields, _start, _stop, _valid
from mailrobbe.api.schemas import (
    DetailMap,
    MapDetailInfo,
    MapDownloadRequest,
    MapJob,
    MapPartial,
    MapRegionInfo,
    MapStatus,
    TownLabel,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import Job
from mailrobbe.enums import JobKind
from mailrobbe.places.gazetteer import label_towns
from mailrobbe.places.model import (
    MAX_ZOOMS,
    REGIONS,
    SIZE_HINTS,
    SIZE_HINTS_BUILD,
    MapOptions,
    MapPhase,
    MapProgress,
)
from mailrobbe.places.tiles import (
    delete_maps,
    free_bytes,
    map_options,
    read_detail,
    read_partial,
    source_host,
    source_setting,
)

router = APIRouter(prefix="/api", tags=["maps"])
log = logging.getLogger(__name__)

PMTILES_TYPE = "application/vnd.pmtiles"
TILE_HEADERS = {"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"}
TOWN_HEADERS = {"Cache-Control": "private, max-age=86400"}


@functools.cache
def _towns() -> bytes:
    labels = [
        TownLabel(
            name=town.name,
            lat=town.latitude,
            lon=town.longitude,
            population=town.population,
            country=town.country,
            capital=town.capital,
        )
        for town in label_towns()
    ]
    return TypeAdapter(list[TownLabel]).dump_json(labels)


@router.get("/map/towns", response_model=list[TownLabel])
async def map_towns() -> Response:
    return Response(
        await asyncio.to_thread(_towns), media_type="application/json", headers=TOWN_HEADERS
    )


def _setting(settings: Settings) -> str | None:
    """MAILROBBE_MAP_SOURCE: protomaps or a URL; None when off or unusable (logged)."""
    try:
        return source_setting(settings.map_source)
    except ValueError as error:
        log.warning("no detail map is offered: %s", error)
        return None


@router.get("/map/status")
async def map_status(session: Session, settings: AppSettings) -> MapStatus:
    setting = _setting(settings)
    directory = settings.map_dir
    facts = await asyncio.to_thread(read_detail, directory)
    partial = await asyncio.to_thread(read_partial, directory)
    row = await jobs.latest_job(session, JobKind.MAP)
    job = None if row is None else await _map_job(session, row)
    detail_map = stopped = None
    if facts is not None:
        fields = facts.model_dump(exclude={"file"})
        detail_map = DetailMap(url=f"/api/map/tiles/{facts.file}", **fields)
    if partial is not None and not (job is not None and job.alive):  # the run shows its own
        stopped = MapPartial(
            region=partial.options.region,
            bbox=partial.options.bbox,
            detail=partial.options.detail,
            build=partial.build,
            bytes_done=partial.bytes_done,
            bytes_total=partial.tile_bytes,
        )
    return MapStatus(
        offered=setting is not None,
        source_host=None if setting is None else source_host(setting),
        detail_map=detail_map,
        partial=stopped,
        regions=[
            MapRegionInfo(key=key, bbox=bbox, sizes=SIZE_HINTS[key])
            for key, bbox in REGIONS.items()
        ],
        details=[MapDetailInfo(key=key, max_zoom=zoom) for key, zoom in MAX_ZOOMS.items()],
        size_hints_build=SIZE_HINTS_BUILD,
        free_bytes=await asyncio.to_thread(free_bytes, directory),
        job=job,
    )


async def _map_job(session: Session, job: Job) -> MapJob | None:
    """A map run as the card shows it; None for a row of another shape."""
    options = _valid(MapOptions, job.options)
    if options is None:
        return None
    return MapJob.model_validate(
        await _job_fields(session, job)
        | {
            "phase": job.phase if job.phase in get_args(MapPhase) else None,
            "options": options,
            "progress": _valid(MapProgress, job.progress) or MapProgress(),
        }
    )


@router.post("/map/download", status_code=202, dependencies=JSON_BODY)
async def start_download(
    request: MapDownloadRequest, session: Session, settings: AppSettings, runs: Runs
) -> MapJob:
    """Start `mailrobbe map download` as the dashboard starts its runs (D46, D246)."""
    setting = _setting(settings)
    if setting is None:
        raise api_error(409, "map_off", "no detail map is offered (MAILROBBE_MAP_SOURCE)")
    try:
        options = map_options(request.region, request.detail, request.bbox, setting)
    except ValueError as error:
        raise api_error(400, "invalid_option", str(error)) from None
    arguments = ["download", f"--region={options.region}", f"--detail={options.detail}"]
    if options.region == "view":
        arguments.append("--bbox=" + ",".join(repr(value) for value in options.bbox))
    environment = processes.child_environment(settings)
    job = await _start(session, settings, runs, JobKind.MAP, arguments, environment)
    started = await _map_job(session, job)
    assert started is not None  # the run recorded its options
    return started


@router.post("/map/download/stop", dependencies=JSON_BODY)
async def stop_download(_: NoOptions, session: Session) -> MapJob:
    job = await _map_job(session, await _stop(session, JobKind.MAP))
    if job is None:
        raise api_error(409, "no_job", "the map run alive has no options this server reads")
    return job


@router.delete("/map/detail", status_code=204)
async def delete_detail(session: Session, settings: AppSettings, runs: Runs) -> Response:
    """The detail map and a stopped download's files; 409 while a map download is alive."""
    if runs.map_lock.locked() or runs.children_of((JobKind.MAP,)):
        raise api_error(409, "job_running", "a map download started here has not ended")
    async with runs.map_lock:
        if await jobs.job_alive(session, JobKind.MAP):
            raise api_error(409, "job_running", "a mailrobbe map run is alive")
        removed = await asyncio.to_thread(delete_maps, settings.map_dir)
    if removed:
        log.info("removed %s from %s", ", ".join(removed), settings.map_dir)
    return Response(status_code=204)


@router.get("/map/tiles/{file}")
async def map_tiles(file: str, settings: AppSettings) -> FileResponse:
    """The detail map's file, by its name only."""
    facts = await asyncio.to_thread(read_detail, settings.map_dir)
    if facts is None or file != facts.file:
        raise api_error(404, "not_found", f"{file!r} is not the detail map")
    path = settings.map_dir / facts.file
    return FileResponse(path, media_type=PMTILES_TYPE, headers=TILE_HEADERS)

"""`mailrobbe map`: the detail map (D245, D246).

    download  take the tiles of a region from MAILROBBE_MAP_SOURCE into one PMTiles file in
              MAILROBBE_MAP_DIR (tiles.py); a stopped download goes on at the next run of the
              same region, detail and bbox from the same source file
    status    print what is there as JSON: the source, the detail map, a download not finished
    delete    remove the detail map and a download not finished yet

A download records itself in `job` (kind map) and holds a lock of its own, so it runs beside an
import or DKIM run and excludes only another download. Its phases are plan (step directories:
the source's header and the leaf directories over the region, the new file's directories),
download (step tiles, in bytes) and finish (step finish: the file in place). It needs the bytes
still to write and 5 % more free in MAILROBBE_MAP_DIR before it fetches a tile.

Exit status as for `mailrobbe dkim`: 0 when done, 130 when stopped by Ctrl-C, SIGTERM or the
dashboard (what was downloaded stays for the next run), 1 when it could not start or failed (the
source not answering after its retries, too little free space; what was downloaded stays), 2
for arguments it cannot use.
"""

import argparse
import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any, get_args

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from mailrobbe.config import Settings, get_settings
from mailrobbe.db.session import create_engine
from mailrobbe.dkim.cli import error_line
from mailrobbe.enums import JobKind, JobOrigin, JobStatus
from mailrobbe.jobrun import EXIT_INTERRUPTED, JobRun, RunRefused, job_run
from mailrobbe.jobs import MAP_LOCK_KEY, application_name
from mailrobbe.places.model import (
    MAP_STEPS,
    MAX_ZOOMS,
    BBox,
    MapDetailKey,
    MapOptions,
    MapProgress,
    MapRegionKey,
)
from mailrobbe.places.tiles import (
    NotEnoughSpace,
    Prepared,
    SourceError,
    check_bbox,
    check_space,
    delete_maps,
    describe,
    download,
    finish,
    free_bytes,
    map_options,
    megabytes,
    prepare,
    read_detail,
    read_partial,
    source_host,
    source_setting,
)

log = logging.getLogger(__name__)

EXIT_FAILED = 1
EXIT_USAGE = 2


def _bbox(value: str) -> BBox:
    try:
        return check_bbox([float(part) for part in value.split(",")])
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r}: {error}") from None


def add_arguments(parser: argparse.ArgumentParser) -> None:
    # Who started the run (job.origin); the dashboard's API passes ui before the task.
    parser.add_argument(
        "--origin",
        type=JobOrigin,
        choices=list(JobOrigin),
        default=JobOrigin.CLI,
        help=argparse.SUPPRESS,
    )
    tasks = parser.add_subparsers(dest="task", required=True, metavar="TASK")
    fetch = tasks.add_parser(
        "download",
        help="download the detail map of a region from OpenStreetMap data",
        description="Take the tiles of a region from MAILROBBE_MAP_SOURCE by range requests "
        "into one PMTiles file in MAILROBBE_MAP_DIR, which replaces the detail map once "
        "complete. A stopped download goes on at the next run of the same choice.",
    )
    fetch.add_argument(
        "--region",
        required=True,
        choices=get_args(MapRegionKey),
        help="de, at, ch (with Liechtenstein), dach, or view with --bbox",
    )
    zooms = ", ".join(f"{key} (zoom {zoom})" for key, zoom in MAX_ZOOMS.items())
    fetch.add_argument(
        "--detail", required=True, choices=get_args(MapDetailKey), help=f"one of {zooms}"
    )
    fetch.add_argument(
        "--bbox",
        type=_bbox,
        metavar="W,S,E,N",
        help="the area of region view in decimal degrees, west below east",
    )
    fetch.add_argument("--quiet", action="store_true", help="no progress output")
    tasks.add_parser(
        "status",
        help="print the detail map and a download not finished yet as JSON",
        description="Print the source, the detail map and a download not finished yet as JSON.",
    )
    tasks.add_parser(
        "delete",
        help="remove the detail map and a download not finished yet",
        description="Remove the detail map and a download not finished yet from "
        "MAILROBBE_MAP_DIR; refused while a download runs.",
    )


def run(args: argparse.Namespace) -> int:
    quiet = getattr(args, "quiet", False)
    logging.basicConfig(level=logging.WARNING if quiet else logging.INFO, format="%(message)s")
    settings = get_settings()
    if args.task == "status":
        print(json.dumps(status(settings), indent=2))
        return 0
    if args.task == "delete":
        return asyncio.run(_delete(settings))
    try:
        setting = source_setting(settings.map_source)
        if setting is None:
            log.error("the detail map is switched off (MAILROBBE_MAP_SOURCE=off)")
            return EXIT_FAILED
        options = map_options(args.region, args.detail, args.bbox, setting)
    except ValueError as error:
        log.error("%s", error)
        return EXIT_USAGE
    try:
        result = asyncio.run(run_download(settings, options, origin=args.origin))
    except RunRefused as refusal:
        log.error("%s", refusal)
        return EXIT_FAILED
    except SQLAlchemyError as error:
        log.error("database error: %s", error_line(error))
        return EXIT_FAILED
    print(json.dumps(asdict(result.summary), indent=2))
    return result.exit_code


def status(settings: Settings) -> dict[str, Any]:
    """What `mailrobbe map status` prints."""
    try:
        setting = source_setting(settings.map_source)
    except ValueError:
        setting = None
    detail = read_detail(settings.map_dir)
    partial = read_partial(settings.map_dir)
    return {
        "source": settings.map_source,
        "offered": setting is not None,
        "source_host": None if setting is None else source_host(setting),
        "map_dir": str(settings.map_dir),
        "free_bytes": free_bytes(settings.map_dir),
        "detail_map": None if detail is None else detail.model_dump(mode="json"),
        "partial": None if partial is None else partial.model_dump(mode="json", exclude={"done"}),
    }


async def _delete(settings: Settings) -> int:
    """Remove the files under the map lock, so no download writes them meanwhile."""
    engine = create_engine(settings.database_url, application_name(JobKind.MAP))
    try:
        async with engine.connect() as connection:
            locked = await connection.scalar(select(func.pg_try_advisory_lock(MAP_LOCK_KEY)))
            await connection.commit()
            if not locked:
                log.error("a map download is running; stop it first")
                return EXIT_FAILED
            try:
                removed = delete_maps(settings.map_dir)
            finally:
                await connection.execute(select(func.pg_advisory_unlock(MAP_LOCK_KEY)))
                await connection.commit()
    except (SQLAlchemyError, OSError) as error:
        log.error("cannot delete the detail map: %s", error_line(error))
        return EXIT_FAILED
    finally:
        await engine.dispose()
    log.info("removed %s", ", ".join(removed) if removed else "nothing")
    return 0


# The download ----------------------------------------------------------------------------------


@dataclass(slots=True)
class MapSummary:
    """Printed as JSON by `mailrobbe map download`."""

    status: str  # done, stopped or failed
    message: str | None  # why it failed
    region: str
    detail: str
    file: str | None = None  # the new detail map's name, once done
    size: int = 0  # bytes of the new file
    tiles: int = 0
    source_url: str | None = None
    build: str | None = None
    restart: str | None = None  # why a stopped download was not continued
    bytes_total: int = 0  # tile bytes of the new file
    bytes_done: int = 0  # of those, on disk
    continued_bytes: int = 0  # downloaded by an earlier run this one continued
    requests: int = 0  # sent to the source by this run, directories included
    directory_bytes: int = 0  # header, metadata and directories read
    tile_bytes: int = 0  # tile bytes this run wrote
    extra_bytes: int = 0  # read along between the tiles of joined requests
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class MapRun:
    summary: MapSummary
    exit_code: int


_STATUSES = {0: JobStatus.DONE, EXIT_INTERRUPTED: JobStatus.STOPPED, EXIT_FAILED: JobStatus.FAILED}


async def run_download(
    settings: Settings, options: MapOptions, *, origin: JobOrigin = JobOrigin.CLI
) -> MapRun:
    """One run of `mailrobbe map download`; jobrun.RunRefused when it cannot start."""
    progress = MapProgress()

    async def report(_db: AsyncConnection) -> MapProgress:
        return progress.model_copy()  # the run adds its steps

    engine = create_engine(settings.database_url, application_name(JobKind.MAP))
    try:
        async with job_run(
            engine, JobKind.MAP, origin, options, phase="plan", figures=report
        ) as job:
            job.steps.plan(*MAP_STEPS)
            result = await _Download(job, settings, options, progress).run()
            job.end(_STATUSES[result.exit_code], _one_line(result.summary))
    finally:
        await engine.dispose()
    return result


class _Download:
    """The phases of one download, keeping its figures and summary."""

    def __init__(
        self, job: JobRun, settings: Settings, options: MapOptions, progress: MapProgress
    ) -> None:
        self.job = job
        self.directory = settings.map_dir
        self.timeout = settings.map_timeout
        self.options = options
        self.progress = progress
        self.summary = MapSummary("failed", None, options.region, options.detail)
        self.started = time.monotonic()
        self.prepared: Prepared | None = None

    async def run(self) -> MapRun:
        try:
            return await self._phases()
        except (SourceError, NotEnoughSpace) as error:
            log.error("%s", error)
            self.summary.message = str(error)
            return self._ended(EXIT_FAILED)

    async def _phases(self) -> MapRun:
        job, directory, options, progress = self.job, self.directory, self.options, self.progress
        with job.steps.step("directories"):
            prepared = await asyncio.to_thread(
                prepare, directory, options, self.timeout, job.stop.is_set
            )
        if prepared is None:
            log.info("stopped while reading the source's directories")
            return self._ended(EXIT_INTERRUPTED)
        self.prepared = prepared
        plan, partial = prepared.plan, prepared.partial
        summary = self.summary
        summary.directory_bytes = prepared.source.bytes
        summary.source_url = progress.source_url = plan.source_url
        summary.build = progress.build = plan.build
        summary.tiles = progress.tiles = plan.tiles
        summary.bytes_total = progress.bytes_total = plan.tile_bytes
        summary.bytes_done = progress.bytes_done = partial.bytes_done
        summary.size = plan.file_size
        summary.restart = prepared.restart
        build = f" (build {plan.build})" if plan.build else ""
        log.info("source: %s%s", plan.source_url, build)
        if prepared.restart:
            log.warning("starting over: %s", prepared.restart)
        if prepared.continued:
            progress.continued_bytes = summary.continued_bytes = partial.bytes_done
            log.info(
                "continuing the stopped download: %s of %s on disk",
                megabytes(partial.bytes_done),
                megabytes(plan.tile_bytes),
            )
        log.info(
            "%s: %s tiles, %s in %d requests (%s read along between tiles), a file of %s",
            describe(options),
            f"{plan.tiles:,}",
            megabytes(plan.tile_bytes),
            len(plan.fetches),
            megabytes(plan.fetch_bytes - plan.tile_bytes),
            megabytes(plan.file_size),
        )
        check_space(directory, plan.file_size - partial.bytes_done)

        job.set_phase("download")
        remaining = plan.tile_bytes - partial.bytes_done
        with job.steps.step("tiles", unit="bytes", total=remaining) as counter:

            def advance(count: int) -> None:
                counter.advance(count)
                progress.bytes_done += count
                summary.bytes_done += count
                summary.tile_bytes += count

            complete = await download(prepared, directory, job.stop, advance)
        if not complete:
            log.info(
                "stopped with %s of %s on disk; the next run of %s continues",
                megabytes(summary.bytes_done),
                megabytes(plan.tile_bytes),
                describe(options),
            )
            return self._ended(EXIT_INTERRUPTED)

        job.set_phase("finish")
        with job.steps.step("finish"):
            facts = await asyncio.to_thread(finish, directory, plan)
        summary.file = facts.file
        log.info("the detail map is %s (%s)", directory / facts.file, megabytes(facts.size))
        return self._ended(0)

    def _ended(self, code: int) -> MapRun:
        summary = self.summary
        summary.status = _STATUSES[code].value
        summary.elapsed_seconds = round(time.monotonic() - self.started, 1)
        if self.prepared is not None:
            source = self.prepared.source
            summary.requests = source.requests
            summary.extra_bytes = source.bytes - summary.directory_bytes - summary.tile_bytes
        return MapRun(summary, code)


def _one_line(summary: MapSummary) -> str:
    """The summary in one line, for job.message."""
    choice = f"{summary.region}, {summary.detail}"
    if summary.status == "done":
        line = (
            f"{choice}: {megabytes(summary.size)}, {summary.tiles:,} tiles in {summary.file}; "
            f"{summary.requests} requests, {megabytes(summary.extra_bytes)} read along"
        )
    elif summary.status == "stopped":
        done = f"{megabytes(summary.bytes_done)} of {megabytes(summary.bytes_total)}"
        line = f"{choice}: stopped with {done} on disk; the next run continues"
    else:
        line = f"{choice}: {summary.message}"
    if summary.restart:
        line += f"; started over: {summary.restart}"
    return line

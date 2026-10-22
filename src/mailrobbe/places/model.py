"""What the places step, the API and the map runs share (D240 to D249).

The detail map (D245) comes in three levels of detail for one of the preset regions or the map's
current view. SIZE_HINTS are the sizes an extract of the Protomaps build of SIZE_HINTS_BUILD had
(the tiles of every zoom up to the level's, deduplicated); a run knows the exact size of its own
source after its directories step. job.options and job.progress of kind map hold MapOptions and
MapProgress as JSON; the API serves them as they are.
"""

from typing import Literal

from pydantic import BaseModel

from mailrobbe.jobs import RunProgress

# (west, south, east, north) in decimal degrees
BBox = tuple[float, float, float, float]

MapRegionKey = Literal["de", "at", "ch", "dach", "view"]  # view: the map's current view
MapDetailKey = Literal["overview", "streets", "full"]

REGIONS: dict[MapRegionKey, BBox] = {
    "de": (5.87, 47.27, 15.04, 55.06),
    "at": (9.53, 46.37, 17.16, 49.02),
    "ch": (5.96, 45.82, 10.49, 47.81),  # with Liechtenstein
    "dach": (5.87, 45.82, 17.16, 55.06),
}
# The highest zoom whose tiles a level takes; the map shows them enlarged beyond it. Zoom 14 is
# the first with every street, zoom 15 adds buildings and points of interest (checked on the
# tiles of Berlin, build 20261022).
MAX_ZOOMS: dict[MapDetailKey, int] = {"overview": 10, "streets": 14, "full": 15}

SIZE_HINTS_BUILD = "20261022"
SIZE_HINTS: dict[MapRegionKey, dict[MapDetailKey, int]] = {
    "de": {"overview": 157_009_636, "streets": 3_455_493_653, "full": 7_193_796_917},
    "at": {"overview": 56_361_660, "streets": 1_059_965_464, "full": 2_032_236_869},
    "ch": {"overview": 29_545_663, "streets": 496_259_929, "full": 997_925_180},
    "dach": {"overview": 226_384_565, "streets": 4_881_325_229, "full": 9_982_947_073},
}

PROTOMAPS = "protomaps"  # MAILROBBE_MAP_SOURCE: the newest daily build
MAP_OFF = "off"  # MAILROBBE_MAP_SOURCE: no download is offered

MapPhase = Literal["plan", "download", "finish"]
# plan: the source's header and the leaf directories over the region (directories); download:
# the tiles (tiles, in bytes); finish: the new file's directories, then the file in place.
MAP_STEPS = ("directories", "tiles", "finish")


class MapOptions(BaseModel):
    """What a map run downloads (job.options of kind map)."""

    region: MapRegionKey
    detail: MapDetailKey
    bbox: BBox  # the region's, or the view's for region view
    max_zoom: int
    source: str  # MAILROBBE_MAP_SOURCE when the run started: protomaps or an https URL


class MapProgress(RunProgress):
    """Live figures of a map run (job.progress of kind map); done, total, rate and remaining
    time of the download are its steps' (D110)."""

    source_url: str | None = None  # the PMTiles file read, once known
    build: str | None = None  # the Protomaps build, e.g. "20261022"; None for another source
    tiles: int = 0  # tiles the new file holds, once the directories are read
    bytes_total: int | None = None  # bytes of tiles to download, once known
    bytes_done: int = 0  # of those, on disk (continued ones included)
    continued_bytes: int = 0  # downloaded by an earlier run this one continued (D246)

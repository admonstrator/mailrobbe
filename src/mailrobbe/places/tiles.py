"""The detail map (D245, D246): the tiles of a region, taken from a PMTiles file on the internet by
range requests, in one PMTiles file in MAILROBBE_MAP_DIR.

    source     MAILROBBE_MAP_SOURCE: protomaps, the newest complete build that builds.json
               lists, or the https URL of another PMTiles v3 file. Every request names Mailrobbe
               in its User-Agent and is tried again RETRIES times with growing pauses; every
               answer must come from the same file (ETag, Last-Modified, size) as the first.
    plan       the source's header and metadata, and of its leaf directories only those over the
               region; every tile of zoom 0 to the detail's that intersects the bbox, its data
               deduplicated by source offset and laid out in tile id order (clustered, as the
               spec defines it); the new file's header and directories; the byte ranges to
               fetch, joined into requests of up to REQUEST_BYTES across the narrowest gaps
               between them, which together stay within EXTRA_SHARE of the tile bytes
    download   the requests into the part file, each piece of an answer where it lands, a few
               at a time; which ones are on disk is kept beside it every few seconds, so a later
               run with the same options and the same source file continues there
    finish     header and directories written before the tiles, the file renamed into place as
               the only detail map, its facts in detail.json; the previous map and the plan go

Files in map_dir: osm-<region>-<detail>-<time>.pmtiles and detail.json (the detail map), and of
a download not finished yet download.part (the new file, its tiles where they land),
download.plan.json (the plan: Plan) and download.json (its facts and what is done: Partial).

The format (github.com/protomaps/PMTiles, spec/v3/spec.md): a header of 127 bytes; the root
directory within the first 16 KiB; metadata JSON, leaf directories and tile data where the
header says. A directory lists entries (tile id, offset, length, run length; run length 0 is a
leaf directory), as varints, compressed as a whole. A tile id counts the tiles of every lower
zoom, then the tile's place on the Hilbert curve of its zoom. The tiles' bytes are copied as
they are, compressed as the source compresses them.
"""

import asyncio
import base64
import bisect
import contextlib
import dataclasses
import gzip
import hashlib
import http.client
import itertools
import json
import logging
import math
import os
import re
import shutil
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from array import array
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, ValidationError

from mailrobbe.places.model import (
    MAP_OFF,
    MAX_ZOOMS,
    PROTOMAPS,
    REGIONS,
    BBox,
    MapDetailKey,
    MapOptions,
    MapRegionKey,
)

log = logging.getLogger(__name__)

USER_AGENT = "Mailrobbe (+https://github.com/admonstrator/mailrobbe)"  # 403 without one
BUILDS_URL = "https://build-metadata.protomaps.dev/builds.json"
BUILDS_BASE = "https://build.protomaps.com/"
BUILDS_LIMIT = 4 * 1024**2  # bytes of builds.json read at most
RETRIES = 3  # a failed request is tried again this often,
RETRY_PAUSES = (2.0, 4.0, 8.0)  # after these pauses (seconds)
REQUEST_BYTES = 16 * 1024**2  # one request fetches at most this much
# A request fetches the gaps of up to GAP_LIMIT between the pieces it joins, the narrowest first,
# as long as they stay within EXTRA_SHARE of the tile bytes (gap_limit; measured on the build of
# 2026-10-22: DACH in full detail 822 requests and 2.1 % more bytes, Switzerland's streets 135
# and 4.9 %); between directories up to DIRECTORY_GAP.
GAP_LIMIT = 1024**2
EXTRA_SHARE = 0.05
DIRECTORY_GAP = 256 * 1024
PARALLEL = 4  # requests in flight during the download
STATE_SECONDS = 2.0  # how often the part file is synced and download.json written
RESERVE = 0.05  # free space beyond the bytes still to write that a download needs

MAGIC = b"PMTiles"
VERSION = 3
HEADER_LENGTH = 127
ROOT_LIMIT = 16_384  # header and root directory together (spec 2)
ROOT_ENTRIES = 16_384  # a new file with more entries has leaf directories
LEAF_ENTRIES = 4096  # entries per leaf directory a new file starts with
DIRECTORY_LIMIT = 64 * 1024**2  # bytes of a directory or the metadata, compressed or not
TILE_LIMIT = 64 * 1024**2  # bytes of one tile
LEAF_DEPTH = 3  # levels of leaf directories followed below the root
NO_COMPRESSION, GZIP = 1, 2  # compression codes; brotli (3) and zstd (4) are not read
COMPRESSIONS = {0: "unknown", 1: "none", 2: "gzip", 3: "brotli", 4: "zstd"}
LATITUDE_LIMIT = 85.0511287798  # Web Mercator
PLAN_VERSION = 1

_HEADER = struct.Struct("<7sB11Q6B4iB2i")
_BUILD = re.compile(r"(\d{8})\.pmtiles")


class SourceError(Exception):
    """The source cannot be used: no answer, no range requests, no PMTiles v3 file, or one this
    module cannot read; the message says why (English)."""


class SourceGone(SourceError):
    """The source answers 404 or 410: a daily build deleted, a URL that went away."""


class SourceChanged(SourceError):
    """An answer came from another file than the first one (ETag, Last-Modified or size)."""


class NotEnoughSpace(Exception):
    """map_dir has less free space than a download still needs and RESERVE more."""


# The format ------------------------------------------------------------------------------------


class Entry(NamedTuple):
    """A directory entry; run_length 0: a leaf directory, its offset in the leaf section."""

    tile_id: int
    offset: int
    length: int
    run_length: int


@dataclass(frozen=True, slots=True)
class Header:
    """The 127 bytes at the start of a PMTiles v3 file."""

    root_offset: int
    root_length: int
    metadata_offset: int
    metadata_length: int
    leaf_offset: int
    leaf_length: int
    tile_data_offset: int
    tile_data_length: int
    addressed_tiles: int
    tile_entries: int
    tile_contents: int
    clustered: bool
    internal_compression: int
    tile_compression: int
    tile_type: int
    min_zoom: int
    max_zoom: int
    bounds: BBox  # west, south, east, north
    center_zoom: int
    center: tuple[float, float]  # longitude, latitude

    def to_bytes(self) -> bytes:
        west, south, east, north = (_e7(value) for value in self.bounds)
        return _HEADER.pack(
            MAGIC,
            VERSION,
            self.root_offset,
            self.root_length,
            self.metadata_offset,
            self.metadata_length,
            self.leaf_offset,
            self.leaf_length,
            self.tile_data_offset,
            self.tile_data_length,
            self.addressed_tiles,
            self.tile_entries,
            self.tile_contents,
            int(self.clustered),
            self.internal_compression,
            self.tile_compression,
            self.tile_type,
            self.min_zoom,
            self.max_zoom,
            west,
            south,
            east,
            north,
            self.center_zoom,
            _e7(self.center[0]),
            _e7(self.center[1]),
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "Header":
        """SourceError for anything but a PMTiles v3 header."""
        if len(data) < HEADER_LENGTH or data[:7] != MAGIC:
            raise SourceError("the source is no PMTiles file")
        fields = _HEADER.unpack(data[:HEADER_LENGTH])
        if fields[1] != VERSION:
            raise SourceError(f"the source is a PMTiles file of version {fields[1]}, not 3")
        west, south, east, north = (value / 1e7 for value in fields[19:23])
        values = [
            *fields[2:13],  # the sections and the counts
            fields[13] == 1,  # clustered
            *fields[14:19],  # compressions, tile type, zooms
            (west, south, east, north),
            fields[23],
            (fields[24] / 1e7, fields[25] / 1e7),
        ]
        names = [field.name for field in dataclasses.fields(cls)]
        return cls(**dict(zip(names, values, strict=True)))


def _e7(degrees: float) -> int:
    return round(degrees * 10_000_000)


def _write_varint(out: bytearray, value: int) -> None:
    while value > 0x7F:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)


def _varints(data: bytes) -> list[int]:
    values = []
    value = shift = 0
    for byte in data:
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
        else:
            values.append(value)
            value = shift = 0
    if shift:
        raise SourceError("a directory of the source ends inside a number")
    return values


def encode_directory(entries: Sequence[Entry]) -> bytes:
    """The entries as a directory, before compression (spec 4.2)."""
    out = bytearray()
    _write_varint(out, len(entries))
    last = 0
    for entry in entries:
        _write_varint(out, entry.tile_id - last)
        last = entry.tile_id
    for entry in entries:
        _write_varint(out, entry.run_length)
    for entry in entries:
        _write_varint(out, entry.length)
    following = 0
    for index, entry in enumerate(entries):
        _write_varint(out, 0 if index and entry.offset == following else entry.offset + 1)
        following = entry.offset + entry.length
    return bytes(out)


def decode_directory(data: bytes) -> list[Entry]:
    """A directory after decompression (spec 4.3); SourceError when it is malformed."""
    values = _varints(data)
    count = values[0] if values else 0
    if not count or len(values) != 1 + 4 * count:
        raise SourceError("a directory of the source is malformed")
    tile_id = 0
    entries = []
    following = 0
    runs, lengths, offsets = 1 + count, 1 + 2 * count, 1 + 3 * count
    for index in range(count):
        tile_id += values[1 + index]
        raw = values[offsets + index]
        if raw == 0 and index == 0:
            raise SourceError("a directory of the source is malformed")
        offset = following if raw == 0 else raw - 1
        length = values[lengths + index]
        entries.append(Entry(tile_id, offset, length, values[runs + index]))
        following = offset + length
    return entries


def compress(data: bytes, compression: int) -> bytes:
    if compression == GZIP:
        return gzip.compress(data, mtime=0)
    if compression == NO_COMPRESSION:
        return data
    raise SourceError(f"the source compresses its directories with {_name(compression)}")


def decompress(data: bytes, compression: int) -> bytes:
    """At most DIRECTORY_LIMIT bytes; SourceError for more, or for data it cannot read."""
    if compression == NO_COMPRESSION:
        return data
    if compression != GZIP:
        raise SourceError(f"the source compresses its directories with {_name(compression)}")
    inflate = zlib.decompressobj(wbits=31)
    try:
        result = inflate.decompress(data, DIRECTORY_LIMIT)
    except zlib.error as error:
        raise SourceError(f"a directory of the source cannot be decompressed: {error}") from None
    if inflate.unconsumed_tail:
        raise SourceError("a directory of the source is larger than 64 MiB")
    return result


def _name(compression: int) -> str:
    return COMPRESSIONS.get(compression, f"compression {compression}")


class Entries:
    """Tile entries as four arrays: 32 bytes an entry, where a tuple and its numbers take some
    180 (a download of DACH in full detail has 1.7 million)."""

    def __init__(self) -> None:
        self.ids = array("Q")
        self.offsets = array("Q")
        self.lengths = array("Q")
        self.runs = array("Q")

    def __len__(self) -> int:
        return len(self.ids)

    def add(self, tile_id: int, offset: int, length: int, run_length: int) -> None:
        self.ids.append(tile_id)
        self.offsets.append(offset)
        self.lengths.append(length)
        self.runs.append(run_length)

    def part(self, start: int, stop: int) -> list[Entry]:
        columns = (self.ids, self.offsets, self.lengths, self.runs)
        return list(map(Entry, *(column[start:stop] for column in columns)))


def build_directories(entries: Entries, compression: int) -> tuple[bytes, bytes]:
    """The root directory and the leaf directories (one section) of the entries, compressed: the
    root alone when it fits the first 16 KiB, else leaves of LEAF_ENTRIES, twice as many per
    leaf until the root of their pointers fits."""
    count = len(entries)
    if count <= ROOT_ENTRIES:
        root = compress(encode_directory(entries.part(0, count)), compression)
        if HEADER_LENGTH + len(root) <= ROOT_LIMIT:
            return root, b""
    size = LEAF_ENTRIES
    while True:
        leaves: list[bytes] = []
        pointers = []
        position = 0
        for start in range(0, count, size):
            leaf = compress(encode_directory(entries.part(start, start + size)), compression)
            pointers.append(Entry(entries.ids[start], position, len(leaf), 0))
            leaves.append(leaf)
            position += len(leaf)
        root = compress(encode_directory(pointers), compression)
        if HEADER_LENGTH + len(root) <= ROOT_LIMIT:
            return root, b"".join(leaves)
        size *= 2


# Tile ids --------------------------------------------------------------------------------------


def tile_id(z: int, x: int, y: int) -> int:
    """The PMTiles id of tile z/x/y."""
    if not (0 <= z <= 31 and 0 <= x < 1 << z and 0 <= y < 1 << z):
        raise ValueError(f"no tile {z}/{x}/{y}")
    position = 0
    for level in range(z - 1, -1, -1):
        size = 1 << level
        right, low = int(x & size > 0), int(y & size > 0)
        position += size * size * ((3 * right) ^ low)
        x, y = x & (size - 1), y & (size - 1)
        if not low:
            if right:
                x, y = size - 1 - x, size - 1 - y
            x, y = y, x
    return _first_id(z) + position


def _first_id(z: int) -> int:
    """The id of the first tile of zoom z: the tiles of every lower zoom."""
    return ((1 << 2 * z) - 1) // 3


def tile_box(bbox: BBox, z: int) -> tuple[int, int, int, int]:
    """The tiles of zoom z intersecting bbox: first and last column, first and last row."""
    west, south, east, north = bbox
    count = 1 << z

    def column(longitude: float) -> int:
        return min(count - 1, max(0, math.floor((longitude + 180.0) / 360.0 * count)))

    def row(latitude: float) -> int:
        latitude = math.radians(max(-LATITUDE_LIMIT, min(LATITUDE_LIMIT, latitude)))
        y = (1.0 - math.asinh(math.tan(latitude)) / math.pi) / 2.0 * count
        return min(count - 1, max(0, math.floor(y)))

    return column(west), row(north), column(east), row(south)


def tile_ranges(bbox: BBox, min_zoom: int, max_zoom: int) -> list[tuple[int, int]]:
    """The ids of every tile of these zooms intersecting bbox, as sorted ranges [start, stop).

    The tiles of an aligned square of 2^k by 2^k tiles have consecutive ids on the Hilbert curve,
    so the squares wholly inside the box give whole ranges and only its edges are split further.
    """
    found: list[tuple[int, int]] = []
    for z in range(min_zoom, max_zoom + 1):
        _cover(z, z, 0, 0, tile_box(bbox, z), found)
    found.sort()
    ranges: list[tuple[int, int]] = []
    for start, stop in found:
        if ranges and ranges[-1][1] == start:
            ranges[-1] = (ranges[-1][0], stop)
        else:
            ranges.append((start, stop))
    return ranges


def _cover(
    z: int, level: int, x: int, y: int, box: tuple[int, int, int, int], found: list[tuple[int, int]]
) -> None:
    """Add the ids of the square of 2^level tiles at x, y (zoom z) that lie in box."""
    first_x, first_y, last_x, last_y = box
    size = 1 << level
    if x > last_x or y > last_y or x + size <= first_x or y + size <= first_y:
        return
    if first_x <= x and x + size - 1 <= last_x and first_y <= y and y + size - 1 <= last_y:
        block = size * size
        base = _first_id(z)
        start = base + (tile_id(z, x, y) - base) // block * block
        found.append((start, start + block))
        return
    half = size >> 1
    for dx in (0, half):
        for dy in (0, half):
            _cover(z, level - 1, x + dx, y + dy, box, found)


def check_bbox(bbox: Sequence[float]) -> BBox:
    """west, south, east, north as given; ValueError unless finite, in range and with an area."""
    if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
        raise ValueError("a bbox is four finite numbers: west, south, east, north")
    west, south, east, north = (float(value) for value in bbox)
    if not (-180 <= west < east <= 180):
        raise ValueError("the bbox needs -180 <= west < east <= 180")
    if not (-90 <= south < north <= 90):
        raise ValueError("the bbox needs -90 <= south < north <= 90")
    return west, south, east, north


def map_options(
    region: MapRegionKey, detail: MapDetailKey, bbox: Sequence[float] | None, source: str
) -> MapOptions:
    """What a download of region and detail from the source setting takes; ValueError for a
    bbox given with a preset region, or one missing or unusable with region view."""
    if region == "view":
        if bbox is None:
            raise ValueError("region view needs a bbox")
        box = check_bbox(bbox)
    elif bbox is not None:
        raise ValueError(f"region {region} takes no bbox")
    else:
        box = REGIONS[region]
    return MapOptions(
        region=region, detail=detail, bbox=box, max_zoom=MAX_ZOOMS[detail], source=source
    )


# The source ------------------------------------------------------------------------------------


def source_setting(value: str) -> str | None:
    """MAILROBBE_MAP_SOURCE: protomaps or the URL; None when off. ValueError for anything else.

    An http URL is taken for a loopback host only (tests, a mirror on this machine)."""
    value = value.strip()
    if value.lower() == MAP_OFF:
        return None
    if value.lower() == PROTOMAPS:
        return PROTOMAPS
    parts = urllib.parse.urlsplit(value)
    if parts.hostname and (parts.scheme == "https" or (parts.scheme == "http" and _local(parts))):
        return value
    raise ValueError(
        f"MAILROBBE_MAP_SOURCE must be {PROTOMAPS}, {MAP_OFF} or an https URL, not {value!r}"
    )


def _local(parts: urllib.parse.SplitResult) -> bool:
    return parts.hostname in ("localhost", "127.0.0.1", "::1")


def source_host(setting: str) -> str:
    """The host a download of this source setting asks."""
    url = BUILDS_BASE if setting == PROTOMAPS else setting
    return urllib.parse.urlsplit(url).hostname or url


@dataclass(frozen=True, slots=True)
class Identity:
    """Which file the answers come from."""

    etag: str | None
    last_modified: str | None
    size: int


class _Retry(Exception):
    """A request that may succeed when tried again; the message says what went wrong."""


class Source:
    """One PMTiles file read by range requests (urllib, with the environment's proxy settings).

    The first answer fixes the file's identity, or the one given when a stopped download is
    continued; an answer from another file raises SourceChanged. Safe to use from several
    threads; requests and bytes count every answer read.
    """

    def __init__(
        self, url: str, build: str | None, timeout: float, identity: Identity | None = None
    ) -> None:
        self.url = url
        self.build = build
        self.timeout = timeout
        self.identity = identity
        self.requests = 0
        self.bytes = 0
        self._lock = threading.Lock()

    def read(self, offset: int, length: int) -> bytes:
        """Bytes offset to offset + length of the file; a short or wrong answer is fetched
        again, RETRIES times with growing pauses, then SourceError."""
        return _retried(lambda: self._read(offset, length))

    def _read(self, offset: int, length: int) -> bytes:
        headers = {"User-Agent": USER_AGENT, "Range": f"bytes={offset}-{offset + length - 1}"}
        request = urllib.request.Request(self.url, headers=headers)
        with _answer(request, self.timeout) as response:
            if response.status != 206:
                raise SourceError(
                    f"the source answers HTTP {response.status} instead of a range (206)"
                )
            identity = self._identity(response.headers, offset, length)
            data = response.read(length + 1)
        with self._lock:
            self.requests += 1
            self.bytes += len(data)
            if self.identity is None:
                self.identity = identity
            elif not _same(self.identity, identity):
                raise SourceChanged(f"the source file {self.url} changed")
        if len(data) != length:
            raise _Retry(f"{len(data)} bytes instead of {length} at {offset}")
        return data

    def _identity(self, headers: Message, offset: int, length: int) -> Identity:
        found = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", headers.get("Content-Range", "").strip())
        if found is None:
            raise _Retry("an answer without a usable Content-Range")
        first, last, size = (int(value) for value in found.groups())
        if (first, last) != (offset, offset + length - 1):
            if last < offset + length - 1 and last == size - 1:
                raise SourceError(
                    f"bytes {offset} to {offset + length} are beyond the source's end"
                )
            raise _Retry(f"bytes {first}-{last} instead of {offset}-{offset + length - 1}")
        return Identity(headers.get("ETag"), headers.get("Last-Modified"), size)


def _same(known: Identity, answer: Identity) -> bool:
    if known.size != answer.size:
        return False
    if known.etag and answer.etag:
        return known.etag == answer.etag
    return known.last_modified == answer.last_modified


@contextlib.contextmanager
def _answer(request: urllib.request.Request, timeout: float) -> Iterator[http.client.HTTPResponse]:
    """The response to a request; SourceGone for 404 and 410, _Retry for what may pass (5xx,
    408, 429, no connection, a timeout), SourceError for any other refusal."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield response
    except urllib.error.HTTPError as error:
        if error.code in (404, 410):
            raise SourceGone(f"the source {request.full_url} is gone (HTTP {error.code})") from None
        if error.code >= 500 or error.code in (408, 429):
            raise _Retry(f"HTTP {error.code}") from None
        raise SourceError(f"the source {request.full_url} answers HTTP {error.code}") from None
    except (TimeoutError, urllib.error.URLError, OSError, http.client.HTTPException) as error:
        reason = getattr(error, "reason", error)
        if isinstance(reason, TimeoutError):
            raise _Retry(f"no answer within {timeout:g} s") from None
        raise _Retry(f"{type(reason).__name__}: {reason}") from None


def _retried[Result](attempt: Callable[[], Result]) -> Result:
    for pause in (*RETRY_PAUSES[:RETRIES], None):
        try:
            return attempt()
        except _Retry as error:
            if pause is None:
                raise SourceError(f"{error} (tried {RETRIES + 1} times)") from None
            log.warning("map source: %s; trying again in %g s", error, pause)
            time.sleep(pause)
    raise AssertionError("unreachable")


def newest_build(timeout: float) -> tuple[str, str]:
    """The URL and build ("20261022") of the newest complete daily build of Protomaps."""

    def fetch() -> bytes:
        request = urllib.request.Request(BUILDS_URL, headers={"User-Agent": USER_AGENT})
        with _answer(request, timeout) as response:
            return response.read(BUILDS_LIMIT)

    try:
        builds = json.loads(_retried(fetch))
    except ValueError as error:
        raise SourceError(f"{BUILDS_URL} is no JSON: {error}") from None
    complete = [
        found.group(1)
        for build in (builds if isinstance(builds, list) else [])
        if isinstance(build, dict)
        and isinstance(build.get("key"), str)
        and (found := _BUILD.fullmatch(build["key"]))
        and isinstance(build.get("size"), int)
        and build["size"] > 0
        and isinstance(build.get("uploaded"), str)
    ]
    if not complete:
        raise SourceError(f"{BUILDS_URL} lists no complete build")
    newest = max(complete)
    return f"{BUILDS_BASE}{newest}.pmtiles", newest


def open_source(setting: str, timeout: float) -> Source:
    """The file a new download of this source setting reads."""
    if setting == PROTOMAPS:
        url, build = newest_build(timeout)
        return Source(url, build, timeout)
    return Source(setting, None, timeout)


def read_spans(source: Source, spans: Sequence[tuple[int, int]]) -> dict[int, bytes]:
    """The bytes of each (offset, length) of the file by its offset; spans fetched together as
    tiles are, but never split."""
    found: dict[int, bytes] = {}
    group: list[tuple[int, int]] = []

    def fetch() -> None:
        start = group[0][0]
        data = source.read(start, max(offset + length for offset, length in group) - start)
        for offset, length in group:
            found[offset] = data[offset - start : offset - start + length]

    end = 0
    for offset, length in sorted(set(spans)):
        if (
            group
            and offset - end <= DIRECTORY_GAP
            and offset + length - group[0][0] <= REQUEST_BYTES
        ):
            group.append((offset, length))
        else:
            if group:
                fetch()
            group = [(offset, length)]
        end = max(end, offset + length) if len(group) > 1 else offset + length
    if group:
        fetch()
    return found


def gap_limit(pieces: Sequence[tuple[int, int, int]]) -> int:
    """The widest gap between two pieces (source offset, target, length) that a request fetches
    along: up to GAP_LIMIT, the narrowest first, as long as together they stay within
    EXTRA_SHARE of the pieces' bytes."""
    ordered = sorted(pieces)
    gaps = sorted(
        max(0, later[0] - earlier[0] - earlier[2]) for earlier, later in itertools.pairwise(ordered)
    )
    budget = EXTRA_SHARE * sum(piece[2] for piece in pieces)
    widest = 0
    for gap in gaps:
        if gap > GAP_LIMIT:
            return GAP_LIMIT
        budget -= gap
        if budget < 0:
            return gap - 1  # every narrower gap fits the budget
        widest = gap
    return widest


def join_fetches(pieces: Sequence[tuple[int, int, int]], gap: int) -> list[list[int]]:
    """Pieces (source offset, target, length) as requests [offset, length, start in the answer,
    length, target, ...]: sorted by offset, joined across gaps of up to gap bytes while a request
    stays within REQUEST_BYTES; a longer piece is split."""
    fetches: list[list[int]] = []
    current: list[int] = []
    end = 0
    for offset, target, length in sorted(pieces):
        while length > 0:
            if current and offset - end <= gap and offset - current[0] < REQUEST_BYTES:
                take = min(length, current[0] + REQUEST_BYTES - offset)
            else:
                current = [offset, 0]
                fetches.append(current)
                end = offset
                take = min(length, REQUEST_BYTES)
            current += (offset - current[0], take, target)
            end = max(end, offset + take)
            current[1] = end - current[0]
            offset, target, length = offset + take, target + take, length - take
    return fetches


# The plan --------------------------------------------------------------------------------------


class Plan(BaseModel):
    """What a download fetches and where it writes it (download.plan.json)."""

    version: int = PLAN_VERSION
    key: str  # SHA-256 of the rest; download.json names the plan it belongs to
    options: MapOptions
    source_url: str
    build: str | None
    etag: str | None
    last_modified: str | None
    source_size: int
    min_zoom: int
    max_zoom: int
    tiles: int  # addressed tiles of the new file
    tile_entries: int
    tile_contents: int
    tile_bytes: int  # its tile data, the bytes to download
    fetch_bytes: int  # what the requests fetch: the tile data and the gaps fetched along
    file_size: int
    front: str  # base64: header, root directory, metadata, leaf directories (finish writes them)
    # Each [offset in the source, length, then per piece: start in the answer, length, offset in
    # the new file]. Sorted by offset.
    fetches: list[list[int]]

    def identity(self) -> Identity:
        return Identity(self.etag, self.last_modified, self.source_size)


class _Found(NamedTuple):
    """Tiles of the region in the source: the ids first to first + run, one content."""

    first: int
    run: int
    offset: int  # in the source's tile data
    length: int


class _Placed:
    """Where each content of the source lands in the new file, by its source offset. A clustered
    source gives the new ones in ascending order (two arrays, searched by bisection); one first
    met out of that order goes in a dict."""

    def __init__(self) -> None:
        self.offsets = array("Q")
        self.targets = array("Q")
        self.others: dict[int, int] = {}

    def __len__(self) -> int:
        return len(self.offsets) + len(self.others)

    def get(self, offset: int) -> int | None:
        offsets = self.offsets
        if offsets and offset <= offsets[-1]:
            index = bisect.bisect_left(offsets, offset)
            if offsets[index] == offset:
                return self.targets[index]
        return self.others.get(offset)

    def add(self, offset: int, target: int) -> None:
        if not self.offsets or offset > self.offsets[-1]:
            self.offsets.append(offset)
            self.targets.append(target)
        else:
            self.others[offset] = target


def plan_extract(
    source: Source, options: MapOptions, stopped: Callable[[], bool] = lambda: False
) -> Plan | None:
    """The plan of a download of options from source; None when stopped meanwhile."""
    header = Header.from_bytes(source.read(0, HEADER_LENGTH))
    assert source.identity is not None
    _check_header(header, source.identity.size)
    spans = [(header.root_offset, header.root_length)]
    spans.append((header.metadata_offset, header.metadata_length))
    parts = read_spans(source, spans)
    compression = header.internal_compression
    metadata = parts[header.metadata_offset]
    try:
        if not isinstance(json.loads(decompress(metadata, compression)), dict):
            raise ValueError("no object")
    except ValueError as error:
        raise SourceError(f"the source's metadata is no JSON object: {error}") from None
    root = decode_directory(decompress(parts[header.root_offset], compression))
    min_zoom = header.min_zoom
    max_zoom = min(options.max_zoom, header.max_zoom)
    ranges = tile_ranges(options.bbox, min_zoom, max_zoom)

    entries = Entries()
    placed = _Placed()
    pieces: list[list[int]] = []  # [source offset, new offset, length], joined when both go on
    position = addressed = 0
    for found in _walk(source, header, root, 1 << 63, ranges, stopped, 0):
        target = placed.get(found.offset)
        if target is None:
            target = position
            placed.add(found.offset, target)
            last = pieces[-1] if pieces else None
            if last and last[0] + last[2] == found.offset and last[1] + last[2] == position:
                last[2] += found.length
            else:
                pieces.append([found.offset, position, found.length])
            position += found.length
        entries.add(found.first, target, found.length, found.run)
        addressed += found.run
    if stopped():
        return None
    if not entries:
        raise SourceError("the source has no tiles in the region")

    root_bytes, leaves = build_directories(entries, compression)
    metadata_offset = HEADER_LENGTH + len(root_bytes)
    leaf_offset = metadata_offset + len(metadata)
    tile_data_offset = leaf_offset + len(leaves)
    west, south, east, north = options.bbox
    new = Header(
        root_offset=HEADER_LENGTH,
        root_length=len(root_bytes),
        metadata_offset=metadata_offset,
        metadata_length=len(metadata),
        leaf_offset=leaf_offset,
        leaf_length=len(leaves),
        tile_data_offset=tile_data_offset,
        tile_data_length=position,
        addressed_tiles=addressed,
        tile_entries=len(entries),
        tile_contents=len(placed),
        clustered=True,
        internal_compression=compression,
        tile_compression=header.tile_compression,
        tile_type=header.tile_type,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        bounds=options.bbox,
        center_zoom=max(min_zoom, min(max_zoom, int(math.log2(360.0 / (east - west))))),
        center=((west + east) / 2, (south + north) / 2),
    )
    front = new.to_bytes() + root_bytes + metadata + leaves
    absolute = [
        (offset + header.tile_data_offset, target + tile_data_offset, length)
        for offset, target, length in pieces
    ]
    fetches = join_fetches(absolute, gap_limit(absolute))
    fields = {
        "options": options,
        "source_url": source.url,
        "build": source.build,
        "etag": source.identity.etag,
        "last_modified": source.identity.last_modified,
        "source_size": source.identity.size,
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "tiles": addressed,
        "tile_entries": len(entries),
        "tile_contents": len(placed),
        "tile_bytes": position,
        "fetch_bytes": sum(fetch[1] for fetch in fetches),
        "file_size": tile_data_offset + position,
        "front": base64.b64encode(front).decode(),
        "fetches": fetches,
    }
    key = hashlib.sha256(Plan.model_validate(fields | {"key": ""}).model_dump_json().encode())
    return Plan.model_validate(fields | {"key": key.hexdigest()})


def _check_header(header: Header, size: int) -> None:
    """SourceError for a header this module cannot read or whose sections leave the file."""
    if header.internal_compression not in (NO_COMPRESSION, GZIP):
        raise SourceError(
            f"the source compresses its directories with {_name(header.internal_compression)}"
        )
    sections = (
        (header.root_offset, header.root_length),
        (header.metadata_offset, header.metadata_length),
        (header.leaf_offset, header.leaf_length),
        (header.tile_data_offset, header.tile_data_length),
    )
    if any(offset + length > size for offset, length in sections):
        raise SourceError("a section of the source lies beyond its end")
    if not 0 < header.root_length <= DIRECTORY_LIMIT or header.metadata_length > DIRECTORY_LIMIT:
        raise SourceError("the source's root directory or metadata has an unusable length")
    if header.min_zoom > header.max_zoom or header.max_zoom > 31:
        raise SourceError("the source's zoom levels are unusable")


def _walk(
    source: Source,
    header: Header,
    directory: list[Entry],
    end: int,
    ranges: Sequence[tuple[int, int]],
    stopped: Callable[[], bool],
    depth: int,
) -> Iterator[_Found]:
    """The region's tiles in this directory and its leaves, in tile id order; end: the first id
    after the directory's (the next entry of the directory above)."""
    matches = list(_matches(directory, end, ranges))
    leaves = {entry: last for entry, _, _, last in matches if not entry.run_length}
    if leaves and depth >= LEAF_DEPTH:
        raise SourceError("the source's leaf directories nest too deep")
    for entry in leaves:
        if entry.offset + entry.length > header.leaf_length or entry.length > DIRECTORY_LIMIT:
            raise SourceError("a leaf directory of the source lies beyond its section")
    spans = [(header.leaf_offset + entry.offset, entry.length) for entry in leaves]
    data = read_spans(source, spans) if spans and not stopped() else {}
    for entry, first, through, _ in matches:
        if stopped():
            return
        if entry.run_length:
            if not 0 < entry.length <= TILE_LIMIT or (
                entry.offset + entry.length > header.tile_data_length
            ):
                raise SourceError(f"the tile {first} of the source has an unusable place")
            yield _Found(first, through - first, entry.offset, entry.length)
        elif entry in leaves:  # a leaf meeting several ranges is walked once, for all of them
            compressed = data[header.leaf_offset + entry.offset]
            leaf = decode_directory(decompress(compressed, header.internal_compression))
            yield from _walk(source, header, leaf, leaves.pop(entry), ranges, stopped, depth + 1)


def _matches(
    directory: Sequence[Entry], end: int, ranges: Sequence[tuple[int, int]]
) -> Iterator[tuple[Entry, int, int, int]]:
    """The entries whose ids meet the ranges, in id order: (entry, first, through, last), the ids
    [first, through) of the entry in one range, and last the end of the entry's ids: of its run,
    or of a leaf up to the next entry (end after the last one)."""
    if not directory:
        return
    ids = [entry.tile_id for entry in directory]
    index = 0
    for start, stop in ranges:
        if start >= end:
            break
        index = max(index, bisect.bisect_right(ids, start) - 1)
        while index < len(directory) and ids[index] < stop:
            entry = directory[index]
            if entry.run_length:
                last = entry.tile_id + entry.run_length
            else:
                last = ids[index + 1] if index + 1 < len(ids) else end
            first, through = max(entry.tile_id, start), min(last, stop)
            if first < through:
                yield entry, first, through, last
            if last > stop:  # the entry goes on into the next range
                break
            index += 1


# The files in map_dir --------------------------------------------------------------------------

DETAIL_FILE = "detail.json"
PART_FILE = "download.part"
PLAN_FILE = "download.plan.json"
PARTIAL_FILE = "download.json"
MAP_FILES = "osm-*.pmtiles"
_MAP_NAME = re.compile(r"osm-[a-z]+-[a-z]+-\d{14}\.pmtiles")


class DetailFacts(BaseModel):
    """The detail map in map_dir (detail.json); the API serves it as DetailMap."""

    file: str  # its name in map_dir
    region: MapRegionKey
    bbox: BBox
    detail: MapDetailKey
    max_zoom: int
    build: str | None
    source_url: str
    size: int
    tiles: int
    downloaded_at: datetime


class Partial(BaseModel):
    """A download not finished yet (download.json): its plan's facts and which of the plan's
    requests are on disk."""

    plan: str  # Plan.key
    options: MapOptions
    source_url: str
    build: str | None
    tile_bytes: int
    done: list[int] = []  # indices of Plan.fetches whose pieces are on disk
    bytes_done: int = 0  # their tile bytes


def read_detail(directory: Path) -> DetailFacts | None:
    """The detail map's facts; None without one, or when its file is gone."""
    facts = _read_json(directory / DETAIL_FILE, DetailFacts)
    if facts is None or not _MAP_NAME.fullmatch(facts.file):
        return None
    return facts if (directory / facts.file).is_file() else None


def read_partial(directory: Path) -> Partial | None:
    """What download.json says of a download not finished yet; None without one."""
    return _read_json(directory / PARTIAL_FILE, Partial)


def _read_json[Model: BaseModel](path: Path, model: type[Model]) -> Model | None:
    try:
        return model.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return None
    except (OSError, ValidationError) as error:
        log.warning("cannot read %s: %s", path, " ".join(str(error).split())[:300])
        return None


def _write_json(path: Path, model: BaseModel) -> None:
    """Replace the file at once, so a reader never sees half of it."""
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as file:
        file.write(model.model_dump_json().encode())
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def delete_maps(directory: Path) -> list[str]:
    """Remove the detail map and a download not finished yet; the names of the files removed."""
    removed = []
    paths = [directory / name for name in (DETAIL_FILE, PART_FILE, PLAN_FILE, PARTIAL_FILE)]
    for path in [*sorted(directory.glob(MAP_FILES)), *paths]:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
            removed.append(path.name)
    return removed


def free_bytes(directory: Path) -> int | None:
    """Free space where the directory is or would be created; None when it cannot be told."""
    for path in (directory.absolute(), *directory.absolute().parents):
        if path.exists():
            try:
                return shutil.disk_usage(path).free
            except OSError:
                return None
    return None


def check_space(directory: Path, needed: int) -> None:
    """NotEnoughSpace unless the directory has needed bytes and RESERVE more free."""
    free = free_bytes(directory)
    if free is not None and free < needed * (1 + RESERVE):
        raise NotEnoughSpace(
            f"not enough free space in {directory}: the download needs {megabytes(needed)} "
            f"and {RESERVE:.0%} more, {megabytes(free)} are free"
        )


def megabytes(value: float) -> str:
    """Bytes as the run logs show them (jobrun's steps: MB of 1024 * 1024 bytes)."""
    return f"{value / 1024**2:,.1f} MB"


# The download ----------------------------------------------------------------------------------


@dataclass(slots=True)
class Prepared:
    """A download ready for its tiles."""

    source: Source
    plan: Plan
    partial: Partial
    continued: bool  # it continues a stopped download
    restart: str | None  # why a stopped download is not continued; None when there was none


def prepare(
    directory: Path,
    options: MapOptions,
    timeout: float,
    stopped: Callable[[], bool] = lambda: False,
) -> Prepared | None:
    """The stopped download of the same options (the source setting included) from the same,
    unchanged file, or a new plan from options.source with a fresh part file; None when stopped
    while planning."""
    found = _stopped_download(directory)
    restart = found if isinstance(found, str) else None
    if isinstance(found, tuple):
        stopped_plan, partial = found
        if stopped_plan.options != options:
            restart = f"the stopped download was of {describe(stopped_plan.options)}"
        else:
            url, build = stopped_plan.source_url, stopped_plan.build
            source = Source(url, build, timeout, stopped_plan.identity())
            try:
                source.read(0, HEADER_LENGTH)
            except SourceGone:
                restart = f"{f'the build {build}' if build else url} is gone from the source"
            except SourceChanged:
                restart = f"{url} changed since the download stopped"
            else:
                return Prepared(source, stopped_plan, partial, True, None)
    source = open_source(options.source, timeout)
    plan = plan_extract(source, options, stopped)
    if plan is None:
        return None
    return Prepared(source, plan, _start_download(directory, plan), False, restart)


def describe(options: MapOptions) -> str:
    """The region and detail, for messages: "de, streets" or "view 9.47,47.04,9.64,47.27, full"."""
    if options.region == "view":
        return f"view {','.join(f'{value:g}' for value in options.bbox)}, {options.detail}"
    return f"{options.region}, {options.detail}"


def _stopped_download(directory: Path) -> tuple[Plan, Partial] | str | None:
    """The plan and progress of a stopped download; why it cannot go on when its files do not
    fit together; None without one."""
    partial = read_partial(directory)
    if partial is None:
        return None
    plan = _read_json(directory / PLAN_FILE, Plan)
    if plan is None or plan.version != PLAN_VERSION or plan.key != partial.plan:
        return "the plan of the stopped download is missing or of another version"
    if not (directory / PART_FILE).is_file():
        return "the part file of the stopped download is missing"
    return plan, partial


def _start_download(directory: Path, plan: Plan) -> Partial:
    """An empty part file, the plan and its progress, in place of any earlier download."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in (PARTIAL_FILE, PLAN_FILE, PART_FILE):
        (directory / name).unlink(missing_ok=True)
    (directory / PART_FILE).write_bytes(b"")
    _write_json(directory / PLAN_FILE, plan)
    partial = Partial(
        plan=plan.key,
        options=plan.options,
        source_url=plan.source_url,
        build=plan.build,
        tile_bytes=plan.tile_bytes,
    )
    _write_json(directory / PARTIAL_FILE, partial)
    return partial


async def download(
    prepared: Prepared, directory: Path, stop: asyncio.Event, advance: Callable[[int], None]
) -> bool:
    """Fetch the plan's requests not on disk yet into the part file, PARALLEL at a time, until
    they all are or stop is set; whether they all are. advance gets the tile bytes of each
    request done. A request failing for good raises its SourceError once the requests in flight
    have ended; download.json keeps every request on disk, synced, also then."""
    plan, partial = prepared.plan, prepared.partial
    done = set(partial.done)
    waiting = [index for index in reversed(range(len(plan.fetches))) if index not in done]
    failure: Exception | None = None
    saved = time.monotonic()
    descriptor = os.open(directory / PART_FILE, os.O_WRONLY)

    async def save() -> None:
        state = partial.model_copy(update={"done": sorted(done)})
        await asyncio.to_thread(_save, descriptor, directory / PARTIAL_FILE, state)

    async def worker() -> None:
        nonlocal failure, saved
        while waiting and failure is None and not stop.is_set():
            index = waiting.pop()
            fetch = plan.fetches[index]
            try:
                written = await asyncio.to_thread(_fetch, prepared.source, fetch, descriptor)
            except Exception as error:
                failure = error
                waiting.append(index)
                return
            done.add(index)
            partial.bytes_done += written
            advance(written)
            if time.monotonic() - saved >= STATE_SECONDS:
                saved = time.monotonic()
                await save()

    try:
        await asyncio.gather(*(worker() for _ in range(PARALLEL)))
    finally:
        await save()
        os.close(descriptor)
    partial.done = sorted(done)
    if failure is not None:
        raise failure
    return not waiting


def _fetch(source: Source, fetch: list[int], descriptor: int) -> int:
    """One request into the part file; the tile bytes it wrote."""
    offset, length, *pieces = fetch
    data = memoryview(source.read(offset, length))
    written = 0
    for index in range(0, len(pieces), 3):
        start, size, target = pieces[index : index + 3]
        view = data[start : start + size]
        while view:
            count = os.pwrite(descriptor, view, target)
            view, target = view[count:], target + count
        written += size
    return written


def _save(descriptor: int, path: Path, partial: Partial) -> None:
    os.fsync(descriptor)  # the requests download.json names are on disk before it names them
    _write_json(path, partial)


def finish(directory: Path, plan: Plan, now: datetime | None = None) -> DetailFacts:
    """Header and directories into the part file, then the file in place as the only detail
    map; the previous map and the download's files are removed. SourceError when the part file
    does not hold what the plan says (the download's files are removed, the next run starts
    over)."""
    now = now or datetime.now(UTC)
    front = base64.b64decode(plan.front)
    part = directory / PART_FILE
    with part.open("r+b") as file:
        size = os.fstat(file.fileno()).st_size
        if size != plan.file_size:
            for name in (PARTIAL_FILE, PLAN_FILE, PART_FILE):
                (directory / name).unlink(missing_ok=True)
            raise SourceError(f"the part file has {size} bytes instead of {plan.file_size}")
        file.write(front)
        file.flush()
        os.fsync(file.fileno())
    options = plan.options
    name = f"osm-{options.region}-{options.detail}-{now:%Y%m%d%H%M%S}.pmtiles"
    os.replace(part, directory / name)
    facts = DetailFacts(
        file=name,
        region=options.region,
        bbox=options.bbox,
        detail=options.detail,
        max_zoom=plan.max_zoom,
        build=plan.build,
        source_url=plan.source_url,
        size=plan.file_size,
        tiles=plan.tiles,
        downloaded_at=now,
    )
    _write_json(directory / DETAIL_FILE, facts)
    for stale in directory.glob(MAP_FILES):
        if stale.name != name:
            stale.unlink(missing_ok=True)
    for leftover in (PLAN_FILE, PARTIAL_FILE):
        (directory / leftover).unlink(missing_ok=True)
    return facts

"""A PMTiles source for the map tests: synthetic files made with places.tiles' writer, served
from a thread on 127.0.0.1 with range requests, ETag and Last-Modified, and the faults a test
asks for (short answers, failing requests, files that change or go away).

    world()     a clustered PMTiles v3 file: every tile of zoom 0 to 4, and of zoom 5 to 8 over
                Central Europe (WORLD_AREA); a tile's bytes name it, but tiles whose x + y is
                divisible by 3 from zoom 5 on are "sea" and share one content, so there are
                repeated contents and runs. With leaves=True its directories have leaves.
    read_tiles  every tile of a PMTiles file as {tile id: bytes}, through the module's reader
"""

import gzip
import hashlib
import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mailrobbe.places import tiles
from mailrobbe.places.model import BBox

WORLD_AREA: BBox = (0.0, 40.0, 25.0, 60.0)
WORLD_MAX_ZOOM = 8
SEA = gzip.compress(b"sea" * 40, mtime=0)
METADATA = {
    "name": "test world",
    "attribution": "test data",
    "vector_layers": [{"id": "earth", "fields": {}}],
}


def tile_bytes(z: int, x: int, y: int) -> bytes:
    if z >= 5 and (x + y) % 3 == 0:
        return SEA
    return gzip.compress(f"{z}/{x}/{y} ".encode() * (5 + (x * 7 + y) % 40), mtime=0)


def world_tiles() -> dict[int, bytes]:
    found = {}
    for z in range(WORLD_MAX_ZOOM + 1):
        box = (0, 0, (1 << z) - 1, (1 << z) - 1) if z <= 4 else tiles.tile_box(WORLD_AREA, z)
        first_x, first_y, last_x, last_y = box
        for x in range(first_x, last_x + 1):
            for y in range(first_y, last_y + 1):
                found[tiles.tile_id(z, x, y)] = tile_bytes(z, x, y)
    return found


def pmtiles(contents: dict[int, bytes], bounds: BBox, max_zoom: int) -> bytes:
    """A clustered file of these tiles: contents in tile id order, a repeated one stored once,
    consecutive ids with the same content as one run."""
    entries: list[tiles.Entry] = []
    placed: dict[bytes, int] = {}
    data = bytearray()
    for tile_id in sorted(contents):
        content = contents[tile_id]
        offset = placed.get(content)
        if offset is None:
            offset = placed[content] = len(data)
            data += content
        last = entries[-1] if entries else None
        if last and last.offset == offset and last.tile_id + last.run_length == tile_id:
            entries[-1] = last._replace(run_length=last.run_length + 1)
        else:
            entries.append(tiles.Entry(tile_id, offset, len(content), 1))
    columns = tiles.Entries()
    for entry in entries:
        columns.add(*entry)
    root, leaves = tiles.build_directories(columns, tiles.GZIP)
    metadata = gzip.compress(json.dumps(METADATA).encode(), mtime=0)
    header = tiles.Header(
        root_offset=tiles.HEADER_LENGTH,
        root_length=len(root),
        metadata_offset=tiles.HEADER_LENGTH + len(root),
        metadata_length=len(metadata),
        leaf_offset=tiles.HEADER_LENGTH + len(root) + len(metadata),
        leaf_length=len(leaves),
        tile_data_offset=tiles.HEADER_LENGTH + len(root) + len(metadata) + len(leaves),
        tile_data_length=len(data),
        addressed_tiles=len(contents),
        tile_entries=len(entries),
        tile_contents=len(placed),
        clustered=True,
        internal_compression=tiles.GZIP,
        tile_compression=tiles.GZIP,
        tile_type=1,
        min_zoom=0,
        max_zoom=max_zoom,
        bounds=bounds,
        center_zoom=0,
        center=(0.0, 0.0),
    )
    return header.to_bytes() + root + metadata + leaves + bytes(data)


def world(monkeypatch: pytest.MonkeyPatch | None = None, *, leaves: bool = False) -> bytes:
    """The test world; with leaves, written with small directories (monkeypatch needed)."""
    if leaves:
        assert monkeypatch is not None
        with monkeypatch.context() as patch:
            patch.setattr(tiles, "ROOT_ENTRIES", 50)
            patch.setattr(tiles, "LEAF_ENTRIES", 64)
            return pmtiles(world_tiles(), (-180.0, -85.0, 180.0, 85.0), WORLD_MAX_ZOOM)
    return pmtiles(world_tiles(), (-180.0, -85.0, 180.0, 85.0), WORLD_MAX_ZOOM)


def read_tiles(data: bytes) -> dict[int, bytes]:
    """Every tile of a PMTiles file by its id, runs expanded."""
    header = tiles.Header.from_bytes(data)
    found: dict[int, bytes] = {}

    def walk(directory: bytes) -> None:
        for entry in tiles.decode_directory(
            tiles.decompress(directory, header.internal_compression)
        ):
            if entry.run_length:
                start = header.tile_data_offset + entry.offset
                for tile_id in range(entry.tile_id, entry.tile_id + entry.run_length):
                    found[tile_id] = data[start : start + entry.length]
            else:
                start = header.leaf_offset + entry.offset
                walk(data[start : start + entry.length])

    walk(data[header.root_offset : header.root_offset + header.root_length])
    return found


def directory_entries(data: bytes) -> list[tiles.Entry]:
    """The tile entries of a PMTiles file in tile id order, leaves resolved."""
    header = tiles.Header.from_bytes(data)
    entries: list[tiles.Entry] = []

    def walk(directory: bytes) -> None:
        for entry in tiles.decode_directory(
            tiles.decompress(directory, header.internal_compression)
        ):
            if entry.run_length:
                entries.append(entry)
            else:
                start = header.leaf_offset + entry.offset
                walk(data[start : start + entry.length])

    walk(data[header.root_offset : header.root_offset + header.root_length])
    return entries


@dataclass
class Request:
    path: str
    range: str | None
    user_agent: str | None


@dataclass
class MapSource:
    """What the server serves and how it misbehaves; tests change the fields as they go."""

    port: int = 0
    files: dict[str, bytes] = field(default_factory=dict)
    versions: dict[str, int] = field(default_factory=dict)  # bumped by put: ETag, Last-Modified
    requests: list[Request] = field(default_factory=list)
    short: int = 0  # the next answers to cut in half
    failing: int = 0  # the next requests to answer 503
    failing_from: int | None = None  # every range starting at or after this offset fails (503)
    whole: bool = False  # answer the whole file (200) to a range request
    lock: threading.Lock = field(default_factory=threading.Lock)

    def put(self, path: str, data: bytes) -> str:
        """Serve data at path, as a new version of the file; its URL."""
        self.files[path] = data
        self.versions[path] = self.versions.get(path, 0) + 1
        return self.url(path)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def ranges(self, path: str) -> list[str]:
        return [request.range or "" for request in self.requests if request.path == path]


class _Handler(BaseHTTPRequestHandler):
    server: "_Server"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        source = self.server.source
        path = self.path.split("?")[0]
        wanted = self.headers.get("Range")
        with source.lock:
            source.requests.append(Request(path, wanted, self.headers.get("User-Agent")))
            data = source.files.get(path)
            version = source.versions.get(path, 0)
            fail = source.failing > 0
            if fail:
                source.failing -= 1
        if data is None:
            self.send_error(404)
            return
        found = re.fullmatch(r"bytes=(\d+)-(\d+)", wanted or "")
        if fail or (
            found and source.failing_from is not None and int(found[1]) >= source.failing_from
        ):
            self.send_error(503)
            return
        headers = {
            "ETag": f'"{hashlib.sha256(data).hexdigest()[:16]}-{version}"',
            "Last-Modified": formatdate(1_700_000_000 + version, usegmt=True),
            "Accept-Ranges": "bytes",
        }
        if found is None or source.whole:
            self._send(200, data, headers)
            return
        first, last = int(found[1]), min(int(found[2]), len(data) - 1)
        if first >= len(data):
            self.send_error(416)
            return
        body = data[first : last + 1]
        headers["Content-Range"] = f"bytes {first}-{last}/{len(data)}"
        with source.lock:
            cut = source.short > 0
            if cut:
                source.short -= 1
        self._send(206, body, headers, sent=len(body) // 2 if cut else None)

    def _send(
        self, status: int, body: bytes, headers: dict[str, str], sent: int | None = None
    ) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body if sent is None else body[:sent])
        if sent is not None:
            self.close_connection = True


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    source: MapSource


@contextmanager
def serving(monkeypatch: pytest.MonkeyPatch) -> Iterator[MapSource]:
    """The server, for a test's fixture; builds.json and the Protomaps builds are asked of it,
    never of the internet, and retries do not pause."""
    server = _Server(("127.0.0.1", 0), _Handler)
    source = MapSource(port=server.server_address[1])
    server.source = source
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    monkeypatch.setattr(tiles, "BUILDS_URL", source.url("/builds.json"))
    monkeypatch.setattr(tiles, "BUILDS_BASE", source.url("/builds/"))
    monkeypatch.setattr(tiles, "RETRY_PAUSES", (0.0, 0.0, 0.0))
    try:
        yield source
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def builds_json(*keys: str, incomplete: tuple[str, ...] = ()) -> bytes:
    """builds.json as Protomaps writes it, with builds of these keys and some without a size."""
    builds = [
        {"key": key, "size": 1000, "uploaded": "2026-10-22T09:03:22.082Z", "version": "4.15.2"}
        for key in keys
    ]
    builds += [{"key": key, "uploaded": "2026-10-23T09:00:00Z"} for key in incomplete]
    return json.dumps(builds).encode()

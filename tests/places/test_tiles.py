"""The detail map's extract of a PMTiles file (D245, D246): the format, tile ids, the plan, the
download and its resumption.

Sources are synthetic files written with the module's own writer and served from a thread on
127.0.0.1 (map_source.py); nothing goes to the internet.
"""

import asyncio
import gzip
import itertools
import json
import random
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mailrobbe.places import tiles
from mailrobbe.places.model import MAX_ZOOMS, BBox, MapOptions
from mailrobbe.places.tiles import (
    GZIP,
    Entries,
    Entry,
    Header,
    NotEnoughSpace,
    SourceError,
    check_bbox,
    decode_directory,
    download,
    encode_directory,
    finish,
    map_options,
    prepare,
    read_detail,
    read_partial,
    tile_id,
    tile_ranges,
)
from tests.places.map_source import (
    METADATA,
    SEA,
    WORLD_MAX_ZOOM,
    MapSource,
    builds_json,
    directory_entries,
    read_tiles,
    serving,
    world,
    world_tiles,
)

SWISS: BBox = (5.96, 45.82, 10.49, 47.81)
TIMEOUT = 5.0
NOW = datetime(2026, 10, 22, 12, 30, tzinfo=UTC)


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> Iterator[MapSource]:
    with serving(monkeypatch) as served:
        yield served


def expected_tiles(bbox: BBox, max_zoom: int) -> dict[int, bytes]:
    """The tiles of the test world an extract of bbox up to max_zoom must hold."""
    every = world_tiles()
    found = {}
    for z in range(max_zoom + 1):
        first_x, first_y, last_x, last_y = tiles.tile_box(bbox, z)
        for x in range(first_x, last_x + 1):
            for y in range(first_y, last_y + 1):
                if (key := tile_id(z, x, y)) in every:
                    found[key] = every[key]
    return found


def view(url: str, bbox: BBox = SWISS, detail: str = "full") -> MapOptions:
    return map_options("view", detail, bbox, url)  # type: ignore[arg-type]


async def downloaded(directory: Path, options: MapOptions) -> tuple[tiles.Prepared, bytes]:
    """A whole download; the plan it took and the new file's bytes."""
    prepared = prepare(directory, options, TIMEOUT)
    assert prepared is not None
    assert await download(prepared, directory, asyncio.Event(), lambda count: None)
    facts = finish(directory, prepared.plan, NOW)
    return prepared, (directory / facts.file).read_bytes()


def tile_requests(source: MapSource, path: str, plan: tiles.Plan) -> list[str]:
    """The range requests of the download, those of the plan's fetches."""
    wanted = {f"bytes={fetch[0]}-{fetch[0] + fetch[1] - 1}" for fetch in plan.fetches}
    return [answer for answer in source.ranges(path) if answer in wanted]


# The format ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("zxy", "expected"),
    [
        ((0, 0, 0), 0),  # the spec's table
        ((1, 0, 0), 1),
        ((1, 0, 1), 2),
        ((1, 1, 1), 3),
        ((1, 1, 0), 4),
        ((2, 0, 0), 5),
        ((12, 3423, 1763), 19078479),
        ((3, 4, 2), 75),  # from the reference implementation (pmtiles 3.8.1)
        ((8, 134, 89), 77522),
        ((10, 539, 360), 1240282),
        ((14, 8625, 5770), 317512514),
        ((15, 17250, 11541), 1270050060),
    ],
)
def test_tile_ids_follow_the_hilbert_curves_of_the_spec(
    zxy: tuple[int, int, int], expected: int
) -> None:
    assert tile_id(*zxy) == expected


def test_a_tile_outside_its_zoom_has_no_id() -> None:
    for zxy in ((1, 2, 0), (3, 0, 8), (-1, 0, 0), (32, 0, 0)):
        with pytest.raises(ValueError):
            tile_id(*zxy)


def test_the_ranges_of_a_box_hold_exactly_its_tiles() -> None:
    rng = random.Random(20261022)
    for _ in range(150):
        west = rng.uniform(-180, 170)
        east = rng.uniform(west + 0.01, min(180, west + rng.choice([1, 10, 90])))
        south = rng.uniform(-85, 80)
        north = rng.uniform(south + 0.01, min(85, south + rng.choice([1, 10, 60])))
        max_zoom = rng.randrange(0, 8)
        ranges = tile_ranges((west, south, east, north), 0, max_zoom)
        assert ranges == sorted(ranges)
        assert all(a[1] < b[0] for a, b in itertools.pairwise(ranges))  # merged
        found = {key for start, stop in ranges for key in range(start, stop)}
        expected = set()
        for z in range(max_zoom + 1):
            first_x, first_y, last_x, last_y = tiles.tile_box((west, south, east, north), z)
            expected |= {
                tile_id(z, x, y)
                for x in range(first_x, last_x + 1)
                for y in range(first_y, last_y + 1)
            }
        assert found == expected


def test_a_box_names_the_tiles_it_touches() -> None:
    assert tiles.tile_box(SWISS, 0) == (0, 0, 0, 0)
    assert tiles.tile_box(SWISS, 8) == (132, 89, 135, 91)  # 47.81 N lies at y 89.2
    assert tiles.tile_box((-180, -90, 180, 90), 2) == (0, 0, 3, 3)  # clamped to the world


def test_a_header_survives_its_bytes() -> None:
    header = Header(
        *(127, 300, 427, 50, 477, 1000, 1477, 9000, 120, 100, 90),
        clustered=True,
        internal_compression=GZIP,
        tile_compression=GZIP,
        tile_type=1,
        min_zoom=0,
        max_zoom=15,
        bounds=(9.47, 47.04, 9.64, 47.27),
        center_zoom=11,
        center=(9.555, 47.155),
    )
    data = header.to_bytes()
    assert len(data) == tiles.HEADER_LENGTH and data[:8] == b"PMTiles\x03"
    assert Header.from_bytes(data) == header
    with pytest.raises(SourceError, match="no PMTiles file"):
        Header.from_bytes(b"MBTiles" + data[7:])
    with pytest.raises(SourceError, match="version 2"):
        Header.from_bytes(data[:7] + b"\x02" + data[8:])


def test_directories_encode_runs_and_contiguous_offsets() -> None:
    entries = [Entry(5, 0, 10, 1), Entry(6, 10, 20, 1), Entry(9, 0, 10, 3), Entry(40, 7, 3, 0)]
    data = encode_directory(entries)
    # count; id deltas; run lengths; lengths; offsets + 1, or 0 right after the previous one
    assert list(data) == [4, 5, 1, 3, 31, 1, 1, 3, 0, 10, 20, 10, 3, 1, 0, 1, 8]
    assert decode_directory(data) == entries
    assert decode_directory(tiles.decompress(tiles.compress(data, GZIP), GZIP)) == entries
    big = [Entry(1_000_000_000 + n, n * 300_000, 300_000, 1) for n in range(3)]
    assert decode_directory(encode_directory(big)) == big


@pytest.mark.parametrize("data", [b"", b"\x00", b"\x02\x01\x01", b"\x81", b"\x01\x05\x01\x0a\x00"])
def test_a_malformed_directory_is_refused(data: bytes) -> None:
    with pytest.raises(SourceError):
        decode_directory(data)


def test_decompression_is_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tiles, "DIRECTORY_LIMIT", 1000)
    assert tiles.decompress(gzip.compress(b"x" * 1000), GZIP) == b"x" * 1000
    with pytest.raises(SourceError, match="larger"):
        tiles.decompress(gzip.compress(b"x" * 1001), GZIP)
    with pytest.raises(SourceError, match="cannot be decompressed"):
        tiles.decompress(b"no gzip", GZIP)
    with pytest.raises(SourceError, match="brotli"):
        tiles.decompress(b"", 3)


def test_many_entries_go_into_leaf_directories(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = Entries()
    for n in range(1000):
        entries.add(n * 3, n * 100, 100, 1 + n % 2)
    root, leaves = tiles.build_directories(entries, GZIP)
    assert leaves == b""  # 1000 entries fit the first 16 KiB
    monkeypatch.setattr(tiles, "ROOT_ENTRIES", 100)
    monkeypatch.setattr(tiles, "LEAF_ENTRIES", 64)
    root, leaves = tiles.build_directories(entries, GZIP)
    pointers = decode_directory(tiles.decompress(root, GZIP))
    assert all(pointer.run_length == 0 for pointer in pointers)
    assert len(pointers) == 16  # 1000 entries in leaves of 64
    found = []
    for pointer in pointers:
        leaf = leaves[pointer.offset : pointer.offset + pointer.length]
        found += decode_directory(tiles.decompress(leaf, GZIP))
    assert found == entries.part(0, 1000)
    assert sum(pointer.length for pointer in pointers) == len(leaves)


def test_the_root_of_a_large_extract_fits_the_first_16_kib() -> None:
    entries = Entries()
    rng = random.Random(3)
    offset = 0
    for n in range(200_000):
        length = rng.randrange(100, 90_000)
        entries.add(n * 2, offset, length, 1)
        offset += length
    root, leaves = tiles.build_directories(entries, GZIP)
    assert tiles.HEADER_LENGTH + len(root) <= tiles.ROOT_LIMIT
    assert leaves


# Joining requests ------------------------------------------------------------------------------


def test_pieces_close_together_are_fetched_by_one_request() -> None:
    pieces = [(100, 5000, 7), (0, 1000, 10), (12, 1010, 5)]
    assert tiles.join_fetches(pieces, 2) == [
        [0, 17, 0, 10, 1000, 12, 5, 1010],
        [100, 7, 0, 7, 5000],
    ]
    assert tiles.join_fetches(pieces, 1) == [
        [0, 10, 0, 10, 1000],
        [12, 5, 0, 5, 1010],
        [100, 7, 0, 7, 5000],
    ]
    assert tiles.join_fetches(pieces, 1000) == [[0, 107, 0, 10, 1000, 12, 5, 1010, 100, 7, 5000]]


def test_a_request_stays_within_its_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tiles, "REQUEST_BYTES", 16)
    assert tiles.join_fetches([(0, 500, 40), (40, 540, 4)], 0) == [
        [0, 16, 0, 16, 500],
        [16, 16, 0, 16, 516],
        [32, 12, 0, 8, 532, 8, 4, 540],
    ]


def test_the_gaps_fetched_along_stay_within_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1000 bytes of pieces with gaps of 1, 2, 3 and 60 bytes: 5 % allows the first three
    pieces = [(0, 0, 250), (251, 0, 250), (503, 0, 250), (756, 0, 190), (1006, 0, 60)]
    assert tiles.gap_limit(pieces) == 59
    fetches = tiles.join_fetches(pieces, tiles.gap_limit(pieces))
    assert [fetch[:2] for fetch in fetches] == [[0, 946], [1006, 60]]
    monkeypatch.setattr(tiles, "GAP_LIMIT", 2)
    assert tiles.gap_limit(pieces) == 2
    assert tiles.gap_limit([(0, 0, 10)]) == 0


# The source ------------------------------------------------------------------------------------


def test_the_source_setting() -> None:
    assert tiles.source_setting(" Protomaps ") == "protomaps"
    assert tiles.source_setting("OFF") is None
    url = "https://maps.example/planet.pmtiles"
    assert tiles.source_setting(url) == url
    assert (
        tiles.source_setting("http://127.0.0.1:8080/a.pmtiles") == "http://127.0.0.1:8080/a.pmtiles"
    )
    for value in ("http://maps.example/a.pmtiles", "ftp://maps.example/a", "planet.pmtiles", ""):
        with pytest.raises(ValueError, match="MAILROBBE_MAP_SOURCE"):
            tiles.source_setting(value)
    assert tiles.source_host("protomaps") == "build.protomaps.com"
    assert tiles.source_host(url) == "maps.example"


def test_the_options_of_a_download() -> None:
    options = map_options("de", "streets", None, "protomaps")
    assert (options.bbox, options.max_zoom) == ((5.87, 47.27, 15.04, 55.06), MAX_ZOOMS["streets"])
    assert map_options("view", "full", [9.47, 47.04, 9.64, 47.27], "x").bbox == (
        9.47,
        47.04,
        9.64,
        47.27,
    )
    with pytest.raises(ValueError, match="needs a bbox"):
        map_options("view", "full", None, "protomaps")
    with pytest.raises(ValueError, match="takes no bbox"):
        map_options("at", "full", SWISS, "protomaps")
    for bbox in (
        [10, 47, 9, 48],
        [9, 48, 10, 47],
        [9, 47, 10],
        [-181, 0, 1, 1],
        [0, 0, float("nan"), 1],
    ):
        with pytest.raises(ValueError):
            check_bbox(bbox)


def test_the_newest_complete_build_is_taken(source: MapSource) -> None:
    source.put(
        "/builds.json",
        builds_json(
            "20261020.pmtiles",
            "20261022.pmtiles",
            "20261021.pmtiles",
            incomplete=("20261023.pmtiles",),
        ),
    )
    assert tiles.newest_build(TIMEOUT) == (source.url("/builds/20261022.pmtiles"), "20261022")
    (request,) = source.requests
    assert request.user_agent == tiles.USER_AGENT
    source.put("/builds.json", builds_json(incomplete=("20261023.pmtiles",)))
    with pytest.raises(SourceError, match="no complete build"):
        tiles.newest_build(TIMEOUT)
    source.put("/builds.json", b"<html>")
    with pytest.raises(SourceError, match="no JSON"):
        tiles.newest_build(TIMEOUT)


def test_every_request_names_mailrobbe(source: MapSource, tmp_path: Path) -> None:
    url = source.put("/world.pmtiles", world())
    assert prepare(tmp_path, view(url), TIMEOUT) is not None
    assert source.requests
    assert {request.user_agent for request in source.requests} == {tiles.USER_AGENT}


def test_a_short_answer_is_fetched_again(source: MapSource) -> None:
    data = world()
    url = source.put("/world.pmtiles", data)
    reader = tiles.Source(url, None, TIMEOUT)
    source.short = 1
    assert reader.read(1000, 5000) == data[1000:6000]
    assert source.ranges("/world.pmtiles") == ["bytes=1000-5999"] * 2
    assert reader.requests == 2


def test_failing_requests_are_tried_again_three_times(source: MapSource) -> None:
    url = source.put("/world.pmtiles", world())
    reader = tiles.Source(url, None, TIMEOUT)
    source.failing = 3
    assert len(reader.read(0, 127)) == 127
    source.failing = 4
    with pytest.raises(SourceError, match=r"HTTP 503 \(tried 4 times\)"):
        reader.read(0, 127)


def test_a_source_must_answer_ranges_of_one_unchanged_pmtiles_file(source: MapSource) -> None:
    data = world()
    url = source.put("/world.pmtiles", data)
    reader = tiles.Source(url, None, TIMEOUT)
    reader.read(0, 10)
    with pytest.raises(SourceError, match="beyond the source's end"):
        reader.read(len(data) - 5, 10)
    source.put("/world.pmtiles", data)  # a new version: another ETag
    with pytest.raises(tiles.SourceChanged):
        reader.read(0, 10)
    with pytest.raises(tiles.SourceGone):
        tiles.Source(source.url("/missing.pmtiles"), None, TIMEOUT).read(0, 10)
    source.whole = True
    with pytest.raises(SourceError, match=r"HTTP 200 instead of a range \(206\)"):
        tiles.Source(url, None, TIMEOUT).read(0, 10)
    source.whole = False
    not_pmtiles = source.put("/other.pmtiles", b"x" * 20_000)
    with pytest.raises(SourceError, match="no PMTiles file"):
        tiles.plan_extract(tiles.Source(not_pmtiles, None, TIMEOUT), view(not_pmtiles))


# The extract -----------------------------------------------------------------------------------


@pytest.mark.parametrize("leaves", [False, True])
async def test_an_extract_holds_the_tiles_of_the_box_as_the_source_has_them(
    source: MapSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leaves: bool
) -> None:
    url = source.put("/world.pmtiles", world(monkeypatch, leaves=leaves))
    if leaves:  # the extract gets leaves too
        monkeypatch.setattr(tiles, "ROOT_ENTRIES", 20)
        monkeypatch.setattr(tiles, "LEAF_ENTRIES", 16)
    options = view(url)
    prepared, data = await downloaded(tmp_path, options)
    expected = expected_tiles(SWISS, WORLD_MAX_ZOOM)
    assert read_tiles(data) == expected
    header = Header.from_bytes(data)
    assert header.bounds == pytest.approx(SWISS)
    assert header.center == pytest.approx((8.225, 46.815))
    assert (header.min_zoom, header.max_zoom) == (0, WORLD_MAX_ZOOM)  # the source has no more
    assert (header.tile_type, header.tile_compression, header.internal_compression) == (1, 2, 2)
    assert header.clustered
    assert header.addressed_tiles == len(expected) == prepared.plan.tiles
    assert header.tile_contents == len(set(expected.values()))
    assert (header.leaf_length > 0) is leaves
    assert header.tile_data_offset + header.tile_data_length == len(data) == prepared.plan.file_size
    metadata = data[header.metadata_offset : header.metadata_offset + header.metadata_length]
    assert json.loads(gzip.decompress(metadata)) == METADATA
    # Clustered: in tile id order each new content follows the previous one, from offset 0;
    # a repeated one points back.
    end = 0
    for entry in directory_entries(data):
        assert entry.offset == end or entry.offset + entry.length <= end
        end = max(end, entry.offset + entry.length)
    assert directory_entries(data)[0].offset == 0
    facts = read_detail(tmp_path)
    assert facts is not None
    assert facts.model_dump() == {
        "file": "osm-view-full-20261022123000.pmtiles",
        "region": "view",
        "bbox": SWISS,
        "detail": "full",
        "max_zoom": WORLD_MAX_ZOOM,
        "build": None,
        "source_url": url,
        "size": len(data),
        "tiles": len(expected),
        "downloaded_at": NOW,
    }
    assert sorted(path.name for path in tmp_path.iterdir()) == ["detail.json", facts.file]


async def test_an_extract_takes_the_zooms_of_its_detail(source: MapSource, tmp_path: Path) -> None:
    url = source.put("/world.pmtiles", world())
    options = view(url).model_copy(update={"max_zoom": 6})
    _, data = await downloaded(tmp_path, options)
    assert read_tiles(data) == expected_tiles(SWISS, 6)
    assert Header.from_bytes(data).max_zoom == 6


async def test_a_repeated_tile_is_fetched_and_stored_once(
    source: MapSource, tmp_path: Path
) -> None:
    url = source.put("/world.pmtiles", world())
    prepared, data = await downloaded(tmp_path, view(url))
    expected = expected_tiles(SWISS, WORLD_MAX_ZOOM)
    sea = sum(content == SEA for content in expected.values())
    assert sea > 3
    assert data.count(SEA) == 1
    assert prepared.plan.tile_bytes == len(b"".join(set(expected.values())))


async def test_adjacent_tiles_are_fetched_together(
    source: MapSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = source.put("/world.pmtiles", world())
    prepared, _ = await downloaded(tmp_path / "a", view(url))
    plan = prepared.plan
    pieces = sum((len(fetch) - 2) // 3 for fetch in plan.fetches)
    assert len(plan.fetches) <= pieces < plan.tile_contents  # adjacent contents: one piece
    assert len(tile_requests(source, "/world.pmtiles", plan)) == len(plan.fetches)
    assert plan.tile_bytes <= plan.fetch_bytes <= plan.tile_bytes * (1 + tiles.EXTRA_SHARE)
    # With a larger budget the gaps between pieces are fetched along and cut away again.
    monkeypatch.setattr(tiles, "EXTRA_SHARE", 100.0)
    joined, data = await downloaded(tmp_path / "b", view(url))
    assert len(joined.plan.fetches) < sum((len(fetch) - 2) // 3 for fetch in joined.plan.fetches)
    assert joined.plan.fetch_bytes > joined.plan.tile_bytes == plan.tile_bytes
    assert read_tiles(data) == expected_tiles(SWISS, WORLD_MAX_ZOOM)


async def test_a_stopped_download_continues_where_it_stopped(
    source: MapSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tiles, "PARALLEL", 1)
    monkeypatch.setattr(tiles, "REQUEST_BYTES", 2048)
    url = source.put("/world.pmtiles", world())
    options = view(url)
    first = prepare(tmp_path, options, TIMEOUT)
    assert first is not None
    assert len(first.plan.fetches) > 5
    stop = asyncio.Event()
    counted: list[int] = []

    def advance(count: int) -> None:
        counted.append(count)
        if len(counted) == 3:
            stop.set()

    assert not await download(first, tmp_path, stop, advance)
    partial = read_partial(tmp_path)
    assert partial is not None
    assert (partial.done, partial.bytes_done) == ([0, 1, 2], sum(counted))
    asked = len(source.requests)

    second = prepare(tmp_path, options, TIMEOUT)
    assert second is not None
    assert (second.continued, second.restart, second.plan.key) == (True, None, first.plan.key)
    assert second.partial.bytes_done == sum(counted)
    assert len(source.requests) == asked + 1  # the header, to see the file is unchanged
    rest: list[int] = []
    assert await download(second, tmp_path, asyncio.Event(), rest.append)
    assert sum(counted) + sum(rest) == first.plan.tile_bytes
    requests = tile_requests(source, "/world.pmtiles", first.plan)
    assert len(requests) == len(set(requests)) == len(first.plan.fetches)  # none twice
    facts = finish(tmp_path, second.plan, NOW)
    data = (tmp_path / facts.file).read_bytes()
    assert read_tiles(data) == expected_tiles(SWISS, WORLD_MAX_ZOOM)
    fresh = tmp_path / "fresh"
    _, again = await downloaded(fresh, options)
    assert data == again


async def stopped_download(directory: Path, options: MapOptions) -> tiles.Prepared:
    """A download stopped after its first request."""
    prepared = prepare(directory, options, TIMEOUT)
    assert prepared is not None
    stop = asyncio.Event()
    assert not await download(prepared, directory, stop, lambda count: stop.set())
    return prepared


async def test_another_choice_or_a_changed_source_starts_over(
    source: MapSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tiles, "PARALLEL", 1)
    monkeypatch.setattr(tiles, "REQUEST_BYTES", 2048)
    url = source.put("/world.pmtiles", world())
    await stopped_download(tmp_path, view(url))
    other = prepare(tmp_path, view(url, (6.0, 46.0, 9.0, 47.0)), TIMEOUT)
    assert other is not None
    assert not other.continued
    assert other.restart == "the stopped download was of view 5.96,45.82,10.49,47.81, full"
    assert read_partial(tmp_path) == other.partial
    assert other.partial.done == []

    await stopped_download(tmp_path, view(url))
    source.put("/world.pmtiles", world())  # the same bytes, but another ETag: rebuilt
    again = prepare(tmp_path, view(url), TIMEOUT)
    assert again is not None
    assert not again.continued
    assert again.restart == f"{url} changed since the download stopped"
    assert again.partial.done == []

    await stopped_download(tmp_path, view(url))
    (tmp_path / tiles.PART_FILE).unlink()
    lost = prepare(tmp_path, view(url), TIMEOUT)
    assert lost is not None and lost.restart == "the part file of the stopped download is missing"


async def test_a_stopped_build_goes_on_while_it_is_there(
    source: MapSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tiles, "PARALLEL", 1)
    monkeypatch.setattr(tiles, "REQUEST_BYTES", 2048)
    source.put("/builds.json", builds_json("20261021.pmtiles"))
    source.put("/builds/20261021.pmtiles", world())
    options = map_options("ch", "overview", None, "protomaps")
    first = await stopped_download(tmp_path, options)
    assert (first.plan.build, first.plan.source_url) == (
        "20261021",
        source.url("/builds/20261021.pmtiles"),
    )
    # A newer build appeared: the stopped one is continued while the source still has it.
    source.put("/builds.json", builds_json("20261021.pmtiles", "20261022.pmtiles"))
    source.put("/builds/20261022.pmtiles", world())
    second = prepare(tmp_path, options, TIMEOUT)
    assert second is not None and second.continued and second.plan.build == "20261021"
    # Daily builds are deleted after some days: then the newest one starts over.
    del source.files["/builds/20261021.pmtiles"]
    third = prepare(tmp_path, options, TIMEOUT)
    assert third is not None and not third.continued
    assert third.restart == "the build 20261021 is gone from the source"
    assert third.plan.build == "20261022"
    assert await download(third, tmp_path, asyncio.Event(), lambda count: None)
    facts = finish(tmp_path, third.plan, NOW)
    assert (facts.build, facts.region, facts.detail) == ("20261022", "ch", "overview")
    data = (tmp_path / facts.file).read_bytes()
    assert read_tiles(data) == expected_tiles((5.96, 45.82, 10.49, 47.81), WORLD_MAX_ZOOM)


async def test_a_range_failing_for_good_keeps_what_is_on_disk(
    source: MapSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tiles, "PARALLEL", 1)
    monkeypatch.setattr(tiles, "REQUEST_BYTES", 2048)
    url = source.put("/world.pmtiles", world())
    prepared = prepare(tmp_path, view(url), TIMEOUT)
    assert prepared is not None
    source.failing_from = prepared.plan.fetches[4][0]
    with pytest.raises(SourceError, match="HTTP 503"):
        await download(prepared, tmp_path, asyncio.Event(), lambda count: None)
    partial = read_partial(tmp_path)
    assert partial is not None and partial.done == [0, 1, 2, 3]
    source.failing_from = None
    again = prepare(tmp_path, view(url), TIMEOUT)
    assert again is not None and again.continued
    assert await download(again, tmp_path, asyncio.Event(), lambda count: None)
    facts = finish(tmp_path, again.plan, NOW)
    assert read_tiles((tmp_path / facts.file).read_bytes()) == expected_tiles(SWISS, WORLD_MAX_ZOOM)


async def test_a_part_file_of_another_size_is_not_put_in_place(
    source: MapSource, tmp_path: Path
) -> None:
    url = source.put("/world.pmtiles", world())
    prepared = prepare(tmp_path, view(url), TIMEOUT)
    assert prepared is not None
    assert await download(prepared, tmp_path, asyncio.Event(), lambda count: None)
    with (tmp_path / tiles.PART_FILE).open("ab") as part:
        part.write(b"more")
    with pytest.raises(SourceError, match="bytes instead of"):
        finish(tmp_path, prepared.plan, NOW)
    assert list(tmp_path.iterdir()) == []  # the next run starts over


async def test_a_new_map_replaces_the_previous_one(source: MapSource, tmp_path: Path) -> None:
    url = source.put("/world.pmtiles", world())
    await downloaded(tmp_path, view(url))
    first = read_detail(tmp_path)
    prepared = prepare(tmp_path, view(url, detail="overview"), TIMEOUT)
    assert prepared is not None
    assert read_detail(tmp_path) == first  # kept while the next one downloads
    assert await download(prepared, tmp_path, asyncio.Event(), lambda count: None)
    facts = finish(tmp_path, prepared.plan, datetime(2026, 10, 23, tzinfo=UTC))
    assert read_detail(tmp_path) == facts
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "detail.json",
        "osm-view-overview-20261023000000.pmtiles",
    ]


# The files -------------------------------------------------------------------------------------


async def test_deleting_removes_the_map_and_a_stopped_download(
    source: MapSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tiles, "PARALLEL", 1)
    monkeypatch.setattr(tiles, "REQUEST_BYTES", 2048)
    url = source.put("/world.pmtiles", world())
    await downloaded(tmp_path, view(url))
    await stopped_download(tmp_path, view(url, detail="overview"))
    (tmp_path / "notes.txt").write_text("not ours")
    removed = tiles.delete_maps(tmp_path)
    assert sorted(removed) == [
        "detail.json",
        "download.json",
        "download.part",
        "download.plan.json",
        "osm-view-full-20261022123000.pmtiles",
    ]
    assert [path.name for path in tmp_path.iterdir()] == ["notes.txt"]
    assert tiles.delete_maps(tmp_path / "missing") == []


def test_the_facts_name_only_a_map_file_that_is_there(tmp_path: Path) -> None:
    facts = tiles.DetailFacts(
        file="osm-de-full-20261022123000.pmtiles",
        region="de",
        bbox=(5.87, 47.27, 15.04, 55.06),
        detail="full",
        max_zoom=15,
        build="20261022",
        source_url="https://build.protomaps.com/20261022.pmtiles",
        size=10,
        tiles=1,
        downloaded_at=NOW,
    )
    (tmp_path / "detail.json").write_text(facts.model_dump_json())
    assert read_detail(tmp_path) is None  # its file is gone
    (tmp_path / facts.file).write_bytes(b"x" * 10)
    assert read_detail(tmp_path) == facts
    (tmp_path / "detail.json").write_text(
        facts.model_copy(update={"file": "../x.pmtiles"}).model_dump_json()
    )
    assert read_detail(tmp_path) is None
    (tmp_path / "detail.json").write_text("{")
    assert read_detail(tmp_path) is None
    assert read_detail(tmp_path / "missing") is None


def test_a_download_needs_its_size_and_five_percent_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage._replace(free=1_000_000_000))
    tiles.check_space(tmp_path, 952_000_000)
    with pytest.raises(NotEnoughSpace) as refused:
        tiles.check_space(tmp_path, 953_000_000)
    assert str(refused.value) == (
        f"not enough free space in {tmp_path}: the download needs 908.9 MB and 5% more, "
        "953.7 MB are free"
    )
    assert tiles.free_bytes(tmp_path / "not" / "there") == 1_000_000_000  # where it would be

    def unknown(path: object) -> None:
        raise OSError("no file system")

    monkeypatch.setattr(shutil, "disk_usage", unknown)
    assert tiles.free_bytes(tmp_path) is None
    tiles.check_space(tmp_path, 10**15)  # cannot be told: the download tries

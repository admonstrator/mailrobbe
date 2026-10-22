"""Rebuild frontend/public/map/, the overview map Mailrobbe ships and serves itself (D244).

Run by hand when a source should be updated, never in tests, CI or the build:

    SSL_CERT_FILE=/path/to/ca.pem uv run python scripts/overview_map.py [--cache DIR]

It downloads the sources named below, keeps what the map draws and writes them as GeoJSON with
coordinates rounded to what the zooms need: the countries of the world (Natural Earth 1:50m),
the first-level regions of Germany, Austria and Switzerland, lakes and rivers about Europe (both
1:10m), one file of label points (countries, regions, lakes) with German names where Natural
Earth has them; the glyphs of the Protomaps basemap (Noto Sans) for the ranges the labels need,
and its light sprites. SOURCES.md lists every URL with the date and the licence. The town labels
are not part of it: the map asks GET /api/map/towns for them (GeoNames, places/gazetteer.py).
"""

import argparse
import hashlib
import itertools
import json
import shutil
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NATURAL_EARTH = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson"
# The commit of github.com/protomaps/basemaps-assets the glyphs and sprites are taken from.
ASSETS_COMMIT = "028c18f713baecad011301ff7a69acc39bcc2ae7"
ASSETS = f"https://raw.githubusercontent.com/protomaps/basemaps-assets/{ASSETS_COMMIT}"
# The sprites are derived from these icons; their licence travels with them.
ICONS_LICENSE = (
    "https://raw.githubusercontent.com/tangrams/icons/92510779634f4a006c61ea70e50cb8c52c765a81"
    "/LICENSE.md"
)
USER_AGENT = "Mailrobbe overview map builder"

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "map"
DACH = ("DE", "AT", "CH")
# Lakes and rivers are kept where they touch this box (west, south, east, north): about Europe.
EUROPE = (-25.0, 34.0, 45.0, 72.0)
FONTS = ("Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic")
# Latin, Latin Extended A and B, IPA and spacing modifiers, combining marks and Greek, Cyrillic,
# Cyrillic Supplement, Latin Extended Additional, General Punctuation.
GLYPH_RANGES = (0, 256, 512, 768, 1024, 1280, 7680, 8192)
SPRITES = ("light.json", "light.png", "light@2x.json", "light@2x.png")
# Decimal places of the coordinates and the tolerance of the simplification in degrees: 1:50m
# data is drawn up to about zoom 7 (0.01 degrees are half a pixel there), 1:10m up to about
# zoom 9.
COUNTRY_DIGITS, COUNTRY_TOLERANCE = 2, 0.01
DETAIL_DIGITS, DETAIL_TOLERANCE = 3, 0.002

Ring = list[list[float]]


def fetch(url: str, cache: Path | None) -> bytes:
    """The bytes at url, from the cache directory when it holds them."""
    cached = cache / hashlib.sha256(url.encode()).hexdigest()[:24] if cache else None
    if cached and cached.is_file():
        return cached.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        body: bytes = response.read()
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(body)
    return body


def simplified(points: Ring, tolerance: float) -> Ring:
    """Douglas-Peucker: the points without those closer than tolerance to the line between the
    ones kept around them; the first and the last stay."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (ax, ay), (bx, by) = points[first], points[last]
        dx, dy = bx - ax, by - ay
        length = (dx * dx + dy * dy) ** 0.5
        farthest, distance = first, 0.0
        for index in range(first + 1, last):
            px, py = points[index]
            if length == 0:
                d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                d = abs(dy * px - dx * py + bx * ay - by * ax) / length
            if d > distance:
                farthest, distance = index, d
        if distance > tolerance:
            keep[farthest] = True
            stack += [(first, farthest), (farthest, last)]
    return [point for point, kept in zip(points, keep, strict=True) if kept]


def rounded_ring(ring: Iterable[list[float]], digits: int, tolerance: float, closed: bool) -> Ring:
    """The points simplified and rounded, without consecutive repetitions; a closed ring stays
    closed."""
    points: Ring = []
    for x, y, *_ in simplified([[point[0], point[1]] for point in ring], tolerance):
        point = [round(x, digits), round(y, digits)]
        if not points or point != points[-1]:
            points.append(point)
    if closed and points and points[0] != points[-1]:
        points.append(points[0])
    return points


def rounded(geometry: dict[str, Any], digits: int, tolerance: float) -> dict[str, Any] | None:
    """A Polygon, MultiPolygon, LineString or MultiLineString simplified and rounded; None when
    nothing that can be drawn is left (rings below four points, lines below two)."""
    kind = geometry["type"]
    if kind in ("Polygon", "MultiPolygon"):
        polygons = [geometry["coordinates"]] if kind == "Polygon" else geometry["coordinates"]
        kept = []
        for polygon in polygons:
            rings = [rounded_ring(ring, digits, tolerance, closed=True) for ring in polygon]
            if len(rings[0]) >= 4:
                kept.append([ring for ring in rings if len(ring) >= 4])
        if not kept:
            return None
        if len(kept) == 1:
            return {"type": "Polygon", "coordinates": kept[0]}
        return {"type": "MultiPolygon", "coordinates": kept}
    if kind in ("LineString", "MultiLineString"):
        lines = [geometry["coordinates"]] if kind == "LineString" else geometry["coordinates"]
        kept_lines = [rounded_ring(line, digits, tolerance, closed=False) for line in lines]
        kept_lines = [line for line in kept_lines if len(line) >= 2]
        if not kept_lines:
            return None
        if len(kept_lines) == 1:
            return {"type": "LineString", "coordinates": kept_lines[0]}
        return {"type": "MultiLineString", "coordinates": kept_lines}
    raise ValueError(f"unexpected geometry {kind}")


def points_of(geometry: dict[str, Any]) -> Iterator[list[float]]:
    kind = geometry["type"]
    depth = {"LineString": 1, "Polygon": 2, "MultiLineString": 2, "MultiPolygon": 3}[kind]

    def walk(value: Any, level: int) -> Iterator[list[float]]:
        if level == 0:
            yield value
        else:
            for item in value:
                yield from walk(item, level - 1)

    yield from walk(geometry["coordinates"], depth)


def touches(geometry: dict[str, Any], box: tuple[float, float, float, float]) -> bool:
    """Whether the geometry's bounding box overlaps box; never for one without points."""
    points = list(points_of(geometry))
    if not points:
        return False
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    west, south, east, north = box
    return min(xs) <= east and max(xs) >= west and min(ys) <= north and max(ys) >= south


def label_point(geometry: dict[str, Any]) -> list[float]:
    """A point inside the largest outer ring: the middle of the longest stretch of the ring's
    middle latitude that lies inside it."""
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    ring = max((polygon[0] for polygon in polygons), key=ring_area)
    ys = [point[1] for point in ring]
    y = (min(ys) + max(ys)) / 2
    crossings = sorted(
        a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        for a, b in itertools.pairwise(ring)
        if (a[1] <= y) != (b[1] <= y)
    )
    spans = list(zip(crossings[::2], crossings[1::2], strict=False))
    west, east = max(spans, key=lambda span: span[1] - span[0])
    return lonlat((west + east) / 2, y)


def lonlat(longitude: float, latitude: float) -> list[float]:
    """A label point's coordinates, rounded."""
    return [round(longitude, DETAIL_DIGITS), round(latitude, DETAIL_DIGITS)]


def ring_area(ring: Ring) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in itertools.pairwise(ring))) / 2


def feature(geometry: dict[str, Any], properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def point(coordinates: list[float], properties: dict[str, Any]) -> dict[str, Any]:
    return feature({"type": "Point", "coordinates": coordinates}, properties)


def german(properties: dict[str, Any], *keys: str) -> str | None:
    """The first of the name fields that is set: the German name before the local one."""
    for key in keys:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def build(cache: Path | None, out: Path) -> list[tuple[str, str]]:
    """Write the map's files into out; the sources read, as (url, what was taken)."""

    def geojson(name: str) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(fetch(f"{NATURAL_EARTH}/{name}.geojson", cache))
        return loaded

    sources: list[tuple[str, str]] = []
    labels: list[dict[str, Any]] = []

    countries = []
    for item in geojson("ne_50m_admin_0_countries")["features"]:
        props = item["properties"]
        geometry = rounded(item["geometry"], COUNTRY_DIGITS, COUNTRY_TOLERANCE)
        if geometry:
            countries.append(feature(geometry, {}))
        name = german(props, "NAME_DE", "NAME")
        if name and props.get("LABEL_X") is not None:
            labels.append(
                point(
                    lonlat(props["LABEL_X"], props["LABEL_Y"]),
                    {"kind": "country", "name": name, "min_zoom": props["MIN_LABEL"]},
                )
            )
    sources.append((f"{NATURAL_EARTH}/ne_50m_admin_0_countries.geojson", "countries, labels"))

    states = []
    for item in geojson("ne_10m_admin_1_states_provinces")["features"]:
        props = item["properties"]
        if props.get("iso_a2") not in DACH:
            continue
        geometry = rounded(item["geometry"], DETAIL_DIGITS, DETAIL_TOLERANCE)
        if geometry:
            states.append(feature(geometry, {"country": props["iso_a2"]}))
        name = german(props, "name_de", "name")
        if name:
            labels.append(
                point(
                    lonlat(props["longitude"], props["latitude"]),
                    {"kind": "state", "name": name, "min_zoom": props["min_label"]},
                )
            )
    sources.append(
        (f"{NATURAL_EARTH}/ne_10m_admin_1_states_provinces.geojson", "regions of DE, AT, CH")
    )

    lakes = []
    for name in ("ne_10m_lakes", "ne_10m_lakes_europe"):
        for item in geojson(name)["features"]:
            props = item["properties"]
            if not item["geometry"] or not touches(item["geometry"], EUROPE):
                continue
            geometry = rounded(item["geometry"], DETAIL_DIGITS, DETAIL_TOLERANCE)
            if not geometry:
                continue
            lakes.append(feature(geometry, {"min_zoom": props.get("min_zoom") or 0}))
            label = german(props, "name_de", "name")
            if label:
                labels.append(
                    point(
                        label_point(geometry),
                        {"kind": "lake", "name": label, "min_zoom": props.get("min_label") or 0},
                    )
                )
        sources.append((f"{NATURAL_EARTH}/{name}.geojson", "lakes about Europe, labels"))

    rivers = []
    for name in ("ne_10m_rivers_lake_centerlines", "ne_10m_rivers_europe"):
        for item in geojson(name)["features"]:
            props = item["properties"]
            if not item["geometry"] or not touches(item["geometry"], EUROPE):
                continue
            geometry = rounded(item["geometry"], DETAIL_DIGITS, DETAIL_TOLERANCE)
            if not geometry:
                continue
            river = {"min_zoom": props.get("min_zoom") or 0, "rank": props.get("scalerank") or 0}
            label = german(props, "name_de", "name")
            if label:
                river["name"] = label
            rivers.append(feature(geometry, river))
        sources.append((f"{NATURAL_EARTH}/{name}.geojson", "rivers about Europe"))

    out.mkdir(parents=True, exist_ok=True)
    for file, features in (
        ("countries.json", countries),
        ("states.json", states),
        ("lakes.json", lakes),
        ("rivers.json", rivers),
        ("labels.json", labels),
    ):
        text = json.dumps(collection(features), ensure_ascii=False, separators=(",", ":"))
        (out / file).write_text(text, "utf-8")

    ranges = ", ".join(f"{start}-{start + 255}" for start in GLYPH_RANGES)
    for font in FONTS:
        folder = out / "fonts" / font
        folder.mkdir(parents=True, exist_ok=True)
        for start in GLYPH_RANGES:
            rangename = f"{start}-{start + 255}.pbf"
            url = f"{ASSETS}/fonts/{urllib.parse.quote(font)}/{rangename}"
            (folder / rangename).write_bytes(fetch(url, cache))
        sources.append((f"{ASSETS}/fonts/{urllib.parse.quote(font)}/", f"glyphs {ranges}"))
    (out / "fonts" / "OFL.txt").write_bytes(fetch(f"{ASSETS}/fonts/OFL.txt", cache))
    sources.append((f"{ASSETS}/fonts/OFL.txt", "the fonts' licence"))

    (out / "sprites").mkdir(exist_ok=True)
    for name in SPRITES:
        (out / "sprites" / name).write_bytes(fetch(f"{ASSETS}/sprites/v4/{name}", cache))
    sources.append((f"{ASSETS}/sprites/v4/", "light sprites"))
    (out / "sprites" / "LICENSE.md").write_bytes(fetch(ICONS_LICENSE, cache))
    sources.append((ICONS_LICENSE, "the icons' licence"))
    return sources


LICENCES = """\
## Licences

- Natural Earth (countries, regions, lakes, rivers, label points): public domain,
  https://www.naturalearthdata.com/about/terms-of-use/
- Noto Sans (the glyphs below fonts/): SIL Open Font License 1.1, fonts/OFL.txt
- The sprites of the Protomaps basemap (sprites/), derived from the icons of tangrams/icons:
  MIT, sprites/LICENSE.md
- The town labels come from the server (GET /api/map/towns): GeoNames, CC BY 4.0,
  https://www.geonames.org/
"""


def write_sources(out: Path, sources: list[tuple[str, str]]) -> None:
    today = datetime.now(UTC).date().isoformat()
    lines = [
        "# Sources of the overview map",
        "",
        "Built by `scripts/overview_map.py`; nothing here is loaded from anywhere but this server.",
        "",
        f"Downloaded {today}:",
        "",
        *(f"- {url} ({what})" for url, what in sources),
        "",
        LICENCES,
    ]
    (out / "SOURCES.md").write_text("\n".join(lines), "utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, help="keep downloads here and use them next time")
    parser.add_argument("--out", type=Path, default=OUT, help=f"target directory ({OUT})")
    args = parser.parse_args(argv)
    staging = args.out.with_name(args.out.name + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    sources = build(args.cache, staging)
    write_sources(staging, sources)
    shutil.rmtree(args.out, ignore_errors=True)
    staging.rename(args.out)
    total = sum(file.stat().st_size for file in args.out.rglob("*") if file.is_file())
    print(f"wrote {args.out}: {total / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

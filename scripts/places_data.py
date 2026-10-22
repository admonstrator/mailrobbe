"""Rebuild src/mailrobbe/places/data/ from GeoNames and Natural Earth (D242 to D244).

Run by hand to refresh the shipped lists, never in tests or CI (it downloads about 235 MB):

    SSL_CERT_FILE=... uv run python scripts/places_data.py [--cache DIR]

The source files are kept in the cache directory (default data/places-sources, outside the
package) and downloaded only when missing there; delete them for a new download. It writes
towns.tsv.gz, postcodes.tsv.gz, countries.tsv and SOURCES.md (with the download date and the
filters); country_names.txt and town_names.txt are kept by hand. New lists change
places_version(), so the next import run gives every place entity and invitation its point
again.
"""

import argparse
import csv
import gzip
import io
import re
import struct
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mailrobbe.places.gazetteer import fold

OUT = Path(__file__).resolve().parent.parent / "src" / "mailrobbe" / "places" / "data"
GEONAMES = "https://download.geonames.org/export"
NATURAL_EARTH = "https://naciscdn.org/naturalearth/10m/cultural"
SOURCES = {
    "cities500.zip": f"{GEONAMES}/dump/cities500.zip",
    "cities15000.zip": f"{GEONAMES}/dump/cities15000.zip",
    "admin1CodesASCII.txt": f"{GEONAMES}/dump/admin1CodesASCII.txt",
    "alternateNamesV2.zip": f"{GEONAMES}/dump/alternateNamesV2.zip",
    "postal-DE.zip": f"{GEONAMES}/zip/DE.zip",
    "postal-AT.zip": f"{GEONAMES}/zip/AT.zip",
    "postal-CH.zip": f"{GEONAMES}/zip/CH.zip",
    "postal-LI.zip": f"{GEONAMES}/zip/LI.zip",
    "ne_10m_admin_0_countries.zip": f"{NATURAL_EARTH}/ne_10m_admin_0_countries.zip",
    "ne_10m_admin_0_map_units.zip": f"{NATURAL_EARTH}/ne_10m_admin_0_map_units.zip",
}

DACH = ("DE", "AT", "CH", "LI")
SEATS = frozenset({"PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC"})
# Sections of a town, historical, destroyed and abandoned places are no towns of their own.
NO_TOWNS = frozenset({"PPLX", "PPLH", "PPLW", "PPLQ", "PPLCH"})
SMALLEST = 500  # inhabitants of a DACH+LI place that is no seat
# alternateNamesV2 languages that are codes and links, not names
CODES = frozenset({"iata", "icao", "faac", "abbr", "link", "post", "unlc", "wkdt", "tcid", "uicn"})
# The ISO 3166-2 letters some rows of the German postcode list give, as GeoNames admin1 codes.
GERMAN_STATES = {
    "BW": "01", "BY": "02", "HB": "03", "HH": "04", "HE": "05", "NI": "06", "NW": "07",
    "RP": "08", "SL": "09", "SH": "10", "BB": "11", "MV": "12", "SN": "13", "ST": "14",
    "TH": "15", "BE": "16",
}  # fmt: skip
# Words of the German postcode list's large customers (companies, authorities): no towns.
COMPANY = re.compile(
    r"\b(?:GmbH|AG|KG|KGaA|OHG|mbH|e\.\s?V|eG|SE|a\.G|Bank|Sparkasse|Versicherung\w*|Verlag"
    r"|Service\w*|Zentrale|Postfach|Gruppe|Holding)\b|&",
    re.IGNORECASE,
)
# Natural Earth's German names where they are a long form or English.
GERMAN_COUNTRY_NAMES = {
    "CY": "Zypern",
    "TW": "Taiwan",
    "CN": "China",
    "KY": "Kaimaninseln",
    "MD": "Moldau",
}
# The parts of the United Kingdom, from the map units, as ISO 3166-2 codes.
UK_PARTS = {
    "England": "GB-ENG",
    "Scotland": "GB-SCT",
    "Wales": "GB-WLS",
    "Northern Ireland": "GB-NIR",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache", type=Path, default=Path("data/places-sources"))
    args = parser.parse_args()
    cache: Path = args.cache
    cache.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        if not (cache / name).exists():
            print(f"downloading {url}")
            request = urllib.request.Request(url, headers={"User-Agent": "mailrobbe places_data"})
            with urllib.request.urlopen(request, timeout=300) as response:
                (cache / (name + ".part")).write_bytes(response.read())
            (cache / (name + ".part")).rename(cache / name)
    downloaded = min(
        datetime.fromtimestamp((cache / name).stat().st_mtime, UTC) for name in SOURCES
    )
    OUT.mkdir(parents=True, exist_ok=True)
    admin1 = _admin1(cache)
    towns = _towns(cache)
    german, codes = _alternate_names(cache, {t.id for t in towns} | {a.id for a in admin1.values()})
    regions = {key: _region_name(entry, german.get(entry.id, [])) for key, entry in admin1.items()}
    count = _write_towns(towns, regions, german, codes)
    known = {
        fold(name)
        for town in towns
        if town.country in DACH
        for name in (town.name, *town.names, *(n[0] for n in german.get(town.id, [])))
    }
    postcodes = _write_postcodes(cache, regions, known)
    countries, version = _write_countries(cache)
    _write_sources(downloaded, count, postcodes, countries, version)
    for path in sorted(OUT.iterdir()):
        print(f"{path.name}: {path.stat().st_size} bytes")


# GeoNames --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Admin1:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class _Town:
    id: str
    name: str
    names: tuple[str, ...]  # GeoNames alternatenames
    latitude: str
    longitude: str
    code: str  # feature code
    country: str
    admin1: str
    population: int


def _admin1(cache: Path) -> dict[tuple[str, str], _Admin1]:
    found = {}
    for line in (cache / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
        key, name, _, geonameid = line.split("\t")
        country, _, code = key.partition(".")
        found[country, code] = _Admin1(geonameid, name)
    return found


def _rows(path: Path, member: str) -> Iterator[list[str]]:
    with zipfile.ZipFile(path) as archive, archive.open(member) as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8"):
            yield line.rstrip("\n").split("\t")


def _towns(cache: Path) -> list[_Town]:
    """DACH+LI from cities500 (at least SMALLEST inhabitants, or a seat), the world from
    cities15000."""
    towns = []
    for name, dach in (("cities500", True), ("cities15000", False)):
        for row in _rows(cache / f"{name}.zip", f"{name}.txt"):
            code, country, population = row[7], row[8], int(row[14] or 0)
            if code in NO_TOWNS or (country in DACH) != dach:
                continue
            if dach and population < SMALLEST and code not in SEATS:
                continue
            names = tuple(row[3].split(",")) if row[3] else ()
            towns.append(
                _Town(row[0], row[1], names, row[4], row[5], code, country, row[10], population)
            )
    return towns


def _alternate_names(
    cache: Path, ids: set[str]
) -> tuple[dict[str, list[list[str]]], dict[str, set[str]]]:
    """The German names of the places (isolanguage de, with their flags preferred, short,
    colloquial, historic) and the names that are codes (CODES), by geonameid."""
    german: dict[str, list[list[str]]] = defaultdict(list)
    codes: dict[str, set[str]] = defaultdict(set)
    print("reading alternateNamesV2.txt")
    for row in _rows(cache / "alternateNamesV2.zip", "alternateNamesV2.txt"):
        if row[1] not in ids:
            continue
        if row[2] == "de":
            german[row[1]].append(row[3:8])
        elif row[2] in CODES:
            codes[row[1]].add(row[3])
    return german, codes


def _german(names: list[list[str]], *, short: bool) -> str | None:
    """A German name: of a region the short one (Zürich, not Kanton Zürich), of a town the
    preferred one; never a colloquial or historic one."""
    usable = [name for name in names if not name[3] and not name[4]]
    if short:
        for name in usable:
            if name[2]:
                return name[0]
    for name in usable:
        if name[1] and not name[2]:
            return name[0]
    plain = [name for name in usable if not name[2]]
    return (plain or usable)[0][0] if plain or usable else None


def _region_name(entry: _Admin1, german: list[list[str]]) -> str:
    return _german(german, short=True) or entry.name


def _latin(name: str) -> bool:
    return all(unicodedata.name(char, "").startswith("LATIN") for char in name if char.isalpha())


def _other_names(town: _Town, own: list[str], codes: set[str]) -> list[str]:
    """Names in Latin script, capitalised, without digits and codes (airports, abbreviations),
    besides its own names; spellings the gazetteer does not tell apart (fold) once."""
    kept: dict[str, str] = {fold(name): name for name in own}
    for other in town.names:
        other = " ".join(other.split())
        if (
            not other
            or other in codes
            or any(char.isdigit() for char in other)
            or "|" in other
            or not other[0].isupper()
            or not _latin(other)
        ):
            continue
        kept.setdefault(fold(other), other)
    return list(kept.values())[len({fold(name) for name in own}) :]


def _write_towns(
    towns: list[_Town],
    regions: dict[tuple[str, str], str],
    german: dict[str, list[list[str]]],
    codes: dict[str, set[str]],
) -> int:
    """Its German name, and as GeoNames writes it (local) where that differs."""
    lines = []
    for town in sorted(towns, key=lambda town: (-town.population, town.name, town.id)):
        names_de = german.get(town.id, [])
        usable = [entry[0] for entry in names_de if not entry[3] and not entry[4]]
        if town.name in usable:
            name = town.name  # GeoNames writes it in German already
        else:  # the German spelling of the same name (Chişinău for Chisinau), else its own
            same = (entry for entry in usable if fold(entry) == fold(town.name))
            name = next(same, None) or _german(names_de, short=False) or town.name
        local = town.name if fold(town.name) != fold(name) else ""
        names = _other_names(town, [name, local] if local else [name], codes.get(town.id, set()))
        region = regions.get((town.country, town.admin1), "")
        capital = "1" if town.code == "PPLC" else ""
        lines.append(
            [name, local, town.country, region, _degrees(town.latitude),
             _degrees(town.longitude), str(town.population), capital, "|".join(names)]
        )  # fmt: skip
    header = ["name", "local", "country", "region", "latitude", "longitude", "population"]
    _write_tsv("towns.tsv.gz", [*header, "capital", "names"], lines)
    return len(lines)


def _degrees(value: str) -> str:
    return f"{float(value):.5f}".rstrip("0").rstrip(".")


def _write_postcodes(cache: Path, regions: dict[tuple[str, str], str], known: set[str]) -> int:
    """One row per postcode and place name; the names of PO boxes (Bern 15) and city districts
    (Wien, Innere Stadt) cut to the town's, large customers (companies) left out. A row without
    an accuracy (the large customers and special postcodes) keeps the longest leading words of
    its name that name a DACH+LI town (Zofingen PostFinance: Zofingen), or is left out."""
    found: dict[tuple[str, str, str], list[str]] = {}
    for country in DACH:
        for row in _rows(cache / f"postal-{country}.zip", f"{country}.txt"):
            postcode, name, region_name, code = row[1], row[2], row[3], row[4]
            name = re.split(r",|\s\S*\d", name, maxsplit=1)[0].strip()
            if not name or not row[9] or not row[10]:
                continue
            if not row[11]:
                if COMPANY.search(name):
                    continue
                words = name.split()
                leading = (" ".join(words[:end]) for end in range(len(words), 0, -1))
                name = next((part for part in leading if fold(part) in known), "")
                if not name:
                    continue
            code = GERMAN_STATES.get(code, code) if country == "DE" else code
            region = regions.get((country, code), region_name)
            found.setdefault(
                (country, postcode, name),
                [country, postcode, name, region, _degrees(row[9]), _degrees(row[10])],
            )
    header = ["country", "postcode", "name", "region", "latitude", "longitude"]
    _write_tsv("postcodes.tsv.gz", header, list(found.values()))
    return len(found)


# Natural Earth ---------------------------------------------------------------------------


def _dbf(data: bytes) -> list[dict[str, str]]:
    """The records of a dBASE table (a shapefile's attributes), as text."""
    count, header, size = struct.unpack_from("<IHH", data, 4)
    fields = []
    at = 32
    while data[at] != 0x0D:
        fields.append((data[at : at + 11].split(b"\0")[0].decode(), data[at + 16]))
        at += 32
    records = []
    for index in range(count):
        start = header + index * size + 1
        record = {}
        for name, width in fields:
            record[name] = data[start : start + width].decode("utf-8").strip("\x00 ")
            start += width
        records.append(record)
    return records


# The fields naming a country; of the parts of the United Kingdom the first ones only (ADMIN
# and FORMAL_EN name the kingdom). NAME_ALT lists names separated by commas.
_NAME_FIELDS = (
    "NAME", "NAME_LONG", "GEOUNIT", "SUBUNIT", "BRK_NAME", "NAME_EN", "NAME_DE", "ADMIN",
    "FORMAL_EN", "NAME_ALT",
)  # fmt: skip
_PART_FIELDS = _NAME_FIELDS[:7]


def _write_countries(cache: Path) -> tuple[int, str]:
    """Every country with an ISO code (the most populous record of the code: France, not
    Clipperton) and the four parts of the United Kingdom, at Natural Earth's label point."""
    name = "ne_10m_admin_0_countries"
    with zipfile.ZipFile(cache / f"{name}.zip") as archive:
        records = _dbf(archive.read(f"{name}.dbf"))
        version = archive.read(f"{name}.VERSION.txt").decode().strip()
    best: dict[str, dict[str, str]] = {}
    for record in records:
        code = record["ISO_A2_EH"]
        if not re.fullmatch("[A-Z]{2}", code):
            continue
        if code not in best or _population(record) > _population(best[code]):
            best[code] = record
    name = "ne_10m_admin_0_map_units"
    with zipfile.ZipFile(cache / f"{name}.zip") as archive:
        for record in _dbf(archive.read(f"{name}.dbf")):
            if record["ADMIN"] == "United Kingdom" and record["GEOUNIT"] in UK_PARTS:
                best[UK_PARTS[record["GEOUNIT"]]] = record
    lines = []
    for code, record in sorted(best.items()):
        german = GERMAN_COUNTRY_NAMES.get(code, record["NAME_DE"])
        names = dict.fromkeys(
            value
            for field in (_PART_FIELDS if code.startswith("GB-") else _NAME_FIELDS)
            for value in _names(record, field)
            if value not in (german, record["NAME_EN"])
        )
        lines.append(
            [code, german, record["NAME_EN"], _degrees(record["LABEL_Y"]),
             _degrees(record["LABEL_X"]), str(_population(record)), "|".join(names)]
        )  # fmt: skip
    header = ["code", "name_de", "name_en", "latitude", "longitude", "population", "names"]
    _write_tsv("countries.tsv", header, lines)
    return len(lines), version


def _population(record: dict[str, str]) -> int:
    return int(float(record["POP_EST"] or 0))


def _names(record: dict[str, str], field: str) -> Iterable[str]:
    value = record[field]
    parts = value.split(",") if field == "NAME_ALT" else [value]
    return (part.strip() for part in parts if part.strip())


# Output -----------------------------------------------------------------------------------


def _write_tsv(name: str, header: list[str], lines: list[list[str]]) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE)
    writer.writerow(header)
    writer.writerows(lines)
    data = buffer.getvalue().encode()
    if name.endswith(".gz"):
        data = gzip.compress(data, compresslevel=9, mtime=0)  # the same lists, the same bytes
    (OUT / name).write_bytes(data)


def _write_sources(
    downloaded: datetime, towns: int, postcodes: int, countries: int, version: str
) -> None:
    day = downloaded.date().isoformat()
    text = f"""# Places data

The lists the step places and the places API read (`mailrobbe.places.gazetteer`, D242 to D244),
built by `scripts/places_data.py` from the files below, downloaded on {day}. Run the script to
refresh them; a new build changes `places_version()`, and the next import run gives every place
entity and invitation its point again.

## towns.tsv.gz ({towns} towns)

GeoNames `cities500.zip` for Germany, Austria, Switzerland and Liechtenstein: every populated
place of at least {SMALLEST} inhabitants and every seat of an administrative unit (PPLA to
PPLA5, PPLC) whatever its size; GeoNames `cities15000.zip` for every other country. Sections of
towns, historical, destroyed and abandoned places (PPLX, PPLH, PPLW, PPLQ, PPLCH) are left out.
Most populous first.

- name: its own where it is one of its German names in `alternateNamesV2.zip` (isolanguage de,
  not colloquial or historic), else the German spelling of it (Chişinău for Chisinau), else the
  German name GeoNames prefers, else its own; local: its own where that differs (Munich for
  München)
- region: the first administrative level (`admin1CodesASCII.txt`), by its short German name
  where GeoNames has one
- names: GeoNames' alternatenames in Latin script, capitalised, without numbers, airport and
  other codes; spellings that differ only in case, accents or punctuation once

## postcodes.tsv.gz ({postcodes} rows)

GeoNames postal codes `DE.zip`, `AT.zip`, `CH.zip`, `LI.zip`: one row per postcode and place
name with its point; names of PO boxes and districts cut to the town (Bern 15, Wien, Innere
Stadt), large customers (companies) left out; the region as in `towns.tsv.gz`.

## countries.tsv ({countries} countries)

Natural Earth 1:10m `admin_0_countries` (version {version}): every country or territory with an
ISO 3166-1 alpha-2 code (ISO_A2_EH), its label point (LABEL_Y, LABEL_X), the German name
(NAME_DE; Zypern, Taiwan, China, Kaimaninseln and Moldau instead of its long forms), the English
name and the long forms; England, Schottland, Wales and Nordirland from `admin_0_map_units`
with their ISO 3166-2 codes.

## country_names.txt and town_names.txt

Written by hand: the names of countries texts use that Natural Earth does not list (Holland,
USA, Weißrussland), and of towns that GeoNames does not list, each for a name of the lists
(Kischinau for Chişinău, Rapperswil-Jona for Rapperswil SG).

## Sources and licences

- GeoNames, <https://www.geonames.org/>, licensed under CC BY 4.0
  (<https://creativecommons.org/licenses/by/4.0/>):
  {SOURCES["cities500.zip"]}, {SOURCES["cities15000.zip"]},
  {SOURCES["admin1CodesASCII.txt"]}, {SOURCES["alternateNamesV2.zip"]},
  {GEONAMES}/zip/ (DE.zip, AT.zip, CH.zip, LI.zip).
- Natural Earth, <https://www.naturalearthdata.com/>, public domain:
  {SOURCES["ne_10m_admin_0_countries.zip"]}, {SOURCES["ne_10m_admin_0_map_units.zip"]}.
"""
    (OUT / "SOURCES.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

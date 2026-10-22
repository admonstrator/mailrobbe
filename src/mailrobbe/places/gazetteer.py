"""The lists shipped in data/ (D242 to D244): towns, postcodes and countries with their points.

    towns.tsv.gz       GeoNames: the towns of Germany, Austria, Switzerland and Liechtenstein
                       of at least 500 inhabitants or seats of an administrative unit, and the
                       world's of at least 15,000; most populous first, with their other names
    postcodes.tsv.gz   GeoNames: the postcodes of the four countries, per place name a point
    countries.tsv      Natural Earth: the countries at their label point, German and English
                       names and the long forms
    country_names.txt  names of countries texts use that Natural Earth does not list (by hand)
    town_names.txt     names of towns texts use that GeoNames does not list (by hand)

SOURCES.md names the files they were built from (scripts/places_data.py). Read once per
process: the towns for nearest_town and label_towns, their names for the step places.

Names are compared folded (fold): case, accents and punctuation do not count, and Sankt is St.
A town is found by its name or one of its other names (Munich, Mailand), a town of the four
countries also without what follows its name (Frankfurt for Frankfurt am Main, Halle for Halle
(Saale)). Of several towns, or several countries, of one name the most populous counts when it
has at least DOMINANCE times the inhabitants of the next; otherwise the name is ambiguous
(Neustadt). Towns closer than SAME_PLACE_KM count as one (GeoNames lists some municipalities
twice: Blankenfelde and Blankenfelde-Mahlow). locate_name gives a place entity its point (D242),
locate_location the location of an invitation (D243): a postcode followed by its town, else a
town named in it as a whole word, the longest name first.
"""

import gzip
import hashlib
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from mailrobbe.enums import PlaceStatus

DATA_DIR = Path(__file__).with_name("data")
# Raised when a rule of this module changes what a name or a location gives (places_version).
RULES = 1
NEAREST_LIMIT_KM = 50.0  # nearest_town names no town farther away than this
DOMINANCE = 10  # the most populous of several places of a name counts at this many times the next
SAME_PLACE_KM = 10.0  # places of one name closer than this to a more populous one are that one
DACH = frozenset({"DE", "AT", "CH", "LI"})
LABEL_DACH = 20_000  # label_towns: towns of the four countries of at least these inhabitants,
LABEL_WORLD = 500_000  # of the world of at least these, and every capital
EARTH_KM = 6371.0088  # mean radius
_CELL = 0.25  # degrees of a cell of nearest_town's grid


@dataclass(frozen=True, slots=True)
class Town:
    """A populated place of the lists."""

    name: str  # its German name where GeoNames has one (München, Mailand), else as GeoNames
    region: str | None  # the first administrative level: Bundesland, Bundesland, Kanton
    country: str  # ISO 3166-1 alpha-2, upper case
    latitude: float
    longitude: float
    population: int  # 0 when GeoNames knows none
    capital: bool  # the capital of its country


@dataclass(frozen=True, slots=True)
class Nearest:
    """The town nearest to a point."""

    town: Town
    distance_km: float  # great-circle distance
    bearing: float  # degrees clockwise from north, from the town towards the point


@dataclass(frozen=True, slots=True)
class Country:
    code: str  # ISO 3166-1 alpha-2; the parts of the United Kingdom by ISO 3166-2 (GB-ENG)
    name: str  # German
    latitude: float  # Natural Earth's label point
    longitude: float
    population: int


@dataclass(frozen=True, slots=True)
class Postcode:
    country: str
    code: str
    name: str  # the place as the postcode list writes it
    region: str | None
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class Located:
    """Where a place entity or an invitation's location lies (entity and calendar_event)."""

    status: PlaceStatus
    latitude: float | None = None  # with found
    longitude: float | None = None
    label: str | None = None  # what the point stands for (Frankfurt am Main, Hessen, Deutschland)


UNKNOWN = Located(PlaceStatus.UNKNOWN)
AMBIGUOUS = Located(PlaceStatus.AMBIGUOUS)


# Folding -----------------------------------------------------------------------------------

_NO_WORD = re.compile(r"[\W_]+")
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})
# What follows the name of a town of the four countries: Frankfurt am Main, Halle (Saale),
# Neustadt an der Weinstraße, Rothenburg ob der Tauber, Mühldorf a. Inn, Biel/Bienne.
_QUALIFIER = re.compile(
    r"\s*[(/,]|\s(?:am|an|im|in|ob|bei|vor|auf|unter|ad)\s|\s[aiobv]\.\s?\S", re.IGNORECASE
)


def fold(text: str) -> str:
    """A name as compared: case folded, the umlauts as ae, oe, ue (München is Muenchen, Mölln
    no Molln), other accents dropped, ß as ss, punctuation as spaces, the word Sankt as St."""
    text = text.casefold()
    if not text.isascii():
        text = unicodedata.normalize("NFC", text).translate(_UMLAUTS)
        decomposed = unicodedata.normalize("NFKD", text)
        text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join("st" if word == "sankt" else word for word in _NO_WORD.sub(" ", text).split())


def base_name(name: str) -> str | None:
    """A town's name without what follows it (Frankfurt am Main: Frankfurt), None when nothing
    follows."""
    found = _QUALIFIER.search(name)
    return name[: found.start()] if found and found.start() > 0 else None


# The lists ---------------------------------------------------------------------------------


def data_files() -> tuple[Path, ...]:
    """The lists the rules read, in name order (SOURCES.md is none)."""
    return tuple(sorted(path for path in DATA_DIR.iterdir() if path.suffix != ".md"))


def _table(name: str) -> Iterator[list[str]]:
    """The rows of a tab-separated list without its header line."""
    data = (DATA_DIR / name).read_bytes()
    text = gzip.decompress(data) if name.endswith(".gz") else data
    lines = text.decode("utf-8").splitlines()
    return (line.split("\t") for line in lines[1:])


@dataclass(frozen=True, slots=True)
class _Towns:
    towns: tuple[Town, ...]  # most populous first
    local: tuple[str, ...]  # per town its name as GeoNames writes it where that differs
    others: tuple[str, ...]  # per town its other names, joined by |


@cache
def _towns() -> _Towns:
    towns, local, others = [], [], []
    for row in _table("towns.tsv.gz"):
        name, own, country, region, lat, lon, population, capital, names = row
        towns.append(
            Town(name, region or None, country, float(lat), float(lon), int(population),
                 capital == "1")
        )  # fmt: skip
        local.append(own)
        others.append(names)
    return _Towns(tuple(towns), tuple(local), tuple(others))


Index = dict[str, tuple[int, ...]]  # folded name -> towns, most populous first


@dataclass(frozen=True, slots=True)
class _Names:
    own: Index  # by a town's own names: its German one and as GeoNames writes it
    other: Index  # by the other names of the towns of the four countries
    world: Index  # by the other names of the world's towns
    base: Index  # by the names of the four countries' towns without what follows them
    words: int  # words of the longest name locations are read by (own, other, base)


@cache
def _names() -> _Names:
    lists = _towns()
    own: defaultdict[str, list[int]] = defaultdict(list)
    other: defaultdict[str, list[int]] = defaultdict(list)
    world: defaultdict[str, list[int]] = defaultdict(list)
    base: defaultdict[str, list[int]] = defaultdict(list)
    for number, town in enumerate(lists.towns):
        names = [town.name, lists.local[number]]
        others = lists.others[number].split("|")
        dach = town.country in DACH
        _add(own, names, number)
        _add(other if dach else world, others, number)
        if dach:
            _add(base, [cut for name in (*names, *others) if (cut := base_name(name))], number)
    read = _finish(own), _finish(other), _finish(base)  # what locations are read by
    words = max(key.count(" ") + 1 for index in read for key in index)
    return _Names(read[0], read[1], _finish(world), read[2], words)


def _finish(index: defaultdict[str, list[int]]) -> Index:
    return {key: tuple(numbers) for key, numbers in index.items() if key}


def _add(index: defaultdict[str, list[int]], names: Sequence[str], number: int) -> None:
    for name in names:
        found = index[fold(name)]
        if not found or found[-1] != number:
            found.append(number)


@cache
def _countries() -> dict[str, Country]:
    return {
        code: Country(code, german, float(lat), float(lon), int(population))
        for code, german, _, lat, lon, population, _ in _table("countries.tsv")
    }


@cache
def _country_index() -> dict[str, tuple[str, ...]]:
    """Folded name -> codes of the countries of that name, most populous first."""
    index: defaultdict[str, set[str]] = defaultdict(set)
    countries = _countries()
    for code, german, english, *_, others in _table("countries.tsv"):
        for name in (german, english, *others.split("|")):
            index[fold(name)].add(code)
    for line in (DATA_DIR / "country_names.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, codes = line.partition(" = ")
            index[fold(name)].update(code.strip() for code in codes.split(","))
    index.pop("", None)
    return {
        key: tuple(sorted(codes, key=lambda code: (-countries[code].population, code)))
        for key, codes in index.items()
    }


@cache
def _postcodes() -> dict[str, tuple[Postcode, ...]]:
    """Postcode -> its places, in the order of the list (DE, AT, CH, LI)."""
    index: defaultdict[str, list[Postcode]] = defaultdict(list)
    for country, code, name, region, lat, lon in _table("postcodes.tsv.gz"):
        index[code].append(Postcode(country, code, name, region or None, float(lat), float(lon)))
    return {code: tuple(places) for code, places in index.items()}


@cache
def _postcode_names() -> dict[str, tuple[Postcode, ...]]:
    """Folded place name of the postcode list -> its postcodes."""
    index: defaultdict[str, list[Postcode]] = defaultdict(list)
    for places in _postcodes().values():
        for place in places:
            index[fold(place.name)].append(place)
    return {key: tuple(places) for key, places in index.items() if key}


@cache
def _town_aliases() -> dict[str, str]:
    """Folded name of town_names.txt -> the name of the lists it stands for."""
    aliases = {}
    for line in (DATA_DIR / "town_names.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, meant = line.partition(" = ")
            aliases[fold(name)] = meant.strip()
    return aliases


@cache
def places_version() -> str:
    """The version of the lists and the rules of the step places (model.PlaceFigures): RULES
    and every data file, as a short hash."""
    digest = hashlib.sha256(f"places {RULES}\n".encode())
    for path in data_files():
        digest.update(f"file {path.name} {path.stat().st_size}\n".encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


# Names to points ---------------------------------------------------------------------------


def dominant(populations: Sequence[int]) -> bool:
    """Whether the first of places of one name, most populous first, is the one meant: the only
    one, or one with at least DOMINANCE times the inhabitants of the next."""
    if len(populations) == 1:
        return True
    return populations[0] > 0 and populations[0] >= DOMINANCE * populations[1]


def country_name(code: str) -> str:
    """The German name of a country of the lists; the code for one they do not know."""
    country = _countries().get(code)
    return code if country is None else country.name


def place_label(name: str, region: str | None, country: str) -> str:
    """What a point stands for: the place, its region and its country in German, each once
    (Berlin, Deutschland; Frankfurt am Main, Hessen, Deutschland)."""
    parts: list[str] = []
    for part in (name, region, country_name(country)):
        if part and fold(part) not in (fold(seen) for seen in parts):
            parts.append(part)
    return ", ".join(parts)


def _decide(candidates: Sequence[int], own: Sequence[int], cut: Sequence[int] = ()) -> Located:
    """The town a name stands for among its candidates (most populous first): the most
    populous when dominant. Else the towns whose own name it is, first those of the four
    countries, then all: the most populous of them when dominant among them and no town of the
    same scope is more populous that has the name as its own or without what follows it (cut).
    So Kiel is Kiel, not Kehl, which GeoNames also calls Kiel; Heidelberg the one in Germany,
    not in South Africa; Neustadt stays ambiguous (Neustadt an der Weinstraße is larger than
    the towns called just Neustadt)."""
    towns = _towns().towns
    if _dominant_town(candidates):
        return _town_point(candidates[0])
    for scope in (DACH, None):
        within = [n for n in own if scope is None or towns[n].country in scope]
        rivals = [
            n for n in _merged(tuple(own), tuple(cut)) if scope is None or towns[n].country in scope
        ]
        if within and within[0] == rivals[0] and _dominant_town(within):
            return _town_point(within[0])
    return AMBIGUOUS


def _dominant_town(numbers: Sequence[int]) -> bool:
    """dominant over towns (most populous first), one closer than SAME_PLACE_KM to a more
    populous one counted as that one."""
    towns = _towns().towns
    distinct: list[Town] = []
    for number in numbers:
        town = towns[number]
        if not any(_near(town.latitude, town.longitude, seen) for seen in distinct):
            distinct.append(town)
    return dominant([town.population for town in distinct])


def _near(latitude: float, longitude: float, place: Town | Postcode) -> bool:
    return distance_km(latitude, longitude, place.latitude, place.longitude) < SAME_PLACE_KM


def _town_point(number: int) -> Located:
    town = _towns().towns[number]
    label = place_label(town.name, town.region, town.country)
    return Located(PlaceStatus.FOUND, town.latitude, town.longitude, label)


def _merged(*found: tuple[int, ...] | None) -> tuple[int, ...]:
    return tuple(sorted({number for numbers in found if numbers for number in numbers}))


def locate_name(label: str, detail: str | None) -> Located:
    """The point of a place entity (D242): a country (detail country) by its names; else a town
    by its own names, the other names of the four countries' towns or their names without what
    follows them, and only when none has it by the other names of the world's towns (which hold
    old and foreign names: Chattogram is also called Islamabad); the label without what follows
    it when nothing has the whole, among the towns of the region or country that follows when it
    names one (Friedberg (Hessen)); else a place of the postcode list whose postcodes lie
    together (Weinstadt). A name of town_names.txt is looked up as the name it stands for.
    Unknown when no place of the lists has that name."""
    key = fold(label)
    if detail == "country":
        codes = _country_index().get(key)
        if not codes:
            return UNKNOWN
        countries = _countries()
        if not dominant([countries[code].population for code in codes]):
            return AMBIGUOUS
        country = countries[codes[0]]
        return Located(PlaceStatus.FOUND, country.latitude, country.longitude, country.name)
    if (meant := _town_aliases().get(key)) is not None:
        label, key = meant, fold(meant)
    names = _names()
    base = base_name(label)
    keys = [(key, "")] if base is None else [(key, ""), (fold(base), fold(label[len(base) :]))]
    for key, follows in keys:
        own, cut = names.own.get(key, ()), names.base.get(key, ())
        candidates = _merged(own, names.other.get(key), cut)
        if candidates and follows and (named := _in_region(candidates, follows)):
            candidates, own, cut = named, _within(own, named), _within(cut, named)
        if candidates:
            return _decide(candidates, own, cut)
        world = names.world.get(key)
        if world:
            return _decide(world, ())
    for key, _ in keys:
        if places := _postcode_names().get(key):
            return _postcode_point(places)
    return UNKNOWN


def _in_region(numbers: tuple[int, ...], follows: str) -> tuple[int, ...]:
    """The towns whose region or country the folded words name (Hessen in Friedberg (Hessen))."""
    towns = _towns().towns
    words = f" {follows} "
    return tuple(
        number
        for number in numbers
        if any(
            part and f" {fold(part)} " in words
            for part in (towns[number].region, country_name(towns[number].country))
        )
    )


def _within(numbers: Sequence[int], kept: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(number for number in numbers if number in kept)


def _postcode_point(places: tuple[Postcode, ...]) -> Located:
    """A place of the postcode list: its first postcode's point when all its postcodes lie
    within SAME_PLACE_KM of it, else ambiguous (a village name of several regions)."""
    first = places[0]
    if not all(_near(place.latitude, place.longitude, first) for place in places[1:]):
        return AMBIGUOUS
    label = place_label(first.name, first.region, first.country)
    return Located(PlaceStatus.FOUND, first.latitude, first.longitude, label)


# A postcode of Germany (five digits) or Austria, Switzerland, Liechtenstein (four), with the
# country's prefix of old (D-, A-, CH-, FL-); not part of a longer number or a decimal (3.14).
_POSTCODE = re.compile(r"(?<![\w.,])(?:(D|A|CH|FL)-)?(\d{5}|\d{4})(?![\w]|[.,]\d)")
_PREFIXES = {"D": "DE", "A": "AT", "CH": "CH", "FL": "LI"}
_WORD = re.compile(r"\w+")
_SEGMENT = re.compile(r"[,;:|\n]")  # a town's name does not reach over these


def locate_location(location: str) -> Located:
    """The point of an invitation's location (D243): a postcode followed by its town (the
    postcode list decides; another word after it counts when the town is named elsewhere in the
    location) is the postcode's point; else a town of the lists named in it as a whole word,
    capitalised, the longest name first; else unknown (Raum 3.14, Teams-Besprechung). Locations
    are read by the towns' own names and the other names and names without what follows them of
    the four countries' towns only: the world's other names hold words a room has too (Raum for
    Rauma). An invitation without a location is no case for this (the step places leaves it
    alone)."""
    found = _postcode_place(location)
    if found is not None:
        return found
    return _named_town(location)


def _postcode_place(location: str) -> Located | None:
    folded = fold(location)
    for match in _POSTCODE.finditer(location):
        country = _PREFIXES.get(match.group(1) or "")
        code = match.group(2)
        places = [
            place
            for place in _postcodes().get(code, ())
            if (place.country == "DE") == (len(code) == 5) and country in (None, place.country)
        ]
        after = fold(location[match.end() :])
        place = next((place for place in places if _starts(after, place.name)), None)
        if place is None:
            place = next((place for place in places if _mentions(folded, place.name)), None)
        if place is not None:
            label = place_label(place.name, place.region, place.country)
            return Located(PlaceStatus.FOUND, place.latitude, place.longitude, label)
    return None


def _starts(text: str, name: str) -> bool:
    """Whether a folded text starts with the first word of the place's name (Frankfurt for
    Frankfurt am Main)."""
    first = fold(name).partition(" ")[0]
    return bool(first) and text.partition(" ")[0] == first


def _mentions(text: str, name: str) -> bool:
    """Whether a folded text names the place as whole words."""
    key = fold(name)
    return f" {key} " in f" {text} "


def _named_town(location: str) -> Located:
    """The town of the longest name the location names as whole words, beginning with a
    capital; unknown when it names none."""
    names = _names()
    best: tuple[int, ...] = ()
    best_own: tuple[int, ...] = ()
    best_cut: tuple[int, ...] = ()
    best_length = 0
    for segment in _SEGMENT.split(location):
        words = _WORD.findall(segment)
        keys = [fold(word) for word in words]
        for start, word in enumerate(words):
            if not word[0].isupper():
                continue
            for end in range(min(len(words), start + names.words), start, -1):
                key = " ".join(keys[start:end])
                if len(key) <= best_length:
                    break
                own, other = names.own.get(key, ()), names.other.get(key, ())
                cut = names.base.get(key, ())
                if own or other or cut:
                    best, best_own, best_cut = _merged(own, other, cut), own, cut
                    best_length = len(key)
                    break
    return _decide(best, best_own, best_cut) if best else UNKNOWN


# The nearest town --------------------------------------------------------------------------


Cell = tuple[tuple[float, float, int], ...]  # latitude, longitude and number of its towns


@cache
def _grid() -> dict[tuple[int, int], Cell]:
    cells: defaultdict[tuple[int, int], list[tuple[float, float, int]]] = defaultdict(list)
    for number, town in enumerate(_towns().towns):
        cells[_cell(town.latitude, town.longitude)].append((town.latitude, town.longitude, number))
    return {cell: tuple(towns) for cell, towns in cells.items()}


def _cell(latitude: float, longitude: float) -> tuple[int, int]:
    return math.floor(latitude / _CELL), math.floor(longitude / _CELL)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """The initial bearing from the first point towards the second, degrees from north."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta = math.radians(lon2 - lon1)
    y = math.sin(delta) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def nearest_town(latitude: float, longitude: float) -> Nearest | None:
    """The town of the lists nearest to the point, None when none is within NEAREST_LIMIT_KM.
    The towns of the grid cells within reach are compared on a flat projection around the
    point (exact enough at this reach), the distance given is the great-circle one."""
    towns, grid = _towns().towns, _grid()
    reach = NEAREST_LIMIT_KM / (math.pi * EARTH_KM / 180)  # degrees of latitude
    rows = math.ceil(reach / _CELL)
    edge = min(89.9, abs(latitude) + reach)
    columns = min(math.ceil(reach / math.cos(math.radians(edge)) / _CELL), int(180 / _CELL))
    cells_around = int(360 / _CELL)
    row, column = _cell(latitude, longitude)
    scale = math.cos(math.radians(latitude)) ** 2
    best, best_number = math.inf, -1
    for dr in range(-rows, rows + 1):
        for dc in range(-columns, columns + 1):
            wrapped = (column + dc + cells_around // 2) % cells_around - cells_around // 2
            for lat, lon, number in grid.get((row + dr, wrapped), ()):
                east = (lon - longitude + 180.0) % 360.0 - 180.0
                flat = (lat - latitude) ** 2 + east * east * scale
                if flat < best:
                    best, best_number = flat, number
    if best_number < 0:
        return None
    town = towns[best_number]
    distance = distance_km(town.latitude, town.longitude, latitude, longitude)
    if distance > NEAREST_LIMIT_KM:
        return None
    return Nearest(town, distance, bearing(town.latitude, town.longitude, latitude, longitude))


@cache
def label_towns() -> tuple[Town, ...]:
    """The towns the overview map labels: the capitals and the larger towns of the lists, most
    populous first."""
    return tuple(
        town
        for town in _towns().towns
        if town.capital
        or town.population >= LABEL_WORLD
        or (town.country in DACH and town.population >= LABEL_DACH)
    )

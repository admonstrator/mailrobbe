"""The shipped place lists and their rules (D242 to D244): names to points, invitation
locations, the nearest town and the towns of the overview map."""

import pytest

from mailrobbe.entities.gazetteer import entries
from mailrobbe.enums import PlaceStatus
from mailrobbe.places import gazetteer
from mailrobbe.places.gazetteer import (
    DACH,
    LABEL_DACH,
    NEAREST_LIMIT_KM,
    Located,
    base_name,
    bearing,
    distance_km,
    dominant,
    fold,
    label_towns,
    locate_location,
    locate_name,
    nearest_town,
    place_label,
    places_version,
)

FOUND = PlaceStatus.FOUND


def _entity_label(line: str) -> str:
    written, _, entity = line.partition(" = ")
    return entity or written


def _label(found: Located) -> str | None:
    assert found.status is FOUND, found
    return found.label


def test_lists_are_small_and_read_once() -> None:
    total = sum(path.stat().st_size for path in gazetteer.data_files())
    assert total < 4_000_000
    towns = gazetteer._towns().towns
    assert len(towns) > 40_000
    assert sum(town.country in DACH for town in towns) > 15_000
    assert [town.population for town in towns] == sorted(
        (town.population for town in towns), reverse=True
    )
    assert gazetteer._towns() is gazetteer._towns()
    assert all(-90 <= town.latitude <= 90 and -180 <= town.longitude <= 180 for town in towns)


def test_places_version_follows_rules_and_files(monkeypatch: pytest.MonkeyPatch) -> None:
    version = places_version()
    assert len(version) == 16 and int(version, 16) >= 0
    assert places_version() == version
    monkeypatch.setattr(gazetteer, "RULES", gazetteer.RULES + 1)
    assert places_version.__wrapped__() != version


def test_fold_and_base_name() -> None:
    assert fold("München") == fold("MUENCHEN") == "muenchen"
    assert fold("Mölln") != fold("Molln")
    assert fold("Sankt Gallen") == fold("St. Gallen") == "st gallen"
    assert fold("Zürich") == fold("Zuerich")
    assert fold("Genève") == "geneve"
    assert fold("Halle (Saale)") == "halle saale"
    assert fold("Weißenfels") == "weissenfels"
    assert base_name("Frankfurt am Main") == "Frankfurt"
    assert base_name("Halle (Saale)") == "Halle"
    assert base_name("Rothenburg ob der Tauber") == "Rothenburg"
    assert base_name("Mühldorf a. Inn") == "Mühldorf"
    assert base_name("Biel/Bienne") == "Biel"
    assert base_name("Berlin") is None
    assert base_name("Bad Homburg vor der Höhe") == "Bad Homburg"


def test_dominance() -> None:
    assert dominant([5])
    assert dominant([0])
    assert dominant([1000, 100])
    assert not dominant([999, 100])
    assert not dominant([0, 0])


def test_place_label_names_each_part_once() -> None:
    assert (
        place_label("Frankfurt am Main", "Hessen", "DE") == "Frankfurt am Main, Hessen, Deutschland"
    )
    assert place_label("Berlin", "Berlin", "DE") == "Berlin, Deutschland"
    assert place_label("Wien", "Wien", "AT") == "Wien, Österreich"
    assert place_label("Vaduz", None, "LI") == "Vaduz, Liechtenstein"
    assert place_label("Nowhere", None, "QQ") == "Nowhere, QQ"


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("Frankfurt", "Frankfurt am Main, Hessen, Deutschland"),
        ("Frankfurt am Main", "Frankfurt am Main, Hessen, Deutschland"),
        ("Frankfurt a.M.", "Frankfurt am Main, Hessen, Deutschland"),
        ("Frankfurt (Oder)", "Frankfurt (Oder), Brandenburg, Deutschland"),
        ("München", "München, Bayern, Deutschland"),
        ("Muenchen", "München, Bayern, Deutschland"),
        ("Munich", "München, Bayern, Deutschland"),
        ("MÜNCHEN", "München, Bayern, Deutschland"),
        ("Mailand", "Mailand, Lombardei, Italien"),
        ("Wien", "Wien, Österreich"),
        ("Vienna", "Wien, Österreich"),
        ("St. Gallen", "St. Gallen, Schweiz"),
        ("Sankt Gallen", "St. Gallen, Schweiz"),
        ("Genf", "Genf, Schweiz"),
        ("Halle (Saale)", "Halle (Saale), Sachsen-Anhalt, Deutschland"),
        (
            "Kiel",
            "Kiel, Schleswig-Holstein, Deutschland",
        ),  # not Kehl, which GeoNames also calls Kiel
        ("Heidelberg", "Heidelberg, Baden-Württemberg, Deutschland"),  # not the South African one
        ("Friedberg (Hessen)", "Friedberg, Hessen, Deutschland"),  # the region decides
        ("Weinstadt", "Weinstadt, Baden-Württemberg, Deutschland"),  # the postcode list has it
        ("Kischinau", "Chişinău, Gemeinde Chişinău, Moldau"),  # town_names.txt
        ("Blankenfelde-Mahlow", "Blankenfelde-Mahlow, Brandenburg, Deutschland"),  # listed twice
    ],
)
def test_town_names(name: str, label: str) -> None:
    assert _label(locate_name(name, "city")) == label


def test_town_point() -> None:
    found = locate_name("Berlin", "city")
    assert found.latitude == pytest.approx(52.52, abs=0.05)
    assert found.longitude == pytest.approx(13.40, abs=0.05)


@pytest.mark.parametrize("name", ["Neustadt", "Friedberg", "Landau", "Halle"])
def test_names_of_several_towns_are_ambiguous(name: str) -> None:
    assert locate_name(name, "city").status is PlaceStatus.AMBIGUOUS


@pytest.mark.parametrize("name", ["Entenhausen", "Xyzzyhausen", "", "  "])
def test_unknown_names(name: str) -> None:
    found = locate_name(name, "city")
    assert found.status is PlaceStatus.UNKNOWN
    assert (found.latitude, found.longitude, found.label) == (None, None, None)


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("Deutschland", "Deutschland"),
        ("Germany", "Deutschland"),
        ("Bundesrepublik Deutschland", "Deutschland"),
        ("Holland", "Niederlande"),
        ("USA", "Vereinigte Staaten"),
        ("Kongo", "Demokratische Republik Kongo"),  # ten times the inhabitants of the other
        ("Schottland", "Schottland"),
        ("Großbritannien", "Vereinigtes Königreich"),
    ],
)
def test_country_names(name: str, label: str) -> None:
    assert _label(locate_name(name, "country")) == label


def test_country_point_and_ambiguous_country() -> None:
    found = locate_name("Schweiz", "country")
    assert found.latitude is not None and found.longitude is not None
    assert 45.8 < found.latitude < 47.8 and 5.9 < found.longitude < 10.5  # within the country
    assert locate_name("Korea", "country").status is PlaceStatus.AMBIGUOUS
    assert locate_name("Narnia", "country").status is PlaceStatus.UNKNOWN


def test_every_country_of_the_entity_list_resolves() -> None:
    missed = [
        label
        for line in entries("countries.txt")
        if locate_name(label := _entity_label(line), "country").status is not FOUND
    ]
    assert len(missed) <= 3, missed  # Korea is two countries


def test_the_towns_of_the_entity_list_resolve() -> None:
    labels = [_entity_label(line) for line in entries("cities.txt")]
    found = [label for label in labels if locate_name(label, "city").status is FOUND]
    unknown = [
        label for label in labels if locate_name(label, "city").status is PlaceStatus.UNKNOWN
    ]
    assert len(found) / len(labels) > 0.95
    assert len(unknown) <= 5, unknown


def test_every_hand_written_town_name_resolves() -> None:
    for name in gazetteer._town_aliases():
        assert locate_name(name, "city").status is FOUND, name


@pytest.mark.parametrize(
    ("location", "label"),
    [
        ("Rathaus, Marktplatz 1, 99423 Weimar", "Weimar, Thüringen, Deutschland"),
        ("Hotel Elephant, Markt 19, 99423 Weimar", "Weimar, Thüringen, Deutschland"),
        ("D-99423 Weimar", "Weimar, Thüringen, Deutschland"),
        ("CH-8001 Zürich, Bahnhofstrasse 1", "Zürich, Schweiz"),
        ("1010 Wien", "Wien, Österreich"),
        ("5610 Wohlen", "Wohlen AG, Aargau, Schweiz"),  # the postcode decides between the Wohlens
        ("60311 Frankfurt", "Frankfurt am Main, Hessen, Deutschland"),
        ("Hotel am Markt, Weimar", "Weimar, Thüringen, Deutschland"),
        ("Messe Frankfurt, Halle 3", "Frankfurt am Main, Hessen, Deutschland"),
        ("Konferenzraum Berlin", "Berlin, Deutschland"),
        ("Am Markt 12, Köln", "Köln, Nordrhein-Westfalen, Deutschland"),  # not Markt in Austria
        ("Treffen in Berlin", "Berlin, Deutschland"),  # not Treffen am Ossiacher See
        ("Grugahalle, Essen", "Essen, Nordrhein-Westfalen, Deutschland"),
        ("Sitzung in Hof", "Hof, Bayern, Deutschland"),
        (
            "Stadthalle Neustadt an der Weinstraße",
            "Neustadt an der Weinstraße, Rheinland-Pfalz, Deutschland",
        ),
    ],
)
def test_locations(location: str, label: str) -> None:
    assert _label(locate_location(location)) == label


def test_postcode_point() -> None:
    by_postcode = locate_location("Marktplatz 1, 99423 Weimar")
    by_name = locate_location("Weimar")
    assert by_postcode.status is by_name.status is FOUND
    assert (by_postcode.latitude, by_postcode.longitude) != (by_name.latitude, by_name.longitude)


@pytest.mark.parametrize(
    "location",
    [
        "Raum 3.14",
        "Teams-Besprechung",
        "Video call",
        "Besprechungsraum 4",
        "Meeting room 3",
        "Room 2.7",
        "Telefonkonferenz; Einwahl folgt",
        "Kantine, 1. OG",
        "https://teams.example/meet/123456",
        "Einwahl: +49 30 1234 5678",
        "Großer Saal",
        "Haus am See",
        "Café Central",
        "Sitzungssaal Rathaus Hof",  # a common word, alone only after in, aus, nach, bei
        "Essen",
    ],
)
def test_locations_without_a_town(location: str) -> None:
    assert locate_location(location).status is PlaceStatus.UNKNOWN


def test_location_of_several_towns_is_ambiguous() -> None:
    assert locate_location("Stadthalle Neustadt").status is PlaceStatus.AMBIGUOUS


def test_distance_and_bearing() -> None:
    assert distance_km(50.0, 8.0, 50.0, 8.0) == 0.0
    assert distance_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.2, abs=0.1)
    assert distance_km(0.0, 179.9, 0.0, -179.9) == pytest.approx(22.2, abs=0.1)
    assert bearing(50.0, 8.0, 51.0, 8.0) == pytest.approx(0.0, abs=0.01)
    assert bearing(50.0, 8.0, 50.0, 9.0) == pytest.approx(89.6, abs=0.1)
    assert bearing(50.0, 8.0, 49.0, 8.0) == pytest.approx(180.0, abs=0.01)
    assert bearing(50.0, 8.0, 50.0, 7.0) == pytest.approx(270.4, abs=0.1)


def test_nearest_town() -> None:
    near = nearest_town(52.52, 13.45)  # east of Berlin's centre
    assert near is not None
    assert near.town.name == "Berlin"
    assert near.distance_km == pytest.approx(2.7, abs=0.3)
    assert 80 < near.bearing < 110  # the point lies east of the town
    zurich = nearest_town(47.37, 8.54)
    assert zurich is not None and zurich.town.name == "Zürich" and zurich.distance_km < 2


@pytest.mark.parametrize(
    ("latitude", "longitude"), [(0.0, 0.0), (89.9, 10.0), (-89.9, 0.0), (40.0, -40.0)]
)
def test_no_town_nearby(latitude: float, longitude: float) -> None:
    assert nearest_town(latitude, longitude) is None


def test_nearest_town_is_the_nearest_of_all() -> None:
    towns = gazetteer._towns().towns
    for latitude, longitude in ((50.0, 8.6), (47.05, 9.5), (-33.9, 151.2), (64.1, -21.9)):
        near = nearest_town(latitude, longitude)
        best = min(
            towns, key=lambda town: distance_km(town.latitude, town.longitude, latitude, longitude)
        )
        assert near is not None
        assert near.town == best
        assert near.distance_km <= NEAREST_LIMIT_KM


def test_label_towns() -> None:
    towns = label_towns()
    assert 1_000 < len(towns) < 3_000
    names = {town.name for town in towns}
    assert {"Berlin", "Wien", "Bern", "Zürich", "Vaduz", "Paris", "Tokyo"} <= names
    assert all(town.capital or town.population >= LABEL_DACH for town in towns)
    assert [town.population for town in towns] == sorted(
        (town.population for town in towns), reverse=True
    )

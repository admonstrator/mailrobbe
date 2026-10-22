"""The lists shipped in data/ (D242 to D244): towns, postcodes and countries with their points.

Read once per process. The places step turns the names of place entities and the locations of
invitations into points with them; the API names the nearest town of a photo and the overview
map's town labels from them.
"""

from dataclasses import dataclass

NEAREST_LIMIT_KM = 50.0  # nearest_town names no town farther away than this


@dataclass(frozen=True, slots=True)
class Town:
    """A populated place of the lists."""

    name: str  # as GeoNames writes it (Frankfurt am Main)
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


def nearest_town(latitude: float, longitude: float) -> Nearest | None:
    """The town of the lists nearest to the point, None when none is within NEAREST_LIMIT_KM."""
    return None  # the contract's placeholder; the lists come with the places step


def label_towns() -> tuple[Town, ...]:
    """The towns the overview map labels: the capitals and the larger towns of the lists, most
    populous first."""
    return ()  # the contract's placeholder; the lists come with the places step

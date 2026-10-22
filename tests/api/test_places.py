"""The places API (D247, D248): photos with a position, one photo, photos around a point, the
places of texts and invitations and their summary; the mail filter photo_area and the position
in MetadataSummary (D249).

The archive is a copy of the imported one with known rows written in SQL (PLACE_ROWS), so that
the API is tested apart from the metadata and places steps. The first seven originals by id
(k=1 to 7) and the first duplicate (k=8) are moved into 1975, where no other mail is; k=7 is
hidden by a rule. Photos (documents 9001 to 9010, 9008 a text without a position):

    9001  Berlin           k=1 and the duplicate  Canon EOS R6     taken 2021-05-06, altitude
    9002  Potsdam          k=2                    Canon EOS R6     GPS time only
    9003  Fiji, east       k=3                    Apple iPhone 12  2020-01-01
    9004  Fiji, west       k=4                    Apple iPhone 12  no capture time but a text
    9005  Munich           only the hidden mail   Canon EOS R6     2021-07-07
    9006  Hamburg          the hidden mail, k=5   Nikon D750       2018-03-03
    9007  near the pole    k=6                    none
    9009  Cologne          only the duplicate     Nikon D750       2022-02-02
    9010  Bremen           no mail at all

Place entities: Berlin (k=1 to 3 and the hidden mail; stored mails 4), Österreich (in document
9008, carried by k=4 and k=5), Hamburg (only in the duplicate; stored mails 0), one ambiguous,
one unknown and one not looked at. Events: two at one Berlin point (k=1, k=2) and one more there
in the hidden mail, Vienna without a known instant (k=3), a room (unknown), an empty location
and one not looked at.
"""

import asyncio
import math
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import make_url, pool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailrobbe.api import places as places_api
from mailrobbe.api.schemas import (
    MailDetail,
    MailFilters,
    MailSelection,
    PhotoDetail,
    PhotoList,
    TextPlaces,
)
from mailrobbe.api.selection import resolve_selection
from mailrobbe.config import Settings
from mailrobbe.enums import DocumentKind
from mailrobbe.places import gazetteer
from mailrobbe.places.gazetteer import Nearest, Town
from mailrobbe.preview.kinds import preview_kind
from tests.api.conftest import _client, _execute, api_settings
from tests.api.test_mails import Params, export, get, rows
from tests.conftest import GeneratedArchive, _temporary_database

pytestmark = pytest.mark.db

YEAR = [("date_from", "1975-01-01"), ("date_to", "1975-12-31")]
FIJI = "179,-18,-179,-16"  # across the 180th meridian
FIGURES_VERSION = "test-lists"

PLACE_ROWS = [
    # what the import's steps may have found is replaced by the known rows
    """UPDATE document SET metadata_latitude = NULL, metadata_longitude = NULL,
        metadata_gps_time = NULL""",
    "DELETE FROM entity WHERE kind = 'place'",
    "DELETE FROM calendar_event",
    "DELETE FROM global_stats WHERE key = 'places'",
    """CREATE TEMP TABLE pick AS SELECT id, row_number() OVER (ORDER BY id) AS k FROM mail
        WHERE is_duplicate_of IS NULL ORDER BY id LIMIT 7""",
    """INSERT INTO pick SELECT id, 8 FROM mail WHERE is_duplicate_of IS NOT NULL
        ORDER BY id LIMIT 1""",
    """UPDATE mail SET date_utc = d.at, has_attachments = true
        FROM pick JOIN (VALUES (1, timestamptz '1975-01-10 12:00+00'), (2, '1975-02-10 12:00+00'),
            (3, '1975-03-10 12:00+00'), (4, '1975-04-10 12:00+00'), (5, '1975-05-10 12:00+00'),
            (6, '1975-06-10 12:00+00'), (7, '1975-04-20 12:00+00'), (8, '1975-08-10 12:00+00'))
            AS d (k, at) ON d.k = pick.k
        WHERE mail.id = pick.id""",
    """INSERT INTO hide_rule (id, name, automated) OVERRIDING SYSTEM VALUE
        VALUES (901, 'Test', true)""",
    "INSERT INTO mail_hidden (rule_id, mail_id) SELECT 901, id FROM pick WHERE k = 7",
    """INSERT INTO document (id, sha256, name, names, mime_type, size_bytes, kind, text_status,
            metadata_status, metadata_fields, metadata_device, metadata_created, metadata_gps,
            metadata_latitude, metadata_longitude, metadata_gps_time, extracted_text)
        OVERRIDING SYSTEM VALUE
        SELECT id, 'places-' || id, name, name, mime, 2048, CAST(kind AS document_kind),
            CAST(status AS document_text_status), 'found', CAST(fields AS jsonb), device,
            created, lat IS NOT NULL, lat, lon, gps, body
        FROM (VALUES
            (9001, 'berlin.jpg', 'image/jpeg', 'image', 'unsupported',
             '{"exif": {"datetime_original": "2021-05-06T10:00:00+02:00"},
               "gps": {"latitude": 52.52, "longitude": 13.405, "altitude": 34.5}}',
             'Canon EOS R6', timestamptz '2021-05-06 08:00+00', 52.52, 13.405,
             timestamptz '2021-05-06 08:00:05+00', CAST(NULL AS text)),
            (9002, 'potsdam.jpg', 'image/jpeg', 'image', 'unsupported',
             '{"exif": {"datetime_original": "2021-06-01T11:00:00"},
               "gps": {"latitude": 52.4, "longitude": 13.06, "timestamp": "2021-06-01T09:00:00Z"}}',
             'Canon EOS R6', NULL, 52.4, 13.06, '2021-06-01 09:00+00', NULL),
            (9003, 'fiji-east.jpg', 'image/jpeg', 'image', 'unsupported', '{"gps": {}}',
             'Apple iPhone 12', '2020-01-01 00:00+00', -17.0, 179.95, NULL, NULL),
            (9004, 'fiji-west.jpg', 'image/jpeg', 'image', 'unsupported',
             '{"exif": {"datetime_original": "2019-07-01T12:00:00"}}',
             'Apple iPhone 12', NULL, -17.0, -179.9, NULL, NULL),
            (9005, 'muenchen.jpg', 'image/jpeg', 'image', 'unsupported', '{"gps": {}}',
             'Canon EOS R6', '2021-07-07 12:00+00', 48.137, 11.575, NULL, NULL),
            (9006, 'hamburg.jpg', 'image/jpeg', 'image', 'unsupported', '{"gps": {}}',
             'Nikon D750', '2018-03-03 12:00+00', 53.55, 9.99, NULL, NULL),
            (9007, 'pol.jpg', 'image/jpeg', 'image', 'unsupported', '{"gps": {}}',
             NULL, NULL, 89.9, 0.0, NULL, NULL),
            (9008, 'liste.txt', 'text/plain', 'text', 'text', '{}', NULL, NULL, NULL, NULL,
             NULL, 'Reise nach Österreich'),
            (9009, 'koeln.jpg', 'image/jpeg', 'image', 'unsupported', '{"gps": {}}',
             'Nikon D750', '2022-02-02 12:00+00', 50.94, 6.96, NULL, NULL),
            (9010, 'bremen.jpg', 'image/jpeg', 'image', 'unsupported', '{"gps": {}}',
             NULL, NULL, 53.08, 8.8, NULL, NULL))
            AS d (id, name, mime, kind, status, fields, device, created, lat, lon, gps, body)""",
    """INSERT INTO attachment (mail_id, filename, mime_type, size_bytes, sha256, position,
            document_id)
        SELECT pick.id, d.name, d.mime_type, d.size_bytes, d.sha256, 80 + c.n, d.id
        FROM (VALUES (9001, 1, 0), (9001, 8, 0), (9002, 2, 0), (9003, 3, 0), (9004, 4, 0),
                (9005, 7, 0), (9006, 7, 1), (9006, 5, 0), (9007, 6, 0), (9008, 4, 1),
                (9008, 5, 1), (9009, 8, 1))
            AS c (document_id, k, n)
        JOIN pick ON pick.k = c.k JOIN document d ON d.id = c.document_id""",
    # the earliest original carrying it, as finalize sets it; 9010 has none
    """UPDATE document d SET first_mail_id = f.mail_id FROM (
            SELECT DISTINCT ON (a.document_id) a.document_id, m.id AS mail_id
            FROM attachment a JOIN mail m ON m.id = a.mail_id WHERE a.document_id > 9000
            ORDER BY a.document_id, m.is_duplicate_of IS NOT NULL, m.date_utc, m.id) f
        WHERE d.id = f.document_id""",
    """INSERT INTO entity (id, kind, key, label, detail, latitude, longitude, place_status,
            place_label, mails)
        OVERRIDING SYSTEM VALUE VALUES
        (9101, 'place', 'zz berlin', 'Berlin', 'city', 52.52, 13.405, 'found',
         'Berlin, Berlin, DE', 4),
        (9102, 'place', 'zz österreich', 'Österreich', 'country', 47.6, 14.1, 'found',
         'Österreich, AT', 2),
        (9103, 'place', 'zz neustadt', 'Neustadt', 'city', NULL, NULL, 'ambiguous', NULL, 2),
        (9104, 'place', 'zz atlantis', 'Atlantis', 'city', NULL, NULL, 'unknown', NULL, 1),
        (9105, 'place', 'zz hamburg', 'Hamburg', 'city', 53.55, 9.99, 'found',
         'Hamburg, Hamburg, DE', 0),
        (9106, 'place', 'zz bonn', 'Bonn', 'city', NULL, NULL, NULL, NULL, 1)""",
    """INSERT INTO mail_entity (entity_id, mail_id, occurrences, context, position)
        SELECT 9101, id, 1, 0, 0 FROM pick WHERE k IN (1, 2, 3, 7)
        UNION ALL SELECT 9103, id, 1, 0, 0 FROM pick WHERE k IN (1, 2)
        UNION ALL SELECT 9105, id, 1, 0, 0 FROM pick WHERE k = 8""",
    """INSERT INTO document_entity (entity_id, document_id, occurrences, context, position)
        VALUES (9102, 9008, 1, 0, 9)""",
    """INSERT INTO calendar_event (mail_id, position, kind, summary, location, starts_at,
            starts_local, latitude, longitude, place_status, place_label, uid)
        SELECT pick.id, 0, 'request', e.summary, e.location, e.starts_at, e.starts_local,
            e.lat, e.lon, e.status, e.label, 'uid-' || e.k
        FROM (VALUES
            (1, 'Treffen 1', '10117 Berlin', timestamptz '1975-01-20 10:00+00',
             timestamp '1975-01-20 11:00', 52.517, 13.3889, 'found', '10117 Berlin, Berlin, DE'),
            (2, 'Treffen 2', 'Berlin Mitte', '1975-02-20 10:00+00', NULL, 52.517, 13.3889,
             'found', '10117 Berlin, Berlin, DE'),
            (7, 'Treffen 7', '10117 Berlin', '1975-04-25 10:00+00', NULL, 52.517, 13.3889,
             'found', '10117 Berlin, Berlin, DE'),
            (3, 'Wien', 'Wien', NULL, '1975-03-20 09:00', 48.2082, 16.3738, 'found',
             'Wien, Wien, AT'),
            (4, 'Raum', 'Raum 3', NULL, NULL, NULL, NULL, 'unknown', NULL),
            (5, 'Leer', '', NULL, NULL, NULL, NULL, NULL, NULL),
            (6, 'Hamburg', 'Hamburg', NULL, NULL, NULL, NULL, NULL, NULL))
            AS e (k, summary, location, starts_at, starts_local, lat, lon, status, label)
        JOIN pick ON pick.k = e.k""",
    f"""INSERT INTO global_stats (key, value) VALUES ('places',
        '{{"computed_at": "2026-10-20T12:00:00+00:00", "version": "{FIGURES_VERSION}"}}')""",
    "ANALYZE",
]


@pytest.fixture(scope="module")
def places_database_url(database_server_url: str, imported_database_url: str) -> Iterator[str]:
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        asyncio.run(_execute(url, PLACE_ROWS))
        yield url


@pytest.fixture(scope="module")
def mails(places_database_url: str) -> dict[int, int]:
    """Mail id by k (1 to 6 originals, 7 the hidden one, 8 the duplicate)."""
    found = asyncio.run(
        rows(
            places_database_url,
            "SELECT id, row_number() OVER (ORDER BY id) AS k FROM mail"
            " WHERE is_duplicate_of IS NULL ORDER BY id LIMIT 7",
        )
    )
    duplicate = asyncio.run(
        rows(
            places_database_url,
            "SELECT id FROM mail WHERE is_duplicate_of IS NOT NULL ORDER BY id LIMIT 1",
        )
    )
    return {row.k: row.id for row in found} | {8: duplicate[0].id}


@pytest.fixture
async def places_client(
    places_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings(places_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


async def point_ids(client: httpx.AsyncClient, params: Params = ()) -> list[int]:
    found = await get(client, "/api/places/photos", params)
    assert found["total"] == len(found["points"]) and not found["truncated"]
    return [point["id"] for point in found["points"]]


async def test_only_my_mails_are_in_1975(
    places_client: httpx.AsyncClient, mails: dict[int, int]
) -> None:
    listed = await get(places_client, "/api/mails", [*YEAR, ("include_hidden", "true")])
    assert {item["id"] for item in listed["items"]} == set(mails.values())


# Photos ---------------------------------------------------------------------------------------


async def test_the_photos_of_the_whole_archive(places_client: httpx.AsyncClient) -> None:
    found = await get(places_client, "/api/places/photos")
    assert found["points"][0] == {"id": 9001, "lat": 52.52, "lon": 13.405}
    # 9005 only in the hidden mail, 9010 in none; 9008 has no position
    assert await point_ids(places_client) == [9001, 9002, 9003, 9004, 9006, 9007, 9009]
    hidden = [("include_hidden", "true")]
    assert await point_ids(places_client, hidden) == [
        9001,
        9002,
        9003,
        9004,
        9005,
        9006,
        9007,
        9009,
    ]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (YEAR, [9001, 9002, 9003, 9004, 9006, 9007, 9009]),
        ([*YEAR, ("include_hidden", "true")], [9001, 9002, 9003, 9004, 9005, 9006, 9007, 9009]),
        ([("hide_duplicates", "true")], [9001, 9002, 9003, 9004, 9006, 9007]),
        ([("date_to", "1975-01-31")], [9001]),
        ([("date_from", "1975-04-15"), ("date_to", "1975-05-31")], [9006]),
        (
            [("date_from", "1975-04-15"), ("date_to", "1975-05-31"), ("include_hidden", "true")],
            [9005, 9006],
        ),
        ([("taken_from", "2021-01-01")], [9001, 9002, 9009]),
        ([("taken_to", "2021-05-06")], [9001, 9003, 9006]),
        ([("taken_to", "2021-05-05")], [9003, 9006]),
        ([("taken_from", "2021-05-07"), ("taken_to", "2021-06-01")], [9002]),
        ([("taken_to", "9999-12-31")], [9001, 9002, 9003, 9006, 9009]),
        ([("device", "Canon EOS R6")], [9001, 9002]),
        ([("device", "Canon EOS R6"), ("include_hidden", "true")], [9001, 9002, 9005]),
        ([("device", "canon eos r6")], []),
        ([("photo_area", FIJI)], [9003, 9004]),
        ([("photo_area", "179,-18,179.99,-16")], [9003]),
    ],
)
async def test_the_photos_under_the_filters(
    places_client: httpx.AsyncClient, params: Params, expected: list[int]
) -> None:
    assert await point_ids(places_client, params) == expected


async def test_the_points_are_cut_at_their_limit(
    places_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(places_api, "PHOTO_POINT_LIMIT", 3)
    found = await get(places_client, "/api/places/photos")
    assert [point["id"] for point in found["points"]] == [9001, 9002, 9003]
    assert (found["total"], found["truncated"]) == (7, True)


async def test_a_research_filter_reaches_the_photos(
    places_database_url: str, places_client: httpx.AsyncClient, mails: dict[int, int]
) -> None:
    await _execute(
        places_database_url,
        [
            "INSERT INTO tag (id, name, color) OVERRIDING SYSTEM VALUE"
            " VALUES (901, 'Orte', 'blue')",
            "INSERT INTO mail_tag (tag_id, mail_sha256)"
            " SELECT 901, raw_sha256 FROM mail WHERE id = :id",
        ],
        id=mails[3],
    )
    try:
        assert await point_ids(places_client, [("tag", "901")]) == [9003]
    finally:
        await rows(places_database_url, "DELETE FROM tag WHERE id = 901")


async def test_invalid_place_filters(places_client: httpx.AsyncClient) -> None:
    for params, status in (
        ([("taken_from", "gestern")], 422),
        ([("photo_area", "200,0,10,10")], 400),
        ([("photo_area", "0,10,10,0")], 400),  # south above north
        ([("photo_area", "0,-91,10,10")], 400),
        ([("photo_area", "abc")], 422),
        ([("person_role", "sent")], 400),  # needs exactly one person
    ):
        found = await get(places_client, "/api/places/photos", params, status=status)
        if status == 400:
            assert found["detail"]["code"] == "invalid_filter"


# One photo ------------------------------------------------------------------------------------


def nearest_at(found: Nearest | None) -> Any:
    calls: list[tuple[float, float]] = []

    def nearest_town(latitude: float, longitude: float) -> Nearest | None:
        calls.append((latitude, longitude))
        return found

    nearest_town.calls = calls  # type: ignore[attr-defined]
    return nearest_town


BERLIN = Town("Berlin", "Berlin", "DE", 52.52, 13.405, 3_600_000, True)


async def test_one_photo_with_its_mails_and_the_nearest_town(
    places_database_url: str,
    places_client: httpx.AsyncClient,
    mails: dict[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    town = nearest_at(Nearest(BERLIN, 2.04, 10.0))
    monkeypatch.setattr(gazetteer, "nearest_town", town)
    raw = await get(places_client, "/api/places/photos/9001")
    detail = PhotoDetail.model_validate(raw)
    assert town.calls == [(52.52, 13.405)]
    occurrence = await rows(
        places_database_url,
        "SELECT id FROM attachment WHERE document_id = 9001 AND mail_id = :id",
        id=mails[1],
    )
    assert detail.attachment_id == occurrence[0].id  # in the earliest mail
    assert (detail.document_id, detail.name, detail.mime_type) == (9001, "berlin.jpg", "image/jpeg")
    assert detail.preview == preview_kind(
        DocumentKind.IMAGE,
        "berlin.jpg",
        "image/jpeg",
        2048,
        hashed=True,
        max_size=Settings().preview_max_size,
    )
    assert (detail.latitude, detail.longitude, detail.altitude) == (52.52, 13.405, 34.5)
    assert detail.taken_at == datetime(2021, 5, 6, 8, tzinfo=UTC)
    assert (detail.taken_text, detail.device) == (None, "Canon EOS R6")
    assert detail.nearest is not None
    assert detail.nearest.model_dump() == {
        "name": "Berlin",
        "region": "Berlin",
        "country": "DE",
        "distance_km": 2.0,
        "direction": "N",
    }
    # the duplicate too, later; with sender and recipients as the mail list shows them
    assert [mail.id for mail in detail.mails] == [mails[1], mails[8]]
    assert detail.mail_count == 2
    listed = await get(places_client, "/api/mails", [("document", "9001")])
    by_id = {item["id"]: item for item in listed["items"]}
    for mail in raw["mails"]:
        item = by_id[mail["id"]]
        assert mail["sender"] == item["sender"] and mail["recipients"] == item["recipients"]
        assert (mail["date"], mail["subject"]) == (item["date"], item["subject"])
        assert mail["recipient_count"] == item["recipient_count"]


async def test_a_photo_of_a_hidden_mail_and_one_without_a_capture_time(
    places_client: httpx.AsyncClient, mails: dict[int, int]
) -> None:
    hidden = PhotoDetail.model_validate(await get(places_client, "/api/places/photos/9005"))
    assert [mail.id for mail in hidden.mails] == [mails[7]]  # the detail shows it (D222)
    assert hidden.nearest is None  # the lists are not there
    gps_only = PhotoDetail.model_validate(await get(places_client, "/api/places/photos/9002"))
    assert gps_only.taken_at == datetime(2021, 6, 1, 9, tzinfo=UTC)
    assert gps_only.taken_text is None and gps_only.altitude is None
    undated = PhotoDetail.model_validate(await get(places_client, "/api/places/photos/9004"))
    assert (undated.taken_at, undated.taken_text) == (None, "2019-07-01T12:00:00")
    pole = PhotoDetail.model_validate(await get(places_client, "/api/places/photos/9007"))
    assert (pole.taken_at, pole.taken_text, pole.device) == (None, None, None)


async def test_the_mails_of_a_photo_are_cut_at_their_limit(
    places_client: httpx.AsyncClient, mails: dict[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(places_api, "PHOTO_MAILS_LIMIT", 1)
    detail = PhotoDetail.model_validate(await get(places_client, "/api/places/photos/9006"))
    assert [mail.id for mail in detail.mails] == [mails[7]]  # the hidden one is the earlier
    assert detail.mail_count == 2


@pytest.mark.parametrize(
    ("distance", "bearing", "expected"),
    [
        (0.49, 90.0, (0.5, None)),  # in the town
        (0.5, 0.0, (0.5, "N")),
        (3.0, 22.4, (3.0, "N")),
        (3.0, 22.5, (3.0, "NO")),
        (3.0, 90.0, (3.0, "O")),
        (3.0, 135.0, (3.0, "SO")),
        (12.34, 180.0, (12.3, "S")),
        (3.0, 225.0, (3.0, "SW")),
        (3.0, 270.0, (3.0, "W")),
        (3.0, 337.4, (3.0, "NW")),
        (3.0, 359.9, (3.0, "N")),
        (3.0, -45.0, (3.0, "NW")),
    ],
)
def test_the_direction_from_the_nearest_town(
    monkeypatch: pytest.MonkeyPatch,
    distance: float,
    bearing: float,
    expected: tuple[float, str | None],
) -> None:
    monkeypatch.setattr(gazetteer, "nearest_town", nearest_at(Nearest(BERLIN, distance, bearing)))
    found = places_api.nearest(52.5, 13.4)
    assert found is not None
    assert (found.distance_km, found.direction) == expected


@pytest.mark.parametrize("document_id", ["9008", "9010", "123456789", "-1"])
async def test_no_photo_is_404(places_client: httpx.AsyncClient, document_id: str) -> None:
    found = await get(places_client, f"/api/places/photos/{document_id}", status=404)
    assert found["detail"]["code"] == "not_found"


async def test_a_photo_id_beyond_bigint_is_invalid(places_client: httpx.AsyncClient) -> None:
    await get(places_client, f"/api/places/photos/{2**63}", status=422)


# Photo list -----------------------------------------------------------------------------------


async def photo_list(client: httpx.AsyncClient, params: Params) -> PhotoList:
    return PhotoList.model_validate(await get(client, "/api/places/photo-list", params))


def km(one: tuple[float, float], other: tuple[float, float]) -> float:
    """The great-circle distance by the spherical law of cosines, rounded as the list does."""
    (lat1, lon1), (lat2, lon2) = (tuple(map(math.radians, point)) for point in (one, other))
    cosine = math.sin(lat1) * math.sin(lat2) + math.cos(lat1) * math.cos(lat2) * math.cos(
        lon2 - lon1
    )
    return round(6371.0088 * math.acos(min(1.0, cosine)), 3)


async def test_the_photos_around_a_point_nearest_first(
    places_client: httpx.AsyncClient, mails: dict[int, int]
) -> None:
    berlin = [("lat", "52.52"), ("lon", "13.405")]
    found = await photo_list(places_client, [*berlin, ("radius_km", "50")])
    assert [item.document_id for item in found.items] == [9001, 9002]
    assert [item.distance_km for item in found.items] == [
        0.0,
        pytest.approx(km((52.52, 13.405), (52.4, 13.06)), abs=0.002),
    ]
    assert (found.total, found.truncated) == (2, False)
    first = found.items[0]
    assert first.first_mail is not None and first.first_mail.id == mails[1]
    assert (first.name, first.device, first.taken_at) == (
        "berlin.jpg",
        "Canon EOS R6",
        datetime(2021, 5, 6, 8, tzinfo=UTC),
    )
    near = await photo_list(places_client, berlin)  # 2 km by default
    assert [item.document_id for item in near.items] == [9001]
    cut = await photo_list(places_client, [*berlin, ("radius_km", "50"), ("limit", "1")])
    assert [item.document_id for item in cut.items] == [9001]
    assert (cut.total, cut.truncated) == (2, True)
    # the duplicate carries 9001 too, but the filters leave only it out
    only = await photo_list(places_client, [*berlin, ("hide_duplicates", "true")])
    assert only.items[0].first_mail is not None and only.items[0].first_mail.id == mails[1]


async def test_the_photos_around_a_point_across_the_meridian_and_at_the_pole(
    places_client: httpx.AsyncClient,
) -> None:
    fiji = await photo_list(places_client, [("lat", "-17"), ("lon", "179.98"), ("radius_km", "20")])
    assert [item.document_id for item in fiji.items] == [9003, 9004]
    distances = [item.distance_km for item in fiji.items]
    assert distances == [
        pytest.approx(km((-17, 179.98), (-17, 179.95)), abs=0.002),
        pytest.approx(km((-17, 179.98), (-17, -179.9)), abs=0.002),
    ]
    far = distances[1]
    assert far is not None and 12 < far < 13  # across the meridian, not around the globe
    west = await photo_list(places_client, [("lat", "-17"), ("lon", "-179.9"), ("radius_km", "5")])
    assert [item.document_id for item in west.items] == [9004]
    # 120 degrees away in longitude, a few kilometres over the pole
    pole = await photo_list(places_client, [("lat", "89.95"), ("lon", "120"), ("radius_km", "20")])
    assert [item.document_id for item in pole.items] == [9007]
    over = pole.items[0].distance_km
    assert over == pytest.approx(km((89.95, 120), (89.9, 0)), abs=0.002)
    assert over is not None and 14 < over < 15


async def test_the_photos_by_capture_time(
    places_client: httpx.AsyncClient, mails: dict[int, int]
) -> None:
    found = await photo_list(places_client, [])
    # earliest first, those without a capture time last
    assert [item.document_id for item in found.items] == [9006, 9003, 9001, 9002, 9009, 9004, 9007]
    assert all(item.distance_km is None for item in found.items)
    # 9006's earliest mail is the hidden one, so the earliest one shown is k=5
    first = {item.document_id: item.first_mail for item in found.items}
    assert first[9006] is not None and first[9006].id == mails[5]
    with_hidden = await photo_list(places_client, [("include_hidden", "true")])
    first = {item.document_id: item.first_mail for item in with_hidden.items}
    assert first[9006] is not None and first[9006].id == mails[7]
    device = await photo_list(places_client, [("device", "Apple iPhone 12")])
    assert [item.document_id for item in device.items] == [9003, 9004]
    assert (device.total, device.truncated) == (2, False)


async def test_invalid_photo_list_parameters(places_client: httpx.AsyncClient) -> None:
    found = await get(places_client, "/api/places/photo-list", [("lat", "52")], status=400)
    assert found["detail"]["code"] == "invalid_filter"
    for params in (
        [("lat", "91"), ("lon", "0")],
        [("lat", "0"), ("lon", "181")],
        [("lat", "0"), ("lon", "0"), ("radius_km", "0")],
        [("lat", "0"), ("lon", "0"), ("radius_km", "201")],
        [("limit", "201")],
    ):
        await get(places_client, "/api/places/photo-list", params, status=422)


# Places from texts ----------------------------------------------------------------------------


async def text_places(client: httpx.AsyncClient, params: Params = ()) -> TextPlaces:
    return TextPlaces.model_validate(await get(client, "/api/places/texts", params))


async def test_the_places_of_the_whole_archive(places_client: httpx.AsyncClient) -> None:
    found = await text_places(places_client)
    # the stored figures, the hidden mail included; Hamburg only in a duplicate
    assert [place.model_dump() for place in found.places] == [
        {
            "entity_id": 9101,
            "label": "Berlin",
            "place": "Berlin, Berlin, DE",
            "detail": "city",
            "lat": 52.52,
            "lon": 13.405,
            "mails": 4,
        },
        {
            "entity_id": 9102,
            "label": "Österreich",
            "place": "Österreich, AT",
            "detail": "country",
            "lat": 47.6,
            "lon": 14.1,
            "mails": 2,
        },
    ]
    assert (found.total, found.exact) == (2, True)
    hidden = await text_places(places_client, [("include_hidden", "true")])
    assert hidden == found


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (YEAR, [(9101, 3), (9102, 2), (9105, 1)]),  # the hidden mail left out, the duplicate in
        ([*YEAR, ("include_hidden", "true")], [(9101, 4), (9102, 2), (9105, 1)]),
        ([*YEAR, ("hide_duplicates", "true")], [(9101, 3), (9102, 2)]),
        ([("date_to", "1975-02-28")], [(9101, 2)]),
        ([("entity", "9102")], [(9102, 2)]),
        ([("photo_area", FIJI)], [(9102, 1), (9101, 1)]),  # k=3 and k=4; ties by id, last first
        ([("q", "from:niemand@nirgends.example")], []),
    ],
)
async def test_the_places_under_the_filters(
    places_client: httpx.AsyncClient, params: Params, expected: list[tuple[int, int]]
) -> None:
    found = await text_places(places_client, params)
    assert [(place.entity_id, place.mails) for place in found.places] == expected
    assert (found.total, found.exact) == (len(expected), True)


async def test_the_places_are_counted_over_a_sample(
    places_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(places_api, "FACET_MAILS", 2)
    found = await text_places(places_client, YEAR)
    assert not found.exact
    assert all(place.mails <= 2 for place in found.places)
    assert found.total == len(found.places)
    monkeypatch.setattr(places_api, "FACET_MAILS", 7)  # every one of the 7 matching mails
    assert (await text_places(places_client, YEAR)).exact
    monkeypatch.setattr(places_api, "TEXT_PLACE_LIMIT", 1)
    cut = await text_places(places_client, YEAR)
    assert [(place.entity_id, place.mails) for place in cut.places] == [(9101, 3)]
    assert (cut.total, cut.exact) == (3, True)


# Places of invitations ------------------------------------------------------------------------


async def test_the_places_of_invitations(
    places_client: httpx.AsyncClient, mails: dict[int, int]
) -> None:
    found = await get(places_client, "/api/places/events")
    assert found["total"] == 2
    berlin, vienna = found["places"]
    assert (berlin["lat"], berlin["lon"], berlin["place"]) == (
        52.517,
        13.3889,
        "10117 Berlin, Berlin, DE",
    )
    assert berlin["locations"] == ["10117 Berlin", "Berlin Mitte"]
    assert berlin["events"] == 2
    assert (berlin["first"], berlin["last"]) == ("1975-01-20T10:00:00Z", "1975-02-20T10:00:00Z")
    assert [event["summary"] for event in berlin["samples"]] == ["Treffen 2", "Treffen 1"]
    sample = berlin["samples"][1]
    assert (sample["mail_id"], sample["kind"], sample["uid"]) == (mails[1], "request", "uid-1")
    assert (sample["location"], sample["all_day"]) == ("10117 Berlin", False)
    assert sample["starts_local"] == "1975-01-20T11:00:00"
    assert (vienna["place"], vienna["events"], vienna["first"], vienna["last"]) == (
        "Wien, Wien, AT",
        1,
        None,
        None,
    )
    assert vienna["samples"][0]["starts_local"] == "1975-03-20T09:00:00"
    hidden = await get(places_client, "/api/places/events", [("include_hidden", "true")])
    berlin = hidden["places"][0]
    assert berlin["events"] == 3
    assert berlin["locations"] == ["10117 Berlin", "Berlin Mitte"]  # two to one
    assert [event["summary"] for event in berlin["samples"]] == [
        "Treffen 7",
        "Treffen 2",
        "Treffen 1",
    ]
    january = await get(places_client, "/api/places/events", [("date_to", "1975-01-31")])
    assert [(place["place"], place["events"]) for place in january["places"]] == [
        ("10117 Berlin, Berlin, DE", 1)
    ]
    assert january["total"] == 1


async def test_the_places_of_invitations_are_cut_at_their_limits(
    places_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(places_api, "TEXT_PLACE_LIMIT", 1)
    monkeypatch.setattr(places_api, "PLACE_EVENTS_LIMIT", 1)
    monkeypatch.setattr(places_api, "PLACE_LOCATIONS_LIMIT", 1)
    found = await get(places_client, "/api/places/events")
    assert found["total"] == 2
    [berlin] = found["places"]
    assert (berlin["events"], berlin["locations"]) == (2, ["10117 Berlin"])
    assert [event["summary"] for event in berlin["samples"]] == ["Treffen 2"]


# Summary --------------------------------------------------------------------------------------


async def test_the_summary(
    places_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = await get(places_client, "/api/places/summary")
    assert (found["photos"], found["photos_dated"]) == (9, 6)  # 9010 too, without a mail
    assert found["devices"] == [
        {"device": "Canon EOS R6", "photos": 3},
        {"device": "Apple iPhone 12", "photos": 2},
        {"device": "Nikon D750", "photos": 2},
    ]
    assert found["texts"] == {"found": 3, "ambiguous": 1, "unknown": 1, "waiting": 1}
    # the empty location is no location
    assert found["events"] == {"found": 4, "ambiguous": 0, "unknown": 1, "waiting": 1}
    assert found["computed_at"] == "2026-10-20T12:00:00Z"
    assert found["outdated"]  # the contract's version of the lists is another
    monkeypatch.setattr(gazetteer, "places_version", lambda: FIGURES_VERSION)
    assert not (await get(places_client, "/api/places/summary"))["outdated"]
    monkeypatch.setattr(places_api, "DEVICE_LIMIT", 1)
    cut = await get(places_client, "/api/places/summary")
    assert cut["devices"] == [{"device": "Canon EOS R6", "photos": 3}]


async def test_the_summary_before_the_first_places_step(
    places_database_url: str, places_client: httpx.AsyncClient
) -> None:
    await rows(places_database_url, "DELETE FROM global_stats WHERE key = 'places'")
    try:
        found = await get(places_client, "/api/places/summary")
        assert (found["computed_at"], found["outdated"]) == (None, True)
    finally:
        await rows(
            places_database_url,
            "INSERT INTO global_stats (key, value) VALUES ('places', CAST(:value AS jsonb))",
            value=f'{{"computed_at": "2026-10-20T12:00:00+00:00", "version": "{FIGURES_VERSION}"}}',
        )


# photo_area in every view of the mail filters (D248) -----------------------------------------


async def test_photo_area_in_the_mail_list_and_its_views(
    places_database_url: str,
    places_client: httpx.AsyncClient,
    generated_archive: GeneratedArchive,
    mails: dict[int, int],
) -> None:
    area = [("photo_area", FIJI), ("sort", "date_asc")]
    listed = await get(places_client, "/api/mails", area)
    assert [item["id"] for item in listed["items"]] == [mails[3], mails[4]]
    summary = await get(places_client, "/api/mails/summary", area)
    assert (summary["total"], summary["exact"]) == (2, True)
    exported = await export(places_client, area)
    assert [int(row[0]) for row in exported] == [mails[3], mails[4]]
    timeline = await get(places_client, "/api/timeline", [("photo_area", FIJI)])
    assert sum(timeline["total"]["counts"]) == 2
    berlin = [("photo_area", "13,52,14,53"), ("sort", "date_asc")]
    listed = await get(places_client, "/api/mails", berlin)
    assert [item["id"] for item in listed["items"]] == [mails[1], mails[2], mails[8]]
    munich = [("photo_area", "11,48,12,49")]
    assert (await get(places_client, "/api/mails", munich))["items"] == []  # only hidden
    with_hidden = await get(places_client, "/api/mails", [*munich, ("include_hidden", "true")])
    assert [item["id"] for item in with_hidden["items"]] == [mails[7]]
    settings = api_settings(places_database_url, generated_archive, Path("no-frontend"))
    engine = create_async_engine(places_database_url, poolclass=pool.NullPool)
    try:
        async with AsyncSession(engine) as session:
            selection = MailSelection(filters=MailFilters(photo_area=FIJI))
            selected = await resolve_selection(session, settings, selection, 10)
    finally:
        await engine.dispose()
    assert [mail.id for mail in selected] == [mails[3], mails[4]]


@pytest.mark.parametrize(
    ("area", "status"),
    [("181,0,10,10", 400), ("0,0,-181,10", 400), ("0,10,10,5", 400), ("0,0,10", 422)],
)
async def test_an_invalid_photo_area_is_refused(
    places_client: httpx.AsyncClient, area: str, status: int
) -> None:
    for path in ("/api/mails", "/api/mails/summary", "/api/mails/export.csv", "/api/timeline"):
        found = await get(places_client, path, [("photo_area", area)], status=status)
        if status == 400:
            assert found["detail"]["code"] == "invalid_filter"


# The position in MetadataSummary (D249) ------------------------------------------------------


async def test_the_document_page_and_the_mail_detail_give_the_position(
    places_client: httpx.AsyncClient, mails: dict[int, int]
) -> None:
    page = await get(places_client, "/api/documents/9001")
    summary = page["metadata"]["summary"]
    assert (summary["latitude"], summary["longitude"], summary["gps"]) == (52.52, 13.405, True)
    text = await get(places_client, "/api/documents/9008")
    assert text["metadata"]["summary"] is None
    detail = MailDetail.model_validate(await get(places_client, f"/api/mails/{mails[4]}"))
    found = {attachment.document_id: attachment.metadata for attachment in detail.attachments}
    assert found[9004] is not None
    assert (found[9004].latitude, found[9004].longitude) == (-17.0, -179.9)
    assert found[9008] is None


def test_the_rows_name_only_places_of_their_own(places_database_url: str) -> None:
    """The fixture's photos are the only ones, so that later steps do not change the cases."""
    found = asyncio.run(
        rows(places_database_url, "SELECT id FROM document WHERE metadata_latitude IS NOT NULL")
    )
    assert sorted(row.id for row in found) == [9001, 9002, 9003, 9004, 9005, 9006, 9007, 9009, 9010]

"""The position of a photo (D241): what summarize takes from the GPS fields for the metadata
step, and that migration 0017 took the same from the fields stored before."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import migrations
from mailrobbe.attachments.metadata.model import Fields, summarize

BERLIN = {"latitude": 52.5200833, "longitude": 13.41}
TIME = datetime(2024, 5, 6, 8, 9, 10, tzinfo=UTC)

# GPS fields -> latitude, longitude, GPS time
CASES: list[tuple[dict[str, Any], tuple[float | None, float | None, datetime | None]]] = [
    ({**BERLIN, "timestamp": "2024-05-06T08:09:10Z"}, (52.5200833, 13.41, TIME)),
    (
        {**BERLIN, "timestamp": "2024-05-06T08:09:10.25Z"},
        (52.5200833, 13.41, TIME.replace(microsecond=250_000)),
    ),
    (BERLIN, (52.5200833, 13.41, None)),
    ({"latitude": 52, "longitude": -13}, (52.0, -13.0, None)),  # integers
    ({"latitude": -90, "longitude": 180}, (-90.0, 180.0, None)),  # the edges
    ({"latitude": 0, "longitude": 13.41}, (0.0, 13.41, None)),  # on the equator
    ({"latitude": 0, "longitude": 0, "timestamp": "2024-05-06T08:09:10Z"}, (None, None, None)),
    ({"latitude": 0.0, "longitude": -0.0}, (None, None, None)),  # a camera's "no fix"
    ({"latitude": 90.5, "longitude": 13.41}, (None, None, None)),
    ({"latitude": 52.52, "longitude": -180.01}, (None, None, None)),
    ({"latitude": 10**30, "longitude": 13.41}, (None, None, None)),
    ({"latitude": "52.52", "longitude": 13.41}, (None, None, None)),  # a string
    ({"latitude": True, "longitude": 13.41}, (None, None, None)),  # jsonb's true is no number
    ({"latitude": [52.52], "longitude": 13.41}, (None, None, None)),
    ({"latitude": 52.52, "timestamp": "2024-05-06T08:09:10Z"}, (None, None, None)),  # one only
    ({**BERLIN, "timestamp": "0001-01-01T00:00:00Z"}, (52.5200833, 13.41, None)),  # year 1
    ({**BERLIN, "timestamp": "1899-12-31T23:59:59Z"}, (52.5200833, 13.41, None)),
    (
        {**BERLIN, "timestamp": "1900-01-01T00:00:00Z"},
        (52.5200833, 13.41, datetime(1900, 1, 1, tzinfo=UTC)),
    ),
    (
        {**BERLIN, "timestamp": "2199-12-31T23:59:59Z"},
        (52.5200833, 13.41, datetime(2199, 12, 31, 23, 59, 59, tzinfo=UTC)),
    ),
    ({**BERLIN, "timestamp": "2300-01-01T00:00:00Z"}, (52.5200833, 13.41, None)),
    ({**BERLIN, "timestamp": "2024-05-06T10:09:10+02:00"}, (52.5200833, 13.41, None)),  # offset
    ({**BERLIN, "timestamp": "2024-05-06T08:09:60Z"}, (52.5200833, 13.41, None)),  # second 60
    ({**BERLIN, "timestamp": "2024-05-06T08:09:10"}, (52.5200833, 13.41, None)),  # no zone
    ({**BERLIN, "timestamp": "2024-05-06"}, (52.5200833, 13.41, None)),
    ({**BERLIN, "timestamp": 1714982950}, (52.5200833, 13.41, None)),
]


@pytest.mark.parametrize(("gps", "expected"), CASES)
def test_summarize_takes_the_position_by_the_rule(
    gps: dict[str, Any], expected: tuple[float | None, float | None, datetime | None]
) -> None:
    fields: Fields = {"gps": gps, "exif": {"make": "Canon"}}

    summary = summarize(fields)

    assert (summary.latitude, summary.longitude, summary.gps_time) == expected
    assert summary.gps is ("latitude" in gps and "longitude" in gps)


def _migration_positions() -> str:
    path = Path(migrations.__file__).with_name("versions") / "0017_places.py"
    spec = importlib.util.spec_from_file_location("revision_0017", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module._POSITIONS)


@pytest.mark.db
async def test_the_migration_took_the_positions_by_the_same_rule(db_session: AsyncSession) -> None:
    # A temporary table of the columns the statement reads and writes shadows document (pg_temp
    # comes first in the search path), so no mail or attachment rows are needed.
    await db_session.execute(
        text(
            "CREATE TEMP TABLE document (id integer, metadata_gps boolean, metadata_fields jsonb, "
            "metadata_latitude float8, metadata_longitude float8, metadata_gps_time timestamptz)"
            " ON COMMIT DROP"
        )
    )
    for number, (gps, _) in enumerate(CASES):
        fields = {"gps": gps}
        await db_session.execute(
            text(
                "INSERT INTO document VALUES (:id, :gps, CAST(:fields AS jsonb), NULL, NULL, NULL)"
            ),
            {"id": number, "gps": summarize(fields).gps, "fields": json.dumps(fields)},
        )

    await db_session.execute(text(_migration_positions()))

    rows = await db_session.execute(
        text(
            "SELECT id, metadata_latitude, metadata_longitude, metadata_gps_time FROM document "
            "ORDER BY id"
        )
    )
    found = {
        row.id: (row.metadata_latitude, row.metadata_longitude, row.metadata_gps_time)
        for row in rows
    }
    assert found == {number: expected for number, (_, expected) in enumerate(CASES)}

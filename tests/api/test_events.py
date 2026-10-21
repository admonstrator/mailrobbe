"""The calendar API (D155): the events of a mail in its detail, the mark of the mail list and
its filters, and the events of a person on GET /api/persons/{id}/events.

The archive is a copy of the imported one whose events are replaced by a known set written in
SQL (EVENTS): an invitation of P with an answer and an update (uid u1), a cancellation sent to
an address merged into P (u2, a zone the phase did not know), an undated invitation without a
UID, and a duplicate mail whose events every person view leaves out.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import make_url

from mailrobbe.api import events as events_api
from tests.api.conftest import _client, _execute, api_settings
from tests.api.test_mails import get, listed, rows
from tests.conftest import GeneratedArchive, _temporary_database

pytestmark = pytest.mark.db

OUTSIDE = "gast@extern.example"


@dataclass(frozen=True)
class Archive:
    url: str
    mails: list[int]  # m1 to m5: the first originals by id
    duplicate: int
    persons: list[int]  # P, Y (merged into P), Z: the first root persons by id
    emails: list[str]  # their addresses


# (mail, position, kind, method, uid, sequence, starts_at, starts_local, zone, organizer,
#  attendees as (email, partstat)); mails 1 to 5 and "d", persons as "P", "Y", "Z".
EVENTS: list[tuple[Any, ...]] = [
    (
        1,
        0,
        "request",
        "REQUEST",
        "u1",
        0,
        "2024-03-01 10:00+00",
        "2024-03-01 11:00",
        "Europe/Berlin",
        "P",
        [("Z", "NEEDS-ACTION"), (OUTSIDE, None)],
    ),
    (
        2,
        0,
        "reply",
        "REPLY",
        "u1",
        0,
        "2024-03-01 10:00+00",
        "2024-03-01 11:00",
        "Europe/Berlin",
        "P",
        [("Z", "ACCEPTED")],
    ),
    (
        3,
        0,
        "request",
        "REQUEST",
        "u1",
        1,
        "2024-03-02 10:00+00",
        "2024-03-02 11:00",
        "Europe/Berlin",
        "P",
        [("Z", "NEEDS-ACTION")],
    ),
    (
        4,
        0,
        "cancel",
        "CANCEL",
        "u2",
        2,
        None,
        "2024-05-01 09:00",
        "Mars/Olympus",
        OUTSIDE,
        [("Y", "NEEDS-ACTION")],
    ),
    (5, 0, "request", None, None, None, None, None, None, None, [("P", "TENTATIVE")]),
    (
        5,
        1,
        "request",
        "REQUEST",
        "u4",
        0,
        "2023-01-01 08:00+00",
        "2023-01-01 09:00",
        "Europe/Berlin",
        OUTSIDE,
        [(OUTSIDE, None)],
    ),
    (
        "d",
        0,
        "request",
        "REQUEST",
        "u1",
        5,
        "2025-01-01 10:00+00",
        "2025-01-01 11:00",
        "Europe/Berlin",
        "P",
        [("Z", "DECLINED")],
    ),
    (
        "d",
        1,
        "request",
        "REQUEST",
        "u3",
        0,
        "2025-02-01 10:00+00",
        "2025-02-01 11:00",
        "Europe/Berlin",
        OUTSIDE,
        [("P", None)],
    ),
]


async def _prepare(url: str) -> Archive:
    mails = [row.id for row in await rows(url, _FIRST_MAILS)]
    duplicate = (await rows(url, _FIRST_DUPLICATE))[0].id
    persons = [row.id for row in await rows(url, _FIRST_PERSONS)]
    emails = [row.canonical_email for row in await rows(url, _EMAILS, ids=persons)]
    await _execute(
        url,
        [
            "DELETE FROM calendar_event",  # the import found the generated ones
            "UPDATE person SET merged_into = :p WHERE id = :y",
        ],
        p=persons[0],
        y=persons[1],
    )
    names = dict(zip("PYZ", emails, strict=True))
    for (
        mail,
        position,
        kind,
        method,
        uid,
        sequence,
        at,
        local,
        zone,
        organizer,
        attendees,
    ) in EVENTS:
        mail_id = duplicate if mail == "d" else mails[mail - 1]
        event = {
            "mail_id": mail_id,
            "position": position,
            "kind": kind,
            "method": method,
            "uid": uid,
            "sequence": sequence,
            "starts_at": None if at is None else datetime.fromisoformat(at),
            "starts_local": None if local is None else datetime.fromisoformat(local),
            "zone": zone,
            "organizer": names.get(organizer, organizer),
            "summary": f"Termin {mail}.{position}",
        }
        await _execute(url, [_INSERT_EVENT], **event)
        for number, (email, partstat) in enumerate(attendees):
            await _execute(
                url,
                [_INSERT_ATTENDEE],
                mail_id=mail_id,
                at=position,
                position=number,
                email=names.get(email, email),
                partstat=partstat,
            )
    return Archive(url, mails, duplicate, persons, emails)


_FIRST_MAILS = "SELECT id FROM mail WHERE is_duplicate_of IS NULL ORDER BY id LIMIT 5"
_FIRST_DUPLICATE = "SELECT id FROM mail WHERE is_duplicate_of IS NOT NULL ORDER BY id LIMIT 1"
_FIRST_PERSONS = "SELECT id FROM person WHERE merged_into IS NULL ORDER BY id LIMIT 3"
_EMAILS = (
    "SELECT p.canonical_email FROM person p JOIN person_email e ON e.email = p.canonical_email "
    "AND e.person_id = p.id WHERE p.id = ANY(:ids) ORDER BY p.id"
)
_INSERT_EVENT = """
    INSERT INTO calendar_event (mail_id, position, kind, method, uid, sequence, summary,
        starts_local, time_zone, starts_at, organizer_email, organizer_name)
    VALUES (:mail_id, :position, :kind, :method, :uid, :sequence, :summary, :starts_local, :zone,
        :starts_at, :organizer, CASE WHEN CAST(:organizer AS text) IS NULL THEN NULL
        ELSE 'Leitung' END)
"""
_INSERT_ATTENDEE = """
    INSERT INTO calendar_attendee (event_id, position, email, name, partstat)
    SELECT id, :position, :email, NULL, :partstat FROM calendar_event
    WHERE mail_id = :mail_id AND position = :at
"""


@pytest.fixture(scope="module")
def archive(database_server_url: str, imported_database_url: str) -> Iterator[Archive]:
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        yield asyncio.run(_prepare(url))


@pytest.fixture
async def events_client(
    archive: Archive, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings(archive.url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


def _summaries(found: Any) -> list[str]:
    return [item["event"]["summary"] for item in found["items"]]


async def test_a_person_sees_one_entry_per_uid_newest_first(
    events_client: httpx.AsyncClient, archive: Archive
) -> None:
    p, y, z = archive.persons
    found = await get(events_client, f"/api/persons/{p}/events")
    # u2 by its wall time (no instant), u1 by its update, u4 not P's, undated last; the
    # duplicate's update of u1 and its u3 are left out
    assert _summaries(found) == ["Termin 4.0", "Termin 3.0", "Termin 5.0"]
    assert found["total"] == 3
    cancel, update, undated = found["items"]
    assert (cancel["organizer"], cancel["partstat"]) == (False, "NEEDS-ACTION")  # through Y
    assert (update["organizer"], update["partstat"]) == (True, None)
    assert (undated["organizer"], undated["partstat"]) == (False, "TENTATIVE")
    assert cancel["event"]["kind"] == "cancel"
    assert update["mail"]["id"] == archive.mails[2]
    assert update["mail"]["subject"] is not None
    assert update["event"]["uid_mails"] == 4  # m1, m2, m3 and the duplicate
    # an alias shows its root's events, the answer of a reply wins over the update's NEEDS-ACTION
    assert await get(events_client, f"/api/persons/{y}/events") == found
    of_z = await get(events_client, f"/api/persons/{z}/events")
    assert _summaries(of_z) == ["Termin 3.0"]
    assert (of_z["items"][0]["organizer"], of_z["items"][0]["partstat"]) == (False, "ACCEPTED")


async def test_the_list_is_cut_at_the_limit(
    events_client: httpx.AsyncClient, archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events_api, "PERSON_EVENT_LIMIT", 2)
    found = await get(events_client, f"/api/persons/{archive.persons[0]}/events")
    assert (_summaries(found), found["total"]) == (["Termin 4.0", "Termin 3.0"], 3)


async def test_persons_without_events_and_unknown_persons(
    events_client: httpx.AsyncClient, archive: Archive
) -> None:
    [other] = await rows(
        archive.url,
        "SELECT max(id) AS id FROM person WHERE merged_into IS NULL AND id <> ALL(:ids)",
        ids=archive.persons,
    )
    assert await get(events_client, f"/api/persons/{other.id}/events") == {"items": [], "total": 0}
    found = await get(events_client, "/api/persons/999999999/events", status=404)
    assert found["detail"]["code"] == "not_found"


async def test_a_mail_shows_its_events_with_attendees_and_persons(
    events_client: httpx.AsyncClient, archive: Archive
) -> None:
    p, _, z = archive.persons
    detail = await get(events_client, f"/api/mails/{archive.mails[0]}")
    [event] = detail["events"]
    assert (event["kind"], event["method"], event["uid"], event["sequence"]) == (
        "request",
        "REQUEST",
        "u1",
        0,
    )
    assert event["starts_at"] == "2024-03-01T10:00:00Z"
    assert event["starts_local"] == "2024-03-01T11:00:00"
    assert (event["time_zone"], event["all_day"], event["uid_mails"]) == ("Europe/Berlin", False, 4)
    organizer = event["organizer"]
    assert (organizer["email"], organizer["name"]) == (archive.emails[0], "Leitung")
    assert organizer["person"]["person_id"] == p
    assert organizer["person"]["name"] == "Leitung"  # the name the invitation gives
    first, outside = event["attendees"]
    assert (first["email"], first["partstat"], first["person"]["person_id"]) == (
        archive.emails[2],
        "NEEDS-ACTION",
        z,
    )
    assert (outside["email"], outside["person"]) == (OUTSIDE, None)

    two = (await get(events_client, f"/api/mails/{archive.mails[4]}"))["events"]
    assert [(e["summary"], e["uid"], e["uid_mails"]) for e in two] == [
        ("Termin 5.0", None, 0),
        ("Termin 5.1", "u4", 1),
    ]
    assert two[0]["organizer"] is None
    assert (two[1]["organizer"]["email"], two[1]["organizer"]["person"]) == (OUTSIDE, None)


async def test_mails_without_events_have_none(
    events_client: httpx.AsyncClient, archive: Archive
) -> None:
    [plain] = await rows(
        archive.url,
        "SELECT min(id) AS id FROM mail m WHERE NOT EXISTS "
        "(SELECT 1 FROM calendar_event e WHERE e.mail_id = m.id)",
    )
    assert (await get(events_client, f"/api/mails/{plain.id}"))["events"] == []


async def test_the_list_marks_and_filters_mails_with_events(
    events_client: httpx.AsyncClient, archive: Archive
) -> None:
    m1, m2, m3, m4, m5 = archive.mails
    d = archive.duplicate
    by_uid = await listed(events_client, [("event_uid", "u1")])
    assert sorted(by_uid) == sorted([m1, m2, m3, d])
    assert sorted(await listed(events_client, [("event", "cancel")])) == [m4]
    assert sorted(await listed(events_client, [("event", "reply"), ("event", "cancel")])) == [
        m2,
        m4,
    ]
    requests = await listed(events_client, [("event", "request"), ("hide_duplicates", "true")])
    assert sorted(requests) == sorted([m1, m3, m5])
    page = await get(
        events_client, "/api/mails", [("event", "request"), ("event", "reply"), ("limit", "200")]
    )
    marks = {item["id"]: item["event"] for item in page["items"]}
    assert marks == {m1: "request", m2: "reply", m3: "request", m5: "request", d: "request"}
    plain = await get(events_client, "/api/mails", [("limit", "50")])
    assert all(
        item["event"] is None
        for item in plain["items"]
        if item["id"] not in {m1, m2, m3, m4, m5, d}
    )

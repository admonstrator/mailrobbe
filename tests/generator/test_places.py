"""Places of the generator (D241, D243): photos with the GPS position of their EXIF, and meetings
at an address or in a town, each with the truth the import must find."""

import itertools
import random
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mailrobbe.attachments.metadata import MetadataLimits, read_metadata
from mailrobbe.attachments.metadata.model import summarize
from mailrobbe.enums import PlaceStatus
from mailrobbe.generator import documents, invitations
from mailrobbe.generator import vocabulary as vocab
from mailrobbe.generator.model import (
    AttachmentSpec,
    DocumentSpec,
    Meeting,
    PhotoGps,
    PlannedMail,
)
from mailrobbe.generator.render import render
from mailrobbe.ical.parse import message_events
from mailrobbe.places.gazetteer import locate_location

WHEN = datetime(2021, 5, 4, 10, 0, tzinfo=UTC)
PHOTO = AttachmentSpec("IMG_1.jpg", "image/jpeg", 60_000)
LIMITS = MetadataLimits(timeout=30)


def _gps(north: float, east: float, offset: str = "+02:00") -> PhotoGps:
    return PhotoGps(north, east, 34.5, datetime(2021, 5, 4, 9, 8, 7), offset, "Apple", "iPhone 13")


@pytest.mark.parametrize(
    ("north", "east", "offset"),
    [
        (52.512345, 13.401234, "+02:00"),  # Berlin
        (-33.86785, -151.20732, "+01:00"),  # south and west
        (0.0, 0.0, "+02:00"),  # a camera without a fix
        (123.456789, 9.9, "+02:00"),  # beyond 90 degrees
    ],
)
def test_a_gps_photo_reads_back_as_its_truth(north: float, east: float, offset: str) -> None:
    gps = _gps(north, east, offset)
    spec = DocumentSpec(7, "jpeg", "photo", WHEN, gps)
    data, _ = documents.document_bytes(spec, 60_000)
    plain, _ = documents.document_bytes(replace(spec, gps=None), 60_000)
    assert len(data) == len(plain)  # the EXIF takes the place of noise
    reading = read_metadata(data, "IMG_1.jpg", "image/jpeg", LIMITS)
    assert reading.error is None
    summary = summarize(reading.fields)
    expected = documents.photo_position(gps)
    assert (summary.latitude, summary.longitude) == (expected or (None, None))
    assert summary.device == "Apple iPhone 13"
    assert summary.gps is (abs(north) <= 90)  # the reader drops a latitude beyond
    hours = int(offset[1:3])
    assert summary.created == datetime(2021, 5, 4, 9 - hours, 8, 7, tzinfo=UTC)
    if expected is not None:
        assert summary.gps_time == summary.created  # the GPS clock in UTC
    else:
        assert summary.gps_time is None
    built = documents.build(replace(PHOTO, document=spec))
    truth = built.truth(PHOTO.filename, PHOTO.mime_type)
    assert built.position == expected
    assert (truth.latitude, truth.longitude) == (expected or (None, None))


def test_photo_position_is_what_no_reader_drops() -> None:
    assert documents.photo_position(None) is None
    assert documents.photo_position(_gps(0.0, 0.0)) is None
    assert documents.photo_position(_gps(90.5, 9.0)) is None
    assert documents.photo_position(_gps(48.1372, 181.0)) is None
    assert documents.photo_position(_gps(0.0, 9.5)) == (0.0, 9.5)  # on the equator
    north, east = documents.photo_position(_gps(-48.123456, -11.98765)) or (0.0, 0.0)
    assert abs(north + 48.123456) < 1e-6 and abs(east + 11.98765) < 1e-6
    assert (round(north, 7), round(east, 7)) == (north, east)


def _new_photos(seed: int, count: int) -> list[DocumentSpec]:
    pool = documents.DocumentPool(seed)
    made: list[DocumentSpec] = []
    for n in range(count):
        spec = pool.attach(PHOTO, "IMG_{n}.jpg", WHEN + timedelta(hours=n))
        if spec.document is not None and spec.document not in made:
            made.append(spec.document)
    return made


def test_the_pool_takes_a_third_of_its_photos_in_outings() -> None:
    made = _new_photos(42, 3000)
    photos = [spec for spec in made if spec.form == "jpeg"]
    taken = [spec.gps for spec in photos if spec.gps is not None]
    assert len(photos) > 300
    assert 0.25 < len(taken) / len(photos) < 0.42
    assert sum(gps.latitude == 123.456789 for gps in taken) == 1
    assert sum(gps.latitude == gps.longitude == 0 for gps in taken) == len(taken) // 10
    assert not any(spec.gps for spec in made if spec.form != "jpeg")
    for spec in photos:  # taken before the mail, in local time with its offset
        if spec.gps is not None:
            offset = timedelta(hours=int(spec.gps.offset[1:3]))
            assert spec.gps.taken.replace(tzinfo=UTC) - offset < spec.when
    outings = Counter((gps.make, gps.model) for gps in taken)
    assert len(outings) > 4
    runs = [1]
    for before, after in itertools.pairwise(taken):
        same = (before.make, before.model) == (after.make, after.model)
        if same and timedelta(0) < after.taken - before.taken <= timedelta(seconds=1500):
            runs[-1] += 1
        else:
            runs.append(1)
    assert max(runs) <= documents.OUTING_PHOTOS[1]
    assert sum(runs) / len(runs) > 2.5  # a few photos of an outing one after another
    centres = list(vocab.CITY_POINTS.values())
    for gps in taken:
        if documents.photo_position(gps) is not None:
            assert min(abs(gps.latitude - a) + abs(gps.longitude - b) for a, b in centres) < 0.2


def test_the_photos_positions_follow_the_seed() -> None:
    first = [spec.gps for spec in _new_photos(7, 600)]
    assert first == [spec.gps for spec in _new_photos(7, 600)]
    assert first != [spec.gps for spec in _new_photos(8, 600)]


def _meetings(plan: list[PlannedMail]) -> list[Meeting]:
    return [
        mail.calendar.meeting
        for mail in plan
        if mail.calendar is not None and mail.calendar.method == "REQUEST"
        and mail.calendar.meeting.sequence == 0
    ]  # fmt: skip


def test_some_meetings_are_at_an_address_or_in_a_town(gen_plan: list[PlannedMail]) -> None:
    meetings = _meetings(gen_plan)
    placed = [m for m in meetings if m.place is not None]
    assert not any(m.rooms for m in placed)  # a booked room stays the location
    free = [m for m in meetings if not m.rooms]
    assert 0.15 < len(placed) / len(free) < 0.6
    towns = {town for _, town in invitations._POSTCODES}
    assert {m.place for m in placed} <= towns
    assert any(any(c.isdigit() for c in m.location) for m in placed)  # with a postcode
    assert all(m.location.endswith(m.place or "") for m in placed)


def test_addressed_keeps_rooms_and_draws_from_its_own_stream(
    gen_plan: list[PlannedMail],
) -> None:
    meetings = _meetings(gen_plan)
    room = next(m for m in meetings if m.rooms)
    assert all(invitations.addressed(random.Random(n), room) == room for n in range(50))
    plain = next(m for m in meetings if m.place is None and not m.rooms)
    made = [invitations.addressed(random.Random(n), plain) for n in range(200)]
    kinds = Counter(
        "as is" if m == plain else "postcode" if any(c.isdigit() for c in m.location) else "town"
        for m in made
    )
    assert kinds.keys() == {"as is", "postcode", "town"}
    assert all(replace(m, location=plain.location, place=None) == plain for m in made)


def test_every_written_location_resolves_to_its_town() -> None:
    for postcode, town in invitations._POSTCODES:
        for venue in invitations._VENUES:
            for location in (
                f"{venue}, {invitations._STREETS[0]} 12, {postcode} {town}",
                f"{venue}, {town}",
                f"{venue} {town}",
            ):
                found = locate_location(location)
                assert found.status is PlaceStatus.FOUND, location
                assert (found.label or "").startswith(town), (location, found.label)


def test_the_events_truth_names_the_town_of_its_location(gen_plan: list[PlannedMail]) -> None:
    """Invitations, answers, updates and .ics documents: an event whose truth has a place is
    found there; a reply states no location, a room or a call no town."""
    mails = [
        mail
        for mail in gen_plan
        if mail.calendar is not None
        or any(a.document is not None and a.document.form == "ics" for a in mail.attachments)
    ]
    places: Counter[str] = Counter()
    for planned in mails:
        mail = render(planned)
        assert mail.calendar is not None
        locations = {
            (event.method, event.uid, event.sequence): event.location
            for event in message_events(mail.raw)
        }
        for truth in mail.calendar:
            location = locations[(truth.method, truth.uid, truth.sequence)]
            if truth.method == "REPLY":
                assert truth.place is None
            if truth.place is None:
                places["none"] += 1
                if location:
                    assert locate_location(location).status is not PlaceStatus.FOUND, location
                continue
            places["town"] += 1
            assert location is not None
            found = locate_location(location)
            assert found.status is PlaceStatus.FOUND, location
            assert (found.label or "").startswith(truth.place), (location, found.label)
    assert places["town"] > 10 and places["none"] > 10

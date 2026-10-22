"""Places (milestone 20, D247, D248): photos with a position, the places named in the mails and
the places of invitations, under the map's filters (schemas.PlaceParams).

Routes: GET /api/places/summary, /api/places/photos, /api/places/photos/{id},
/api/places/photo-list, /api/places/texts, /api/places/events.

A photo is a document with a position (D241); its own conditions (the position, the capture
time, the device) are columns of document, and ix_document_metadata_position holds every photo.
It shows when a mail carrying it meets the mail filters (filters.mail_conditions, which leave out
the hidden mails unless include_hidden, D222): one EXISTS over attachment and mail. Without mail
filters that test becomes the list of the few photos failing it, those a hidden mail carries or
no mail at all with no other carrier (_carried), so that the map of the whole archive reads
document alone. The capture time is metadata_created, else the GPS time; a photo without one
never meets taken_from or taken_to.

Photos around a point are found in a box of latitude and longitude first, a range of the index,
then by their great-circle distance (_box, _distance). The box spans every longitude when the
circle holds a pole, and goes on beyond the 180th meridian on the other side.

Places from texts (D242) are place entities with a point. Without mail filters they show
entity.mails, the stored figures with the hidden mails (D222), read from ix_entity_located; with
filters they are counted over the matching mails that mention them (entities.mentions), at most
FACET_MAILS of them as the facets do (D87), under the count budget of D19 with the facets'
fallback. Places of invitations (D243) are counted per point and place over the events whose mail
meets the filters; the calendar is small enough to be grouped whole.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Annotated, Any, get_args

from fastapi import APIRouter, Query
from sqlalchemy import (
    ColumnElement,
    Executable,
    Select,
    any_,
    exists,
    func,
    null,
    or_,
    select,
    true,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.documents import DocumentId, _all_unless_canceled
from mailrobbe.api.entities import FACET_FALLBACK, _distinct_mails, _ids
from mailrobbe.api.filters import _midnight, in_area, resolve_contents, unfiltered
from mailrobbe.api.mails import _count_budget, _participants, _terms, _where
from mailrobbe.api.schemas import (
    DEVICE_LIMIT,
    FACET_MAILS,
    PHOTO_MAILS_LIMIT,
    PHOTO_POINT_LIMIT,
    PLACE_EVENTS_LIMIT,
    PLACE_LOCATIONS_LIMIT,
    RECIPIENT_PREVIEW,
    TEXT_PLACE_LIMIT,
    CompassDirection,
    DeviceCount,
    EventPlace,
    EventPlaces,
    NearestTown,
    PhotoDetail,
    PhotoList,
    PhotoListItem,
    PhotoListParams,
    PhotoPoint,
    PhotoPoints,
    PlaceCounts,
    PlaceDetailKind,
    PlaceEvent,
    PlaceMail,
    PlaceParams,
    PlaceSummary,
    TextPlace,
    TextPlaces,
)
from mailrobbe.attachments.metadata.model import _CREATED
from mailrobbe.db.models import Attachment, CalendarEvent, Document, Entity, Mail, MailHidden
from mailrobbe.entities.mentions import mentions
from mailrobbe.enums import EntityKind, ParticipationRole, PlaceStatus
from mailrobbe.persons.labels import attach_labels
from mailrobbe.places import gazetteer
from mailrobbe.places.model import read_figures
from mailrobbe.preview.kinds import preview_kind

router = APIRouter(prefix="/api", tags=["places"])

EARTH_RADIUS_KM = 6371.0088  # the mean radius
IN_TOWN_KM = 0.5  # a photo nearer its town than this is in it: no direction (D248)
# Bearings from north in steps of 45 degrees, clockwise.
_COMPASS: tuple[CompassDirection, ...] = get_args(CompassDirection)

_LATITUDE = Document.metadata_latitude
_LONGITUDE = Document.metadata_longitude
_PHOTO = _LATITUDE.is_not(None)  # the predicate of ix_document_metadata_position
_taken: ColumnElement[datetime | None] = func.coalesce(
    Document.metadata_created, Document.metadata_gps_time
)
# The capture time as the file writes it, where it gives no zone: the fields summarize takes the
# creation time from, then the GPS date alone.
_TAKEN_FIELDS = (*_CREATED, ("gps", "timestamp"))
_EARLIEST = (Mail.date_utc.asc().nulls_last(), Mail.id)  # undated mails last

_PLACE_COLUMNS = (
    Entity.id,
    Entity.label,
    Entity.place_label,
    Entity.detail,
    Entity.latitude,
    Entity.longitude,
)
_LOCATED_PLACE = (
    Entity.latitude.is_not(None),  # the predicate of ix_entity_located
    Entity.longitude.is_not(None),
    Entity.kind == EntityKind.PLACE,
    Entity.detail.in_(get_args(PlaceDetailKind)),
)
_EVENT_POINT = (CalendarEvent.latitude, CalendarEvent.longitude, CalendarEvent.place_label)


# Filters -------------------------------------------------------------------------------------


async def _mail_where(
    session: AsyncSession, params: PlaceParams, settings: AppSettings
) -> list[ColumnElement[bool]]:
    """The mail filters' conditions (400 invalid_filter), research filters looked up first."""
    return await resolve_contents(session, _where(params, _terms(params.q), settings))


def _photo_where(
    params: PlaceParams, mail_where: Sequence[ColumnElement[bool]]
) -> list[ColumnElement[bool]]:
    """The photos meeting the filters: a position, the capture time and device asked for, and a
    mail carrying it that meets mail_where."""
    where: list[ColumnElement[bool]] = [_PHOTO]
    if params.taken_from is not None:
        where.append(_taken >= _midnight(params.taken_from))
    if params.taken_to is not None:  # the calendar's last day has no day after it
        if params.taken_to < date.max:
            where.append(_taken < _midnight(params.taken_to + timedelta(days=1)))
        else:
            where.append(_taken.is_not(None))
    if params.device is not None:
        where.append(Document.metadata_device == params.device)
    where.append(_carried(mail_where))
    return where


def _carried(where: Sequence[ColumnElement[bool]]) -> ColumnElement[bool]:
    """A mail carrying the photo meets where. Without mail filters, the photos failing that are
    listed instead, in a subquery PostgreSQL runs once and hashes: of the photos a hidden mail
    carries (where is VISIBLE) or that no mail carries, those without a carrier meeting where,
    tested one at a time (as documents._carried with walk), where an anti join would read the
    carrying mails of every photo."""
    if not unfiltered(where):
        return exists().where(
            Attachment.document_id == Document.id, Mail.id == Attachment.mail_id, *where
        )
    photo = Document.__table__.alias("failing")
    touched = [photo.c.first_mail_id.is_(None)]  # finalize deletes it soon (D14)
    if where:
        hidden = select(Attachment.document_id).where(
            Attachment.mail_id.in_(select(MailHidden.mail_id))
        )
        touched.append(photo.c.id.in_(hidden))
    carrier = (
        select(true())
        .select_from(Attachment, Mail)
        .where(Attachment.document_id == photo.c.id, Mail.id == Attachment.mail_id, *where)
        .limit(1)
    )
    failing = select(photo.c.id).where(
        photo.c.metadata_latitude.is_not(None),
        or_(*touched),
        carrier.scalar_subquery().is_(None),  # scalar: never hashed in full
    )
    return Document.id.not_in(failing)


# Photos --------------------------------------------------------------------------------------


@router.get("/places/photos")
async def photos(
    params: Annotated[PlaceParams, Query()], session: Session, settings: AppSettings
) -> PhotoPoints:
    where = _photo_where(params, await _mail_where(session, params, settings))
    rows = list(
        await session.execute(
            select(Document.id, _LATITUDE, _LONGITUDE)
            .where(*where)
            .order_by(Document.id)
            .limit(PHOTO_POINT_LIMIT + 1)
        )
    )
    total = len(rows)
    if total > PHOTO_POINT_LIMIT:
        total = await session.scalar(select(func.count()).select_from(Document).where(*where)) or 0
    return PhotoPoints(
        points=[
            PhotoPoint(id=row.id, lat=row.metadata_latitude, lon=row.metadata_longitude)
            for row in rows[:PHOTO_POINT_LIMIT]
        ],
        total=total,
        truncated=total > PHOTO_POINT_LIMIT,
    )


@router.get("/places/photos/{document_id}")
async def photo_detail(
    document_id: DocumentId, session: Session, settings: AppSettings
) -> PhotoDetail:
    found = await session.execute(
        select(
            Document.id,
            Document.name,
            Document.mime_type,
            Document.kind,
            Document.size_bytes,
            Document.sha256,
            Document.metadata_fields,
            Document.metadata_device,
            _LATITUDE,
            _LONGITUDE,
            _taken.label("taken_at"),
        ).where(Document.id == document_id, _PHOTO)
    )
    photo = found.one_or_none()
    carrying = Attachment.document_id == document_id
    first = await session.scalar(  # finalize deletes documents without attachments
        select(Attachment.id)
        .join(Mail, Mail.id == Attachment.mail_id)
        .where(carrying)
        .order_by(*_EARLIEST, Attachment.position)
        .limit(1)
    )
    if photo is None or first is None:
        raise api_error(404, "not_found", f"no photo with document id {document_id}")
    # Every mail carrying it, duplicates and hidden ones too (D222), as the mail detail does.
    mail_ids = list(
        await session.scalars(
            select(Mail.id)
            .where(Mail.id.in_(select(Attachment.mail_id).where(carrying)))
            .order_by(*_EARLIEST)
            .limit(PHOTO_MAILS_LIMIT)
        )
    )
    mail_count = await session.scalar(
        select(func.count(Attachment.mail_id.distinct())).where(carrying)
    )
    mails = await _place_mails(session, mail_ids)
    fields = photo.metadata_fields or {}
    detail = PhotoDetail(
        document_id=photo.id,
        attachment_id=first,
        name=photo.name,
        mime_type=photo.mime_type,
        preview=preview_kind(
            photo.kind,
            photo.name,
            photo.mime_type,
            photo.size_bytes,
            hashed=photo.sha256 is not None,
            max_size=settings.preview_max_size,
        ),
        latitude=photo.metadata_latitude,
        longitude=photo.metadata_longitude,
        altitude=_altitude(fields),
        taken_at=photo.taken_at,
        taken_text=None if photo.taken_at is not None else _taken_text(fields),
        device=photo.metadata_device,
        nearest=nearest(photo.metadata_latitude, photo.metadata_longitude),
        mails=[mails[mail_id] for mail_id in mail_ids if mail_id in mails],
        mail_count=mail_count or 0,
    )
    await attach_labels(session, detail)
    return detail


def _altitude(fields: dict[str, Any]) -> float | None:
    """The GPS altitude the file states, in metres; None without a number."""
    gps = fields.get("gps")
    value = gps.get("altitude") if isinstance(gps, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def _taken_text(fields: dict[str, Any]) -> str | None:
    """The capture time as found in the first field that gives one (D167: shown, not used)."""
    for source, key in _TAKEN_FIELDS:
        found = fields.get(source)
        value = found.get(key) if isinstance(found, dict) else None
        if isinstance(value, str) and value:
            return value
    return None


def nearest(latitude: float, longitude: float) -> NearestTown | None:
    """The town of the shipped lists nearest to the point (places.gazetteer), with the direction
    from it towards the point; None beyond its limit."""
    found = gazetteer.nearest_town(latitude, longitude)
    if found is None:
        return None
    direction = None
    if found.distance_km >= IN_TOWN_KM:
        direction = _COMPASS[int((found.bearing % 360 + 22.5) // 45) % len(_COMPASS)]
    return NearestTown(
        name=found.town.name,
        region=found.town.region,
        country=found.town.country,
        distance_km=round(found.distance_km, 1),
        direction=direction,
    )


@router.get("/places/photo-list")
async def photo_list(
    params: Annotated[PhotoListParams, Query()], session: Session, settings: AppSettings
) -> PhotoList:
    """Around a point, nearest first; else by capture time, photos without one last."""
    if (params.lat is None) != (params.lon is None):
        raise api_error(400, "invalid_filter", "lat and lon go together")
    mail_where = await _mail_where(session, params, settings)
    where = _photo_where(params, mail_where)
    distance: ColumnElement[Any] = null()
    order: list[Any] = [_taken.asc().nulls_last(), Document.id]
    if params.lat is not None and params.lon is not None:
        distance = _distance(params.lat, params.lon)
        where += [*_box(params.lat, params.lon, params.radius_km), distance <= params.radius_km]
        order = [distance, Document.id]
    rows = list(
        await session.execute(
            select(
                Document.id,
                Document.name,
                _LATITUDE,
                _LONGITUDE,
                _taken.label("taken_at"),
                Document.metadata_device,
                distance.label("distance"),
                func.count().over().label("total"),
            )
            .where(*where)
            .order_by(*order)
            .limit(params.limit)
        )
    )
    firsts = await _first_carriers(session, [row.id for row in rows], mail_where)
    mails = await _place_mails(session, [mail_id for _, mail_id in firsts.values()])
    items = [
        PhotoListItem(
            document_id=row.id,
            attachment_id=firsts[row.id][0],
            name=row.name,
            latitude=row.metadata_latitude,
            longitude=row.metadata_longitude,
            taken_at=row.taken_at,
            device=row.metadata_device,
            distance_km=None if row.distance is None else round(row.distance, 3),
            first_mail=mails.get(firsts[row.id][1]),
        )
        for row in rows
        if row.id in firsts  # a carrier gone since the first query
    ]
    total = rows[0].total if rows else 0
    page = PhotoList(items=items, total=total, truncated=total > params.limit)
    await attach_labels(session, page)
    return page


def _distance(latitude: float, longitude: float) -> ColumnElement[float]:
    """The great-circle distance in km from the point to the photo's position (haversine)."""
    lat_delta = func.radians(_LATITUDE - latitude)
    lon_delta = func.radians(_LONGITUDE - longitude)
    half = func.power(func.sin(lat_delta / 2), 2) + math.cos(math.radians(latitude)) * func.cos(
        func.radians(_LATITUDE)
    ) * func.power(func.sin(lon_delta / 2), 2)
    distance: ColumnElement[float] = 2 * EARTH_RADIUS_KM * func.asin(func.least(1, func.sqrt(half)))
    return distance


def _box(latitude: float, longitude: float, radius_km: float) -> list[ColumnElement[bool]]:
    """The box around the circle of radius_km: its latitudes, and the longitudes it spans where
    it is widest; every longitude when it holds a pole, across the 180th meridian where it
    reaches beyond."""
    angle = radius_km / EARTH_RADIUS_KM
    south = latitude - math.degrees(angle)
    north = latitude + math.degrees(angle)
    if south <= -90 or north >= 90:
        return [_LATITUDE.between(max(south, -90), min(north, 90))]
    spread = math.degrees(math.asin(math.sin(angle) / math.cos(math.radians(latitude))))
    west, east = longitude - spread, longitude + spread
    west, east = (west + 360 if west < -180 else west), (east - 360 if east > 180 else east)
    return [in_area(_LATITUDE, _LONGITUDE, (west, south, east, north))]


async def _first_carriers(
    session: AsyncSession, document_ids: Sequence[int], where: Sequence[ColumnElement[bool]]
) -> dict[int, tuple[int, int]]:
    """Per photo its occurrence in the earliest mail carrying it that meets where: the
    attachment's and the mail's id."""
    if not document_ids:
        return {}
    rows = await session.execute(
        select(Attachment.document_id, Attachment.id, Attachment.mail_id)
        .join(Mail, Mail.id == Attachment.mail_id)
        .where(Attachment.document_id == any_(_ids(document_ids)), *where)
        .order_by(Attachment.document_id, *_EARLIEST, Attachment.position)
        .ext(postgresql.distinct_on(Attachment.document_id))
    )
    return {row.document_id: (row.id, row.mail_id) for row in rows}


async def _place_mails(session: AsyncSession, mail_ids: Sequence[int]) -> dict[int, PlaceMail]:
    """These mails with their sender and recipients, as the mail list shows them."""
    if not mail_ids:
        return {}
    rows = await session.execute(
        select(Mail.id, Mail.date_utc, Mail.subject).where(Mail.id == any_(_ids(mail_ids)))
    )
    people = await _participants(session, mail_ids)
    found = {}
    for row in rows:
        participants = people.get(row.id, [])
        senders = [person for role, person in participants if role is ParticipationRole.FROM]
        recipients = [person for role, person in participants if role is not ParticipationRole.FROM]
        found[row.id] = PlaceMail(
            id=row.id,
            date=row.date_utc,
            subject=row.subject,
            sender=senders[0] if senders else None,
            recipients=recipients[:RECIPIENT_PREVIEW],
            recipient_count=len(recipients),
        )
    return found


# Places from texts ---------------------------------------------------------------------------


@router.get("/places/texts")
async def text_places(
    params: Annotated[PlaceParams, Query()], session: Session, settings: AppSettings
) -> TextPlaces:
    where = _where(params, _terms(params.q), settings)
    if unfiltered(where):
        shown = (*_LOCATED_PLACE, Entity.mails > 0)  # 0: only in duplicates (D85)
        top = (
            select(*_PLACE_COLUMNS, Entity.mails)
            .where(*shown)
            .order_by(Entity.mails.desc(), Entity.id.desc())
            .limit(TEXT_PLACE_LIMIT)
        )
        total = await session.scalar(select(func.count()).select_from(Entity).where(*shown))
        places = [_text_place(row) for row in await session.execute(top)]
        return TextPlaces(places=places, total=total or 0, exact=True)
    where = await resolve_contents(session, where)
    await _count_budget(session, settings)
    ids: list[int] | None = None
    for size in (FACET_MAILS, FACET_FALLBACK):  # as the facets count (api/entities.py)
        if ids is None:
            matched = await _all_unless_canceled(
                session, select(Mail.id).where(*where).limit(size + 1)
            )
            ids = None if matched is None else [row.id for row in matched]
        if ids is None:
            continue
        counted = await _all_unless_canceled(session, _text_counts(ids[:size]))
        if counted is not None:
            return TextPlaces(
                places=[_text_place(row) for row in counted],
                total=counted[0].total if counted else 0,
                exact=len(ids) <= size,
            )
    return TextPlaces(places=[], total=0, exact=False)


def _text_counts(mail_ids: Sequence[int]) -> Executable:
    """The place entities with a point that these mails mention, with the mails mentioning
    each, most first, and how many there are. The mentions are counted per entity first, as
    the facets count them (entities._facet_counts): starting from the few entities with a
    point, PostgreSQL joined every mention in an attachment's text again for each of them."""
    mention = mentions()
    counted = (
        select(mention.c.entity_id, _distinct_mails(mention))
        .where(mention.c.mail_id == any_(_ids(mail_ids)))
        .group_by(mention.c.entity_id)
        .subquery("counted")
    )
    return (
        select(*_PLACE_COLUMNS, counted.c.mails, func.count().over().label("total"))
        .join_from(counted, Entity, Entity.id == counted.c.entity_id)
        .where(*_LOCATED_PLACE)
        .order_by(counted.c.mails.desc(), Entity.id.desc())
        .limit(TEXT_PLACE_LIMIT)
    )


def _text_place(row: Any) -> TextPlace:
    return TextPlace(
        entity_id=row.id,
        label=row.label,
        place=row.place_label or row.label,
        detail=row.detail,
        lat=row.latitude,
        lon=row.longitude,
        mails=row.mails,
    )


# Places of invitations -----------------------------------------------------------------------


@dataclass(slots=True)
class _Point:
    """The events at one point and place, as event_places adds them up."""

    events: int = 0
    first: datetime | None = None
    last: datetime | None = None
    locations: list[tuple[int, str]] = field(default_factory=list)  # (events, as written)
    samples: list[PlaceEvent] = field(default_factory=list)


@router.get("/places/events")
async def event_places(
    params: Annotated[PlaceParams, Query()], session: Session, settings: AppSettings
) -> EventPlaces:
    where = await _mail_where(session, params, settings)
    # The events meeting the filters, found once for both queries below: the filters are tested
    # on each event's mail, and a full text word reads that mail's stored words.
    event_ids = list(
        await session.scalars(
            select(CalendarEvent.id)
            .join_from(CalendarEvent, Mail, Mail.id == CalendarEvent.mail_id)
            .where(CalendarEvent.latitude.is_not(None), CalendarEvent.longitude.is_not(None))
            .where(*where)
        )
    )

    if not event_ids:
        return EventPlaces(places=[], total=0)

    def matched(*columns: Any) -> Select[Any]:
        return select(*columns).where(CalendarEvent.id == any_(_ids(event_ids)))

    events = func.count().label("events")
    by_location = matched(
        *_EVENT_POINT,
        CalendarEvent.location,
        events,
        func.min(CalendarEvent.starts_at).label("first"),
        func.max(CalendarEvent.starts_at).label("last"),
    ).group_by(*_EVENT_POINT, CalendarEvent.location)
    points: dict[tuple[float, float, str | None], _Point] = {}
    for row in await session.execute(by_location):
        point = points.setdefault((row.latitude, row.longitude, row.place_label), _Point())
        point.events += row.events
        if row.first is not None:
            point.first = row.first if point.first is None else min(point.first, row.first)
        if row.last is not None:
            point.last = row.last if point.last is None else max(point.last, row.last)
        if row.location is not None:
            point.locations.append((row.events, row.location))
    rank = func.row_number().over(
        partition_by=_EVENT_POINT,
        order_by=(
            CalendarEvent.starts_at.desc().nulls_last(),
            CalendarEvent.starts_local.desc().nulls_last(),
            CalendarEvent.id.desc(),
        ),
    )
    ranked = matched(
        CalendarEvent.id,
        CalendarEvent.mail_id,
        CalendarEvent.kind,
        CalendarEvent.summary,
        CalendarEvent.location,
        CalendarEvent.starts_at,
        CalendarEvent.starts_local,
        CalendarEvent.all_day,
        CalendarEvent.uid,
        *_EVENT_POINT,
        rank.label("rank"),
    ).subquery("ranked")
    latest = select(ranked).where(ranked.c.rank <= PLACE_EVENTS_LIMIT).order_by(ranked.c.rank)
    for row in await session.execute(latest):
        found = points.get((row.latitude, row.longitude, row.place_label))
        if found is not None:
            found.samples.append(
                PlaceEvent(
                    event_id=row.id,
                    mail_id=row.mail_id,
                    kind=row.kind,
                    summary=row.summary,
                    location=row.location,
                    starts_at=row.starts_at,
                    starts_local=row.starts_local,
                    all_day=row.all_day,
                    uid=row.uid,
                )
            )
    places = []
    for (latitude, longitude, label), point in points.items():
        locations = [text for _, text in sorted(point.locations, key=lambda x: (-x[0], x[1]))]
        places.append(
            EventPlace(
                lat=latitude,
                lon=longitude,
                place=label or (locations[0] if locations else ""),
                locations=locations[:PLACE_LOCATIONS_LIMIT],
                events=point.events,
                first=point.first,
                last=point.last,
                samples=point.samples,
            )
        )
    places.sort(key=lambda place: (-place.events, place.place, place.lat, place.lon))
    return EventPlaces(places=places[:TEXT_PLACE_LIMIT], total=len(points))


# Summary -------------------------------------------------------------------------------------


@router.get("/places/summary")
async def summary(session: Session) -> PlaceSummary:
    photos, dated = (
        await session.execute(select(func.count(), func.count(_taken)).where(_PHOTO))
    ).one()
    count = func.count().label("photos")
    device = Document.metadata_device
    devices = await session.execute(
        select(device, count)
        .where(_PHOTO, device.is_not(None))
        .group_by(device)
        .order_by(count.desc(), device.collate("C"))
        .limit(DEVICE_LIMIT)
    )
    texts = await _place_counts(session, Entity.place_status, Entity.kind == EntityKind.PLACE)
    events = await _place_counts(
        session, CalendarEvent.place_status, func.btrim(CalendarEvent.location) != ""
    )
    figures = await read_figures(session)
    return PlaceSummary(
        photos=photos,
        photos_dated=dated,
        devices=[DeviceCount(device=row.metadata_device, photos=row.photos) for row in devices],
        texts=texts,
        events=events,
        outdated=figures is None or figures.version != gazetteer.places_version(),
        computed_at=None if figures is None else figures.computed_at,
    )


async def _place_counts(
    session: AsyncSession, status: Any, condition: ColumnElement[bool]
) -> PlaceCounts:
    """What the places step found for the rows meeting condition, by place_status."""
    counts = {
        value: n
        for value, n in await session.execute(
            select(status, func.count()).where(condition).group_by(status)
        )
    }
    return PlaceCounts(
        found=counts.get(PlaceStatus.FOUND, 0),
        ambiguous=counts.get(PlaceStatus.AMBIGUOUS, 0),
        unknown=counts.get(PlaceStatus.UNKNOWN, 0),
        waiting=counts.get(None, 0),
    )

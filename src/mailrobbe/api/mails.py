"""The mail list: search, filters, keyset pages, counts, neighbours, CSV export (D19 to D21, D25).

Routes: GET /api/mails, /api/mails/summary, /api/mails/export.csv, /api/mails/{id}/neighbors.
Registered before the detail router, so /api/mails/summary is not taken for a mail id.

Counts of a filtered list run under a statement timeout (MAILROBBE_API_COUNT_TIMEOUT) inside a
savepoint, so a count that runs out of time falls back to a bounded one and leaves the session
usable; the unfiltered figures come from global_stats.
"""

import csv
import io
from collections import defaultdict
from collections.abc import AsyncIterator, Collection, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Executable,
    Row,
    ScalarSelect,
    any_,
    distinct,
    func,
    literal,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from mailrobbe import aggregates
from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.filters import (
    Cursor,
    CursorError,
    FilterError,
    beyond,
    first_ids,
    internal_domains,
    mail_conditions,
    order,
    resolve_contents,
)
from mailrobbe.api.query import DKIM_KEYS, QueryError, parse_query
from mailrobbe.api.schemas import (
    COUNT_LIMIT,
    RECIPIENT_PREVIEW,
    DkimKey,
    MailFilters,
    MailListItem,
    MailListParams,
    MailNeighbors,
    MailOrderParams,
    MailPage,
    MailSummary,
    PersonRef,
    QueryTerm,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import Mail, MailMark, MailTag, MboxFile, Note, Participation, Person, Tag
from mailrobbe.enums import DkimStatus, ParticipationRole
from mailrobbe.persons.roots import member_ids

router = APIRouter(prefix="/api", tags=["mails"])

_Row = Row[*tuple[Any, ...]]

_ROLE_ORDER = {role: index for index, role in enumerate(ParticipationRole)}
_NO_FILTERS = MailFilters().model_dump(exclude={"q"})
_QUERY_CANCELED = "57014"  # SQLSTATE of a statement stopped by statement_timeout
CSV_BATCH = 1000  # rows per fetch from the server-side cursor and per chunk sent
CSV_FILENAME = "mailrobbe-mails.csv"
CSV_HEADER = (
    "ID",
    "Datum",
    "DKIM",
    "Von (Name)",
    "Von (Adresse)",
    "An",
    "Betreff",
    "Anhang",
    "Message-ID",
    "MBOX-Datei",
    "Offset",
)
_BOM = "\ufeff"  # spreadsheet programs then read the file as UTF-8
# Cells a spreadsheet would read as a formula get a leading apostrophe.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


# The research data of each row of a page (D53), read by its content's SHA-256 through the
# indexes on mail_tag and note: tag ids by name, and the number of notes.
_TAGS = func.array(
    select(MailTag.tag_id)
    .join(Tag, Tag.id == MailTag.tag_id)
    .where(MailTag.mail_sha256 == Mail.raw_sha256)
    .order_by(func.lower(Tag.name), Tag.id)
    .scalar_subquery(),
    type_=ARRAY(BigInteger),
).label("tags")
_NOTES = (
    select(func.count()).where(Note.mail_sha256 == Mail.raw_sha256).scalar_subquery().label("notes")
)


def _terms(q: str) -> list[QueryTerm]:
    try:
        return parse_query(q)
    except QueryError as error:
        raise api_error(400, "invalid_query", str(error)) from error


def _where(
    filters: MailFilters, terms: list[QueryTerm], settings: Settings
) -> list[ColumnElement[bool]]:
    """Every condition of the filters and of q's terms (400 invalid_filter)."""
    try:
        return mail_conditions(filters, terms, internal_domains(settings.internal_domains))
    except FilterError as error:
        raise api_error(400, "invalid_filter", str(error)) from error


@router.get("/mails")
async def list_mails(
    params: Annotated[MailListParams, Query()], session: Session, settings: AppSettings
) -> MailPage:
    terms = _terms(params.q)
    cursor = None
    if params.cursor is not None:
        try:
            cursor = Cursor.decode(params.cursor, params.sort)
        except CursorError as error:
            raise api_error(400, "invalid_cursor", str(error)) from error
    where = _where(params, terms, settings)
    reverse = cursor is not None and cursor.before
    after = None if cursor is None else (cursor.date_utc, cursor.mail_id)
    ids = await first_ids(
        session, where, params.sort, params.limit + 1, after=after, reverse=reverse
    )
    more = len(ids) > params.limit
    del ids[params.limit :]
    if reverse:
        ids.reverse()
    statement = (
        select(
            Mail.id,
            Mail.date_utc,
            Mail.subject,
            Mail.dkim_status,
            Mail.has_attachments,
            Mail.thread_id,
            Mail.is_duplicate_of,
            Mail.byte_length,
            Mail.mbox_file_id,
            func.coalesce(MailMark.flagged, False).label("flagged"),
            MailMark.review,
            _TAGS,
            _NOTES,
        )
        .outerjoin(MailMark, MailMark.mail_sha256 == Mail.raw_sha256)
        .where(Mail.id == any_(literal(ids, ARRAY(BigInteger))))
    )
    found = {row.id: row for row in await session.execute(statement)}
    rows = [found[mail_id] for mail_id in ids]
    people = await _participants(session, [row.id for row in rows])
    # The addresses of the one person filtered for, as the person filter reads them.
    members = set(await member_ids(session, params.person[0])) if len(params.person) == 1 else None

    def at(row: _Row, before: bool) -> str:
        return Cursor(params.sort, before, row.date_utc, row.id).encode()

    # A prev cursor walks backwards: "more" then means there are mails before this page.
    prev_cursor = next_cursor = None
    if cursor is None:
        next_cursor = at(rows[-1], False) if more else None
    elif cursor.before:
        prev_cursor = at(rows[0], True) if more else None
        next_cursor = at(rows[-1], False) if rows else cursor.flipped().encode()
    else:
        next_cursor = at(rows[-1], False) if more else None
        prev_cursor = at(rows[0], True) if rows else cursor.flipped().encode()
    return MailPage(
        items=[_item(row, people.get(row.id, []), members) for row in rows],
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        query_terms=terms,
    )


async def _participants(
    session: AsyncSession, mail_ids: Sequence[int]
) -> dict[int, list[tuple[ParticipationRole, PersonRef]]]:
    """Every participant of these mails, in one query."""
    rows = await session.execute(
        select(
            Participation.mail_id,
            Participation.role,
            Person.id,
            Person.canonical_email,
            func.coalesce(Participation.display_name, Person.display_name),
        )
        .join(Person, Person.id == Participation.person_id)
        .where(Participation.mail_id == any_(literal(list(mail_ids), ARRAY(BigInteger))))
    )
    people: defaultdict[int, list[tuple[ParticipationRole, PersonRef]]] = defaultdict(list)
    for mail_id, role, person_id, email, name in rows:
        people[mail_id].append((role, PersonRef(person_id=person_id, email=email, name=name)))
    for participants in people.values():
        participants.sort(key=_participant_order)
    return people


def _participant_order(participant: tuple[ParticipationRole, PersonRef]) -> tuple[Any, ...]:
    """From, To, Cc, Bcc; within a role by name (unnamed last), then address."""
    role, person = participant
    return (_ROLE_ORDER[role], person.name is None, (person.name or "").casefold(), person.email)


def _item(
    row: _Row,
    participants: list[tuple[ParticipationRole, PersonRef]],
    members: Collection[int] | None = None,
) -> MailListItem:
    """members: the addresses of the one person filtered for, whose first role the item names."""
    senders = [person for role, person in participants if role is ParticipationRole.FROM]
    recipients = [person for role, person in participants if role is not ParticipationRole.FROM]
    roles = [role for role, person in participants if members and person.person_id in members]
    return MailListItem(
        id=row.id,
        date=row.date_utc,
        subject=row.subject,
        dkim_status=row.dkim_status,
        has_attachments=row.has_attachments,
        sender=senders[0] if senders else None,
        recipients=recipients[:RECIPIENT_PREVIEW],
        recipient_count=len(recipients),
        thread_id=row.thread_id,
        is_duplicate=row.is_duplicate_of is not None,
        flagged=row.flagged,
        size=row.byte_length,
        mbox_file_id=row.mbox_file_id,
        person_role=min(roles, key=_ROLE_ORDER.__getitem__, default=None),
        review=row.review,
        tags=row.tags,
        notes=row.notes,
    )


# Summary and neighbours ----------------------------------------------------------------------


@router.get("/mails/summary")
async def summary(
    filters: Annotated[MailFilters, Query()], session: Session, settings: AppSettings
) -> MailSummary:
    terms = _terms(filters.q)
    if not terms and filters.model_dump(exclude={"q"}) == _NO_FILTERS:
        figures = await aggregates.current_global_stats(session, settings.stats_max_age)
        return MailSummary(
            total=figures.mails,
            exact=True,
            dkim=_dkim_counts(figures.dkim),
            persons=figures.persons,
            domains=figures.domains,
            date_min=figures.date_min,
            date_max=figures.date_max,
        )
    where = await resolve_contents(session, _where(filters, terms, settings))
    await _count_budget(session, settings)
    row = await _unless_canceled(session, _aggregate(where))
    if row is not None:
        total, *counts, date_min, date_max, persons, domains = row
        return MailSummary(
            total=total,
            exact=True,
            dkim=dict(zip(DKIM_KEYS, counts, strict=True)),
            persons=persons,
            domains=domains,
            date_min=date_min,
            date_max=date_max,
        )
    bounded = select(Mail.id).where(*where).limit(COUNT_LIMIT + 1).subquery()
    row = await _unless_canceled(session, select(func.count()).select_from(bounded))
    total = None if row is None else min(row[0], COUNT_LIMIT)
    return MailSummary(
        total=total,
        exact=row is not None and row[0] <= COUNT_LIMIT,
        dkim=None,
        persons=None,
        domains=None,
        date_min=None,
        date_max=None,
    )


def _aggregate(where: Sequence[ColumnElement[bool]]) -> Executable:
    """Count, DKIM counts (DKIM_KEYS order), date range, distinct persons and their domains."""
    matched = select(Mail.id, Mail.dkim_status, Mail.date_utc).where(*where).cte("matched")
    # Distinct participating addresses first (a hash aggregate down to a few thousand rows),
    # then their persons and domains.
    people = (
        select(Participation.person_id)
        .distinct()
        .join(matched, matched.c.id == Participation.mail_id)
        .cte("people")
    )

    def distinct_count(column: ColumnElement[Any]) -> ScalarSelect[int]:
        joined = select(func.count(distinct(column))).join_from(
            people, Person, Person.id == people.c.person_id
        )
        return joined.scalar_subquery()

    status = matched.c.dkim_status
    return select(
        func.count(),
        *(
            func.count().filter(
                status.is_(None) if key == "unchecked" else status == DkimStatus(key)
            )
            for key in DKIM_KEYS
        ),
        func.min(matched.c.date_utc),
        func.max(matched.c.date_utc),
        distinct_count(func.coalesce(Person.merged_into, Person.id)),
        distinct_count(Person.domain.expression),
    ).select_from(matched)


def _dkim_counts(counts: dict[str, int]) -> dict[DkimKey, int]:
    return {key: counts.get(key, 0) for key in DKIM_KEYS}


async def _count_budget(session: AsyncSession, settings: Settings) -> None:
    """The statement timeout for the counts of this request's transaction."""
    milliseconds = max(1, round(settings.api_count_timeout * 1000))
    await session.execute(select(func.set_config("statement_timeout", str(milliseconds), True)))


async def _unless_canceled(session: AsyncSession, statement: Executable) -> _Row | None:
    """The statement's one row, or None when the statement timeout stopped it."""
    try:
        async with session.begin_nested():
            return (await session.execute(statement)).one()
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) != _QUERY_CANCELED:
            raise
        return None


@router.get("/mails/{mail_id}/neighbors")
async def neighbors(
    mail_id: int,
    params: Annotated[MailOrderParams, Query()],
    session: Session,
    settings: AppSettings,
) -> MailNeighbors:
    where = _where(params, _terms(params.q), settings)
    found = (await session.execute(select(Mail.date_utc).where(Mail.id == mail_id))).one_or_none()
    if found is None:
        raise api_error(404, "not_found", f"no mail with id {mail_id}")
    date_utc = found.date_utc
    where = await resolve_contents(session, where)

    async def neighbour(reverse: bool) -> int | None:
        ids = await first_ids(
            session, where, params.sort, 1, after=(date_utc, mail_id), reverse=reverse
        )
        return ids[0] if ids else None

    prev_id = await neighbour(True)
    next_id = await neighbour(False)
    position = None
    if await session.scalar(select(Mail.id).where(Mail.id == mail_id, *where)) is not None:
        await _count_budget(session, settings)
        earlier = (
            select(Mail.id)
            .where(*where, beyond(params.sort, date_utc, mail_id, reverse=True))
            .limit(COUNT_LIMIT)
            .subquery()
        )
        row = await _unless_canceled(session, select(func.count()).select_from(earlier))
        if row is not None and row[0] < COUNT_LIMIT:
            position = row[0] + 1
    return MailNeighbors(prev_id=prev_id, next_id=next_id, position=position)


# CSV export ----------------------------------------------------------------------------------


@router.get("/mails/export.csv")
async def export_csv(
    params: Annotated[MailOrderParams, Query()], request: Request, settings: AppSettings
) -> StreamingResponse:
    where = _where(params, _terms(params.q), settings)
    sender_link, sender = aliased(Participation), aliased(Person)
    first_sender = (
        select(
            func.coalesce(sender_link.display_name, sender.display_name).label("name"),
            sender.canonical_email.label("email"),
        )
        .join(sender, sender.id == sender_link.person_id)
        .where(sender_link.mail_id == Mail.id, sender_link.role == ParticipationRole.FROM)
        .order_by(
            func.coalesce(sender_link.display_name, sender.display_name), sender.canonical_email
        )
        .limit(1)
        .lateral("first_sender")
    )
    recipient_link, recipient = aliased(Participation), aliased(Person)
    recipients = (
        select(
            func.string_agg(recipient.canonical_email, ", ").aggregate_order_by(
                recipient_link.role, recipient.canonical_email
            )
        )
        .join(recipient, recipient.id == recipient_link.person_id)
        .where(recipient_link.mail_id == Mail.id, recipient_link.role != ParticipationRole.FROM)
        .scalar_subquery()
    )
    statement = (
        select(
            Mail.id,
            Mail.date_utc,
            Mail.dkim_status,
            first_sender.c.name,
            first_sender.c.email,
            recipients,
            Mail.subject,
            Mail.has_attachments,
            Mail.message_id,
            MboxFile.path,
            Mail.byte_offset,
        )
        .join(MboxFile, MboxFile.id == Mail.mbox_file_id)
        .outerjoin(first_sender, true())
        .where(*where)
        .order_by(*order(params.sort))
    )
    return StreamingResponse(
        _csv_chunks(request.app.state.sessionmaker, statement),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{CSV_FILENAME}"'},
    )


async def _csv_chunks(
    sessionmaker: async_sessionmaker[AsyncSession], statement: Executable
) -> AsyncIterator[bytes]:
    """The CSV in chunks, read through a server-side cursor; its own session, as the request's
    session may be gone while the response streams."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    buffer.write(_BOM)
    writer.writerow(CSV_HEADER)
    async with sessionmaker() as session:
        result = await session.stream(statement.execution_options(yield_per=CSV_BATCH))
        async for rows in result.partitions():
            for row in rows:
                writer.writerow(_csv_row(row))
            yield _take(buffer).encode()
    yield _take(buffer).encode()


def _csv_row(row: _Row) -> list[str]:
    mail_id, date_utc, status, name, email, recipients, subject, attached, *rest = row
    message_id, path, offset = rest
    return [
        str(mail_id),
        "" if date_utc is None else date_utc.isoformat(),
        "unchecked" if status is None else status.value,
        _cell(name),
        _cell(email),
        _cell(recipients),
        _cell(subject),
        "ja" if attached else "nein",
        _cell(message_id),
        _cell(path),
        str(offset),
    ]


def _cell(value: str | None) -> str:
    """Text for a CSV cell; one a spreadsheet would take for a formula gets a leading '."""
    text = value or ""
    return "'" + text if text.startswith(_FORMULA_START) else text


def _take(buffer: io.StringIO) -> str:
    text = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate()
    return text

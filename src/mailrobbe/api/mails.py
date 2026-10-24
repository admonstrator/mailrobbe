"""The mail list: search, filters, keyset pages, counts, neighbours, CSV export (D19 to D21, D25).

Routes: GET /api/mails, /api/mails/summary, /api/mails/export.csv, /api/mails/{id}/neighbors.
Registered before the detail router, so /api/mails/summary is not taken for a mail id.

Counts of a filtered list run under a statement timeout (MAILROBBE_API_COUNT_TIMEOUT) inside a
savepoint, so a count that runs out of time falls back to a bounded one and leaves the session
usable; the unfiltered figures come from global_stats.

Hidden mails (D222): a filtered count counts the matches a hide rule hides beside the others,
in the same pass (VISIBLE as a column instead of a condition). Without filters the archive's
figures less the hidden ones: the stored figures of the hide rules (hiding.model) and a lookup
of the few mails the team keeps visible, so the first page stays a few cheap queries.
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
    Select,
    Text,
    all_,
    and_,
    any_,
    bindparam,
    distinct,
    func,
    literal,
    literal_column,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from mailrobbe import aggregates
from mailrobbe.api import events, near, paging
from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.filters import (
    VISIBLE,
    WALK_ROWS,
    Cursor,
    CursorError,
    FilterError,
    beyond,
    first_ids,
    internal_domains,
    mail_conditions,
    order,
    party_conditions,
    resolve_contents,
    text_query,
    unfiltered,
)
from mailrobbe.api.fulltext import full_text_search
from mailrobbe.api.hits import machine_hits, page_files, page_hits
from mailrobbe.api.query import DKIM_KEYS, QueryError, parse_query
from mailrobbe.api.schemas import (
    COUNT_LIMIT,
    HIT_FILES,
    RECIPIENT_PREVIEW,
    DkimKey,
    EntityRef,
    MailEntityHit,
    MailFilters,
    MailHitPerson,
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
from mailrobbe.db.models import (
    MAIL_SORT_KEY,
    TIMESTAMPTZ,
    Attachment,
    Entity,
    Mail,
    MailHidden,
    MailMark,
    MailSignal,
    MailTag,
    MboxFile,
    Note,
    Participation,
    Person,
    Tag,
)
from mailrobbe.entities.mentions import mentions
from mailrobbe.enums import DkimStatus, ParticipationRole, TextOrigin
from mailrobbe.hiding import model as hiding
from mailrobbe.persons.labels import attach_labels, label_text, labelled_persons
from mailrobbe.persons.roots import member_ids
from mailrobbe.signals.model import rules

router = APIRouter(prefix="/api", tags=["mails"])

_Row = Row[*tuple[Any, ...]]

_ROLE_ORDER = {role: index for index, role in enumerate(ParticipationRole)}
# The archive's figures answer a summary without filters, with or without the hidden mails.
_UNFILTERED = {"q", "include_hidden"}
_NO_FILTERS = MailFilters().model_dump(exclude=_UNFILTERED)
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
    "Signale",
    "Benennungen",
)
CSV_BOM = "\ufeff"  # spreadsheet programs then read the file as UTF-8
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
    jumped = None
    if paging.wanted(params.page, params.last):  # D193
        if cursor is not None:
            raise api_error(400, "invalid_cursor", "a cursor and a page to jump to")
        jumped = await _jump(session, settings, params, await resolve_contents(session, where))
        ids = list(jumped.rows)
    else:
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
    if jumped is not None:
        prev_cursor = at(rows[0], True) if jumped.before and rows else None
        next_cursor = at(rows[-1], False) if jumped.after and rows else None
    elif cursor is None:
        next_cursor = at(rows[-1], False) if more else None
    elif cursor.before:
        prev_cursor = at(rows[0], True) if more else None
        next_cursor = at(rows[-1], False) if rows else cursor.flipped().encode()
    else:
        next_cursor = at(rows[-1], False) if more else None
        prev_cursor = at(rows[0], True) if rows else cursor.flipped().encode()
    items = [_item(row, people.get(row.id, []), members) for row in rows]
    search = full_text_search(
        terms, params.scope, params.whole_word, params.min_hits, params.body_part
    )
    hits = {} if search is None else await page_hits(session, ids, search)  # D176
    if search is not None and search.counted:
        # D73 from the counts: no counted word in the mail itself, but in an attachment
        for item in items:
            item.hits = counts = hits[item.id]
            itself, attached = counts.subject + counts.body, counts.attachment + counts.filename
            item.attachment_match = itself == 0 and attached > 0
        in_texts = [item.id for item in items if hits[item.id].attachment > 0]
        machine = await machine_hits(session, in_texts, search)  # D189, D296
        named = [item.id for item in items if hits[item.id].attachment + hits[item.id].filename]
        files = await page_files(session, named, search, HIT_FILES)  # D344
        for item in items:
            origins = machine.get(item.id, set())
            item.attachment_machine = bool(origins)
            item.attachment_transcript = TextOrigin.TRANSCRIPT in origins
            item.hit_files = files.get(item.id, [])
    else:
        through_attachments = await _found_through_attachments(session, terms, ids)
        for item in items:
            item.hits = hits.get(item.id)
            item.attachment_match = item.id in through_attachments
    near_counts = await near.near_counts(session, ids)
    event_kinds = await events.event_kinds(session, ids)
    persons = await _hit_persons(session, ids, terms)
    entities = await _hit_entities(session, ids, params.entity)
    for item in items:
        item.near_count = near_counts.get(item.id, 0)
        item.event = event_kinds.get(item.id)
        item.hit_persons = persons.get(item.id, [])
        item.hit_entities = entities.get(item.id, [])
    page = MailPage(
        items=items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        query_terms=terms,
        page=jumped.page if jumped is not None else 1 if cursor is None else None,
    )
    await attach_labels(session, page)
    return page


# Hidden mails a jump through the unfiltered list passes as a list of ids at most (_by_id).
BY_ID_LIMIT = 50_000


async def _jump(
    session: AsyncSession,
    settings: Settings,
    params: MailListParams,
    where: Sequence[ColumnElement[bool]],
) -> paging.Jump:
    """The ids of the page a jump names (D193); where with its research filters resolved."""
    far = not params.last and (params.page or 1) * params.limit >= WALK_ROWS  # beyond the walk
    plain = await _by_id(session, where) if far and unfiltered(where) else None

    async def read(offset: int, limit: int, reverse: bool) -> list[int]:
        if offset + limit <= WALK_ROWS:  # the bounded walk, or every match when it runs out
            ids = await first_ids(session, where, params.sort, offset + limit, reverse=reverse)
            return ids[offset:]
        # Unfiltered: PostgreSQL walks ix_mail_sort, or sorts the table far from both ends.
        if plain is not None:
            ordered = select(Mail.id).where(*plain).order_by(*order(params.sort, reverse))
            return list(await session.scalars(ordered.offset(offset).limit(limit)))
        # Every match, then sorted as in filters.first_ids: MATERIALIZED keeps PostgreSQL from
        # walking the order for a filter it believes common.
        matched = (
            select(Mail.id, literal_column(MAIL_SORT_KEY, TIMESTAMPTZ).label("key"))
            .where(*where)
            .cte("matched")
            .prefix_with("MATERIALIZED")
        )
        down = (params.sort == "date_desc") != reverse
        by = [matched.c.key, matched.c.id]
        ordered = select(matched.c.id).order_by(*(c.desc() if down else c.asc() for c in by))
        return list(await session.scalars(ordered.offset(offset).limit(limit)))

    count = select(func.count()).select_from(Mail).where(*(where if plain is None else plain))
    return await paging.jump(
        session, settings, read, count, page=params.page, last=params.last, limit=params.limit
    )


async def _by_id(
    session: AsyncSession, where: Sequence[ColumnElement[bool]]
) -> list[ColumnElement[bool]] | None:
    """The unfiltered where (VISIBLE alone, or nothing) as a test of the mail's id: the hidden
    mails are found from mail_hidden first, so that counting reads an index alone and a page
    far into the archive needs no other column of the mails it passes. None for more than
    BY_ID_LIMIT hidden mails, whose list would weigh more than the walk it saves."""
    if not where:
        return []
    # A mail of mail_hidden fails VISIBLE unless it is kept (hiding.model); ~VISIBLE itself
    # would test every mail of the archive for a row in mail_hidden.
    hidden = select(MailHidden.mail_id).distinct().join(Mail, Mail.id == MailHidden.mail_id)
    ids = list(await session.scalars(hidden.where(~hiding.kept()).limit(BY_ID_LIMIT + 1)))
    if len(ids) > BY_ID_LIMIT:
        return None
    if not ids:
        return []
    await paging.custom_plans(session)
    return [Mail.id != all_(literal(sorted(ids), ARRAY(BigInteger)))]


async def _found_through_attachments(
    session: AsyncSession, terms: Sequence[QueryTerm], mail_ids: Sequence[int]
) -> set[int]:
    """The mails of a page that matched q's full text words through an attachment alone (D73):
    their own text does not match."""
    query = text_query(terms)
    if query is None or not mail_ids:
        return set()
    own = await session.scalars(
        select(Mail.id).where(
            Mail.id == any_(literal(list(mail_ids), ARRAY(BigInteger))),
            Mail.tsv.bool_op("@@")(query),
        )
    )
    return set(mail_ids) - set(own)


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


async def _hit_persons(
    session: AsyncSession, mail_ids: Sequence[int], terms: Sequence[QueryTerm]
) -> dict[int, list[MailHitPerson]]:
    """The participants of these mails that q's address operators name (D344), by the same
    conditions the filter uses, in the order of _participant_order."""
    parties = party_conditions(terms)
    if not parties or not mail_ids:
        return {}
    rows = await session.execute(
        select(
            Participation.mail_id,
            Participation.role,
            Person.id,
            Person.canonical_email,
            func.coalesce(Participation.display_name, Person.display_name),
        )
        .join(Person, Person.id == Participation.person_id)
        .where(
            Participation.mail_id == any_(literal(list(mail_ids), ARRAY(BigInteger))),
            or_(*(and_(Participation.role.in_(roles), person) for roles, person in parties)),
        )
        .distinct()
    )
    found: defaultdict[int, list[tuple[ParticipationRole, PersonRef]]] = defaultdict(list)
    for mail_id, role, person_id, email, name in rows:
        found[mail_id].append((role, PersonRef(person_id=person_id, email=email, name=name)))
    return {
        mail_id: [
            MailHitPerson(role=role, **person.model_dump())
            for role, person in sorted(participants, key=_participant_order)
        ]
        for mail_id, participants in found.items()
    }


async def _hit_entities(
    session: AsyncSession, mail_ids: Sequence[int], entity_ids: Sequence[int]
) -> dict[int, list[MailEntityHit]]:
    """Where these mails mention the entities the list is filtered by (D344): in their own text,
    in which attachments; in the order of entity_ids."""
    if not entity_ids or not mail_ids:
        return {}
    mention = mentions()
    rows = await session.execute(
        select(
            mention.c.mail_id,
            Entity.id,
            Entity.kind,
            Entity.label,
            Entity.detail,
            mention.c.document_id,
            Attachment.filename,
        )
        .join(Entity, Entity.id == mention.c.entity_id)
        .outerjoin(
            Attachment,
            and_(
                Attachment.mail_id == mention.c.mail_id,
                Attachment.document_id == mention.c.document_id,
            ),
        )
        .where(
            mention.c.mail_id == any_(literal(list(mail_ids), ARRAY(BigInteger))),
            mention.c.entity_id == any_(literal(list(entity_ids), ARRAY(BigInteger))),
        )
        .order_by(mention.c.mail_id, Attachment.position)
    )
    found: dict[int, dict[int, MailEntityHit]] = defaultdict(dict)
    for mail_id, entity_id, kind, label, detail, document_id, filename in rows:
        hit = found[mail_id].get(entity_id)
        if hit is None:
            entity = EntityRef(id=entity_id, kind=kind, label=label, detail=detail)
            hit = found[mail_id][entity_id] = MailEntityHit(entity=entity, in_mail=False, files=[])
        if document_id is None:
            hit.in_mail = True
        elif len(hit.files) < HIT_FILES and filename not in hit.files:
            hit.files.append(filename)
    position = {entity_id: index for index, entity_id in enumerate(entity_ids)}
    return {
        mail_id: sorted(hits.values(), key=lambda hit: position[hit.entity.id])
        for mail_id, hits in found.items()
    }


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
    if not terms and filters.model_dump(exclude=_UNFILTERED) == _NO_FILTERS:
        return await _archive_summary(session, settings, filters.include_hidden)
    where = _where(filters, terms, settings)
    # The hidden mails are counted beside the others: VISIBLE moves from the conditions into the
    # count, so the hidden matches cost no second pass (D222).
    counted = [condition for condition in where if condition is not VISIBLE]
    shown = hiding.shown() if len(counted) < len(where) else None
    where = await resolve_contents(session, counted)
    await _count_budget(session, settings)
    row = await _unless_canceled(session, _aggregate(where, shown))
    if row is not None:
        total, *counts, date_min, date_max, persons, domains, hidden = row
        return MailSummary(
            total=total,
            exact=True,
            dkim=dict(zip(DKIM_KEYS, counts, strict=True)),
            persons=persons,
            domains=domains,
            date_min=date_min,
            date_max=date_max,
            hidden=None if shown is None else hidden,
        )
    if shown is not None:
        where.append(shown)
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


async def _archive_summary(
    session: AsyncSession, settings: Settings, include_hidden: bool
) -> MailSummary:
    """The archive's figures (global_stats), without include_hidden less the mails a hide rule
    hides; persons, domains and dates stay the archive's (D222)."""
    figures = await aggregates.current_global_stats(session, settings.stats_max_age)
    dkim = _dkim_counts(figures.dkim)
    hidden: dict[DkimKey, int] = {}
    if not include_hidden:
        matched = await hiding.current_figures(session, figures.updated_at)
        kept = await hiding.kept_counts(session) if matched.mails else {}
        hidden = {key: matched.dkim.get(key, 0) - kept.get(key, 0) for key in dkim}
    return MailSummary(
        total=figures.mails - sum(hidden.values()),
        exact=True,
        dkim={key: count - hidden.get(key, 0) for key, count in dkim.items()},
        persons=figures.persons,
        domains=figures.domains,
        date_min=figures.date_min,
        date_max=figures.date_max,
        hidden=None if include_hidden else sum(hidden.values()),
    )


def _aggregate(
    where: Sequence[ColumnElement[bool]], shown: ColumnElement[bool] | None = None
) -> Executable:
    """Count, DKIM counts (DKIM_KEYS order), date range, distinct persons and their domains of
    the mails shown, then the hidden ones; shown None: every match is shown."""
    visible = true() if shown is None else shown
    matched = (
        select(Mail.id, Mail.dkim_status, Mail.date_utc, visible.label("shown"))
        .where(*where)
        .cte("matched")
    )
    shown_mail = matched.c.shown
    # Distinct participating addresses first (a hash aggregate down to a few thousand rows),
    # then their persons and domains.
    people = (
        select(Participation.person_id)
        .distinct()
        .join(matched, matched.c.id == Participation.mail_id)
        .where(shown_mail)
        .cte("people")
    )

    def distinct_count(column: ColumnElement[Any]) -> ScalarSelect[int]:
        joined = select(func.count(distinct(column))).join_from(
            people, Person, Person.id == people.c.person_id
        )
        return joined.scalar_subquery()

    status = matched.c.dkim_status
    return select(
        func.count().filter(shown_mail),
        *(
            func.count().filter(
                shown_mail, status.is_(None) if key == "unchecked" else status == DkimStatus(key)
            )
            for key in DKIM_KEYS
        ),
        func.min(matched.c.date_utc).filter(shown_mail),
        func.max(matched.c.date_utc).filter(shown_mail),
        distinct_count(func.coalesce(Person.merged_into, Person.id)),
        distinct_count(Person.domain.expression),
        func.count().filter(~shown_mail),
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
    # The signals the last signals phase stored (D139), named in display order in Python.
    signals = func.array(
        select(MailSignal.signal).where(MailSignal.mail_id == Mail.id).scalar_subquery(),
        type_=ARRAY(Text),
    )
    # Its participants that show a label (D157): the persons labelled_persons finds when the
    # CSV starts, named in Python.
    named = func.array(
        select(Participation.person_id)
        .where(
            Participation.mail_id == Mail.id,
            Participation.person_id == any_(bindparam("named", type_=ARRAY(BigInteger))),
        )
        .order_by(Participation.role, Participation.person_id)
        .scalar_subquery(),
        type_=ARRAY(BigInteger),
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
            signals,
            named,
        )
        .join(MboxFile, MboxFile.id == Mail.mbox_file_id)
        .outerjoin(first_sender, true())
        .where(*where)
        .order_by(*order(params.sort))
    )
    signal_rules = rules(settings)
    labels = {key: signal_rules.label(key) for key in signal_rules.keys}
    return StreamingResponse(
        _csv_chunks(request.app.state.sessionmaker, statement, labels),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{CSV_FILENAME}"'},
    )


async def _csv_chunks(
    sessionmaker: async_sessionmaker[AsyncSession], statement: Select[Any], labels: dict[str, str]
) -> AsyncIterator[bytes]:
    """The CSV in chunks, read through a server-side cursor; its own session, as the request's
    session may be gone while the response streams. labels: the German name of each signal, in
    display order."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    buffer.write(CSV_BOM)
    writer.writerow(CSV_HEADER)
    async with sessionmaker() as session:
        named = {
            person_id: text
            for person_id, (email, label) in (await labelled_persons(session)).items()
            if (text := label_text(label, email))
        }
        statement = statement.params(named=list(named))
        result = await session.stream(statement.execution_options(yield_per=CSV_BATCH))
        async for rows in result.partitions():
            for row in rows:
                writer.writerow(_csv_row(row, labels, named))
            yield _take(buffer).encode()
    yield _take(buffer).encode()


def _csv_row(row: _Row, labels: dict[str, str], named: dict[int, str]) -> list[str]:
    """named: the label_text of each person whose label has a name or role."""
    mail_id, date_utc, status, name, email, recipients, subject, attached, *rest = row
    message_id, path, offset, signals, participants = rest
    return [
        str(mail_id),
        "" if date_utc is None else date_utc.isoformat(),
        "unchecked" if status is None else status.value,
        csv_cell(name),
        csv_cell(email),
        csv_cell(recipients),
        csv_cell(subject),
        "ja" if attached else "nein",
        csv_cell(message_id),
        csv_cell(path),
        str(offset),
        csv_cell(", ".join(label for key, label in labels.items() if key in signals)),
        csv_cell("; ".join(dict.fromkeys(named[person] for person in participants))),
    ]


def csv_cell(value: str | None) -> str:
    """Text for a CSV cell; one a spreadsheet would take for a formula gets a leading '."""
    text = value or ""
    return "'" + text if text.startswith(_FORMULA_START) else text


def _take(buffer: io.StringIO) -> str:
    text = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate()
    return text


# List items for other views: the examples of a hide rule's preview (D223) ----------------------


async def _rows(session: AsyncSession, ids: list[int]) -> list[_Row]:
    """The columns of a list item of each mail, in the order of ids, as list_mails reads them;
    ids that are gone are left out."""
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
    return [found[mail_id] for mail_id in ids if mail_id in found]


async def mail_items(session: AsyncSession, ids: list[int]) -> list[MailListItem]:
    """These mails as the list shows them, in this order, without search hits; labels are set
    by the caller's attach_labels."""
    rows = await _rows(session, ids)
    people = await _participants(session, ids)
    items = [_item(row, people.get(row.id, [])) for row in rows]
    near_counts = await near.near_counts(session, ids)
    event_kinds = await events.event_kinds(session, ids)
    for item in items:
        item.near_count = near_counts.get(item.id, 0)
        item.event = event_kinds.get(item.id)
    return items

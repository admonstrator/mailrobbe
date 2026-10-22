"""Entities (milestone 10, D80 to D89): the entity list and its summary, refs for filter chips,
an entity's page, the facets of the mail list and the entities of one mail. Endpoints and models
are in schemas.py; the mail list's entity and amount filters (D86) are in filters.py.

Routes: GET /api/entities, /api/entities/summary, /api/entities/refs, /api/entities/{id},
/api/mails/facets, /api/mails/{id}/entities. Registered before the detail router, so that
/api/mails/facets is not taken for a mail id; the static entity paths come before {id}.

Mentions are read through entities.mentions: a mail's own and those of its attachments'
documents, so that an entity in a document counts for every mail carrying it (D80). A condition
on its entity_id or mail_id reaches both branches of that UNION ALL, so PostgreSQL reads the
mentions of one entity (pk_mail_entity, pk_document_entity) or of some mails
(ix_mail_entity_mail_id, ix_attachment_mail_id), never all of them.

The list pages by keyset as the document list does (D88): a cursor names the sort key of its
boundary row and is bound to the sort order, ties go by id in the direction of the sort, and the
sorts by mails, first mention and value walk their indexes (ix_entity_mails or
ix_entity_kind_mails, ix_entity_first_date, ix_entity_value). The name order, lower(label) in
code point order, has no index and sorts the matching entities.

Facets (D87): without filters they are entity.mails, the top of each kind read from
ix_entity_kind_mails. With filters they are counted: the ids of at most FACET_MAILS matching
mails, the first ones PostgreSQL finds, then their mentions per entity as distinct mails
(_distinct_mails), both under the count budget of the mail list's summary (D19). When it runs
out, FACET_FALLBACK of those mails are counted instead, and when that runs out too, there are
no facets.

An entity's page counts contexts and years over every mentioning mail that is no duplicate, as
entity.mails does (D85); the persons and related entities, which read every participant and
every mention of those mails, over at most FACET_MAILS of them.
"""

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

import fastapi
from fastapi import APIRouter, Query
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Executable,
    Integer,
    Numeric,
    SQLColumnExpression,
    Text,
    any_,
    case,
    exists,
    func,
    literal,
    literal_column,
    select,
    union_all,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.detail import mail_senders
from mailrobbe.api.documents import _all_unless_canceled, mail_persons
from mailrobbe.api.filters import _contains, _escape_like, amount, resolve_contents, unfiltered
from mailrobbe.api.mails import _count_budget, _terms, _where
from mailrobbe.api.persons import _DUPLICATES, _beyond, _by, _Cursor, _int, _stamp, _text
from mailrobbe.api.schemas import (
    ENTITY_PERSONS_LIMIT,
    ENTITY_REFS_LIMIT,
    ENTITY_RELATED_LIMIT,
    ENTITY_SAMPLES,
    ENTITY_SNIPPET_LENGTH,
    FACET_MAILS,
    EntityContextKey,
    EntityCount,
    EntityDetail,
    EntityFacetParams,
    EntityFacets,
    EntityListItem,
    EntityListParams,
    EntityPage,
    EntityRef,
    EntitySample,
    EntitySort,
    EntitySummary,
    EntityYear,
    MailEntity,
    PersonRef,
    ThreadMail,
)
from mailrobbe.db.models import (
    FIRST_DATE_SORT_KEY,
    TIMESTAMPTZ,
    Document,
    DocumentEntityScan,
    Entity,
    Mail,
    MailEntityScan,
    Person,
    PersonEmail,
)
from mailrobbe.entities.mentions import mentions
from mailrobbe.entities.model import scan_version
from mailrobbe.enums import DocumentTextStatus, EntityContext, EntityKind
from mailrobbe.persons.labels import attach_labels
from mailrobbe.persons.roots import ROOT

router = APIRouter(prefix="/api", tags=["entities"])

# entity.id and mail.id are bigints: a larger number is a validation error.
EntityId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]
MailId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]

FACET_FALLBACK = 1_000  # mails the facets count over when FACET_MAILS took too long (D87)

_FIRST_DATE: ColumnElement[Any] = literal_column(FIRST_DATE_SORT_KEY, TIMESTAMPTZ)
_NO_DATE = literal_column("'-infinity'::timestamp with time zone", TIMESTAMPTZ)
_LABEL_KEY = func.lower(Entity.label)
_CONTEXTS: dict[EntityContextKey, EntityContext] = {
    "cash": EntityContext.CASH,
    "donation": EntityContext.DONATION,
    "receipt": EntityContext.RECEIPT,
}
_KIND_ORDER = {kind: index for index, kind in enumerate(EntityKind)}
_WITH_TEXT = (DocumentTextStatus.TEXT, DocumentTextStatus.TIMEOUT)  # scanned texts (D84)
_BIGINT = range(-(2**63), 2**63)
_REF_COLUMNS = (Entity.id, Entity.kind, Entity.label, Entity.detail)
_ITEM_COLUMNS = (
    *_REF_COLUMNS,
    Entity.value,
    Entity.currency,
    Entity.mails,
    Entity.documents,
    Entity.first_date,
    Entity.last_date,
)


def _ref(row: Any) -> EntityRef:
    return EntityRef(id=row.id, kind=row.kind, label=row.label, detail=row.detail)


def _figures(row: Any) -> dict[str, Any]:
    """The fields of EntityListItem."""
    return {
        **_ref(row).model_dump(),
        "value": None if row.value is None else float(row.value),
        "currency": row.currency,
        "mails": row.mails,
        "documents": row.documents,
        "first_date": row.first_date,
        "last_date": row.last_date,
    }


def _ids(values: Sequence[int]) -> ColumnElement[Any]:
    return literal(list(values), ARRAY(BigInteger))


# List ----------------------------------------------------------------------------------------


def _decimal(value: Any) -> Decimal:
    """A value sort's cursor key: the value as text, as Decimal keeps it."""
    try:
        return Decimal(_text(value))
    except InvalidOperation as error:
        raise ValueError("not a number") from error


def _sort_key(
    sort: EntitySort,
) -> tuple[SQLColumnExpression[Any], SQLColumnExpression[Any], bool, Any]:
    """The sort key before the id, the column a cursor keeps of it, whether it descends, and how
    a cursor's value is read. The first date keeps first_date itself, as its key is -infinity
    without one; the value keeps its decimal digits as text."""
    match sort:
        case "mails":
            return Entity.mails, Entity.mails, True, _int
        case "recent":
            return _FIRST_DATE, Entity.first_date, True, _stamp
        case "oldest":
            return _FIRST_DATE, Entity.first_date, False, _stamp
        case "value":
            return Entity.value, Entity.value, True, _decimal
    return _LABEL_KEY.collate("C"), _LABEL_KEY, False, _text


def _boundary(sort: EntitySort, value: Any) -> ColumnElement[Any]:
    match sort:
        case "mails":
            return literal(value, Integer)
        case "recent" | "oldest":
            return func.coalesce(literal(value, TIMESTAMPTZ), _NO_DATE)
        case "value":
            return literal(value, Numeric())
    return literal(value, Text)


def _list_conditions(params: EntityListParams) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = []
    if params.kind:
        where.append(Entity.kind.in_(sorted(set(params.kind))))
    if params.q.strip():
        where.append(Entity.label.ilike(_contains(params.q.strip())))  # ix_entity_label_trgm
    if params.detail is not None:
        where.append(Entity.detail == params.detail)
    if params.value_min is not None:
        where.append(Entity.value >= amount(params.value_min))
    if params.value_max is not None:
        where.append(Entity.value <= amount(params.value_max))
    if params.sort == "value":  # entities without a value have no place in that order
        where.append(Entity.value.is_not(None))
    return where


@router.get("/entities")
async def list_entities(
    params: Annotated[EntityListParams, Query()], session: Session
) -> EntityPage:
    scope = f"entities/{params.sort}"
    key, kept, descending, kind = _sort_key(params.sort)
    cursor = _Cursor.decode(params.cursor, scope, (kind, _int))
    columns = [key, Entity.id]
    reverse = cursor is not None and cursor.before
    start = []
    if cursor is not None:
        boundary = [_boundary(params.sort, cursor.key[0]), literal(cursor.key[1], BigInteger)]
        start.append(_beyond(columns, boundary, descending != reverse))
    statement = (
        select(*_ITEM_COLUMNS, kept.label("key"))
        .where(*_list_conditions(params), *start)
        .order_by(*_by(columns, descending != reverse))
        .limit(params.limit + 1)
    )
    rows: list[Any] = list(await session.execute(statement))
    more = len(rows) > params.limit
    del rows[params.limit :]
    if reverse:
        rows.reverse()

    def at(row: Any, before: bool) -> str:
        value = str(row.key) if isinstance(row.key, Decimal) else row.key
        return _Cursor(scope, before, (value, row.id)).encode()

    # As in the mail list: a prev cursor walks backwards, "more" then means rows before the page.
    prev_cursor = next_cursor = None
    if cursor is None:
        next_cursor = at(rows[-1], False) if more else None
    elif cursor.before:
        prev_cursor = at(rows[0], True) if more else None
        next_cursor = at(rows[-1], False) if rows else cursor.flipped().encode()
    else:
        next_cursor = at(rows[-1], False) if more else None
        prev_cursor = at(rows[0], True) if rows else cursor.flipped().encode()
    return EntityPage(
        items=[EntityListItem(**_figures(row)) for row in rows],
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
    )


@router.get("/entities/summary")
async def entity_summary(session: Session) -> EntitySummary:
    kinds = dict.fromkeys(EntityKind, 0)
    for kind, count in await session.execute(
        select(Entity.kind, func.count()).group_by(Entity.kind)
    ):
        kinds[kind] = count
    # Anti joins on the scan tables' primary keys (D84): the mails, and the document texts,
    # that the current extraction has not scanned, or a text extracted again since its scan.
    version = scan_version()
    mail_scanned = exists().where(
        MailEntityScan.mail_id == Mail.id, MailEntityScan.version == version
    )
    text_scanned = exists().where(
        DocumentEntityScan.document_id == Document.id,
        DocumentEntityScan.version == version,
        DocumentEntityScan.extracted_at.is_not_distinct_from(Document.extracted_at),
    )
    mails_waiting = await session.scalar(
        select(func.count()).select_from(Mail).where(~mail_scanned)
    )
    documents_waiting = await session.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.text_status.in_(_WITH_TEXT), ~text_scanned)
    )
    return EntitySummary(
        kinds=kinds, mails_waiting=mails_waiting or 0, documents_waiting=documents_waiting or 0
    )


@router.get("/entities/refs")
async def entity_refs(
    session: Session, ids: Annotated[list[int] | None, Query(alias="id")] = None
) -> list[EntityRef]:
    """The entities of these ids that exist, in the order asked (the mail list's filter chips)."""
    asked = ids or []
    if len(asked) > ENTITY_REFS_LIMIT:
        raise api_error(400, "invalid_filter", f"at most {ENTITY_REFS_LIMIT} ids")
    usable = [entity_id for entity_id in dict.fromkeys(asked) if entity_id in _BIGINT]
    if not usable:
        return []
    rows = await session.execute(select(*_REF_COLUMNS).where(Entity.id == any_(_ids(usable))))
    found = {row.id: _ref(row) for row in rows}
    return [found[entity_id] for entity_id in usable if entity_id in found]


# One entity ----------------------------------------------------------------------------------


@router.get("/entities/{entity_id}")
async def entity_detail(entity_id: EntityId, session: Session) -> EntityDetail:
    found = await session.execute(select(*_ITEM_COLUMNS, Entity.key).where(Entity.id == entity_id))
    entity = found.one_or_none()
    if entity is None:
        raise api_error(404, "not_found", f"no entity with id {entity_id}")
    years, contexts = await _years(session, entity_id)
    # The mails the persons and related entities are counted over: any FACET_MAILS of them.
    mention = mentions()
    mentioning = (
        select(mention.c.mail_id)
        .distinct()
        .where(mention.c.entity_id == entity_id, mention.c.mail_id.not_in(_DUPLICATES))
        .limit(FACET_MAILS + 1)
    )
    sample = list(await session.scalars(mentioning))
    sampled = len(sample) > FACET_MAILS
    del sample[FACET_MAILS:]
    mail_ids = select(func.unnest(_ids(sample)))
    senders, sender_count, recipients, recipient_count = await mail_persons(
        session, mail_ids, ENTITY_PERSONS_LIMIT
    )
    detail = EntityDetail(
        **_figures(entity),
        key=entity.key,
        contexts=contexts,
        years=years,
        senders=senders,
        sender_count=sender_count,
        recipients=recipients,
        recipient_count=recipient_count,
        related=await _related(session, entity_id, sample),
        persons_sampled=sampled,
        samples=await _samples(session, entity_id),
        archive_person=await _archive_person(session, entity.kind, entity.key, entity.label),
    )
    await attach_labels(session, detail)
    return detail


async def _years(
    session: AsyncSession, entity_id: int
) -> tuple[list[EntityYear], dict[EntityContextKey, int]]:
    """The mentioning mails that are no duplicates per UTC year (undated ones in none), and
    per context of their mentions (D82): one pass over the mentions, a row per mail."""
    mention = mentions()
    per_mail = (
        select(mention.c.mail_id, func.bit_or(mention.c.context).label("context"))
        .where(mention.c.entity_id == entity_id)
        .group_by(mention.c.mail_id)
        .subquery("per_mail")
    )
    # literal constants: as parameters, PostgreSQL would not see GROUP BY's expression as the
    # selected one
    utc = func.timezone(literal_column("'UTC'"), Mail.date_utc)
    year = func.date_part(literal_column("'year'"), utc).cast(Integer)
    flags = per_mail.c.context
    counts = (
        func.count().filter(flags.op("&")(int(flag)) != 0).label(key)
        for key, flag in _CONTEXTS.items()
    )
    rows = list(
        await session.execute(
            select(year.label("year"), func.count().label("mails"), *counts)
            .join_from(per_mail, Mail, Mail.id == per_mail.c.mail_id)
            .where(Mail.is_duplicate_of.is_(None))
            .group_by(year)
        )
    )
    years = [
        EntityYear(year=row.year, mails=row.mails)
        for row in sorted(rows, key=lambda row: row.year or 0)
        if row.year is not None
    ]
    contexts = {key: sum(getattr(row, key) for row in rows) for key in _CONTEXTS}
    return years, contexts


async def _related(
    session: AsyncSession, entity_id: int, mail_ids: Sequence[int]
) -> list[EntityCount]:
    """The other entities mentioned in these mails, most shared mails first."""
    if not mail_ids:
        return []
    mention = mentions()
    shared = _distinct_mails(mention)
    top = (
        select(mention.c.entity_id, shared)
        .where(mention.c.mail_id == any_(_ids(mail_ids)), mention.c.entity_id != entity_id)
        .group_by(mention.c.entity_id)
        .order_by(shared.desc(), mention.c.entity_id.desc())
        .limit(ENTITY_RELATED_LIMIT)
        .subquery("top")
    )
    rows = await session.execute(
        select(*_REF_COLUMNS, top.c.mails)
        .join_from(top, Entity, Entity.id == top.c.entity_id)
        .order_by(top.c.mails.desc(), Entity.id.desc())
    )
    return [EntityCount(entity=_ref(row), mails=row.mails) for row in rows]


# A snippet comes from the text from ENTITY_SNIPPET_LENGTH characters before the mention on, at
# most _SPAN characters of it; one more says whether the text goes on.
_SPAN = 2 * ENTITY_SNIPPET_LENGTH
_SPACE = re.compile(r"\s")
_ELLIPSIS = "…"


async def _samples(session: AsyncSession, entity_id: int) -> list[EntitySample]:
    """The earliest mentioning mails that are no duplicates (undated ones last), each with the
    text around its mention: the mail's own, else the one in its attachments' document of the
    lowest id. The text is cut in PostgreSQL, so that a long document stays there."""
    mention = mentions()
    earliest = (
        select(Mail.id, Mail.date_utc, Mail.subject, Mail.dkim_status)
        .where(
            Mail.id.in_(select(mention.c.mail_id).where(mention.c.entity_id == entity_id)),
            Mail.is_duplicate_of.is_(None),
        )
        .order_by(Mail.date_utc.asc().nulls_last(), Mail.id)
        .limit(ENTITY_SAMPLES)
    )
    mails = list(await session.execute(earliest))
    ids = [row.id for row in mails]
    if not ids:
        return []
    shown = mentions("shown")
    first = (
        select(shown.c.mail_id, shown.c.position, shown.c.document_id)
        .where(shown.c.entity_id == entity_id, shown.c.mail_id == any_(_ids(ids)))
        .order_by(shown.c.mail_id, shown.c.document_id.asc().nulls_first())
        .ext(postgresql.distinct_on(shown.c.mail_id))
        .subquery("first")
    )
    start = func.greatest(0, first.c.position - ENTITY_SNIPPET_LENGTH)
    text = case(  # entities.model.scanned_text for the mail's own mentions
        (first.c.document_id.is_(None), func.concat(Mail.subject, "\n", Mail.body_text)),
        else_=Document.extracted_text,
    )
    rows = await session.execute(
        select(
            first.c.mail_id,
            first.c.position,
            first.c.document_id,
            Document.name,
            start.label("start"),
            func.substr(text, start + 1, _SPAN + 1).label("around"),
        )
        .join(Mail, Mail.id == first.c.mail_id)
        .outerjoin(Document, Document.id == first.c.document_id)
    )
    texts = {row.mail_id: row for row in rows}
    senders = await mail_senders(session, ids)
    samples = []
    for mail in mails:
        found = texts.get(mail.id)
        snippet = None
        if found is not None and found.around:
            snippet = mention_snippet(found.around, found.position - found.start, found.start > 0)
        samples.append(
            EntitySample(
                mail=ThreadMail(
                    id=mail.id,
                    date=mail.date_utc,
                    subject=mail.subject,
                    sender=senders.get(mail.id),
                    dkim_status=mail.dkim_status,
                ),
                snippet=snippet,
                document_id=None if found is None else found.document_id,
                document_name=None if found is None else found.name,
            )
        )
    return samples


def mention_snippet(around: str, at: int, cut: bool) -> str | None:
    """At most ENTITY_SNIPPET_LENGTH characters of around with the mention at offset `at`, in
    whole words where it can, whitespace collapsed, with … where the text goes on. cut: around
    does not begin at the start of the text; one character beyond _SPAN: it goes on after."""
    more = len(around) > _SPAN
    around = around[:_SPAN]
    at = min(max(at, 0), len(around))
    begin = max(0, at - ENTITY_SNIPPET_LENGTH // 4)
    if begin > 0 and not around[begin - 1].isspace():  # begin with a whole word
        space = _SPACE.search(around, begin, at)
        begin = space.end() if space else begin
    lead = _ELLIPSIS if cut or begin > 0 else ""
    words = " ".join(around[begin:].split())
    room = ENTITY_SNIPPET_LENGTH - len(lead)
    if more or len(words) > room:
        keep = room - len(_ELLIPSIS)
        if len(words) > keep and words[keep] != " ":  # end with a whole word
            end = words.rfind(" ", 0, keep)
            keep = end if end > room // 2 else keep  # unless that drops too much
        words = words[:keep].rstrip() + _ELLIPSIS
    return lead + words if words.strip(_ELLIPSIS + " ") else None


async def _archive_person(
    session: AsyncSession, kind: EntityKind, key: str, label: str
) -> PersonRef | None:
    """The root person behind an address (person_email), or the one root person whose display
    name is this name in any case (an ILIKE without wildcards, served by the trigram index)."""
    match kind:
        case EntityKind.EMAIL:
            owner = (
                select(ROOT)
                .join(PersonEmail, PersonEmail.person_id == Person.id)
                .where(PersonEmail.email == key.lower())
            )
            roots = list(await session.scalars(owner))
        case EntityKind.PERSON:
            named = (
                select(Person.id)
                .where(Person.merged_into.is_(None), Person.display_name.ilike(_escape_like(label)))
                .limit(2)
            )
            roots = list(await session.scalars(named))
        case _:
            return None
    if len(roots) != 1:
        return None
    row = (
        await session.execute(
            select(Person.id, Person.canonical_email, Person.display_name).where(
                Person.id == roots[0]
            )
        )
    ).one()
    return PersonRef(person_id=row.id, email=row.canonical_email, name=row.display_name)


# Facets --------------------------------------------------------------------------------------


@router.get("/mails/facets")
async def facets(
    params: Annotated[EntityFacetParams, Query()], session: Session, settings: AppSettings
) -> EntityFacets:
    only = sorted(set(params.kind), key=_KIND_ORDER.__getitem__)
    where = _where(params, _terms(params.q), settings)
    if unfiltered(where):
        top = await _top_entities(session, only or list(EntityKind), params.limit)
        return EntityFacets(kinds=top, mails=None, sampled=False)
    where = await resolve_contents(session, where)
    await _count_budget(session, settings)
    ids: list[int] | None = None
    for size in (FACET_MAILS, FACET_FALLBACK):
        if ids is None:
            matched = select(Mail.id).where(*where).limit(size + 1)
            found = await _all_unless_canceled(session, matched)
            ids = None if found is None else [row.id for row in found]
        if ids is None:
            continue
        sample = ids[:size]
        counted = await _all_unless_canceled(session, _facet_counts(sample, only, params.limit))
        if counted is not None:
            return EntityFacets(kinds=_by_kind(counted), mails=len(sample), sampled=len(ids) > size)
    return EntityFacets(kinds={}, mails=None, sampled=False)


async def _top_entities(
    session: AsyncSession, kinds: Sequence[EntityKind], limit: int
) -> dict[EntityKind, list[EntityCount]]:
    """The entities with most mails of each kind (entity.mails), each kind read backwards from
    ix_entity_kind_mails. Entities whose figures are 0 (only in duplicates, or not counted yet
    after a stopped phase, D85) are no signposts and left out."""
    tops = [
        select(*_REF_COLUMNS, Entity.mails)
        .where(Entity.kind == kind, Entity.mails > 0)
        .order_by(Entity.mails.desc(), Entity.id.desc())
        .limit(limit)
        .subquery()
        for kind in kinds
    ]
    rows = await session.execute(union_all(*(select(top) for top in tops)))
    return _by_kind(list(rows))


def _facet_counts(mail_ids: Sequence[int], kinds: Sequence[EntityKind], limit: int) -> Executable:
    """Per entity (of these kinds; empty: all), the distinct mails among mail_ids mentioning
    it, the `limit` with most of each kind; ties by id, as in the list."""
    mention = mentions()
    counted = (
        select(mention.c.entity_id, _distinct_mails(mention))
        .where(mention.c.mail_id == any_(_ids(mail_ids)))
        .group_by(mention.c.entity_id)
        .subquery("counted")
    )
    rank = func.row_number().over(
        partition_by=Entity.kind, order_by=(counted.c.mails.desc(), Entity.id.desc())
    )
    ranked = select(*_REF_COLUMNS, counted.c.mails, rank.label("rank")).join_from(
        counted, Entity, Entity.id == counted.c.entity_id
    )
    if kinds:
        ranked = ranked.where(Entity.kind.in_(kinds))
    top = ranked.subquery("ranked")
    return select(top).where(top.c.rank <= limit)


def _distinct_mails(mention: Any) -> ColumnElement[int]:
    """The distinct mails of each group of mentions, as `mails`: an entity can be mentioned in
    a mail's text and in its attachments. count(DISTINCT) sorts the mentions; the hashed
    DISTINCT of (entity_id, mail_id) it replaces spilled to disk over the 250,000 mentions of
    10,000 mails and then, now and then, ran for minutes instead of 0.4 s (PostgreSQL 16)."""
    return func.count(mention.c.mail_id.distinct()).label("mails")


def _by_kind(rows: Sequence[Any]) -> dict[EntityKind, list[EntityCount]]:
    """Rows of entities with their mails by kind, in EntityKind order, most mails first."""
    found: dict[EntityKind, list[EntityCount]] = {}
    for row in sorted(rows, key=lambda row: (_KIND_ORDER[row.kind], -row.mails, -row.id)):
        found.setdefault(row.kind, []).append(EntityCount(entity=_ref(row), mails=row.mails))
    return found


# One mail ------------------------------------------------------------------------------------


@router.get("/mails/{mail_id}/entities")
async def mail_entities(mail_id: MailId, session: Session) -> list[MailEntity]:
    """What was found in the mail's own text and in its attachments' documents (D89): one
    entry per entity and source, so an entity in the text and in an attachment comes twice."""
    if await session.scalar(select(Mail.id).where(Mail.id == mail_id)) is None:
        raise api_error(404, "not_found", f"no mail with id {mail_id}")
    mention = mentions()
    rows = await session.execute(
        select(
            *_REF_COLUMNS,
            mention.c.occurrences,
            mention.c.context,
            mention.c.document_id,
            Document.name.label("document_name"),
        )
        .distinct()  # a document attached twice
        .join_from(mention, Entity, Entity.id == mention.c.entity_id)
        .outerjoin(Document, Document.id == mention.c.document_id)
        .where(mention.c.mail_id == mail_id)
    )

    def order(row: Any) -> tuple[Any, ...]:
        source = (row.document_id is not None, row.document_id or 0)
        return (_KIND_ORDER[row.kind], -row.occurrences, row.label, *source, row.id)

    return [
        MailEntity(
            entity=_ref(row),
            occurrences=row.occurrences,
            context=[key for key, flag in _CONTEXTS.items() if row.context & flag],
            document_id=row.document_id,
            document_name=row.document_name,
        )
        for row in sorted(rows, key=order)
    ]

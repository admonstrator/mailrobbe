"""The research file (milestone 8, D53 to D61): overview, themes and starter set, tags, Akten,
saved searches and permalinks. The routes are listed in schemas.py; marks, links and bulk
changes are in marks.py, notes in notes.py, and detail.py reads the research data of one mail.

Research rows name a mail's content by its raw SHA-256 (D53). Figures count mail rows, as the
list's filters do: a content in two byte-identical mails counts twice, one that is not in the
archive (any more) not at all. Writes record the editor (D54). Names of tags, Akten and saved
searches are trimmed and unique ignoring case (SQL lower, as the unique indexes of tag and
collection); the check runs under NAME_LOCK, so two requests cannot both find a name free.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, Concatenate, get_args

import fastapi
from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Row,
    Text,
    any_,
    column,
    delete,
    distinct,
    exists,
    func,
    literal,
    select,
    update,
    values,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute

from mailrobbe import aggregates
from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.schemas import (
    COLLECTION_PERSONS,
    PERMALINK_MIN_DIGITS,
    CollectionCreate,
    CollectionDetail,
    CollectionInfo,
    CollectionPerson,
    CollectionUpdate,
    PermalinkTarget,
    PersonRef,
    ResearchOverview,
    ReviewKey,
    SavedSearch,
    SavedSearchCreate,
    SavedSearchUpdate,
    TagCreate,
    TagInfo,
    TagUpdate,
    ThemeInfo,
    ThemeSearchInfo,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import (
    Collection,
    CollectionMail,
    Mail,
    MailMark,
    MailTag,
    Note,
    Participation,
    Person,
    Tag,
)
from mailrobbe.db.models import SavedSearch as SearchRow
from mailrobbe.persons.roots import ROOT
from mailrobbe.themes import load_themes

router = APIRouter(prefix="/api", tags=["research"])

REVIEW_KEYS: tuple[ReviewKey, ...] = get_args(ReviewKey)

# Ids of tags, Akten, saved searches and notes are bigints: a larger number is a validation
# error, not a database error.
RowId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]

NAME_LOCK = int.from_bytes(b"mrnames", "big")  # transaction-level advisory lock, name checks
_PERMALINK = re.compile(rf"[0-9a-f]{{{PERMALINK_MIN_DIGITS},64}}")

_TAG_COLUMNS = (Tag.id, Tag.name, Tag.color, Tag.description, Tag.created_by, Tag.created_at)
_COLLECTION_COLUMNS = (
    Collection.id,
    Collection.name,
    Collection.description,
    Collection.created_by,
    Collection.created_at,
    Collection.updated_at,
)
_SEARCH_COLUMNS = (
    SearchRow.id,
    SearchRow.name,
    SearchRow.query,
    SearchRow.collection_id,
    SearchRow.created_by,
    SearchRow.created_at,
    SearchRow.updated_at,
)
Named = type[Tag] | type[Collection] | type[SearchRow]
Link = type[MailTag] | type[CollectionMail]
_KIND: dict[Named, str] = {Tag: "tag", Collection: "Akte", SearchRow: "saved search"}
_Row = Row[*tuple[Any, ...]]


def _shas(shas: Sequence[str]) -> ColumnElement[list[str]]:
    return literal(list(shas), ARRAY(Text))


def _ids(ids: Sequence[int]) -> ColumnElement[list[int]]:
    return literal(list(ids), ARRAY(BigInteger))


def trimmed(value: str, field: str) -> str:
    """value without surrounding whitespace; nothing left is a 422 like FastAPI's own."""
    stripped = value.strip()
    if not stripped:
        error = {
            "type": "string_too_short",
            "loc": ("body", field),
            "msg": "String should have at least 1 character besides whitespace",
            "input": value,
        }
        raise RequestValidationError([error])
    return stripped


async def mail_sha256(session: AsyncSession, mail_id: int) -> str:
    """The content a mail's research data belongs to; 404 not_found for an unknown mail."""
    sha = await session.scalar(select(Mail.raw_sha256).where(Mail.id == mail_id))
    if sha is None:
        raise api_error(404, "not_found", f"no mail with id {mail_id}")
    return sha


def _not_found(model: Named, row_id: int) -> HTTPException:
    return api_error(404, "not_found", f"no {_KIND[model]} with id {row_id}")


async def _known(session: AsyncSession, model: Named, ids: Sequence[int]) -> None:
    """404 not_found unless every id names a row of model."""
    wanted = sorted(set(ids))
    found = set(await session.scalars(select(model.id).where(model.id == any_(_ids(wanted)))))
    missing = [row_id for row_id in wanted if row_id not in found]
    if missing:
        raise _not_found(model, missing[0])


async def _free_name(
    session: AsyncSession, model: Named, name: str, own: int | None = None
) -> None:
    """409 duplicate_name when another row of model has this name ignoring case. Holds
    NAME_LOCK until the transaction ends, so the name stays free until it is written."""
    await session.execute(select(func.pg_advisory_xact_lock(NAME_LOCK)))
    taken = select(model.id).where(func.lower(model.name) == func.lower(name))
    if own is not None:
        taken = taken.where(model.id != own)
    if await session.scalar(taken.limit(1)) is not None:
        raise api_error(409, "duplicate_name", f"a {_KIND[model]} named {name!r} exists already")


async def _current(
    session: AsyncSession, model: Named, columns: Sequence[Any], row_id: int
) -> _Row:
    row = (await session.execute(select(*columns).where(model.id == row_id))).one_or_none()
    if row is None:
        raise _not_found(model, row_id)
    return row


async def _change(
    session: AsyncSession,
    model: Named,
    columns: Sequence[Any],
    current: _Row,
    wanted: dict[str, Any],
) -> _Row:
    """The row after writing the wanted values that differ from current; a new name must be
    free, and updated_at moves when the model has one and something changed."""
    changes = {key: value for key, value in wanted.items() if getattr(current, key) != value}
    if not changes:
        return current
    if "name" in changes:
        await _free_name(session, model, changes["name"], current.id)
    if model is not Tag:
        changes["updated_at"] = func.now()
    statement = update(model).where(model.id == current.id).values(changes).returning(*columns)
    return (await session.execute(statement)).one()


async def _delete(session: AsyncSession, model: Named, row_id: int) -> Response:
    if await session.scalar(delete(model).where(model.id == row_id).returning(model.id)) is None:
        raise _not_found(model, row_id)
    await session.commit()
    return Response(status_code=204)


# Overview --------------------------------------------------------------------------------------


async def _mail_counts(
    session: AsyncSession, link: Link, key: InstrumentedAttribute[int], ids: Sequence[int] = ()
) -> dict[int, int]:
    """Mail rows per tag or Akte (key: its column in link), of the given ones or of all."""
    counts = select(key, func.count()).join(Mail, Mail.raw_sha256 == link.mail_sha256)
    if ids:
        counts = counts.where(key == any_(_ids(ids)))
    rows = await session.execute(counts.group_by(key))
    return {row_id: mails for row_id, mails in rows}


async def _mark_counts(session: AsyncSession) -> tuple[dict[str, int], int]:
    """Mail rows per review status, and bookmarked mail rows."""
    rows = await session.execute(
        select(MailMark.review, func.count(), func.count().filter(MailMark.flagged))
        .join(Mail, Mail.raw_sha256 == MailMark.mail_sha256)
        .group_by(MailMark.review)
    )
    reviewed: dict[str, int] = {}
    flagged = 0
    for status, mails, bookmarked in rows:
        if status is not None:
            reviewed[status.value] = mails
        flagged += bookmarked
    return reviewed, flagged


async def _apart[**P, T](
    sessionmaker: async_sessionmaker[AsyncSession],
    query: Callable[Concatenate[AsyncSession, P], Awaitable[T]],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """query on a session (a connection) of its own, so that several run at once. Without
    parallel workers: starting them takes longer than the lookups they would share."""
    async with sessionmaker() as session:
        workers = func.set_config("max_parallel_workers_per_gather", "0", True)
        await session.execute(select(workers))
        return await query(session, *args, **kwargs)


def _missing_names(model: Named, names: Sequence[str]) -> ColumnElement[int]:
    """How many of names no row of model has, ignoring case."""
    wanted = func.unnest(literal(list(names), ARRAY(Text))).table_valued("name").render_derived()
    lacking = ~exists().where(func.lower(model.name) == func.lower(wanted.c.name))
    return select(func.count()).select_from(wanted).where(lacking).scalar_subquery()


async def _listing(session: AsyncSession) -> tuple[list[_Row], list[_Row], list[_Row], int, int]:
    """Tags, Akten and saved searches in the overview's order; notes and starter_missing."""
    tags = await session.execute(select(*_TAG_COLUMNS).order_by(func.lower(Tag.name), Tag.id))
    collections = await session.execute(
        select(*_COLLECTION_COLUMNS).order_by(Collection.updated_at.desc(), Collection.id.desc())
    )
    searches = await session.execute(
        select(*_SEARCH_COLUMNS).order_by(func.lower(SearchRow.name), SearchRow.id)
    )
    themes = load_themes()
    starter = [search.name for theme in themes for search in theme.searches]
    notes, starter_missing = (
        await session.execute(
            select(
                select(func.count()).select_from(Note).scalar_subquery(),
                _missing_names(Tag, [theme.name for theme in themes])
                + _missing_names(SearchRow, starter),
            )
        )
    ).one()
    return list(tags), list(collections), list(searches), notes, starter_missing


async def _overview(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> ResearchOverview:
    """The figures count mail rows, so each content of a tag, an Akte or a mark is looked up in
    ix_mail_raw_sha256: about 30,000 lookups for 10,000 reviewed and 15,000 tagged mails, too
    many for one connection within 100 ms. The three counts run at once, each on a connection
    of its own. The archive's total, from which unreviewed follows, is that of global_stats,
    like every counter next to the filters (D19)."""
    archive = await aggregates.current_global_stats(session, settings.stats_max_age)
    tag_mails, collection_mails, (reviewed, flagged), listing = await asyncio.gather(
        _apart(sessionmaker, _mail_counts, MailTag, MailTag.tag_id),
        _apart(sessionmaker, _mail_counts, CollectionMail, CollectionMail.collection_id),
        _apart(sessionmaker, _mark_counts),
        _listing(session),
    )
    tags, collections, searches, notes, starter_missing = listing
    reviewed["unreviewed"] = archive.mails - sum(reviewed.values())
    return ResearchOverview(
        tags=[TagInfo(mails=tag_mails.get(row.id, 0), **row._mapping) for row in tags],
        collections=[
            CollectionInfo(mails=collection_mails.get(row.id, 0), **row._mapping)
            for row in collections
        ],
        searches=[SavedSearch(**row._mapping) for row in searches],
        review={key: reviewed.get(key, 0) for key in REVIEW_KEYS},
        flagged=flagged,
        notes=notes,
        starter_missing=starter_missing,
    )


@router.get("/research")
async def research_overview(
    request: Request, session: Session, settings: AppSettings
) -> ResearchOverview:
    return await _overview(session, request.app.state.sessionmaker, settings)


@router.get("/research/themes")
async def research_themes() -> list[ThemeInfo]:
    return [
        ThemeInfo(
            key=theme.key,
            name=theme.name,
            color=theme.color,
            description=theme.description,
            terms=list(theme.terms),
            searches=[ThemeSearchInfo(name=s.name, query=s.query) for s in theme.searches],
        )
        for theme in load_themes()
    ]


@router.post("/research/starter")
async def create_starter(
    request: Request, session: Session, settings: AppSettings, editor: Editor
) -> ResearchOverview:
    """The themes' tags and saved searches whose names are not taken yet (D64); nothing is
    tagged, and a second call creates nothing."""
    themes = load_themes()
    await session.execute(select(func.pg_advisory_xact_lock(NAME_LOCK)))
    tags = postgresql.insert(Tag).values(
        [
            {
                "name": theme.name,
                "color": theme.color,
                "description": theme.description,
                "created_by": editor,
            }
            for theme in themes
        ]
    )
    await session.execute(tags.on_conflict_do_nothing(index_elements=[func.lower(Tag.name)]))
    wanted = values(column("name", Text), column("query", Text), name="wanted").data(
        [(search.name, search.query) for theme in themes for search in theme.searches]
    )
    new = select(wanted.c.name, wanted.c.query, literal(editor, Text)).where(
        ~exists().where(func.lower(SearchRow.name) == func.lower(wanted.c.name))
    )
    await session.execute(
        postgresql.insert(SearchRow).from_select(["name", "query", "created_by"], new)
    )
    await session.commit()
    return await _overview(session, request.app.state.sessionmaker, settings)


# Tags ------------------------------------------------------------------------------------------


@router.post("/tags", status_code=201)
async def create_tag(tag: TagCreate, session: Session, editor: Editor) -> TagInfo:
    name = trimmed(tag.name, "name")
    await _free_name(session, Tag, name)
    created = postgresql.insert(Tag).values(
        name=name, color=tag.color, description=tag.description, created_by=editor
    )
    row = (await session.execute(created.returning(*_TAG_COLUMNS))).one()
    await session.commit()
    return TagInfo(mails=0, **row._mapping)


@router.patch("/tags/{tag_id}")
async def update_tag(tag_id: RowId, change: TagUpdate, session: Session) -> TagInfo:
    current = await _current(session, Tag, _TAG_COLUMNS, tag_id)
    wanted: dict[str, Any] = {}
    if change.name is not None:
        wanted["name"] = trimmed(change.name, "name")
    if change.color is not None:
        wanted["color"] = change.color
    if change.description is not None:
        wanted["description"] = change.description
    row = await _change(session, Tag, _TAG_COLUMNS, current, wanted)
    await session.commit()
    mails = await _mail_counts(session, MailTag, MailTag.tag_id, [tag_id])
    return TagInfo(mails=mails.get(tag_id, 0), **row._mapping)


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(tag_id: RowId, session: Session) -> Response:
    """The tag and, through the foreign key, its links to every mail (D57)."""
    return await _delete(session, Tag, tag_id)


# Akten -----------------------------------------------------------------------------------------


@router.post("/collections", status_code=201)
async def create_collection(
    collection: CollectionCreate, session: Session, editor: Editor
) -> CollectionInfo:
    name = trimmed(collection.name, "name")
    await _free_name(session, Collection, name)
    created = postgresql.insert(Collection).values(
        name=name, description=collection.description, created_by=editor
    )
    row = (await session.execute(created.returning(*_COLLECTION_COLUMNS))).one()
    await session.commit()
    return CollectionInfo(mails=0, **row._mapping)


@router.get("/collections/{collection_id}")
async def collection_detail(collection_id: RowId, session: Session) -> CollectionDetail:
    """The Akte with the figures of its mails in the archive (D58)."""
    row = await _current(session, Collection, _COLLECTION_COLUMNS, collection_id)
    member = CollectionMail.collection_id == collection_id
    # One pass over the members' mails; a member without one is missing (D58).
    figures = (
        select(
            func.count(Mail.id),
            func.min(Mail.date_utc),
            func.max(Mail.date_utc),
            select(func.count()).where(member).scalar_subquery()
            - func.count(distinct(Mail.raw_sha256)),
            func.array_agg(Mail.id),
        )
        .join_from(CollectionMail, Mail, Mail.raw_sha256 == CollectionMail.mail_sha256)
        .where(member)
    )
    total, date_min, date_max, missing, ids = (await session.execute(figures)).one()
    involved = func.count(distinct(Participation.mail_id)).label("mails")
    top = (
        select(ROOT.label("root"), involved)
        .join(Person, Person.id == Participation.person_id)
        .where(Participation.mail_id == any_(_ids(ids or ())))
        .group_by(ROOT)
        .order_by(involved.desc(), ROOT)
        .limit(COLLECTION_PERSONS)
        .subquery("top")
    )
    persons = await session.execute(
        select(top.c.root, top.c.mails, Person.canonical_email, Person.display_name)
        .join(Person, Person.id == top.c.root)
        .order_by(top.c.mails.desc(), top.c.root)
    )
    searches = await session.execute(
        select(*_SEARCH_COLUMNS)
        .where(SearchRow.collection_id == collection_id)
        .order_by(func.lower(SearchRow.name), SearchRow.id)
    )
    return CollectionDetail(
        mails=total,
        date_min=date_min,
        date_max=date_max,
        missing=missing,
        persons=[
            CollectionPerson(
                person=PersonRef(person_id=root, email=email, name=name), mails=involved
            )
            for root, involved, email, name in persons
        ],
        searches=[SavedSearch(**search._mapping) for search in searches],
        **row._mapping,
    )


@router.patch("/collections/{collection_id}")
async def update_collection(
    collection_id: RowId, change: CollectionUpdate, session: Session
) -> CollectionInfo:
    current = await _current(session, Collection, _COLLECTION_COLUMNS, collection_id)
    wanted: dict[str, Any] = {}
    if change.name is not None:
        wanted["name"] = trimmed(change.name, "name")
    if change.description is not None:
        wanted["description"] = change.description
    row = await _change(session, Collection, _COLLECTION_COLUMNS, current, wanted)
    await session.commit()
    mails = await _mail_counts(
        session, CollectionMail, CollectionMail.collection_id, [collection_id]
    )
    return CollectionInfo(mails=mails.get(collection_id, 0), **row._mapping)


@router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(collection_id: RowId, session: Session) -> Response:
    """The Akte and its memberships; its mails, notes and tags stay, its saved searches lose
    it (both through the foreign keys, D58)."""
    return await _delete(session, Collection, collection_id)


# Saved searches --------------------------------------------------------------------------------


@router.post("/searches", status_code=201)
async def create_search(search: SavedSearchCreate, session: Session, editor: Editor) -> SavedSearch:
    name = trimmed(search.name, "name")
    if search.collection_id is not None:
        await _known(session, Collection, [search.collection_id])
    await _free_name(session, SearchRow, name)
    created = postgresql.insert(SearchRow).values(
        name=name, query=search.query, collection_id=search.collection_id, created_by=editor
    )
    row = (await session.execute(created.returning(*_SEARCH_COLUMNS))).one()
    await session.commit()
    return SavedSearch(**row._mapping)


@router.patch("/searches/{search_id}")
async def update_search(
    search_id: RowId, change: SavedSearchUpdate, session: Session
) -> SavedSearch:
    current = await _current(session, SearchRow, _SEARCH_COLUMNS, search_id)
    wanted: dict[str, Any] = {}
    if change.name is not None:
        wanted["name"] = trimmed(change.name, "name")
    if change.query is not None:
        wanted["query"] = change.query
    if "collection_id" in change.model_fields_set:  # null detaches it from its Akte
        if change.collection_id is not None:
            await _known(session, Collection, [change.collection_id])
        wanted["collection_id"] = change.collection_id
    row = await _change(session, SearchRow, _SEARCH_COLUMNS, current, wanted)
    await session.commit()
    return SavedSearch(**row._mapping)


@router.delete("/searches/{search_id}", status_code=204)
async def delete_search(search_id: RowId, session: Session) -> Response:
    return await _delete(session, SearchRow, search_id)


# Permalinks ------------------------------------------------------------------------------------


def _starting_with(digits: str) -> list[ColumnElement[bool]]:
    """SHA-256 values starting with these hex digits, as a range of ix_mail_raw_sha256.

    LIKE 'digits%' would use the index only under the C collation; a range works under any,
    and hex strings sort the same in all of them. Its upper end is the prefix plus one (none
    after ffff...); left() checks the rows the range yields.
    """
    where = [Mail.raw_sha256 >= digits, func.left(Mail.raw_sha256, len(digits)) == digits]
    following = int(digits, 16) + 1
    if following < 16 ** len(digits):
        where.append(Mail.raw_sha256 < f"{following:0{len(digits)}x}")
    return where


@router.get("/permalink/{prefix}")
async def permalink(prefix: str, session: Session) -> PermalinkTarget:
    """The mail whose content's SHA-256 starts with prefix (D61): its original, the mail that
    is no duplicate with the lowest id."""
    digits = prefix.lower()
    if not _PERMALINK.fullmatch(digits):
        raise api_error(
            404,
            "not_found",
            f"{prefix!r} is no permalink: it takes {PERMALINK_MIN_DIGITS} to 64 hex digits",
        )
    rows = (
        await session.execute(
            select(Mail.id, Mail.raw_sha256)
            .where(*_starting_with(digits))
            .order_by(Mail.is_duplicate_of.is_not(None), Mail.id)
        )
    ).all()
    if not rows:
        raise api_error(404, "not_found", f"no mail whose SHA-256 starts with {digits}")
    if len({sha for _, sha in rows}) > 1:
        raise api_error(
            409, "ambiguous_permalink", f"mails with different contents start with {digits}"
        )
    return PermalinkTarget(mail_id=rows[0].id, raw_sha256=rows[0].raw_sha256)

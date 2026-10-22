"""AI tags and theme hints in the lists (milestone 17, D309, D310): GET /api/ai/facets, GET
/api/ai/tags and POST /api/ai/tags/{id}/adopt. Models are in schemas.py (AiFacets, AiTagCount,
AiTagAdopt, AiTagAdopted); the filters ai_tag and ai_theme are in filters.py.

An AI tag or a theme describes a mail when it hangs on a valid summary of the mail's content
(duplicates included) or of one of its attachments' documents (filters.described_mails, the one
definition the filters read too). Every count of an AI tag's mails is read the same way: the
tag lookup and the summary card through tag_counts, the facets over some mails.

Facets are counted as the entity facets are (D87). With filters over at most FACET_MAILS of the
matching mails under the count budget of the list's summary (D19), then over FACET_FALLBACK.
Without filters over every described mail, straight from the summaries: their size, not the
archive's, and hidden mails included as in the other unfiltered facets (D202); should that run
out of time (an archive summarised in large parts), as with a filter.

Adopting an AI tag (D310) adds the team tag of the same name, found in any case or made, to the
mails as a bulk tag change does (marks._add_links, at most BULK_LIMIT, the editor recorded).
"""

from collections.abc import Sequence
from typing import Annotated, Any

import fastapi
from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, Select, Subquery, UnaryExpression, any_, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.documents import _all_unless_canceled
from mailrobbe.api.entities import FACET_FALLBACK, _ids
from mailrobbe.api.filters import _contains, described_mails, resolve_contents, unfiltered
from mailrobbe.api.imports import JSON_BODY
from mailrobbe.api.mails import _count_budget, _terms, _where
from mailrobbe.api.marks import _add_links
from mailrobbe.api.research import NAME_LOCK, _shas
from mailrobbe.api.schemas import (
    AI_FACET_TAGS,
    BULK_LIMIT,
    FACET_MAILS,
    AiFacets,
    AiFacetTheme,
    AiTagAdopt,
    AiTagAdopted,
    AiTagCount,
    AiTagParams,
    MailFilters,
    MailSelection,
    TagCreate,
)
from mailrobbe.api.selection import resolve_selection
from mailrobbe.db.models import AiTag, AiTagLink, AiThemeHint, Mail, MailTag, Tag
from mailrobbe.themes import load_themes

router = APIRouter(prefix="/api/ai", tags=["ai"])

# ai_tag.id is a bigint: a larger number is a validation error in the path and names no tag in
# a list.
TagId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]
_BIGINT = range(-(2**63), 2**63)
TEAM_TAG_COLOR = TagCreate.model_fields["color"].default  # as POST /api/tags makes a tag


def _counted(
    mark: type[AiTagLink] | type[AiThemeHint],
    *,
    mail_ids: Sequence[int] | None = None,
    tag_ids: Sequence[int] | None = None,
) -> Subquery:
    """Per AI tag or theme (key) the distinct mails it describes (mails): among mail_ids, of the
    tags tag_ids, each when given. Both reach the two branches of described_mails, so that
    PostgreSQL reads the summaries of those mails or the links of those tags only."""
    marked = described_mails(mark)
    statement = select(marked.c.key, func.count(marked.c.mail_id.distinct()).label("mails"))
    if mail_ids is not None:
        statement = statement.where(marked.c.mail_id == any_(_ids(mail_ids)))
    if tag_ids is not None:
        statement = statement.where(marked.c.key == any_(_ids(tag_ids)))
    return statement.group_by(marked.c.key).subquery("counted")


def _most_mails(mails: ColumnElement[int]) -> tuple[UnaryExpression[Any], ...]:
    """Most mails first, ties by label in code point order, then by id."""
    return mails.desc(), AiTag.label.collate("C").asc(), AiTag.id.asc()


def _top_tags(counted: Subquery, limit: int) -> Select[Any]:
    """The AI tags of counted with most mails."""
    return (
        select(AiTag.id, AiTag.label, counted.c.mails)
        .join_from(counted, AiTag, AiTag.id == counted.c.key)
        .order_by(*_most_mails(counted.c.mails))
        .limit(limit)
    )


def _tag_count(row: Any) -> AiTagCount:
    return AiTagCount(id=row.id, label=row.label, mails=row.mails)


async def tag_counts(session: AsyncSession, tag_ids: Sequence[int]) -> list[AiTagCount]:
    """These AI tags with the mails each describes (AiTagCount.mails: by the mail's own summary
    or an attachment's document's, duplicates included, D309), most mails first; a tag that no
    valid summary has any more with 0, an unknown id left out. The count the tag lookup and the
    summary card share, and that the facets count over some mails."""
    wanted = sorted({tag_id for tag_id in tag_ids if tag_id in _BIGINT})
    if not wanted:
        return []
    counted = _counted(AiTagLink, tag_ids=wanted)
    mails = func.coalesce(counted.c.mails, 0)
    statement = (
        select(AiTag.id, AiTag.label, mails.label("mails"))
        .outerjoin(counted, counted.c.key == AiTag.id)
        .where(AiTag.id == any_(_ids(wanted)))
        .order_by(*_most_mails(mails))
    )
    return [_tag_count(row) for row in await session.execute(statement)]


# Tag lookup ----------------------------------------------------------------------------------


@router.get("/tags")
async def ai_tags(params: Annotated[AiTagParams, Query()], session: Session) -> list[AiTagCount]:
    """By id in the order given (the chips of a filter), or the tags whose label holds q in any
    case (every tag for an empty q) with most mails first (D309); at most limit."""
    if params.id:
        counts = {tag.id: tag for tag in await tag_counts(session, params.id)}
        given = [tag_id for tag_id in dict.fromkeys(params.id) if tag_id in counts]
        return [counts[tag_id] for tag_id in given[: params.limit]]
    q = params.q.strip()
    named = None
    if q:
        named = list(await session.scalars(select(AiTag.id).where(AiTag.label.ilike(_contains(q)))))
        if not named:
            return []
    rows = await session.execute(_top_tags(_counted(AiTagLink, tag_ids=named), params.limit))
    return [_tag_count(row) for row in rows]


# Facets --------------------------------------------------------------------------------------


@router.get("/facets")
async def ai_facets(
    filters: Annotated[MailFilters, Query()], session: Session, settings: AppSettings
) -> AiFacets:
    where = _where(filters, _terms(filters.q), settings)
    await _count_budget(session, settings)
    if unfiltered(where):
        counted = await _facet_counts(session, None)
        if counted is not None:
            return AiFacets(tags=counted[0], themes=counted[1], mails=None, sampled=False)
    where = await resolve_contents(session, where)
    ids: list[int] | None = None
    for size in (FACET_MAILS, FACET_FALLBACK):
        if ids is None:
            matched = select(Mail.id).where(*where).limit(size + 1)
            found = await _all_unless_canceled(session, matched)
            ids = None if found is None else [row.id for row in found]
        if ids is None:
            continue
        sample = ids[:size]
        counted = await _facet_counts(session, sample)
        if counted is not None:
            tags, themes = counted
            return AiFacets(tags=tags, themes=themes, mails=len(sample), sampled=len(ids) > size)
    return AiFacets(tags=[], themes=[], mails=None, sampled=False)


async def _facet_counts(
    session: AsyncSession, mail_ids: Sequence[int] | None
) -> tuple[list[AiTagCount], list[AiFacetTheme]] | None:
    """The AI tags with most mails (AI_FACET_TAGS) and the themes with mails in the order of
    themes.toml, among mail_ids (None: every described mail); None when the count budget ran
    out."""
    top = _top_tags(_counted(AiTagLink, mail_ids=mail_ids), AI_FACET_TAGS)
    tags = await _all_unless_canceled(session, top)
    if tags is None:
        return None
    counted = _counted(AiThemeHint, mail_ids=mail_ids)
    themes = await _all_unless_canceled(session, select(counted))
    if themes is None:
        return None
    mails = {row.key: row.mails for row in themes}
    found = [theme for theme in load_themes() if mails.get(theme.key, 0) > 0]
    return [_tag_count(row) for row in tags], [
        AiFacetTheme(key=theme.key, label=theme.name, mails=mails[theme.key]) for theme in found
    ]


# Adopting an AI tag (D310) ---------------------------------------------------------------------


@router.post("/tags/{tag_id}/adopt", dependencies=JSON_BODY)
async def adopt_tag(
    tag_id: TagId, request: AiTagAdopt, session: Session, settings: AppSettings, editor: Editor
) -> AiTagAdopted:
    """The team tag of the AI tag's name on one mail, on the mails of a filter that carry the AI
    tag, or on every mail carrying it, hidden ones too, as its unfiltered facet counts them."""
    label = await session.scalar(select(AiTag.label).where(AiTag.id == tag_id))
    if label is None:
        raise api_error(404, "not_found", f"no AI tag with id {tag_id}")
    if request.mail_id is not None and request.filters is not None:
        raise api_error(400, "invalid_selection", "give at most one of mail_id and filters")
    if request.mail_id is not None:
        selection = MailSelection(ids=[request.mail_id])
    else:
        filters = request.filters or MailFilters(include_hidden=True)
        carrying = filters.model_copy(update={"ai_tag": [*filters.ai_tag, tag_id]})
        selection = MailSelection(filters=carrying)
    mails = await resolve_selection(session, settings, selection, BULK_LIMIT)
    team, created = await _team_tag(session, label, editor)
    shas = sorted({mail.raw_sha256 for mail in mails})
    tagged = select(MailTag.mail_sha256).where(
        MailTag.tag_id == team, MailTag.mail_sha256 == any_(_shas(shas))
    )
    had = set(await session.scalars(tagged))
    if await _add_links(session, MailTag, Tag, [team], shas, editor):
        # as after a bulk change: the next filter by the tag is planned on the new numbers
        await session.execute(text("ANALYZE mail_tag"))
    await session.commit()
    added = sum(1 for mail in mails if mail.raw_sha256 not in had)
    return AiTagAdopted(tag_id=team, created=created, mails=added)


async def _team_tag(session: AsyncSession, name: str, editor: str | None) -> tuple[int, bool]:
    """The team tag of this name in any case, or a new one, and whether it was made now.
    NAME_LOCK keeps the name free until the transaction ends, as POST /api/tags does."""
    await session.execute(select(func.pg_advisory_xact_lock(NAME_LOCK)))
    found = await session.scalar(select(Tag.id).where(func.lower(Tag.name) == func.lower(name)))
    if found is not None:
        return found, False
    created = postgresql.insert(Tag).values(name=name, color=TEAM_TAG_COLOR, created_by=editor)
    return (await session.execute(created.returning(Tag.id))).scalar_one(), True

"""Standard blocks (milestone 18, D224 to D227): their list, figures, pages and the team's
choices. Routes: GET /api/blocks/summary, GET /api/blocks, GET /api/blocks/{hash},
PUT /api/blocks/{hash}/override.

paragraph_block holds what the last blocks step looked at (blocks.phase): every standard block,
detected or marked by hand, and every detected one the team took back, with its figures.
paragraph_override holds the team's choices, which the next run applies; a block is pending
while the choice, or detection where there is none, differs from what the step applied. Both
tables hold a few thousand rows at most, so the summary and the list read them whole. A block's
page counts its senders and domains on request through ix_mail_paragraph_hash, and so do the
figures of a paragraph the team chose before the blocks step counted it.

A choice equal to what detection says removes the team's choice instead of storing it, so
"Wieder als Standardblock" on a block taken back, or "Kein Standardblock" on one marked by hand,
leaves the paragraph to the rule of D225.
"""

from typing import Annotated, Any

import fastapi
from fastapi import APIRouter, Query
from sqlalchemy import (
    ColumnElement,
    and_,
    delete,
    distinct,
    false,
    func,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.filters import _contains
from mailrobbe.api.schemas import (
    BLOCK_HASH_PATTERN,
    BLOCK_SAMPLE_LIMIT,
    BLOCK_SENDERS,
    TEXT_LIMIT,
    BlockDetail,
    BlockInfo,
    BlockListParams,
    BlockOverrideUpdate,
    BlockPage,
    BlockSender,
    BlockSummary,
    DomainCount,
    PersonRef,
)
from mailrobbe.blocks import phase
from mailrobbe.blocks.model import hash_hex, paragraph_hash, parse_hash, read_figures
from mailrobbe.db.models import (
    Mail,
    MailParagraph,
    ParagraphBlock,
    ParagraphOverride,
    Participation,
    Person,
)
from mailrobbe.enums import ParticipationRole
from mailrobbe.persons.labels import attach_labels

router = APIRouter(prefix="/api", tags=["blocks"])

BlockHash = Annotated[str, fastapi.Path(pattern=BLOCK_HASH_PATTERN)]

# What the next run applies: the team's choice, else detection as the last step found it.
_EXPECTED = func.coalesce(ParagraphOverride.standard, ParagraphBlock.detected)
_PENDING = _EXPECTED.is_distinct_from(func.coalesce(ParagraphBlock.standard, false()))
_INFO = (
    ParagraphBlock.hash,
    ParagraphBlock.sample,
    ParagraphBlock.standard,
    ParagraphBlock.detected,
    ParagraphOverride.standard.label("override"),
    _PENDING.label("pending"),
    ParagraphBlock.mails,
    ParagraphBlock.senders,
    ParagraphBlock.first_date,
    ParagraphBlock.last_date,
)


_BLOCKS = select(*_INFO).outerjoin(ParagraphOverride, ParagraphOverride.hash == ParagraphBlock.hash)


def _info(row: Any) -> BlockInfo:
    return BlockInfo(
        hash=hash_hex(row.hash),
        sample=row.sample,
        standard=row.standard,
        detected=row.detected,
        override=row.override,
        pending=row.pending,
        mails=row.mails,
        senders=row.senders,
        first_date=row.first_date,
        last_date=row.last_date,
    )


@router.get("/blocks/summary")
async def block_summary(session: Session, settings: AppSettings) -> BlockSummary:
    figures = await read_figures(session)
    pending = await session.scalar(
        select(func.count())
        .select_from(ParagraphBlock)
        .join(ParagraphOverride, ParagraphOverride.hash == ParagraphBlock.hash, full=True)
        .where(_PENDING)
    )
    return BlockSummary(
        blocks=0 if figures is None else figures.blocks,
        detected=0 if figures is None else figures.detected,
        marked=0 if figures is None else figures.marked,
        dismissed=0 if figures is None else figures.dismissed,
        pending=pending or 0,
        mails=0 if figures is None else figures.mails,
        waiting=await phase.waiting(session),
        min_mails=settings.block_min_mails,
        computed_at=None if figures is None else figures.computed_at,
    )


@router.get("/blocks")
async def block_list(params: Annotated[BlockListParams, Query()], session: Session) -> BlockPage:
    where: list[ColumnElement[bool]] = (
        [ParagraphBlock.standard.is_(True)]
        if params.state == "standard"
        else [ParagraphBlock.detected.is_(True), ParagraphBlock.standard.is_(False)]
    )
    if params.q.strip():
        where.append(ParagraphBlock.sample.ilike(_contains(params.q.strip())))
    total = await session.scalar(select(func.count()).select_from(ParagraphBlock).where(*where))
    order = (
        [ParagraphBlock.mails.desc()]
        if params.sort == "mails"
        else [ParagraphBlock.last_date.desc().nulls_last()]
    )
    rows = await session.execute(
        _BLOCKS.where(*where)
        .order_by(*order, ParagraphBlock.hash)
        .offset(params.offset)
        .limit(params.limit)
    )
    return BlockPage(items=[_info(row) for row in rows], total=total or 0)


@router.get("/blocks/{block_hash}")
async def block_detail(block_hash: BlockHash, session: Session) -> BlockDetail:
    value = parse_hash(block_hash)
    block = await _block_info(session, value)
    if block is None:
        raise api_error(404, "not_found", f"no standard block or choice {block_hash}")
    held = _held(value)
    mails = func.count().label("mails")
    senders = await session.execute(
        select(Person.id, Person.canonical_email, Person.display_name, mails)
        .select_from(held)
        .join(Participation, _sent(held.c.mail_id))
        .join(Person, Person.id == Participation.person_id)
        .group_by(Person.id)
        .order_by(mails.desc(), Person.id)
        .limit(BLOCK_SENDERS)
    )
    domain_mails = func.count(distinct(held.c.mail_id)).label("mails")
    domains = await session.execute(
        select(Person.domain, domain_mails)
        .select_from(held)
        .join(Participation, _sent(held.c.mail_id))
        .join(Person, Person.id == Participation.person_id)
        .group_by(Person.domain)
        .order_by(domain_mails.desc(), Person.domain)
        .limit(BLOCK_SENDERS)
    )
    detail = BlockDetail(
        block=block,
        senders=[
            BlockSender(
                person=PersonRef(
                    person_id=row.id, email=row.canonical_email, name=row.display_name
                ),
                mails=row.mails,
            )
            for row in senders
        ],
        domains=[DomainCount(domain=row.domain, mails=row.mails) for row in domains],
    )
    await attach_labels(session, detail)
    return detail


@router.put("/blocks/{block_hash}/override")
async def save_override(
    block_hash: BlockHash, update: BlockOverrideUpdate, session: Session, editor: Editor
) -> BlockInfo:
    """The team's choice (module docstring); it takes effect at the next run."""
    value = parse_hash(block_hash)
    if update.sample is not None and (
        len(update.sample) > TEXT_LIMIT or paragraph_hash(update.sample) != value
    ):
        raise api_error(400, "invalid_block", f"the sample is no paragraph of {block_hash}")
    stored = (
        await session.execute(
            select(ParagraphBlock.detected, ParagraphBlock.sample).where(
                ParagraphBlock.hash == value
            )
        )
    ).one_or_none()
    chosen = await session.scalar(
        select(ParagraphOverride.sample).where(ParagraphOverride.hash == value)
    )
    detected = stored is not None and stored.detected
    if update.standard is None or update.standard == detected:
        await session.execute(delete(ParagraphOverride).where(ParagraphOverride.hash == value))
    else:
        sample = update.sample if update.sample is not None else stored and stored.sample
        if not sample:
            raise api_error(
                400, "invalid_block", f"{block_hash} is not counted yet: its sample is needed"
            )
        values = {"standard": update.standard, "sample": sample[:BLOCK_SAMPLE_LIMIT]}
        insert = postgresql.insert(ParagraphOverride).values(hash=value, editor=editor, **values)
        await session.execute(
            insert.on_conflict_do_update(
                index_elements=[ParagraphOverride.hash],
                set_={**values, "editor": editor, "updated_at": func.now()},
            )
        )
    await session.commit()
    block = await _block_info(session, value, update.sample or chosen)
    if block is None:
        raise api_error(404, "not_found", f"no standard block or choice {block_hash}")
    return block


async def _block_info(
    session: AsyncSession, value: int, sample: str | None = None
) -> BlockInfo | None:
    """The block as paragraph_block holds it; else a paragraph chosen by the team, or one whose
    sample the caller has, counted now in mail_paragraph; None when nothing knows the hash."""
    row = (await session.execute(_BLOCKS.where(ParagraphBlock.hash == value))).one_or_none()
    if row is not None:
        return _info(row)
    chosen = (
        await session.execute(
            select(ParagraphOverride.standard, ParagraphOverride.sample).where(
                ParagraphOverride.hash == value
            )
        )
    ).one_or_none()
    shown = chosen.sample if chosen is not None else sample
    if shown is None:
        return None
    held = _held(value)
    figures = (
        await session.execute(
            select(
                func.count(distinct(held.c.mail_id)).label("mails"),
                func.count(distinct(Participation.person_id)).label("senders"),
                func.min(Mail.date_utc).label("first_date"),
                func.max(Mail.date_utc).label("last_date"),
            )
            .select_from(held)
            .join(Mail, Mail.id == held.c.mail_id)
            .outerjoin(Participation, _sent(held.c.mail_id))
        )
    ).one()
    override = None if chosen is None else chosen.standard
    return BlockInfo(
        hash=hash_hex(value),
        sample=shown[:BLOCK_SAMPLE_LIMIT],
        standard=False,
        detected=False,
        override=override,
        pending=bool(override),
        mails=figures.mails,
        senders=figures.senders,
        first_date=figures.first_date,
        last_date=figures.last_date,
    )


def _held(value: int) -> Any:
    """The mails that are no duplicates holding the paragraph anywhere, each once."""
    return (
        select(MailParagraph.mail_id)
        .join(Mail, Mail.id == MailParagraph.mail_id)
        .where(MailParagraph.hash == value, Mail.is_duplicate_of.is_(None))
        .distinct()
        .subquery("held")
    )


def _sent(mail_id: Any) -> ColumnElement[bool]:
    return and_(Participation.mail_id == mail_id, Participation.role == ParticipationRole.FROM)

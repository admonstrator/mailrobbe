"""The figures of every entity (D85), at the end of an entities phase that was not stopped.

    mails        distinct mentioning mails that are no duplicates, over mentions(): a mention in
                 a document counts for every mail carrying it, a mail mentioning an entity in its
                 text and in two attachments counts once
    documents    documents whose text mentions it
    first, last  the earliest and latest date of those mails
    orphans      entities no longer mentioned (their mails deleted, their texts scanned again
                 without them) are deleted

Set-based over all entities, writing only rows whose figures change, in the caller's
transaction; the phase gives it one of its own.
"""

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import (
    CursorResult,
    Delete,
    Executable,
    Update,
    delete,
    exists,
    func,
    select,
    tuple_,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.db.models import Attachment, DocumentEntity, Entity, Mail, MailEntity
from mailrobbe.entities.mentions import mentions


@dataclass(frozen=True, slots=True)
class FiguresRefresh:
    """Rows changed by one refresh_entity_figures."""

    updated: int  # entities whose figures changed
    deleted: int  # entities no longer mentioned, removed


async def refresh_entity_figures(session: AsyncSession) -> FiguresRefresh:
    """Recompute the figures of every entity and delete the ones no longer mentioned."""
    deleted = await _changed(session, _orphans())
    updated = await _changed(session, _figures())
    return FiguresRefresh(updated, deleted)


def _figures() -> Update:
    mention = mentions()
    # A mail once per entity, whether it mentions it in its text or in several attachments.
    pairs = select(mention.c.entity_id, mention.c.mail_id).distinct().subquery("pairs")
    original = Mail.is_duplicate_of.is_(None)
    per_mail = (
        select(
            pairs.c.entity_id,
            func.count().filter(original).label("mails"),
            func.min(Mail.date_utc).filter(original).label("first_date"),
            func.max(Mail.date_utc).filter(original).label("last_date"),
        )
        .join(Mail, Mail.id == pairs.c.mail_id)
        .group_by(pairs.c.entity_id)
        .subquery("per_mail")
    )
    per_document = (
        select(DocumentEntity.entity_id, func.count().label("documents"))
        .group_by(DocumentEntity.entity_id)
        .subquery("per_document")
    )
    figures = (
        select(
            Entity.id,
            func.coalesce(per_mail.c.mails, 0).label("mails"),
            func.coalesce(per_document.c.documents, 0).label("documents"),
            per_mail.c.first_date,
            per_mail.c.last_date,
        )
        .outerjoin(per_mail, per_mail.c.entity_id == Entity.id)
        .outerjoin(per_document, per_document.c.entity_id == Entity.id)
        .subquery("figures")
    )
    stored = tuple_(Entity.mails, Entity.documents, Entity.first_date, Entity.last_date)
    computed = tuple_(
        figures.c.mails, figures.c.documents, figures.c.first_date, figures.c.last_date
    )
    return (
        update(Entity)
        .where(Entity.id == figures.c.id, stored.is_distinct_from(computed))
        .values(
            mails=figures.c.mails,
            documents=figures.c.documents,
            first_date=figures.c.first_date,
            last_date=figures.c.last_date,
        )
    )


def _orphans() -> Delete:
    """Entities without a row in mentions(): neither in a mail's text nor in a document that a
    mail carries. Written over the two tables of mentions() rather than the union, so that
    PostgreSQL answers both with an anti-join."""
    in_mail = exists().where(MailEntity.entity_id == Entity.id)
    in_attachment = (
        exists()
        .where(DocumentEntity.entity_id == Entity.id)
        .where(Attachment.document_id == DocumentEntity.document_id)
    )
    return delete(Entity).where(~in_mail, ~in_attachment)


async def _changed(session: AsyncSession, statement: Executable) -> int:
    result = cast(CursorResult[Any], await session.execute(statement))
    return result.rowcount

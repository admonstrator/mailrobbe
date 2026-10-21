"""Marks, links and bulk changes of the research file (D55, D57, D58, D60): the bookmark and
review status of a mail, its tags and Akten, and one change to many mails at once. Routes:
PUT /api/mails/{id}/mark, POST /api/mails/{id}/tags and /collections, POST /api/mails/bulk.

Registered before the detail router, so /api/mails/bulk is not taken for a mail id. Every write
names the mail's content (D53), so byte-identical copies share it, records the editor (D54) and
is one set-based statement whatever the number of mails.
"""

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter
from sqlalchemy import Text, any_, delete, func, literal, select, text, true, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.detail import MailId, collection_refs, tag_refs
from mailrobbe.api.research import Link, _ids, _known, _shas, mail_sha256
from mailrobbe.api.schemas import (
    BULK_LIMIT,
    BulkRequest,
    BulkResult,
    CollectionRef,
    LinkChange,
    Mark,
    MarkUpdate,
    TagRef,
)
from mailrobbe.api.selection import resolve_selection
from mailrobbe.db.models import Collection, CollectionMail, MailMark, MailTag, Tag
from mailrobbe.enums import ReviewStatus

router = APIRouter(prefix="/api", tags=["research"])


# Marks -----------------------------------------------------------------------------------------


async def _set_flag(
    session: AsyncSession, shas: Sequence[str], flagged: bool, editor: str | None
) -> int:
    """Bookmark these contents, or take the bookmark off; the number whose bookmark changed.
    flagged_by/at name who set it and when, and are cleared with it (D55)."""
    if flagged:
        insert = postgresql.insert(MailMark).from_select(
            ["mail_sha256", "flagged", "flagged_by", "flagged_at"],
            select(func.unnest(_shas(shas)), true(), literal(editor, Text), func.now()),
        )
        statement: Any = insert.on_conflict_do_update(
            index_elements=[MailMark.mail_sha256],
            set_={
                "flagged": True,
                "flagged_by": insert.excluded.flagged_by,
                "flagged_at": insert.excluded.flagged_at,
            },
            where=~MailMark.flagged,
        )
    else:
        statement = (
            update(MailMark)
            .where(MailMark.mail_sha256 == any_(_shas(shas)), MailMark.flagged)
            .values(flagged=False, flagged_by=None, flagged_at=None)
        )
    changed = len((await session.execute(statement.returning(MailMark.mail_sha256))).all())
    if not flagged:
        await _drop_empty_marks(session, shas)
    return changed


async def _set_review(
    session: AsyncSession, shas: Sequence[str], review: ReviewStatus | None, editor: str | None
) -> int:
    """Give these contents a review status, or none (unreviewed); the number whose status
    changed. review_by/at name who set it and when, and are cleared with it (D55)."""
    if review is not None:
        insert = postgresql.insert(MailMark).from_select(
            ["mail_sha256", "review", "review_by", "review_at"],
            select(
                func.unnest(_shas(shas)),
                literal(review, MailMark.review.type),
                literal(editor, Text),
                func.now(),
            ),
        )
        statement: Any = insert.on_conflict_do_update(
            index_elements=[MailMark.mail_sha256],
            set_={
                "review": insert.excluded.review,
                "review_by": insert.excluded.review_by,
                "review_at": insert.excluded.review_at,
            },
            where=MailMark.review.is_distinct_from(insert.excluded.review),
        )
    else:
        statement = (
            update(MailMark)
            .where(MailMark.mail_sha256 == any_(_shas(shas)), MailMark.review.is_not(None))
            .values(review=None, review_by=None, review_at=None)
        )
    changed = len((await session.execute(statement.returning(MailMark.mail_sha256))).all())
    if review is None:
        await _drop_empty_marks(session, shas)
    return changed


async def _drop_empty_marks(session: AsyncSession, shas: Sequence[str]) -> None:
    """mail_mark has a row only while it holds a bookmark or a status."""
    await session.execute(
        delete(MailMark)
        .where(
            MailMark.mail_sha256 == any_(_shas(shas)),
            ~MailMark.flagged,
            MailMark.review.is_(None),
        )
        .execution_options(synchronize_session=False)
    )


@router.put("/mails/{mail_id}/mark")
async def save_mark(mail_id: MailId, change: MarkUpdate, session: Session, editor: Editor) -> Mark:
    """Fields left out stay; "review": null makes the mail unreviewed again (D55)."""
    sha = await mail_sha256(session, mail_id)
    if change.flagged is not None:
        await _set_flag(session, [sha], change.flagged, editor)
    if "review" in change.model_fields_set:
        await _set_review(session, [sha], change.review, editor)
    row = (
        await session.execute(
            select(
                MailMark.flagged,
                MailMark.flagged_by,
                MailMark.flagged_at,
                MailMark.review,
                MailMark.review_by,
                MailMark.review_at,
            ).where(MailMark.mail_sha256 == sha)
        )
    ).one_or_none()
    await session.commit()
    if row is None:
        return Mark(
            flagged=False,
            flagged_by=None,
            flagged_at=None,
            review=None,
            review_by=None,
            review_at=None,
        )
    return Mark(**row._mapping)


# Links -----------------------------------------------------------------------------------------


def _key(link: Link) -> InstrumentedAttribute[int]:
    """The column of link naming the tag or Akte."""
    return MailTag.tag_id if link is MailTag else CollectionMail.collection_id


async def _add_links(
    session: AsyncSession,
    link: Link,
    owner: type[Tag] | type[Collection],
    ids: Sequence[int],
    shas: Sequence[str],
    editor: str | None,
) -> list[int]:
    """Put every content into each of these tags or Akten (ids of owner); for every new link
    the id of its tag or Akte."""
    key = _key(link)
    pairs = select(owner.id, func.unnest(_shas(shas)), literal(editor, Text)).where(
        owner.id == any_(_ids(ids))
    )
    insert = postgresql.insert(link).from_select([key.key, "mail_sha256", "added_by"], pairs)
    return list(await session.scalars(insert.on_conflict_do_nothing().returning(key)))


async def _remove_links(
    session: AsyncSession, link: Link, ids: Sequence[int], shas: Sequence[str]
) -> list[int]:
    """For every link removed, the id of its tag or Akte."""
    key = _key(link)
    removed = (
        delete(link)
        .where(key == any_(_ids(ids)), link.mail_sha256 == any_(_shas(shas)))
        .returning(key)
        .execution_options(synchronize_session=False)
    )
    return list(await session.scalars(removed))


async def _touch(session: AsyncSession, collection_ids: Sequence[int]) -> None:
    """A change of an Akte's mails is a change of the Akte (updated_at, D58)."""
    if collection_ids:
        await session.execute(
            update(Collection)
            .where(Collection.id == any_(_ids(sorted(set(collection_ids)))))
            .values(updated_at=func.now())
            .execution_options(synchronize_session=False)
        )


async def _change_links(
    session: AsyncSession,
    mail_id: int,
    change: LinkChange,
    link: Link,
    owner: type[Tag] | type[Collection],
    editor: str | None,
) -> tuple[str, list[int]]:
    """Add, then remove (so an id in both ends up removed); unknown ids change nothing. The
    mail's content and the ids whose links changed."""
    sha = await mail_sha256(session, mail_id)
    await _known(session, owner, [*change.add, *change.remove])
    changed = await _add_links(session, link, owner, change.add, [sha], editor)
    changed += await _remove_links(session, link, change.remove, [sha])
    return sha, changed


@router.post("/mails/{mail_id}/tags")
async def change_mail_tags(
    mail_id: MailId, change: LinkChange, session: Session, editor: Editor
) -> list[TagRef]:
    sha, _ = await _change_links(session, mail_id, change, MailTag, Tag, editor)
    await session.commit()
    return await tag_refs(session, sha)


@router.post("/mails/{mail_id}/collections")
async def change_mail_collections(
    mail_id: MailId, change: LinkChange, session: Session, editor: Editor
) -> list[CollectionRef]:
    sha, changed = await _change_links(session, mail_id, change, CollectionMail, Collection, editor)
    await _touch(session, changed)
    await session.commit()
    return await collection_refs(session, sha)


# Bulk changes ----------------------------------------------------------------------------------

# The field each action needs (BulkRequest); review may be null, the others not.
_BULK_VALUE = {
    "tag_add": "tag_id",
    "tag_remove": "tag_id",
    "collection_add": "collection_id",
    "collection_remove": "collection_id",
    "review": "review",
    "flag": "flagged",
}
_BULK_TABLE = {
    "tag_add": MailTag,
    "tag_remove": MailTag,
    "collection_add": CollectionMail,
    "collection_remove": CollectionMail,
    "review": MailMark,
    "flag": MailMark,
}


@router.post("/mails/bulk")
async def bulk_change(
    request: BulkRequest, session: Session, settings: AppSettings, editor: Editor
) -> BulkResult:
    """One change to every selected mail (D60), one statement for all of them."""
    field = _BULK_VALUE[request.action]
    given = field in request.model_fields_set
    if not given or (field != "review" and getattr(request, field) is None):
        raise api_error(400, "invalid_selection", f"{request.action} needs {field}")
    if request.tag_id is not None and request.action.startswith("tag_"):
        await _known(session, Tag, [request.tag_id])
    if request.collection_id is not None and request.action.startswith("collection_"):
        await _known(session, Collection, [request.collection_id])
    mails = await resolve_selection(session, settings, request, BULK_LIMIT)
    shas = sorted({mail.raw_sha256 for mail in mails})
    match request.action:
        case "tag_add":
            assert request.tag_id is not None
            changed = len(await _add_links(session, MailTag, Tag, [request.tag_id], shas, editor))
        case "tag_remove":
            assert request.tag_id is not None
            changed = len(await _remove_links(session, MailTag, [request.tag_id], shas))
        case "collection_add" | "collection_remove":
            assert request.collection_id is not None
            ids = [request.collection_id]
            if request.action == "collection_add":
                linked = await _add_links(session, CollectionMail, Collection, ids, shas, editor)
            else:
                linked = await _remove_links(session, CollectionMail, ids, shas)
            await _touch(session, linked)
            changed = len(linked)
        case "review":
            changed = await _set_review(session, shas, request.review, editor)
        case "flag":
            assert request.flagged is not None
            changed = await _set_flag(session, shas, request.flagged, editor)
    if changed:
        # The change may be most of its table. Until autovacuum gets to it, PostgreSQL would
        # plan the next filter by it for the rows the table had before: a tag it believes
        # empty is joined as a nested loop over all of its links per mail, 30 s for 50,000.
        await session.execute(text(f"ANALYZE {_BULK_TABLE[request.action].__tablename__}"))
    await session.commit()
    return BulkResult(mails=len(mails), changed=changed)

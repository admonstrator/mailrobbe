"""What an export says about a mail, from the database: metadata, DKIM, attachments and the
research data (D62), a batch of mails in a few queries.

An export names its mails by content (D53); of the mails with one raw SHA-256 the original (no
duplicate, then the lowest id) stands for all, as for permalinks (D61).
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from sqlalchemy import BigInteger, ColumnElement, Row, Text, any_, case, func, literal, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import (
    AttachmentInfo,
    CollectionRef,
    MailResearch,
    MailSource,
    Mark,
    NoteInfo,
    PersonRef,
    TagColor,
    TagRef,
)
from mailrobbe.db.models import (
    Attachment,
    Collection,
    CollectionMail,
    DkimResult,
    DnsCache,
    Mail,
    MailMark,
    MailTag,
    MboxFile,
    Note,
    Participation,
    Person,
    Tag,
)
from mailrobbe.dkim.override import key_name
from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus, ParticipationRole

_Row = Row[*tuple[Any, ...]]

# The PDF does not parse a larger message again but shows the text the importer indexed: MIME
# parsing takes up to eight times a message's size in memory, a few hundred MB for a mail with
# large attachments.
PARSE_LIMIT = 8 * 1024**2

NO_MARK = Mark(
    flagged=False, flagged_by=None, flagged_at=None, review=None, review_by=None, review_at=None
)


@dataclass(frozen=True, slots=True)
class Signature:
    """One dkim_result row with the answer for its key as dns_cache holds it now."""

    index: int
    status: DkimStatus
    reason: DkimReason | None
    domain: str | None
    selector: str | None
    algorithm: str | None
    key_bits: int | None
    aligned: bool | None
    signed_at: datetime | None
    checked_at: datetime
    key_status: DnsStatus | None  # None: no answer for the key's name is cached
    key_record: str | None
    key_fetched_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExportMail:
    id: int
    raw_sha256: str
    message_id: str | None
    in_reply_to: str | None
    subject: str | None
    date: datetime | None  # date_utc
    source: MailSource
    dkim_status: DkimStatus | None  # None: not checked yet
    # mail.body_text (the full text index's text) of a message above PARSE_LIMIT; else None.
    index_text: str | None = None
    # Participants by role, each by display name then address as in the detail view.
    participants: dict[ParticipationRole, list[PersonRef]] = field(default_factory=dict)
    signatures: list[Signature] = field(default_factory=list)
    attachments: list[AttachmentInfo] = field(default_factory=list)


_COLUMNS = (
    Mail.id,
    Mail.raw_sha256,
    Mail.message_id,
    Mail.in_reply_to,
    Mail.subject,
    Mail.date_utc,
    Mail.mbox_file_id,
    MboxFile.path,
    Mail.byte_offset,
    Mail.byte_length,
    Mail.dkim_status,
    case((Mail.byte_length > PARSE_LIMIT, Mail.body_text)).label("index_text"),
)


def _texts(values: Sequence[str]) -> ColumnElement[list[str]]:
    return literal(list(values), ARRAY(Text))


async def originals(session: AsyncSession, hashes: Sequence[str]) -> dict[str, ExportMail]:
    """The original mail of each content still in the archive, by raw SHA-256."""
    rows = await session.execute(
        select(*_COLUMNS)
        .join(MboxFile, MboxFile.id == Mail.mbox_file_id)
        .where(Mail.raw_sha256 == any_(_texts(hashes)))
        .order_by(Mail.raw_sha256, Mail.is_duplicate_of.is_not(None), Mail.id)
        .ext(postgresql.distinct_on(Mail.raw_sha256))
    )
    mails = await _complete(session, rows.all())
    return {mail.raw_sha256: mail for mail in mails}


async def by_id(session: AsyncSession, mail_id: int) -> ExportMail | None:
    rows = await session.execute(
        select(*_COLUMNS).join(MboxFile, MboxFile.id == Mail.mbox_file_id).where(Mail.id == mail_id)
    )
    mails = await _complete(session, rows.all())
    return mails[0] if mails else None


async def _complete(session: AsyncSession, rows: Sequence[_Row]) -> list[ExportMail]:
    mails = [
        ExportMail(
            id=row.id,
            raw_sha256=row.raw_sha256,
            message_id=row.message_id,
            in_reply_to=row.in_reply_to,
            subject=row.subject,
            date=row.date_utc,
            source=MailSource(
                mbox_file_id=row.mbox_file_id,
                path=row.path,
                byte_offset=row.byte_offset,
                byte_length=row.byte_length,
            ),
            dkim_status=row.dkim_status,
            index_text=row.index_text,
        )
        for row in rows
    ]
    if not mails:
        return mails
    found = {mail.id: mail for mail in mails}
    ids = literal(list(found), ARRAY(BigInteger))
    name = func.coalesce(Participation.display_name, Person.display_name)
    participants = await session.execute(
        select(Participation.mail_id, Participation.role, Person.id, Person.canonical_email, name)
        .join(Person, Person.id == Participation.person_id)
        .where(Participation.mail_id == any_(ids))
        .order_by(Participation.mail_id, Participation.role, name, Person.canonical_email)
    )
    for mail_id, role, person_id, email, display in participants:
        ref = PersonRef(person_id=person_id, email=email, name=display)
        found[mail_id].participants.setdefault(role, []).append(ref)
    results = list(
        await session.scalars(
            select(DkimResult)
            .where(DkimResult.mail_id == any_(ids))
            .order_by(DkimResult.mail_id, DkimResult.signature_index)
        )
    )
    names = {key_name(r.selector, r.domain) for r in results if r.selector and r.domain}
    keys: dict[str, DnsCache] = {}
    if names:
        cached = await session.scalars(select(DnsCache).where(DnsCache.name.in_(names)))
        keys = {key.name: key for key in cached}
    for result in results:
        key = None
        if result.selector and result.domain:
            key = keys.get(key_name(result.selector, result.domain))
        found[result.mail_id].signatures.append(
            Signature(
                index=result.signature_index,
                status=result.status,
                reason=DkimReason(result.reason) if result.reason else None,
                domain=result.domain,
                selector=result.selector,
                algorithm=result.algorithm,
                key_bits=result.key_bits,
                aligned=result.aligned,
                signed_at=result.signed_at,
                checked_at=result.checked_at,
                key_status=key.status if key else None,
                key_record=key.record if key else None,
                key_fetched_at=key.fetched_at if key else None,
            )
        )
    attachments = await session.execute(
        select(
            Attachment.mail_id,
            Attachment.id,
            Attachment.filename,
            Attachment.mime_type,
            Attachment.size_bytes,
            Attachment.sha256,
        )
        .where(Attachment.mail_id == any_(ids))
        .order_by(Attachment.mail_id, Attachment.id)
    )
    for mail_id, attachment_id, filename, mime_type, size, sha256 in attachments:
        found[mail_id].attachments.append(
            AttachmentInfo(
                id=attachment_id, filename=filename, mime_type=mime_type, size=size, sha256=sha256
            )
        )
    return mails


async def research(session: AsyncSession, hashes: Sequence[str]) -> dict[str, MailResearch]:
    """The research data of each content (D53 to D58), empty where nothing was recorded."""
    wanted = _texts(hashes)
    marks = {
        mark.mail_sha256: Mark(
            flagged=mark.flagged,
            flagged_by=mark.flagged_by,
            flagged_at=mark.flagged_at,
            review=mark.review,
            review_by=mark.review_by,
            review_at=mark.review_at,
        )
        for mark in await session.scalars(
            select(MailMark).where(MailMark.mail_sha256 == any_(wanted))
        )
    }
    tags: dict[str, list[TagRef]] = defaultdict(list)
    for sha, tag_id, tag_name, color in await session.execute(
        select(MailTag.mail_sha256, Tag.id, Tag.name, Tag.color)
        .join(Tag, Tag.id == MailTag.tag_id)
        .where(MailTag.mail_sha256 == any_(wanted))
        .order_by(func.lower(Tag.name), Tag.id)
    ):
        tags[sha].append(TagRef(id=tag_id, name=tag_name, color=cast(TagColor, color)))
    collections: dict[str, list[CollectionRef]] = defaultdict(list)
    for sha, collection_id, collection_name in await session.execute(
        select(CollectionMail.mail_sha256, Collection.id, Collection.name)
        .join(Collection, Collection.id == CollectionMail.collection_id)
        .where(CollectionMail.mail_sha256 == any_(wanted))
        .order_by(func.lower(Collection.name), Collection.id)
    ):
        collections[sha].append(CollectionRef(id=collection_id, name=collection_name))
    notes: dict[str, list[NoteInfo]] = defaultdict(list)
    for note in await session.scalars(
        select(Note).where(Note.mail_sha256 == any_(wanted)).order_by(Note.created_at, Note.id)
    ):
        notes[note.mail_sha256].append(
            NoteInfo(
                id=note.id,
                body=note.body,
                author=note.author,
                created_at=note.created_at,
                updated_at=note.updated_at,
            )
        )
    return {
        sha: MailResearch(
            mark=marks.get(sha, NO_MARK),
            tags=tags[sha],
            collections=collections[sha],
            notes=notes[sha],
        )
        for sha in hashes
    }

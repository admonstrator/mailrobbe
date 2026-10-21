"""What an export says about a mail, from the database: metadata, DKIM, attachments with what
their files say about themselves (D167), the signals the last signals phase stored (D139), the
labels of its participants (D157) and the research data (D62), a batch of mails in a few
queries; and the keys from other sources than today's DNS its signatures rest on, with their
evidence and the sources' answers (D105), one key at a time.

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
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import (
    AttachmentInfo,
    CollectionRef,
    MailResearch,
    MailSource,
    Mark,
    NoteInfo,
    PersonLabel,
    PersonRef,
    TagColor,
    TagRef,
)
from mailrobbe.db.models import (
    Attachment,
    Collection,
    CollectionMail,
    DkimKey,
    DkimKeyEvidence,
    DkimKeyLookup,
    DkimResult,
    DnsCache,
    Document,
    Mail,
    MailMark,
    MailSignal,
    MailTag,
    MboxFile,
    Note,
    Participation,
    Person,
    Tag,
)
from mailrobbe.dkim.keys.identity import key_identity
from mailrobbe.dkim.override import key_name
from mailrobbe.enums import (
    DkimReason,
    DkimStatus,
    DnsStatus,
    DocumentMetadataStatus,
    KeyOrigin,
    ParticipationRole,
)
from mailrobbe.persons.labels import label_text, shown_labels
from mailrobbe.signals.model import SignalRules, signal_keys

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
    # The key the result rests on (D100): its origin, the dkim_key row (None for today's DNS),
    # its SHA-256 (keys.identity; for today's DNS of the cached record) and its evidence ids.
    key_origin: KeyOrigin | None = None
    key_id: int | None = None
    key_sha256: str | None = None
    evidence: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class AttachmentMetadata:
    """What an attachment's file says about itself (D167), as the import's metadata step stored
    it: every field found (attachments.metadata.model), never rated."""

    status: DocumentMetadataStatus
    error: str | None
    fields: dict[str, dict[str, Any]]


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
    # The keys of the signals stored in mail_signal (D139), in display order.
    signals: list[str] = field(default_factory=list)
    # The labels its participants show (D156), by person id; written only with research data.
    labels: dict[int, PersonLabel] = field(default_factory=dict)
    # Attachment id -> its metadata; attachments without a document yet are left out.
    attachment_metadata: dict[int, AttachmentMetadata] = field(default_factory=dict)

    def signal_names(self, signal_rules: SignalRules) -> list[str]:
        """The German names of its signals, as the mail list's CSV names them."""
        return [signal_rules.label(key) for key in self.signals]

    def label_texts(self) -> list[str]:
        """Its participants named by a label, From to Bcc, each once (labels.label_text)."""
        texts = (
            label_text(self.labels[person.person_id], person.email)
            for role in ParticipationRole
            for person in self.participants.get(role, [])
            if person.person_id in self.labels
        )
        return list(dict.fromkeys(text for text in texts if text))


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
    persons = {ref.person_id for m in mails for refs in m.participants.values() for ref in refs}
    labels = await shown_labels(session, persons)
    for mail in mails:
        for refs in mail.participants.values():
            mail.labels.update(
                (r.person_id, labels[r.person_id]) for r in refs if r.person_id in labels
            )
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
    stored = await _stored_keys(session, {r.key_id for r in results if r.key_id is not None})
    for result in results:
        key = None
        if result.selector and result.domain:
            key = keys.get(key_name(result.selector, result.domain))
        key_sha256, evidence = (
            stored.get(result.key_id, (None, ())) if result.key_id else (None, ())
        )
        if result.key_origin is KeyOrigin.DNS and key and key.record:
            identity = key_identity(key.record)
            key_sha256 = identity.key_sha256 if identity else None
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
                key_origin=result.key_origin,
                key_id=result.key_id,
                key_sha256=key_sha256,
                evidence=evidence,
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
            Document.metadata_status,
            Document.metadata_error,
            Document.metadata_fields,
        )
        .outerjoin(Document, Document.id == Attachment.document_id)
        .where(Attachment.mail_id == any_(ids))
        .order_by(Attachment.mail_id, Attachment.id)
    )
    for row in attachments:
        found[row.mail_id].attachments.append(
            AttachmentInfo(
                id=row.id,
                filename=row.filename,
                mime_type=row.mime_type,
                size=row.size_bytes,
                sha256=row.sha256,
            )
        )
        if row.metadata_status is not None:
            found[row.mail_id].attachment_metadata[row.id] = AttachmentMetadata(
                row.metadata_status, row.metadata_error, row.metadata_fields or {}
            )
    # signal_keys() is the display order of SignalRules.keys whatever the settings, so no
    # settings are needed here; a key of a theme removed since goes last.
    order = {key: index for index, key in enumerate(signal_keys())}
    signals = await session.execute(
        select(MailSignal.mail_id, MailSignal.signal).where(MailSignal.mail_id == any_(ids))
    )
    for mail_id, signal in signals:
        found[mail_id].signals.append(signal)
    for mail in mails:
        mail.signals.sort(key=lambda key: (order.get(key, len(order)), key))
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


async def _stored_keys(
    session: AsyncSession, key_ids: set[int]
) -> dict[int, tuple[str, tuple[int, ...]]]:
    """The SHA-256 and the evidence ids of each dkim_key."""
    if not key_ids:
        return {}
    rows = await session.execute(
        select(
            DkimKey.id,
            DkimKey.key_sha256,
            func.array_remove(
                func.array_agg(aggregate_order_by(DkimKeyEvidence.id, DkimKeyEvidence.id)), None
            ),
        )
        .outerjoin(DkimKeyEvidence, DkimKeyEvidence.key_id == DkimKey.id)
        .where(DkimKey.id == any_(literal(sorted(key_ids), ARRAY(BigInteger))))
        .group_by(DkimKey.id)
    )
    return {key_id: (sha256, tuple(evidence)) for key_id, sha256, evidence in rows}


# Keys (D105) ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KeyEvidence:
    """One piece of evidence with the lookup it comes from, its answer included."""

    id: int
    origin: KeyOrigin
    observed_from: datetime | None
    observed_to: datetime | None
    reference: str | None
    note: str | None
    editor: str | None
    details: dict[str, Any]
    lookup_id: int
    source: str
    query: str
    asked_at: datetime
    outcome: str
    http_status: int | None
    raw: bytes | None
    raw_sha256: str | None
    raw_type: str | None
    raw_name: str | None
    tool_version: str

    @property
    def used(self) -> list[tuple[str, int]]:
        """The signatures a reconstruction used: (mail SHA-256, signature index)."""
        return [
            (entry["mail_sha256"], entry["signature_index"])
            for entry in self.details.get("signatures", [])
            if isinstance(entry, dict) and {"mail_sha256", "signature_index"} <= entry.keys()
        ]


@dataclass(frozen=True, slots=True)
class ExportKey:
    """A dkim_key row with its evidence, strongest origin first, then oldest."""

    id: int
    name: str
    key_type: str
    bits: int
    key_sha256: str
    record: str
    origin: KeyOrigin
    factorable: bool
    evidence: list[KeyEvidence]


async def export_key(session: AsyncSession, key_id: int) -> ExportKey | None:
    """The key with its evidence and the lookups' answers; None when it is gone."""
    key = await session.get(DkimKey, key_id)
    if key is None:
        return None
    rows = await session.execute(
        select(DkimKeyEvidence, DkimKeyLookup)
        .join(DkimKeyLookup, DkimKeyLookup.id == DkimKeyEvidence.lookup_id)
        .where(DkimKeyEvidence.key_id == key_id)
        .order_by(DkimKeyEvidence.origin, DkimKeyEvidence.created_at, DkimKeyEvidence.id)
    )
    evidence = [
        KeyEvidence(
            id=item.id,
            origin=item.origin,
            observed_from=item.observed_from,
            observed_to=item.observed_to,
            reference=item.reference,
            note=item.note,
            editor=item.editor,
            details=item.details,
            lookup_id=lookup.id,
            source=lookup.source,
            query=lookup.query,
            asked_at=lookup.asked_at,
            outcome=lookup.outcome,
            http_status=lookup.http_status,
            raw=lookup.raw,
            raw_sha256=lookup.raw_sha256,
            raw_type=lookup.raw_type,
            raw_name=lookup.raw_name,
            tool_version=lookup.tool_version,
        )
        for item, lookup in rows
    ]
    return ExportKey(
        id=key.id,
        name=key.name,
        key_type=key.key_type,
        bits=key.bits,
        key_sha256=key.key_sha256,
        record=key.record,
        origin=key.origin,
        factorable=key.factorable,
        evidence=evidence,
    )

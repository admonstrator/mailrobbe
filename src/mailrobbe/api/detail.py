"""One mail: metadata, research data, bodies read on demand from its MBOX file, EML download and
DKIM recheck (D22, D53); each signature with the key from another source it rests on (D100).

Routes: GET /api/mails/{id}, /api/mails/{id}/body, /api/mails/{id}/eml,
POST /api/mails/{id}/dkim/recheck. Writes to the research data are in research.py.

The detail comes from the database alone, in the same few queries whatever the mail. Body, EML
and recheck read the message from its MBOX file in a worker thread and use it only while its
SHA-256 is still raw_sha256; parsing and DKIM checks run in a worker thread too.
"""

import asyncio
import logging
from typing import Annotated, Any, Literal, cast

import fastapi
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import BigInteger, Text, any_, func, literal, literal_column, select, tuple_
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from mailrobbe.ai.queue import OCR_READABLE, TRANSCRIBABLE
from mailrobbe.api import body, events, hiding, near
from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.schemas import (
    DUPLICATES_LIMIT,
    THREAD_LIMIT,
    AttachmentInfo,
    CollectionRef,
    DkimKeyInfo,
    DkimSignature,
    KeyEvidenceInfo,
    MailDetail,
    MailDkim,
    MailHeaders,
    MailRaw,
    MailResearch,
    MailSource,
    MailText,
    Mark,
    MetadataSummary,
    NoteInfo,
    Participant,
    PersonRef,
    TagColor,
    TagRef,
    ThreadMail,
    UsedSignature,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import (
    MAIL_SORT_KEY,
    Attachment,
    Collection,
    CollectionMail,
    DkimKey,
    DkimKeyEvidence,
    DkimKeyLookup,
    DkimResult,
    DnsCache,
    Document,
    Edge,
    Mail,
    MailMark,
    MailTag,
    MboxFile,
    Note,
    Participation,
    Person,
    PersonStats,
    Tag,
)
from mailrobbe.dkim import store
from mailrobbe.dkim.checker import DkimChecker
from mailrobbe.dkim.keys.store import keep_cached_keys, load_candidates
from mailrobbe.dkim.override import key_name
from mailrobbe.enums import (
    DkimReason,
    DkimStatus,
    DocumentMetadataStatus,
    DocumentProtection,
    ParticipationRole,
)
from mailrobbe.mbox import read_verified
from mailrobbe.persons.labels import attach_labels
from mailrobbe.persons.roots import ROOT
from mailrobbe.preview.kinds import preview_kind

router = APIRouter(prefix="/api", tags=["mail"])
log = logging.getLogger(__name__)

# mail.id is a bigint: a larger number is a validation error, not a database error.
MailId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]
BodyFormat = Literal["text", "html", "headers", "raw"]

# The UI shows the HTML body in <iframe sandbox="">; this policy keeps it inert even when opened
# directly: no script, nothing loaded from anywhere, only inline styles and data: images (D22).
HTML_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'self'; sandbox"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, no-cache",
}

_NAME = func.coalesce(Participation.display_name, Person.display_name)  # as used in that mail
NOTE_COLUMNS = (Note.id, Note.body, Note.author, Note.created_at, Note.updated_at)  # a NoteInfo
_REPLIED = aliased(Mail)
_DUPLICATE = aliased(Mail)
_DETAIL = (
    select(
        Mail.id,
        Mail.subject,
        Mail.date_utc,
        Mail.message_id,
        Mail.in_reply_to,
        Mail.reference_ids,
        Mail.mbox_file_id,
        MboxFile.path,
        Mail.byte_offset,
        Mail.byte_length,
        Mail.raw_sha256,
        Mail.has_attachments,
        Mail.dkim_status,
        Mail.thread_id,
        Mail.is_duplicate_of,
        Mail.list_id,
        MailMark.flagged,
        MailMark.flagged_by,
        MailMark.flagged_at,
        MailMark.review,
        MailMark.review_by,
        MailMark.review_at,
        # The mail replied to: the original before its duplicates, then the lowest id.
        select(_REPLIED.id)
        .where(_REPLIED.message_id == Mail.in_reply_to, _REPLIED.id != Mail.id)
        .order_by(_REPLIED.is_duplicate_of.is_not(None), _REPLIED.id)
        .limit(1)
        .scalar_subquery()
        .label("in_reply_to_id"),
        func.array(
            select(_DUPLICATE.id)
            .where(_DUPLICATE.is_duplicate_of == Mail.id)
            .order_by(_DUPLICATE.id)
            .limit(DUPLICATES_LIMIT)
            .scalar_subquery(),
            type_=postgresql.ARRAY(BigInteger),
        ).label("duplicates"),
    )
    .join(MboxFile, MboxFile.id == Mail.mbox_file_id)
    .outerjoin(MailMark, MailMark.mail_sha256 == Mail.raw_sha256)
)


@router.get("/mails/{mail_id}")
async def mail_detail(mail_id: MailId, session: Session, settings: AppSettings) -> MailDetail:
    mail = (await session.execute(_DETAIL.where(Mail.id == mail_id))).one_or_none()
    if mail is None:
        raise _not_found(mail_id)
    thread, thread_size = await _thread(session, mail_id, mail.thread_id)
    group = await near.near_group(session, mail_id)
    detail = MailDetail(
        id=mail.id,
        subject=mail.subject,
        date=mail.date_utc,
        message_id=mail.message_id,
        in_reply_to=mail.in_reply_to,
        in_reply_to_id=mail.in_reply_to_id,
        reference_ids=mail.reference_ids or [],
        source=MailSource(
            mbox_file_id=mail.mbox_file_id,
            path=mail.path,
            byte_offset=mail.byte_offset,
            byte_length=mail.byte_length,
        ),
        raw_sha256=mail.raw_sha256,
        has_attachments=mail.has_attachments,
        dkim=await _dkim(session, mail_id, mail.dkim_status),
        participants=await _participants(session, mail_id),
        attachments=await _attachments(session, mail_id, settings.preview_max_size),
        thread_id=mail.thread_id,
        thread=thread,
        thread_size=thread_size,
        duplicate_of=mail.is_duplicate_of,
        duplicates=mail.duplicates,
        research=MailResearch(
            mark=Mark(
                flagged=bool(mail.flagged),
                flagged_by=mail.flagged_by,
                flagged_at=mail.flagged_at,
                review=mail.review,
                review_by=mail.review_by,
                review_at=mail.review_at,
            ),
            tags=await tag_refs(session, mail.raw_sha256),
            collections=await collection_refs(session, mail.raw_sha256),
            notes=await mail_notes(session, mail.raw_sha256),
        ),
        near_group=group.group_id,
        near=group.mails,
        near_size=group.size,
        events=await events.mail_events(session, mail_id),
        hidden=await hiding.mail_hiding(session, mail_id),  # D222
        list_id=mail.list_id,
    )
    await attach_labels(session, detail)
    return detail


@router.get("/mails/{mail_id}/body", response_model=None)
async def mail_body(
    mail_id: MailId,
    session: Session,
    settings: AppSettings,
    view: Annotated[BodyFormat, Query(alias="format")] = "text",
) -> MailText | MailHeaders | MailRaw | Response:
    message = await stored_message(session, settings, mail_id)
    if view == "html":
        html = await asyncio.to_thread(body.mail_html, message)
        if html is None:
            raise api_error(404, "no_html", f"mail {mail_id} has no HTML part")
        return Response(html, media_type="text/html", headers=HTML_HEADERS)
    if view == "headers":
        return await asyncio.to_thread(body.mail_headers, message)
    if view == "raw":
        return await asyncio.to_thread(body.mail_raw, message)
    return await body.text_view(session, message)  # standard blocks cut out (D227)


@router.get("/mails/{mail_id}/eml")
async def mail_eml(mail_id: MailId, session: Session, settings: AppSettings) -> Response:
    message = await stored_message(session, settings, mail_id)
    disposition = f'attachment; filename="mail-{mail_id}.eml"'
    return Response(
        message, media_type="message/rfc822", headers={"Content-Disposition": disposition}
    )


@router.post("/mails/{mail_id}/dkim/recheck")
async def recheck_dkim(mail_id: MailId, session: Session, settings: AppSettings) -> MailDkim:
    """Check the mail again (SPEC 3.4, D13): keys that were missing or timed out are asked anew."""
    message = await stored_message(session, settings, mail_id)
    answers = await store.load_dns_cache(session)
    await keep_cached_keys(session)  # D106
    candidates = await load_candidates(session)  # keys of deleted selectors and kept ones
    await session.commit()  # no transaction stays open while DNS answers
    try:
        checker = DkimChecker.from_settings(
            settings, preload=answers, refresh_negative=True, candidates=candidates
        )
    except (OSError, ValueError) as error:
        log.error(
            "cannot recheck DKIM of mail %d, the DKIM DNS settings are wrong: %s", mail_id, error
        )
        raise HTTPException(500, "the DKIM DNS settings are wrong, see the server log") from None
    verdict = await asyncio.to_thread(checker.check, message)
    await store.save_verdicts(session, [(mail_id, verdict)])
    await store.upsert_dns_cache(session, checker.take_new_answers())
    await session.commit()
    return await _dkim(session, mail_id, verdict.status)


def _not_found(mail_id: int) -> HTTPException:
    return api_error(404, "not_found", f"no mail with id {mail_id}")


# Reading the source ------------------------------------------------------------------------


async def stored_message(session: AsyncSession, settings: Settings, mail_id: int) -> bytes:
    """The mail's message from its MBOX file, only while it is the imported one (D22)."""
    found = await session.execute(
        select(MboxFile.path, Mail.byte_offset, Mail.byte_length, Mail.raw_sha256)
        .join(MboxFile, MboxFile.id == Mail.mbox_file_id)
        .where(Mail.id == mail_id)
    )
    row = found.one_or_none()
    if row is None:
        raise _not_found(mail_id)
    await session.commit()  # the file may be slow to read; hold no connection meanwhile
    path, byte_offset, byte_length, raw_sha256 = row
    try:
        message = await asyncio.to_thread(
            read_verified, settings.mbox_dir / path, byte_offset, byte_length, raw_sha256
        )
    except OSError as error:
        log.warning("mail %d: cannot read %s: %s", mail_id, path, error)
        raise api_error(409, "source_missing", f"cannot read {path}: {error}") from None
    if message is None:
        log.warning(
            "mail %d: %s at offset %d is not the imported mail any more", mail_id, path, byte_offset
        )
        raise api_error(
            409, "source_changed", f"{path} at offset {byte_offset} no longer holds mail {mail_id}"
        )
    return message


# Parts of the detail -----------------------------------------------------------------------


async def tag_refs(session: AsyncSession, mail_sha256: str) -> list[TagRef]:
    """The tags of a mail's content, by name ignoring case (research.py answers links with it)."""
    rows = await session.execute(
        select(Tag.id, Tag.name, Tag.color)
        .join(MailTag, MailTag.tag_id == Tag.id)
        .where(MailTag.mail_sha256 == mail_sha256)
        .order_by(func.lower(Tag.name), Tag.id)
    )
    return [TagRef(id=id_, name=name, color=cast(TagColor, color)) for id_, name, color in rows]


async def collection_refs(session: AsyncSession, mail_sha256: str) -> list[CollectionRef]:
    """The Akten holding a mail's content, by name ignoring case."""
    rows = await session.execute(
        select(Collection.id, Collection.name)
        .join(CollectionMail, CollectionMail.collection_id == Collection.id)
        .where(CollectionMail.mail_sha256 == mail_sha256)
        .order_by(func.lower(Collection.name), Collection.id)
    )
    return [CollectionRef(id=id_, name=name) for id_, name in rows]


async def mail_notes(session: AsyncSession, mail_sha256: str) -> list[NoteInfo]:
    """The notes on a mail's content, oldest first."""
    rows = await session.execute(
        select(*NOTE_COLUMNS)
        .where(Note.mail_sha256 == mail_sha256)
        .order_by(Note.created_at, Note.id)
    )
    return [NoteInfo(**row._mapping) for row in rows]


async def _participants(session: AsyncSession, mail_id: int) -> list[Participant]:
    """From, to, cc, bcc (the enum's order), by name then address within a role.

    The figures are those of each address's root person (D26, D28): mails and contacts from its
    person_stats row, mails_with_sender from the edge between the sender's root and its root
    (none for the sender's own root). None where there is no such row.
    """
    root = ROOT.label("root")
    rows = (
        await session.execute(
            select(
                Participation.role,
                Person.id,
                Person.canonical_email,
                _NAME,
                root,
                PersonStats.mails,
                PersonStats.contacts,
            )
            .join(Person, Person.id == Participation.person_id)
            .outerjoin(PersonStats, PersonStats.person_id == ROOT)
            .where(Participation.mail_id == mail_id)
            .order_by(Participation.role, _NAME, Person.canonical_email)
        )
    ).all()
    sender = next((row.root for row in rows if row.role is ParticipationRole.FROM), None)
    together: dict[int, int] = {}
    others = {row.root for row in rows} - {sender}
    if sender is not None and others:
        pairs = [(min(sender, other), max(sender, other)) for other in others]
        edges = await session.execute(
            select(Edge.person_a, Edge.person_b, Edge.mails_total).where(
                tuple_(Edge.person_a, Edge.person_b).in_(pairs)
            )
        )
        for person_a, person_b, total in edges:
            together[person_b if person_a == sender else person_a] = total
    return [
        Participant(
            person_id=person_id,
            email=email,
            name=name,
            role=role,
            mails=mails,
            contacts=contacts,
            mails_with_sender=together.get(person_root),
        )
        for role, person_id, email, name, person_root, mails, contacts in rows
    ]


async def _dkim(session: AsyncSession, mail_id: int, status: DkimStatus | None) -> MailDkim:
    """The mail's signatures by index, each with the dns_cache row of its key if there is one
    and the key from another source it rests on (D100)."""
    results = list(
        await session.scalars(
            select(DkimResult)
            .where(DkimResult.mail_id == mail_id)
            .order_by(DkimResult.signature_index)
        )
    )
    names = {key_name(r.selector, r.domain) for r in results if r.selector and r.domain}
    keys: dict[str, DnsCache] = {}
    if names:
        cached = await session.scalars(select(DnsCache).where(DnsCache.name.in_(names)))
        keys = {key.name: key for key in cached}
    found = await key_infos(session, {r.key_id for r in results if r.key_id is not None})
    return MailDkim(
        status=status, signatures=[_signature(result, keys, found) for result in results]
    )


def _signature(
    result: DkimResult, keys: dict[str, DnsCache], found: dict[int, DkimKeyInfo]
) -> DkimSignature:
    key = None
    if result.selector and result.domain:
        key = keys.get(key_name(result.selector, result.domain))
    return DkimSignature(
        index=result.signature_index,
        status=result.status,
        reason=DkimReason(result.reason) if result.reason else None,
        domain=result.domain,
        selector=result.selector,
        algorithm=result.algorithm,
        key_bits=result.key_bits,
        signed_headers=result.signed_headers,
        body_hash_ok=result.body_hash_ok,
        signed_at=result.signed_at,
        aligned=result.aligned,
        checked_at=result.checked_at,
        dns_cached=result.dns_cached,
        dns_record=key.record if key else None,
        dns_fetched_at=key.fetched_at if key else None,
        dns_ttl=key.ttl if key else None,
        key_origin=result.key_origin,
        key=None if result.key_id is None else found.get(result.key_id),
    )


async def key_infos(session: AsyncSession, key_ids: set[int]) -> dict[int, DkimKeyInfo]:
    """The dkim_key rows with these ids and all their evidence, strongest origin first: one query
    for the keys, one for their evidence, one for today's ids of the mails a reconstruction used
    (by content, the original first, as permalinks do, D61).

    A key's signatures are the results it verified on mails that are no duplicates, counted
    through ix_dkim_result_key_id.
    """
    if not key_ids:
        return {}
    ids = literal(sorted(key_ids), postgresql.ARRAY(BigInteger))
    verified = (
        select(func.count())
        .select_from(DkimResult)
        .join(Mail, Mail.id == DkimResult.mail_id)
        .where(DkimResult.key_id == DkimKey.id, Mail.is_duplicate_of.is_(None))
        .scalar_subquery()
    )
    keys = (
        await session.execute(
            select(DkimKey, verified.label("signatures"))
            .where(DkimKey.id == any_(ids))
            .order_by(DkimKey.origin, DkimKey.id)  # key_origin lists the strongest first
        )
    ).all()
    lookup = DkimKeyLookup
    evidence = (
        await session.execute(
            select(
                DkimKeyEvidence,
                lookup.source,
                lookup.asked_at,
                lookup.raw_sha256,
                func.octet_length(lookup.raw).label("raw_size"),
            )
            .join(lookup, lookup.id == DkimKeyEvidence.lookup_id)
            .where(DkimKeyEvidence.key_id == any_(ids))
            .order_by(DkimKeyEvidence.origin, DkimKeyEvidence.created_at, DkimKeyEvidence.id)
        )
    ).all()
    used = {
        row.DkimKeyEvidence.id: [
            (entry["mail_sha256"], entry["signature_index"])
            for entry in row.DkimKeyEvidence.details.get("signatures", [])
        ]
        for row in evidence
    }
    today = await _originals(session, {sha for pairs in used.values() for sha, _ in pairs})
    pieces: dict[int, list[KeyEvidenceInfo]] = {}
    for row in evidence:
        item: DkimKeyEvidence = row.DkimKeyEvidence
        pieces.setdefault(item.key_id, []).append(
            KeyEvidenceInfo(
                id=item.id,
                origin=item.origin,
                source=row.source,
                lookup_id=item.lookup_id,
                asked_at=row.asked_at,
                observed_from=item.observed_from,
                observed_to=item.observed_to,
                reference=item.reference,
                note=item.note,
                editor=item.editor,
                raw_sha256=row.raw_sha256,
                raw_size=row.raw_size,
                signatures=[
                    UsedSignature(mail_id=today.get(sha), mail_sha256=sha, signature_index=index)
                    for sha, index in used[item.id]
                ],
            )
        )
    return {
        key.id: DkimKeyInfo(
            id=key.id,
            name=key.name,
            key_type=key.key_type,
            bits=key.bits,
            key_sha256=key.key_sha256,
            record=key.record,
            origin=key.origin,
            factorable=key.factorable,
            signatures=signatures,
            evidence=pieces.get(key.id, []),
        )
        for key, signatures in keys
    }


async def _originals(session: AsyncSession, hashes: set[str]) -> dict[str, int]:
    """The mail standing for each content: no duplicate first, then the lowest id."""
    if not hashes:
        return {}
    rows = await session.execute(
        select(Mail.raw_sha256, Mail.id)
        .where(Mail.raw_sha256 == any_(literal(sorted(hashes), postgresql.ARRAY(Text))))
        .order_by(Mail.raw_sha256, Mail.is_duplicate_of.is_not(None), Mail.id)
        .ext(postgresql.distinct_on(Mail.raw_sha256))
    )
    return {sha: mail_id for sha, mail_id in rows}


# Where the text recognition stands for an attachment's document (D280, AttachmentOcr).
_OCR_STATE = literal_column(
    f"""CASE
    WHEN document.sha256 IS NULL THEN NULL
    WHEN EXISTS (SELECT 1 FROM ai_task t WHERE t.kind = 'ocr' AND t.target_sha256 = document.sha256
                 AND t.status IN ('waiting', 'running')) THEN 'queued'
    WHEN document.text_origin = 'ocr' THEN 'recognised'
    WHEN EXISTS (SELECT 1 FROM ai_result r WHERE r.kind = 'ocr' AND r.state = 'valid'
                 AND r.target_sha256 = document.sha256) THEN 'no_text'
    WHEN EXISTS (SELECT 1 FROM document d WHERE d.id = document.id AND {OCR_READABLE})
        THEN 'readable'
END""",
    Text,
)

# Where the transcription stands for an attachment's recording (D296, AttachmentTranscript).
_TRANSCRIPT_STATE = literal_column(
    f"""CASE
    WHEN document.sha256 IS NULL THEN NULL
    WHEN EXISTS (SELECT 1 FROM ai_task t WHERE t.kind = 'transcribe'
                 AND t.target_sha256 = document.sha256 AND t.status IN ('waiting', 'running'))
        THEN 'queued'
    WHEN document.text_origin = 'transcript' THEN 'transcribed'
    WHEN EXISTS (SELECT 1 FROM ai_result r WHERE r.kind = 'transcribe' AND r.state = 'valid'
                 AND r.target_sha256 = document.sha256) THEN 'no_text'
    WHEN EXISTS (SELECT 1 FROM document d WHERE d.id = document.id AND {TRANSCRIBABLE})
        THEN 'transcribable'
END""",
    Text,
)


async def _attachments(
    session: AsyncSession, mail_id: int, preview_max_size: int
) -> list[AttachmentInfo]:
    """The mail's attachments, each with its document (D75) once finalize assigned it, and the
    preview the browser can show (D120); a container's entries that became documents under it
    (D231), in its order."""
    rows = await session.execute(
        select(
            Attachment.id,
            Attachment.container_id,
            Attachment.path,
            Attachment.filename,
            Attachment.mime_type,
            Attachment.size_bytes,
            Attachment.sha256,
            Attachment.document_id,
            Document.kind,
            Document.text_status,
            Document.pages,
            Document.mails,
            Document.metadata_status,
            Document.metadata_author,
            Document.metadata_modified_by,
            Document.metadata_program,
            Document.metadata_device,
            Document.metadata_created,
            Document.metadata_gps,
            Document.protection,
            Document.members_status,
            Document.metadata_latitude,
            Document.metadata_longitude,
            _OCR_STATE.label("ocr"),
            _TRANSCRIPT_STATE.label("transcript"),
            Document.duration,
        )
        .outerjoin(Document, Document.id == Attachment.document_id)
        .where(Attachment.mail_id == mail_id)
        .order_by(Attachment.container_id.is_not(None), Attachment.position, Attachment.id)
    )

    def metadata(row: Any) -> MetadataSummary | None:
        """What the file says about itself (D167), when its summary names anything."""
        summary = MetadataSummary(
            author=row.metadata_author,
            modified_by=row.metadata_modified_by,
            software=row.metadata_program,
            device=row.metadata_device,
            created=row.metadata_created,
            gps=bool(row.metadata_gps),
            latitude=row.metadata_latitude,  # D249
            longitude=row.metadata_longitude,
        )
        found = row.metadata_status == DocumentMetadataStatus.FOUND
        return summary if found and summary != MetadataSummary() else None

    def info(row: Any) -> AttachmentInfo:
        locked = row.protection == DocumentProtection.LOCKED
        return AttachmentInfo(
            id=row.id,
            filename=row.filename,
            mime_type=row.mime_type,
            size=row.size_bytes,
            sha256=row.sha256,
            document_id=row.document_id,
            kind=row.kind,
            text_status=row.text_status,
            pages=row.pages,
            document_mails=row.mails,
            preview=None  # nothing shows a locked one (D209)
            if locked
            else preview_kind(
                row.kind,
                row.filename,
                row.mime_type,
                row.size_bytes,
                hashed=row.sha256 is not None,
                max_size=preview_max_size,
            ),
            metadata=metadata(row),
            protection=row.protection,
            path=row.path,
            members_status=row.members_status,
            ocr=row.ocr,
            transcript=row.transcript,
            duration=row.duration,
        )

    infos: dict[int, AttachmentInfo] = {}
    top: list[AttachmentInfo] = []
    for row in rows:  # containers before their members
        infos[row.id] = info(row)
        container = infos.get(row.container_id) if row.container_id is not None else None
        if row.container_id is None:
            top.append(infos[row.id])
        elif container is not None:
            container.members.append(infos[row.id])
    return top


async def _thread(
    session: AsyncSession, mail_id: int, thread_id: int | None
) -> tuple[list[ThreadMail], int]:
    """At most THREAD_LIMIT mails of the thread around this one, by date then id; and its size."""
    if thread_id is None:
        return [], 0
    members = (
        select(
            Mail.id,
            Mail.date_utc,
            Mail.subject,
            Mail.dkim_status,
            func.row_number()
            .over(order_by=(literal_column(MAIL_SORT_KEY), Mail.id))
            .label("position"),
            func.count().over().label("size"),
        )
        .where(Mail.thread_id == thread_id)
        .cte("members")
    )
    # The window starts half a limit before this mail, but never past the last full window.
    position = select(members.c.position).where(members.c.id == mail_id).scalar_subquery()
    start = func.greatest(
        1, func.least(position - THREAD_LIMIT // 2, members.c.size - THREAD_LIMIT + 1)
    )
    rows = (
        await session.execute(
            select(members)
            .where(members.c.position >= start, members.c.position < start + THREAD_LIMIT)
            .order_by(members.c.position)
        )
    ).all()
    senders = await mail_senders(session, [row.id for row in rows])
    thread = [
        ThreadMail(
            id=row.id,
            date=row.date_utc,
            subject=row.subject,
            sender=senders.get(row.id),
            dkim_status=row.dkim_status,
        )
        for row in rows
    ]
    return thread, rows[0].size if rows else 0


async def mail_senders(session: AsyncSession, mail_ids: list[int]) -> dict[int, PersonRef]:
    """The sender of each mail: its first from participant by name, then address."""
    if not mail_ids:
        return {}
    rows = await session.execute(
        select(Participation.mail_id, Person.id, Person.canonical_email, _NAME)
        .join(Person, Person.id == Participation.person_id)
        .where(Participation.mail_id.in_(mail_ids), Participation.role == ParticipationRole.FROM)
        .order_by(Participation.mail_id, _NAME, Person.canonical_email)
        .ext(postgresql.distinct_on(Participation.mail_id))
    )
    return {
        mail_id: PersonRef(person_id=person_id, email=email, name=name)
        for mail_id, person_id, email, name in rows
    }

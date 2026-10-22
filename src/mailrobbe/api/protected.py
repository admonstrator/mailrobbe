"""Protected and packed documents (milestone 19, D230 to D239): what the document page shows of a
document's password and of its container, and the passwords typed in by hand (D237). Endpoints
and models are in schemas.py; the document page and list (api/documents.py) use the helpers.

Routes: POST /api/documents/{id}/password, /api/documents/passwords.

A typed-in password is kept as a finding of the editor (passwords.store), so a later import run
tries it on documents found since (tier manual), and is tried at once on the locked document, or
on every locked one, each in a process of its own (attachments.protected.try_passwords), at most
MAILROBBE_PREVIEW_WORKERS at a time. A hit opens the document with the text read with the
password (tier typed, found_by the editor); a container is unpacked and an opened document's
metadata read by the next import run. The request holds no database connection while it reads
MBOX files and tries.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Annotated, Any

import fastapi
from fastapi import APIRouter
from sqlalchemy import BigInteger, any_, literal, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.detail import mail_senders
from mailrobbe.api.schemas import (
    RECIPIENT_PREVIEW,
    DocumentContainerRef,
    DocumentMember,
    DocumentMembers,
    DocumentPassword,
    DocumentRef,
    PasswordFinding,
    PasswordTry,
    PasswordTryResult,
    PersonRef,
    ThreadMail,
)
from mailrobbe.attachments.content import AttachmentChanged, document_sources, read_attachment
from mailrobbe.attachments.extract import ExtractionLimits
from mailrobbe.attachments.protected import trial_format, try_passwords
from mailrobbe.config import Settings
from mailrobbe.db.models import (
    Document,
    Mail,
    Participation,
    Password,
    Person,
)
from mailrobbe.db.models import (
    DocumentMember as MemberRow,
)
from mailrobbe.db.models import (
    DocumentPassword as PasswordRow,
)
from mailrobbe.db.models import (
    PasswordFinding as FindingRow,
)
from mailrobbe.enums import (
    DocumentKind,
    DocumentMembersStatus,
    DocumentProtection,
    ParticipationRole,
    PasswordTier,
)
from mailrobbe.jobrun import describe
from mailrobbe.passwords.store import Finding, Opener, record_tried, store_findings, store_opened

router = APIRouter(prefix="/api", tags=["documents"])
log = logging.getLogger(__name__)

DocumentId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]

CONTAINER_KINDS = (DocumentKind.ARCHIVE, DocumentKind.EMAIL)  # the archives step's (D231)
# A locked document a password may open: a container whose format is not unpacked is left alone,
# as the passwords step does (passwords.phase).
_LOCKED = (
    Document.protection == DocumentProtection.LOCKED,
    Document.members_status.is_distinct_from(DocumentMembersStatus.UNSUPPORTED),
)
_TRIED_COLUMNS = (Document.id, Document.name, Document.mime_type, Document.kind)


# The document page ----------------------------------------------------------------------------


def password_trial(row: Any) -> bool:
    """Whether a password can be tried on the document: PDF, OOXML, ZIP and 7z (D235), not ODF
    (D239) nor a container whose format is not unpacked. row has kind, name, mime_type and
    members_status."""
    if row.members_status == DocumentMembersStatus.UNSUPPORTED:
        return False
    if row.kind in (DocumentKind.ARCHIVE, DocumentKind.PDF):
        return True
    return trial_format(row.name, row.mime_type, b"") is not None


async def contained_documents(session: AsyncSession, ids: Sequence[int]) -> set[int]:
    """Those of the documents found inside a container (D231)."""
    if not ids:
        return set()
    found = await session.scalars(
        select(MemberRow.member_id)
        .where(MemberRow.member_id == any_(literal(list(ids), ARRAY(BigInteger))))
        .distinct()
    )
    return {document_id for document_id in found if document_id is not None}


async def found_password(session: AsyncSession, document_id: int) -> DocumentPassword | None:
    """The password that opened the document, with where it was found (D208, D236)."""
    row = (
        await session.execute(
            select(
                Password.value,
                PasswordRow.tier,
                PasswordRow.found_at,
                PasswordRow.found_by,
                FindingRow.id.label("finding_id"),
                FindingRow.context,
                FindingRow.mail_id,
                FindingRow.document_id,
                FindingRow.editor,
                FindingRow.created_at,
            )
            .join(Password, Password.id == PasswordRow.password_id)
            .outerjoin(FindingRow, FindingRow.id == PasswordRow.finding_id)
            .where(PasswordRow.document_id == document_id)
        )
    ).one_or_none()
    if row is None:
        return None
    finding = None
    if row.finding_id is not None:
        mail, recipients = await _finding_mail(session, row.mail_id)
        finding = PasswordFinding(
            id=row.finding_id,
            context=row.context,
            mail=mail,
            recipients=recipients,
            document=await _document_ref(session, row.document_id),
            editor=row.editor,
            created_at=row.created_at,
        )
    return DocumentPassword(
        value=row.value,
        tier=row.tier,
        found_at=row.found_at,
        found_by=row.found_by,
        finding=finding,
    )


async def _finding_mail(
    session: AsyncSession, mail_id: int | None
) -> tuple[ThreadMail | None, list[PersonRef]]:
    """The mail a password was found in, and its first To recipients by name, then address."""
    if mail_id is None:
        return None, []
    row = (
        await session.execute(
            select(Mail.id, Mail.date_utc, Mail.subject, Mail.dkim_status).where(Mail.id == mail_id)
        )
    ).one_or_none()
    if row is None:
        return None, []
    senders = await mail_senders(session, [mail_id])
    name = Person.display_name
    to = await session.execute(
        select(Person.id, Person.canonical_email, name)
        .join(Participation, Participation.person_id == Person.id)
        .where(Participation.mail_id == mail_id, Participation.role == ParticipationRole.TO)
        .order_by(name.is_(None), name, Person.canonical_email)
        .limit(RECIPIENT_PREVIEW)
    )
    mail = ThreadMail(
        id=row.id,
        date=row.date_utc,
        subject=row.subject,
        sender=senders.get(mail_id),
        dkim_status=row.dkim_status,
    )
    recipients = [PersonRef(person_id=pid, email=email, name=display) for pid, email, display in to]
    return mail, recipients


async def _document_ref(session: AsyncSession, document_id: int | None) -> DocumentRef | None:
    if document_id is None:
        return None
    name = await session.scalar(select(Document.name).where(Document.id == document_id))
    return DocumentRef(id=document_id, name=name)


async def container_members(session: AsyncSession, row: Any) -> DocumentMembers | None:
    """A container's entries in its order (D231); None for a document that is no container. row
    has id, kind, members_status and members_error."""
    if row.kind not in CONTAINER_KINDS:
        return None
    entries = await session.execute(
        select(MemberRow, Document.kind, Document.text_status, Document.protection)
        .outerjoin(Document, Document.id == MemberRow.member_id)
        .where(MemberRow.container_id == row.id)
        .order_by(MemberRow.position)
    )
    return DocumentMembers(
        status=row.members_status,
        error=row.members_error,
        entries=[
            DocumentMember(
                position=member.position,
                path=member.path,
                size=member.size_bytes,
                status=member.status,
                error=member.error,
                document_id=member.member_id,
                kind=kind,
                text_status=text_status,
                protection=protection,
            )
            for member, kind, text_status, protection in entries
        ],
    )


async def containers_of(session: AsyncSession, document_id: int) -> list[DocumentContainerRef]:
    """The containers the document was found in, with its path there (D231)."""
    rows = await session.execute(
        select(MemberRow.container_id, Document.name, MemberRow.path)
        .join(Document, Document.id == MemberRow.container_id)
        .where(MemberRow.member_id == document_id)
        .order_by(MemberRow.container_id, MemberRow.position)
    )
    return [
        DocumentContainerRef(document_id=container_id, name=name, path=path)
        for container_id, name, path in rows
    ]


# Passwords typed in by hand -------------------------------------------------------------------


@router.post("/documents/{document_id}/password")
async def try_password(
    document_id: DocumentId,
    body: PasswordTry,
    session: Session,
    settings: AppSettings,
    editor: Editor,
) -> PasswordTryResult:
    row = (
        await session.execute(
            select(*_TRIED_COLUMNS, Document.protection, Document.members_status).where(
                Document.id == document_id
            )
        )
    ).one_or_none()
    if row is None:
        raise api_error(404, "not_found", f"no document with id {document_id}")
    if row.protection != DocumentProtection.LOCKED or not password_trial(row):
        raise api_error(409, "not_locked", f"document {document_id} is not locked")
    return await _try(session, settings, editor, body.password.strip(), [row])


@router.post("/documents/passwords")
async def try_password_everywhere(
    body: PasswordTry, session: Session, settings: AppSettings, editor: Editor
) -> PasswordTryResult:
    rows = await session.execute(
        select(*_TRIED_COLUMNS, Document.members_status).where(*_LOCKED).order_by(Document.id)
    )
    documents = [row for row in rows if password_trial(row)]
    return await _try(session, settings, editor, body.password.strip(), documents)


async def _try(
    session: AsyncSession,
    settings: Settings,
    editor: str | None,
    value: str,
    documents: Sequence[Any],
) -> PasswordTryResult:
    """Keep the password as the editor's finding and try it on the documents (D237)."""
    ids = await store_findings(session, [Finding(value, editor=editor)])
    password_id = ids[value]
    finding_id = await session.scalar(
        select(FindingRow.id).where(
            FindingRow.password_id == password_id,
            FindingRow.mail_id.is_(None),
            FindingRow.document_id.is_(None),
        )
    )
    sources = await document_sources(session, [row.id for row in documents])
    await session.commit()  # reading and trying may be slow: hold no connection meanwhile
    limits = ExtractionLimits(
        timeout=settings.attachment_text_timeout, memory=int(settings.attachment_text_memory)
    )
    opener = Opener(password_id, finding_id, PasswordTier.TYPED, found_by=editor)
    gate = asyncio.Semaphore(max(1, settings.preview_workers))
    writing = asyncio.Lock()  # one session: its writes one after another
    opened: list[int] = []
    errors = 0

    async def one(row: Any) -> None:
        nonlocal errors
        source = sources.get(row.id)
        if source is None:  # its attachments were deleted since
            errors += 1
            return
        async with gate:
            try:
                data = await asyncio.to_thread(read_attachment, settings.mbox_dir, source)
            except (OSError, AttachmentChanged) as error:
                log.warning("document %d could not be read to open it: %s", row.id, describe(error))
                errors += 1
                return
            tried = await try_passwords(
                data,
                row.name,
                row.mime_type,
                [value],
                seconds=settings.password_seconds,
                limits=limits,
            )
        if tried.error is not None:
            log.warning("document %d: trying a typed-in password: %s", row.id, tried.error)
            errors += 1
        async with writing:
            await record_tried(session, row.id, 0, tried.tried)
            if tried.index is not None:
                await store_opened(session, row.id, opener, tried.extraction)
                opened.append(row.id)
            await session.commit()

    await asyncio.gather(*(one(row) for row in documents))
    if opened:
        log.info("a typed-in password opened %d of %d documents", len(opened), len(documents))
    return PasswordTryResult(tried=len(documents), opened=sorted(opened), errors=errors)

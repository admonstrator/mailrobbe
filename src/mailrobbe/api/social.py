"""One mail as a picture for social media (D214 to D217), and a transcribed recording with the
mail it came with (D298): the PNG and what it blacks out.

Routes: GET /api/mails/{id}/social(.png) and GET /api/documents/{id}/social(.png). Registered
before the detail router, so they stay with this module, as the PDF of one mail stays with
exports.py.

Both answers of a kind come from the same plan (social.render.plan, plan_transcript), so the
figures the dialog shows belong to the picture it previews. The image is drawn for the request
and stored nowhere; what it can hold is what the plan holds, every name in it blacked out before
anything is drawn.
"""

import asyncio
import math
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import select

from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.detail import MailId, stored_message
from mailrobbe.api.documents import DocumentId, transcript_of
from mailrobbe.api.schemas import (
    SocialCard,
    SocialParams,
    SocialRedaction,
    TranscriptSocialParams,
)
from mailrobbe.db.models import Attachment, Document
from mailrobbe.export import records
from mailrobbe.social.model import CardOptions, RedactionKind
from mailrobbe.social.render import CardPlan, draw, plan, plan_transcript

router = APIRouter(prefix="/api", tags=["social"])


@router.get("/mails/{mail_id}/social")
async def social_card(
    mail_id: MailId,
    params: Annotated[SocialParams, Query()],
    session: Session,
    settings: AppSettings,
) -> SocialCard:
    """What the image of these parameters shows and what it blacks out (D217)."""
    return _card(await _plan(mail_id, params, session, settings))


@router.get(
    "/mails/{mail_id}/social.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def social_png(
    mail_id: MailId,
    params: Annotated[SocialParams, Query()],
    session: Session,
    settings: AppSettings,
) -> Response:
    """The picture itself; 409 like the body views when its source is missing or changed."""
    prepared = await _plan(mail_id, params, session, settings)
    return await _png(prepared, f"mailrobbe-{mail_id}-social.png")


@router.get("/documents/{document_id}/social")
async def transcript_card(
    document_id: DocumentId,
    params: Annotated[TranscriptSocialParams, Query()],
    session: Session,
) -> SocialCard:
    """What the picture of a transcribed recording shows and what it blacks out (D298)."""
    return _card(await _transcript_plan(document_id, params, session))


@router.get(
    "/documents/{document_id}/social.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def transcript_png(
    document_id: DocumentId,
    params: Annotated[TranscriptSocialParams, Query()],
    session: Session,
) -> Response:
    """The picture of a transcribed recording; it reads no MBOX file, only the database."""
    prepared = await _transcript_plan(document_id, params, session)
    return await _png(prepared, f"mailrobbe-dokument-{document_id}-social.png")


def options(params: SocialParams) -> CardOptions:
    """The parameters of a request as the renderer takes them."""
    return CardOptions(
        shape=params.shape,
        participants=params.participants,
        contacts=params.contacts,
        names=params.names,
        organizations=params.organizations,
        terms=tuple(params.terms),
        quotes=params.quotes,
        dkim=params.dkim,
        checksum=params.checksum,
    )


def _card(prepared: CardPlan) -> SocialCard:
    return SocialCard(
        width=prepared.width,
        height=prepared.height,
        places=prepared.redaction.places,
        redactions=[
            SocialRedaction(kind=kind, places=prepared.redaction.counts[kind])
            for kind in RedactionKind
            if prepared.redaction.counts.get(kind)
        ],
        lines=len(prepared.body),
        truncated=prepared.truncated,
    )


async def _png(prepared: CardPlan, filename: str) -> Response:
    png = await asyncio.to_thread(draw, prepared)
    return Response(
        png,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


async def _plan(
    mail_id: int, params: SocialParams, session: Session, settings: AppSettings
) -> CardPlan:
    mail = await records.by_id(session, mail_id)
    if mail is None:
        raise api_error(404, "not_found", f"no mail with id {mail_id}")
    message = await stored_message(session, settings, mail_id)
    return await asyncio.to_thread(plan, mail, message, options(params))


async def _transcript_plan(
    document_id: int, params: TranscriptSocialParams, session: Session
) -> CardPlan:
    """The card of a document's valid transcript, headed by the mail of the attachment asked
    for, else by the first mail carrying the document (D298). A transcript in which nobody
    speaks has no picture."""
    sha256 = await session.scalar(select(Document.sha256).where(Document.id == document_id))
    transcript = await transcript_of(session, sha256) if sha256 is not None else None
    if transcript is None or not transcript.segments:
        raise api_error(404, "not_found", f"document {document_id} has no transcript")
    carrier = select(Attachment.mail_id, Attachment.filename, Attachment.size_bytes).where(
        Attachment.document_id == document_id
    )
    if params.attachment is not None:
        carrier = carrier.where(Attachment.id == params.attachment)
    else:
        first = select(Document.first_mail_id).where(Document.id == document_id)
        carrier = carrier.where(Attachment.mail_id == first.scalar_subquery())
    found = (await session.execute(carrier.order_by(Attachment.id).limit(1))).first()
    mail = await records.by_id(session, found.mail_id) if found is not None else None
    if found is None or mail is None:
        raise api_error(404, "not_found", f"no mail carries document {document_id} as asked")
    excerpt = None
    if params.start is not None or params.end is not None:
        excerpt = (params.start or 0.0, params.end if params.end is not None else math.inf)
    return await asyncio.to_thread(
        plan_transcript,
        mail,
        found.filename,
        found.size_bytes,
        transcript.result.duration,
        transcript.segments,
        options(params),
        excerpt,
    )

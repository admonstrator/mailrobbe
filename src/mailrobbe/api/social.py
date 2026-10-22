"""One mail as a picture for social media (D214 to D217): the PNG and what it blacks out.

Routes: GET /api/mails/{id}/social, GET /api/mails/{id}/social.png. Registered before the
detail router, so both stay with this module, as the PDF of one mail stays with exports.py.

Both answers come from the same plan (social.render.plan), so the figures the dialog shows
belong to the picture it previews. The image is drawn for the request and stored nowhere; what
it can hold is what the plan holds, every name in it blacked out before anything is drawn.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response

from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.detail import MailId, stored_message
from mailrobbe.api.schemas import SocialCard, SocialParams, SocialRedaction
from mailrobbe.export import records
from mailrobbe.social.model import CardOptions, RedactionKind
from mailrobbe.social.render import CardPlan, draw, plan

router = APIRouter(prefix="/api", tags=["social"])


@router.get("/mails/{mail_id}/social")
async def social_card(
    mail_id: MailId,
    params: Annotated[SocialParams, Query()],
    session: Session,
    settings: AppSettings,
) -> SocialCard:
    """What the image of these parameters shows and what it blacks out (D217)."""
    prepared = await _plan(mail_id, params, session, settings)
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
    png = await asyncio.to_thread(draw, prepared)
    return Response(
        png,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="mailrobbe-{mail_id}-social.png"'},
    )


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


async def _plan(
    mail_id: int, params: SocialParams, session: Session, settings: AppSettings
) -> CardPlan:
    mail = await records.by_id(session, mail_id)
    if mail is None:
        raise api_error(404, "not_found", f"no mail with id {mail_id}")
    message = await stored_message(session, settings, mail_id)
    return await asyncio.to_thread(plan, mail, message, options(params))

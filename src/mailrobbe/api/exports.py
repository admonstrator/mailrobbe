"""Exports of mails for lawyers and archives (milestone 8, D62, D63): the PDF of one mail, and
ZIP exports of a selection with EML, PDF and manifest, recorded in mail_export.

Routes: POST/GET /api/exports, GET /api/exports/{id}/download, GET /api/mails/{id}/pdf.
Registered before the detail router, so /api/mails/{id}/pdf stays with this module.

An export stores the SHA-256 of its mails in export order (oldest first), byte-identical copies
once; its download reads them anew from the archive (mailrobbe.export.bundle).
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

import fastapi
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.detail import MailId, stored_message
from mailrobbe.api.schemas import EXPORT_LIMIT, EXPORTS_LISTED, ExportInfo, ExportRequest
from mailrobbe.api.selection import resolve_selection
from mailrobbe.db.models import MailExport
from mailrobbe.export import records
from mailrobbe.export.bundle import folder_name, stream_export
from mailrobbe.export.pdf import render_pdf

router = APIRouter(prefix="/api", tags=["exports"])

ExportId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]


@router.post("/exports", status_code=201)
async def create_export(
    request: ExportRequest, session: Session, settings: AppSettings, editor: Editor
) -> ExportInfo:
    mails = await resolve_selection(session, settings, request, EXPORT_LIMIT)
    export = MailExport(
        label=request.label.strip(),
        selection=request.model_dump(mode="json", include={"ids", "filters"}, exclude_unset=True),
        include_research=request.include_research,
        mail_sha256=list(dict.fromkeys(mail.raw_sha256 for mail in mails)),
        created_by=editor,
    )
    session.add(export)
    await session.flush()
    await session.refresh(export)  # created_at from the database's clock
    await session.commit()
    return _info(export)


@router.get("/exports")
async def list_exports(session: Session) -> list[ExportInfo]:
    exports = await session.scalars(
        select(MailExport).order_by(MailExport.id.desc()).limit(EXPORTS_LISTED)
    )
    return [_info(export) for export in exports]


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: ExportId, request: Request, session: Session, settings: AppSettings
) -> StreamingResponse:
    export = await session.get(MailExport, export_id)
    if export is None:
        raise api_error(404, "not_found", f"no export with id {export_id}")
    await session.commit()  # the stream reads with sessions of its own
    return StreamingResponse(
        stream_export(request.app.state.sessionmaker, settings, export),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder_name(export_id)}.zip"'},
    )


@router.get("/mails/{mail_id}/pdf")
async def mail_pdf(
    mail_id: MailId,
    session: Session,
    settings: AppSettings,
    research: Annotated[bool, Query()] = False,
) -> Response:
    """The PDF of the export (D63) for one mail, dated now; 409 like the body views when its
    source is missing or changed."""
    mail = await records.by_id(session, mail_id)
    if mail is None:
        raise api_error(404, "not_found", f"no mail with id {mail_id}")
    notes = None
    if research:
        notes = (await records.research(session, [mail.raw_sha256]))[mail.raw_sha256]
    message = await stored_message(session, settings, mail_id)
    pdf = await asyncio.to_thread(
        render_pdf, mail, message, created_at=datetime.now(UTC), research=notes
    )
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="mailrobbe-{mail_id}.pdf"'},
    )


def _info(export: MailExport) -> ExportInfo:
    return ExportInfo(
        id=export.id,
        label=export.label,
        mails=len(export.mail_sha256),
        include_research=export.include_research,
        created_by=export.created_by,
        created_at=export.created_at,
        manifest_sha256=export.manifest_sha256,
        downloaded_at=export.downloaded_at,
        download_url=f"/api/exports/{export.id}/download",
    )

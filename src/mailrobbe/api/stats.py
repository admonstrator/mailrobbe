"""Whole-archive figures and the MBOX file list: GET /api/stats, /api/stats/sender-domains,
/api/mbox-files (D19).

importer.running tells whether an import run is alive (D47: its process holds the import lock),
not whether some file has status running, which stays so after a crash until the next scan.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import aggregates, jobs
from mailrobbe.api.deps import AppSettings, Session
from mailrobbe.api.filters import internal_domains
from mailrobbe.api.query import DKIM_KEYS
from mailrobbe.api.schemas import TOP_SENDER_DOMAINS, DomainCount, ImportState, MboxFileInfo, Stats
from mailrobbe.db.models import MboxFile
from mailrobbe.enums import JobKind

router = APIRouter(prefix="/api", tags=["stats"])

MAX_SENDER_DOMAINS = 2000  # limit of /api/stats/sender-domains

_IMPORT_STATE = text("""
    SELECT count(*), count(*) FILTER (WHERE status = 'done'),
           COALESCE(sum(bytes_done), 0), COALESCE(sum(size_bytes), 0)
    FROM mbox_file
""")


@router.get("/stats")
async def stats(session: Session, settings: AppSettings) -> Stats:
    figures = await aggregates.current_global_stats(session, settings.stats_max_age)
    top = await aggregates.read_sender_domains(session, limit=TOP_SENDER_DOMAINS)
    files, done, bytes_done, size = (await session.execute(_IMPORT_STATE)).one()
    return Stats(
        mails=figures.mails,
        persons=figures.persons,
        domains=figures.domains,
        date_min=figures.date_min,
        date_max=figures.date_max,
        dkim={key: figures.dkim.get(key, 0) for key in DKIM_KEYS},
        sender_domains=[DomainCount(domain=domain, mails=mails) for domain, mails in top],
        sender_domain_count=figures.sender_domain_count,
        mbox_files=figures.mbox_files,
        internal_domains=internal_domains(settings.internal_domains),
        importer=ImportState(
            running=await jobs.job_alive(session, JobKind.IMPORT),
            files_total=files,
            files_done=done,
            progress=min(1.0, bytes_done / size) if size else 1.0,
        ),
        updated_at=figures.updated_at,
    )


@router.get("/stats/sender-domains")
async def sender_domains(
    session: Session,
    settings: AppSettings,
    q: str = "",
    limit: Annotated[int, Query(ge=1, le=MAX_SENDER_DOMAINS)] = 100,
) -> list[DomainCount]:
    await aggregates.current_global_stats(session, settings.stats_max_age)
    domains = await aggregates.read_sender_domains(session, q, limit)
    return [DomainCount(domain=domain, mails=mails) for domain, mails in domains]


@router.get("/mbox-files")
async def mbox_files(session: Session) -> list[MboxFileInfo]:
    return await read_mbox_files(session)


async def read_mbox_files(session: AsyncSession) -> list[MboxFileInfo]:
    """Every mbox_file row by path, also for /api/import/status."""
    files = await session.scalars(select(MboxFile).order_by(MboxFile.path.collate("C")))
    return [
        MboxFileInfo(
            id=file.id,
            path=file.path,
            size_bytes=file.size_bytes,
            status=file.status,
            mails_parsed=file.mails_parsed,
            bytes_done=file.bytes_done,
            error_count=file.error_count,
            worker_id=file.worker_id,
            started_at=file.started_at,
            finished_at=file.finished_at,
        )
        for file in files
    ]

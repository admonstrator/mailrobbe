"""The import dashboard (SPEC 5.5, D46 to D50): GET /api/import/status, /api/import/summary,
/api/import/errors; POST /api/import/start, /api/import/pause, /api/import/rescan,
/api/dkim/recheck, /api/dkim/recheck/stop.

The status is polled every 2 s while a run is alive (D48), so it reads mbox_file and the latest
job rows only, never mail. A run is alive while its process holds the advisory lock of its kind
(jobs.job_alive); a row still running without it belongs to a process that died, and may have
left a statement running in the database (JobInfo.leftover, D113).

Starting a run starts a child process (processes.py) and answers with the job row it recorded;
one run at a time, of either kind. Pausing and stopping set job.stop_requested, which the run
reads every 2 s, so they work for runs started on a command line too.

Every POST takes a JSON body (pause and stop take {}) declared as application/json. A page on
another site can make the browser post forms, text or a body without a content type here, with
the Basic Auth credentials the browser has cached, but not JSON without asking the server first.
"""

import asyncio
import base64
import binascii
import logging
import os
from typing import Annotated, Any, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from mailrobbe import aggregates, jobs
from mailrobbe.api import processes
from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.query import DKIM_KEYS
from mailrobbe.api.schemas import (
    DkimJob,
    DkimKeysJob,
    DkimPhase,
    DkimRecheckRequest,
    FailReasonCount,
    FileProblem,
    ImportErrorItem,
    ImportErrorPage,
    ImportErrorParams,
    ImportJob,
    ImportPhase,
    ImportStartRequest,
    ImportStatus,
    ImportSummary,
    ImportTotals,
    MboxFileInfo,
    ScanResult,
)
from mailrobbe.api.stats import read_mbox_files
from mailrobbe.config import Settings
from mailrobbe.db.models import ImportErrorRecord, Job, MboxFile
from mailrobbe.dkim.keys.model import DkimKeysOptions, DkimKeysPhase, DkimKeysProgress
from mailrobbe.dkim.resolver import parse_nameservers
from mailrobbe.enums import (
    DkimReason,
    DnsStatus,
    DocumentTextStatus,
    ImportErrorKind,
    JobKind,
    JobStatus,
    MboxStatus,
)
from mailrobbe.graph.excerpt import edge_table
from mailrobbe.importer import scan
from mailrobbe.jobs import DkimOptions, DkimProgress, ImportOptions, ImportProgress

log = logging.getLogger(__name__)


def _json_only(request: Request) -> None:
    """415 unless the body is declared as JSON: FastAPI also reads a body without a content type
    as JSON, and a browser sends that across sites without asking first."""
    media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(415, "the request body must be JSON (Content-Type: application/json)")


def _runs(request: Request) -> processes.Runs:
    runs: processes.Runs = request.app.state.runs
    return runs


def _engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


router = APIRouter(prefix="/api", tags=["import"])
# The settings of a start from the dashboard that the next start takes over (D49).
DEFAULT_KEYS = ("workers", "attachment_hash_limit", "dkim_nameservers")
JSON_BODY = [Depends(_json_only)]
Runs = Annotated[processes.Runs, Depends(_runs)]
Engine = Annotated[AsyncEngine, Depends(_engine)]


class NoOptions(BaseModel):
    """The body of pause and stop: {}."""


# Status ----------------------------------------------------------------------------------------


@router.get("/import/status")
async def import_status(session: Session, settings: AppSettings) -> ImportStatus:
    files = await read_mbox_files(session)
    import_row = await jobs.latest_job(session, JobKind.IMPORT)
    dkim_row = await jobs.latest_job(session, JobKind.DKIM)
    keys_row = await jobs.latest_job(session, JobKind.DKIM_KEYS)
    return ImportStatus(
        mbox_dir=str(settings.mbox_dir),
        mbox_dir_ok=_mbox_dir_ok(settings),
        totals=_totals(files),
        files=files,
        import_job=None if import_row is None else await _import_job(session, settings, import_row),
        dkim_job=None if dkim_row is None else await _dkim_job(session, settings, dkim_row),
        keys_job=None if keys_row is None else await _keys_job(session, settings, keys_row),
        defaults=_defaults(settings, import_row),
    )


def _mbox_dir_ok(settings: Settings) -> bool:
    return settings.mbox_dir.is_dir() and os.access(settings.mbox_dir, os.R_OK | os.X_OK)


def _totals(files: list[MboxFileInfo]) -> ImportTotals:
    """Sums over the rows just read, so they always match the file table."""
    statuses = {status: sum(file.status is status for file in files) for status in MboxStatus}
    size_bytes = sum(file.size_bytes for file in files)
    bytes_done = sum(file.bytes_done for file in files)
    mails_parsed = sum(file.mails_parsed for file in files)
    if files and statuses[MboxStatus.DONE] == len(files):
        estimated: int | None = mails_parsed
    elif bytes_done > 0:
        estimated = round(mails_parsed * size_bytes / bytes_done)
    else:
        estimated = None
    return ImportTotals(
        files=len(files),
        done=statuses[MboxStatus.DONE],
        running=statuses[MboxStatus.RUNNING],
        pending=statuses[MboxStatus.PENDING],
        paused=statuses[MboxStatus.PAUSED],
        error=statuses[MboxStatus.ERROR],
        size_bytes=size_bytes,
        bytes_done=bytes_done,
        mails_parsed=mails_parsed,
        mails_estimated=estimated,
        error_count=sum(file.error_count for file in files),
    )


def _defaults(settings: Settings, latest: Job | None) -> ImportOptions:
    """What a start from the dashboard uses (D49): the DEFAULT_KEYS of the latest import run,
    the rest from the server's settings, which a start passes on."""
    options = ImportOptions.from_settings(settings)
    stored = None if latest is None else _valid(ImportOptions, latest.options)
    if stored is None:
        return options
    return options.model_copy(update={key: getattr(stored, key) for key in DEFAULT_KEYS})


async def _import_job(session: AsyncSession, settings: Settings, job: Job) -> ImportJob:
    return ImportJob.model_validate(
        await _job_fields(session, job)
        | {
            "phase": job.phase if job.phase in get_args(ImportPhase) else None,
            "options": _valid(ImportOptions, job.options) or ImportOptions.from_settings(settings),
            "progress": _valid(ImportProgress, job.progress) or ImportProgress(),
        }
    )


async def _dkim_job(session: AsyncSession, settings: Settings, job: Job) -> DkimJob:
    options = _valid(DkimOptions, job.options) or DkimOptions(
        # what `mailrobbe dkim` selects without flags (D13)
        statuses=list(DkimRecheckRequest.model_validate({}).statuses),
        workers=settings.import_workers,
        offline=settings.dkim_offline,
    )
    return DkimJob.model_validate(
        await _job_fields(session, job)
        | {
            "phase": job.phase if job.phase in get_args(DkimPhase) else None,
            "options": options,
            "progress": _valid(DkimProgress, job.progress) or DkimProgress(),
        }
    )


async def _keys_job(session: AsyncSession, settings: Settings, job: Job) -> DkimKeysJob:
    """A dkim-keys run as the dashboard shows it (D101)."""
    options = _valid(DkimKeysOptions, job.options) or DkimKeysOptions(
        task="reconstruct", workers=settings.import_workers
    )
    return DkimKeysJob.model_validate(
        await _job_fields(session, job)
        | {
            "phase": job.phase if job.phase in get_args(DkimKeysPhase) else None,
            "options": options,
            "progress": _valid(DkimKeysProgress, job.progress) or DkimKeysProgress(),
        }
    )


async def _job_fields(session: AsyncSession, job: Job) -> dict[str, Any]:
    alive = job.status is JobStatus.RUNNING and await jobs.job_alive(session, job.kind)
    orphaned = job.status is JobStatus.RUNNING and not alive
    now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    return {
        "id": job.id,
        "kind": job.kind,
        "origin": job.origin,
        "status": job.status,
        "alive": alive,
        "stop_requested": job.stop_requested,
        "started_at": job.started_at,
        "updated_at": job.updated_at,
        "report_age_seconds": max(0.0, (now - job.updated_at).total_seconds()),
        "finished_at": job.finished_at,
        "message": job.message,
        "leftover": await jobs.db_activity(session, job.kind) if orphaned else None,
    }


def _valid[Model: BaseModel](model: type[Model], value: object) -> Model | None:
    """The stored JSON as the model; None for a row written in another shape, so the dashboard
    shows defaults instead of failing."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        log.warning("job row does not match %s: %s", model.__name__, error)
        return None


# Summary ---------------------------------------------------------------------------------------

_SIZES = text("""
    SELECT pg_database_size(current_database()) AS db_size,
           (SELECT COALESCE(sum(size_bytes), 0) FROM mbox_file) AS raw_size,
           pg_relation_size('ix_mail_tsv') AS fulltext_size,
           (SELECT count(*) FROM alias_suggestion WHERE tier = 'certain') AS suggestions
""")
_DNS_CACHE = text("SELECT status::text, count(*) FROM dns_cache GROUP BY status")
# Live, both cheap: attachment rows by an index-only scan, documents by ix_document_text_status.
_ATTACHMENTS = text("SELECT count(*) FROM attachment")
_DOCUMENTS = text("SELECT text_status::text, count(*) FROM document GROUP BY text_status")


@router.get("/import/summary")
async def import_summary(session: Session, settings: AppSettings) -> ImportSummary:
    figures = await aggregates.current_global_stats(session, settings.stats_max_age)
    sizes = (await session.execute(_SIZES)).one()
    dns_cache = {status: 0 for status in DnsStatus}
    for status, count in await session.execute(_DNS_CACHE):
        dns_cache[DnsStatus(status)] = count
    signatures, cached = figures.dkim_signatures, figures.dkim_signatures_cached
    return ImportSummary(
        db_size_bytes=sizes.db_size,
        raw_size_bytes=sizes.raw_size,
        fulltext_index_bytes=sizes.fulltext_size,
        dns_cache=dns_cache,
        dns_hit_ratio=cached / signatures if signatures else None,
        persons=figures.persons,
        open_suggestions=sizes.suggestions,  # certain ones (D160); dismissed pairs are never stored
        edge_table=await edge_table(session),
        duplicates=figures.duplicates,
        dkim={key: figures.dkim.get(key, 0) for key in DKIM_KEYS},
        fail_reasons=[
            FailReasonCount(reason=DkimReason(reason), mails=mails)
            for reason, mails in figures.dkim_fail_reasons.items()
        ],
        updated_at=figures.updated_at,
        attachments=await session.scalar(_ATTACHMENTS) or 0,
        documents=await _documents(session),
    )


async def _documents(session: AsyncSession) -> dict[DocumentTextStatus, int]:
    """Documents by text status, every status present (D72)."""
    documents = dict.fromkeys(DocumentTextStatus, 0)
    for status, count in await session.execute(_DOCUMENTS):
        documents[DocumentTextStatus(status)] = count
    return documents


# Errors ----------------------------------------------------------------------------------------

_CURSOR_PREFIX = "error:"


@router.get("/import/errors")
async def import_errors(
    params: Annotated[ImportErrorParams, Query()], session: Session
) -> ImportErrorPage:
    error = ImportErrorRecord
    filters: list[ColumnElement[bool]] = []
    if params.kind is not None:
        filters.append(error.kind == params.kind.value)
    if params.mbox_file is not None:
        filters.append(error.mbox_file_id == params.mbox_file)
    after = [] if params.cursor is None else [error.id < _decode_cursor(params.cursor)]
    found = list(
        await session.execute(
            select(error, MboxFile.path)
            .outerjoin(MboxFile, MboxFile.id == error.mbox_file_id)
            .where(*filters, *after)
            .order_by(error.id.desc())
            .limit(params.limit + 1)
        )
    )
    more = len(found) > params.limit
    del found[params.limit :]
    total = await session.scalar(select(func.count()).select_from(error).where(*filters))
    count = func.count().label("count")
    kinds = await session.execute(
        select(error.kind, count).group_by(error.kind).order_by(count.desc(), error.kind)
    )
    return ImportErrorPage(
        items=[
            ImportErrorItem(
                id=row.id,
                mbox_file_id=row.mbox_file_id,
                path=path,
                byte_offset=row.byte_offset,
                kind=ImportErrorKind(row.kind),
                message=row.message,
                created_at=row.created_at,
            )
            for row, path in found
        ],
        next_cursor=_encode_cursor(found[-1][0].id) if more else None,
        total=total or 0,
        kinds={ImportErrorKind(kind): number for kind, number in kinds},
    )


def _encode_cursor(error_id: int) -> str:
    return base64.urlsafe_b64encode(f"{_CURSOR_PREFIX}{error_id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> int:
    """The id of the last error of the previous page; 400 invalid_cursor for anything else."""
    try:
        decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        if not decoded.startswith(_CURSOR_PREFIX):
            raise ValueError(decoded)
        return int(decoded.removeprefix(_CURSOR_PREFIX))
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise api_error(400, "invalid_cursor", "malformed cursor") from error


# Starting and stopping runs --------------------------------------------------------------------


@router.post("/import/start", status_code=202, dependencies=JSON_BODY)
async def start_import(
    start: ImportStartRequest, session: Session, settings: AppSettings, runs: Runs
) -> ImportJob:
    defaults = _defaults(settings, await jobs.latest_job(session, JobKind.IMPORT))
    nameservers = defaults.dkim_nameservers
    if start.dkim_nameservers is not None:
        try:
            nameservers = ", ".join(parse_nameservers(start.dkim_nameservers))
        except ValueError as error:
            raise api_error(400, "invalid_option", str(error)) from error
    hash_limit = defaults.attachment_hash_limit
    if start.attachment_hash_limit is not None:
        hash_limit = start.attachment_hash_limit
    environment = processes.child_environment(
        settings,
        {
            "MAILROBBE_IMPORT_ATTACHMENT_HASH_LIMIT": str(hash_limit),
            "MAILROBBE_DKIM_NAMESERVERS": nameservers,
        },
    )
    arguments = ["--workers", str(start.workers or defaults.workers)]
    job = await _start(session, settings, runs, JobKind.IMPORT, arguments, environment)
    return await _import_job(session, settings, job)


@router.post("/import/pause", dependencies=JSON_BODY)
async def pause_import(_: NoOptions, session: Session, settings: AppSettings) -> ImportJob:
    return await _import_job(session, settings, await _stop(session, JobKind.IMPORT))


@router.post("/dkim/recheck", status_code=202, dependencies=JSON_BODY)
async def start_dkim(
    recheck: DkimRecheckRequest, session: Session, settings: AppSettings, runs: Runs
) -> DkimJob:
    arguments = ["--status", *dict.fromkeys(recheck.statuses)]
    if recheck.workers is not None:
        arguments += ["--jobs", str(recheck.workers)]
    environment = processes.child_environment(settings)
    job = await _start(session, settings, runs, JobKind.DKIM, arguments, environment)
    return await _dkim_job(session, settings, job)


@router.post("/dkim/recheck/stop", dependencies=JSON_BODY)
async def stop_dkim(_: NoOptions, session: Session, settings: AppSettings) -> DkimJob:
    return await _dkim_job(session, settings, await _stop(session, JobKind.DKIM))


async def _start(
    session: AsyncSession,
    settings: Settings,
    runs: processes.Runs,
    kind: JobKind,
    arguments: list[str],
    environment: dict[str, str],
) -> Job:
    """Start a run unless one of either kind is alive or starting; its job row."""
    _require_mbox_dir(settings)
    if runs.lock.locked() or runs.children:
        raise api_error(409, "job_running", "a run started from the dashboard has not ended")
    async with runs.lock:
        for other in JobKind:
            if await jobs.job_alive(session, other):
                raise api_error(409, "job_running", f"a mailrobbe {other} run is alive")
        try:
            job_id = await runs.start(session, kind, arguments, environment)
        except processes.StartFailed as error:
            raise api_error(500, "job_failed", str(error)) from error
    job = await session.get(Job, job_id, populate_existing=True)
    assert job is not None
    return job


async def _stop(session: AsyncSession, kind: JobKind) -> Job:
    """Ask the live run of this kind to stop; its job row, or 409 no_job."""
    job_id = None
    if await jobs.job_alive(session, kind):
        job_id = await jobs.request_stop(session, kind)
    if job_id is None:
        raise api_error(409, "no_job", f"no mailrobbe {kind} run is alive")
    await session.commit()
    job = await session.get(Job, job_id, populate_existing=True)
    assert job is not None
    return job


def _require_mbox_dir(settings: Settings) -> None:
    if not _mbox_dir_ok(settings):
        raise api_error(409, "mbox_dir_missing", f"{settings.mbox_dir} is no readable directory")


# Rescan ----------------------------------------------------------------------------------------


@router.post("/import/rescan", dependencies=JSON_BODY)
async def rescan(
    _: NoOptions, session: Session, settings: AppSettings, runs: Runs, engine: Engine
) -> ScanResult:
    """The importer's scan (D14, D50) under the import lock, so no import runs meanwhile."""
    _require_mbox_dir(settings)
    if runs.lock.locked():
        raise api_error(409, "job_running", "a run is starting or a rescan is under way")
    async with runs.lock, engine.connect() as connection:
        locked = await connection.scalar(select(func.pg_try_advisory_lock(jobs.IMPORT_LOCK_KEY)))
        await connection.commit()  # the lock belongs to the connection, not to the transaction
        if not locked:
            raise api_error(409, "job_running", "a mailrobbe import run is alive")
        try:
            # Reading the first MiB of every file may take seconds on a slow mount.
            found = await asyncio.to_thread(scan.find_mbox_files, settings.mbox_dir)
            report = await scan.scan(session, settings.mbox_dir, found)
        finally:
            await connection.execute(select(func.pg_advisory_unlock(jobs.IMPORT_LOCK_KEY)))
            await connection.commit()
    return ScanResult(
        files=len(report.files),
        pending=len(report.pending),
        new=list(report.new),
        replaced=[FileProblem(path=path, reason=reason) for path, reason in report.replaced],
        missing=list(report.missing),
        unreadable=[FileProblem(path=path, reason=reason) for path, reason in report.unreadable],
    )

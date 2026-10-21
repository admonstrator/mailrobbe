"""Runs of the importer and the DKIM check, as the import dashboard sees them (D46, D47).

Every `mailrobbe import` and `mailrobbe dkim` run holds the advisory lock of its kind for its
whole length (a session lock on a connection it keeps open) and records itself in `job`:

    begin_job    right after taking the lock: marks earlier rows of the kind that never
                 recorded their end as failed, then inserts the running row
    report_job   every REPORT_SECONDS: phase and live figures; returns whether a stop was
                 requested, so a run reads the dashboard's request on the same round trip
    end_job      done, stopped or failed, with a one-line message

The API reads the rows (latest_job), asks a run to stop (request_stop) and tells a live run from
one whose process died without recording its end (job_alive: is the kind's lock held?).

job.options and job.progress hold the models below as JSON; the API serves them as they are.
All functions run in the caller's transaction and never commit.
"""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.config import Settings
from mailrobbe.db.models import Job
from mailrobbe.enums import JobKind, JobOrigin, JobStatus

Executor = AsyncSession | AsyncConnection

REPORT_SECONDS = 2.0  # how often a run reports its figures and reads a stop request
RATE_WINDOW = 60.0  # seconds the throughput figures average over

# Session-level advisory locks held by a run from start to end: one run per kind at a time.
IMPORT_LOCK_KEY = int.from_bytes(b"mailrobb", "big")
DKIM_LOCK_KEY = int.from_bytes(b"mrdkimrn", "big")
# A dkim-keys run checks mails again at its end, so it shares the DKIM lock (D101).
LOCK_KEYS: dict[JobKind, int] = {
    JobKind.IMPORT: IMPORT_LOCK_KEY,
    JobKind.DKIM: DKIM_LOCK_KEY,
    JobKind.DKIM_KEYS: DKIM_LOCK_KEY,
}

# The phases a run goes through, in order (job.phase).
ImportPhase = Literal["scan", "headers", "import", "finalize", "attachments"]
DkimPhase = Literal["check", "aggregates"]

LOST_MESSAGE = "the run ended without recording its end"


class ImportOptions(BaseModel):
    """What an import run works with (job.options of kind import)."""

    workers: int
    attachment_hash_limit: int  # bytes; larger attachments get no SHA-256
    max_mail_size: int  # bytes; larger mails are imported with their headers only
    dkim_nameservers: str  # comma-separated IP addresses; empty: the system resolver
    dkim_offline: bool
    mbox_dir: str
    # Text extraction (D72); defaults for the rows of runs from before milestone 9.
    text_max_size: int = 50 * 1024**2  # bytes; larger documents are not read
    text_timeout: float = 60.0  # seconds per document

    @classmethod
    def from_settings(cls, settings: Settings, workers: int | None = None) -> "ImportOptions":
        """The options of a run with these settings; workers defaults to import_workers."""
        return cls(
            workers=workers or max(1, settings.import_workers),
            attachment_hash_limit=int(settings.import_attachment_hash_limit),
            max_mail_size=int(settings.import_max_mail_size),
            dkim_nameservers=settings.dkim_nameservers,
            dkim_offline=settings.dkim_offline,
            mbox_dir=str(settings.mbox_dir),
            text_max_size=int(settings.attachment_text_max_size),
            text_timeout=settings.attachment_text_timeout,
        )


class ImportProgress(BaseModel):
    """Live figures of an import run (job.progress of kind import)."""

    workers: int = 0  # worker processes importing a file right now
    files_queued: int = 0  # files this run set out to import (pending after its scan)
    files_finished: int = 0  # of those, the ones that ended (done, paused or error)
    mails_imported: int = 0  # mails this run stored
    bytes_imported: int = 0  # MBOX bytes this run stored
    mails_per_second: float = 0.0  # over the last RATE_WINDOW seconds
    dkim_per_second: float = 0.0  # mails checked for DKIM per second, same window
    bytes_per_second: float = 0.0  # same window
    eta_seconds: float | None = None  # bytes left in the queued files / bytes_per_second
    headers_total: int = 0  # phase headers: mails whose headers are read again (D52)
    headers_done: int = 0
    documents_total: int = 0  # phase attachments: documents whose text this run extracts (D72)
    documents_done: int = 0  # of those, the ones stored (with or without text)
    documents_per_second: float = 0.0  # over the last RATE_WINDOW seconds


class DkimOptions(BaseModel):
    """What a DKIM run checks (job.options of kind dkim)."""

    statuses: list[str] | None  # DKIM keys selected, "unchecked" for NULL; None: every mail
    mail_ids: list[int] = []  # when set, exactly these mails, whatever their status
    workers: int
    offline: bool


class DkimProgress(BaseModel):
    """Live figures of a DKIM run (job.progress of kind dkim)."""

    workers: int = 0
    selected: int = 0  # mails selected when the run started
    checked: int = 0
    skipped: int = 0  # file missing, unreadable or changed
    mails_per_second: float = 0.0  # checked and skipped, over the last RATE_WINDOW seconds
    eta_seconds: float | None = None


async def begin_job(
    db: Executor,
    kind: JobKind,
    origin: JobOrigin,
    options: BaseModel,
    phase: str | None = None,
) -> int:
    """Record a run that has just taken the lock of its kind; returns its job id.

    Holding the lock means no other run of the kind, or of a kind sharing its lock, is alive, so
    rows still running belong to runs that died (killed, out of memory, container stopped) and
    are marked failed.
    """
    sharing = [other for other, key in LOCK_KEYS.items() if key == LOCK_KEYS[kind]]
    await db.execute(
        update(Job)
        .where(Job.kind.in_(sharing), Job.status == JobStatus.RUNNING)
        .values(status=JobStatus.FAILED, message=LOST_MESSAGE, finished_at=Job.updated_at)
    )
    job_id = await db.scalar(
        postgresql.insert(Job)
        .values(
            kind=kind, origin=origin.value, phase=phase, options=options.model_dump(mode="json")
        )
        .returning(Job.id)
    )
    assert job_id is not None
    return int(job_id)


async def report_job(
    db: Executor,
    job_id: int,
    *,
    phase: str | None = None,
    progress: BaseModel | None = None,
) -> bool:
    """Store the run's phase and figures (each only when given); returns stop_requested."""
    values: dict[str, object] = {"updated_at": func.now()}
    if phase is not None:
        values["phase"] = phase
    if progress is not None:
        values["progress"] = progress.model_dump(mode="json")
    stop = await db.scalar(
        update(Job).where(Job.id == job_id).values(values).returning(Job.stop_requested)
    )
    return bool(stop)


async def end_job(
    db: Executor,
    job_id: int,
    status: JobStatus,
    *,
    message: str | None = None,
    progress: BaseModel | None = None,
) -> None:
    """Record how the run ended; status is done, stopped or failed."""
    assert status is not JobStatus.RUNNING
    values: dict[str, object] = {
        "status": status,
        "message": message,
        "updated_at": func.now(),
        "finished_at": func.now(),
    }
    if progress is not None:
        values["progress"] = progress.model_dump(mode="json")
    await db.execute(update(Job).where(Job.id == job_id).values(values))


async def request_stop(db: Executor, kind: JobKind) -> int | None:
    """Ask the running job of this kind to stop; its id, or None when no row is running.

    The run reads the request at its next report and ends as after Ctrl-C: an import stores
    the batches it holds and pauses its files, a DKIM run commits the chunks it finished.
    """
    return await db.scalar(
        update(Job)
        .where(
            Job.id == select(func.max(Job.id)).where(Job.kind == kind).scalar_subquery(),
            Job.status == JobStatus.RUNNING,
        )
        .values(stop_requested=True)
        .returning(Job.id)
    )


async def latest_job(db: Executor, kind: JobKind) -> Job | None:
    """The newest run of this kind, running or ended; None before the first one."""
    result = await db.execute(select(Job).where(Job.kind == kind).order_by(Job.id.desc()).limit(1))
    return result.scalar_one_or_none()


# A bigint advisory key shows in pg_locks as its high half in classid and its low half in objid,
# with objsubid 1. pg_locks lists the locks of every database on the server.
_LOCK_HELD = text("""
    SELECT EXISTS (
        SELECT 1 FROM pg_locks
        WHERE locktype = 'advisory' AND granted AND objsubid = 1
          AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
          AND classid::bigint = :high AND objid::bigint = :low
    )
""")


async def job_alive(db: Executor, kind: JobKind) -> bool:
    """Whether a run of this kind holds its lock in this database, i.e. its process lives."""
    key = LOCK_KEYS[kind]
    held = await db.scalar(_LOCK_HELD, {"high": key >> 32, "low": key & 0xFFFFFFFF})
    return bool(held)

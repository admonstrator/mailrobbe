"""Runs of the importer, the DKIM check and the key runs, as the import dashboard sees them (D46,
D47, D101).

Every run holds the advisory lock of its kind for its whole length (a session lock on a
connection it keeps open; dkim-keys shares the DKIM lock) and records itself in `job`:

    begin_job    right after taking the lock: marks earlier rows of the kind that never
                 recorded their end as failed, then inserts the running row
    report_job   every REPORT_SECONDS: phase and live figures; returns whether a stop was
                 requested, so a run reads the dashboard's request on the same round trip
    end_job      done, stopped or failed, with a one-line message

The API reads the rows (latest_job), asks a run to stop (request_stop) and tells a live run from
one whose process died without recording its end (job_alive: is the kind's lock held?).

job.options and job.progress hold the models below as JSON; the API serves them as they are.
Every progress lists the run's steps (StepProgress, D110): the phases and the parts of the
finalize, each waiting, running or ended, with its counter, elapsed time, rate and the remaining
time they imply, and what the database does for the run (DbActivity). jobrun.Steps fills them.
All functions run in the caller's transaction and never commit.
"""

import os
from datetime import datetime
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

StepStatus = Literal["waiting", "running", "done", "stopped", "skipped", "failed"]
StepUnit = Literal["bytes", "mails", "documents", "names", "domains"]  # what done and total count


class StepProgress(BaseModel):
    """One step of a run (D110), in the order the run goes through them."""

    key: str  # English name, e.g. "edges"; the dashboard has a German label for each
    # waiting: still to come; stopped: left on a stop request before its counter reached its
    # total; skipped: nothing to do in this run; failed: it raised, and the run with it
    status: StepStatus = "waiting"
    unit: StepUnit | None = None  # None: the step does not count its work
    done: int = 0
    total: int | None = None  # None: not known
    started_at: datetime | None = None
    seconds: float = 0.0  # in the step: so far while it runs, in all once it ended
    rate: float | None = None  # units per second over the last RATE_WINDOW s, while it runs
    eta_seconds: float | None = None  # an estimate while it runs: (total - done) / rate


class DbActivity(BaseModel):
    """The run's longest running statement, from pg_stat_activity (D111)."""

    seconds: float  # since it started
    # pg_stat_activity.wait_event_type: None while it computes, "IO" while it reads or writes,
    # "Lock" while it waits for a lock another session holds
    wait: str | None = None


class RunProgress(BaseModel):
    """What every run reports beside its own figures."""

    steps: list[StepProgress] = []
    database: DbActivity | None = None  # None: no statement of the run is running


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


class ImportProgress(RunProgress):
    """Live figures of an import run (job.progress of kind import); the counters of the headers
    and attachments phases are their steps'."""

    workers: int = 0  # worker processes importing a file right now
    files_queued: int = 0  # files this run set out to import (pending after its scan)
    files_finished: int = 0  # of those, the ones that ended (done, paused or error)
    mails_imported: int = 0  # mails this run stored
    bytes_imported: int = 0  # MBOX bytes this run stored
    mails_per_second: float = 0.0  # over the last RATE_WINDOW seconds
    dkim_per_second: float = 0.0  # mails checked for DKIM per second, same window
    bytes_per_second: float = 0.0  # same window
    eta_seconds: float | None = None  # bytes left in the queued files / bytes_per_second


class DkimOptions(BaseModel):
    """What a DKIM run checks (job.options of kind dkim)."""

    statuses: list[str] | None  # DKIM keys selected, "unchecked" for NULL; None: every mail
    mail_ids: list[int] = []  # when set, exactly these mails, whatever their status
    workers: int
    offline: bool


class DkimProgress(RunProgress):
    """Live figures of a DKIM run (job.progress of kind dkim)."""

    workers: int = 0
    selected: int = 0  # mails selected when the run started
    checked: int = 0
    skipped: int = 0  # file missing, unreadable or changed
    mails_per_second: float = 0.0  # checked and skipped, over the last RATE_WINDOW seconds
    eta_seconds: float | None = None


def lock_sharers(kind: JobKind) -> list[JobKind]:
    """The kinds whose runs hold the same lock as runs of this kind, this kind included."""
    return [other for other, key in LOCK_KEYS.items() if key == LOCK_KEYS[kind]]


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
    await db.execute(
        update(Job)
        .where(Job.kind.in_(lock_sharers(kind)), Job.status == JobStatus.RUNNING)
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


# What the database does for a run (D111, D113). A run names its connections after its kind and
# process (application_name), so its statements show in pg_stat_activity even after the process
# died: a statement keeps running on the server until it would send its result to the client that
# left.
_ACTIVITY = """
    SELECT extract(epoch FROM clock_timestamp() - query_start)::float8, wait_event_type
    FROM pg_stat_activity
    WHERE datname = current_database() AND pid <> pg_backend_pid() AND state = 'active'
      AND {sessions}
    ORDER BY query_start LIMIT 1
"""
_RUN_ACTIVITY = text(_ACTIVITY.format(sessions="application_name = :name"))
_KIND_ACTIVITY = text(_ACTIVITY.format(sessions="starts_with(application_name, :prefix)"))
_LEFTOVERS = text("""
    SELECT pid FROM pg_stat_activity
    WHERE datname = current_database() AND pid <> pg_backend_pid()
      AND starts_with(application_name, :prefix) AND application_name <> :name
""")
_TERMINATE = text("SELECT pg_terminate_backend(:pid)")


def application_name(kind: JobKind, pid: int | None = None) -> str:
    """The name of the database connections of a run of this kind in this process (or pid)."""
    return f"mailrobbe {kind.value} {os.getpid() if pid is None else pid}"


async def db_activity(db: Executor, kind: JobKind, pid: int | None = None) -> DbActivity | None:
    """The longest running statement of the run in process pid, or of any run of this kind
    (pid None: a run whose process died may have left one)."""
    if pid is None:
        result = await db.execute(_KIND_ACTIVITY, {"prefix": f"mailrobbe {kind.value} "})
    else:
        result = await db.execute(_RUN_ACTIVITY, {"name": application_name(kind, pid)})
    row = result.first()
    return None if row is None else DbActivity(seconds=max(0.0, row[0] or 0.0), wait=row[1])


async def end_leftovers(db: Executor, kind: JobKind) -> int:
    """End the database sessions of runs of this kind in other processes; how many.

    Called by a run holding the kind's lock, so those runs are dead: what their sessions still
    do is rolled back anyway, and would hold the locks the new run needs until then.
    """
    params = {"prefix": f"mailrobbe {kind.value} ", "name": application_name(kind)}
    pids = list(await db.scalars(_LEFTOVERS, params))
    for pid in pids:
        await db.execute(_TERMINATE, {"pid": pid})
    return len(pids)

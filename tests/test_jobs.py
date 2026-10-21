"""The job table helpers (D47): recording runs, stop requests and telling live runs from dead."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from mailrobbe import jobs
from mailrobbe.config import Settings
from mailrobbe.enums import JobKind, JobOrigin, JobStatus
from mailrobbe.jobs import DkimOptions, DkimProgress, ImportOptions, ImportProgress

pytestmark = pytest.mark.db

OPTIONS = ImportOptions(
    workers=4,
    attachment_hash_limit=50 * 1024**2,
    max_mail_size=128 * 1024**2,
    dkim_nameservers="",
    dkim_offline=False,
    mbox_dir="/data/mbox",
)


def test_import_options_from_settings() -> None:
    settings = Settings(
        import_workers=3,
        import_attachment_hash_limit="10MiB",  # type: ignore[arg-type]
        dkim_nameservers="192.0.2.53",
        mbox_dir="/srv/mbox",  # type: ignore[arg-type]
    )
    options = ImportOptions.from_settings(settings)
    assert options.workers == 3
    assert options.attachment_hash_limit == 10 * 1024**2
    assert options.dkim_nameservers == "192.0.2.53"
    assert options.mbox_dir == "/srv/mbox"
    assert ImportOptions.from_settings(settings, workers=7).workers == 7


async def test_a_run_from_begin_to_end(db_session: AsyncSession) -> None:
    job_id = await jobs.begin_job(db_session, JobKind.IMPORT, JobOrigin.CLI, OPTIONS, "scan")
    job = await jobs.latest_job(db_session, JobKind.IMPORT)
    assert job is not None and job.id == job_id
    assert (job.status, job.origin, job.phase) == (JobStatus.RUNNING, "cli", "scan")
    assert ImportOptions.model_validate(job.options) == OPTIONS
    assert ImportProgress.model_validate(job.progress) == ImportProgress()

    progress = ImportProgress(workers=4, mails_imported=10, mails_per_second=12.5)
    stop = await jobs.report_job(db_session, job_id, phase="import", progress=progress)
    assert stop is False
    await db_session.refresh(job)
    assert job.phase == "import"
    assert ImportProgress.model_validate(job.progress) == progress

    assert await jobs.report_job(db_session, job_id) is False  # a heartbeat keeps the rest
    await db_session.refresh(job)
    assert (job.phase, job.progress["mails_imported"]) == ("import", 10)

    await jobs.end_job(db_session, job_id, JobStatus.DONE, message="10 mails")
    await db_session.refresh(job)
    assert (job.status, job.message) == (JobStatus.DONE, "10 mails")
    assert job.finished_at is not None


async def test_stop_request_reaches_the_running_job_only(db_session: AsyncSession) -> None:
    assert await jobs.request_stop(db_session, JobKind.IMPORT) is None
    options = DkimOptions(statuses=["no_key"], workers=2, offline=False)
    dkim_id = await jobs.begin_job(db_session, JobKind.DKIM, JobOrigin.UI, options, "check")
    assert await jobs.request_stop(db_session, JobKind.IMPORT) is None  # other kind

    assert await jobs.request_stop(db_session, JobKind.DKIM) == dkim_id
    assert await jobs.report_job(db_session, dkim_id, progress=DkimProgress(checked=5)) is True

    await jobs.end_job(db_session, dkim_id, JobStatus.STOPPED)
    assert await jobs.request_stop(db_session, JobKind.DKIM) is None  # it has ended


async def test_begin_marks_runs_that_never_ended_as_failed(db_session: AsyncSession) -> None:
    lost = await jobs.begin_job(db_session, JobKind.IMPORT, JobOrigin.UI, OPTIONS)
    other = await jobs.begin_job(db_session, JobKind.DKIM, JobOrigin.CLI, OPTIONS)
    current = await jobs.begin_job(db_session, JobKind.IMPORT, JobOrigin.CLI, OPTIONS)
    rows: dict[int, str] = dict(
        (await db_session.execute(text("SELECT id, status::text FROM job ORDER BY id"))).all()
    )
    assert rows == {lost: "failed", other: "running", current: "running"}
    message = await db_session.scalar(text("SELECT message FROM job WHERE id = :id"), {"id": lost})
    assert message == jobs.LOST_MESSAGE


@pytest.fixture
async def other_connection(migrated_database_url: str) -> AsyncIterator[AsyncConnection]:
    """A second connection to the test database, like a run's process holding its lock."""
    engine = create_async_engine(migrated_database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


async def test_job_alive_sees_the_lock_of_another_connection(
    db_session: AsyncSession, other_connection: AsyncConnection
) -> None:
    assert await jobs.job_alive(db_session, JobKind.IMPORT) is False
    lock = text("SELECT pg_advisory_lock(:key)")
    await other_connection.execute(lock, {"key": jobs.IMPORT_LOCK_KEY})
    await other_connection.commit()
    try:
        assert await jobs.job_alive(db_session, JobKind.IMPORT) is True
        assert await jobs.job_alive(db_session, JobKind.DKIM) is False
    finally:
        await other_connection.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": jobs.IMPORT_LOCK_KEY}
        )
        await other_connection.commit()
    assert await jobs.job_alive(db_session, JobKind.IMPORT) is False


def test_lock_keys_differ_from_the_other_advisory_locks() -> None:
    others = {int.from_bytes(name, "big") for name in (b"mr_edges", b"mrglobal", b"mrperson")}
    assert len(set(jobs.LOCK_KEYS.values())) == len(jobs.LOCK_KEYS)
    assert not others & set(jobs.LOCK_KEYS.values())

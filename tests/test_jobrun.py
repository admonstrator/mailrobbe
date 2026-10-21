"""The run side of jobs (D47): lock, job row, reports, stop requests, signals, rate window."""

import asyncio
import logging
import os
import signal
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from mailrobbe import jobrun, jobs, migrate
from mailrobbe.db.session import create_engine
from mailrobbe.enums import JobKind, JobOrigin, JobStatus
from mailrobbe.jobrun import RateWindow, RunRefused, job_run
from mailrobbe.jobs import DkimOptions, DkimProgress

OPTIONS = DkimOptions(statuses=["no_key"], workers=2, offline=False)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_rates_cover_the_last_window_or_the_time_since_the_start() -> None:
    clock = _Clock()
    window = RateWindow(0, 0, clock=clock)
    clock.now += 2
    assert window.rates(20, 0) == (10.0, 0.0)
    for _ in range(29):  # 10 per second up to 60 s after the start
        clock.now += 2
        mails, _ = window.rates(10 * (clock.now - 1000), 0)
    assert mails == 10.0
    for _ in range(30):  # then 4 per second: after a whole window only that counts
        clock.now += 2
        mails, _ = window.rates(600 + 4 * (clock.now - 1060), 0)
    assert mails == pytest.approx(4.0)
    clock.now += 2  # nothing more: the sample at the window's start had 608
    assert window.rates(840, 0)[0] == pytest.approx((840 - 608) / 60)
    assert RateWindow(5, clock=clock).rates(7) == (0.0,)  # no time passed


async def test_a_second_ctrl_c_aborts_only_when_it_comes_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aborted: list[str] = []
    monkeypatch.setattr(jobrun, "abort", aborted.append)
    stop = asyncio.Event()
    with jobrun.stop_on_signals(stop, "aborted here"):
        os.kill(os.getpid(), signal.SIGINT)
        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.sleep(0.1)
        assert stop.is_set()
        assert not aborted
        await asyncio.sleep(jobrun.REPEAT_SECONDS)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.1)
    assert aborted == ["aborted here"]


async def test_a_run_off_the_main_thread_leaves_the_signals_alone() -> None:
    async def run() -> bool:
        stop = asyncio.Event()
        with jobrun.stop_on_signals(stop, "aborted here"):  # no handler outside the main thread
            return stop.is_set()

    assert await asyncio.to_thread(asyncio.run, run()) is False


# Runs against a database ----------------------------------------------------------------------


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    migrate.upgrade("head", empty_database_url)
    return empty_database_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def other(database_url: str) -> AsyncIterator[AsyncConnection]:
    """A connection of another process: the dashboard, or a second run."""
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


@pytest.fixture(autouse=True)
def quick_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobrun, "REPORT_SECONDS", 0.05)


class _Counter:
    """Figures that count their reports."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, db: AsyncConnection) -> BaseModel:
        self.calls += 1
        return DkimProgress(checked=self.calls)


async def _row(db: AsyncConnection, job_id: int) -> dict[str, Any]:
    row = (await db.execute(text("SELECT * FROM job WHERE id = :id"), {"id": job_id})).one()
    await db.commit()
    return dict(row._mapping)


async def _until(condition: Any, seconds: float = 5.0) -> None:
    async with asyncio.timeout(seconds):
        while not await condition():
            await asyncio.sleep(0.02)


@pytest.mark.db
async def test_a_run_reports_its_figures_and_phases_and_records_its_end(
    engine: AsyncEngine, other: AsyncConnection
) -> None:
    figures = _Counter()
    async with job_run(
        engine, JobKind.DKIM, JobOrigin.UI, OPTIONS, phase="check", figures=figures
    ) as run:
        row = await _row(other, run.job_id)
        assert (row["kind"], row["origin"], row["status"]) == (JobKind.DKIM, "ui", "running")
        assert DkimOptions.model_validate(row["options"]) == OPTIONS
        assert await jobs.job_alive(other, JobKind.DKIM)

        async def reported(times: int) -> bool:
            progress = (await _row(other, run.job_id))["progress"]
            return bool(progress.get("checked", 0) >= times)

        await _until(lambda: reported(3))  # every REPORT_SECONDS
        run.set_phase("aggregates")
        await asyncio.sleep(0.01)  # reported at once, not at the next tick
        assert (await _row(other, run.job_id))["phase"] == "aggregates"
        run.end(JobStatus.DONE, "3 mails")

    row = await _row(other, run.job_id)
    assert (row["status"], row["message"], row["phase"]) == ("done", "3 mails", "aggregates")
    assert row["progress"]["checked"] == figures.calls  # the last figures, taken at the end
    assert row["finished_at"] is not None
    assert not await jobs.job_alive(other, JobKind.DKIM)


@pytest.mark.db
async def test_a_stop_request_sets_the_stop_event(
    engine: AsyncEngine, other: AsyncConnection, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    async with job_run(
        engine, JobKind.IMPORT, JobOrigin.CLI, OPTIONS, phase="scan", figures=_Counter()
    ) as run:
        assert await jobs.request_stop(other, JobKind.IMPORT) == run.job_id
        await other.commit()
        await asyncio.wait_for(run.stop.wait(), 5)
        run.end(JobStatus.STOPPED, "stopped")
    assert (await _row(other, run.job_id))["status"] == "stopped"
    assert "stop requested from the dashboard" in caplog.text


@pytest.mark.db
async def test_a_run_that_raises_ends_failed(engine: AsyncEngine, other: AsyncConnection) -> None:
    with pytest.raises(ValueError):
        async with job_run(
            engine, JobKind.DKIM, JobOrigin.CLI, OPTIONS, phase="check", figures=_Counter()
        ) as run:
            raise ValueError("no luck")
    row = await _row(other, run.job_id)
    assert (row["status"], row["message"]) == ("failed", "ValueError: no luck")


@pytest.mark.db
async def test_a_run_whose_end_cannot_be_recorded_keeps_its_outcome(
    engine: AsyncEngine,
    other: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def gone(*args: Any, **kwargs: Any) -> None:
        raise OSError("connection lost")

    monkeypatch.setattr(jobrun, "end_job", gone)
    async with job_run(
        engine, JobKind.DKIM, JobOrigin.CLI, OPTIONS, phase="check", figures=_Counter()
    ) as run:
        run.end(JobStatus.DONE, "fine")
    assert "cannot record the end of the run: OSError: connection lost" in caplog.text
    assert (await _row(other, run.job_id))["status"] == "running"  # shown as aborted
    assert not await jobs.job_alive(other, JobKind.DKIM)


@pytest.mark.db
@pytest.mark.parametrize(
    ("kind", "message"),
    [
        (JobKind.IMPORT, "another import is running"),
        (JobKind.DKIM, "another DKIM check is running"),
    ],
)
async def test_a_second_run_of_a_kind_is_refused(
    engine: AsyncEngine, other: AsyncConnection, kind: JobKind, message: str
) -> None:
    await other.execute(text("SELECT pg_advisory_lock(:key)"), {"key": jobs.LOCK_KEYS[kind]})
    await other.commit()
    with pytest.raises(RunRefused, match=message):
        async with job_run(engine, kind, JobOrigin.CLI, OPTIONS, phase="x", figures=_Counter()):
            pass
    assert await other.scalar(text("SELECT count(*) FROM job")) == 0


@pytest.mark.db
async def test_an_outdated_schema_is_refused(empty_database_url: str) -> None:
    engine = create_engine(empty_database_url)
    try:
        with pytest.raises(RunRefused, match="schema is at revision none, not at 0008"):
            async with job_run(
                engine, JobKind.DKIM, JobOrigin.CLI, OPTIONS, phase="x", figures=_Counter()
            ):
                pass
    finally:
        await engine.dispose()


async def test_an_unreachable_database_is_refused() -> None:
    engine = create_engine("postgresql+asyncpg://nobody@127.0.0.1:1/none")
    try:
        with pytest.raises(RunRefused, match="cannot connect to the database"):
            async with job_run(
                engine, JobKind.DKIM, JobOrigin.CLI, OPTIONS, phase="x", figures=_Counter()
            ):
                pass
    finally:
        await engine.dispose()

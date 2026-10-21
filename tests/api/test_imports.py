"""The import dashboard's API (D46 to D50): status, summary and errors of the imported archive,
starting, pausing and stopping runs as child processes of the server, rescanning the directory.

Expected figures come from direct SQL. Runs are started with tests/api/fake_run.py in place of
the real commands (processes.CLI), so a test decides how its run behaves; the last two tests
start `mailrobbe import` and `mailrobbe dkim` themselves. Writing tests use their own
copy of the imported database (mutable_database_url) and, for the rescan, of the archive.
"""

import asyncio
import os
import shutil
import signal
import sys
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import func, pool, select
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from mailrobbe import jobs
from mailrobbe.api import imports, processes
from mailrobbe.api.app import create_app
from mailrobbe.api.schemas import MboxFileInfo
from mailrobbe.config import Settings
from mailrobbe.enums import JobKind, JobOrigin, MboxStatus
from mailrobbe.jobs import ImportOptions
from tests.api.conftest import api_settings
from tests.api.fake_run import EXIT_STATUS
from tests.api.test_mails import get, rows
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

FAKE_RUN = Path(__file__).with_name("fake_run.py")
POSTS = (
    "/api/import/start",
    "/api/import/pause",
    "/api/import/rescan",
    "/api/dkim/recheck",
    "/api/dkim/recheck/stop",
)


def fake(monkeypatch: pytest.MonkeyPatch, behaviour: str) -> None:
    """Runs started from now on are fake_run.py with this behaviour."""
    monkeypatch.setattr(processes, "CLI", (sys.executable, str(FAKE_RUN), behaviour))


@dataclass(frozen=True, slots=True)
class Dashboard:
    app: FastAPI
    client: httpx.AsyncClient
    url: str  # its database

    @property
    def runs(self) -> processes.Runs:
        runs: processes.Runs = self.app.state.runs
        return runs


@asynccontextmanager
async def serve(settings: Settings) -> AsyncIterator[Dashboard]:
    """The app with its lifespan, so leaving stops its runs as a server shutdown does."""
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield Dashboard(app, client, settings.database_url)


@pytest.fixture
def settings(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> Settings:
    return api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")


@pytest.fixture
async def dashboard(settings: Settings) -> AsyncIterator[Dashboard]:
    """The dashboard on this test's copy of the imported database, without any job rows."""
    await rows(settings.database_url, "DELETE FROM job")
    async with serve(settings) as dashboard:
        yield dashboard


async def post(client: httpx.AsyncClient, path: str, body: Any, status: int = 200) -> Any:
    response = await client.post(path, json=body)
    assert response.status_code == status, response.text
    return response.json()


async def error_code(client: httpx.AsyncClient, path: str, body: Any, status: int) -> str:
    code: str = (await post(client, path, body, status))["detail"]["code"]
    return code


async def until(condition: Callable[[], Awaitable[bool]], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while not await condition():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.05)


async def reaped(dashboard: Dashboard) -> None:
    """Every child of the dashboard has ended and was awaited."""

    async def none_left() -> bool:
        return not dashboard.runs.children

    await until(none_left)


async def run_ended(dashboard: Dashboard, key: str) -> dict[str, Any]:
    """The latest run of a kind ("import_job", "dkim_job") once it ended and was reaped."""

    async def ended() -> bool:
        job = (await get(dashboard.client, "/api/import/status"))[key]
        return job["status"] != "running" and not dashboard.runs.children

    await until(ended)
    job: dict[str, Any] = (await get(dashboard.client, "/api/import/status"))[key]
    return job


@asynccontextmanager
async def holding(url: str, kind: JobKind) -> AsyncIterator[AsyncConnection]:
    """The advisory lock of a run of this kind, held by another connection meanwhile."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(select(func.pg_advisory_lock(jobs.LOCK_KEYS[kind])))
            await connection.commit()
            yield connection
    finally:
        await engine.dispose()


# Status ----------------------------------------------------------------------------------------


async def test_status_lists_the_files_and_their_sums(
    client: httpx.AsyncClient, imported_database_url: str, generated_archive: GeneratedArchive
) -> None:
    status = await get(client, "/api/import/status")
    assert status["mbox_dir"] == str(generated_archive.mbox_dir)
    assert status["mbox_dir_ok"] is True
    assert status["files"] == await get(client, "/api/mbox-files")
    (sums,) = await rows(
        imported_database_url,
        "SELECT count(*) AS files, count(*) FILTER (WHERE status = 'done') AS done,"
        " sum(size_bytes) AS size_bytes, sum(bytes_done) AS bytes_done,"
        " sum(mails_parsed) AS mails_parsed, sum(error_count) AS error_count FROM mbox_file",
    )
    assert sums.done == sums.files > 1
    assert status["totals"] == {
        "files": sums.files,
        "done": sums.done,
        "running": 0,
        "pending": 0,
        "paused": 0,
        "error": 0,
        "size_bytes": sums.size_bytes,
        "bytes_done": sums.bytes_done,
        "mails_parsed": sums.mails_parsed,
        "mails_estimated": sums.mails_parsed,
        "error_count": sums.error_count,
    }
    assert status["dkim_job"] is None

    # Whatever the importer recorded about itself, the run has ended.
    latest = await rows(
        imported_database_url,
        "SELECT id, status::text AS status, options FROM job WHERE kind = 'import'"
        " ORDER BY id DESC LIMIT 1",
    )
    settings = Settings(mbox_dir=generated_archive.mbox_dir)
    defaults = ImportOptions.from_settings(settings).model_dump()
    if latest:
        job = status["import_job"]
        assert (job["id"], job["status"], job["alive"]) == (latest[0].id, latest[0].status, False)
        defaults |= {key: latest[0].options[key] for key in imports.DEFAULT_KEYS}
    else:
        assert status["import_job"] is None
    assert status["defaults"] == defaults


def file_info(status: MboxStatus, size: int, done: int, mails: int) -> MboxFileInfo:
    return MboxFileInfo(
        id=1,
        path="a",
        size_bytes=size,
        status=status,
        mails_parsed=mails,
        bytes_done=done,
        error_count=2,
        worker_id=None,
        started_at=None,
        finished_at=None,
    )


def test_totals_extrapolate_the_mails_by_the_bytes_done() -> None:
    done = file_info(MboxStatus.DONE, 1000, 1000, 10)
    running = file_info(MboxStatus.RUNNING, 3000, 1000, 12)
    pending = file_info(MboxStatus.PENDING, 4000, 0, 0)
    totals = imports._totals([done, running, pending])
    assert (totals.files, totals.done, totals.running, totals.pending) == (3, 1, 1, 1)
    assert (totals.size_bytes, totals.bytes_done, totals.mails_parsed) == (8000, 2000, 22)
    assert totals.mails_estimated == 88  # 22 mails in 2000 of 8000 bytes
    assert totals.error_count == 6
    assert imports._totals([pending]).mails_estimated is None  # nothing done yet
    assert imports._totals([]).mails_estimated is None
    # Done files are counted as they are, even when their last bytes held no mail.
    assert imports._totals([file_info(MboxStatus.DONE, 1000, 900, 7)]).mails_estimated == 7


async def test_status_shows_the_latest_runs_and_whether_they_live(
    dashboard: Dashboard, settings: Settings
) -> None:
    url = dashboard.url
    options = ImportOptions.from_settings(settings, workers=3).model_copy(
        update={"attachment_hash_limit": 1024, "dkim_nameservers": "192.0.2.1"}
    )
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await jobs.begin_job(connection, JobKind.IMPORT, JobOrigin.CLI, options, "import")
            dkim_options = jobs.DkimOptions(statuses=["no_key"], workers=2, offline=False)
            await jobs.begin_job(connection, JobKind.DKIM, JobOrigin.UI, dkim_options, "check")
            await connection.commit()
    finally:
        await engine.dispose()

    status = await get(dashboard.client, "/api/import/status")
    # Rows still running whose process holds no lock: shown as not alive (aborted).
    assert (status["import_job"]["status"], status["import_job"]["alive"]) == ("running", False)
    assert status["import_job"]["origin"] == "cli"
    assert status["import_job"]["phase"] == "import"
    assert status["import_job"]["options"] == options.model_dump()
    assert status["import_job"]["progress"] == jobs.ImportProgress().model_dump()
    assert status["dkim_job"]["options"] == dkim_options.model_dump()
    assert status["dkim_job"]["alive"] is False
    # The next start from the dashboard uses the run's settings of D49, the rest from the server.
    assert status["defaults"] == ImportOptions.from_settings(settings).model_dump() | {
        "workers": 3,
        "attachment_hash_limit": 1024,
        "dkim_nameservers": "192.0.2.1",
    }

    async with holding(url, JobKind.IMPORT):
        status = await get(dashboard.client, "/api/import/status")
        assert status["import_job"]["alive"] is True
        assert status["dkim_job"]["alive"] is False

    # Rows of another shape do not break the status.
    await rows(
        url,
        'UPDATE job SET options = \'{"workers": "many"}\', progress = \'{"workers": []}\','
        " phase = 'unknown'",
    )
    status = await get(dashboard.client, "/api/import/status")
    assert status["import_job"]["options"] == ImportOptions.from_settings(settings).model_dump()
    assert status["import_job"]["progress"] == jobs.ImportProgress().model_dump()
    assert status["import_job"]["phase"] is None
    assert status["dkim_job"]["options"]["statuses"] == ["unchecked", "no_key", "temp_error"]
    assert status["defaults"] == ImportOptions.from_settings(settings).model_dump()


# Summary ---------------------------------------------------------------------------------------


async def test_summary_has_the_sizes_and_the_aggregated_figures(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    summary = await get(client, "/api/import/summary")
    url = imported_database_url
    (sizes,) = await rows(
        url,
        "SELECT pg_database_size(current_database()) AS db,"
        " (SELECT sum(size_bytes) FROM mbox_file) AS raw,"
        " pg_relation_size('ix_mail_tsv') AS fulltext,"
        " (SELECT count(*) FROM alias_suggestion) AS suggestions,"
        " (SELECT count(*) FROM person WHERE merged_into IS NULL) AS persons,"
        " (SELECT count(*) FROM mail WHERE is_duplicate_of IS NOT NULL) AS duplicates,"
        " (SELECT count(*) FROM edge) AS pairs,"
        " (SELECT count(*) FROM dkim_result) AS signatures,"
        " (SELECT count(*) FROM dkim_result WHERE dns_cached) AS cached",
    )
    dns = {
        row.status: row.count
        for row in await rows(url, "SELECT status::text, count(*) FROM dns_cache GROUP BY 1")
    }
    dkim = {
        row.status: row.count
        for row in await rows(
            url,
            "SELECT COALESCE(dkim_status::text, 'unchecked') AS status, count(*)"
            " FROM mail GROUP BY 1",
        )
    }
    reasons = await rows(
        url,
        "SELECT r.reason, count(DISTINCT r.mail_id) AS mails FROM dkim_result r"
        " JOIN mail m ON m.id = r.mail_id WHERE m.dkim_status = 'fail' AND r.status = 'fail'"
        " GROUP BY r.reason ORDER BY mails DESC, r.reason",
    )
    assert summary["db_size_bytes"] == pytest.approx(sizes.db, rel=0.01)
    assert summary["raw_size_bytes"] == sizes.raw
    assert summary["fulltext_index_bytes"] == sizes.fulltext > 0
    assert summary["dns_cache"] == {
        key: dns.get(key, 0) for key in ("found", "not_found", "temp_error")
    }
    assert sizes.signatures > 0
    assert summary["dns_hit_ratio"] == pytest.approx(sizes.cached / sizes.signatures)
    assert summary["persons"] == sizes.persons
    assert summary["open_suggestions"] == sizes.suggestions
    assert summary["edge_table"]["pairs"] == sizes.pairs > 0
    assert summary["duplicates"] == sizes.duplicates > 0
    assert summary["dkim"] == {key: dkim.get(key, 0) for key in summary["dkim"]}
    assert len(summary["dkim"]) == 7
    assert summary["fail_reasons"] == [{"reason": r.reason, "mails": r.mails} for r in reasons]
    assert reasons
    assert summary["updated_at"] is not None


async def test_summary_without_signatures_has_no_hit_ratio(dashboard: Dashboard) -> None:
    await rows(dashboard.url, "DELETE FROM dkim_result")
    await rows(dashboard.url, "UPDATE global_stats SET updated_at = now() - interval '1 hour'")
    summary = await get(dashboard.client, "/api/import/summary")
    assert summary["dns_hit_ratio"] is None
    assert summary["fail_reasons"] == []


# Errors ----------------------------------------------------------------------------------------


async def error_pages(client: httpx.AsyncClient, params: list[tuple[str, str]]) -> list[Any]:
    """Every page, following next_cursor."""
    found: list[Any] = []
    cursor = None
    while True:
        page = await get(
            client, "/api/import/errors", [*params, *([("cursor", cursor)] if cursor else [])]
        )
        found.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return found


async def test_errors_page_newest_first(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    expected = await rows(
        imported_database_url,
        "SELECT e.id, e.mbox_file_id, f.path, e.byte_offset, e.kind, e.message, e.created_at"
        " FROM import_error e LEFT JOIN mbox_file f ON f.id = e.mbox_file_id ORDER BY e.id DESC",
    )
    assert len(expected) > 20
    pages = await error_pages(client, [("limit", "7")])
    assert [len(page["items"]) for page in pages[:-1]] == [7] * (len(pages) - 1)
    items = [item for page in pages for item in page["items"]]
    for item in items:
        item["created_at"] = datetime.fromisoformat(item["created_at"])
    assert items == [dict(row._mapping) for row in expected]
    kinds = Counter(row.kind for row in expected)
    assert all(page["total"] == len(expected) for page in pages)
    assert all(page["kinds"] == dict(kinds) for page in pages)
    first = await get(client, "/api/import/errors")
    assert len(first["items"]) == min(50, len(expected))


async def test_errors_filter_by_kind_and_file(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    every = await rows(imported_database_url, "SELECT id, kind, mbox_file_id FROM import_error")
    kind, _ = Counter(row.kind for row in every).most_common(1)[0]
    file_id = Counter(row.mbox_file_id for row in every if row.kind == kind).most_common(1)[0][0]
    for params, matching in (
        ([("kind", kind)], [row for row in every if row.kind == kind]),
        ([("mbox_file", str(file_id))], [row for row in every if row.mbox_file_id == file_id]),
        (
            [("kind", kind), ("mbox_file", str(file_id))],
            [row for row in every if row.kind == kind and row.mbox_file_id == file_id],
        ),
    ):
        pages = await error_pages(client, [*params, ("limit", "5")])
        ids = [item["id"] for page in pages for item in page["items"]]
        assert ids == sorted((row.id for row in matching), reverse=True)
        assert pages[0]["total"] == len(matching)
        assert pages[0]["kinds"] == dict(Counter(row.kind for row in every))  # unfiltered
    await get(client, "/api/import/errors", [("kind", "nonsense")], status=422)


@pytest.mark.parametrize(
    "cursor", ["x", "ZXJyb3I6YWJj", "Zm9vOjE", "%%%", imports._encode_cursor(5)[:-2] + "!!"]
)
async def test_an_unusable_error_cursor_is_refused(client: httpx.AsyncClient, cursor: str) -> None:
    page = await get(client, "/api/import/errors", [("cursor", cursor)], status=400)
    assert page["detail"]["code"] == "invalid_cursor"


# Starting and stopping runs --------------------------------------------------------------------


def test_the_environment_of_a_run_carries_every_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@db/x",
        mbox_dir=Path("/srv/mbox"),
        import_workers=3,
        import_attachment_hash_limit="10MiB",  # type: ignore[arg-type]
        dkim_offline=True,
        dkim_dns_timeout=2.5,
        basic_auth_user="aaron",
        basic_auth_password=SecretStr("geheim"),
    )
    monkeypatch.setenv("MAILROBBE_DKIM_DNS_OVERRIDE", "/somewhere/else.json")
    monkeypatch.setenv("MAILROBBE_DATABASE_URL", "postgresql+asyncpg://other")
    monkeypatch.setenv("UNRELATED", "kept")
    environment = processes.child_environment(settings, {"MAILROBBE_DKIM_NAMESERVERS": "192.0.2.1"})
    assert environment["MAILROBBE_DATABASE_URL"] == "postgresql+asyncpg://u:p@db/x"
    assert environment["MAILROBBE_IMPORT_ATTACHMENT_HASH_LIMIT"] == str(10 * 1024**2)
    assert environment["MAILROBBE_BASIC_AUTH_PASSWORD"] == "geheim"
    assert environment["MAILROBBE_DKIM_OFFLINE"] == "true"
    assert environment["MAILROBBE_DKIM_NAMESERVERS"] == "192.0.2.1"
    assert "MAILROBBE_DKIM_DNS_OVERRIDE" not in environment  # None: the child's default too
    assert environment["UNRELATED"] == "kept"
    # The child reads back the same settings, apart from the override.
    with monkeypatch.context() as patch:
        for name in [name for name in os.environ if name.startswith("MAILROBBE_")]:
            patch.delenv(name)
        for name, value in environment.items():
            patch.setenv(name, value)
        assert Settings() == settings.model_copy(update={"dkim_nameservers": "192.0.2.1"})


async def test_an_import_started_from_the_dashboard_runs_until_paused(
    dashboard: Dashboard, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    client = dashboard.client
    request = {
        "workers": 3,
        "attachment_hash_limit": 1024,
        "dkim_nameservers": "192.0.2.1 ,2001:db8::1",
    }
    job = await post(client, "/api/import/start", request, status=202)
    assert (job["kind"], job["origin"], job["status"], job["alive"]) == (
        "import",
        "ui",
        "running",
        True,
    )
    assert job["stop_requested"] is False
    # The run got the options as arguments and MAILROBBE_* variables.
    assert job["options"] == ImportOptions.from_settings(settings).model_dump() | {
        "workers": 3,
        "attachment_hash_limit": 1024,
        "dkim_nameservers": "192.0.2.1, 2001:db8::1",
    }
    status = await get(client, "/api/import/status")
    assert status["import_job"] == job | {"updated_at": status["import_job"]["updated_at"]}
    assert (await get(client, "/api/stats"))["importer"]["running"] is True

    # One run at a time, of either kind.
    assert await error_code(client, "/api/import/start", {}, 409) == "job_running"
    assert await error_code(client, "/api/dkim/recheck", {}, 409) == "job_running"
    assert await error_code(client, "/api/dkim/recheck/stop", {}, 409) == "no_job"

    paused = await post(client, "/api/import/pause", {})
    assert (paused["id"], paused["stop_requested"]) == (job["id"], True)
    ended = await run_ended(dashboard, "import_job")
    assert (ended["status"], ended["message"], ended["alive"]) == (
        "stopped",
        "stop requested",
        False,
    )
    assert (await get(client, "/api/stats"))["importer"]["running"] is False
    assert await error_code(client, "/api/import/pause", {}, 409) == "no_job"
    # The next start uses the options of this run (D49).
    assert (await get(client, "/api/import/status"))["defaults"] == job["options"]


async def test_a_start_without_options_uses_the_defaults(
    dashboard: Dashboard, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "done")
    client = dashboard.client
    first = await post(client, "/api/import/start", {}, status=202)
    assert first["options"] == ImportOptions.from_settings(settings).model_dump()
    assert (await run_ended(dashboard, "import_job"))["status"] == "done"

    second = await post(client, "/api/import/start", {"workers": 2, "dkim_nameservers": ""}, 202)
    assert (second["options"]["workers"], second["options"]["dkim_nameservers"]) == (2, "")
    await run_ended(dashboard, "import_job")
    third = await post(client, "/api/import/start", {}, status=202)
    assert third["id"] > second["id"]
    assert third["options"] == second["options"]


async def test_a_dkim_recheck_started_from_the_dashboard_runs_until_stopped(
    dashboard: Dashboard, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    client = dashboard.client
    request = {"statuses": ["no_key", "temp_error", "no_key"], "workers": 2}
    job = await post(client, "/api/dkim/recheck", request, status=202)
    assert (job["kind"], job["origin"], job["alive"]) == ("dkim", "ui", True)
    assert job["options"] == {
        "statuses": ["no_key", "temp_error"],
        "mail_ids": [],
        "workers": 2,
        "offline": False,
    }
    assert await error_code(client, "/api/import/start", {}, 409) == "job_running"
    assert await error_code(client, "/api/import/pause", {}, 409) == "no_job"
    stopping = await post(client, "/api/dkim/recheck/stop", {})
    assert (stopping["id"], stopping["stop_requested"]) == (job["id"], True)
    ended = await run_ended(dashboard, "dkim_job")
    assert (ended["status"], ended["message"]) == ("stopped", "stop requested")

    default = await post(client, "/api/dkim/recheck", {}, status=202)
    assert default["options"]["statuses"] == ["unchecked", "no_key", "temp_error"]
    assert default["options"]["workers"] == settings.import_workers
    await post(client, "/api/dkim/recheck/stop", {})
    await run_ended(dashboard, "dkim_job")
    await post(client, "/api/dkim/recheck", {"statuses": []}, status=422)
    await post(client, "/api/dkim/recheck", {"statuses": ["nonsense"]}, status=422)


@pytest.mark.parametrize("kind", list(JobKind))
async def test_nothing_starts_while_a_run_of_either_kind_is_alive(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch, kind: JobKind
) -> None:
    fake(monkeypatch, "done")
    async with holding(dashboard.url, kind):  # e.g. a run started on a command line
        for path in ("/api/import/start", "/api/dkim/recheck"):
            assert await error_code(dashboard.client, path, {}, 409) == "job_running"
        # It holds the lock but has recorded no row yet: nothing to stop.
        stop = "/api/import/pause" if kind is JobKind.IMPORT else "/api/dkim/recheck/stop"
        assert await error_code(dashboard.client, stop, {}, 409) == "no_job"
    assert dashboard.runs.children == []
    await post(dashboard.client, "/api/import/start", {}, status=202)


async def test_a_run_from_a_command_line_can_be_paused(
    dashboard: Dashboard, settings: Settings
) -> None:
    async with holding(dashboard.url, JobKind.IMPORT) as connection:
        options = ImportOptions.from_settings(settings)
        job_id = await jobs.begin_job(connection, JobKind.IMPORT, JobOrigin.CLI, options, "scan")
        await connection.commit()
        paused = await post(dashboard.client, "/api/import/pause", {})
        assert (paused["id"], paused["origin"], paused["stop_requested"]) == (job_id, "cli", True)
        assert await jobs.report_job(connection, job_id) is True  # what the run reads
        await connection.commit()
    # Its process is gone without recording its end: nothing alive to pause.
    assert await error_code(dashboard.client, "/api/import/pause", {}, 409) == "no_job"


async def test_starting_needs_the_mbox_directory(
    mutable_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake(monkeypatch, "done")
    settings = api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(update={"mbox_dir": tmp_path / "missing"})
    async with serve(settings) as dashboard:
        status = await get(dashboard.client, "/api/import/status")
        assert (status["mbox_dir"], status["mbox_dir_ok"]) == (str(tmp_path / "missing"), False)
        for path in ("/api/import/start", "/api/dkim/recheck", "/api/import/rescan"):
            assert await error_code(dashboard.client, path, {}, 409) == "mbox_dir_missing"
        (tmp_path / "missing").write_text("a file, no directory")
        assert (
            await error_code(dashboard.client, "/api/import/start", {}, 409) == "mbox_dir_missing"
        )
        assert dashboard.runs.children == []


@pytest.mark.parametrize(
    "nameservers", ["192.0.2.1, resolver.example", "1.1.1.1;8.8.8.8", "999.1.1.1"]
)
async def test_nameservers_must_be_ip_addresses(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch, nameservers: str
) -> None:
    fake(monkeypatch, "done")
    request = {"dkim_nameservers": nameservers}
    detail = (await post(dashboard.client, "/api/import/start", request, status=400))["detail"]
    assert detail["code"] == "invalid_option"
    bad = nameservers.split(", ")[-1]
    assert repr(bad) in detail["message"]
    assert dashboard.runs.children == []


async def test_a_run_that_ends_before_recording_itself_fails_the_start(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "exit")
    detail = (await post(dashboard.client, "/api/import/start", {}, status=500))["detail"]
    assert detail["code"] == "job_failed"
    assert f"exit status {EXIT_STATUS}" in detail["message"]
    await reaped(dashboard)
    assert (await get(dashboard.client, "/api/import/status"))["import_job"] is None


async def test_the_real_command_failing_at_once_fails_the_start(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    settings = api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")
    async with serve(settings) as dashboard:
        # The child gets a database that does not exist; the server's own stays usable.
        dashboard.app.state.settings = settings.model_copy(
            update={"database_url": mutable_database_url + "_missing"}
        )
        for path in ("/api/import/start", "/api/dkim/recheck"):
            detail = (await post(dashboard.client, path, {}, status=500))["detail"]
            assert detail["code"] == "job_failed"
            assert "exit status" in detail["message"]
            await reaped(dashboard)


async def test_a_run_that_never_records_itself_is_left_running_until_shutdown(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "silent")
    monkeypatch.setattr(processes, "START_TIMEOUT", 1.0)
    async with serve(settings) as dashboard:
        detail = (await post(dashboard.client, "/api/import/start", {}, status=500))["detail"]
        assert detail["code"] == "job_failed"
        assert "has not recorded its run" in detail["message"]
        (child,) = dashboard.runs.children
        assert child.returncode is None
        # Still starting, as far as the dashboard can tell.
        assert await error_code(dashboard.client, "/api/dkim/recheck", {}, 409) == "job_running"
    assert child.returncode == 0  # SIGTERM at shutdown
    assert dashboard.runs.children == []


async def test_shutdown_stops_the_runs_it_started(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    async with serve(settings) as dashboard:
        job = await post(dashboard.client, "/api/import/start", {}, status=202)
        (child,) = dashboard.runs.children
    assert child.returncode == 0
    with pytest.raises(ProcessLookupError):  # reaped, not a zombie
        os.kill(child.pid, 0)
    (row,) = await rows(
        settings.database_url, f"SELECT status::text, message FROM job WHERE id = {job['id']}"
    )
    assert (row.status, row.message) == ("stopped", "SIGTERM")


async def test_shutdown_kills_runs_that_ignore_sigterm(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "stubborn")
    monkeypatch.setattr(processes, "STOP_TIMEOUT", 1.0)
    async with serve(settings) as dashboard:
        await post(dashboard.client, "/api/import/start", {}, status=202)
        (child,) = dashboard.runs.children
    assert child.returncode == -signal.SIGKILL
    with pytest.raises(ProcessLookupError):
        os.kill(child.pid, 0)
    async with serve(settings) as dashboard:

        async def aborted() -> bool:
            job = (await get(dashboard.client, "/api/import/status"))["import_job"]
            return (job["status"], job["alive"]) == ("running", False)

        await until(aborted)  # once the database noticed the lost connection


@pytest.mark.parametrize("path", POSTS)
async def test_posts_take_only_json(dashboard: Dashboard, path: str) -> None:
    client = dashboard.client
    for headers, content in (
        ({"Content-Type": "text/plain"}, b"{}"),
        ({"Content-Type": "application/x-www-form-urlencoded"}, b"workers=2"),
        ({"Content-Type": "multipart/form-data; boundary=x"}, b"--x--"),
        ({}, b"{}"),  # no content type: FastAPI would read it as JSON
    ):
        response = await client.post(path, headers=headers, content=content)
        assert response.status_code in (415, 422), (headers, response.text)
    response = await client.post(path, headers={"Content-Type": "application/json"})
    assert response.status_code == 422  # no body at all
    assert dashboard.runs.children == []


# Rescan ----------------------------------------------------------------------------------------


@pytest.fixture
async def archive_copy(
    settings: Settings, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[Dashboard]:
    """The dashboard on a copy of the archive, which the test may change."""
    shutil.copytree(generated_archive.mbox_dir, tmp_path / "mbox")
    async with serve(settings.model_copy(update={"mbox_dir": tmp_path / "mbox"})) as dashboard:
        yield dashboard


async def test_rescan_reports_what_changed_on_disk(archive_copy: Dashboard, tmp_path: Path) -> None:
    client, url, mbox_dir = archive_copy.client, archive_copy.url, tmp_path / "mbox"
    files = sorted(file["path"] for file in await get(client, "/api/mbox-files"))
    assert len(files) >= 3
    assert await post(client, "/api/import/rescan", {}) == {
        "files": len(files),
        "pending": 0,
        "new": [],
        "replaced": [],
        "missing": [],
        "unreadable": [],
    }

    gone, changed, copied = files[0], files[1], files[2]
    (mbox_dir / gone).unlink()
    with (mbox_dir / changed).open("r+b") as handle:  # still an MBOX file, another one
        handle.seek(200)
        handle.write(b"X")
    shutil.copy(mbox_dir / copied, mbox_dir / "zz-new.mbox")
    (mbox_dir / os.fsdecode(b"\xff.mbox")).write_bytes(b"From x\n")
    (changed_id,) = [
        row.id for row in await rows(url, f"SELECT id FROM mbox_file WHERE path = '{changed}'")
    ]

    result = await post(client, "/api/import/rescan", {})
    assert result == {
        "files": len(files),  # one gone, one new
        "pending": 2,
        "new": ["zz-new.mbox"],
        "replaced": [{"path": changed, "reason": "first MiB changed"}],
        "missing": [gone],
        "unreadable": [{"path": "?.mbox", "reason": "name is not UTF-8"}],
    }
    assert await rows(url, f"SELECT id FROM mail WHERE mbox_file_id = {changed_id}") == []
    totals = (await get(client, "/api/import/status"))["totals"]
    assert (totals["files"], totals["pending"]) == (len(files) + 1, 2)


async def test_rescan_waits_for_no_import(archive_copy: Dashboard) -> None:
    async with holding(archive_copy.url, JobKind.IMPORT):
        assert await error_code(archive_copy.client, "/api/import/rescan", {}, 409) == "job_running"
    async with archive_copy.runs.lock:  # a start from the dashboard is under way
        assert await error_code(archive_copy.client, "/api/import/rescan", {}, 409) == "job_running"
    async with holding(archive_copy.url, JobKind.DKIM):  # only an import excludes a rescan
        assert (await post(archive_copy.client, "/api/import/rescan", {}))["pending"] == 0
    # The scan released the lock.
    async with holding(archive_copy.url, JobKind.IMPORT):
        pass


# The real commands, as Aaron's dashboard starts them --------------------------------------------


async def test_the_dashboard_starts_the_real_import(dashboard: Dashboard) -> None:
    job = await post(dashboard.client, "/api/import/start", {"workers": 2}, status=202)
    assert (job["origin"], job["options"]["workers"]) == ("ui", 2)
    ended = await run_ended(dashboard, "import_job")
    assert ended["status"] == "done", ended["message"]
    totals = (await get(dashboard.client, "/api/import/status"))["totals"]
    assert totals["done"] == totals["files"]


async def test_the_dashboard_starts_the_real_dkim_recheck(dashboard: Dashboard) -> None:
    await rows(
        dashboard.url,
        "UPDATE mail SET dkim_status = NULL WHERE id IN (SELECT id FROM mail ORDER BY id LIMIT 5)",
    )
    job = await post(dashboard.client, "/api/dkim/recheck", {"statuses": ["unchecked"]}, 202)
    assert job["options"]["statuses"] == ["unchecked"]
    ended = await run_ended(dashboard, "dkim_job")
    assert ended["status"] == "done", ended["message"]
    assert ended["progress"]["checked"] == 5
    assert await rows(dashboard.url, "SELECT id FROM mail WHERE dkim_status IS NULL") == []

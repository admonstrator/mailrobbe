"""GET /api/stats, /api/stats/sender-domains and /api/mbox-files, and keeping global_stats
current (D19): finalize writes them, `mailrobbe dkim` and the API's lazy refresh renew them.
The import counts as running while a run holds the import lock (D47)."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, pool, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import aggregates, jobs
from mailrobbe.api.schemas import TOP_SENDER_DOMAINS
from mailrobbe.config import Settings
from mailrobbe.dkim.recheck import recheck
from tests.api.conftest import _client, api_settings
from tests.api.test_mails import get, rows
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

SENDER_DOMAINS = (
    "SELECT p.domain, count(DISTINCT pa.mail_id) AS mails FROM participation pa"
    " JOIN person p ON p.id = pa.person_id WHERE pa.role = 'from'"
    " GROUP BY p.domain ORDER BY mails DESC, p.domain"
)


def stamp(value: Any) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


async def test_stats_are_the_figures_of_the_archive(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    url = imported_database_url
    stats = await get(client, "/api/stats")
    figures = (
        await rows(
            url,
            "SELECT count(*) AS mails, min(date_utc) AS date_min, max(date_utc) AS date_max,"
            " (SELECT count(*) FROM person WHERE merged_into IS NULL) AS persons,"
            " (SELECT count(DISTINCT domain) FROM person) AS domains,"
            " (SELECT count(*) FROM mbox_file) AS files,"
            " (SELECT count(*) FROM mbox_file WHERE status = 'done') AS done,"
            " (SELECT sum(bytes_done)::float / sum(size_bytes) FROM mbox_file) AS progress"
            " FROM mail",
        )
    )[0]
    dkim = dict(
        (row.status, row.count)
        for row in await rows(
            url,
            "SELECT COALESCE(dkim_status::text, 'unchecked') AS status, count(*) FROM mail"
            " GROUP BY 1",
        )
    )
    senders = [
        {"domain": row.domain, "mails": row.mails} for row in await rows(url, SENDER_DOMAINS)
    ]
    assert len(senders) > TOP_SENDER_DOMAINS

    assert stats["updated_at"] is not None
    assert {key: value for key, value in stats.items() if key != "updated_at"} == {
        "mails": figures.mails,
        "persons": figures.persons,
        "domains": figures.domains,
        "date_min": stamp(figures.date_min),
        "date_max": stamp(figures.date_max),
        "dkim": {key: dkim.get(key, 0) for key in stats["dkim"]},
        "sender_domains": senders[:TOP_SENDER_DOMAINS],
        "sender_domain_count": len(senders),
        "mbox_files": figures.files,
        "internal_domains": [],
        "importer": {
            "running": False,
            "files_total": figures.files,
            "files_done": figures.done,
            "progress": min(1.0, figures.progress),
        },
        "near": None,  # until an import computed near duplicates (D153)
        "events": {"request": 0, "reply": 0, "cancel": 0},
    }
    assert len(stats["dkim"]) == 7


async def test_sender_domains_search_and_limit(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    senders = [(row.domain, row.mails) for row in await rows(imported_database_url, SENDER_DOMAINS)]
    every = await get(client, "/api/stats/sender-domains", [("limit", "2000")])
    assert [(entry["domain"], entry["mails"]) for entry in every] == senders

    part = senders[0][0].split(".")[0][1:4]
    matching = [entry for entry in senders if part in entry[0]]
    found = await get(client, "/api/stats/sender-domains", [("q", part.upper()), ("limit", "2")])
    assert [(entry["domain"], entry["mails"]) for entry in found] == matching[:2]
    assert len(await get(client, "/api/stats/sender-domains")) == min(100, len(senders))


async def test_stats_name_the_internal_domains(
    imported_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    settings = api_settings(imported_database_url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(update={"internal_domains": " Elbtal.Example ,, other.test"})
    async for client in _client(settings):
        stats = await get(client, "/api/stats")
        assert stats["internal_domains"] == ["elbtal.example", "other.test"]


@pytest.mark.parametrize("limit", ["0", "2001"])
async def test_sender_domains_limit_is_bounded(client: httpx.AsyncClient, limit: str) -> None:
    await get(client, "/api/stats/sender-domains", [("limit", limit)], status=422)


async def test_mbox_files_by_path(client: httpx.AsyncClient, imported_database_url: str) -> None:
    files = await get(client, "/api/mbox-files")
    expected = await rows(
        imported_database_url,
        "SELECT id, path, size_bytes, status::text AS status, mails_parsed, bytes_done,"
        " error_count, worker_id, started_at, finished_at"
        ' FROM mbox_file ORDER BY path COLLATE "C"',
    )
    for file in files:
        for key in ("started_at", "finished_at"):
            file[key] = None if file[key] is None else datetime.fromisoformat(file[key])
    assert files == [dict(row._mapping) for row in expected]
    assert len(files) > 1


async def test_the_importer_runs_while_an_import_holds_its_lock(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    # A file an import left running when it crashed does not count (D47).
    await rows(
        url, "UPDATE mbox_file SET status = 'running' WHERE id = (SELECT min(id) FROM mbox_file)"
    )
    assert (await get(mutable_client, "/api/stats"))["importer"]["running"] is False
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as run:
            await run.execute(select(func.pg_advisory_lock(jobs.IMPORT_LOCK_KEY)))
            await run.commit()
            assert (await get(mutable_client, "/api/stats"))["importer"]["running"] is True
    finally:
        await engine.dispose()
    assert (await get(mutable_client, "/api/stats"))["importer"]["running"] is False


async def _change_archive(url: str) -> int:
    """Marks five mails as not checked; returns the number of unchecked mails."""
    await rows(
        url,
        "UPDATE mail SET dkim_status = NULL WHERE id IN (SELECT id FROM mail ORDER BY id LIMIT 5)",
    )
    return 5


async def _age_global_stats(url: str) -> None:
    await rows(url, "UPDATE global_stats SET updated_at = now() - interval '1 hour'")


async def test_stats_are_refreshed_once_older_than_the_maximum_age(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    before = await get(mutable_client, "/api/stats")
    assert before["dkim"]["unchecked"] == 0
    unchecked = await _change_archive(mutable_database_url)
    assert await get(mutable_client, "/api/stats") == before  # still fresh: stored figures
    summary = await get(mutable_client, "/api/mails/summary")
    assert summary["dkim"]["unchecked"] == 0

    await _age_global_stats(mutable_database_url)
    after = await get(mutable_client, "/api/stats")
    assert after["dkim"]["unchecked"] == unchecked
    assert datetime.fromisoformat(after["updated_at"]) > datetime.fromisoformat(
        before["updated_at"]
    )
    summary = await get(mutable_client, "/api/mails/summary")
    assert summary["dkim"]["unchecked"] == unchecked


async def test_stored_stats_are_served_while_another_refresh_runs(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    before = await get(mutable_client, "/api/stats")
    unchecked = await _change_archive(mutable_database_url)
    await _age_global_stats(mutable_database_url)
    engine = create_async_engine(mutable_database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as other:
            # A refresh elsewhere (finalize, mailrobbe dkim) holds the lock.
            await other.execute(select(func.pg_advisory_lock(aggregates._LOCK_KEY)))
            during = await get(mutable_client, "/api/stats/sender-domains", [("limit", "1")])
            stats = await get(mutable_client, "/api/stats")
            await other.execute(select(func.pg_advisory_unlock(aggregates._LOCK_KEY)))
    finally:
        await engine.dispose()
    assert stats["dkim"] == before["dkim"]  # served without waiting for the lock
    assert during == before["sender_domains"][:1]
    assert (await get(mutable_client, "/api/stats"))["dkim"]["unchecked"] == unchecked


async def test_dkim_recheck_refreshes_global_stats(
    mutable_database_url: str, generated_archive: GeneratedArchive
) -> None:
    url = mutable_database_url
    unchecked = await _change_archive(url)
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await aggregates.refresh_global_stats(connection)
            stored = await aggregates.read_global_stats(connection)
        assert stored is not None and stored.dkim[aggregates.UNCHECKED] == unchecked

        settings = Settings(
            database_url=url,
            mbox_dir=generated_archive.mbox_dir,
            dkim_dns_override=generated_archive.dns_override,
        )
        summary = await asyncio.to_thread(recheck, settings, statuses={None})
        assert summary.checked == unchecked

        async with engine.connect() as connection:
            figures = await aggregates.read_global_stats(connection)
            counts = dict(
                (status or aggregates.UNCHECKED, count)
                for status, count in await connection.execute(
                    text("SELECT dkim_status::text, count(*) FROM mail GROUP BY 1")
                )
            )
    finally:
        await engine.dispose()
    assert figures is not None and figures.updated_at > stored.updated_at
    assert figures.dkim == {key: counts.get(key, 0) for key in figures.dkim}
    assert figures.dkim[aggregates.UNCHECKED] == 0


async def test_import_leaves_current_global_stats(imported_database_url: str) -> None:
    engine = create_async_engine(imported_database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            figures = await aggregates.read_global_stats(connection)
            mails = await connection.scalar(text("SELECT count(*) FROM mail"))
    finally:
        await engine.dispose()
    assert figures is not None and figures.mails == mails

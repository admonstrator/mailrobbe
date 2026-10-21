"""The signals phase of every import (D135), on the generated archive imported
before: "Import starten" fills every signal under the rules of the moment, and a time zone
PostgreSQL does not know fails the run without touching the stored signals."""

from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.config import Settings
from mailrobbe.generator.population import is_freemail
from mailrobbe.importer.cli import run_import
from mailrobbe.jobs import ImportProgress
from mailrobbe.signals.model import NEEDS_INTERNAL, SignalFigures, read_figures, rules
from tests.api.conftest import imported_database_url, mutable_database_url  # noqa: F401
from tests.conftest import GeneratedArchive

pytestmark = [pytest.mark.db, pytest.mark.slow]


async def _rows(url: str, query: str) -> list[tuple[Any, ...]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            return [tuple(row) for row in await connection.execute(text(query))]
    finally:
        await engine.dispose()


async def _figures(url: str) -> SignalFigures | None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            return await read_figures(connection)
    finally:
        await engine.dispose()


async def _settings(url: str, archive: GeneratedArchive, **changes: str) -> Settings:
    """The generated archive's largest domain as internal, its mail providers as private."""
    domains = [domain for (domain,) in await _rows(
        url, "SELECT domain FROM person GROUP BY domain ORDER BY count(*) DESC, domain"
    )]  # fmt: skip
    values = {
        "internal_domains": domains[0],
        "private_domains": ",".join(domain for domain in domains if is_freemail(domain)),
    }
    return Settings(database_url=url, dkim_dns_override=archive.dns_override, **(values | changes))


async def _last_job(url: str) -> dict[str, Any]:
    [(status, phase, message, progress)] = await _rows(
        url, "SELECT status::text, phase, message, progress FROM job ORDER BY id DESC LIMIT 1"
    )
    return {"status": status, "phase": phase, "message": message, "progress": progress}


async def test_starting_the_import_again_fills_every_signal(
    mutable_database_url: str,  # noqa: F811
    generated_archive: GeneratedArchive,
) -> None:
    url = mutable_database_url
    # The archive's own import computed its signals without internal and generated domains.
    before = await _figures(url)
    assert before is not None and before.rules["internal_domains"] == []
    assert all(before.signals[key] == 0 for key in NEEDS_INTERNAL)

    settings = await _settings(url, generated_archive)
    assert await run_import(settings, generated_archive.mbox_dir, 2) == 0
    job = await _last_job(url)
    assert (job["status"], job["phase"]) == ("done", "signals")
    steps = {step.key: step for step in ImportProgress.model_validate(job["progress"]).steps}
    assert steps["import"].status == "skipped"  # nothing new
    assert steps["signals"].status == "done"
    assert steps["signals"].done == steps["signals"].total == len(rules(settings).keys) + 1

    figures = await _figures(url)
    assert figures is not None and figures.rules == rules(settings).snapshot()
    assert figures.computed_at > before.computed_at
    found = {signal for (signal,) in await _rows(url, "SELECT DISTINCT signal FROM mail_signal")}
    # The generated archive has Bcc to private addresses, private aliases and forwards.
    assert found >= {
        "private", "internal_to_private", "private_to_internal", "private_alias", "bcc",
        "forward", "forward_out", "night", "weekend",
    }  # fmt: skip
    assert all(figures.signals[key] > 0 for key in found)
    senders = {
        signal for (signal,) in await _rows(url, "SELECT DISTINCT signal FROM person_signal")
    }
    assert senders >= {"private", "private_alias", "bcc", "forward"}


async def test_an_unknown_time_zone_fails_the_import(
    mutable_database_url: str,  # noqa: F811
    generated_archive: GeneratedArchive,
) -> None:
    url = mutable_database_url
    stored = await _rows(url, 'SELECT * FROM mail_signal ORDER BY signal COLLATE "C", mail_id')
    figures = await _figures(url)
    settings = await _settings(url, generated_archive, timezone="Mars/Olympus")
    assert await run_import(settings, generated_archive.mbox_dir, 2) == 1
    job = await _last_job(url)
    assert (job["status"], job["phase"]) == ("failed", "signals")
    assert job["message"].endswith(
        "; PostgreSQL does not know the time zone 'Mars/Olympus': set MAILROBBE_TIMEZONE to a "
        "name of pg_timezone_names, such as Europe/Berlin"
    )
    steps = {step.key: step for step in ImportProgress.model_validate(job["progress"]).steps}
    assert steps["signals"].status == "failed"
    assert await _rows(url, 'SELECT * FROM mail_signal ORDER BY signal COLLATE "C", mail_id') == (
        stored
    )
    assert await _figures(url) == figures

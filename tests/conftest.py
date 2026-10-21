"""Shared fixtures: PostgreSQL databases and a generated MBOX archive.

Database tests need a PostgreSQL server: MAILROBBE_TEST_DATABASE_URL is an asyncpg URL such as
postgresql+asyncpg://mailrobbe:mailrobbe@127.0.0.1:5432/mailrobbe. Without it they skip, unless
MAILROBBE_REQUIRE_DB=1 (set in CI) turns the skip into a failure. The tests only connect to that
database to create and drop their own ones named mailrobbe_test_<hex>, so it is safe to point the
variable at the compose database.

Alembic's env.py calls asyncio.run, so migrations run in sync fixtures, or in a thread
(asyncio.to_thread) from async tests.
"""

import asyncio
import json
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailrobbe import migrate
from mailrobbe.generator.config import DNS_OVERRIDE_NAME, MANIFEST_NAME, GeneratorConfig
from mailrobbe.generator.pipeline import generate

TEST_DATABASE_URL_ENV = "MAILROBBE_TEST_DATABASE_URL"
REQUIRE_DB_ENV = "MAILROBBE_REQUIRE_DB"


async def _execute_autocommit(server_url: str, statement: str) -> None:
    # CREATE/DROP DATABASE cannot run inside a transaction block.
    engine = create_async_engine(server_url, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@contextmanager
def _temporary_database(server_url: str) -> Iterator[str]:
    name = f"mailrobbe_test_{secrets.token_hex(6)}"
    asyncio.run(_execute_autocommit(server_url, f"CREATE DATABASE {name}"))
    try:
        yield make_url(server_url).set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(_execute_autocommit(server_url, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


@pytest.fixture(scope="session")
def database_server_url() -> str:
    """URL from MAILROBBE_TEST_DATABASE_URL; skips, or fails with MAILROBBE_REQUIRE_DB=1."""
    url = os.environ.get(TEST_DATABASE_URL_ENV)
    if url:
        return url
    reason = f"{TEST_DATABASE_URL_ENV} is not set"
    if os.environ.get(REQUIRE_DB_ENV) == "1":
        pytest.fail(f"{reason}, but {REQUIRE_DB_ENV}=1 requires the database tests", pytrace=False)
    pytest.skip(f"{reason}; database tests need a PostgreSQL server")


@pytest.fixture
def empty_database_url(database_server_url: str) -> Iterator[str]:
    """A fresh database without any schema, created for this test and dropped after it."""
    with _temporary_database(database_server_url) as url:
        yield url


@pytest.fixture(scope="session")
def migrated_database_url(database_server_url: str) -> Iterator[str]:
    """A database migrated to head, created once per test session and dropped at its end.

    Shared by all tests, so they must not change it: write through db_session, which rolls back.
    """
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        yield url


@pytest.fixture
async def db_session(migrated_database_url: str) -> AsyncIterator[AsyncSession]:
    """Session on the migrated database inside a transaction that is rolled back after the test.

    session.commit() only releases a savepoint, so code under test may commit; nothing reaches
    other tests. Expected errors go into `async with session.begin_nested():` to keep the
    transaction usable.
    """
    engine = create_async_engine(migrated_database_url, poolclass=pool.NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class GeneratedArchive:
    """Output of one generator run: the MBOX directory and its manifest (one dict per mail)."""

    mbox_dir: Path
    manifest: list[dict[str, Any]]
    config: GeneratorConfig

    @property
    def dns_override(self) -> Path:
        return self.config.meta_dir / DNS_OVERRIDE_NAME


@pytest.fixture(scope="session")
def generated_archive(tmp_path_factory: pytest.TempPathFactory) -> GeneratedArchive:
    """600 generated mails in several small files, with many faults and duplicates.

    Built once per test session and shared, so tests must not change the files. The manifest
    (data/mbox/_generator/manifest.jsonl format) is the ground truth for every mail.
    """
    out_dir = tmp_path_factory.mktemp("archive") / "mbox"
    config = GeneratorConfig(
        out_dir=out_dir,
        meta_dir=out_dir / "_generator",
        mails=600,
        persons=150,
        domains=20,
        file_size=8 * 1024**2,
        large_attachments=1,
        large_attachment_size=2 * 1024**2,
        fault_rate=0.2,
        duplicate_rate=0.05,
    )
    generate(config)
    lines = (config.meta_dir / MANIFEST_NAME).read_text(encoding="utf-8").splitlines()
    return GeneratedArchive(out_dir, [json.loads(line) for line in lines], config)

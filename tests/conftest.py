"""Database fixtures.

Database tests need a PostgreSQL server: MAILSPIDER_TEST_DATABASE_URL is an asyncpg URL such as
postgresql+asyncpg://mailspider:mailspider@127.0.0.1:5432/mailspider. Without it they skip, unless
MAILSPIDER_REQUIRE_DB=1 (set in CI) turns the skip into a failure. The tests only connect to that
database to create and drop their own ones named mailspider_test_<hex>, so it is safe to point the
variable at the compose database.

Alembic's env.py calls asyncio.run, so migrations run in sync fixtures, or in a thread
(asyncio.to_thread) from async tests.
"""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailspider import migrate

TEST_DATABASE_URL_ENV = "MAILSPIDER_TEST_DATABASE_URL"
REQUIRE_DB_ENV = "MAILSPIDER_REQUIRE_DB"


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
    name = f"mailspider_test_{secrets.token_hex(6)}"
    asyncio.run(_execute_autocommit(server_url, f"CREATE DATABASE {name}"))
    try:
        yield make_url(server_url).set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(_execute_autocommit(server_url, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


@pytest.fixture(scope="session")
def database_server_url() -> str:
    """URL from MAILSPIDER_TEST_DATABASE_URL; skips, or fails with MAILSPIDER_REQUIRE_DB=1."""
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

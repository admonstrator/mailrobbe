"""The engine every command and the API connect with (db/session.py)."""

import pytest
from sqlalchemy import text

from mailrobbe.db.session import create_engine

pytestmark = pytest.mark.db


async def test_connections_run_without_jit(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SHOW jit")) == "off"  # D35
    finally:
        await engine.dispose()

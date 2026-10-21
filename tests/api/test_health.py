import socket
import time

import httpx
import pytest

from mailrobbe.api.app import create_app
from mailrobbe.config import Settings


async def _get_health(database_url: str) -> httpx.Response:
    app = create_app(Settings(database_url=database_url))
    transport = httpx.ASGITransport(app=app)
    # ASGITransport does not run the lifespan; enter it so the engine is disposed afterwards.
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        return await client.get("/api/health")


@pytest.mark.db
async def test_health_reports_schema_revision(migrated_database_url: str) -> None:
    response = await _get_health(migrated_database_url)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "schema_revision": "0008"}


@pytest.mark.db
async def test_health_without_migrations_has_no_revision(empty_database_url: str) -> None:
    response = await _get_health(empty_database_url)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "schema_revision": None}


async def test_health_fails_fast_when_database_is_unreachable() -> None:
    # A bound socket that never listens: connections are refused, and no other process can take
    # the port while the test runs.
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        url = f"postgresql+asyncpg://mailrobbe:x@127.0.0.1:{closed.getsockname()[1]}/mailrobbe"
        started = time.monotonic()
        response = await _get_health(url)
        elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "database": "unavailable",
        "schema_revision": None,
    }
    assert elapsed < 5

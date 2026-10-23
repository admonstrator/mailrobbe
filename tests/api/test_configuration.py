"""The page "Einstellungen" (D313 to D315): GET and PUT /api/settings on a copy of the imported
archive, the server taking a save over at once, and a new server or command reading it."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import stored_settings
from mailrobbe.api import processes
from mailrobbe.api.app import create_app
from mailrobbe.api.deps import EDITOR_HEADER
from mailrobbe.config import Settings
from tests.api.conftest import api_settings
from tests.conftest import GeneratedArchive


@pytest.fixture
def settings(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> Settings:
    """The archive's settings with a time zone from the environment."""
    base = api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")
    return base.model_copy(update={"timezone": "UTC"})


@asynccontextmanager
async def serve(settings: Settings) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield app, client


async def put(client: httpx.AsyncClient, values: dict[str, Any], status: int = 200) -> Any:
    response = await client.put(
        "/api/settings", json={"values": values}, headers={EDITOR_HEADER: "Aaron"}
    )
    assert response.status_code == status, response.text
    return response.json()


def by_name(view: Any) -> dict[str, Any]:
    return {item["name"]: item for item in view["items"]}


async def stored(url: str) -> dict[str, Any]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(text("SELECT name, value FROM setting"))
            return {name: value for name, value in rows}
    finally:
        await engine.dispose()


async def test_the_page_shows_every_setting_but_the_fixed_ones(settings: Settings) -> None:
    async with serve(settings) as (_, client):
        view = (await client.get("/api/settings")).json()
    assert [item["name"] for item in view["items"]] == list(stored_settings.EDITABLE)
    assert view["fixed"] == sorted(stored_settings.FIXED)
    assert {"database_url", "basic_auth_password", "ai_allow_remote"} <= set(view["fixed"])
    items = by_name(view)
    assert items["timezone"] | {"changed_at": None} == {
        "name": "timezone",
        "kind": "text",
        "value": "UTC",
        "base": "UTC",
        "source": "env",
        "secret_set": False,
        "choices": [],
        "minimum": None,
        "maximum": None,
        "changed_at": None,
        "changed_by": None,
    }
    assert (items["block_min_mails"]["source"], items["block_min_mails"]["minimum"]) == (
        "default",
        2,
    )
    assert (items["ai_ocr_uncertain"]["kind"], items["ai_ocr_uncertain"]["maximum"]) == (
        "number",
        100,
    )
    assert items["import_max_mail_size"] | {"name": None} == items["import_max_mail_size"] | {
        "name": None,
        "kind": "bytes",
        "value": 128 * 1024**2,
    }
    assert items["ai_text_protocol"]["choices"] == ["auto", "openai", "ollama"]
    assert items["dkim_offline"]["kind"] == "boolean"
    assert items["ai_text_key"] | {"name": None} == items["ai_text_key"] | {
        "name": None,
        "kind": "secret",
        "value": None,
        "base": None,
        "secret_set": False,
    }


async def test_a_save_holds_at_once_and_a_reset_brings_the_environment_back(
    settings: Settings,
) -> None:
    async with serve(settings) as (app, client):
        view = await put(
            client,
            {"block_min_mails": 7, "ai_text_key": "sk-hidden", "timezone": "Europe/Vienna"},
        )
        items = by_name(view)
        assert (items["block_min_mails"]["value"], items["block_min_mails"]["base"]) == (7, 25)
        assert (items["block_min_mails"]["source"], items["block_min_mails"]["changed_by"]) == (
            "stored",
            "Aaron",
        )
        assert items["block_min_mails"]["changed_at"] is not None
        assert (items["ai_text_key"]["value"], items["ai_text_key"]["secret_set"]) == (None, True)
        assert "sk-hidden" not in (await client.get("/api/settings")).text
        # the server's views and the runs it starts take the new values at once
        assert (await client.get("/api/blocks/summary")).json()["min_mails"] == 7
        environment = processes.child_environment(app.state.settings)
        assert environment["MAILROBBE_BLOCK_MIN_MAILS"] == "7"
        assert environment["MAILROBBE_AI_TEXT_KEY"] == "sk-hidden"
        assert environment["MAILROBBE_TIMEZONE"] == "Europe/Vienna"
        assert await stored(settings.database_url) == {
            "block_min_mails": 7,
            "ai_text_key": "sk-hidden",
            "timezone": "Europe/Vienna",
        }

        items = by_name(await put(client, {"block_min_mails": None, "timezone": None}))
        assert (items["block_min_mails"]["value"], items["block_min_mails"]["source"]) == (
            25,
            "default",
        )
        assert (items["timezone"]["value"], items["timezone"]["source"]) == ("UTC", "env")
        assert (await client.get("/api/blocks/summary")).json()["min_mails"] == 25
        assert await stored(settings.database_url) == {"ai_text_key": "sk-hidden"}


async def test_a_value_like_the_environments_and_sizes_are_stored_plainly(
    settings: Settings,
) -> None:
    async with serve(settings) as (_, client):
        await put(client, {"timezone": "Europe/Berlin", "import_max_mail_size": 64 * 1024**2})
        items = by_name(await put(client, {"timezone": "UTC"}))
    assert (items["timezone"]["source"], items["import_max_mail_size"]["value"]) == (
        "env",
        64 * 1024**2,
    )
    assert await stored(settings.database_url) == {"import_max_mail_size": 64 * 1024**2}


@pytest.mark.parametrize(
    ("values", "name"),
    [
        ({"ai_context_tokens": 100}, "ai_context_tokens"),
        ({"import_workers": "many"}, "import_workers"),
        ({"ai_ocr_engine": "magic"}, "ai_ocr_engine"),
        ({"database_url": "postgresql://elsewhere"}, "database_url"),
        ({"ai_allow_remote": True}, "ai_allow_remote"),
        ({"no_such_setting": 1}, "no_such_setting"),
        ({"timezone": "Mars/Olympus"}, "timezone"),
        ({"dkim_nameservers": "dns.example"}, "dkim_nameservers"),
        ({"map_source": "ftp://tiles.example/planet.pmtiles"}, "map_source"),
        ({"ai_text_url": "localhost:1234"}, "ai_text_url"),
        ({"dkim_key_archive_url": ""}, "dkim_key_archive_url"),
        ({"ai_ocr_languages": " "}, "ai_ocr_languages"),
    ],
)
async def test_a_value_not_taken_stores_nothing(
    settings: Settings, values: dict[str, Any], name: str
) -> None:
    async with serve(settings) as (app, client):
        response = await put(client, {"block_min_mails": 7, **values}, status=400)
        assert response["detail"]["code"] == "invalid_setting"
        assert response["detail"]["message"].startswith(f"{name}: ")
        assert app.state.settings.block_min_mails == 25
    assert await stored(settings.database_url) == {}


async def test_switching_off_and_empty_values_are_taken(settings: Settings) -> None:
    values = {"dkim_key_archive_url": "off", "map_source": "off", "ai_text_url": ""}
    async with serve(settings) as (app, client):
        await put(client, {**values, "dkim_nameservers": "192.0.2.1, 2001:db8::1"})
        assert app.state.settings.dkim_nameservers == "192.0.2.1, 2001:db8::1"
        assert app.state.settings.map_source == "off"


async def test_a_new_server_and_a_command_read_the_stored_values(settings: Settings) -> None:
    async with serve(settings) as (_, client):
        await put(client, {"ai_text_model": "text-large", "ai_context_tokens": 8192})
    async with serve(settings) as (app, client):
        assert app.state.settings.ai_text_model == "text-large"
        status = (await client.get("/api/ai/status")).json()
        assert status["defaults"]["context_tokens"] == 8192
    loaded = await stored_settings.load(settings)
    assert (loaded.ai_text_model, loaded.ai_context_tokens) == ("text-large", 8192)
    assert loaded.database_url == settings.database_url

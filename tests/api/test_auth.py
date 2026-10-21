"""Optional HTTP Basic Auth (D4, D24): off, on and half configured; /api/health stays open."""

import base64
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from mailrobbe.api.app import create_app
from mailrobbe.config import Settings
from tests.api.conftest import _client

pytestmark = pytest.mark.db

USER = "aaron"
PASSWORD = "Grüße an €uch: geheim"  # non-ASCII and a colon, sent as UTF-8
INDEX = "<!doctype html><title>Mailrobbe</title>"


def _basic(credentials: bytes) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(credentials).decode()}


GOOD = _basic(f"{USER}:{PASSWORD}".encode())


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text(INDEX)
    return tmp_path / "dist"


async def _app(
    database_url: str, dist: Path, user: str = "", password: str = ""
) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        database_url=database_url,
        frontend_dir=dist,
        basic_auth_user=user,
        basic_auth_password=SecretStr(password),
    )
    async for http in _client(settings):
        yield http


async def test_without_credentials_everything_is_open(
    migrated_database_url: str, dist: Path
) -> None:
    async for http in _app(migrated_database_url, dist):
        assert (await http.get("/api/health")).status_code == 200
        assert (await http.get("/mails/1")).text == INDEX
        assert (await http.get("/api/mails/1")).status_code == 404


async def test_with_credentials_every_request_needs_them(
    migrated_database_url: str, dist: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        async for http in _app(migrated_database_url, dist, USER, PASSWORD):
            for method, path in (
                ("GET", "/"),
                ("GET", "/mails/1?q=x"),
                ("GET", "/api/mails/1"),
                ("PUT", "/api/mails/1/mark"),
                ("POST", "/api/health"),
            ):
                response = await http.request(method, path)
                assert response.status_code == 401, path
                assert response.headers["www-authenticate"] == (
                    'Basic realm="Mailrobbe", charset="UTF-8"'
                )
                assert response.json() == {"detail": "authentication required"}
            for headers in (
                _basic(f"{USER}:wrong".encode()),
                _basic(f"eva:{PASSWORD}".encode()),
                _basic(f"{USER}{PASSWORD}".encode()),  # no colon
                _basic(f"{USER}:{PASSWORD}".encode("latin-1", "replace")),
                {"Authorization": "Basic not-base64!"},
                {"Authorization": GOOD["Authorization"].replace("Basic", "Bearer")},
            ):
                assert (await http.get("/", headers=headers)).status_code == 401, headers

            assert (await http.get("/api/health")).status_code == 200
            assert (await http.get("/", headers=GOOD)).text == INDEX
            lower = {"Authorization": GOOD["Authorization"].replace("Basic", "basic")}
            assert (await http.get("/mails/1", headers=lower)).text == INDEX
            response = await http.get("/api/mails/1", headers=GOOD)
            assert (response.status_code, response.json()["detail"]["code"]) == (404, "not_found")
    assert PASSWORD not in caplog.text


@pytest.mark.parametrize("half", [{"user": USER}, {"password": PASSWORD}])
def test_half_configured_credentials_are_an_error(half: dict[str, str], tmp_path: Path) -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://mailrobbe:x@127.0.0.1:9/mailrobbe",
        frontend_dir=tmp_path,
        basic_auth_user=half.get("user", ""),
        basic_auth_password=SecretStr(half.get("password", "")),
    )
    with pytest.raises(ValueError) as error:
        create_app(settings)
    message = str(error.value)
    assert "MAILROBBE_BASIC_AUTH_USER" in message and "MAILROBBE_BASIC_AUTH_PASSWORD" in message
    assert PASSWORD not in message

"""Serving the built frontend (D24) from a temporary frontend_dir; no database needed."""

import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from mailrobbe.api.frontend import ASSET_HEADERS, INDEX_HEADERS, MAP_HEADERS, NONCE_PLACEHOLDER
from mailrobbe.config import Settings
from tests.api.conftest import _client

INDEX = "<!doctype html><title>Mailrobbe</title><script type=module src=/assets/app-3f9a1c.js>"
SCRIPT = "console.log('Mailrobbe')\n"
VIEWER = f"<!doctype html><script nonce={NONCE_PLACEHOLDER} src=/viewer/pdf-viewer.js></script>"
GLYPHS = b"\x0a\x13\x0a\x11Noto Sans Regular"
# Never connected: these tests only reach routes that do not use the database.
NO_DATABASE = "postgresql+asyncpg://mailrobbe:x@127.0.0.1:9/mailrobbe"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets" / "app-3f9a1c.js").write_text(SCRIPT)
    (dist / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (dist / "viewer").mkdir()
    (dist / "viewer" / "pdf.html").write_text(VIEWER)
    (dist / "viewer" / "pdf-viewer.js").write_text(SCRIPT)
    (dist / "map" / "fonts" / "Noto Sans Regular").mkdir(parents=True)
    (dist / "map" / "fonts" / "Noto Sans Regular" / "0-255.pbf").write_bytes(GLYPHS)
    (tmp_path / "secret.txt").write_text("outside the frontend")
    (dist / "link.txt").symlink_to(tmp_path / "secret.txt")
    return dist


@pytest.fixture
async def client(dist: Path) -> AsyncIterator[httpx.AsyncClient]:
    async for http in _client(Settings(database_url=NO_DATABASE, frontend_dir=dist)):
        yield http


def _is_index(response: httpx.Response) -> bool:
    return (
        response.status_code == 200
        and response.text == INDEX
        and response.headers["content-type"].startswith("text/html")
        and all(response.headers[name] == value for name, value in INDEX_HEADERS.items())
    )


async def test_index_for_the_root_and_client_side_routes(client: httpx.AsyncClient) -> None:
    for path in ("/", "/index.html", "/mails/123?q=from:eva", "/personen/7/", "/assets/gone.js"):
        assert _is_index(await client.get(path)), path


async def test_assets_are_cached_for_good(client: httpx.AsyncClient) -> None:
    response = await client.get("/assets/app-3f9a1c.js")
    assert (response.status_code, response.text) == (200, SCRIPT)
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == ASSET_HEADERS["Cache-Control"]
    assert "content-security-policy" not in response.headers


async def test_other_files_are_served_as_they_are(client: httpx.AsyncClient) -> None:
    response = await client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert "cache-control" not in response.headers


async def test_the_overview_map_is_revalidated_and_its_gaps_are_404s(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/map/fonts/Noto%20Sans%20Regular/0-255.pbf")
    assert (response.status_code, response.content) == (200, GLYPHS)
    assert response.headers["cache-control"] == MAP_HEADERS["Cache-Control"]
    assert "etag" in response.headers
    again = await client.get(
        "/map/fonts/Noto%20Sans%20Regular/0-255.pbf",
        headers={"If-None-Match": response.headers["etag"]},
    )
    assert again.status_code == 304
    for path in ("/map/fonts/Noto%20Sans%20Regular/65024-65279.pbf", "/map/states.json"):
        assert (await client.get(path)).status_code == 404, path
    assert _is_index(await client.get("/mapx/states.json"))


async def test_the_pdf_viewer_runs_sandboxed_by_a_nonce_of_its_own(
    client: httpx.AsyncClient,
) -> None:
    nonces = []
    for _ in range(2):
        response = await client.get("/viewer/pdf.html")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        policy = response.headers["content-security-policy"]
        nonce = re.fullmatch(r"<!doctype html><script nonce=(\S+) src=.*", response.text)
        assert nonce is not None and NONCE_PLACEHOLDER not in response.text
        nonces.append(nonce.group(1))
        assert policy.startswith("sandbox allow-scripts; default-src 'none'; ")
        assert f"script-src 'nonce-{nonce.group(1)}';" in policy
        assert "allow-same-origin" not in policy and "connect-src" not in policy
        assert response.headers["cache-control"] == "no-store"
    assert nonces[0] != nonces[1]
    script = await client.get("/viewer/pdf-viewer.js")
    assert (script.status_code, script.text) == (200, SCRIPT)
    assert script.headers["cache-control"] == "no-cache"
    assert script.headers["x-content-type-options"] == "nosniff"


async def test_head_requests(client: httpx.AsyncClient) -> None:
    for path, size in (("/mails/5", len(INDEX)), ("/assets/app-3f9a1c.js", len(SCRIPT))):
        response = await client.head(path)
        assert (response.status_code, response.content) == (200, b"")
        assert response.headers["content-length"] == str(size)


async def test_nothing_outside_the_directory_is_served(client: httpx.AsyncClient) -> None:
    for path in (
        "/link.txt",
        "/%2e%2e/secret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/..%2fsecret.txt",
        "//secret.txt",
        "/%00",
    ):
        response = await client.get(httpx.URL(f"http://test{path}"))
        assert _is_index(response), path


async def test_unknown_api_paths_stay_json_404s(client: httpx.AsyncClient) -> None:
    for path in ("/api", "/api/unknown", "/api/mails/1/attachments"):
        response = await client.get(path)
        assert (response.status_code, response.json()) == (404, {"detail": "Not Found"}), path


async def test_without_a_built_frontend_only_the_api_runs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "empty").mkdir()
    for missing in (tmp_path / "missing", tmp_path / "empty"):
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            async for http in _client(Settings(database_url=NO_DATABASE, frontend_dir=missing)):
                response = await http.get("/mails/1")
        assert f"frontend not built: no index.html in {missing}" in caplog.text
        assert (response.status_code, response.json()) == (404, {"detail": "Not Found"})

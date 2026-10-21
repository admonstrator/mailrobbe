"""The preview endpoints (D120 to D124): DOCX and ODT pages, audio and video with Range requests,
the cache, and every error, on a small archive built here."""

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ByteSize

from mailrobbe import migrate
from mailrobbe.api import previews as previews_module
from mailrobbe.api.previews import HTML_HEADERS, MEDIA_HEADERS, inline_disposition
from mailrobbe.config import Settings
from mailrobbe.importer.cli import run_import
from mailrobbe.preview import convert as converting
from tests.api.conftest import _client
from tests.api.test_mails import rows
from tests.attachments.doubles import attachment_mail, digest
from tests.conftest import _temporary_database
from tests.importer.doubles import SEPARATOR
from tests.preview.samples import (
    DOCX_MIME,
    ODT_MIME,
    docx,
    drawing,
    footnotes,
    odt,
    para,
    png,
    run,
    wav,
)

pytestmark = pytest.mark.db

DOCX = docx(
    para(run("Bericht über die Spenden"), style="Heading1")
    + para(
        run("Siehe "),
        '<w:hyperlink r:id="rIdLink">' + run("Quelle") + "</w:hyperlink>",
        '<w:r><w:footnoteReference w:id="1"/></w:r>',
    )
    + para(drawing("rIdPng", "Logo")),
    related=(
        ("rIdLink", "hyperlink", "https://tracker.example/?id=7", True),
        ("rIdNotes", "footnotes", "footnotes.xml", False),
        ("rIdPng", "image", "media/logo.png", False),
    ),
    parts={"word/footnotes.xml": footnotes("Protokoll vom 3. März"), "word/media/logo.png": png()},
)
ODT = odt("<text:h text:outline-level='1'>Protokoll</text:h><text:p>Tagesordnung</text:p>")
WAV = wav()
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + bytes(range(256)) * 8
BROKEN = b"PK\x03\x04 kein Word-Dokument"
PDF = b"%PDF-1.4\n%kein echtes PDF\n"
NOTE = b"Nur Text.\n"
FILES = [
    [("Bericht.docx", DOCX_MIME, DOCX)],
    [("Protokoll.odt", ODT_MIME, ODT)],
    [("Aufnahme.wav", "audio/wav", WAV)],
    [("Kaputt.docx", DOCX_MIME, BROKEN)],
    [("Vertrag.pdf", "application/pdf", PDF), ("Notiz.txt", "text/plain", NOTE)],
    [("Stimme.mp3", "audio/mpeg", MP3)],
]


@dataclass(frozen=True, slots=True)
class Archive:
    url: str
    settings: Settings
    mbox: Path  # the MBOX file
    ids: dict[str, int]  # attachment id by file name
    hashes: dict[str, str]  # SHA-256 by file name


@pytest.fixture(scope="module")
def archive(
    database_server_url: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Archive]:
    mbox_dir = tmp_path_factory.mktemp("previews") / "mbox"
    mbox_dir.mkdir()
    with (mbox_dir / "previews.mbox").open("wb") as handle:
        for index, files in enumerate(FILES):
            handle.write(SEPARATOR + b"\n" + attachment_mail(index, files) + b"\n")
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(
            database_url=url, mbox_dir=mbox_dir, frontend_dir=mbox_dir.parent / "no-frontend"
        )
        assert asyncio.run(run_import(settings, mbox_dir, 1)) == 0
        found = asyncio.run(rows(url, "SELECT id, filename, sha256 FROM attachment"))
        yield Archive(
            url=url,
            settings=settings,
            mbox=mbox_dir / "previews.mbox",
            ids={row.filename: row.id for row in found},
            hashes={row.filename: row.sha256 for row in found},
        )


@dataclass(slots=True)
class Previews:
    """A client on the archive with its own copy of the MBOX file and its own cache."""

    http: httpx.AsyncClient
    archive: Archive
    mbox: Path
    cache: Path

    async def get(self, name: str, view: str, **headers: str) -> httpx.Response:
        return await self.http.get(
            f"/api/attachments/{self.archive.ids[name]}/{view}", headers=headers
        )

    def cached(self) -> list[str]:
        return sorted(str(p.relative_to(self.cache)) for p in self.cache.rglob("*") if p.is_file())


async def previews_client(
    archive: Archive, tmp_path: Path, **settings: Any
) -> AsyncIterator[Previews]:
    (tmp_path / "mbox").mkdir()
    mbox = tmp_path / "mbox" / archive.mbox.name
    shutil.copyfile(archive.mbox, mbox)
    cache = tmp_path / "previews"
    update = {"mbox_dir": mbox.parent, "preview_dir": cache, **settings}
    async for http in _client(archive.settings.model_copy(update=update)):
        yield Previews(http, archive, mbox, cache)


@pytest.fixture
async def client(archive: Archive, tmp_path: Path) -> AsyncIterator[Previews]:
    async for previews in previews_client(archive, tmp_path):
        yield previews


def error(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


# Pages ---------------------------------------------------------------------------------------


async def test_docx_and_odt_as_pages(client: Previews) -> None:
    for name, texts in (
        ("Bericht.docx", ["<h1>Bericht über die Spenden</h1>", "<a>Quelle</a>", "März"]),
        ("Protokoll.odt", ["<h1>Protokoll</h1><p>Tagesordnung</p>"]),
    ):
        response = await client.get(name, "html")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        for header, value in HTML_HEADERS.items():
            assert response.headers[header] == value
        page = response.text
        assert page.startswith('<!doctype html>\n<html><head><meta charset="utf-8">')
        assert "Content-Security-Policy" in page
        for text in texts:
            assert text in page
        assert "tracker" not in page and "http:" not in page and "https:" not in page
    page = (await client.get("Bericht.docx", "html")).text
    assert '<img alt="Logo" src="data:image/png;base64,' in page
    assert '<a href="about:srcdoc#footnote-1" id="footnote-ref-1">[1]</a>' in page
    hashes = client.archive.hashes
    assert client.cached() == [
        f"html/{sha[:2]}/{sha}.v{converting.VERSION}.html"
        for sha in sorted((hashes["Bericht.docx"], hashes["Protokoll.odt"]))
    ]


async def test_a_cached_page_needs_no_mbox_file(client: Previews) -> None:
    first = await client.get("Bericht.docx", "html")
    assert first.status_code == 200
    client.mbox.unlink()
    again = await client.get("Bericht.docx", "html")
    assert (again.status_code, again.text) == (200, first.text)
    assert error(await client.get("Protokoll.odt", "html")) == (409, "source_missing")


async def test_a_failed_conversion_is_remembered(client: Previews) -> None:
    response = await client.get("Kaputt.docx", "html")
    assert error(response) == (422, "preview_failed")
    message = response.json()["detail"]["message"]
    assert message.startswith("damaged document: damaged ZIP container: BadZipFile")
    sha = client.archive.hashes["Kaputt.docx"]
    assert client.cached() == [f"html/{sha[:2]}/{sha}.v{converting.VERSION}.failed"]
    client.mbox.unlink()  # the second answer comes from the cache
    response = await client.get("Kaputt.docx", "html")
    assert error(response) == (422, "preview_failed")
    assert response.json()["detail"]["message"] == message


async def test_formats_without_a_page_or_a_player(client: Previews) -> None:
    for name in ("Vertrag.pdf", "Aufnahme.wav", "Notiz.txt"):
        response = await client.get(name, "html")
        assert error(response) == (415, "no_preview"), name
    message = (await client.get("Vertrag.pdf", "html")).json()["detail"]["message"]
    assert message.endswith("is pdf: only DOCX and ODT are shown as HTML")
    for name in ("Vertrag.pdf", "Notiz.txt", "Bericht.docx", "Kaputt.docx"):
        response = await client.get(name, "media")
        assert error(response) == (415, "no_preview"), name
    assert "no audio or video a browser plays" in response.json()["detail"]["message"]
    assert client.cached() == []  # neither bytes nor reasons are kept for them


# Media ---------------------------------------------------------------------------------------


async def test_media_with_range_requests(client: Previews) -> None:
    size = len(WAV)
    response = await client.get("Aufnahme.wav", "media")
    assert response.status_code == 200
    assert response.content == WAV
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(size)
    assert response.headers["content-disposition"] == 'inline; filename="Aufnahme.wav"'
    assert response.headers["etag"]
    for header, value in MEDIA_HEADERS.items():
        assert response.headers[header] == value
    sha = client.archive.hashes["Aufnahme.wav"]
    assert client.cached() == [f"media/{sha[:2]}/{sha}.v1"]

    client.mbox.unlink()  # every further answer comes from the cache
    response = await client.get("Aufnahme.wav", "media", range="bytes=0-99")
    assert response.status_code == 206
    assert response.content == WAV[:100]
    assert response.headers["content-range"] == f"bytes 0-99/{size}"
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["content-security-policy"] == MEDIA_HEADERS["Content-Security-Policy"]
    response = await client.get("Aufnahme.wav", "media", range="bytes=-100")
    assert (response.status_code, response.content) == (206, WAV[-100:])
    assert response.headers["content-range"] == f"bytes {size - 100}-{size - 1}/{size}"
    response = await client.get("Aufnahme.wav", "media", range=f"bytes={size // 2}-")
    assert (response.status_code, response.content) == (206, WAV[size // 2 :])
    response = await client.get("Aufnahme.wav", "media", range=f"bytes={size}-")
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{size}"


async def test_mp3_by_its_first_bytes(client: Previews) -> None:
    response = await client.get("Stimme.mp3", "media")
    assert (response.status_code, response.content) == (200, MP3)
    assert response.headers["content-type"] == "audio/mpeg"


def test_inline_disposition() -> None:
    assert inline_disposition("Aufnahme.wav") == 'inline; filename="Aufnahme.wav"'
    assert inline_disposition("Sitzung März.m4a") == (
        "inline; filename=\"Sitzung M_rz.m4a\"; filename*=UTF-8''Sitzung%20M%C3%A4rz.m4a"
    )


# Errors --------------------------------------------------------------------------------------


async def test_unknown_too_large_and_unhashed(archive: Archive, tmp_path: Path) -> None:
    async for client in previews_client(archive, tmp_path, preview_max_size=ByteSize(len(WAV) - 1)):
        for view in ("html", "media"):
            response = await client.http.get(f"/api/attachments/0/{view}")
            assert error(response) == (404, "not_found")
        response = await client.get("Aufnahme.wav", "media")
        assert error(response) == (413, "preview_too_large")
        assert response.json()["detail"]["message"] == (
            f"attachment {archive.ids['Aufnahme.wav']} has {len(WAV)} bytes, more than the "
            f"preview limit of {ByteSize(len(WAV) - 1).human_readable(decimal=False)}"
        )
        assert (await client.get("Stimme.mp3", "media")).status_code == 200

        async def stored(name: str, sha256: str | None) -> None:
            sql = "UPDATE attachment SET sha256 = :sha256 WHERE id = :id"
            await rows(archive.url, sql, sha256=sha256, id=archive.ids[name])

        try:
            await stored("Stimme.mp3", None)  # as above the hash limit (D18)
            await stored("Protokoll.odt", None)
            assert error(await client.get("Stimme.mp3", "media")) == (413, "preview_too_large")
            assert error(await client.get("Protokoll.odt", "html")) == (413, "preview_too_large")
        finally:
            await stored("Stimme.mp3", archive.hashes["Stimme.mp3"])
            await stored("Protokoll.odt", archive.hashes["Protokoll.odt"])
        assert (await client.get("Protokoll.odt", "html")).status_code == 200
        for path in (f"/api/attachments/{2**63}/html", "/api/attachments/x/media"):
            assert (await client.http.get(path)).status_code == 422


async def test_a_missing_or_changed_source(client: Previews, archive: Archive) -> None:
    original = client.mbox.read_bytes()
    client.mbox.unlink()
    for name, view in (("Bericht.docx", "html"), ("Aufnahme.wav", "media")):
        assert error(await client.get(name, view)) == (409, "source_missing")
    changed = bytearray(original)
    for name in ("Bericht.docx", "Aufnahme.wav"):
        (mail,) = await rows(
            archive.url,
            "SELECT m.byte_offset, m.byte_length FROM attachment a"
            " JOIN mail m ON m.id = a.mail_id WHERE a.id = :id",
            id=archive.ids[name],
        )
        changed[mail.byte_offset + mail.byte_length // 2] ^= 0x01
    client.mbox.write_bytes(bytes(changed))
    for name, view in (("Bericht.docx", "html"), ("Aufnahme.wav", "media")):
        assert error(await client.get(name, view)) == (409, "source_changed")
    assert client.cached() == []  # a missing file is no reason to remember
    client.mbox.write_bytes(original)
    assert (await client.get("Bericht.docx", "html")).status_code == 200
    assert (await client.get("Aufnahme.wav", "media")).status_code == 200


# Concurrency and a cache that cannot be used ------------------------------------------------


async def test_one_conversion_per_document_and_a_limited_number_at_once(
    archive: Archive, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    running = 0
    most = 0

    async def counted(data: bytes, fmt: str, *, timeout: float, memory: int) -> bytes:
        nonlocal running, most
        calls.append(fmt)
        running += 1
        most = max(most, running)
        try:
            await asyncio.sleep(0.2)
            return await converting.convert(data, fmt, timeout=timeout, memory=memory)
        finally:
            running -= 1

    monkeypatch.setattr(previews_module, "convert", counted)
    async for client in previews_client(archive, tmp_path, preview_workers=1):
        responses = await asyncio.gather(
            client.get("Bericht.docx", "html"),
            client.get("Bericht.docx", "html"),
            client.get("Protokoll.odt", "html"),
            client.get("Bericht.docx", "html"),
        )
        assert [response.status_code for response in responses] == [200] * 4
        assert len({responses[0].text, responses[1].text, responses[3].text}) == 1
        assert sorted(calls) == ["docx", "odt"]  # the document once, though asked three times
        assert most == 1  # MAILROBBE_PREVIEW_WORKERS


async def test_an_unusable_cache_still_shows_previews(
    archive: Archive, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the cache directory should be")
    async for client in previews_client(archive, tmp_path, preview_dir=blocked):
        with caplog.at_level(logging.WARNING):
            for _ in range(2):
                response = await client.get("Bericht.docx", "html")
                assert response.status_code == 200
                assert "<h1>Bericht über die Spenden</h1>" in response.text
                response = await client.get("Aufnahme.wav", "media", range="bytes=0-99")
                assert (response.status_code, response.content) == (200, WAV)  # no ranges
                assert response.headers["content-type"] == "audio/wav"
        warnings = [r.getMessage() for r in caplog.records if "preview cache" in r.getMessage()]
        assert len(warnings) == 1
        assert warnings[0].startswith(f"preview cache {blocked} is not usable")


async def test_the_hash_of_the_wav_is_its_own(archive: Archive) -> None:
    assert archive.hashes["Aufnahme.wav"] == digest(WAV)
    assert archive.hashes["Bericht.docx"] == digest(DOCX)

"""The export API (D62, D63) against the imported generated archive (tests/api/conftest.py).

Creating an export writes mail_export, so these tests use mutable_client or a client of their
own on a copy of the database; broken sources come from copies of the MBOX files in tmp_path.
Every manifest field is compared with direct SQL, every file with SHA256SUMS the way
sha256sum -c reads it.
"""

import asyncio
import csv
import hashlib
import io
import json
import re
import shutil
import zipfile
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pypdf
import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mailrobbe.api import exports
from mailrobbe.api.schemas import LABEL_LIMIT, ExportInfo
from mailrobbe.db.models import MailExport
from mailrobbe.dkim.override import key_name
from mailrobbe.export.bundle import stream_export
from mailrobbe.export.manifest import (
    CSV_HEADER,
    CSV_RESEARCH_HEADER,
    ERROR_TEXTS,
    ManifestAddress,
    ManifestAttachment,
    ManifestDkim,
    ManifestFile,
    ManifestFiles,
    ManifestMail,
    ManifestSignature,
    ManifestSource,
)
from mailrobbe.mbox import read_message
from tests.api.conftest import _client, api_settings
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

Row = dict[str, Any]
EDITOR = {"X-Mailrobbe-Editor": "Lena%20Vogt"}
SUMS_LINE = re.compile(r"([0-9a-f]{64})  (\S.*)")


@dataclass(frozen=True, slots=True)
class Archive:
    """The imported archive as direct SQL sees it."""

    mbox_dir: Path
    mails: dict[int, Row]  # by id, with the MBOX file's path
    participants: dict[int, dict[str, list[ManifestAddress]]]  # mail id -> role -> addresses
    dkim: dict[int, list[Row]]  # mail id -> dkim_result rows by signature_index
    dns: dict[str, Row]  # dns_cache rows by name
    attachments: dict[int, list[Row]]  # mail id -> attachment rows by id

    def original(self, sha256: str) -> Row:
        """The mail an export takes for a content: no duplicate first, then the lowest id."""
        copies = [mail for mail in self.mails.values() if mail["raw_sha256"] == sha256]
        return min(copies, key=lambda mail: (mail["is_duplicate_of"] is not None, mail["id"]))

    def order(self, ids: list[int]) -> list[str]:
        """The contents of the mails, as an export stores them: oldest first, each once."""
        mails = sorted((self.mails[i] for i in set(ids)), key=_sort_key)
        return list(dict.fromkeys(mail["raw_sha256"] for mail in mails))

    def message(self, mail: Row) -> bytes:
        return read_message(self.mbox_dir / mail["path"], mail["byte_offset"], mail["byte_length"])

    def entry(self, number: int, mail: Row, pdf: bytes) -> dict[str, Any]:
        """The manifest entry of a mail exported with its files, without research data."""
        folder = f"{number:04d}-{mail['id']}"
        signatures = []
        for result in self.dkim[mail["id"]]:
            key = None
            if result["selector"] and result["domain"]:
                key = self.dns.get(key_name(result["selector"], result["domain"]))
            signatures.append(
                ManifestSignature(
                    index=result["signature_index"],
                    result=result["status"],
                    reason=result["reason"],
                    domain=result["domain"],
                    selector=result["selector"],
                    algorithm=result["algorithm"],
                    key_bits=result["key_bits"],
                    aligned=result["aligned"],
                    signed_at=result["signed_at"],
                    checked_at=result["checked_at"],
                    key_status=key["status"] if key else None,
                    key_record=key["record"] if key else None,
                    key_fetched_at=key["fetched_at"] if key else None,
                )
            )
        roles = self.participants[mail["id"]]
        entry = ManifestMail(
            number=number,
            folder=folder,
            mail_id=mail["id"],
            sha256=mail["raw_sha256"],
            message_id=mail["message_id"],
            in_reply_to=mail["in_reply_to"],
            date=mail["date_utc"],
            subject=mail["subject"],
            from_=roles.get("from", []),
            to=roles.get("to", []),
            cc=roles.get("cc", []),
            bcc=roles.get("bcc", []),
            source=ManifestSource(
                file=mail["path"],
                byte_offset=mail["byte_offset"],
                byte_length=mail["byte_length"],
            ),
            files=ManifestFiles(
                eml=ManifestFile(
                    path=f"{folder}/mail.eml",
                    size=len(self.message(mail)),
                    sha256=mail["raw_sha256"],
                ),
                pdf=ManifestFile(
                    path=f"{folder}/mail.pdf", size=len(pdf), sha256=hashlib.sha256(pdf).hexdigest()
                ),
            ),
            dkim=ManifestDkim(status=mail["dkim_status"], signatures=signatures),
            attachments=[
                ManifestAttachment(
                    filename=a["filename"],
                    mime_type=a["mime_type"],
                    size=a["size_bytes"],
                    sha256=a["sha256"],
                )
                for a in self.attachments[mail["id"]]
            ],
        )
        return entry.model_dump(mode="json", by_alias=True, exclude={"research"})


@pytest.fixture(scope="module")
def archive(imported_database_url: str, generated_archive: GeneratedArchive) -> Archive:
    return asyncio.run(_load(imported_database_url, generated_archive.mbox_dir))


async def _load(url: str, mbox_dir: Path) -> Archive:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:

            async def rows(sql: str) -> list[Row]:
                return [row._asdict() for row in await connection.execute(text(sql))]

            mails = {
                row["id"]: row
                for row in await rows(
                    "SELECT m.*, f.path FROM mail m JOIN mbox_file f ON f.id = m.mbox_file_id"
                )
            }
            participants: dict[int, dict[str, list[ManifestAddress]]] = defaultdict(dict)
            for row in await rows(
                "SELECT p.mail_id, p.role::text AS role, e.canonical_email AS email, "
                "COALESCE(p.display_name, e.display_name) AS name "
                "FROM participation p JOIN person e ON e.id = p.person_id "
                "ORDER BY p.mail_id, p.role, name, email"
            ):
                address = ManifestAddress(email=row["email"], name=row["name"])
                participants[row["mail_id"]].setdefault(row["role"], []).append(address)
            dkim: dict[int, list[Row]] = defaultdict(list)
            for row in await rows("SELECT * FROM dkim_result ORDER BY mail_id, signature_index"):
                dkim[row["mail_id"]].append(row)
            dns = {row["name"]: row for row in await rows("SELECT * FROM dns_cache")}
            attachments: dict[int, list[Row]] = defaultdict(list)
            for row in await rows("SELECT * FROM attachment ORDER BY id"):
                attachments[row["mail_id"]].append(row)
    finally:
        await engine.dispose()
    return Archive(mbox_dir, mails, participants, dkim, dns, attachments)


def _sort_key(mail: Row) -> tuple[bool, datetime, int]:
    """The mail list's oldest first: mails without a date first, then by id."""
    date = mail["date_utc"]
    return (date is not None, date or datetime.min.replace(tzinfo=UTC), mail["id"])


def _pick(archive: Archive) -> list[int]:
    """Mails worth exporting: some plain ones, a byte-identical copy (not the original), the
    one with the most attachments, one with several signatures and one without a date."""
    mails = sorted(archive.mails.values(), key=lambda mail: mail["id"])
    copy = next(
        mail
        for mail in mails
        if mail["id"] != archive.original(mail["raw_sha256"])["id"]
        and mail["raw_sha256"] != mails[0]["raw_sha256"]
    )
    attached = max(mails, key=lambda mail: len(archive.attachments[mail["id"]]))
    signed = next(mail for mail in mails if len(archive.dkim[mail["id"]]) > 1)
    undated = [mail for mail in mails if mail["date_utc"] is None][:1]
    picked = [mail["id"] for mail in [*mails[:10], copy, attached, signed, *undated]]
    return list(dict.fromkeys(picked))


# Helpers -------------------------------------------------------------------------------------


async def _create(client: httpx.AsyncClient, body: dict[str, Any]) -> ExportInfo:
    response = await client.post("/api/exports", json=body, headers=EDITOR)
    assert response.status_code == 201, response.text
    return ExportInfo.model_validate(response.json())


async def _download(client: httpx.AsyncClient, info: ExportInfo) -> bytes:
    response = await client.get(info.download_url)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="mailrobbe-export-{info.id}.zip"'
    )
    return response.content


async def _listed(client: httpx.AsyncClient, export_id: int) -> ExportInfo:
    response = await client.get("/api/exports")
    assert response.status_code == 200
    return next(e for e in map(ExportInfo.model_validate, response.json()) if e.id == export_id)


async def _code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


async def _execute(url: str, *statements: str, **params: object) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _stored(url: str, export_id: int) -> Row:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT * FROM mail_export WHERE id = :id"), {"id": export_id}
            )
            return result.one()._asdict()
    finally:
        await engine.dispose()


class Zip:
    """A downloaded export, read back."""

    def __init__(self, data: bytes, export_id: int) -> None:
        self.data = data
        self.folder = f"mailrobbe-export-{export_id}"
        self.zip = zipfile.ZipFile(io.BytesIO(data))
        assert self.zip.testzip() is None
        names = self.zip.namelist()
        assert all(name.startswith(f"{self.folder}/") for name in names)
        self.paths = [name.removeprefix(f"{self.folder}/") for name in names]

    def read(self, path: str) -> bytes:
        return self.zip.read(f"{self.folder}/{path}")

    def manifest(self) -> dict[str, Any]:
        manifest: dict[str, Any] = json.loads(self.read("manifest.json"))
        return manifest

    def csv(self) -> list[list[str]]:
        data = self.read("manifest.csv")
        assert data.startswith(b"\xef\xbb\xbf")  # UTF-8 with BOM, as the mail list's CSV
        return list(csv.reader(io.StringIO(data[3:].decode(), newline=""), delimiter=";"))

    def pdf_text(self, path: str) -> str:
        reader = pypdf.PdfReader(io.BytesIO(self.read(path)))
        return " ".join(" ".join(page.extract_text() for page in reader.pages).split())

    def check_sums(self) -> list[str]:
        """What sha256sum -c SHA256SUMS does in the export's folder: every line names a file
        relative to it and its SHA-256, which must match. Returns the paths listed."""
        sums = self.read("SHA256SUMS").decode()
        assert sums.endswith("\n")
        listed = []
        for line in sums.splitlines():
            match = SUMS_LINE.fullmatch(line)
            assert match, line
            digest, path = match.groups()
            assert hashlib.sha256(self.read(path)).hexdigest() == digest, path
            listed.append(path)
        return listed


# Creating and listing ------------------------------------------------------------------------


async def test_creating_an_export_stores_the_selection(
    mutable_client: httpx.AsyncClient, mutable_database_url: str, archive: Archive
) -> None:
    ids = _pick(archive)
    copy = next(i for i in ids if archive.original(archive.mails[i]["raw_sha256"])["id"] != i)
    original = archive.original(archive.mails[copy]["raw_sha256"])["id"]
    sent = [copy, *ids, original]
    info = await _create(mutable_client, {"ids": sent, "label": "  Für Kanzlei Weber  "})
    order = archive.order(sent)
    assert info.model_dump(exclude={"id", "created_at"}) == {
        "label": "Für Kanzlei Weber",
        "mails": len(order),  # byte-identical copies once
        "include_research": False,
        "created_by": "Lena Vogt",
        "manifest_sha256": None,
        "downloaded_at": None,
        "download_url": f"/api/exports/{info.id}/download",
    }
    stored = await _stored(mutable_database_url, info.id)
    assert stored["selection"] == {"ids": sent}  # as sent
    assert stored["mail_sha256"] == order
    assert stored["created_at"] == info.created_at

    filters = {"dkim": ["pass", "fail"], "q": "a"}
    filtered = await _create(mutable_client, {"filters": filters, "include_research": True})
    stored = await _stored(mutable_database_url, filtered.id)
    assert stored["selection"] == {"filters": filters}
    assert (filtered.label, filtered.include_research) == ("", True)
    listed = (await mutable_client.get("/api/exports")).json()
    assert [e["id"] for e in listed] == [filtered.id, info.id]  # newest first


async def test_selection_errors_and_limits(
    mutable_client: httpx.AsyncClient, archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = sorted(archive.mails)[:3]
    post = mutable_client.post
    assert await _code(await post("/api/exports", json={})) == (400, "invalid_selection")
    nothing = {"filters": {"q": "Wortohnetreffer"}}
    assert await _code(await post("/api/exports", json=nothing)) == (400, "empty_selection")
    unknown = {"ids": [*ids, 987654321]}
    assert await _code(await post("/api/exports", json=unknown)) == (404, "not_found")
    broken = {"filters": {"q": "dkim:maybe"}}
    assert await _code(await post("/api/exports", json=broken)) == (400, "invalid_query")
    long = {"ids": ids, "label": "x" * (LABEL_LIMIT + 1)}
    assert (await post("/api/exports", json=long)).status_code == 422
    monkeypatch.setattr(exports, "EXPORT_LIMIT", 2)
    response = await post("/api/exports", json={"ids": ids})
    assert await _code(response) == (400, "too_many_mails")
    assert await _code(await post("/api/exports", json={"filters": {}})) == (400, "too_many_mails")
    assert (await mutable_client.get("/api/exports")).json() == []

    monkeypatch.setattr(exports, "EXPORTS_LISTED", 2)
    made = [(await _create(mutable_client, {"ids": [i]})).id for i in ids]
    assert [e["id"] for e in (await mutable_client.get("/api/exports")).json()] == made[:0:-1]
    response = await mutable_client.get("/api/exports/987654321/download")
    assert await _code(response) == (404, "not_found")


# The ZIP -------------------------------------------------------------------------------------


async def test_the_zip_holds_every_mail_with_manifest_and_checksums(
    mutable_client: httpx.AsyncClient, mutable_database_url: str, archive: Archive
) -> None:
    ids = _pick(archive)
    info = await _create(mutable_client, {"ids": ids, "label": "Akte Hafen"})
    data = await _download(mutable_client, info)
    export = Zip(data, info.id)
    created = info.created_at.astimezone(UTC)

    # Layout: a folder per mail in export order, then manifests, LIESMICH.txt and SHA256SUMS.
    mails = [archive.original(sha) for sha in archive.order(ids)]
    folders = [f"{n:04d}-{mail['id']}" for n, mail in enumerate(mails, 1)]
    assert export.paths == [
        *(f"{folder}/{name}" for folder in folders for name in ("mail.eml", "mail.pdf")),
        "manifest.json",
        "manifest.csv",
        "LIESMICH.txt",
        "SHA256SUMS",
    ]
    zip_time = (*created.timetuple()[:5], created.second // 2 * 2)  # in steps of two seconds
    for entry in export.zip.infolist():
        assert entry.date_time == zip_time
        assert (entry.compress_type, entry.external_attr >> 16) == (zipfile.ZIP_DEFLATED, 0o644)
    assert sorted(export.check_sums()) == sorted(export.paths[:-1])

    # Each mail.eml is the message as imported; each PDF names it.
    for folder, mail in zip(folders, mails, strict=True):
        eml = export.read(f"{folder}/mail.eml")
        assert eml == archive.message(mail)
        assert hashlib.sha256(eml).hexdigest() == mail["raw_sha256"]
        reading = export.pdf_text(f"{folder}/mail.pdf")
        assert f"SHA-256 {mail['raw_sha256']}" in reading
        assert (
            f"Mail {mail['id']} · Lesefassung erstellt am {created:%d.%m.%Y, %H:%M:%S} UTC"
            in reading
        )
        assert f"für Export {info.id}" in reading
        assert "Rechercheangaben" not in reading

    # manifest.json: the export, and every mail as the database has it.
    manifest = export.manifest()
    assert manifest["format"] == "mailrobbe-export"
    assert manifest["version"] == 1
    assert manifest["export"] == {
        "id": info.id,
        "label": "Akte Hafen",
        "created_by": "Lena Vogt",
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "include_research": False,
        "mails": len(mails),
        "errors": 0,
    }
    for number, (entry, mail) in enumerate(zip(manifest["mails"], mails, strict=True), 1):
        pdf = export.read(f"{folders[number - 1]}/mail.pdf")
        assert entry == archive.entry(number, mail, pdf)
    assert any(len(entry["dkim"]["signatures"]) > 1 for entry in manifest["mails"])
    assert any(entry["attachments"] for entry in manifest["mails"])

    # manifest.csv: the same per mail, below the export's figures.
    rows = export.csv()
    assert rows[:8] == [
        ["Mailrobbe-Export", str(info.id)],
        ["Bezeichnung", "Akte Hafen"],
        ["Erstellt von", "Lena Vogt"],
        ["Erstellt am (UTC)", manifest["export"]["created_at"]],
        ["Mails", str(len(mails))],
        ["Davon mit Fehler", "0"],
        ["Rechercheangaben", "nein"],
        [],
    ]
    assert tuple(rows[8]) == CSV_HEADER
    for row, entry in zip(rows[9:], manifest["mails"], strict=True):
        cells = dict(zip(CSV_HEADER, row, strict=True))
        assert cells["Nr."] == str(entry["number"])
        assert cells["Ordner"] == entry["folder"]
        assert cells["Mail-ID"] == str(entry["mail_id"])
        assert cells["SHA-256 mail.eml"] == entry["files"]["eml"]["sha256"]
        assert cells["SHA-256 mail.pdf"] == entry["files"]["pdf"]["sha256"]
        assert cells["Fehler"] == ""
        assert cells["Datum (UTC)"] == (entry["date"] or "")
        assert cells["MBOX-Datei"] == entry["source"]["file"]
        assert cells["Offset"] == str(entry["source"]["byte_offset"])
        assert cells["Länge"] == str(entry["source"]["byte_length"])
        assert cells["DKIM"] == entry["dkim"]["status"]
        assert cells["Anhänge"].count("Bytes)") == len(entry["attachments"])

    readme = export.read("LIESMICH.txt").decode()
    assert readme.startswith(f"Mailrobbe-Export {info.id} \N{EN DASH} „Akte Hafen“\r\n")
    assert "\n" not in readme.replace("\r\n", "")
    for expected in ("sha256sum -c SHA256SUMS", "shasum -a 256 -c SHA256SUMS", "nicht enthalten"):
        assert expected in readme

    # The end of the first complete download records the SHA-256 of SHA256SUMS ...
    first = await _listed(mutable_client, info.id)
    assert first.manifest_sha256 == hashlib.sha256(export.read("SHA256SUMS")).hexdigest()
    assert first.downloaded_at is not None
    # ... and a second download gives the same bytes and changes nothing.
    assert await _download(mutable_client, info) == data
    assert await _listed(mutable_client, info.id) == first


async def test_a_download_broken_off_records_nothing(
    mutable_client: httpx.AsyncClient,
    mutable_database_url: str,
    archive: Archive,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
) -> None:
    info = await _create(mutable_client, {"ids": sorted(archive.mails)[:3]})
    engine = create_async_engine(mutable_database_url, poolclass=pool.NullPool)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            export = await session.get(MailExport, info.id)
        assert export is not None
        settings = api_settings(mutable_database_url, generated_archive, tmp_path)
        stream = stream_export(sessionmaker, settings, export)
        assert (await anext(stream)).startswith(b"PK")
        await stream.aclose()
    finally:
        await engine.dispose()
    assert (await _listed(mutable_client, info.id)).manifest_sha256 is None


# Research data -------------------------------------------------------------------------------


async def test_research_data_only_on_request(
    mutable_client: httpx.AsyncClient, mutable_database_url: str, archive: Archive
) -> None:
    first, second = (archive.original(sha) for sha in archive.order(sorted(archive.mails)[:2]))
    await _execute(
        mutable_database_url,
        "INSERT INTO mail_mark (mail_sha256, flagged, flagged_by, flagged_at, review, review_by, "
        "review_at) VALUES (:sha, true, 'Lena Vogt', :at, 'relevant', 'Lena Vogt', :at)",
        "WITH t AS (INSERT INTO tag (name, color) VALUES ('Kartell', 'red') RETURNING id) "
        "INSERT INTO mail_tag (tag_id, mail_sha256) SELECT id, :sha FROM t",
        "WITH c AS (INSERT INTO collection (name) VALUES ('Akte Hafen') RETURNING id) "
        "INSERT INTO collection_mail (collection_id, mail_sha256) SELECT id, :sha FROM c",
        "INSERT INTO note (mail_sha256, body, author, created_at, updated_at) "
        "VALUES (:sha, 'Quelle B bestätigt.', 'Lena Vogt', :at, :at)",
        sha=first["raw_sha256"],
        at=datetime(2025, 7, 1, 12, 0, tzinfo=UTC),
    )
    selection = {"ids": [first["id"], second["id"]]}
    marked = f"0001-{first['id']}/mail.pdf"

    without = await _create(mutable_client, selection)
    export = Zip(await _download(mutable_client, without), without.id)
    manifest = export.manifest()
    assert "selection" not in manifest["export"]
    assert all("research" not in entry for entry in manifest["mails"])
    assert export.csv()[8] == list(CSV_HEADER)
    for path in export.paths:
        content = export.pdf_text(path) if path.endswith(".pdf") else export.read(path).decode()
        for secret in ("Kartell", "Akte Hafen", "Quelle B", "Rechercheangaben (intern)"):
            assert secret not in content, (path, secret)

    included = await _create(mutable_client, {**selection, "include_research": True})
    export = Zip(await _download(mutable_client, included), included.id)
    manifest = export.manifest()
    assert manifest["export"]["include_research"] is True
    assert manifest["export"]["selection"] == selection
    assert [entry["research"] for entry in manifest["mails"]] == [
        {
            "review": "relevant",
            "review_by": "Lena Vogt",
            "review_at": "2025-07-01T12:00:00Z",
            "flagged": True,
            "flagged_by": "Lena Vogt",
            "flagged_at": "2025-07-01T12:00:00Z",
            "tags": ["Kartell"],
            "collections": ["Akte Hafen"],
            "notes": [
                {
                    "author": "Lena Vogt",
                    "created_at": "2025-07-01T12:00:00Z",
                    "updated_at": "2025-07-01T12:00:00Z",
                    "text": "Quelle B bestätigt.",
                }
            ],
        },
        {
            "review": None,
            "review_by": None,
            "review_at": None,
            "flagged": False,
            "flagged_by": None,
            "flagged_at": None,
            "tags": [],
            "collections": [],
            "notes": [],
        },
    ]
    rows = export.csv()
    assert rows[6] == ["Rechercheangaben", "ja"]
    assert tuple(rows[8]) == CSV_HEADER + CSV_RESEARCH_HEADER
    assert rows[9][len(CSV_HEADER) :] == [
        "Relevant (Lena Vogt, 2025-07-01T12:00:00Z)",
        "ja",
        "Kartell",
        "Akte Hafen",
        "Lena Vogt, 2025-07-01T12:00:00Z: Quelle B bestätigt.",
    ]
    assert rows[10][len(CSV_HEADER) :] == ["Ungesichtet", "nein", "", "", ""]
    pdf = export.pdf_text(marked)
    assert "Rechercheangaben (intern)" in pdf
    assert "Quelle B bestätigt." in pdf
    assert "ENTHALTEN" in export.read("LIESMICH.txt").decode()


# Broken sources ------------------------------------------------------------------------------


@pytest.fixture
async def copy_client(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Client on this test's own database whose MBOX directory is a copy in tmp_path/mbox."""
    shutil.copytree(
        generated_archive.mbox_dir, tmp_path / "mbox", ignore=shutil.ignore_patterns("_generator")
    )
    settings = api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings.model_copy(update={"mbox_dir": tmp_path / "mbox"})):
        yield http


async def test_unreadable_mails_are_listed_with_an_error(
    copy_client: httpx.AsyncClient, mutable_database_url: str, archive: Archive, tmp_path: Path
) -> None:
    by_file: dict[str, list[Row]] = defaultdict(list)
    for mail in sorted(archive.mails.values(), key=lambda mail: mail["id"]):
        if archive.original(mail["raw_sha256"])["id"] == mail["id"]:
            by_file[mail["path"]].append(mail)
    assert len(by_file) > 1
    (missing, *_), (changed, kept, *_) = list(by_file.values())[:2]
    info = await _create(copy_client, {"ids": [missing["id"], changed["id"], kept["id"]]})
    gone = "0" * 64
    await _execute(
        mutable_database_url,
        "UPDATE mail_export SET mail_sha256 = mail_sha256 || :gone WHERE id = :id",
        gone=[gone],
        id=info.id,
    )
    (tmp_path / "mbox" / missing["path"]).unlink()
    copy = tmp_path / "mbox" / changed["path"]
    content = bytearray(copy.read_bytes())
    content[changed["byte_offset"] + changed["byte_length"] // 2] ^= 0x01
    copy.write_bytes(bytes(content))

    export = Zip(await _download(copy_client, info), info.id)
    manifest = export.manifest()
    errors = {
        entry["sha256"]: (entry["error"]["code"], entry["error"]["message"])
        for entry in manifest["mails"]
        if entry["error"]
    }
    assert errors == {
        missing["raw_sha256"]: ("source_missing", ERROR_TEXTS["source_missing"]),
        changed["raw_sha256"]: ("source_changed", ERROR_TEXTS["source_changed"]),
        gone: ("not_in_archive", ERROR_TEXTS["not_in_archive"]),
    }
    assert manifest["export"]["errors"] == 3
    assert [entry["number"] for entry in manifest["mails"]] == [1, 2, 3, 4]
    for entry in manifest["mails"]:
        if entry["error"]:
            assert (entry["folder"], entry["files"]) == (None, None)
            assert (entry["mail_id"] is None) is (entry["sha256"] == gone)
    good = next(entry for entry in manifest["mails"] if entry["error"] is None)
    assert good["mail_id"] == kept["id"]
    assert export.paths[:2] == [f"{good['folder']}/mail.eml", f"{good['folder']}/mail.pdf"]
    assert len(export.paths) == 6
    assert sorted(export.check_sums()) == sorted(export.paths[:-1])
    failed = [row for row in export.csv()[9:] if row[CSV_HEADER.index("Fehler")]]
    assert len(failed) == 3
    assert "Bei 3 von ihnen fehlen die Dateien" in export.read("LIESMICH.txt").decode()


# The PDF of one mail -------------------------------------------------------------------------


async def test_the_pdf_of_a_mail(client: httpx.AsyncClient, archive: Archive) -> None:
    mail = archive.mails[min(archive.mails)]
    response = await client.get(f"/api/mails/{mail['id']}/pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="mailrobbe-{mail["id"]}.pdf"'
    )
    reader = pypdf.PdfReader(io.BytesIO(response.content))
    text = " ".join(" ".join(page.extract_text() for page in reader.pages).split())
    assert f"SHA-256 {mail['raw_sha256']}" in text
    assert f"Mail {mail['id']} · Lesefassung erstellt am" in text
    assert "für Export" not in text
    assert "Rechercheangaben" not in text

    response = await client.get(f"/api/mails/{mail['id']}/pdf", params={"research": "true"})
    reader = pypdf.PdfReader(io.BytesIO(response.content))
    text = " ".join(" ".join(page.extract_text() for page in reader.pages).split())
    assert "Rechercheangaben (intern) Bewertung Ungesichtet Markiert nein" in text

    assert await _code(await client.get("/api/mails/987654321/pdf")) == (404, "not_found")


async def test_the_pdf_of_a_mail_whose_source_broke(
    copy_client: httpx.AsyncClient, archive: Archive, tmp_path: Path
) -> None:
    mail = archive.mails[min(archive.mails)]
    copy = tmp_path / "mbox" / mail["path"]
    original = copy.read_bytes()
    copy.write_bytes(original[: mail["byte_offset"] + mail["byte_length"] - 1])
    response = await copy_client.get(f"/api/mails/{mail['id']}/pdf")
    assert await _code(response) == (409, "source_changed")
    copy.unlink()
    response = await copy_client.get(f"/api/mails/{mail['id']}/pdf")
    assert await _code(response) == (409, "source_missing")

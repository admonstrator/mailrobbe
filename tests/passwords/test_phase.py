"""The passwords step of an import (D234 to D236) on ARCHIVE (tests/passwords/samples.py): what
one import opens, and run_passwords on copies of it: locked marks, the incremental scan, the
passwords offered once, one broken or unreadable document, a stop, a child over its time limit."""

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.attachments import protected
from mailrobbe.attachments.metadata import METADATA_VERSION
from mailrobbe.config import Settings
from mailrobbe.db.session import create_sessionmaker
from mailrobbe.jobrun import Step
from mailrobbe.jobs import ImportProgress
from mailrobbe.passwords import phase
from mailrobbe.passwords.candidates import CANDIDATES_VERSION
from mailrobbe.passwords.phase import PasswordsResult, run_passwords, waiting
from tests.passwords.samples import (
    GEHEIM_PASSWORD,
    LISTE_PASSWORD,
    LISTE_TEXT,
    PAKET_PASSWORD,
    PASSWORDS,
    VERTRAG_PASSWORD,
    VERTRAG_TEXT,
    copied,
    documents,
    execute,
    fetch,
    imported,
    mail_ids,
    needs_seven_zip,
    write_archive,
)

pytestmark = [pytest.mark.db, pytest.mark.slow, needs_seven_zip]


@pytest.fixture(scope="module")
def mbox_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_archive(tmp_path_factory.mktemp("passwords") / "mbox")


@pytest.fixture(scope="module")
def imported_url(database_server_url: str, mbox_dir: Path) -> Iterator[str]:
    """ARCHIVE imported once. Read only."""
    with imported(database_server_url, mbox_dir) as url:
        yield url


@pytest.fixture
def url(database_server_url: str, imported_url: str) -> Iterator[str]:
    """This test's own copy of the imported archive."""
    with copied(database_server_url, imported_url) as copy:
        yield copy


async def run(
    url: str, mbox_dir: Path, stop: asyncio.Event | None = None, **settings: Any
) -> PasswordsResult:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        return await run_passwords(
            create_sessionmaker(engine),
            Settings(database_url=url, **settings),
            mbox_dir,
            2,
            stop or asyncio.Event(),
            Step(),
        )
    finally:
        await engine.dispose()


async def waiting_now(url: str) -> int:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with create_sessionmaker(engine)() as session:
            return await waiting(session)
    finally:
        await engine.dispose()


async def add_mail(url: str, body: str) -> int:
    """A mail written in SQL, far from the others and without participants: its passwords are of
    tier archive for every document."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            return int(
                await connection.scalar(
                    text(
                        "INSERT INTO mail (mbox_file_id, byte_offset, byte_length, raw_sha256, "
                        "subject, body_text, date_utc) SELECT min(id), "
                        "(SELECT coalesce(max(byte_offset), 0) + 1000000 FROM mail), 1, 'neu', "
                        "'Neu', :body, '2030-01-01' FROM mbox_file RETURNING id"
                    ),
                    {"body": body},
                )
            )
    finally:
        await engine.dispose()


async def findings(url: str) -> list[tuple[Any, ...]]:
    rows = await fetch(
        url,
        "SELECT pw.value, f.mail_id, f.document_id, f.context FROM password_finding f "
        "JOIN password pw ON pw.id = f.password_id ORDER BY f.id",
    )
    return [tuple(row) for row in rows]


async def relock(url: str, name: str) -> None:
    """Lock an opened document again, as before any password was tried on it."""
    await execute(
        url,
        "DELETE FROM document_password WHERE document_id = (SELECT id FROM document "
        "WHERE name = :name)",
        "UPDATE document SET protection = 'locked', text_status = 'encrypted', "
        "extracted_text = NULL, password_tried_until = 0, password_tries = 0 WHERE name = :name",
        name=name,
    )


async def test_one_import_opens_what_the_archive_holds_the_passwords_of(
    imported_url: str,
) -> None:
    ids = await mail_ids(imported_url)
    docs = await documents(imported_url)
    password_ids = {
        row.value: row.id for row in await fetch(imported_url, "SELECT id, value FROM password")
    }
    assert sorted(password_ids, key=password_ids.__getitem__) == list(PASSWORDS)
    last = max(password_ids.values())
    assert await findings(imported_url) == [
        (LISTE_PASSWORD, ids[1], None, f"Das Kennwort lautet: {LISTE_PASSWORD}"),
        (VERTRAG_PASSWORD, ids[2], None, f"Passwort: {VERTRAG_PASSWORD}"),
        (PAKET_PASSWORD, ids[7], None, f"PIN: {PAKET_PASSWORD}"),
    ]
    finding = {
        row.value: row.id
        for row in await fetch(
            imported_url,
            "SELECT pw.value, f.id FROM password_finding f "
            "JOIN password pw ON pw.id = f.password_id",
        )
    }
    # a reply in the same thread, the mail itself, a mail between the same persons
    for name, password, tier in (
        ("Liste.pdf", LISTE_PASSWORD, "thread"),
        ("Vertrag.docx", VERTRAG_PASSWORD, "mail"),
        ("Paket.zip", PAKET_PASSWORD, "contacts"),
    ):
        doc = docs[name]
        assert (doc.protection, doc.password, doc.tier, doc.finding_id, doc.found_by) == (
            "open",
            password,
            tier,
            finding[password],
            None,
        ), name
    # opened with its text, read with the password (D236)
    assert (docs["Liste.pdf"].text_status, docs["Liste.pdf"].extracted_text) == (
        "text",
        "\n\n".join(LISTE_TEXT),
    )
    # its metadata read again with the password by the metadata step that follows
    assert (docs["Liste.pdf"].pages, docs["Liste.pdf"].metadata_version) == (2, METADATA_VERSION)
    assert docs["Vertrag.docx"].extracted_text == VERTRAG_TEXT
    assert (docs["Liste.pdf"].password_tries, docs["Vertrag.docx"].password_tries) == (1, 1)
    assert docs["Paket.zip"].password_tries == 3  # the contacts' passwords by id, its own last
    # without its password: locked, every password offered and tried, so not offered again
    geheim = docs["Geheim.pdf"]
    assert (geheim.protection, geheim.text_status, geheim.extracted_text) == (
        "locked",
        "encrypted",
        None,
    )
    assert (geheim.password_tries, geheim.password_tried_until) == (3, last)
    assert geheim.password_tried_at is not None
    # ODF is detected, not opened (D239): offered, never tried
    notiz = docs["Notiz.odt"]
    assert (notiz.protection, notiz.password_tries, notiz.password_tried_until) == (
        "locked",
        0,
        last,
    )
    # how far the scan got
    [scan] = await fetch(imported_url, "SELECT value FROM global_stats WHERE key = 'passwords'")
    assert scan.value["version"] == CANDIDATES_VERSION
    assert scan.value["mail_until"] == max(ids.values())
    [job] = await fetch(imported_url, "SELECT progress FROM job")
    steps = {s.key: s for s in ImportProgress.model_validate(job.progress).steps}
    assert (steps["passwords"].status, steps["passwords"].total, steps["passwords"].done) == (
        "done",
        5,  # Liste.pdf, Vertrag.docx, Geheim.pdf, Notiz.odt and Paket.zip
        5,
    )


async def test_waiting_and_the_locked_marks(url: str, mbox_dir: Path) -> None:
    # the texts of the documents opened by the import are new: they may hold passwords
    assert await waiting_now(url) == 2
    assert (await run(url, mbox_dir)).locked == 2
    assert await waiting_now(url) == 0
    await add_mail(url, "Nichts Neues.")
    assert await waiting_now(url) == 2
    await run(url, mbox_dir)
    assert await waiting_now(url) == 0
    await execute(url, "INSERT INTO password (value) VALUES ('nie-angeboten')")
    assert await waiting_now(url) == 2  # a password no locked document was offered
    await run(url, mbox_dir)
    assert await waiting_now(url) == 0
    # a document the text extraction found encrypted is marked locked by the step
    await execute(url, "UPDATE document SET text_status = 'encrypted' WHERE name = 'Bericht.txt'")
    assert await waiting_now(url) == 3
    result = await run(url, mbox_dir)
    assert (result.locked, result.opened) == (3, 0)
    bericht = (await documents(url))["Bericht.txt"]
    assert (bericht.protection, bericht.password_tries) == ("locked", 0)  # no password opens text
    assert await waiting_now(url) == 0
    # nothing locked: nothing to do, whatever is new
    await execute(url, "UPDATE document SET protection = NULL, text_status = 'text'")
    await add_mail(url, "Kennwort: Neu-1")
    assert await waiting_now(url) == 0


async def test_the_scan_reads_only_what_is_new(
    url: str, mbox_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run(url, mbox_dir)
    ids = await mail_ids(url)
    await execute(url, "DELETE FROM password_finding WHERE mail_id = :mail", mail=ids[1])
    new_mail = await add_mail(url, "Hallo,\nder Zugangscode ist Neu-42\nGruß")
    await execute(
        url,
        "UPDATE document SET extracted_text = 'PIN: Doku-7', extracted_at = now() "
        "WHERE name = 'Bericht.txt'",
    )
    bericht = (await documents(url))["Bericht.txt"].id
    result = await run(url, mbox_dir)
    assert result.found == 2
    assert await findings(url) == [
        (VERTRAG_PASSWORD, ids[2], None, f"Passwort: {VERTRAG_PASSWORD}"),
        (PAKET_PASSWORD, ids[7], None, f"PIN: {PAKET_PASSWORD}"),
        ("Neu-42", new_mail, None, "der Zugangscode ist Neu-42"),  # the mails first
        ("Doku-7", None, bericht, "PIN: Doku-7"),
    ]
    # nothing new: nothing found, and the finding deleted from an old mail stays away
    assert (await run(url, mbox_dir)).found == 0
    assert len(await findings(url)) == 4
    # a new rule scans everything again
    monkeypatch.setattr(phase, "CANDIDATES_VERSION", CANDIDATES_VERSION + 1)
    assert (await run(url, mbox_dir)).found == 5
    assert (LISTE_PASSWORD, ids[1], None, f"Das Kennwort lautet: {LISTE_PASSWORD}") in (
        await findings(url)
    )
    [scan] = await fetch(url, "SELECT value FROM global_stats WHERE key = 'passwords'")
    assert scan.value["version"] == CANDIDATES_VERSION + 1


async def test_only_new_passwords_are_offered(url: str, mbox_dir: Path) -> None:
    before = (await documents(url))["Geheim.pdf"]
    await add_mail(url, "Kennwort: Falsch-1")
    await run(url, mbox_dir)
    docs = await documents(url)
    top = int((await fetch(url, "SELECT max(id) AS id FROM password"))[0].id)
    assert (docs["Geheim.pdf"].password_tries, docs["Geheim.pdf"].password_tried_until) == (
        before.password_tries + 1,
        top,
    )
    assert docs["Geheim.pdf"].protection == "locked"
    assert (docs["Notiz.odt"].password_tries, docs["Notiz.odt"].password_tried_until) == (0, top)
    # its password, written later anywhere in the archive, opens it
    late = await add_mail(url, f"Das Kennwort ist {GEHEIM_PASSWORD}")
    result = await run(url, mbox_dir)
    assert (result.locked, result.opened) == (2, 1)
    geheim = (await documents(url))["Geheim.pdf"]
    assert (geheim.protection, geheim.password, geheim.tier) == ("open", GEHEIM_PASSWORD, "archive")
    assert (geheim.text_status, geheim.extracted_text) == ("text", "Nur für den Vorstand")
    assert geheim.password_tries == before.password_tries + 2
    [finding] = await fetch(
        url, "SELECT mail_id FROM password_finding WHERE id = :id", id=geheim.finding_id
    )
    assert finding.mail_id == late


async def test_one_broken_document_does_not_end_the_step(
    url: str, mbox_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    await relock(url, "Liste.pdf")
    await execute(url, "UPDATE document SET password_tried_until = 0 WHERE name = 'Geheim.pdf'")
    real = protected.try_passwords

    async def broken(data: bytes, filename: str | None, *args: Any, **kwargs: Any) -> Any:
        if filename == "Geheim.pdf":
            raise RuntimeError("kaputt")
        return await real(data, filename, *args, **kwargs)

    monkeypatch.setattr(phase, "try_passwords", broken)
    caplog.set_level(logging.WARNING, logger="mailrobbe")
    result = await run(url, mbox_dir)
    assert result.opened == 1
    docs = await documents(url)
    assert (docs["Liste.pdf"].protection, docs["Liste.pdf"].tier) == ("open", "thread")
    assert (docs["Geheim.pdf"].protection, docs["Geheim.pdf"].password_tried_until) == ("locked", 0)
    assert f"document {docs['Geheim.pdf'].id}: trying passwords failed: " in caplog.text


async def test_an_unreadable_document_waits_for_its_file(
    url: str, mbox_dir: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    await add_mail(url, f"Kennwort: {GEHEIM_PASSWORD}")
    caplog.set_level(logging.WARNING, logger="mailrobbe")
    assert (await run(url, tmp_path)).opened == 0  # the MBOX file is missing
    geheim = (await documents(url))["Geheim.pdf"]
    assert (geheim.protection, geheim.password_tries) == ("locked", 3)
    assert f"document {geheim.id} could not be read to open it" in caplog.text
    assert await waiting_now(url) == 2  # its new password was not offered yet
    assert (await run(url, mbox_dir)).opened == 1
    assert (await documents(url))["Geheim.pdf"].protection == "open"


async def test_a_child_over_its_time_limit_counts_its_passwords_as_tried(
    url: str, mbox_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    await relock(url, "Liste.pdf")
    monkeypatch.setattr(protected, "_GRACE", 0.0)
    caplog.set_level(logging.WARNING, logger="mailrobbe")
    result = await run(url, mbox_dir, password_seconds=0, attachment_text_timeout=0.01)
    assert result.opened == 0
    liste = (await documents(url))["Liste.pdf"]
    assert (liste.protection, liste.password_tries) == ("locked", len(PASSWORDS))
    assert "trying passwords: stopped after the time limit of 0.01 s" in caplog.text


async def test_a_stop_leaves_the_rest_to_the_next_run(url: str, mbox_dir: Path) -> None:
    await relock(url, "Liste.pdf")
    await add_mail(url, "Kennwort: Spaeter-1")
    stop = asyncio.Event()
    stop.set()
    result = await run(url, mbox_dir, stop)
    assert (result.opened, result.found) == (0, 0)
    assert (await documents(url))["Liste.pdf"].protection == "locked"
    result = await run(url, mbox_dir)
    assert (result.opened, result.found) == (1, 1)

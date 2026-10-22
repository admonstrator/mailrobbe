"""The archives step of an import (D231, D232) on ARCHIVE (tests/passwords/samples.py): the
members one import lists, and unpack_containers on copies of it: an opened container, a locked
one waiting for its password, a missing MBOX file, no 7-Zip command, a new MEMBERS_VERSION and a
container found inside another one that a mail later carries itself."""

import asyncio
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.attachments import containers
from mailrobbe.attachments.containers import (
    ArchivesResult,
    WaitingContainer,
    unpack_containers,
    waiting_containers,
)
from mailrobbe.attachments.content import attachment_source, read_attachment
from mailrobbe.config import Settings
from mailrobbe.db.models import MEMBERS_VERSION
from mailrobbe.db.session import create_sessionmaker
from mailrobbe.jobrun import Step
from mailrobbe.jobs import ImportProgress
from mailrobbe.passwords.store import Opener, store_opened
from tests.importer.doubles import write_mbox
from tests.passwords.samples import (
    AKTEN,
    ANLAGE,
    BERICHT,
    CARL,
    DORA,
    INNER,
    MBOX_NAME,
    PAKET_PASSWORD,
    PLAN,
    ZIP_MIME,
    copied,
    documents,
    execute,
    fetch,
    import_archive,
    imported,
    mail,
    mail_ids,
    needs_seven_zip,
    write_archive,
)

pytestmark = [pytest.mark.db, pytest.mark.slow, needs_seven_zip]


@pytest.fixture(scope="module")
def mbox_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_archive(tmp_path_factory.mktemp("containers") / "mbox")


@pytest.fixture(scope="module")
def imported_url(database_server_url: str, mbox_dir: Path) -> Iterator[str]:
    """ARCHIVE imported once: Paket.zip is open, not unpacked yet. Read only."""
    with imported(database_server_url, mbox_dir) as url:
        yield url


@pytest.fixture
def url(database_server_url: str, imported_url: str) -> Iterator[str]:
    with copied(database_server_url, imported_url) as copy:
        yield copy


async def waiting(url: str) -> list[WaitingContainer]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with create_sessionmaker(engine)() as session:
            return await waiting_containers(session)
    finally:
        await engine.dispose()


async def unpack(url: str, mbox_dir: Path) -> ArchivesResult:
    """One archives step, as the import runs it."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        sessionmaker = create_sessionmaker(engine)
        async with sessionmaker() as session:
            found = await waiting_containers(session)
        return await unpack_containers(
            sessionmaker, Settings(database_url=url), mbox_dir, found, 2, asyncio.Event(), Step()
        )
    finally:
        await engine.dispose()


async def members(url: str, name: str) -> list[tuple[Any, ...]]:
    """The entries of the container with this name: position, path, size, status, member."""
    rows = await fetch(
        url,
        "SELECT dm.position, dm.path, dm.size_bytes, dm.status::text AS status, m.name AS member "
        "FROM document_member dm JOIN document c ON c.id = dm.container_id "
        "LEFT JOIN document m ON m.id = dm.member_id WHERE c.name = :name ORDER BY dm.position",
        name=name,
    )
    return [tuple(row) for row in rows]


async def member_attachments(url: str) -> list[tuple[Any, ...]]:
    """Every member attachment: its mail, container, path, file name, MIME type, document."""
    rows = await fetch(
        url,
        "SELECT a.mail_id, c.filename AS container, a.path, a.filename, a.mime_type, "
        "d.name AS document FROM attachment a JOIN attachment c ON c.id = a.container_id "
        "LEFT JOIN document d ON d.id = a.document_id ORDER BY a.mail_id, c.id, a.position",
    )
    return [tuple(row) for row in rows]


async def test_one_import_unpacks_what_it_can_open(imported_url: str) -> None:
    ids = await mail_ids(imported_url)
    docs = await documents(imported_url)

    def listed(name: str) -> tuple[Any, ...]:
        doc = docs[name]
        return (doc.members_status, doc.members_version, doc.members_error, doc.protection)

    assert listed("Akten.zip") == ("done", MEMBERS_VERSION, None, None)
    assert await members(imported_url, "Akten.zip") == [
        (0, "Bericht.txt", len(BERICHT), "document", "Bericht.txt"),
        (1, "Ordner/Notiz.txt", len(AKTEN["Ordner/Notiz.txt"]), "document", "Notiz.txt"),
        (2, "inner.zip", docs["inner.zip"].size_bytes, "document", "inner.zip"),
    ]
    assert listed("Weitergeleitet.eml") == ("done", MEMBERS_VERSION, None, None)
    assert await members(imported_url, "Weitergeleitet.eml") == [
        (0, "Anlage.txt", len(ANLAGE), "document", "Anlage.txt")
    ]
    # in a container in a container: listed where it is, not unpacked (depth 2)
    assert listed("inner.zip") == ("too_deep", MEMBERS_VERSION, None, None)
    assert await members(imported_url, "inner.zip") == []
    # listed locked before its password was known, opened by the passwords step that followed:
    # unpacked by the next run
    assert listed("Paket.zip") == (None, 0, None, "open")
    assert await members(imported_url, "Paket.zip") == [
        (0, "Plan.txt", len(PLAN), "locked", None)  # the ZIP lists its size unencrypted
    ]
    # each readable entry an attachment of the mail carrying the container
    assert await member_attachments(imported_url) == [
        (ids[4], "Akten.zip", "Bericht.txt", "Bericht.txt", "text/plain", "Bericht.txt"),
        (ids[4], "Akten.zip", "Ordner/Notiz.txt", "Notiz.txt", "text/plain", "Notiz.txt"),
        (ids[4], "Akten.zip", "inner.zip", "inner.zip", ZIP_MIME, "inner.zip"),
        (ids[5], "Weitergeleitet.eml", "Anlage.txt", "Anlage.txt", "text/plain", "Anlage.txt"),
    ]
    # the members got their text in the same run (the attachments step follows)
    for name, data in (("Bericht.txt", BERICHT), ("Anlage.txt", ANLAGE)):
        assert (docs[name].text_status, docs[name].extracted_text) == (
            "text",
            data.decode().strip(),
        ), name
    assert (docs["inner.zip"].kind_name, docs["inner.zip"].mails) == ("archive", 1)
    [job] = await fetch(imported_url, "SELECT progress FROM job")
    steps = {s.key: s for s in ImportProgress.model_validate(job.progress).steps}
    archives = steps["archives"]
    assert (archives.status, archives.total, archives.done) == ("done", 3, 3)
    assert list(steps).index("archives") < list(steps).index("attachments")


async def test_an_opened_container_is_unpacked_with_its_password(url: str, mbox_dir: Path) -> None:
    ids = await mail_ids(url)
    docs = await documents(url)
    paket = docs["Paket.zip"]
    [carrier] = await fetch(
        url,
        "SELECT id FROM attachment WHERE document_id = :id AND container_id IS NULL",
        id=paket.id,
    )
    assert await waiting(url) == [
        WaitingContainer(paket.id, carrier.id, "Paket.zip", ZIP_MIME, PAKET_PASSWORD)
    ]
    result = await unpack(url, mbox_dir)
    assert (result.containers, result.unpacked, result.members) == (1, 1, 1)
    docs = await documents(url)
    assert (docs["Paket.zip"].members_status, docs["Paket.zip"].protection) == ("done", "open")
    assert await members(url, "Paket.zip") == [(0, "Plan.txt", len(PLAN), "document", "Plan.txt")]
    assert (ids[6], "Paket.zip", "Plan.txt", "Plan.txt", "text/plain", "Plan.txt") in (
        await member_attachments(url)
    )
    assert docs["Plan.txt"].text_status == "pending"  # read by the attachments step that follows
    assert await waiting(url) == []


async def test_a_locked_container_waits_for_its_password(url: str) -> None:
    paket = (await documents(url))["Paket.zip"]
    await execute(
        url,
        "DELETE FROM document_password WHERE document_id = :id",
        "UPDATE document SET protection = 'locked', members_status = 'locked', "
        "members_version = :version WHERE id = :id",
        id=paket.id,
        version=MEMBERS_VERSION,
    )
    assert await waiting(url) == []
    [password] = await fetch(url, "SELECT id FROM password WHERE value = :v", v=PAKET_PASSWORD)
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with create_sessionmaker(engine)() as session, session.begin():
            await store_opened(session, paket.id, Opener(password.id, None, "typed", "Aaron"), None)
    finally:
        await engine.dispose()
    [found] = await waiting(url)
    assert (found.document_id, found.password) == (paket.id, PAKET_PASSWORD)


async def test_an_unreadable_container_waits_for_its_file(
    url: str, mbox_dir: Path, tmp_path: Path
) -> None:
    await execute(url, "UPDATE document SET members_status = NULL WHERE name = 'Akten.zip'")
    before = await member_attachments(url)
    result = await unpack(url, tmp_path)  # the MBOX file is missing
    assert (result.containers, result.unpacked) == (2, 0)
    docs = await documents(url)
    for name in ("Akten.zip", "Paket.zip"):
        assert (docs[name].members_status, docs[name].members_version) == (
            "unreadable",
            MEMBERS_VERSION,
        ), name
        assert MBOX_NAME in docs[name].members_error, name
    # what was listed before stays until it is read again
    assert len(await members(url, "Akten.zip")) == 3
    assert await member_attachments(url) == before
    assert {c.document_id for c in await waiting(url)} == {
        docs["Akten.zip"].id,
        docs["Paket.zip"].id,
    }
    assert (await unpack(url, mbox_dir)).unpacked == 2
    assert len(await members(url, "Akten.zip")) == 3
    assert len(await member_attachments(url)) == len(before) + 1  # Plan.txt
    assert await waiting(url) == []


async def test_without_7zip_only_attached_mails_are_unpacked(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await execute(
        url, "UPDATE document SET members_status = NULL WHERE kind IN ('archive', 'email')"
    )
    docs = await documents(url)
    everything = [docs[name].id for name in ("Weitergeleitet.eml", "Paket.zip", "Akten.zip")]
    # inner.zip has no occurrence of its own in a mail
    assert sorted(c.document_id for c in await waiting(url)) == sorted(everything)
    monkeypatch.setattr(containers, "SEVEN_ZIP", False)
    assert [c.document_id for c in await waiting(url)] == [docs["Weitergeleitet.eml"].id]


async def test_a_new_members_version_lists_every_container_again(
    url: str, mbox_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await unpack(url, mbox_dir)  # Paket.zip
    names = ("Akten.zip", "Weitergeleitet.eml", "Paket.zip")
    listed = {name: await members(url, name) for name in names}
    attachments = await member_attachments(url)
    document_ids = {name: doc.id for name, doc in (await documents(url)).items()}
    monkeypatch.setattr(containers, "MEMBERS_VERSION", MEMBERS_VERSION + 1)
    assert len(await waiting(url)) == 3
    assert (await unpack(url, mbox_dir)).unpacked == 3
    # the same entries and documents, none twice; the member documents keep their text
    assert {name: await members(url, name) for name in names} == listed
    assert await member_attachments(url) == attachments
    docs = await documents(url)
    assert {name: doc.id for name, doc in docs.items()} == document_ids
    assert docs["Bericht.txt"].extracted_text == BERICHT.decode().strip()
    assert {docs[name].members_version for name in names} == {MEMBERS_VERSION + 1}
    assert docs["inner.zip"].members_version == MEMBERS_VERSION
    assert await waiting(url) == []


async def test_a_container_a_mail_carries_itself_is_unpacked(
    url: str, mbox_dir: Path, tmp_path: Path
) -> None:
    """inner.zip, too deep in Akten.zip, sent on its own later: unpacked for that mail."""
    [inner] = await fetch(url, "SELECT id FROM attachment WHERE path = 'inner.zip'")
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            source = await attachment_source(connection, inner.id)
    finally:
        await engine.dispose()
    assert source is not None and source.container is not None
    data = read_attachment(mbox_dir, source)  # read through Akten.zip
    copy = tmp_path / "mbox"
    copy.mkdir()
    shutil.copy(mbox_dir / MBOX_NAME, copy / MBOX_NAME)
    later = mail(8, CARL, DORA, "Innen", "Das innere Archiv.\n", [("inner.zip", ZIP_MIME, data)])
    write_mbox(copy / "zweite.mbox", [later.as_bytes()])
    await asyncio.to_thread(import_archive, url, copy)
    ids = await mail_ids(url)
    docs = await documents(url)
    assert (docs["inner.zip"].members_status, docs["inner.zip"].mails) == ("done", 2)
    assert await members(url, "inner.zip") == [
        (0, "tief.txt", len(INNER["tief.txt"]), "document", "tief.txt")
    ]
    # a member of the mail carrying it itself only: Akten.zip still lists it as an entry
    tief = [row for row in await member_attachments(url) if row[2] == "tief.txt"]
    assert tief == [(ids[8], "inner.zip", "tief.txt", "tief.txt", "text/plain", "tief.txt")]
    assert docs["tief.txt"].extracted_text == INNER["tief.txt"].decode().strip()

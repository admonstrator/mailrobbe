"""passwords.store (D234, D236, D237): findings once per place, the passwords offered and tried,
and an opened document, with and without the text read with its password."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.attachments.extract import Extraction
from mailrobbe.db.models import EXTRACTOR_VERSION
from mailrobbe.enums import DocumentKind, DocumentTextStatus
from mailrobbe.passwords.store import Finding, Opener, record_tried, store_findings, store_opened

pytestmark = pytest.mark.db

_ROWS = (
    "INSERT INTO mbox_file (id, path, size_bytes) VALUES (1, 'a.mbox', 100000)",
    "INSERT INTO mail (id, mbox_file_id, byte_offset, byte_length, raw_sha256) "
    "OVERRIDING SYSTEM VALUE VALUES (1, 1, 0, 100, 'a'), (2, 1, 100, 100, 'b')",
    "INSERT INTO document (id, sha256, mime_type, size_bytes, text_status, protection, "
    "members_status, members_version, metadata_version) OVERRIDING SYSTEM VALUE VALUES "
    "(1, 'pdf', 'application/pdf', 100, 'encrypted', 'locked', NULL, 0, 3), "
    "(2, 'zip', 'application/zip', 100, 'text', 'locked', 'locked', 1, 3), "
    "(3, 'txt', 'text/plain', 100, 'text', NULL, NULL, 0, 3)",
)


@pytest.fixture
async def session(db_session: AsyncSession) -> AsyncSession:
    for statement in _ROWS:
        await db_session.execute(text(statement))
    return db_session


async def rows(session: AsyncSession, sql: str) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in await session.execute(text(sql))]


async def document(session: AsyncSession, document_id: int) -> dict[str, Any]:
    [row] = await rows(session, f"SELECT * FROM document WHERE id = {document_id}")
    return row


async def test_each_value_once_and_each_finding_once_per_place(session: AsyncSession) -> None:
    assert await store_findings(session, []) == {}
    ids = await store_findings(
        session,
        [
            Finding("Hafen-2019", "Kennwort: Hafen-2019", mail_id=1),
            Finding("Hafen-2019", "Kennwort: Hafen-2019", mail_id=1),  # the same place again
            Finding("Hafen-2019", "PW Hafen-2019", mail_id=2),
            Finding("Hafen-2019", "Kennwort: Hafen-2019", document_id=3),
            Finding("Nordlicht7", "Passwort: Nordlicht7", mail_id=2),
            Finding("Nordlicht7", editor="Aaron"),  # typed in by hand
        ],
    )
    assert set(ids) == {"Hafen-2019", "Nordlicht7"}
    # a later scan finds the same places again, a second editor types it in too
    again = await store_findings(
        session,
        [
            Finding("Hafen-2019", "Kennwort: Hafen-2019", mail_id=1),
            Finding("Nordlicht7", editor="Berta"),
            Finding("Wellen#5", "PIN: Wellen#5", mail_id=1),
        ],
    )
    assert {k: again[k] for k in ids} == ids
    assert again["Wellen#5"] > max(ids.values())  # ids grow: password_tried_until (D235)
    findings = await rows(
        session,
        "SELECT pw.value, f.mail_id, f.document_id, f.context, f.editor FROM password_finding f "
        "JOIN password pw ON pw.id = f.password_id ORDER BY f.id",
    )
    assert [tuple(f.values()) for f in findings] == [
        ("Hafen-2019", 1, None, "Kennwort: Hafen-2019", None),
        ("Hafen-2019", 2, None, "PW Hafen-2019", None),
        ("Hafen-2019", None, 3, "Kennwort: Hafen-2019", None),
        ("Nordlicht7", 2, None, "Passwort: Nordlicht7", None),
        ("Nordlicht7", None, None, "", "Aaron"),  # the first editor's finding stays
        ("Wellen#5", 1, None, "PIN: Wellen#5", None),
    ]


async def test_record_tried_keeps_the_highest_id_and_counts(session: AsyncSession) -> None:
    await record_tried(session, 1, 7, 3)
    await record_tried(session, 1, 5, 2)  # a lower id lowers nothing
    await record_tried(session, 1, 0, 1)  # as for a password typed in (api.protected)
    found = await document(session, 1)
    assert (found["password_tried_until"], found["password_tries"]) == (7, 6)
    assert found["password_tried_at"] is not None
    untouched = await document(session, 3)
    assert (untouched["password_tried_until"], untouched["password_tries"]) == (0, 0)


async def test_an_opened_document_gets_its_text(session: AsyncSession) -> None:
    ids = await store_findings(session, [Finding("Hafen-2019", "Kennwort", mail_id=2)])
    [finding] = await rows(session, "SELECT id FROM password_finding")
    opener = Opener(ids["Hafen-2019"], finding["id"], "thread")
    extraction = Extraction(
        DocumentTextStatus.TEXT, "Vertrauliche\x00 Liste", pages=2, kind=DocumentKind.PDF
    )
    await store_opened(session, 1, opener, extraction)
    found = await document(session, 1)
    assert found["protection"] == "open"
    assert (found["text_status"], found["extracted_text"], found["pages"]) == (
        "text",
        "Vertrauliche Liste",
        2,
    )
    assert (found["text_truncated"], found["text_error"]) == (False, None)
    assert found["extractor_version"] == EXTRACTOR_VERSION and found["extracted_at"] is not None
    assert found["metadata_version"] == 0  # read again by the metadata step, with the password
    [stored] = await rows(session, "SELECT * FROM document_password")
    assert (stored["document_id"], stored["password_id"], stored["finding_id"]) == (
        1,
        ids["Hafen-2019"],
        finding["id"],
    )
    assert (stored["tier"], stored["found_by"]) == ("thread", None)

    # typed in later: the one row says so
    await store_opened(session, 1, Opener(ids["Hafen-2019"], None, "typed", "Aaron"), extraction)
    [stored] = await rows(session, "SELECT * FROM document_password")
    assert (stored["finding_id"], stored["tier"], stored["found_by"]) == (None, "typed", "Aaron")


async def test_an_opened_container_waits_for_the_archives_step(session: AsyncSession) -> None:
    ids = await store_findings(session, [Finding("Wellen#5", "PIN: Wellen#5", mail_id=1)])
    await store_opened(session, 2, Opener(ids["Wellen#5"], None, "contacts"), None)
    found = await document(session, 2)
    assert (found["protection"], found["members_status"], found["members_version"]) == (
        "open",
        None,
        0,
    )
    # its own text (the names of its entries) is left as it was
    assert (found["text_status"], found["metadata_version"]) == ("text", 3)
    [stored] = await rows(session, "SELECT document_id, tier FROM document_password")
    assert tuple(stored.values()) == (2, "contacts")

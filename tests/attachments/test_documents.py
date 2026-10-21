"""refresh_documents in finalize (D70): one document per content, figures, kinds, clean-up."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.attachments.documents import DocumentRefresh
from mailrobbe.importer.finalize import finalize
from mailrobbe.importer.model import ParsedAttachment, ParsedMail
from mailrobbe.importer.store import Batch, Store
from tests.importer.doubles import add_mbox_file, fetch, make_mail, make_record, message

PDF = "application/pdf"
CONTRACT = "c" * 64
PHOTO = "f" * 64
JAN = datetime(2024, 1, 10, tzinfo=UTC)
MAR = datetime(2024, 3, 5, tzinfo=UTC)


def _file(name: str | None, mime_type: str, size: int, sha256: str | None) -> ParsedAttachment:
    return ParsedAttachment(name, mime_type, size, sha256)


async def _store(session: AsyncSession, file_id: int, mails: list[tuple[int, ParsedMail]]) -> None:
    batch = Batch()
    for offset, mail in mails:
        batch.add(make_record(offset, message(offset)), mail)
    await Store().write(session, file_id, batch)


async def _documents(session: AsyncSession) -> dict[str | None, dict[str, object]]:
    """Documents by SHA-256 (the unhashed one under None)."""
    rows = await session.execute(
        text(
            "SELECT sha256, name, names, mime_type, size_bytes, kind::text, text_status::text, "
            "mails, attachments, first_date, last_date, first_mail_id FROM document"
        )
    )
    await session.commit()
    return {row.sha256: row._asdict() for row in rows}


@pytest.mark.db
async def test_one_document_per_content_with_figures_over_originals(
    db_session: AsyncSession,
) -> None:
    first = await add_mbox_file(db_session, "a.mbox")
    second = await add_mbox_file(db_session, "b.mbox")
    original = make_mail(
        message_id="<1@a.example>",
        subject="Vertrag",
        date_utc=JAN,
        attachments=(
            _file("Vertrag.pdf", PDF, 1000, CONTRACT),
            _file("IMG_1.jpg", "image/jpeg", 500, PHOTO),
        ),
    )
    later = make_mail(
        message_id="<2@a.example>",
        date_utc=MAR,
        attachments=(
            _file("Vertrag_final.pdf", "application/octet-stream", 1000, CONTRACT),
            _file("Archiv.zip", "application/zip", 90_000_000, None),
        ),
    )
    await _store(db_session, first, [(0, original), (1000, later)])
    await _store(db_session, second, [(0, original)])  # a duplicate of the first mail

    result = await finalize(db_session)

    assert result.documents == DocumentRefresh(assigned=6, changed=3, classified=3, deleted=0)
    documents = await _documents(db_session)
    assert set(documents) == {CONTRACT, PHOTO, None}
    ids = dict(await fetch(db_session, "SELECT message_id, min(id) FROM mail GROUP BY 1"))
    assert documents[CONTRACT] | {"first_mail_id": None} == {
        "sha256": CONTRACT,
        "name": "Vertrag.pdf",  # twice, once with the duplicate
        "names": "Vertrag.pdf\nVertrag_final.pdf",
        "mime_type": PDF,
        "size_bytes": 1000,
        "kind": "pdf",
        "text_status": "pending",
        "mails": 2,
        "attachments": 3,
        "first_date": JAN,
        "last_date": MAR,
        "first_mail_id": None,
    }
    assert documents[CONTRACT]["first_mail_id"] == ids["<1@a.example>"]
    assert (documents[PHOTO]["kind"], documents[PHOTO]["text_status"]) == ("image", "unsupported")
    assert documents[None]["kind"] == "archive"
    assert documents[None]["text_status"] == "pending"  # the names of a ZIP's members
    assert (documents[None]["mails"], documents[None]["names"]) == (1, "Archiv.zip")
    positions = await fetch(
        db_session, "SELECT filename, position FROM attachment ORDER BY mail_id, position"
    )
    assert positions[:2] == [("Vertrag.pdf", 0), ("IMG_1.jpg", 1)]
    unassigned = await fetch(
        db_session, "SELECT count(*) FROM attachment WHERE document_id IS NULL"
    )
    assert unassigned == [(0,)]

    again = await finalize(db_session)
    assert again.documents == DocumentRefresh(0, 0, 0, 0)


@pytest.mark.db
async def test_later_mails_join_documents_and_documents_without_attachments_go(
    db_session: AsyncSession,
) -> None:
    file_id = await add_mbox_file(db_session)
    contract = _file("Vertrag.pdf", PDF, 1000, CONTRACT)
    await _store(db_session, file_id, [(0, make_mail(date_utc=MAR, attachments=(contract,)))])
    await finalize(db_session)
    await db_session.execute(
        text("UPDATE document SET text_status = 'text', extracted_text = 'Vertragstext'")
    )
    await db_session.commit()

    earlier = make_mail(date_utc=JAN, attachments=(_file("v1.pdf", PDF, 1000, CONTRACT),))
    photo = make_mail(date_utc=JAN, attachments=(_file("a.jpg", "image/jpeg", 9, PHOTO),))
    await _store(db_session, file_id, [(1000, earlier), (2000, photo)])
    result = await finalize(db_session)

    assert result.documents.assigned == 2
    documents = await _documents(db_session)
    assert documents[CONTRACT]["text_status"] == "text"  # extracted once, kept
    assert documents[CONTRACT]["names"] == "Vertrag.pdf\nv1.pdf"
    assert (documents[CONTRACT]["mails"], documents[CONTRACT]["first_date"]) == (2, JAN)

    await db_session.execute(text("DELETE FROM mail WHERE byte_offset = 2000"))
    await db_session.commit()
    result = await finalize(db_session)
    assert result.documents.deleted == 1
    assert set(await _documents(db_session)) == {CONTRACT}

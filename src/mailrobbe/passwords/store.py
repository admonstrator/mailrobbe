"""The one place writing the password tables (D234 to D237): findings, tries and opened documents.

The passwords step (passwords.phase) and the passwords typed in through the API (api.passwords)
both write through here, in the caller's transaction.

    store_findings   `password` keeps each distinct value once, `password_finding` where it
                     stands (a mail, a document, or neither with an editor for a typed-in one)
    record_tried     the highest password id offered to a document and how many were tried
    store_opened     document_password with where the password was found and its tier; the
                     document is set open and gets its text (or, for a container, is unpacked
                     again by the next archives step) and its metadata is read again (D236)
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.attachments.extract import Extraction
from mailrobbe.db.models import EXTRACTOR_VERSION


@dataclass(frozen=True, slots=True)
class Finding:
    value: str
    context: str = ""  # the line(s) it stands in (D208)
    mail_id: int | None = None
    document_id: int | None = None
    editor: str | None = None  # a password typed in by hand (D237)


@dataclass(frozen=True, slots=True)
class Opener:
    """The password that opened a document and where it came from (D236)."""

    password_id: int
    finding_id: int | None
    tier: str  # a PasswordTier value
    found_by: str | None = None  # the editor who typed it in (tier typed)


async def store_findings(session: AsyncSession, findings: Sequence[Finding]) -> dict[str, int]:
    """Store the findings; the id of every value."""
    values = sorted({f.value for f in findings})
    if not values:
        return {}
    await session.execute(
        text(
            "INSERT INTO password (value) SELECT unnest(CAST(:values AS text[])) "
            "ON CONFLICT (value) DO NOTHING"
        ),
        {"values": values},
    )
    rows = await session.execute(
        text("SELECT value, id FROM password WHERE value = ANY(CAST(:values AS text[]))"),
        {"values": values},
    )
    ids: dict[str, int] = {value: pid for value, pid in rows}
    await session.execute(
        text(
            "INSERT INTO password_finding (password_id, mail_id, document_id, context, editor) "
            "VALUES (:password_id, :mail_id, :document_id, :context, :editor) "
            "ON CONFLICT ON CONSTRAINT uq_password_finding_place DO NOTHING"
        ),
        [
            {
                "password_id": ids[f.value],
                "mail_id": f.mail_id,
                "document_id": f.document_id,
                "context": f.context,
                "editor": f.editor,
            }
            for f in findings
        ],
    )
    return ids


async def record_tried(session: AsyncSession, document_id: int, until: int, tried: int) -> None:
    """Every password up to `until` was offered to the document; `tried` of them were tried."""
    await session.execute(
        text(
            "UPDATE document SET "
            "password_tried_until = GREATEST(password_tried_until, :until), "
            "password_tries = password_tries + :tries, password_tried_at = now() "
            "WHERE id = :id"
        ),
        {"id": document_id, "until": until, "tries": tried},
    )


async def store_opened(
    session: AsyncSession,
    document_id: int,
    opener: Opener,
    extraction: Extraction | None,
) -> None:
    """Store the password that opened the document and open it (D236). `extraction` is the
    text read with the password; None for a container, which the next archives step unpacks
    again with the password."""
    await session.execute(
        text(
            "INSERT INTO document_password "
            "(document_id, password_id, finding_id, tier, found_by) "
            "VALUES (:document_id, :password_id, :finding_id, "
            "CAST(:tier AS password_tier), :found_by) "
            "ON CONFLICT (document_id) DO UPDATE SET password_id = excluded.password_id, "
            "finding_id = excluded.finding_id, tier = excluded.tier, "
            "found_by = excluded.found_by, found_at = now()"
        ),
        {
            "document_id": document_id,
            "password_id": opener.password_id,
            "finding_id": opener.finding_id,
            "tier": opener.tier,
            "found_by": opener.found_by,
        },
    )
    if extraction is None:
        await session.execute(
            text(
                "UPDATE document SET protection = 'open', members_status = NULL, "
                "members_version = 0 WHERE id = :id"
            ),
            {"id": document_id},
        )
        return
    await session.execute(
        text(
            "UPDATE document SET protection = 'open', "
            "text_status = CAST(:status AS document_text_status), extracted_text = :text, "
            "text_truncated = :truncated, text_error = :error, pages = :pages, "
            "extractor_version = :version, extracted_at = now(), metadata_version = 0 "
            "WHERE id = :id"
        ),
        {
            "id": document_id,
            "status": extraction.status.value,
            "text": _clean(extraction.text) or None,
            "truncated": extraction.truncated,
            "error": extraction.error,
            "pages": extraction.pages,
            "version": EXTRACTOR_VERSION,
        },
    )


def _clean(value: str) -> str:
    return value.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")

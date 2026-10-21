"""Documents (D70): every distinct attachment content once, assigned and counted by finalize.

refresh_documents runs in finalize after duplicates and threads, in the caller's transaction:

    assign      a document for each new SHA-256 (shared by every attachment with it), one of
                its own for each attachment too large to hash (D18); attachment.document_id
    figures     per document over its attachments: mails that are not duplicates, every
                attachment, first and last date, the earliest mail, the file name used most,
                every file name and the MIME type declared most
    classify    kind for documents that have none yet (attachments.kinds, from name and MIME
                type); formats without text extraction become unsupported at once, so the
                attachments phase never reads them
    orphans     documents left without attachments (their file was replaced, D14) are deleted

Every step is set-based and writes only rows whose values change, like the rest of finalize.
The text extraction (the import's attachments phase, D72) works on the documents afterwards.
"""

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, Executable, text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.attachments.kinds import classify
from mailrobbe.enums import DocumentTextStatus

# names keeps this many characters: every file name a document was sent under, for the search.
NAMES_LIMIT = 10_000

_NEW_HASHED = text("""
    INSERT INTO document (sha256, mime_type, size_bytes)
    SELECT sha256, mode() WITHIN GROUP (ORDER BY mime_type COLLATE "C"), max(size_bytes)
    FROM attachment WHERE document_id IS NULL AND sha256 IS NOT NULL
    GROUP BY sha256 ORDER BY sha256
    ON CONFLICT (sha256) DO NOTHING
""")
_ASSIGN_HASHED = text("""
    UPDATE attachment a SET document_id = d.id FROM document d
    WHERE a.document_id IS NULL AND a.sha256 IS NOT NULL AND d.sha256 = a.sha256
""")
# The new document ids are drawn first, so each unhashed attachment knows its own.
_ASSIGN_UNHASHED = text("""
    WITH todo AS MATERIALIZED (
        SELECT id, nextval(pg_get_serial_sequence('document', 'id')) AS document_id,
            mime_type, size_bytes
        FROM attachment WHERE document_id IS NULL AND sha256 IS NULL ORDER BY id
    ), created AS (
        INSERT INTO document (id, mime_type, size_bytes)
        SELECT document_id, mime_type, size_bytes FROM todo
    )
    UPDATE attachment a SET document_id = todo.document_id FROM todo WHERE a.id = todo.id
""")
_FIGURES = text(f"""
    WITH figures AS (
        SELECT a.document_id,
            count(DISTINCT a.mail_id) FILTER (WHERE m.is_duplicate_of IS NULL) AS mails,
            count(*) AS attachments,
            min(m.date_utc) FILTER (WHERE m.is_duplicate_of IS NULL) AS first_date,
            max(m.date_utc) FILTER (WHERE m.is_duplicate_of IS NULL) AS last_date,
            -- ties and the list in byte order, whatever the database's collation
            mode() WITHIN GROUP (ORDER BY a.filename COLLATE "C") AS name,
            left(COALESCE(string_agg(DISTINCT a.filename COLLATE "C", E'\\n'
                ORDER BY a.filename COLLATE "C"), ''), {NAMES_LIMIT}) AS names,
            mode() WITHIN GROUP (ORDER BY a.mime_type COLLATE "C") AS mime_type
        FROM attachment a JOIN mail m ON m.id = a.mail_id
        WHERE a.document_id IS NOT NULL
        GROUP BY a.document_id
    ), firsts AS (  -- the earliest original, undated ones last
        SELECT DISTINCT ON (a.document_id) a.document_id, m.id AS mail_id
        FROM attachment a JOIN mail m ON m.id = a.mail_id
        WHERE a.document_id IS NOT NULL
        ORDER BY a.document_id, m.is_duplicate_of IS NOT NULL, m.date_utc, m.id
    )
    UPDATE document d SET mails = f.mails, attachments = f.attachments,
        first_date = f.first_date, last_date = f.last_date, first_mail_id = firsts.mail_id,
        name = f.name, names = f.names, mime_type = f.mime_type
    FROM figures f JOIN firsts ON firsts.document_id = f.document_id
    WHERE d.id = f.document_id
      AND (d.mails, d.attachments, d.first_date, d.last_date, d.first_mail_id, d.name, d.names,
           d.mime_type)
          IS DISTINCT FROM (f.mails, f.attachments, f.first_date, f.last_date, firsts.mail_id,
           f.name, f.names, f.mime_type)
""")
_UNCLASSIFIED = text("SELECT id, name, mime_type FROM document WHERE kind IS NULL ORDER BY id")
_CLASSIFY = text("""
    UPDATE document d SET kind = CAST(u.kind AS document_kind),
        text_status = CASE WHEN u.extractable THEN d.text_status
            ELSE CAST(:unsupported AS document_text_status) END
    FROM unnest(CAST(:ids AS bigint[]), CAST(:kinds AS text[]), CAST(:extractable AS boolean[]))
        AS u(id, kind, extractable)
    WHERE d.id = u.id
""")
_ORPHANS = text("""
    DELETE FROM document d WHERE NOT EXISTS (SELECT 1 FROM attachment a WHERE a.document_id = d.id)
""")


@dataclass(frozen=True, slots=True)
class DocumentRefresh:
    """Rows changed by one refresh_documents."""

    assigned: int  # attachments that got their document
    changed: int  # documents whose figures changed
    classified: int  # documents that got their kind
    deleted: int  # documents without attachments, removed


async def refresh_documents(session: AsyncSession) -> DocumentRefresh:
    """Assign, count, classify and clean up documents; see the module docstring."""
    await session.execute(_NEW_HASHED)
    assigned = await _changed(session, _ASSIGN_HASHED)
    assigned += await _changed(session, _ASSIGN_UNHASHED)
    if assigned:
        # The statistics may still say no attachment has a document (the first finalize after
        # an import): planned on them, _FIGURES reads every attachment once per document (D110).
        await session.execute(text("ANALYZE attachment"))
    changed = await _changed(session, _FIGURES)
    rows = (await session.execute(_UNCLASSIFIED)).all()
    if rows:
        formats = [classify(name, mime_type) for _, name, mime_type in rows]
        await session.execute(
            _CLASSIFY,
            {
                "ids": [row.id for row in rows],
                "kinds": [fmt.kind.value for fmt in formats],
                "extractable": [fmt.extractable for fmt in formats],
                "unsupported": DocumentTextStatus.UNSUPPORTED.value,
            },
        )
    deleted = await _changed(session, _ORPHANS)
    return DocumentRefresh(assigned, changed, len(rows), deleted)


async def _changed(session: AsyncSession, statement: Executable) -> int:
    result = cast(CursorResult[Any], await session.execute(statement))
    return result.rowcount

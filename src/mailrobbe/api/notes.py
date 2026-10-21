"""Notes on mails (D56): any number per mail, each with its author (D54), editable and
deletable by anyone. Routes: POST /api/mails/{id}/notes, PATCH and DELETE /api/notes/{id},
GET /api/notes.

A note belongs to its mail's content (D53): byte-identical copies share it, and it stays when
the content leaves the archive; the list then shows it without a mail. The list pages newest
first by keyset on (created_at, id), with cursors bound to q as in the person list; q is a
part of the text in any case, which ix_note_body_trgm serves from three characters on.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import case, delete, func, select, true, tuple_, update
from sqlalchemy.dialects import postgresql

from mailrobbe.api.deps import Editor, Session, api_error
from mailrobbe.api.detail import NOTE_COLUMNS, MailId, mail_senders
from mailrobbe.api.filters import _contains
from mailrobbe.api.persons import _Cursor, _int, _stamp
from mailrobbe.api.research import RowId, mail_sha256, trimmed
from mailrobbe.api.schemas import (
    NoteCreate,
    NoteEdit,
    NoteInfo,
    NoteItem,
    NoteListParams,
    NoteMail,
    NotePage,
)
from mailrobbe.db.models import Mail, Note

router = APIRouter(prefix="/api", tags=["research"])


@router.post("/mails/{mail_id}/notes", status_code=201)
async def add_note(mail_id: MailId, note: NoteCreate, session: Session, editor: Editor) -> NoteInfo:
    sha = await mail_sha256(session, mail_id)
    added = postgresql.insert(Note).values(
        mail_sha256=sha, body=trimmed(note.body, "body"), author=editor
    )
    row = (await session.execute(added.returning(*NOTE_COLUMNS))).one()
    await session.commit()
    return NoteInfo(**row._mapping)


@router.patch("/notes/{note_id}")
async def edit_note(note_id: RowId, edit: NoteEdit, session: Session) -> NoteInfo:
    """The new text; updated_at moves when it differs. The author stays the one who wrote it."""
    body = trimmed(edit.body, "body")
    edited = (
        update(Note)
        .where(Note.id == note_id)
        .values(body=body, updated_at=case((Note.body == body, Note.updated_at), else_=func.now()))
        .returning(*NOTE_COLUMNS)
    )
    row = (await session.execute(edited)).one_or_none()
    if row is None:
        raise api_error(404, "not_found", f"no note with id {note_id}")
    await session.commit()
    return NoteInfo(**row._mapping)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: RowId, session: Session) -> Response:
    if await session.scalar(delete(Note).where(Note.id == note_id).returning(Note.id)) is None:
        raise api_error(404, "not_found", f"no note with id {note_id}")
    await session.commit()
    return Response(status_code=204)


@router.get("/notes")
async def list_notes(params: Annotated[NoteListParams, Query()], session: Session) -> NotePage:
    """Every note, or those whose text contains q, newest first; each with the original of its
    mails (no duplicate, lowest id), or none when its content is not in the archive."""
    q = params.q.strip()
    scope = f"notes/{q}"
    cursor = _Cursor.decode(params.cursor, scope, (_stamp, _int))
    where = [Note.body.ilike(_contains(q))] if q else []
    start = [] if cursor is None else [tuple_(Note.created_at, Note.id) < tuple_(*cursor.key)]
    # The page first, then the mail of each of its notes.
    page = (
        select(*NOTE_COLUMNS, Note.mail_sha256)
        .where(*where, *start)
        .order_by(Note.created_at.desc(), Note.id.desc())
        .limit(params.limit + 1)
        .subquery("page")
    )
    original = (
        select(Mail.id, Mail.subject, Mail.date_utc)
        .where(Mail.raw_sha256 == page.c.mail_sha256)
        .order_by(Mail.is_duplicate_of.is_not(None), Mail.id)
        .limit(1)
        .lateral("original")
    )
    rows = list(
        await session.execute(
            select(
                page,
                original.c.id.label("mail_id"),
                original.c.subject,
                original.c.date_utc,
            )
            .outerjoin(original, true())
            .order_by(page.c.created_at.desc(), page.c.id.desc())
        )
    )
    more = len(rows) > params.limit
    del rows[params.limit :]
    total = await session.scalar(select(func.count()).select_from(Note).where(*where))
    senders = await mail_senders(session, [row.mail_id for row in rows if row.mail_id is not None])
    next_cursor = None
    if more:
        last = rows[-1]
        next_cursor = _Cursor(scope, False, (last.created_at, last.id)).encode()
    return NotePage(
        items=[
            NoteItem(
                id=row.id,
                body=row.body,
                author=row.author,
                created_at=row.created_at,
                updated_at=row.updated_at,
                mail_sha256=row.mail_sha256,
                mail=NoteMail(
                    id=row.mail_id,
                    subject=row.subject,
                    date=row.date_utc,
                    sender=None if row.mail_id is None else senders.get(row.mail_id),
                ),
            )
            for row in rows
        ],
        next_cursor=next_cursor,
        total=total or 0,
    )

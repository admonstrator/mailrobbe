"""What the model reads of a mail or a document (D302): from the database only, never the MBOX
file.

    mail      by its raw SHA-256 (D301): the earliest mail with that content that is not a
              duplicate, else any. The head: "Art: E-Mail", subject, date, sender and recipients
              by name and address, the names of its attachments. The text: its own words, the
              text segments of quotes.split_text (D151), without quotes, originals, forwards and
              signatures; with fewer than SUMMARY_MIN_WORDS words and a forwarded message, the
              first forward or original after a line "Weitergeleitet:"
    document  by its SHA-256 (D185): kind, file name, date and sender of the first mail carrying
              it and where its text comes from; the text whatever its origin (extracted,
              recognised, transcribed)

A mail with fewer than SUMMARY_MIN_WORDS words of its own is short: tags and theme hints only, as
any summary would be longer than it (D302); a document is always summarised, as the queue counts
it (ai.queue). SummaryInput.stored maps an offset in the text back to
the stored text (mail.body_text, document.extracted_text), where a theme hint's quote stands
(D304). The head lines are German, as are the prompts.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.ai.model import SUMMARY_MIN_WORDS
from mailrobbe.enums import AiTarget
from mailrobbe.quotes import Segment, split_text

HEAD_NAMES = 20  # recipients per role and attachment names in the head; the rest counted
FORWARDED = "Weitergeleitet:"
_ROLES = {"from": "Von", "to": "An", "cc": "Cc", "bcc": "Bcc"}
_KINDS = {
    "pdf": "PDF",
    "document": "Textdokument",
    "spreadsheet": "Tabelle",
    "presentation": "Präsentation",
    "text": "Text",
    "email": "E-Mail",
    "image": "Bild",
    "archive": "Archiv",
    "media": "Audio oder Video",
}
_ORIGINS = {"extracted": "aus der Datei", "ocr": "maschinell erkannt", "transcript": "Transkript"}

_MAIL = text("""
    SELECT id, subject, date_utc, COALESCE(body_text, '') AS body FROM mail
    WHERE raw_sha256 = :sha256
    ORDER BY is_duplicate_of IS NOT NULL, id
    LIMIT 1
""")
_PEOPLE = text("""
    SELECT p.role::text AS role, COALESCE(p.display_name, n.display_name) AS name,
        n.canonical_email AS email
    FROM participation p JOIN person n ON n.id = p.person_id
    WHERE p.mail_id = :mail_id AND p.role = ANY(CAST(:roles AS participation_role[]))
    ORDER BY p.role, name, email
""")
_ATTACHMENTS = text("""
    SELECT COALESCE(NULLIF(filename, ''), '(ohne Namen)') FROM attachment
    WHERE mail_id = :mail_id AND container_id IS NULL
    ORDER BY position, id
""")
_DOCUMENT = text("""
    SELECT name, kind::text AS kind, COALESCE(extracted_text, '') AS body,
        text_origin::text AS origin, first_date, first_mail_id
    FROM document WHERE sha256 = :sha256
""")


@dataclass(frozen=True, slots=True)
class Span:
    """A piece of SummaryInput.text taken from the stored text."""

    at: int  # offset in SummaryInput.text
    stored: int  # offset in the stored text
    length: int


@dataclass(frozen=True, slots=True)
class SummaryInput:
    """One mail or document as the model reads it."""

    target: AiTarget
    sha256: str
    name: str  # the subject or file name, for the run's progress; "" without one
    head: tuple[str, ...]  # German lines: "Art: E-Mail", "Betreff: …"
    text: str
    spans: tuple[Span, ...]  # where the pieces of text stand in the stored text
    words: int
    short: bool  # a mail with fewer than SUMMARY_MIN_WORDS words: tags and theme hints only
    origin: str | None = None  # a document's text_origin

    def stored(self, position: int) -> int | None:
        """The offset in the stored text of this offset in text; None where text has words of
        its own ("Weitergeleitet:", the blank lines between pieces)."""
        for span in self.spans:
            if span.at <= position < span.at + span.length:
                return span.stored + position - span.at
        return None


async def mail_input(session: AsyncSession, sha256: str) -> SummaryInput | None:
    """The mail with this content (module docstring); None when no mail has it."""
    mail = (await session.execute(_MAIL, {"sha256": sha256})).first()
    if mail is None:
        return None
    people = await _people(session, mail.id, list(_ROLES))
    attachments = list((await session.execute(_ATTACHMENTS, {"mail_id": mail.id})).scalars())
    head = ["Art: E-Mail"]
    if mail.subject:
        head.append(f"Betreff: {_line(mail.subject)}")
    if mail.date_utc is not None:
        head.append(f"Datum: {_date(mail.date_utc)}")
    for role, label in _ROLES.items():
        if people.get(role):
            head.append(f"{label}: {_listed(people[role])}")
    if attachments:
        head.append(f"Anhänge: {_listed(attachments)}")
    body, spans, words = own_text(mail.body)
    return SummaryInput(
        target=AiTarget.MAIL,
        sha256=sha256,
        name=_line(mail.subject or ""),
        head=tuple(head),
        text=body,
        spans=spans,
        words=words,
        short=words < SUMMARY_MIN_WORDS,
    )


def own_text(body: str) -> tuple[str, tuple[Span, ...], int]:
    """A mail's own words (module docstring): the text, its spans in body, its words."""
    segments = split_text(body)
    # (line before it, start, end) of each piece taken from body
    pieces = [("", *span) for s in segments if s.kind == "text" if (span := _trimmed(body, s))]
    words = sum(len(body[start:end].split()) for _, start, end in pieces)
    forward = next((s for s in segments if s.kind in ("forward", "original")), None)
    if words < SUMMARY_MIN_WORDS and forward is not None and (span := _trimmed(body, forward)):
        pieces.append((FORWARDED, *span))
        words += len(body[span[0] : span[1]].split())
    joined: list[str] = []
    spans: list[Span] = []
    for lead, start, end in pieces:
        if joined:
            joined.append("\n\n")
        if lead:
            joined.append(f"{lead}\n")
        at = sum(len(part) for part in joined)
        joined.append(body[start:end])
        spans.append(Span(at, start, end - start))
    return "".join(joined), tuple(spans), words


async def document_input(session: AsyncSession, sha256: str) -> SummaryInput | None:
    """The document with this content (module docstring); None when no document has it."""
    document = (await session.execute(_DOCUMENT, {"sha256": sha256})).first()
    if document is None:
        return None
    head = [f"Art: Dokument ({_KINDS.get(document.kind or '', 'Datei')})"]
    if document.name:
        head.append(f"Dateiname: {_line(document.name)}")
    if document.first_date is not None:
        head.append(f"Datum der ersten Mail: {_date(document.first_date)}")
    if document.first_mail_id is not None:
        senders = (await _people(session, document.first_mail_id, ["from"])).get("from")
        if senders:
            head.append(f"Absender der ersten Mail: {_listed(senders)}")
    head.append(f"Textquelle: {_ORIGINS.get(document.origin, document.origin)}")
    words = len(document.body.split())
    return SummaryInput(
        target=AiTarget.DOCUMENT,
        sha256=sha256,
        name=_line(document.name or ""),
        head=tuple(head),
        text=document.body,
        spans=(Span(0, 0, len(document.body)),),
        words=words,
        short=False,
        origin=document.origin,
    )


async def _people(session: AsyncSession, mail_id: int, roles: list[str]) -> dict[str, list[str]]:
    """The mail's participants of these roles, as "Name <address>", by role."""
    found: dict[str, list[str]] = {}
    parameters: dict[str, Any] = {"mail_id": mail_id, "roles": roles}
    for row in (await session.execute(_PEOPLE, parameters)).all():
        name = _line(row.name or "")
        shown = f"{name} <{row.email}>" if name and name.casefold() != row.email else row.email
        found.setdefault(row.role, []).append(shown)
    return found


def _trimmed(body: str, segment: Segment) -> tuple[int, int] | None:
    """The segment's start and end without the whitespace at its ends; None for a blank one."""
    piece = body[segment.start : segment.end]
    stripped = piece.strip()
    if not stripped:
        return None
    first = segment.start + len(piece) - len(piece.lstrip())
    return first, first + len(stripped)


def _listed(names: Sequence[str]) -> str:
    shown = ", ".join(names[:HEAD_NAMES])
    rest = len(names) - HEAD_NAMES
    return f"{shown} und {rest} weitere" if rest > 0 else shown


def _line(value: str) -> str:
    return " ".join(value.split())


def _date(moment: datetime) -> str:
    return f"{moment.astimezone(UTC):%d.%m.%Y %H:%M} UTC"

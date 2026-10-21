"""Data passed from MBOX framing and parsing (worker side) to storage.

Every object here crosses no process boundary but must stay cheap: a worker holds one batch of
ParsedMail at a time, never the raw messages of that batch. All strings are free of NUL
characters, which PostgreSQL text cannot hold.
"""

from dataclasses import dataclass
from datetime import datetime

from mailrobbe.enums import ImportErrorKind

# mail.body_text is cut to this many characters; mail.tsv indexes the stored text.
BODY_TEXT_LIMIT = 50_000
# Bytes of a message above MAILROBBE_IMPORT_MAX_MAIL_SIZE that are kept for parsing its headers.
TRUNCATED_HEAD_SIZE = 1024**2


@dataclass(frozen=True, slots=True)
class Issue:
    """One import_error row: a defect found in a record; the offset comes from the record."""

    kind: ImportErrorKind
    message: str  # English, one line, names the header or part concerned


@dataclass(frozen=True, slots=True)
class ParsedAddress:
    email: str  # lowercase, no angle brackets or whitespace, exactly one "@" with text around it
    display_name: str | None = None  # decoded, whitespace collapsed; None when empty


@dataclass(frozen=True, slots=True)
class ParsedAttachment:
    filename: str | None  # decoded; None when the part has no file name
    mime_type: str  # lowercase "type/subtype"
    size_bytes: int  # size of the decoded payload
    sha256: str | None  # hex digest of the decoded payload; None above the hash limit


@dataclass(frozen=True, slots=True)
class ParsedMail:
    """What the importer stores about one message (SPEC 3.2), apart from framing and DKIM."""

    message_id: str | None  # "<...>" as in the header; None when missing or malformed
    in_reply_to: str | None  # first "<...>" of In-Reply-To
    reference_ids: tuple[str, ...]  # "<...>" ids of References, in header order, deduplicated
    subject: str | None  # decoded, folding removed
    date_utc: datetime | None  # timezone-aware UTC
    sender: tuple[ParsedAddress, ...]  # From
    to: tuple[ParsedAddress, ...]
    cc: tuple[ParsedAddress, ...]
    bcc: tuple[ParsedAddress, ...]
    body_text: str | None  # text part, or text from HTML when there is none (D3); cut
    attachments: tuple[ParsedAttachment, ...]
    issues: tuple[Issue, ...]
    list_id: str | None = None  # List-Id inside its angle brackets, lowercase (D39)
    automated: bool = False  # Auto-Submitted other than "no", or Precedence bulk/junk/auto_reply

    @property
    def has_attachments(self) -> bool:
        return bool(self.attachments)

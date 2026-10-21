"""Text extraction of one document (D71, D72): bytes in, Extraction out.

extract_document is the only entry point. It classifies the content (attachments.kinds, with the
first bytes), runs the extractor of its format in a child process that is killed at the time
limit and may use at most limits.memory more memory, and keeps at most limits.max_chars
characters. It never raises for a bad document: damage, encryption and limits are statuses.
"""

from dataclasses import dataclass

from mailrobbe.attachments.kinds import HEAD_SIZE, classify
from mailrobbe.db.models import DOCUMENT_TEXT_LIMIT
from mailrobbe.enums import DocumentKind, DocumentTextStatus


@dataclass(frozen=True, slots=True)
class ExtractionLimits:
    max_chars: int = DOCUMENT_TEXT_LIMIT  # text kept; more sets Extraction.truncated
    timeout: float = 60.0  # seconds; then the child is killed and its text so far kept
    memory: int = 1024**3  # bytes of address space the child may add (Linux only)


@dataclass(frozen=True, slots=True)
class Extraction:
    # text, empty, scanned, encrypted, unsupported, failed or timeout; never pending, too_large
    # or unreadable, which the caller decides before reading
    status: DocumentTextStatus
    text: str = ""  # NUL-free, LF line ends; for text and timeout
    truncated: bool = False  # stopped at max_chars or at the time limit
    pages: int | None = None  # pages, sheets or slides, when the format has them
    error: str | None = None  # English, one line: why failed or timeout
    kind: DocumentKind | None = None  # the kind the content shows (first bytes), for document.kind


def extract_document(
    data: bytes, filename: str | None, mime_type: str, limits: ExtractionLimits
) -> Extraction:
    """The text of one document. Placeholder of the contract: plain text only, in-process."""
    fmt = classify(filename, mime_type, data[:HEAD_SIZE])
    if fmt.name != "text":
        return Extraction(DocumentTextStatus.UNSUPPORTED, kind=fmt.kind)
    text = data.decode("utf-8", "replace").replace("\x00", "")
    if not text.strip():
        return Extraction(DocumentTextStatus.EMPTY, kind=fmt.kind)
    return Extraction(
        DocumentTextStatus.TEXT,
        text[: limits.max_chars],
        truncated=len(text) > limits.max_chars,
        kind=fmt.kind,
    )

"""Text extraction of one document (D71, D72): bytes in, Extraction out.

extract_document is the only entry point. It classifies the content (attachments.kinds, with the
first bytes), runs the extractor of its format in a child process that is killed at the time
limit and may use at most limits.memory more memory (sandbox), and keeps at most limits.max_chars
characters. It never raises for a bad document: damage, encryption and limits are statuses.

Modules: base (the Sink extractors write to, their exceptions), sandbox (the child process),
packages (ZIP containers of XML parts, safe XML parsing), one module per format family: pdf,
ooxml (DOCX, XLSX, PPTX), odf (ODT, ODS, ODP), xps (XPS, OpenXPS), rtf, plain (text, CSV, HTML,
XML, JSON, iCalendar, vCard), mail (attached mails), archive (ZIP member names).
"""

from dataclasses import dataclass
from functools import partial

from mailrobbe.attachments.extract import sandbox
from mailrobbe.attachments.extract.archive import extract_zip
from mailrobbe.attachments.extract.base import Extractor
from mailrobbe.attachments.extract.mail import extract_mail
from mailrobbe.attachments.extract.odf import extract_odf
from mailrobbe.attachments.extract.ooxml import extract_docx, extract_pptx, extract_xlsx
from mailrobbe.attachments.extract.pdf import extract_pdf
from mailrobbe.attachments.extract.plain import (
    extract_calendar,
    extract_html,
    extract_json,
    extract_text,
    extract_xml,
)
from mailrobbe.attachments.extract.rtf import extract_rtf
from mailrobbe.attachments.extract.xps import extract_xps
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


# kinds.FORMATS names of the extractable formats -> their extractor
EXTRACTORS: dict[str, Extractor] = {
    "pdf": extract_pdf,
    "docx": extract_docx,
    "xlsx": extract_xlsx,
    "pptx": extract_pptx,
    "odt": extract_odf,
    "ods": extract_odf,
    "odp": extract_odf,
    "xps": extract_xps,
    "rtf": extract_rtf,
    "csv": extract_text,
    "text": extract_text,
    "html": extract_html,
    "xml": extract_xml,
    "json": extract_json,
    "calendar": extract_calendar,
    "vcard": extract_calendar,
    "eml": extract_mail,
    "zip": extract_zip,
}


def extract_document(
    data: bytes, filename: str | None, mime_type: str, limits: ExtractionLimits
) -> Extraction:
    """The text of one document; see the module docstring."""
    fmt = classify(filename, mime_type, data[:HEAD_SIZE])
    extractor = EXTRACTORS.get(fmt.name) if fmt.extractable else None
    if extractor is None:
        return Extraction(DocumentTextStatus.UNSUPPORTED, kind=fmt.kind)
    if not data:
        return Extraction(DocumentTextStatus.EMPTY, kind=fmt.kind)
    outcome = sandbox.run(
        partial(extractor, data),
        timeout=limits.timeout,
        memory=limits.memory,
        max_chars=limits.max_chars,
    )
    return Extraction(
        outcome.status,
        outcome.text,
        outcome.truncated,
        outcome.pages,
        outcome.error,
        fmt.kind,
    )

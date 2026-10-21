"""Metadata of attachments (D167): what a file says about itself, bytes in, Reading out.

read_metadata is the only entry point. It classifies the content (attachments.kinds, with the
first bytes), runs the reader of its format in a child process with the time and memory limits
of the text extraction (extract.sandbox.call), and turns what the reader collected into a
Reading: found when there are fields (with the first damage noted), failed when the reader met
damage and found nothing, empty otherwise. It never raises for a bad document. The attachments
phase calls it in its workers, for the documents it reads for their text and in the metadata
step for the others (attachments.phase); the API and the export only read what was stored.

Modules: model (fields, values, Reading, the summary the list and the mail detail use), exif
(TIFF structures: EXIF and GPS), xmp (XMP packets), images (JPEG, PNG, WebP, TIFF), pdf (with
pypdf), office (DOCX, XLSX, PPTX), odf (ODT, ODS, ODP).
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from mailrobbe.attachments.extract import sandbox
from mailrobbe.attachments.extract.base import Damaged, Encrypted, reason
from mailrobbe.attachments.kinds import HEAD_SIZE, classify
from mailrobbe.attachments.metadata.images import image_format, read_image
from mailrobbe.attachments.metadata.model import Collector, Reading
from mailrobbe.attachments.metadata.odf import read_odf
from mailrobbe.attachments.metadata.office import read_docx, read_ooxml
from mailrobbe.attachments.metadata.pdf import read_pdf
from mailrobbe.enums import DocumentMetadataStatus

# document.metadata_version of metadata read by the current readers; raising it reads the
# documents of lower versions again at the next import.
METADATA_VERSION = 1

Reader = Callable[[bytes, Collector], Any]

# kinds.FORMATS names (and image formats by their first bytes) -> their reader
READERS: dict[str, Reader] = {
    "pdf": read_pdf,
    "docx": read_docx,
    "xlsx": read_ooxml,
    "pptx": read_ooxml,
    "odt": read_odf,
    "ods": read_odf,
    "odp": read_odf,
    "image": read_image,
}


@dataclass(frozen=True, slots=True)
class MetadataLimits:
    timeout: float = 60.0  # seconds; then the child is killed
    memory: int = 1024**3  # bytes of address space the child may add (Linux only)


def read_metadata(
    data: bytes, filename: str | None, mime_type: str, limits: MetadataLimits
) -> Reading:
    """The metadata of one document; see the module docstring."""
    fmt = classify(filename, mime_type, data[:HEAD_SIZE])
    reader = READERS.get(fmt.name)
    if reader is None or (fmt.name == "image" and image_format(data) is None):
        return Reading(DocumentMetadataStatus.UNSUPPORTED)
    if not data:
        return Reading(DocumentMetadataStatus.EMPTY)
    called = sandbox.call(
        partial(_collect, reader, data), timeout=limits.timeout, memory=limits.memory
    )
    if called.error is not None:
        return Reading(DocumentMetadataStatus.FAILED, error=called.error)
    fields, problem = called.value["fields"], called.value["problem"]
    if fields:
        return Reading(DocumentMetadataStatus.FOUND, fields, problem)
    if problem:
        return Reading(DocumentMetadataStatus.FAILED, error=problem)
    return Reading(DocumentMetadataStatus.EMPTY)


def _collect(reader: Reader, data: bytes) -> dict[str, Any]:
    """Runs in the child: the fields found and the first damage met, as JSON."""
    out = Collector()
    try:
        reader(data, out)
    except MemoryError:
        raise
    except Encrypted:
        out.damaged("encrypted: needs a password")
    except Damaged as error:
        out.damaged(str(error) or "damaged file")
    except Exception as error:
        out.damaged(f"damaged file: {reason(error)}")
    return {"fields": out.fields, "problem": out.problem}

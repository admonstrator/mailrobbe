"""PDF (D167): the information dictionary, the XMP packet of the catalog, and signs of what else
the file holds, read with pypdf.

The information dictionary's standard entries (Title, Author, Subject, Keywords, Creator,
Producer, CreationDate, ModDate, Trapped) go to pdf, its other entries under their own names to
pdf_custom. From the bytes themselves: the version of the header and the revisions, one per
%%EOF marker, as every incremental update appends one (a linearized file has one more, which is
not counted); from the catalog the names of the embedded files (EmbeddedFiles). A file that
needs a password keeps what can be read without one. pypdf's warnings are not logged.
"""

import io
import logging
import re

from pypdf import PasswordType, PdfReader
from pypdf.generic import ByteStringObject, DictionaryObject, NameObject, StreamObject

from mailrobbe.attachments.extract.base import reason
from mailrobbe.attachments.metadata.model import LIST_LIMIT, Collector, DateParser
from mailrobbe.attachments.metadata.xmp import read_xmp

_STANDARD = {
    "/Title": "title",
    "/Author": "author",
    "/Subject": "subject",
    "/Keywords": "keywords",
    "/Creator": "creator",
    "/Producer": "producer",
    "/CreationDate": "creation_date",
    "/ModDate": "mod_date",
    "/Trapped": "trapped",
}
_DATES = frozenset({"creation_date", "mod_date"})
_VERSION = re.compile(rb"%PDF-(\d\.\d)")
PDF_DATE = DateParser(
    r"(?:D:)?(?P<year>\d{4})(?:(?P<month>\d{2})(?:(?P<day>\d{2})(?:(?P<hour>\d{2})"
    r"(?:(?P<minute>\d{2})(?P<second>\d{2})?)?)?)?)?"
    r"(?P<zone>Z|[+-]\d{2}'?(?:\d{2}'?)?)?(?:\d{2}'?\d{2}'?)?"
)

logging.getLogger("pypdf").setLevel(logging.ERROR)


def read_pdf(data: bytes, out: Collector) -> None:
    header = _VERSION.search(data[:1024])
    if header:
        out.text("pdf", "version", header.group(1).decode())
    markers = data.count(b"%%EOF")
    if markers:
        linearized = b"/Linearized" in data[:1024] and markers > 1
        out.number("pdf", "revisions", markers - 1 if linearized else markers)
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("") != PasswordType.NOT_DECRYPTED
            except NotImplementedError:
                decrypted = False
            if not decrypted:
                out.damaged("encrypted: the information dictionary needs a password")
                return
        root = reader.trailer.get("/Root")
        info = reader.trailer.get("/Info")
    except Exception as error:
        out.damaged(f"damaged PDF: {reason(error)}")
        return
    _info(_resolve(info), out)
    catalog = _resolve(root)
    if isinstance(catalog, DictionaryObject):
        _xmp(catalog, out)
        _embedded(reader, out)


def _resolve(value: object) -> object:
    try:
        return getattr(value, "get_object", lambda: value)()
    except Exception:
        return None


def _info(info: object, out: Collector) -> None:
    if not isinstance(info, DictionaryObject):
        return
    for name in list(info.keys())[:200]:
        value = _resolve(info.get(name))
        if isinstance(value, NameObject):
            found = str(value).removeprefix("/")
        elif isinstance(value, ByteStringObject):
            found = bytes(value).decode("latin-1")
        elif isinstance(value, str):
            found = str(value)
        else:
            continue
        key = _STANDARD.get(str(name))
        if key in _DATES:
            out.date("pdf", key, found, PDF_DATE)
        elif key is not None:
            out.text("pdf", key, found)
        else:
            out.text("pdf_custom", str(name).removeprefix("/"), found)


def _xmp(catalog: DictionaryObject, out: Collector) -> None:
    try:
        stream = _resolve(catalog.get("/Metadata"))
        packet = stream.get_data() if isinstance(stream, StreamObject) else None
    except Exception as error:
        out.damaged(f"PDF: the XMP stream cannot be read ({reason(error)})")
        return
    if packet:
        read_xmp(packet, out)


def _embedded(reader: PdfReader, out: Collector) -> None:
    """The names of the embedded files; their bytes are not read."""
    names: list[str] = []
    count = 0
    try:
        for embedded in reader.attachment_list:
            count += 1
            if len(names) < LIST_LIMIT and embedded.name:
                names.append(str(embedded.name))
    except Exception as error:
        out.damaged(f"PDF: the embedded files cannot be listed ({reason(error)})")
    if count:
        out.number("pdf", "embedded_files", count)
        out.texts("pdf", "embedded_file_names", names)

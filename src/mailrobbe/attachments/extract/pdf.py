"""PDF (D71, D72): the text layer page by page, with pypdf.

A PDF that needs a user password is encrypted; one encrypted with an empty user password is read.
A page whose text cannot be extracted is left out; when no page could be read the file is
damaged. Scanned is a PDF with pages but no text layer at all, at least one of them holding an
image (an XObject image, also inside a form, or an inline image): the work list of a later OCR.
A PDF with text on some pages and only images on others is text; one without text and images is
empty. pypdf's warnings about the repairs it makes are not logged.
"""

import io
import logging
import re

from pypdf import PageObject, PasswordType, PdfReader
from pypdf.generic import DictionaryObject

from mailrobbe.attachments.extract.base import Damaged, Encrypted, Sink, reason
from mailrobbe.enums import DocumentTextStatus

_FORM_DEPTH = 3  # nested form XObjects searched for images
_INLINE_IMAGE = re.compile(rb"(?:^|\s)BI\s.*?\sID\s", re.S)
_WORD = re.compile(r"\w")

logging.getLogger("pypdf").setLevel(logging.ERROR)


def extract_pdf(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
            except NotImplementedError:  # a security handler pypdf does not know
                raise Encrypted from None
            if decrypted == PasswordType.NOT_DECRYPTED:
                raise Encrypted
        pages = reader.pages
        count = len(pages)
    except Encrypted:
        raise
    except Exception as error:
        raise Damaged(f"damaged PDF: {reason(error)}") from None
    sink.set_pages(count)
    with_text = with_images = 0
    errors: list[str] = []
    for number in range(count):
        try:
            page = pages[number]
            text = page.extract_text() or ""
        except Exception as error:
            errors.append(f"page {number + 1}: {reason(error)}")
            continue
        if _WORD.search(text):
            with_text += 1
            sink.text(text)
            sink.block()
        elif _has_images(page):
            with_images += 1
    if with_text:
        return None
    if errors and not with_images:
        raise Damaged(f"damaged PDF, no page readable ({errors[0]})")
    return DocumentTextStatus.SCANNED if with_images else DocumentTextStatus.EMPTY


def _has_images(page: PageObject) -> bool:
    try:
        if _xobject_images(page.get("/Resources"), _FORM_DEPTH):
            return True
        contents = page.get_contents()
        return contents is not None and _INLINE_IMAGE.search(contents.get_data()) is not None
    except Exception:
        return False


def _xobject_images(resources: object, depth: int) -> bool:
    resources = getattr(resources, "get_object", lambda: resources)()
    if not isinstance(resources, DictionaryObject):
        return False
    xobjects = resources.get("/XObject")
    xobjects = getattr(xobjects, "get_object", lambda: xobjects)()
    if not isinstance(xobjects, DictionaryObject):
        return False
    for reference in xobjects.values():
        xobject = reference.get_object()
        if not isinstance(xobject, DictionaryObject):
            continue
        subtype = xobject.get("/Subtype")
        if subtype == "/Image":
            return True
        if (
            subtype == "/Form"
            and depth > 0
            and _xobject_images(xobject.get("/Resources"), depth - 1)
        ):
            return True
    return False

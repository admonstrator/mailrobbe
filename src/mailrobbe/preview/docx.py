"""DOCX to HTML (D122) with mammoth: paragraphs, headings, lists, tables with their spans, bold,
italic, underline, footnotes and endnotes at the end with links back and forth, and raster images
(sanitize.Images; anything else becomes the placeholder). Hyperlinks keep their text; the
sanitizer drops their targets. Headers, footers and comments are left out, as mammoth does.

mammoth parses with minidom, which would read a zip bomb whole and expand the entities a document
type declaration defines. So before mammoth sees the package, every XML part it reads (the parts
named .xml or .rels, the main document and the parts related to it apart from images) is parsed
once with the reader of the text extraction (attachments.extract.packages): within its
decompression budget, refusing document type and entity declarations. What else could get
through ends at the child process's limits (convert). Linked images are never fetched.

A password-protected DOCX is an OLE container holding EncryptedPackage (Encrypted); another OLE
file under a DOCX name is a legacy Word file, which this converter does not read (Damaged).
"""

import io
from typing import Any

import mammoth
from mammoth import html as mammoth_html

from mailrobbe.attachments.extract.base import Damaged, Encrypted
from mailrobbe.attachments.extract.packages import _ZIP_ERRORS, Package
from mailrobbe.preview.sanitize import IMAGE_PLACEHOLDER, Images

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")
_PIECE = 1 << 16
# Added to mammoth's own: a document title is a heading too, and underlined text stays
# underlined (mammoth drops underlines by default).
_STYLE_MAP = "p[style-name='Title'] => h1:fresh\np.Title => h1:fresh\nu => u"


def docx_html(data: bytes) -> str:
    """The HTML of a DOCX body, not yet sanitized."""
    if data.startswith(_OLE):
        if _ENCRYPTED_PACKAGE in data:
            raise Encrypted
        raise Damaged("a legacy Word file (OLE), not a DOCX")
    _check(Package(data))
    images = Images()

    def image(element: Any) -> list[Any]:
        try:
            with element.open() as handle:
                url = images.data_url(iter(lambda: handle.read(_PIECE), b""))
        except (*_ZIP_ERRORS, ValueError):  # a missing part, or a linked image
            url = None
        if url is None:
            return [mammoth_html.text(IMAGE_PLACEHOLDER)]
        attributes = {"src": url}
        if element.alt_text:
            attributes["alt"] = element.alt_text
        return [mammoth_html.element("img", attributes)]

    result = mammoth.convert_to_html(
        io.BytesIO(data),
        style_map=_STYLE_MAP,
        convert_image=image,
        include_embedded_style_map=False,
    )
    return str(result.value)


class _Ignore:
    def start(self, name: str, attrs: dict[str, str]) -> None:
        pass

    def end(self, name: str) -> None:
        pass

    def data(self, text: str) -> None:
        pass


def _check(package: Package) -> None:
    """Parse every part mammoth reads as XML once with the safe reader; Damaged when one is not
    well-formed, declares a document type or entities, or the parts exceed the XML budget."""
    main = "word/document.xml"  # mammoth's default, as the text extraction's
    for kind, member in package.relationships("").values():
        if kind.endswith("/officeDocument"):
            main = member
    parts = {name for name in package.names if name.endswith((".xml", ".rels"))}
    parts.add(main)
    parts.update(
        member
        for kind, member in package.relationships(main).values()
        if not kind.endswith("/image")
    )
    for name in sorted(parts & package.names):
        package.parse(name, _Ignore())

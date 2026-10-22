"""Office Open XML: DOCX, XLSX and PPTX (D71), read from their XML parts (packages).

DOCX: the body, then footnotes, endnotes and comments, then the headers and footers (each
distinct one once); deleted text of tracked changes counts, field instructions do not. XLSX:
every sheet in workbook order under its name, row by row, cells separated by tabs at their
column (gaps of empty cells kept, up to MAX_GAP), shared and inline strings as typed, numbers,
dates (serial numbers), booleans and errors as written in <v>, formulas not; pages are sheets.
PPTX: slides in presentation order, each followed by its notes; pages are slides.

A password-protected OOXML file is not a ZIP but an OLE container holding EncryptedPackage
(encrypted); another OLE file under an OOXML name is a legacy binary file (unsupported).
"""

import io
import re

from mailrobbe.attachments.extract.base import Damaged, Encrypted, Sink
from mailrobbe.attachments.extract.packages import (
    LineBuffer,
    Package,
    Paragraphs,
    natural,
    relationship_id,
)
from mailrobbe.enums import DocumentTextStatus

MAX_GAP = 16  # empty cells kept between two values of a row
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")
_COLUMN = re.compile(r"[A-Za-z]+")


def _ole(data: bytes) -> DocumentTextStatus:
    if _ENCRYPTED_PACKAGE in data:
        raise Encrypted
    return DocumentTextStatus.UNSUPPORTED  # a legacy binary file under an OOXML name


def is_encrypted_ole(data: bytes) -> bool:
    """Whether the content is a password-protected OOXML file (an OLE EncryptedPackage)."""
    return data.startswith(_OLE) and _ENCRYPTED_PACKAGE in data


def decrypt_ooxml(data: bytes, password: str) -> bytes:
    """The decrypted OOXML (a ZIP) of a protected file; raises Encrypted on the wrong password
    and Damaged on a broken one. Runs in the extraction's child process (D235)."""
    import msoffcrypto  # heavy; imported where it is used, as the other readers do

    try:
        office = msoffcrypto.OfficeFile(io.BytesIO(data))
        office.load_key(password=password)
        out = io.BytesIO()
        office.decrypt(out)
    except msoffcrypto.exceptions.InvalidKeyError:
        raise Encrypted from None
    except Exception as error:  # a format msoffcrypto cannot read, or a broken file
        if _wrong_password(error):
            raise Encrypted from None
        raise Damaged(f"cannot decrypt the Office file: {error}") from None
    return out.getvalue()


def _wrong_password(error: Exception) -> bool:
    return "password" in str(error).lower() or "key" in type(error).__name__.lower()


def _main_part(package: Package, default: str) -> str:
    for kind, member in package.relationships("").values():
        if kind.endswith("/officeDocument"):
            return member
    return default


def _related(package: Package, part: str, kind: str) -> list[str]:
    """Members related to `part` by relationships of this kind, in natural name order."""
    members = {
        member
        for rel_kind, member in package.relationships(part).values()
        if rel_kind.endswith(f"/{kind}") and member in package.names
    }
    return sorted(members, key=natural)


# DOCX


class _Word(Paragraphs):
    TEXTS = frozenset({"t", "delText"})
    TABS = frozenset({"tab"})
    BREAKS = frozenset({"br", "cr"})
    SKIP = frozenset({"Fallback", "tabs", "rPr", "pPr"})  # alternatives, tab stops, formats

    def other(self, name: str, attrs: dict[str, str]) -> None:
        if name == "noBreakHyphen":
            self.piece("-")


def extract_docx(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    if data.startswith(_OLE):
        return _ole(data)
    package = Package(data)
    main = _main_part(package, "word/document.xml")
    if main not in package.names:
        raise Damaged(f"no document part ({main})")
    package.parse(main, _Word(sink))
    sink.block()
    for kind in ("footnotes", "endnotes", "comments"):
        for member in _related(package, main, kind):
            package.parse(member, _Word(sink))
            sink.block()
    seen: set[tuple[str, ...]] = set()
    for kind in ("header", "footer"):
        for member in _related(package, main, kind):
            buffer = LineBuffer()
            package.parse(member, _Word(buffer))
            lines = tuple(line for line in buffer.lines if line.strip())
            if lines and lines not in seen:
                seen.add(lines)
                for line in lines:
                    sink.line(line)
                sink.block()
    return None


# XLSX


class _Workbook:
    """The sheets of workbook.xml in their order: (name, relationship id)."""

    def __init__(self) -> None:
        self.sheets: list[tuple[str, str]] = []

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == "sheet":
            self.sheets.append((attrs.get("name", ""), relationship_id(attrs)))

    def end(self, name: str) -> None:
        pass

    def data(self, text: str) -> None:
        pass


class _SharedStrings:
    """sharedStrings.xml: the text of each <si>, rich text runs joined, phonetic runs left out."""

    def __init__(self) -> None:
        self.strings: list[str] = []
        self._parts: list[str] | None = None
        self._in_text = False
        self._phonetic = 0

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == "si":
            self._parts = []
        elif name == "t":
            self._in_text = True
        elif name == "rPh":
            self._phonetic += 1

    def end(self, name: str) -> None:
        if name == "si" and self._parts is not None:
            self.strings.append("".join(self._parts))
            self._parts = None
        elif name == "t":
            self._in_text = False
        elif name == "rPh":
            self._phonetic -= 1

    def data(self, text: str) -> None:
        if self._in_text and self._parts is not None and not self._phonetic:
            self._parts.append(text)


def _column(reference: str | None, previous: int) -> int:
    """1-based column of a cell reference such as "AB12"; the next one without a reference."""
    match = _COLUMN.match(reference or "")
    if match is None:
        return previous + 1
    number = 0
    for letter in match.group().upper():
        number = number * 26 + ord(letter) - 64
    return number


class _Sheet:
    """A worksheet's rows as lines of tab-separated cell values."""

    def __init__(self, out: Sink, shared: list[str]) -> None:
        self._out = out
        self._shared = shared
        self._row: list[tuple[int, str]] = []
        self._column = 0
        self._type = "n"
        self._value: list[str] = []
        self._collect = False  # inside <v>, or <t> of an inline string
        self._inline = False
        self._phonetic = 0

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == "c":
            self._column = _column(attrs.get("r"), self._column)
            self._type = attrs.get("t", "n")
            self._value = []
        elif name == "v":
            self._collect = True
        elif name == "is":
            self._inline = True
        elif name == "t" and self._inline and not self._phonetic:
            self._collect = True
        elif name == "rPh":
            self._phonetic += 1
        elif name == "row":
            self._row = []
            self._column = 0

    def end(self, name: str) -> None:
        if name in ("v", "t"):
            self._collect = False
        elif name == "is":
            self._inline = False
        elif name == "rPh":
            self._phonetic -= 1
        elif name == "c":
            value = "".join(self._value)
            if self._type == "s":
                index = int(value) if value.strip().isdigit() else -1
                value = self._shared[index] if 0 <= index < len(self._shared) else ""
            value = " ".join(value.split())
            if value:
                self._row.append((self._column, value))
        elif name == "row":
            self._out.line(_row_line(self._row))

    def data(self, text: str) -> None:
        if self._collect:
            self._value.append(text)


def _row_line(cells: list[tuple[int, str]]) -> str:
    parts: list[str] = []
    previous = 0
    for column, value in cells:
        parts.extend([""] * min(max(column - previous - 1, 0), MAX_GAP))
        parts.append(value)
        previous = column
    return "\t".join(parts)


def extract_xlsx(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    if data.startswith(_OLE):
        return _ole(data)
    package = Package(data)
    book = _main_part(package, "xl/workbook.xml")
    if book not in package.names:
        raise Damaged(f"no workbook part ({book})")
    workbook = _Workbook()
    package.parse(book, workbook)
    rels = package.relationships(book)
    shared = _SharedStrings()
    for member in _related(package, book, "sharedStrings") or [
        name for name in ("xl/sharedStrings.xml",) if name in package.names
    ]:
        package.parse(member, shared)
    sink.set_pages(len(workbook.sheets))
    for name, rel_id in workbook.sheets:
        kind, member = rels.get(rel_id, ("", ""))
        sink.line(name)
        if kind.endswith("/worksheet") and member in package.names:
            package.parse(member, _Sheet(sink, shared.strings))
        sink.block()
    return None


# PPTX


class _Drawing(Paragraphs):
    """DrawingML text: shapes, tables (a:tbl) and fields of a slide."""


class _Notes(_Drawing):
    """A notes page without its slide image, slide number, date, header and footer."""

    _PLACEHOLDERS = frozenset({"sldNum", "sldImg", "dt", "hdr", "ftr"})

    def __init__(self, out: Sink) -> None:
        super().__init__(out)
        self._hidden = False

    def other(self, name: str, attrs: dict[str, str]) -> None:
        if name == "sp":
            self._hidden = False
        elif name == "ph":
            self._hidden = attrs.get("type") in self._PLACEHOLDERS

    def paragraph(self, text: str) -> None:
        if not self._hidden:
            super().paragraph(text)


class _SlideList:
    """The relationship ids of p:sldIdLst in presentation.xml, in slide order."""

    def __init__(self) -> None:
        self.ids: list[str] = []

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == "sldId":
            self.ids.append(relationship_id(attrs))

    def end(self, name: str) -> None:
        pass

    def data(self, text: str) -> None:
        pass


def extract_pptx(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    if data.startswith(_OLE):
        return _ole(data)
    package = Package(data)
    main = _main_part(package, "ppt/presentation.xml")
    if main not in package.names:
        raise Damaged(f"no presentation part ({main})")
    order = _SlideList()
    package.parse(main, order)
    rels = package.relationships(main)
    slides = [
        rels[rel_id][1]
        for rel_id in order.ids
        if rel_id in rels and rels[rel_id][0].endswith("/slide")
    ]
    slides = [member for member in slides if member in package.names]
    sink.set_pages(len(slides))
    for member in slides:
        package.parse(member, _Drawing(sink))
        for notes in _related(package, member, "notesSlide"):
            sink.line("")
            package.parse(notes, _Notes(sink))
        sink.block()
    return None

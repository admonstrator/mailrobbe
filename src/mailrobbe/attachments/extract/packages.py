"""ZIP packages of XML parts (OOXML and ODF): bounded reads, safe parsing, paragraphs and tables.

A part is decompressed piece by piece and counted against one budget per document, so a zip bomb
ends as Damaged after XML_BUDGET bytes instead of filling the memory; the parser never sees the
whole part at once. XML is parsed with the standard library's expat, refusing document type
declarations (OOXML and ODF never have one) and entity declarations: no external entities, no
entity expansion.

Paragraphs collects the paragraphs and table rows of WordprocessingML, DrawingML and ODF text as
lines: a paragraph per line, table cells separated by tabs, a row per line, the paragraphs of a
cell joined by spaces.
"""

import io
import posixpath
import re
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from typing import Protocol
from xml.parsers import expat

from mailrobbe.attachments.extract.base import Damaged, Encrypted, reason

XML_BUDGET = 256 * 1024**2  # decompressed XML bytes one document may read in all
_PIECE = 1 << 20
_NUMBER = re.compile(r"(\d+)")

# What reading a member of a broken or unusual ZIP raises.
_ZIP_ERRORS = (
    zipfile.BadZipFile,
    zlib.error,
    EOFError,
    KeyError,
    NotImplementedError,
    RuntimeError,
    OSError,
)


class Malformed(Damaged):
    """XML that is not well-formed."""


class Lines(Protocol):
    """Where text goes: a Sink, or a buffer of lines."""

    def line(self, text: str) -> None: ...
    def block(self) -> None: ...


class LineBuffer:
    """Lines kept for later, for parts written only when they differ (headers, footers)."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)

    def block(self) -> None:
        self.lines.append("")


def natural(name: str) -> list[object]:
    """Sort key of member names: header2.xml before header10.xml."""
    return [int(part) if part.isdigit() else part for part in _NUMBER.split(name)]


def attribute(attrs: dict[str, str], local: str) -> str | None:
    """An attribute by its local name, whatever its namespace prefix."""
    for key, value in attrs.items():
        if key == local or (key.endswith(local) and key[-len(local) - 1] == ":"):
            return value
    return None


def relationship_id(attrs: dict[str, str]) -> str:
    """The r:id of an element (relationships namespace, whatever its prefix); an element may
    also have a plain id of its own, as p:sldId does."""
    return next((value for key, value in attrs.items() if key.endswith(":id")), "")


class Handler(Protocol):
    def start(self, name: str, attrs: dict[str, str]) -> None: ...
    def end(self, name: str) -> None: ...
    def data(self, text: str) -> None: ...


def parse_xml(pieces: Iterable[bytes], handler: Handler, where: str, doctype: bool = False) -> None:
    """Feed XML to handler with element names stripped of their prefix ("w:p" -> "p").

    A DOCTYPE is refused unless `doctype`; entity declarations are always refused.
    """
    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.buffer_size = 1 << 16
    start, end = handler.start, handler.end

    def on_start(name: str, attrs: dict[str, str]) -> None:
        start(name[name.find(":") + 1 :], attrs)

    def on_end(name: str) -> None:
        end(name[name.find(":") + 1 :])

    def refuse_doctype(*_: object) -> None:
        raise Damaged(f"{where}: XML with a document type declaration is not read")

    def refuse_entity(*_: object) -> None:
        raise Damaged(f"{where}: XML with entity declarations is not read")

    parser.StartElementHandler = on_start
    parser.EndElementHandler = on_end
    parser.CharacterDataHandler = handler.data
    parser.EntityDeclHandler = refuse_entity
    if not doctype:
        parser.StartDoctypeDeclHandler = refuse_doctype
    try:
        for piece in pieces:
            parser.Parse(piece, False)
        parser.Parse(b"", True)
    except expat.ExpatError as error:
        raise Malformed(f"{where}: malformed XML ({error})") from None


class Package:
    """The members of a ZIP container, read within the document's XML budget."""

    def __init__(self, data: bytes) -> None:
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(data))
            self.names = frozenset(self._zip.namelist())
        except _ZIP_ERRORS as error:
            raise Damaged(f"damaged ZIP container: {reason(error)}") from None
        self._budget = XML_BUDGET

    def pieces(self, name: str) -> Iterator[bytes]:
        """The decompressed bytes of a member, piece by piece."""
        try:
            if self._zip.getinfo(name).flag_bits & 0x1:
                raise Encrypted
            with self._zip.open(name) as member:
                while piece := member.read(_PIECE):
                    self._budget -= len(piece)
                    if self._budget < 0:
                        raise Damaged(
                            f"{name}: more than {XML_BUDGET // 1024**2} MiB of XML in the "
                            "document (a zip bomb?)"
                        )
                    yield piece
        except _ZIP_ERRORS as error:
            raise Damaged(f"{name}: {reason(error)}") from None

    def read(self, name: str) -> bytes:
        return b"".join(self.pieces(name))

    def parse(self, name: str, handler: Handler) -> None:
        parse_xml(self.pieces(name), handler, name)

    def relationships(self, part: str) -> dict[str, tuple[str, str]]:
        """Relationship id -> (type, member name) of an OOXML part ("" for the package)."""
        folder, _, file = part.rpartition("/")
        rels = posixpath.join(folder, "_rels", f"{file}.rels")
        if rels not in self.names:
            return {}
        found: dict[str, tuple[str, str]] = {}

        def start(name: str, attrs: dict[str, str]) -> None:
            if name != "Relationship" or attrs.get("TargetMode") == "External":
                return
            target = attrs.get("Target", "")
            if target.startswith("/"):
                member = target.lstrip("/")
            else:
                member = posixpath.normpath(posixpath.join(folder, target))
            found[attrs.get("Id", "")] = (attrs.get("Type", ""), member)

        parse_xml(self.pieces(rels), _Callbacks(start), rels)
        return found


class _Callbacks:
    def __init__(self, start: Callable[[str, dict[str, str]], None]) -> None:
        self.start = start

    def end(self, name: str) -> None:
        pass

    def data(self, text: str) -> None:
        pass


class Paragraphs:
    """Paragraphs and table rows of one XML part as lines (see the module docstring).

    The element names are local names; subclasses set them per format. TEXTS None means all
    character data inside a paragraph is text (ODF), else only that inside those elements.
    """

    PARAGRAPHS: frozenset[str] = frozenset({"p"})
    TEXTS: frozenset[str] | None = frozenset({"t"})
    TABS: frozenset[str] = frozenset()
    BREAKS: frozenset[str] = frozenset({"br"})
    ROWS: frozenset[str] = frozenset({"tr"})
    CELLS: frozenset[str] = frozenset({"tc"})
    SKIP: frozenset[str] = frozenset({"Fallback"})  # subtrees without text of their own

    def __init__(self, out: Lines) -> None:
        self.out = out
        self._paragraphs: list[list[str]] = []
        self._rows: list[list[str]] = []
        self._cells: list[list[str]] = []
        self._skip = 0  # depth inside a skipped subtree
        self._in_text = 0

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if self._skip:
            self._skip += 1
        elif name in self.SKIP:
            self._skip = 1
        elif name in self.PARAGRAPHS:
            self._paragraphs.append([])
        elif self.TEXTS is not None and name in self.TEXTS:
            self._in_text += 1
        elif name in self.TABS:
            self.piece("\t")
        elif name in self.BREAKS:
            self.piece("\n")
        elif name in self.ROWS:
            self._rows.append([])
        elif name in self.CELLS:
            self._cells.append([])
        else:
            self.other(name, attrs)

    def end(self, name: str) -> None:
        if self._skip:
            self._skip -= 1
        elif name in self.PARAGRAPHS and self._paragraphs:
            self.paragraph("".join(self._paragraphs.pop()))
        elif self.TEXTS is not None and name in self.TEXTS:
            self._in_text = max(0, self._in_text - 1)
        elif name in self.ROWS and self._rows:
            self.row(self._rows.pop())
        elif name in self.CELLS and self._cells:
            self.cell(" ".join(part for part in self._cells.pop() if part))
        else:
            self.other_end(name)

    def data(self, text: str) -> None:
        if self._paragraphs and not self._skip and (self.TEXTS is None or self._in_text):
            self._paragraphs[-1].append(text)

    def piece(self, text: str) -> None:
        if self._paragraphs and not self._skip:
            self._paragraphs[-1].append(text)

    def other(self, name: str, attrs: dict[str, str]) -> None:
        """An element that is none of the above."""

    def other_end(self, name: str) -> None:
        """The end of such an element."""

    def paragraph(self, text: str) -> None:
        if self._cells:
            self._cells[-1].append(" ".join(text.split()))
        else:
            for line in text.split("\n"):
                self.out.line(line)

    def cell(self, text: str) -> None:
        if self._rows:
            self._rows[-1].append(text)
        else:
            self.paragraph(text)

    def row(self, cells: list[str]) -> None:
        line = "\t".join(cells).rstrip("\t")
        if self._cells:  # a table inside a table cell
            self._cells[-1].append(" ".join(line.split()))
        else:
            self.out.line(line)

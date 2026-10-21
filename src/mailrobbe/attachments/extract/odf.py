"""OpenDocument: ODT, ODS and ODP (D71), read from content.xml (packages).

The text is that of text:p and text:h, with text:s, text:tab and text:line-break as spaces, tabs
and line breaks; notes, comments and tracked deletions count, note citation marks do not. ODT
adds the headers and footers of its page styles (styles.xml). ODS gives every sheet under its
name, row by row, each cell as displayed (its paragraphs), repeated cells and rows written once
per repetition up to MAX_REPEAT; pages are sheets. ODP gives the pages (slides) with their notes;
pages are slides.

An encrypted document says so in META-INF/manifest.xml (manifest:encryption-data).
"""

from mailrobbe.attachments.extract.base import Damaged, Encrypted, Sink
from mailrobbe.attachments.extract.packages import Lines, Package, Paragraphs, attribute
from mailrobbe.enums import DocumentTextStatus

MAX_REPEAT = 100  # copies of a repeated non-empty cell or row
_MANIFEST = "META-INF/manifest.xml"


class _Text(Paragraphs):
    PARAGRAPHS = frozenset({"p", "h"})
    TEXTS = None
    TABS = frozenset({"tab"})
    BREAKS = frozenset({"line-break"})
    ROWS = frozenset({"table-row"})
    CELLS = frozenset({"table-cell", "covered-table-cell"})
    SKIP = frozenset(
        {"note-citation", "forms", "scripts", "font-face-decls", "styles", "automatic-styles"}
    )

    def __init__(self, out: Lines) -> None:
        super().__init__(out)
        self._body = ""  # text, spreadsheet or presentation
        self._depth = 0  # of table:table or draw:page elements below the body
        self._pages = 0
        self._row_repeat = 1
        self._cell_repeat: list[int] = []
        self._empty_cells = 0  # empty cells waiting for a value to their right

    def other(self, name: str, attrs: dict[str, str]) -> None:
        if name == "s":
            count = attribute(attrs, "c")
            self.piece(" " * min(int(count) if count and count.isdigit() else 1, 64))
        elif name in ("text", "spreadsheet", "presentation") and not self._body:
            self._body = name
        elif (name, self._body) in (("table", "spreadsheet"), ("page", "presentation")):
            self._depth += 1
            if self._depth == 1:
                self._pages += 1
                if name == "table":
                    self.out.line(attribute(attrs, "name") or "")

    def other_end(self, name: str) -> None:
        if (name, self._body) in (("table", "spreadsheet"), ("page", "presentation")):
            self._depth -= 1
            if self._depth == 0:
                self.out.block()

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if self._skip:
            pass
        elif name in self.ROWS:
            repeat = attribute(attrs, "number-rows-repeated")
            self._row_repeat = int(repeat) if repeat and repeat.isdigit() else 1
            self._empty_cells = 0
        elif name in self.CELLS:
            repeat = attribute(attrs, "number-columns-repeated")
            self._cell_repeat.append(int(repeat) if repeat and repeat.isdigit() else 1)
        super().start(name, attrs)

    def cell(self, text: str) -> None:
        repeat = self._cell_repeat.pop() if self._cell_repeat else 1
        if not self._in_row():
            super().cell(text)
        elif not text:
            self._empty_cells += repeat
        else:
            for _ in range(min(self._empty_cells, MAX_REPEAT)):
                super().cell("")
            self._empty_cells = 0
            for _ in range(min(repeat, MAX_REPEAT)):
                super().cell(text)

    def row(self, cells: list[str]) -> None:
        self._empty_cells = 0
        repeat = self._row_repeat if any(cells) else 1
        self._row_repeat = 1
        for _ in range(min(repeat, MAX_REPEAT)):
            super().row(cells)

    def _in_row(self) -> bool:
        return bool(self._rows)

    @property
    def pages(self) -> int | None:
        return self._pages if self._body in ("spreadsheet", "presentation") else None


def _encrypted(package: Package) -> bool:
    if _MANIFEST not in package.names:
        return False
    return b"encryption-data" in package.read(_MANIFEST)


def extract_odf(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    package = Package(data)
    if _encrypted(package):
        raise Encrypted
    if "content.xml" not in package.names:
        raise Damaged("no content part (content.xml)")
    content = _Text(sink)
    package.parse("content.xml", content)
    if content.pages is not None:
        sink.set_pages(content.pages)
    sink.block()
    if content.pages is None and "styles.xml" in package.names:  # headers and footers
        package.parse("styles.xml", _Text(sink))
    return None

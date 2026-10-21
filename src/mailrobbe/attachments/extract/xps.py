"""XPS and OpenXPS (D78): the text of a printed document, page by page; pages are pages.

An XPS file is a ZIP package of XML parts like OOXML (packages): its fixed representation names a
document sequence, which names its documents, which name their pages. A page's text is the
UnicodeString of its Glyphs elements; runs on one baseline (the same OriginY) are joined into a
line, as a reader sees them. A file without that chain is read page by page in the natural order
of its .fpage members. As for a PDF, a document whose pages hold images (ImageBrush) but no text
is a scan, one without text and images empty.
"""

import posixpath

from mailrobbe.attachments.extract.base import Damaged, Sink
from mailrobbe.attachments.extract.packages import Package, natural
from mailrobbe.enums import DocumentTextStatus

_FIXED_REPRESENTATION = "/fixedrepresentation"  # XPS and OpenXPS relationship types end so


def _member(folder: str, source: str) -> str:
    if source.startswith("/"):
        return source.lstrip("/")
    return posixpath.normpath(posixpath.join(folder, source))


class _Sources:
    """The Source attributes of one element name, as members of the package."""

    def __init__(self, element: str, folder: str) -> None:
        self.element = element
        self.folder = folder
        self.members: list[str] = []

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == self.element and (source := attrs.get("Source")):
            self.members.append(_member(self.folder, source))

    def end(self, name: str) -> None:
        pass

    def data(self, text: str) -> None:
        pass


def _sources(package: Package, part: str, element: str) -> list[str]:
    handler = _Sources(element, posixpath.dirname(part))
    package.parse(part, handler)
    return [member for member in handler.members if member in package.names]


def _pages(package: Package) -> list[str]:
    sequences = [
        member
        for kind, member in package.relationships("").values()
        if kind.endswith(_FIXED_REPRESENTATION) and member in package.names
    ]
    pages: list[str] = []
    for sequence in sequences[:1]:
        for document in _sources(package, sequence, "DocumentReference"):
            pages += _sources(package, document, "PageContent")
    if not pages:
        pages = sorted((name for name in package.names if name.endswith(".fpage")), key=natural)
    return list(dict.fromkeys(pages))


class _Page:
    """The text of one FixedPage as lines, and whether it shows images."""

    def __init__(self, sink: Sink) -> None:
        self._sink = sink
        self._runs: list[str] = []
        self._baseline: str | None = None
        self.texts = 0
        self.images = 0

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == "ImageBrush":
            self.images += 1
            return
        if name != "Glyphs":
            return
        run = " ".join(attrs.get("UnicodeString", "").removeprefix("{}").split())
        if not run:
            return
        baseline = attrs.get("OriginY")
        if self._runs and baseline != self._baseline:
            self.flush()
        self._baseline = baseline
        self._runs.append(run)
        self.texts += 1

    def end(self, name: str) -> None:
        pass

    def data(self, text: str) -> None:
        pass

    def flush(self) -> None:
        if self._runs:
            self._sink.line(" ".join(self._runs))
            self._runs.clear()


def extract_xps(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    package = Package(data)
    pages = _pages(package)
    if not pages:
        raise Damaged("no pages (FixedPage parts)")
    sink.set_pages(len(pages))
    texts = images = 0
    for part in pages:
        page = _Page(sink)
        package.parse(part, page)
        page.flush()
        sink.block()
        texts += page.texts
        images += page.images
    if texts:
        return None
    return DocumentTextStatus.SCANNED if images else DocumentTextStatus.EMPTY

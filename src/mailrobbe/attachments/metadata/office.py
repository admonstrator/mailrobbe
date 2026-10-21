"""Office Open XML: DOCX, XLSX and PPTX (D167), read from their property parts (extract.packages).

docProps/core.xml (the core properties: creator, last modified by, created, modified, last
printed, revision, title, subject, keywords, description, category, content status) and
docProps/app.xml (the extended properties: application and its version, company, manager,
template, total editing time in minutes, pages, words, characters, slides, notes, hidden
slides) to office, and docProps/custom.xml (the file's own properties, under their own names,
the value as written) to office_custom, each found by its package relationship, else by its
usual name. A DOCX also counts its comments (comments part) and the tracked changes of its body
(insertions, deletions and moves, also of formatting), each with the authors named, where it
has any. Parts are read within the document's XML budget and parsed safely, as the text
extraction does.
"""

import re
from collections.abc import Callable

from mailrobbe.attachments.extract.base import Damaged
from mailrobbe.attachments.extract.ooxml import _OLE, _main_part, _ole, _related
from mailrobbe.attachments.extract.packages import Package, attribute
from mailrobbe.attachments.metadata.model import Collector
from mailrobbe.attachments.metadata.xmp import W3C_DATE

_CORE = {
    "creator": "creator",
    "lastModifiedBy": "last_modified_by",
    "created": "created",
    "modified": "modified",
    "lastPrinted": "last_printed",
    "revision": "revision",
    "title": "title",
    "subject": "subject",
    "keywords": "keywords",
    "description": "description",
    "category": "category",
    "contentStatus": "content_status",
}
_APP = {
    "Application": "application",
    "AppVersion": "app_version",
    "Company": "company",
    "Manager": "manager",
    "Template": "template",
    "TotalTime": "total_time",
    "Pages": "pages",
    "Words": "words",
    "Characters": "characters",
    "Slides": "slides",
    "Notes": "notes",
    "HiddenSlides": "hidden_slides",
}
DATES = frozenset({"created", "modified", "last_printed"})
_NUMBERS = frozenset(
    {"revision", "total_time", "pages", "words", "characters", "slides", "notes", "hidden_slides"}
)
_CHANGES = frozenset(
    {
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "rPrChange",
        "pPrChange",
        "sectPrChange",
        "tblPrChange",
        "trPrChange",
        "tcPrChange",
    }
)
_CORE_TYPE = "/metadata/core-properties"
_APP_TYPE = "/extended-properties"
_CUSTOM_TYPE = "/custom-properties"


class Children:
    """The text of each child element of a parent (by local name): (name, attributes, text)."""

    def __init__(self, parent: str) -> None:
        self.parent = parent
        self.found: list[tuple[str, dict[str, str], str]] = []
        self._path: list[str] = []
        self._text: list[str] | None = None
        self._attrs: dict[str, str] = {}

    def start(self, name: str, attrs: dict[str, str]) -> None:
        inside = bool(self._path) and self._path[-1] == self.parent
        self._path.append(name)
        self._text, self._attrs = ([], attrs) if inside else (None, {})

    def end(self, name: str) -> None:
        self._path.pop()
        if self._text is not None and self._path and self._path[-1] == self.parent:
            self.found.append((name, self._attrs, "".join(self._text)))
        self._text = None

    def data(self, text: str) -> None:
        if self._text is not None:
            self._text.append(text)


class _Custom:
    """The custom properties: (name, the text of its value, whatever its type)."""

    def __init__(self) -> None:
        self.found: list[tuple[str, str]] = []
        self._name: str | None = None
        self._text: list[str] = []

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == "property":
            self._name, self._text = attribute(attrs, "name"), []

    def end(self, name: str) -> None:
        if name == "property":
            if self._name:
                self.found.append((self._name, "".join(self._text)))
            self._name = None

    def data(self, text: str) -> None:
        if self._name is not None:
            self._text.append(text)


class _Count:
    """Elements of some names, and the w:author of each."""

    def __init__(self, names: Callable[[str], bool]) -> None:
        self.names = names
        self.count = 0
        self.authors: list[str] = []

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if self.names(name):
            self.count += 1
            author = attribute(attrs, "author")
            if author and author not in self.authors:
                self.authors.append(author)

    def end(self, name: str) -> None:
        pass

    def data(self, text: str) -> None:
        pass


def store(out: Collector, source: str, key: str, value: str, dates: frozenset[str]) -> None:
    """A property value: a date as ISO 8601, a count as a number, else the text."""
    if key in dates:
        out.date(source, key, value, W3C_DATE)
    elif key in _NUMBERS and (number := count(value)) is not None:
        out.number(source, key, number)
    else:
        out.text(source, key, value)


def count(value: str) -> int | None:
    """A count as a property states it: ASCII digits only (int() also reads other scripts'
    digits and refuses more than 4,300), at most 18 of them."""
    text = value.strip()
    return int(text) if re.fullmatch("[0-9]{1,18}", text) else None


def read_ooxml(data: bytes, out: Collector) -> Package:
    """The core and extended properties of an OOXML package; the package, for read_docx."""
    if data.startswith(_OLE):
        _ole(data)  # raises Encrypted for a password-protected file
        raise Damaged("a legacy binary Office file under an OOXML name")
    package = Package(data)
    parts = {kind: member for kind, member in package.relationships("").values()}
    core = next((m for k, m in parts.items() if k.endswith(_CORE_TYPE)), "docProps/core.xml")
    app = next((m for k, m in parts.items() if k.endswith(_APP_TYPE)), "docProps/app.xml")
    for member, root, keys in ((core, "coreProperties", _CORE), (app, "Properties", _APP)):
        if member not in package.names:
            continue
        properties = Children(root)
        package.parse(member, properties)
        for name, _, value in properties.found:
            if name in keys:
                store(out, "office", keys[name], value, DATES)
    custom = next((m for k, m in parts.items() if k.endswith(_CUSTOM_TYPE)), "docProps/custom.xml")
    if custom in package.names:
        own = _Custom()
        package.parse(custom, own)
        for name, value in own.found:
            out.text("office_custom", name, value)
    return package


def read_docx(data: bytes, out: Collector) -> None:
    """The properties, and the comments and tracked changes of the body."""
    package = read_ooxml(data, out)
    main = _main_part(package, "word/document.xml")
    if main not in package.names:
        return
    comments = _Count(lambda name: name == "comment")
    for member in _related(package, main, "comments"):
        package.parse(member, comments)
    changes = _Count(_CHANGES.__contains__)
    package.parse(main, changes)
    if comments.count:
        out.number("office", "comments", comments.count)
        out.texts("office", "comment_authors", comments.authors)
    if changes.count:
        out.number("office", "tracked_changes", changes.count)
        out.texts("office", "change_authors", changes.authors)

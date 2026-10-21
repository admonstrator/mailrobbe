"""ODT to HTML (D122): an own converter on the ZIP and XML readers of the text extraction
(attachments.extract.packages, with their decompression budget and without document type or
entity declarations), for structure and emphasis, not layout.

From content.xml: paragraphs; headings by outline level (h1 to h6); bold, italic and underline of
the paragraph and text styles (automatic styles and the named ones of styles.xml, with their
parents); line breaks, tabs and runs of spaces (text:s); lists, numbered when their list style
numbers that level; tables with column and row spans and header rows; images of the package
(Pictures/) as raster data: URLs (sanitize.Images) or the placeholder, their title as alt text;
footnotes and endnotes at the end, under their citation, with links back and forth. Comments,
tracked deletions, forms, scripts and embedded objects are left out; links keep their text.
Whitespace in the XML collapses to one space, as ODF wants; the page keeps the spaces and tabs
that text:s and text:tab stand for (white-space: pre-wrap).

An encrypted document says so in META-INF/manifest.xml (as in attachments.extract.odf).
"""

import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape

from mailrobbe.attachments.extract.base import Damaged, Encrypted
from mailrobbe.attachments.extract.packages import Package, attribute
from mailrobbe.preview.sanitize import IMAGE_PLACEHOLDER, Images

_MANIFEST = "META-INF/manifest.xml"
_MAX_SPACES = 64  # of one text:s
_PARENTS = 16  # style parents followed at most
_WHITESPACE = re.compile(r"[ \t\r\n]+")
# Subtrees shown neither as text nor otherwise.
_SKIPPED = frozenset(
    {
        "tracked-changes",
        "annotation",
        "forms",
        "scripts",
        "event-listeners",
        "binary-data",
        "object",
        "object-ole",
        "covered-table-cell",
        "sequence-decls",
        "variable-decls",
        "user-field-decls",
    }
)
_LEVEL_STYLES = ("list-level-style-number", "list-level-style-bullet", "list-level-style-image")

End = str | Callable[[], None]  # what the end of an element does: write HTML, or call


def odt_html(data: bytes) -> str:
    """The HTML of an ODT body, not yet sanitized."""
    package = Package(data)
    if _MANIFEST in package.names and b"encryption-data" in package.read(_MANIFEST):
        raise Encrypted
    if "content.xml" not in package.names:
        raise Damaged("no content part (content.xml)")
    styles = _Styles()
    if "styles.xml" in package.names:
        package.parse("styles.xml", styles)
    converter = _Converter(package, styles)
    package.parse("content.xml", converter)
    return converter.html()


@dataclass(slots=True)
class _Style:
    parent: str | None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None


class _Styles:
    """Emphasis of the paragraph and text styles, and which list levels are numbered; fed with
    styles.xml and the automatic styles at the start of content.xml."""

    def __init__(self) -> None:
        self._styles: dict[tuple[str, str], _Style] = {}  # by family and name
        self._lists: dict[str, dict[int, bool]] = {}  # list style -> level -> numbered
        self._style: _Style | None = None  # the style:style being read
        self._list: dict[int, bool] | None = None  # the text:list-style being read

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == "style":
            self._style = _Style(attribute(attrs, "parent-style-name"))
            key = (attribute(attrs, "family") or "", attribute(attrs, "name") or "")
            self._styles[key] = self._style
        elif name == "text-properties" and self._style is not None:
            weight = attribute(attrs, "font-weight")
            if weight:
                self._style.bold = weight == "bold" or (weight.isdigit() and int(weight) >= 600)
            posture = attribute(attrs, "font-style")
            if posture:
                self._style.italic = posture in ("italic", "oblique")
            underline = attribute(attrs, "text-underline-style")
            if underline:
                self._style.underline = underline != "none"
        elif name == "list-style":
            self._list = self._lists.setdefault(attribute(attrs, "name") or "", {})
        elif name in _LEVEL_STYLES and self._list is not None:
            level = attribute(attrs, "level") or ""
            if level.isdigit():
                self._list[int(level)] = name == "list-level-style-number"

    def end(self, name: str) -> None:
        if name == "style":
            self._style = None
        elif name == "list-style":
            self._list = None

    def data(self, text: str) -> None:
        pass

    def emphasis(self, family: str, name: str | None) -> tuple[str, ...]:
        """The tags (strong, em, u) of a style, its own settings before its parents'."""
        bold = italic = underline = None
        for _ in range(_PARENTS):
            style = self._styles.get((family, name or ""))
            if style is None:
                break
            bold = style.bold if bold is None else bold
            italic = style.italic if italic is None else italic
            underline = style.underline if underline is None else underline
            name = style.parent
        found = (("strong", bold), ("em", italic), ("u", underline))
        return tuple(tag for tag, on in found if on)

    def numbered(self, name: str | None, level: int) -> bool:
        levels = self._lists.get(name or "", {})
        return levels.get(level, levels.get(1, False))


@dataclass(slots=True)
class _Output:
    """HTML written for the document, or for one note's body."""

    parts: list[str] = field(default_factory=list)
    paragraphs: int = 0  # open paragraphs: a text box's paragraphs sit inside one
    label: str = ""  # a note's link back, written into its first paragraph


@dataclass(slots=True)
class _Frame:
    """A draw:frame: its images (package members), and its title or description as alt text."""

    depth: int
    images: list[str] = field(default_factory=list)
    alt: list[str] = field(default_factory=list)
    in_alt: bool = False


@dataclass(slots=True)
class _Note:
    number: int
    kind: str  # footnote or endnote
    citation: list[str] = field(default_factory=list)
    in_citation: bool = False


class _Converter:
    """content.xml to HTML; see the module docstring."""

    def __init__(self, package: Package, styles: _Styles) -> None:
        self._package = package
        self._styles = styles
        self._images = Images()
        self._outputs = [_Output()]  # the document, then the note whose body is being read
        self._ends: list[End] = []  # per open element of the body
        self._in_body = False
        self._skip = 0  # depth inside a skipped subtree
        self._lists: list[str | None] = []  # the list style of each open list
        self._header_rows = 0
        self._frames: list[_Frame] = []
        self._notes: list[_Note] = []  # the open notes
        self._numbered = 0  # notes so far
        self._written: dict[str, list[str]] = {"footnote": [], "endnote": []}

    def html(self) -> str:
        notes = self._written["footnote"] + self._written["endnote"]
        body = "".join(self._outputs[0].parts)
        return (body + "<hr>" + "".join(notes)) if notes else body

    # expat callbacks

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if self._skip:
            self._skip += 1
        elif not self._in_body:
            self._in_body = name == "body"
            self._styles.start(name, attrs)  # the automatic styles before the body
        elif name in _SKIPPED:
            self._skip = 1
        else:
            self._ends.append(self._open(name, attrs))

    def end(self, name: str) -> None:
        if self._skip:
            self._skip -= 1
        elif not self._ends:
            self._in_body = self._in_body and name != "body"
            self._styles.end(name)
        else:
            end = self._ends.pop()
            if isinstance(end, str):
                self._write(end)
            else:
                end()

    def data(self, text: str) -> None:
        if self._skip or not self._in_body:
            return
        if self._notes and self._notes[-1].in_citation:
            self._notes[-1].citation.append(text)
        elif self._frames and self._frames[-1].in_alt:
            self._frames[-1].alt.append(text)
        elif self._out.paragraphs:
            self._write(escape(_WHITESPACE.sub(" ", text), quote=False))

    # elements

    @property
    def _out(self) -> _Output:
        return self._outputs[-1]

    def _write(self, html: str) -> None:
        self._out.parts.append(html)

    def _open(self, name: str, attrs: dict[str, str]) -> End:
        """Write the start of an element of the body; returns what its end does."""
        match name:
            case "p" | "h":
                return self._paragraph(name, attrs)
            case "span":
                return self._emphasis(self._styles.emphasis("text", attribute(attrs, "style-name")))
            case "s":
                count = attribute(attrs, "c") or "1"
                self._write(" " * min(int(count) if count.isdigit() else 1, _MAX_SPACES))
            case "tab":
                self._write("\t")
            case "line-break":
                self._write("<br>")
            case "list":
                return self._list(attrs)
            case "list-item" | "list-header":
                self._write("<li>")
                return "</li>"
            case "table":
                self._write("<table>")
                return "</table>"
            case "table-header-rows":
                self._header_rows += 1
                self._write("<thead>")
                return self._header_rows_end
            case "table-row":
                self._write("<tr>")
                return "</tr>"
            case "table-cell":
                return self._cell(attrs)
            case "frame":
                self._frames.append(_Frame(len(self._ends) + 1))
                return self._frame_end
            case "image" if self._frames:
                self._frames[-1].images.append(attribute(attrs, "href") or "")
            case "title" | "desc" if self._frames and self._frames[-1].depth == len(self._ends):
                self._frames[-1].in_alt = True
                return self._alt_end
            case "note":
                kind = "endnote" if attribute(attrs, "note-class") == "endnote" else "footnote"
                self._numbered += 1
                self._notes.append(_Note(self._numbered, kind))
                return self._note_end
            case "note-citation" if self._notes:
                self._notes[-1].in_citation = True
                return self._citation_end
            case "note-body" if self._notes:
                note = self._notes[-1]
                label = escape(_label(note))
                back = f'<sup><a href="#note-ref-{note.number}">{label}</a></sup> '
                self._outputs.append(_Output(label=back))
                return self._note_body_end
        return ""

    def _paragraph(self, name: str, attrs: dict[str, str]) -> End:
        out = self._out
        out.paragraphs += 1

        def end(closing: str) -> Callable[[], None]:
            def close() -> None:
                out.parts.append(closing)
                out.paragraphs -= 1

            return close

        if out.paragraphs > 1:  # a paragraph of a text box inside a paragraph
            out.parts.append("<br>")
            return end("")
        if name == "h":
            level = attribute(attrs, "outline-level") or "1"
            tag = f"h{min(max(int(level), 1), 6) if level.isdigit() else 1}"
            tags: tuple[str, ...] = ()
        else:
            tag = "p"
            tags = self._styles.emphasis("paragraph", attribute(attrs, "style-name"))
        out.parts.append(f"<{tag}>{out.label}" + "".join(f"<{t}>" for t in tags))
        out.label = ""
        return end("".join(f"</{t}>" for t in reversed(tags)) + f"</{tag}>")

    def _emphasis(self, tags: tuple[str, ...]) -> str:
        self._write("".join(f"<{tag}>" for tag in tags))
        return "".join(f"</{tag}>" for tag in reversed(tags))

    def _list(self, attrs: dict[str, str]) -> End:
        style = attribute(attrs, "style-name") or (self._lists[-1] if self._lists else None)
        self._lists.append(style)
        tag = "ol" if self._styles.numbered(style, len(self._lists)) else "ul"
        self._write(f"<{tag}>")

        def close() -> None:
            self._write(f"</{tag}>")
            self._lists.pop()

        return close

    def _header_rows_end(self) -> None:
        self._write("</thead>")
        self._header_rows -= 1

    def _cell(self, attrs: dict[str, str]) -> str:
        tag = "th" if self._header_rows else "td"
        spans = ""
        for key, name in (("columns", "colspan"), ("rows", "rowspan")):
            value = attribute(attrs, f"number-{key}-spanned") or ""
            if value.isdigit() and int(value) > 1:
                spans += f' {name}="{int(value)}"'
        self._write(f"<{tag}{spans}>")
        return f"</{tag}>"

    def _frame_end(self) -> None:
        frame = self._frames.pop()
        if not frame.images:
            return
        alt = " ".join("".join(frame.alt).split())
        url = next(filter(None, map(self._image, frame.images)), None)  # the first one shown
        if url is None:
            self._write(escape(IMAGE_PLACEHOLDER))
        else:
            self._write(f'<img src="{url}" alt="{escape(alt)}">')

    def _image(self, href: str) -> str | None:
        """An image of the package as a data: URL; None for another image or a link outside."""
        member = posixpath.normpath(href).lstrip("/")
        if ":" in href or member not in self._package.names:
            return None
        try:
            return self._images.data_url(self._package.pieces(member))
        except Damaged:  # a broken image does not stop the document
            return None

    def _alt_end(self) -> None:
        self._frames[-1].in_alt = False

    def _citation_end(self) -> None:
        note = self._notes[-1]
        note.in_citation = False
        label = escape(_label(note))
        self._write(
            f'<sup><a href="#note-{note.number}" id="note-ref-{note.number}">{label}</a></sup>'
        )

    def _note_end(self) -> None:
        self._notes.pop()

    def _note_body_end(self) -> None:
        out = self._outputs.pop()
        note = self._notes[-1]
        body = "".join(out.parts)
        self._written[note.kind].append(f'<div id="note-{note.number}">{out.label}{body}</div>')


def _label(note: _Note) -> str:
    return " ".join("".join(note.citation).split()) or str(note.number)

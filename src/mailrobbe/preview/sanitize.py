"""What a converted document may contain (D122), and the page it is served as.

sanitize writes HTML anew through an allow list on html.parser: every tag and attribute it keeps
is serialised again and escaped, so the browser parses exactly what the list allows, whatever the
input did to confuse a parser. It keeps text structure (paragraphs, headings, emphasis, lists,
tables), ids, colspan and rowspan (digits), links within the document and raster images as data:
URLs. Elements holding code or metadata (script, style, svg, iframe, form, head, ...) go with
their content; any other element goes and its text stays. No style or event attribute survives,
and no URL apart from those data: URLs and the links within the document.

A link within the document (href="#id") is written as about:srcdoc#id: the app shows the page in
<iframe srcdoc>, where a bare #id resolves against the app's own URL and would load the app into
the frame instead of scrolling to the note (tried in Chromium).

page wraps the result into the document the API serves: its own Content-Security-Policy (a srcdoc
frame inherits the app's policy; this one narrows it to inline styles and data: images) and one
small stylesheet for readable text.

Images embeds a document's images as data: URLs when their first bytes prove PNG, JPEG, GIF or
WebP, at most IMAGE_BUDGET bytes per document; the converters write IMAGE_PLACEHOLDER for
anything else (EMF, WMF, SVG, TIFF, linked images).
"""

import base64
import re
from collections.abc import Iterable
from html import escape
from html.parser import HTMLParser

IMAGE_PLACEHOLDER = "[Bild nicht darstellbar]"
IMAGE_BUDGET = 32 * 1024**2  # image bytes one document may embed
POLICY = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"

_KEPT = frozenset(
    {
        "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s", "sub",
        "sup", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
        "blockquote", "pre", "code", "span", "div", "hr", "a", "img",
    }
)  # fmt: skip
# Elements whose content is code or metadata: dropped with everything inside them.
_DROPPED = frozenset(
    {
        "script", "style", "template", "iframe", "object", "embed", "svg", "math", "form",
        "noscript", "title", "head", "link", "meta", "base", "applet", "frame", "frameset",
        "noembed", "noframes",
    }
)  # fmt: skip
# Elements without content or end tag in HTML.
_VOID = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
        "source", "track", "wbr",
    }
)  # fmt: skip
_FRAGMENT = "about:srcdoc#"  # a link within the page, in the app's srcdoc frame
_SPAN = re.compile(r"[1-9][0-9]{0,3}")
_RASTER_URL = re.compile(r"data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}")
_RASTER_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
_STYLE = (
    "html{color-scheme:light}"
    "body{margin:0 auto;padding:16px 20px;max-width:50rem;color:#1f2328;background:#fff;"
    "font:15px/1.55 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;overflow-wrap:anywhere}"
    "p,h1,h2,h3,h4,h5,h6,li,td,th,caption{white-space:pre-wrap;tab-size:4}"
    "h1{font-size:1.6em}h2{font-size:1.35em}h3{font-size:1.15em}h4,h5,h6{font-size:1em}"
    "table{border-collapse:collapse;margin:.75em 0}"
    "td,th{border:1px solid #c8ccd1;padding:.25em .5em;vertical-align:top;text-align:left}"
    "td>p,th>p,li>p{margin:.2em 0}"
    "img{max-width:100%;height:auto}"
    "hr{border:0;border-top:1px solid #c8ccd1;margin:1.5em 0}"
)


def sanitize(html: str) -> str:
    """The HTML with only what the allow list keeps, every tag closed."""
    parser = _Sanitizer()
    parser.feed(html)
    parser.close()
    return parser.result()


def page(body: str) -> str:
    """The served document around sanitized HTML."""
    return (
        '<!doctype html>\n<html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">'
        f"<style>{_STYLE}</style></head><body>{body}</body></html>\n"
    )


def raster_type(head: bytes) -> str | None:
    """image/png, image/jpeg, image/gif or image/webp when the first bytes prove it."""
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    for signature, media_type in _RASTER_SIGNATURES:
        if head.startswith(signature):
            return media_type
    return None


class Images:
    """A document's images as data: URLs, at most IMAGE_BUDGET bytes in all."""

    def __init__(self) -> None:
        self._left = IMAGE_BUDGET

    def data_url(self, pieces: Iterable[bytes]) -> str | None:
        """The image read from pieces as a data: URL; None when it is no raster image a browser
        shows, or larger than what is left of the budget."""
        data = bytearray()
        for piece in pieces:
            data += piece
            if len(data) > self._left:
                return None
        media_type = raster_type(bytes(data[:12]))
        if media_type is None:
            return None
        self._left -= len(data)
        return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._open: list[str] = []  # kept elements not closed yet
        self._dropping: str | None = None  # the dropped element whose content is skipped
        self._depth = 0  # how often it is open

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._dropping is not None:
            if tag == self._dropping:
                self._depth += 1
            return
        if tag in _DROPPED:
            if tag not in _VOID:
                self._dropping, self._depth = tag, 1
            return
        if tag not in _KEPT:
            return
        kept = _attributes(tag, attrs)
        if tag == "img" and "src" not in kept:
            self._out.append(escape(IMAGE_PLACEHOLDER))
            return
        written = "".join(f' {name}="{escape(value)}"' for name, value in kept.items())
        self._out.append(f"<{tag}{written}>")
        if tag not in _VOID:
            self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._dropping is not None:
            if tag == self._dropping:
                self._depth -= 1
                if not self._depth:
                    self._dropping = None
            return
        if tag not in self._open:
            return  # never opened, or void
        while self._open:
            name = self._open.pop()
            self._out.append(f"</{name}>")
            if name == tag:
                return

    def handle_data(self, data: str) -> None:
        if self._dropping is None:
            self._out.append(escape(data, quote=False))

    def result(self) -> str:
        return "".join(self._out) + "".join(f"</{name}>" for name in reversed(self._open))


def _attributes(tag: str, attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    """The attributes kept of an element, by the allow list; the first of a name counts."""
    kept: dict[str, str] = {}
    seen: set[str] = set()
    for name, value in attrs:
        if value is None or name in seen:
            continue
        seen.add(name)
        if name == "href":
            if tag == "a" and value.startswith(("#", _FRAGMENT)):
                kept[name] = _FRAGMENT + value.partition("#")[2]
        elif _allowed(tag, name, value):
            kept[name] = value
    return kept


def _allowed(tag: str, name: str, value: str) -> bool:
    """Whether an attribute other than href is kept as it is."""
    match name:
        case "id":
            return True
        case "colspan" | "rowspan":
            return tag in ("td", "th") and _SPAN.fullmatch(value) is not None
        case "src":
            return tag == "img" and _RASTER_URL.fullmatch(value) is not None
        case "alt":
            return tag == "img"
    return False

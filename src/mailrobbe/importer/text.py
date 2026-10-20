"""Text out of mail bytes: charsets with heuristics, RFC 2047 encoded words, base64, HTML.

Archives hold mislabelled, undeclared and unknown charsets, raw 8-bit headers and broken
encodings (SPEC 3.5). Nothing here raises for such input: bytes that do not decode as declared
are tried as UTF-8, then cp1252, then latin-1 (which never fails), and every guess is reported
as an ENCODING issue naming the header or part (`where`). Text labelled as a Western 8-bit
charset that is valid UTF-8 is taken as UTF-8, the common mislabelling. iso-8859-1 is read as
cp1252, as browsers do, so the quotes and euro signs of Windows mailers survive.
"""

import binascii
import codecs
import functools
import re
from html.parser import HTMLParser

from mailrobbe.enums import ImportErrorKind
from mailrobbe.importer.model import Issue

_ALIASES = {"iso8859-1": "cp1252", "gb2312": "gb18030", "gbk": "gb18030"}
_WESTERN = frozenset({"cp1252", "iso8859-15"})  # where mislabelled UTF-8 is checked for
_FALLBACKS = ("utf-8", "cp1252", "latin-1")
# NUL and lone surrogates: PostgreSQL text cannot hold them.
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")
# An encoded word; one whose closing `?=` is missing ends at whitespace or the end.
_ENCODED_WORD = re.compile(r"=\?([^?\s]+)\?([BbQq])\?(\S*?)(\?=|(?=\s)|$)")
_SPACES = re.compile(r"\s+")
_BASE64_LETTERS = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
_NOT_BASE64 = bytes(sorted(set(range(256)) - set(_BASE64_LETTERS)))


def clean(text: str) -> str:
    """Text without NUL characters and lone surrogates."""
    return _UNSTORABLE.sub("", text)


def ascii_bytes(text: str) -> bytes:
    """The bytes behind a str the compat32 parser made (ASCII, 8-bit bytes as surrogates)."""
    try:
        return text.encode("ascii", "surrogateescape")
    except UnicodeEncodeError:
        return text.encode("utf-8", "surrogatepass")


@functools.lru_cache(maxsize=512)
def _codec(charset: str) -> str | None:
    """Python codec of a MIME charset label; None when unknown or not a text encoding."""
    label = charset.strip().strip("\"'").partition("*")[0]  # RFC 2231 adds *language
    try:
        name = codecs.lookup(label).name
        b"x".decode(name)  # LookupError for codecs such as base64 that do not make text
    except (LookupError, ValueError):
        return None
    return _ALIASES.get(name, name)


def _guess(data: bytes) -> tuple[str, str]:
    for codec in _FALLBACKS[:-1]:
        try:
            return data.decode(codec), codec
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1"), "latin-1"


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def decode_bytes(data: bytes, charset: str | None, where: str, issues: list[Issue]) -> str:
    """Text of `data` in `charset` (None: US-ASCII, the MIME default), with heuristics."""
    codec = _codec(charset) if charset else "ascii"
    if codec is None:
        text, used = _guess(data)
        issues.append(
            Issue(ImportErrorKind.ENCODING, f"{where}: unknown charset {charset!r}, read as {used}")
        )
        return text
    if codec in _WESTERN and not data.isascii() and _is_utf8(data):
        issues.append(Issue(ImportErrorKind.ENCODING, f"{where}: labelled {charset} but is UTF-8"))
        return data.decode("utf-8")
    try:
        return data.decode(codec)
    except UnicodeError:  # also what idna raises for a label it cannot take
        text, used = _guess(data)
        label = charset or "US-ASCII"
        issues.append(
            Issue(ImportErrorKind.ENCODING, f"{where}: invalid {label} bytes, read as {used}")
        )
        return text


def header_text(value: str, where: str, issues: list[Issue]) -> str:
    """A header value as compat32 holds it: raw 8-bit bytes decoded, folding removed.

    UTF-8 is what RFC 6532 allows in headers, so it passes silently; other 8-bit bytes are read
    as cp1252 (or latin-1) with an issue. Encoded words are left for decode_words.
    """
    if not value.isascii():
        data = ascii_bytes(value)
        try:
            value = data.decode("utf-8")
        except UnicodeDecodeError:
            value, used = _guess(data)
            issues.append(
                Issue(ImportErrorKind.ENCODING, f"{where}: raw 8-bit bytes, read as {used}")
            )
    return value.replace("\r", "").replace("\n", "")


def decode_words(text: str, where: str, issues: list[Issue]) -> str:
    """RFC 2047: encoded words decoded, whitespace between adjacent ones dropped.

    Adjacent words of one charset are joined before decoding, since mailers split multibyte
    characters across words. A malformed word (bad base64, missing `?=`) is decoded as far as
    possible, with one issue per header.
    """
    if "=?" not in text:
        return text
    out: list[str] = []
    charset: str | None = None
    run = b""
    broken = False
    end = 0
    for match in _ENCODED_WORD.finditer(text):
        gap = text[end : match.start()]
        end = match.end()
        word_charset, method, payload, closing = match.groups()
        if method in "Bb":
            data, valid = decode_base64(payload.encode("ascii", "replace"))
        else:
            data = binascii.a2b_qp(payload.encode("ascii", "replace"), header=True)
            valid = True
        broken = broken or not valid or closing != "?="
        if charset is not None and not gap.strip():
            if word_charset.lower() == charset:
                run += data
                continue
            out.append(decode_bytes(run, charset, where, issues))
        else:
            if charset is not None:
                out.append(decode_bytes(run, charset, where, issues))
            out.append(gap)
        charset, run = word_charset.lower(), data
    if charset is not None:
        out.append(decode_bytes(run, charset, where, issues))
    out.append(text[end:])
    if broken:
        issues.append(Issue(ImportErrorKind.ENCODING, f"{where}: malformed encoded word"))
    return "".join(out)


def decode_base64(data: bytes) -> tuple[bytes, bool]:
    """Base64 as RFC 2045 asks: whitespace ignored; on errors lenient, and False.

    Lenient means characters outside the alphabet are skipped and padding ends a run of letters
    that is decoded on its own (concatenated base64 blocks), missing padding added, so whatever
    can be decoded is.
    """
    letters = data.translate(None, b" \t\r\n")
    try:
        return binascii.a2b_base64(letters, strict_mode=True), True
    except binascii.Error:
        pass
    decoded = []
    for run in letters.translate(None, _NOT_BASE64).split(b"="):
        run = run[: len(run) - (len(run) % 4 == 1)]  # a single letter left over holds no byte
        if run:
            decoded.append(binascii.a2b_base64(run + b"=" * (-len(run) % 4)))
    return b"".join(decoded), False


class _HtmlText(HTMLParser):
    """Collects the text a reader sees: no head, script or style; blocks on lines of their own."""

    _SKIP = frozenset({"script", "style", "template", "noscript", "title"})
    _BLOCK = frozenset(
        {
            *("address", "article", "aside", "blockquote", "br", "center", "dd", "details"),
            *("div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form"),
            *("h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol"),
            *("p", "pre", "section", "summary", "table", "tbody", "tfoot", "thead", "tr", "ul"),
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._in_head = False
        self._skipping = 0
        self._pre = 0  # inside <pre>: line breaks are text

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head":
            self._in_head = True
        elif tag == "body":
            self._in_head = False
        elif tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")
            self._pre += tag == "pre"
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
        elif tag in self._SKIP:
            self._skipping = max(0, self._skipping - 1)
        elif tag in self._BLOCK and tag != "br":
            self.parts.append("\n")
            if tag == "pre":
                self._pre = max(0, self._pre - 1)

    def handle_data(self, data: str) -> None:
        if not (self._in_head or self._skipping):
            self.parts.append(data if self._pre else _SPACES.sub(" ", data))


def html_to_text(html: str) -> str:
    """Readable text of an HTML body: entities unescaped, one empty line at most in a row."""
    parser = _HtmlText()
    try:
        parser.feed(html)
        parser.close()
    except AssertionError:  # html.parser gives up on some broken declarations
        pass
    lines: list[str] = []
    for line in "".join(parser.parts).split("\n"):
        line = " ".join(line.split())
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip("\n")

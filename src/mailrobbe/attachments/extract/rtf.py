"""RTF (D71): the text with control words stripped.

A small tokenizer over the bytes: groups, control words and symbols, \\'hh bytes (decoded with
the document's \\ansicpg code page, cp1252 by default) and \\uN characters (followed by \\ucN
fallback characters, which are dropped). Destinations without text of their own (font and
colour tables, style sheets, document info, pictures, objects, field instructions and every
\\* destination) are skipped; headers, footers, footnotes and field results are text. A
damaged file (unbalanced braces) is read as far as it goes.
"""

import codecs
import re

from mailrobbe.attachments.extract.base import Sink
from mailrobbe.enums import DocumentTextStatus

_TOKEN = re.compile(
    rb"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?"  # control word with its parameter
    rb"|\\'([0-9a-fA-F]{2})"  # a byte in the code page
    rb"|\\([^a-zA-Z'])"  # control symbol
    rb"|([{}])"
    rb"|[\r\n]+"  # line breaks in the file are not text
    rb"|([^\\{}\r\n]+)"
)
_SKIPPED = frozenset(
    {
        *(b"fonttbl", b"colortbl", b"stylesheet", b"info", b"pict", b"object", b"themedata"),
        *(b"colorschememapping", b"datastore", b"latentstyles", b"listtable", b"rsidtbl"),
        *(b"listoverridetable", b"generator", b"xmlnstbl", b"mmathPr", b"fldinst", b"filetbl"),
        *(b"revtbl", b"pgdsctbl", b"operator", b"nonshppict", b"sp", b"background"),
        *(b"wgrffmtfilter", b"objdata", b"bkmkstart", b"bkmkend", b"protusertbl"),
    }
)
_BREAKS = frozenset({b"par", b"line", b"sect", b"page", b"row"})
_CHARACTERS = {
    b"tab": "\t",
    b"cell": "\t",
    b"emdash": "\u2014",
    b"endash": "\u2013",
    b"bullet": "\u2022",
    b"lquote": "\u2018",
    b"rquote": "\u2019",
    b"ldblquote": "\u201c",
    b"rdblquote": "\u201d",
    b"emspace": " ",
    b"enspace": " ",
    b"qmspace": " ",
}
_SYMBOLS = {b"~": "\u00a0", b"-": "", b"_": "-", b"\\": "\\", b"{": "{", b"}": "}"}


def _codec(number: int) -> str:
    try:
        return codecs.lookup(f"cp{number}").name
    except LookupError:
        return "cp1252"


def extract_rtf(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    codec = "cp1252"
    line: list[str] = []
    pending = bytearray()  # \'hh bytes, decoded together (multibyte code pages)
    stack: list[tuple[bool, int]] = []  # per open group: (skipped, \uc value)
    skipped = False
    uc = 1
    fallback = 0  # characters still to drop after a \u
    first = False  # the next token is the first of its group
    position = 0
    size = len(data)

    def take_pending() -> None:
        if pending:
            line.append(pending.decode(codec, "replace"))
            pending.clear()

    while position < size:
        match = _TOKEN.match(data, position)
        if match is None:  # a lone backslash at the end
            break
        position = match.end()
        word, parameter, hex_byte, symbol, brace, text = match.groups()
        starts_group = first
        first = False
        if hex_byte is not None:
            if fallback:
                fallback -= 1
            elif not skipped:
                pending.append(int(hex_byte, 16))
            continue
        take_pending()
        if brace == b"{":
            stack.append((skipped, uc))
            first = True
        elif brace == b"}":
            if stack:
                skipped, uc = stack.pop()
            fallback = 0
        elif word is not None:
            if word == b"bin" and parameter:
                position += max(0, int(parameter))  # binary data follows
            elif starts_group and word in _SKIPPED:
                skipped = True
            elif word == b"ansicpg" and parameter:
                codec = _codec(int(parameter))
            elif word == b"uc" and parameter:
                uc = max(0, int(parameter))
            elif skipped:
                pass
            elif word == b"u" and parameter:
                value = int(parameter)
                line.append(chr(value + 65536 if value < 0 else value))
                fallback = uc
            elif word in _BREAKS:
                sink.line("".join(line))
                line.clear()
            elif word in _CHARACTERS:
                line.append(_CHARACTERS[word])
        elif symbol is not None:
            if symbol == b"*":
                skipped = True
            elif symbol in (b"\n", b"\r"):
                if not skipped:
                    sink.line("".join(line))
                    line.clear()
            elif not skipped and symbol in _SYMBOLS:
                line.append(_SYMBOLS[symbol])
        elif text is not None and not skipped:
            if fallback:
                dropped = min(fallback, len(text))
                fallback -= dropped
                text = text[dropped:]
            line.append(text.decode(codec, "replace"))
    take_pending()
    sink.line("".join(line))
    return None

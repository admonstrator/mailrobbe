"""Quoted text in a mail's text (D151, D152): the one rule that tells the sender's own words from
what they quote or forward, for the folded text view of the mail detail (api/body.py) and the
fingerprint of near duplicates (near/model.py), so that both agree.

    text       the sender's own words
    quote      lines starting with ">" anywhere in the text (the history of a reply, inline
               answers, bottom posting), with the attribution above them ("Am … schrieb …:",
               "On … wrote:", also wrapped onto two lines)
    original   an Outlook block, to the end of the text: a separator line ("-----Original
               Message-----", "-----Ursprüngliche Nachricht-----"), or "Von:"/"From:" followed
               within three lines by "Gesendet:"/"Sent:" (also "*Von:*" as Outlook's text
               export writes it) with the rule of underscores above it
    forward    a forwarded message, to the end of the text: "-------- Weitergeleitete
               Nachricht --------", "---------- Forwarded message ---------", "Anfang der
               weitergeleiteten Nachricht:", "Begin forwarded message:"
    signature  from a line "-- " (or "--" when a client dropped the space) to the next segment
               of another kind or the end

split_text cuts a text into segments that cover it in order without gaps; a blank line belongs
to the segment of the line above it, blank lines at the start to the first segment. Folded at
first are originals, forwards, signatures and a quote with no own words after it (the history);
a quote between own paragraphs stays open up to OPEN_QUOTE_LINES lines. A text without words of
its own (a forward, a quote without an answer) shows its first segment open.

unquoted_lines applies the same rules to every line of a text, nested history included: what is
left once the quote markers, the attributions and the head and header lines of originals and
forwards are gone.
"""

import re
from dataclasses import dataclass
from typing import Literal

# The kind of a segment, the same as schemas.SegmentKind.
Kind = Literal["text", "quote", "original", "forward", "signature"]

OPEN_QUOTE_LINES = 5  # a quote between own paragraphs with more lines than this starts folded
_ATTRIBUTION_LENGTH = 400  # characters; a longer line is no attribution

_ATTRIBUTION = re.compile(r"(?:Am\s.+\sschrieb\b.*|On\s.+\swrote):")
_SEPARATOR = re.compile(r"-{2,}\s*(?:Ursprüngliche Nachricht|Original Message)\s*-{2,}", re.I)
_FORWARD = re.compile(
    r"-{2,}\s*(?:Weitergeleitete Nachricht|Forwarded Message)\s*-{2,}"
    r"|Anfang der weitergeleiteten Nachricht:|Begin forwarded message:",
    re.I,
)
_RULE = re.compile(r"_{20,}")
_FROM = re.compile(r"\*?(?:Von|From):")
_SENT = re.compile(r"\*?(?:Gesendet|Sent):")
_HEADER = re.compile(r"\*?(?:Von|From|Gesendet|Sent|Datum|Date|An|To|Cc|Betreff|Subject)\*?:")
_QUOTED = re.compile(r"\s*>")
_MARKERS = re.compile(r"^\s*(?:>\s?)+")
_CONTENT = re.compile(r"[^\s>]")
_DELIMITERS = ("-- ", "--")


@dataclass(frozen=True, slots=True)
class Segment:
    kind: Kind
    start: int  # character offset in the text
    end: int  # exclusive
    lines: int  # lines with something on them besides quote markers
    folded: bool  # shown folded at first


def split_text(text: str) -> list[Segment]:
    """The text's segments (module docstring); one text segment for a text without quotes."""
    lines = text.split("\n")
    spans: list[tuple[Kind, int, int]] = []  # kind, first line, line after the last
    for index, kind in enumerate(_kinds(lines)):
        if spans and spans[-1][0] == kind:
            spans[-1] = (kind, spans[-1][1], index + 1)
        else:
            spans.append((kind, index, index + 1))
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    counts = [
        sum(1 for line in lines[first:last] if _CONTENT.search(line)) for _, first, last in spans
    ]
    own = [index for index, (kind, _, _) in enumerate(spans) if kind == "text" and counts[index]]
    segments = []
    for index, (kind, first, last) in enumerate(spans):
        folded = kind != "text"
        if kind == "quote":  # the history, or a long quote between own words
            folded = not own or own[-1] < index or counts[index] > OPEN_QUOTE_LINES
        if index == 0 and not own:
            folded = False
        end = min(offsets[last], len(text))
        segments.append(Segment(kind, offsets[first], end, counts[index], folded))
    return segments


def unquoted_lines(text: str) -> list[str]:
    """The text's lines without quote markers, without the attribution above a quote and
    without the head and header lines of every original and forward, nested ones too (D152):
    a forward without words of its own then reads like the mail it forwards."""
    lines = text.split("\n")
    framing: set[int] = set()
    for index in range(len(lines)):
        block = _block(lines, index)
        if block is not None:
            framing.update(range(block[1], _header_end(lines, index)))
    for first, count in _attributions(lines, len(lines)):
        framing.update(range(first, first + count))
    return [_MARKERS.sub("", line) for index, line in enumerate(lines) if index not in framing]


def _kinds(lines: list[str]) -> list[Kind]:
    """The kind of every line; a blank line takes the kind of the line above it."""
    found: list[Kind | None] = [None if _blank(line) else "text" for line in lines]
    cut = len(lines)  # the original or forward that runs to the end
    for index in range(len(lines)):
        block = _block(lines, index)
        if block is not None:
            kind, cut = block
            found[cut:] = [kind] * (len(lines) - cut)
            break
    for index in range(cut):
        if _QUOTED.match(lines[index]):
            found[index] = "quote"
    for first, count in _attributions(lines, cut):
        found[first : first + count] = ["quote"] * count
    index = 0
    while index < cut:
        if lines[index].rstrip("\r") in _DELIMITERS:
            while index < cut and found[index] != "quote":
                found[index] = "signature"
                index += 1
        index += 1
    top: Kind = next((kind for kind in found if kind is not None), "text")
    kinds: list[Kind] = []
    for line_kind in found:
        kinds.append(line_kind or (kinds[-1] if kinds else top))
    return kinds


def _block(lines: list[str], index: int) -> tuple[Kind, int] | None:
    """An original or a forward starting at this line: its kind and its first line (the rule of
    underscores above an Outlook header block)."""
    line = lines[index].strip()
    if _FORWARD.fullmatch(line):
        return "forward", index
    if _SEPARATOR.fullmatch(line):
        return "original", index
    if not _FROM.match(line):
        return None
    if not any(_SENT.match(below.strip()) for below in lines[index + 1 : index + 4]):
        return None
    above = index - 1
    return "original", above if above >= 0 and _RULE.fullmatch(lines[above].strip()) else index


def _header_end(lines: list[str], index: int) -> int:
    """The line after the head (at index) and the header lines of an original or a forward; the
    header lines run to the next blank line."""
    after = index if _FROM.match(lines[index].strip()) else index + 1
    while after < len(lines) and _blank(lines[after]):
        after += 1
    if after < len(lines) and _HEADER.match(lines[after].strip()):
        while after < len(lines) and not _blank(lines[after]):
            after += 1
    return after


def _attributions(lines: list[str], end: int) -> list[tuple[int, int]]:
    """The attribution above each block of quoted lines before line end, blank lines between
    them allowed: its first line and its length (two lines when a client wrapped it)."""
    found = []
    above = -1  # the last line before index that is not blank
    for index in range(end):
        if _blank(lines[index]):
            continue
        if _QUOTED.match(lines[index]) and above >= 0 and not _QUOTED.match(lines[above]):
            if _attribution(lines[above]):
                found.append((above, 1))
            elif above > 0 and _attribution(f"{lines[above - 1].strip()} {lines[above].strip()}"):
                found.append((above - 1, 2))
        above = index
    return found


def _attribution(line: str) -> bool:
    line = line.strip()
    return len(line) <= _ATTRIBUTION_LENGTH and _ATTRIBUTION.fullmatch(line) is not None


def _blank(line: str) -> bool:
    return not line.strip()

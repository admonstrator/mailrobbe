# ruff: noqa: RUF001  (typographic quotes, apostrophes and dashes in texts are meant)
"""The contexts of amounts, IBANs and account numbers (D82): cash, donation, receipt.

An occurrence takes the contexts of the context words (terms.find_terms) in its sentence. A
sentence ends at ., ! or ? followed by whitespace and a capital (a dot after an abbreviation such
as Dr. or Nr., a single letter or a number ends none: "am 3. Oktober"), at a blank line, and in a
table at the end of the line. A table line is one with a tab, two semicolons or vertical bars,
or two commas directly before a word (Spende,DE89...): the rows of spreadsheets and CSV files,
whose cells are no sentences. A sentence reaches at most WINDOW characters to either side of the
occurrence, so that a long list without punctuation (a table in a PDF) does not lend its words
to every amount in it.
"""

import re
from bisect import bisect_left, bisect_right

from mailrobbe.entities.occurrences import Occurrences
from mailrobbe.enums import EntityContext

WINDOW = 250
_ABBREVIATIONS = frozenset(
    ["abs", "abt", "bd", "bzgl", "bzw", "ca", "co", "corp", "dipl", "dr", "evtl", "fa", "fr",
     "gem", "geb", "ggf", "hr", "inc", "inkl", "ing", "jh", "jr", "kto", "ltd", "max", "min",
     "mio", "mr", "mrd", "mrs", "ms", "mwst", "nr", "pkt", "prof", "rd", "sog", "sr", "st", "std",
     "str", "tel", "tsd", "usw", "vgl", "vs", "zt", "zzgl"]
)  # fmt: skip
_END = re.compile(r"([.!?])[.!?]*(?=\s+[\"'„‚“‘(«»]?[A-ZÄÖÜ])|\n[^\S\n]*\n")
_WORD_BEFORE = re.compile(r"\w*\Z")
# Each alternative scans its line at most twice: [^\n;]* cannot pass a semicolon, and the lazy
# scans for a second comma give up only when the line has fewer than two.
_CSV_COMMA = r",(?=[^\W\d_])"
_TABLE_LINE = re.compile(
    rf"^(?:[^\n]*?\t|(?:[^\n;]*;){{2}}|(?:[^\n|]*\|){{2}}|[^\n]*?{_CSV_COMMA}[^\n]*?{_CSV_COMMA})"
    r"[^\n]*$",
    re.MULTILINE,
)


def mark(found: Occurrences, words: list[tuple[int, int, EntityContext]]) -> None:
    """Give each amount, IBAN and account the contexts of the words in its sentences."""
    entries = found.contextual()
    if not entries or not words:
        return
    bounds = _boundaries(found.text)
    word_starts = [start for start, _, _ in words]
    for entry in entries:
        for start, end in entry.spans:
            low = max(bounds[bisect_right(bounds, start) - 1], start - WINDOW)
            high = min(bounds[bisect_left(bounds, end)], end + WINDOW)
            index = bisect_left(word_starts, low)
            while index < len(words) and words[index][0] < high:
                if words[index][1] <= high:
                    entry.context |= words[index][2]
                index += 1


def _boundaries(text: str) -> list[int]:
    """Sentence boundaries, sorted, from 0 to len(text)."""
    bounds = {0, len(text)}
    for match in _END.finditer(text):
        if match.group(1) == ".":
            start = match.start()
            before = _WORD_BEFORE.search(text, max(0, start - 12), start)
            word = before.group() if before else ""
            if len(word) < 2 or word.isdigit() or word.lower() in _ABBREVIATIONS:
                continue
        bounds.add(match.end())
    for line in _TABLE_LINE.finditer(text):
        bounds.update((line.start(), line.end()))
    return sorted(bounds)

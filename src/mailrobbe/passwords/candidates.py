"""Password candidates in a text (D234): the word after a keyword like "Kennwort".

A candidate is the word after Kennwort, Passwort, Passphrase, PW, Pass, Code, Zugangscode, PIN,
password, passphrase or pwd, any case, with an optional colon or "ist"/"lautet"/"is" between (up
to four words may stand before such a separator); on the same or the next line, surrounding
quotes stripped. No word lists and no guessing (D207): a wrong
candidate only costs one try at the file, the file decides.

`candidates(text)` yields each distinct candidate with the line(s) it stands in, so a finding can
show where a password was written (D208). It is pure and used for mails and for document texts.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

PASSWORD_MAX_LENGTH = 128  # a candidate longer than this is not a password people type
CANDIDATES_VERSION = 1  # raise when the rule changes: the passwords step scans everything again

_KEYWORDS = (
    "kennwort",
    "kennworts",
    "passwort",
    "passworts",
    "passphrase",
    "zugangscode",
    "zugangsdaten",
    "password",
    "passwords",
    "passcode",
    "pwd",
    "pw",
    "pin",
    "code",
    "pass",
)
# A keyword, an optional "ist"/"lautet"/"is"/":"/"=" (or two, "lautet:"), then the candidate up to
# white space or quotes; after such a word the candidate may stand on the next line. Up to four
# words may stand between the keyword and such a separator ("Passwort für das ZIP lautet: X").
# The keyword stands at a word boundary; "pass" does not fire inside "passen" (\b after it). A word
# longer than PASSWORD_MAX_LENGTH is no candidate, not even its beginning. Every keyword starts a
# match of its own, so one candidate never swallows the next keyword ("Das Kennwort für die Datei
# von neulich:" on one line, "Kennwort: X" on the next).
_KEYWORD = "|".join(sorted(_KEYWORDS, key=len, reverse=True))
_KEYWORD_AT = re.compile(rf"\b(?:{_KEYWORD})\b", re.IGNORECASE)
_SEPARATOR = r"(?:(?:ist|lautet|is)\b|=|:)[ \t]*"
_CHARACTER = r"[^\s\"'»«„“”‚‘’`()\[\]<>]"  # noqa: RUF001 - of a password, up to these quotes
_CANDIDATE = re.compile(
    rf"\b(?:{_KEYWORD})\b"
    rf"(?:(?:[ \t]+[^\s:=]+){{1,4}}?[ \t]*{_SEPARATOR}(?:{_SEPARATOR})?(?:\n[ \t]*)?"
    rf"|[ \t]*(?:(?:{_SEPARATOR}){{1,2}}(?:\n[ \t]*)?)?)"
    r"[\"'»«„“”‚‘’`(\[]?"  # noqa: RUF001 - German quotation marks a sender may wrap a password in
    rf"(?P<value>{_CHARACTER}{{1,{PASSWORD_MAX_LENGTH}}})(?!{_CHARACTER})",
    re.IGNORECASE,
)
_TRAILING = ".,;:"  # sentence punctuation; a form without it is tried too (D207: a try is cheap)


@dataclass(frozen=True, slots=True)
class Candidate:
    value: str  # the password as written
    context: str  # the line(s) it was found in, for the evidence (D208)


def candidates(text: str) -> Iterator[Candidate]:
    """Each distinct password candidate of a text, with the line(s) it stands in, first seen
    first."""
    if not text:
        return
    lines = text.splitlines()
    joined = "\n".join(lines)
    seen: set[str] = set()
    for keyword in _KEYWORD_AT.finditer(joined):
        match = _CANDIDATE.match(joined, keyword.start())
        if match is None:
            continue
        raw = match.group("value")
        context = _context(joined, match.start(), match.end())
        for value in (raw, raw.rstrip(_TRAILING)):
            # a word has a letter or a digit: "Kennwort:" or "das Passwort, das" holds none
            if any(c.isalnum() for c in value) and value not in seen:
                seen.add(value)
                yield Candidate(value, context)


def _context(text: str, start: int, end: int) -> str:
    """The line(s) from `start` to `end` (a keyword, its candidate on the next line), trimmed, at
    most 300 characters."""
    first = text.rfind("\n", 0, start) + 1
    last = text.find("\n", end)
    lines = text[first : last if last != -1 else len(text)].strip()
    return lines if len(lines) <= 300 else lines[:297] + "..."

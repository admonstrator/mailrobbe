"""Password candidates in a text (D234): the word after a keyword like "Kennwort".

A candidate is the word after Kennwort, Passwort, Passphrase, PW, Pass, Code, Zugangscode, PIN,
password, passphrase or pwd, any case, with an optional colon or "ist"/"lautet" between; on the
same or the next line, surrounding quotes stripped. No word lists and no guessing (D207): a wrong
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
# A keyword, an optional "ist"/"lautet"/":"/"=" (or two, "lautet:"), then the candidate up to
# white space or quotes; after such a word the candidate may stand on the next line. The keyword
# stands at a word boundary; "pass" does not fire inside "passen" (\b after it).
_KEYWORD = "|".join(sorted(_KEYWORDS, key=len, reverse=True))
_CANDIDATE = re.compile(
    rf"\b(?:{_KEYWORD})\b"
    r"[ \t]*(?:(?:(?:ist|lautet|=|:)[ \t]*){1,2}(?:\n[ \t]*)?)?"
    r"[\"'»«„“”‚‘’`(\[]?"  # noqa: RUF001 - German quotation marks a sender may wrap a password in
    r"(?P<value>[^\s\"'»«„“”‚‘’`()\[\]<>]{1,%d})" % PASSWORD_MAX_LENGTH,  # noqa: RUF001
    re.IGNORECASE,
)
_TRAILING = ".,;:"  # sentence punctuation; a form without it is tried too (D207: a try is cheap)


@dataclass(frozen=True, slots=True)
class Candidate:
    value: str  # the password as written
    context: str  # the line(s) it was found in, for the evidence (D208)


def candidates(text: str) -> Iterator[Candidate]:
    """Each distinct password candidate of a text, with its surrounding line, first seen first."""
    if not text:
        return
    lines = text.splitlines()
    joined = "\n".join(lines)
    seen: set[str] = set()
    for match in _CANDIDATE.finditer(joined):
        raw = match.group("value")
        context = _context(joined, match.start())
        for value in (raw, raw.rstrip(_TRAILING)):
            if value and len(value) <= PASSWORD_MAX_LENGTH and value not in seen:
                seen.add(value)
                yield Candidate(value, context)


def _context(text: str, at: int) -> str:
    """The line holding position `at`, trimmed, at most 300 characters."""
    start = text.rfind("\n", 0, at) + 1
    end = text.find("\n", at)
    line = text[start : end if end != -1 else len(text)].strip()
    return line if len(line) <= 300 else line[:297] + "..."

"""The search syntax of the mail list (SPEC 4, D20): q split into terms, no SQL.

Tokens are separated by whitespace; double quotes group, also inside a token
(`subject:"finale Fassung"`, `"exakte Phrase"`), and an unclosed quote runs to the end of q.
A token `name:value` with a known operator name (any case) and a non-empty value is an operator
term; a bare `<local@host>` is a Message-ID; everything else is one full-text term per token,
including unknown prefixes such as `Re:` or `https:` and operators without a value. An operator
whose value cannot be used raises QueryError naming the token. filters.py turns the terms into
SQL; every term must hold.
"""

import re
from datetime import date
from typing import get_args

from mailrobbe.api.schemas import DkimKey, QueryKey, QueryTerm

DKIM_KEYS: tuple[DkimKey, ...] = get_args(DkimKey)
_OPERATORS: dict[str, QueryKey] = {
    key: key for key in get_args(QueryKey) if key not in ("text", "message_id")
}
_TOKEN = re.compile(r'(?:[^\s"]+|"[^"]*(?:"|\Z))+')
_OPERATOR = re.compile(r"([A-Za-z]+):(.*)", re.DOTALL)
_MESSAGE_ID = re.compile(r"<[^<>\s@]+@[^<>\s]+>")
_ISO_DAY = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_GERMAN_DAY = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


class QueryError(ValueError):
    """An operator with a value that cannot be used; `term` is the token as written in q."""

    def __init__(self, term: str, problem: str) -> None:
        super().__init__(f"{problem}: {term}")
        self.term = term


def parse_query(q: str) -> list[QueryTerm]:
    """The terms of q in order; raw is the exact substring of q for each."""
    return [_term(match.group()) for match in _TOKEN.finditer(q)]


def parse_day(value: str) -> date | None:
    """A day written as YYYY-MM-DD or DD.MM.YYYY; None for anything else."""
    if iso := _ISO_DAY.fullmatch(value):
        year, month, day = iso.groups()
    elif german := _GERMAN_DAY.fullmatch(value):
        day, month, year = german.groups()
    else:
        return None
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _term(raw: str) -> QueryTerm:
    operator = _OPERATOR.fullmatch(raw)
    if operator:
        key = _OPERATORS.get(operator.group(1).lower())
        value = _unquote(operator.group(2))
        if key and value:
            return QueryTerm(key=key, value=_checked(key, value, raw), raw=raw)
    value = _unquote(raw)
    if '"' not in raw and _MESSAGE_ID.fullmatch(raw):
        return QueryTerm(key="message_id", value=value, raw=raw)
    return QueryTerm(key="text", value=value, raw=raw)


def _checked(key: str, value: str, raw: str) -> str:
    """The value of an operator term; enumerated values in lower case."""
    if key == "has":
        if value.lower() != "attachment":
            raise QueryError(raw, "has: only knows attachment")
        return "attachment"
    if key == "dkim":
        if value.lower() not in DKIM_KEYS:
            raise QueryError(raw, f"dkim: takes one of {', '.join(DKIM_KEYS)}")
        return value.lower()
    if key in ("after", "before") and parse_day(value) is None:
        raise QueryError(raw, f"{key}: takes a day as YYYY-MM-DD or DD.MM.YYYY")
    return value


def _unquote(text: str) -> str:
    return text.replace('"', "")

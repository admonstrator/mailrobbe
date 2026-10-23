"""The search syntax of the mail list (SPEC 4, D20): q split into terms, no SQL.

Tokens are separated by whitespace; double quotes group, also inside a token
(`subject:"finale Fassung"`, `"exakte Phrase"`), and an unclosed quote runs to the end of q.
A token `name:value` with a known operator name (any case) and a non-empty value is an operator
term; a bare `<local@host>` is a Message-ID; everything else is one full-text term per token,
including unknown prefixes such as `Re:` or `https:` and operators without a value. The
operators betreff:, text:, anhang: and datei: are full text words looked for in one place only
(D172). A token `"a b"~N` is a proximity term (D229, key near): the two words in the quotes with
at most N words between them, in either order, N from 1 to PROXIMITY_LIMIT; anything else after
the closing quote's `~`, or another number of words than two, is unusable, while `"a b"` alone
stays a phrase. from:, to:, cc:, bcc: and recipient: (To, Cc or Bcc) take a party (D340): a part
of an address or a name, or with a leading @ or dot a domain, `@beispiel.de` that domain with its
subdomains and `.ru` every domain ending so; domain: takes a domain in any of these forms and
looks at every role; between: takes two parties separated by a comma, one of which sent the mail
and the other received it (`between:anna,.ru`). A leading minus negates an operator, a proximity
term or a Message-ID (D175);
free text words keep it, since websearch_to_tsquery reads it. An operator or a proximity term
that cannot be used raises QueryError naming the token. filters.py turns the terms into SQL;
every term must hold.
"""

import re
from datetime import date
from typing import get_args

from mailrobbe.api.schemas import PROXIMITY_LIMIT, DkimKey, QueryKey, QueryTerm

DKIM_KEYS: tuple[DkimKey, ...] = get_args(DkimKey)
# Full text words in one place (D172): German names, as the filter column names the places.
PLACED: dict[str, QueryKey] = {
    "betreff": "in_subject",
    "text": "in_body",
    "anhang": "in_attachment",
    "datei": "in_filename",
}
_OPERATORS: dict[str, QueryKey] = {
    key: key
    for key in get_args(QueryKey)
    if key not in ("text", "message_id", "near") and key not in PLACED.values()
} | PLACED
# Operators taking a party of a role; `recipient` stands for To, Cc and Bcc together (D340).
ADDRESS_KEYS: tuple[QueryKey, ...] = ("from", "to", "cc", "bcc", "recipient")
_TOKEN = re.compile(r'(?:[^\s"]+|"[^"]*(?:"|\Z))+')
_OPERATOR = re.compile(r"([A-Za-z]+):(.*)", re.DOTALL)
_MESSAGE_ID = re.compile(r"<[^<>\s@]+@[^<>\s]+>")
_NEAR = re.compile(r'"([^"]*)"~(.*)', re.DOTALL)  # "a b"~N, whatever follows the tilde
_DISTANCE = re.compile(r"[0-9]+")
_ISO_DAY = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_GERMAN_DAY = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


class QueryError(ValueError):
    """An operator or a proximity term that cannot be used; `term` is the token as written in
    q."""

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


def party_domain(party: str) -> str | None:
    """The domain a party of an address operator names (D340), lower case without its leading @
    and dots, when it starts with @ or a dot; None for a part of an address or a name."""
    return party.lower().lstrip("@.") if party.startswith(("@", ".")) else None


def between_parties(value: str) -> list[str]:
    """The parties of between: as written, separated by commas (D340)."""
    return [party.strip() for party in value.split(",")]


def _term(raw: str) -> QueryTerm:
    if raw.startswith("-") and (negated := _operator(raw[1:], raw)):
        return negated.model_copy(update={"negated": True})
    return _operator(raw, raw) or QueryTerm(key="text", value=_unquote(raw), raw=raw)


def _operator(token: str, raw: str) -> QueryTerm | None:
    """The operator, proximity or Message-ID term token is, raw being the token as written; None
    for a full text word."""
    if near := _NEAR.fullmatch(token):
        return _near(near.group(1), near.group(2), raw)
    operator = _OPERATOR.fullmatch(token)
    if operator:
        key = _OPERATORS.get(operator.group(1).lower())
        value = _unquote(operator.group(2))
        if key and value:
            return QueryTerm(key=key, value=_checked(key, value, raw), raw=raw)
    if '"' not in token and _MESSAGE_ID.fullmatch(token):
        return QueryTerm(key="message_id", value=_unquote(token), raw=raw)
    return None


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
    parties = between_parties(value) if key == "between" else [value]
    if key == "between" and (len(parties) != 2 or not all(parties)):
        raise QueryError(raw, "between: takes two parties separated by a comma")
    if key == "domain" and not value.strip("@."):
        raise QueryError(raw, "domain: takes a domain")
    if key in (*ADDRESS_KEYS, "between") and any(party_domain(p) == "" for p in parties):
        raise QueryError(raw, f"{key}: takes a domain after @ or the dot")
    if key in ("after", "before") and parse_day(value) is None:
        raise QueryError(raw, f"{key}: takes a day as YYYY-MM-DD or DD.MM.YYYY")
    return value


def _near(words: str, distance: str, raw: str) -> QueryTerm:
    """The proximity term "words"~distance (D229): two words, at most distance words apart."""
    if not _DISTANCE.fullmatch(distance) or not 1 <= int(distance) <= PROXIMITY_LIMIT:
        raise QueryError(raw, f"a proximity term takes ~ and a number from 1 to {PROXIMITY_LIMIT}")
    if len(words.split()) != 2:
        raise QueryError(raw, "a proximity term takes exactly two words in its quotes")
    return QueryTerm(key="near", value=" ".join(words.split()), raw=raw, distance=int(distance))


def _unquote(text: str) -> str:
    return text.replace('"', "")

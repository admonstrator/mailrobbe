"""The full text part of a mail list search (D79, D170 to D176): q's words, where they are looked
for, whole words, and how often they must occur. Pure, apart from the SQL helpers at the end.

The free words of q are what websearch_to_tsquery reads (text_search): words, "phrases", a
leading minus for a word that must not occur, and "or" between alternatives, where the words
written next to each other must all occur (websearch's `a b or c` is `(a & b) | c`). FullText
keeps them as such groups, so that a whole word search (D173) can test them word by word. The
operators betreff:, text:, anhang: and datei: (query.PLACED) are words looked for in one place
only, each a condition of its own like any operator.

Places (D171) are the weights of the two tsvectors (migrations 0002 and 0008): in mail.tsv the
subject is A and the text B, in document.tsv the file names are A and the text B. A query limited
to some places carries those weights on its lexemes (weighted), which the GIN indexes serve with
a recheck, so the places need no index of their own.

A whole word (D173) is the word as written, in any case, not inside a longer word: letters and
digits around it end it, anything else does not (spaces, punctuation, the _ . - of file names).
Its German stem is always in the tsvector of a text holding it, so the full text indexes find the
candidates (prefilter) and a regular expression (word_regex) decides on their texts.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, get_args

from sqlalchemy import ColumnElement, Text, cast, func, literal_column
from sqlalchemy.dialects.postgresql import TSQUERY

from mailrobbe.api.schemas import QueryKey, QueryTerm, SearchField
from mailrobbe.db.models import TEXT_SEARCH_CONFIG

FIELDS: tuple[SearchField, ...] = get_args(SearchField)
# The places of each tsvector by weight (D171).
MAIL_WEIGHTS: dict[SearchField, str] = {"subject": "A", "body": "B"}
DOCUMENT_WEIGHTS: dict[SearchField, str] = {"filename": "A", "attachment": "B"}
# The place of each placed operator (query.PLACED).
PLACE_OF: dict[QueryKey, SearchField] = {
    "in_subject": "subject",
    "in_body": "body",
    "in_attachment": "attachment",
    "in_filename": "filename",
}
TEXT_SEARCH: ColumnElement[Any] = literal_column(f"'{TEXT_SEARCH_CONFIG}'::regconfig")

_SPECIAL = frozenset("\\^$.|?*+()[]{}")  # escaped alike in PostgreSQL's and Python's syntax
_LEXEME = r"('(?:[^']|'')*')"  # a lexeme in the text of a tsquery, quotes doubled inside


@dataclass(frozen=True, slots=True)
class Words:
    """A word or a quoted phrase of q as typed, without its quotes and its minus."""

    text: str  # the word, or the phrase's words separated by single spaces
    phrase: bool = False  # written in quotes
    negated: bool = False  # written with a leading minus: must not occur

    def websearch(self) -> str:
        """The words as websearch_to_tsquery reads them."""
        written = f'"{self.text}"' if self.phrase else self.text
        return f"-{written}" if self.negated else written


@dataclass(frozen=True, slots=True)
class FullText:
    """The full text words of q with the list's options (MailFilters.scope, whole_word,
    min_hits)."""

    search: str  # the free words as websearch_to_tsquery reads them (text_search); "" without
    # The free words as alternatives (or) of words that must all hold, in q's order; a group
    # may hold negated words only. () without free words, and for a q of "or" alone, which
    # websearch_to_tsquery reads as the word "or".
    groups: tuple[tuple[Words, ...], ...]
    fields: frozenset[SearchField]  # where the free words are looked for; all four by default
    placed: tuple[tuple[SearchField, Words], ...]  # betreff:, text:, anhang:, datei:, in order
    whole_word: bool
    min_hits: int | None

    @property
    def counted(self) -> tuple[tuple[Words, frozenset[SearchField]], ...]:
        """The words whose occurrences count for min_hits and MailHitCounts (D174, D176), each
        with the places it is looked for: the free words that are not negated in fields, the
        placed ones that are not negated in their place. A word typed twice counts once."""
        found: dict[tuple[Words, frozenset[SearchField]], None] = {}
        for group in self.groups:
            for words in group:
                if not words.negated:
                    found[words, self.fields] = None
        for field, words in self.placed:
            if not words.negated:
                found[words, frozenset((field,))] = None
        return tuple(found)

    def prefilter(self) -> str | None:
        """The free words for websearch_to_tsquery without the negated ones, alternatives kept:
        what a whole word search asks the index for (D173), since a text holding a word holds its
        stem. None when an alternative has no word that must occur (nothing to ask the index)
        or there are no free words."""
        if not self.groups or any(all(w.negated for w in group) for group in self.groups):
            return None
        alternatives = (
            " ".join(w.websearch() for w in group if not w.negated) for group in self.groups
        )
        return " or ".join(alternatives)


def full_text_search(
    terms: Sequence[QueryTerm],
    scope: Sequence[SearchField] = (),
    whole_word: bool = False,
    min_hits: int | None = None,
) -> FullText | None:
    """The full text part of q's terms with the options; None when q has no full text words
    (free or placed), and then the options have no effect."""
    search = text_search(terms)
    placed = tuple(
        (PLACE_OF[term.key], _words(term, negated=term.negated))
        for term in terms
        if term.key in PLACE_OF and term.value.strip()
    )
    if not search and not placed:
        return None
    return FullText(
        search=search,
        groups=_groups(terms),
        fields=frozenset(scope) or frozenset(FIELDS),
        placed=placed,
        whole_word=whole_word,
        min_hits=min_hits,
    )


def text_search(terms: Sequence[QueryTerm]) -> str:
    """q's free words as websearch_to_tsquery reads them; "" without any."""
    return " ".join(_phrase(term) for term in terms if term.key == "text")


def _phrase(term: QueryTerm) -> str:
    """A text term for websearch_to_tsquery: quoted tokens stay phrases."""
    return f'"{term.value}"' if '"' in term.raw else term.value


def _groups(terms: Sequence[QueryTerm]) -> tuple[tuple[Words, ...], ...]:
    """The free words as websearch_to_tsquery groups them: "or" (any case, unquoted) between
    two words separates alternatives, an "or" at either end or after another is dropped."""
    groups: list[list[Words]] = [[]]
    for term in terms:
        if term.key != "text":
            continue
        if '"' not in term.raw and term.value.lower() == "or":
            if groups[-1]:
                groups.append([])
            continue
        negated = term.raw.startswith("-")
        words = _words(term, negated=negated)
        if words.text:
            groups[-1].append(words)
    return tuple(tuple(group) for group in groups if group)


def _words(term: QueryTerm, negated: bool) -> Words:
    value = term.value[1:] if term.key == "text" and negated else term.value
    return Words(text=" ".join(value.split()), phrase='"' in term.raw, negated=negated)


# Whole words (D173) ---------------------------------------------------------------------------


def word_regex(words: Words) -> str:
    """A regular expression of PostgreSQL (ARE) for the words as written, to be used without
    regard to case (~*, the flag i): not inside a longer word, any characters other than letters
    and digits between the words of a phrase."""
    body = "[^[:alnum:]]+".join(_escaped(part) for part in words.text.split())
    return f"(?<![[:alnum:]]){body}(?![[:alnum:]])"


def word_regex_python(words: Words) -> re.Pattern[str]:
    """word_regex for Python's re, ignoring case, for texts read back (snippets)."""
    body = r"[\W_]+".join(re.escape(part) for part in words.text.split())
    return re.compile(rf"(?<![^\W_]){body}(?![^\W_])", re.IGNORECASE)


def _escaped(text: str) -> str:
    return "".join("\\" + char if char in _SPECIAL else char for char in text)


# SQL ------------------------------------------------------------------------------------------


def ts_query(search: str) -> ColumnElement[Any]:
    """The tsquery of words written as websearch_to_tsquery reads them."""
    return func.websearch_to_tsquery(TEXT_SEARCH, search)


def weighted(query: ColumnElement[Any], weights: str) -> ColumnElement[Any]:
    """query with every lexeme limited to these weights ("A", "B" or "AB"; D171). Immutable like
    query, so PostgreSQL computes it once while planning and the GIN index serves it, rechecking
    the weights on the rows it finds."""
    labelled = func.regexp_replace(cast(query, Text), _LEXEME, rf"\1:{weights}", "g")
    return cast(labelled, TSQUERY)


def weights(fields: frozenset[SearchField], places: dict[SearchField, str]) -> str:
    """The weights of the fields among places (MAIL_WEIGHTS or DOCUMENT_WEIGHTS), sorted; ""
    when none of them is there."""
    return "".join(sorted(places[field] for field in fields if field in places))

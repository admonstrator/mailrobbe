"""The full text part of a mail list search (D79, D170 to D176, D226, D229): q's words, where
they are looked for, whole words, and how often they must occur. Pure, apart from the SQL helpers
at the end.

The free words of q are what websearch_to_tsquery reads (text_search): words, "phrases", a
leading minus for a word that must not occur, and "or" between alternatives, where the words
written next to each other must all occur (websearch's `a b or c` is `(a & b) | c`). FullText
keeps them as such groups, so that a whole word search (D173) can test them word by word. The
operators betreff:, text:, anhang: and datei: (query.PLACED) are words looked for in one place
only; a proximity term `"a b"~N` (D229) is its two words with at most N words between them, in
either order, looked for in the places of the free words. Each of these is a condition of its
own like any operator, never part of the free words' alternatives. A proximity term asks for
the OR of the phrases `a <k> b` and `b <k> a` for k from 1 to N + 1 (near_query), each word
stemmed as in a phrase: at most 2 * (PROXIMITY_LIMIT + 1) alternatives of the same lexemes.

Places (D171) are the weights of the two tsvectors (migrations 0002, 0008 and 0016): in mail.tsv
the subject is A and the text B (the sender's own words), C (quotes, originals, forwards) and D
(standard blocks); in document.tsv the file names are A and the text B. Which weights a mail's
text is depends on body_part (D226, BODY_WEIGHTS): clean, the default, B and C; own B; full B,
C and D. A mail without ranges has its whole text in B, so the default finds what it found
before them. A query limited to some places carries those weights on its lexemes (weighted),
which the GIN indexes serve with a recheck, so the places need no index of their own. Where the
weights chosen hold all a mail without ranges carries (A and B), the index is asked the query
as before and only the mails with ranges are rechecked with the weighted one (mail_recheck), so
that the default search reads no tsvector the index does not for the others.

A whole word (D173) is the word as written, in any case, not inside a longer word: letters and
digits around it end it, anything else does not (spaces, punctuation, the _ . - of file names).
A word or a phrase in quotes is always looked for as written (D341, FullText.exact), the other
words of the same search by their stems unless whole_word is set; a proximity term keeps its
stems, its quotes being the syntax of the pair.
Its German stem is always in the tsvector of a text holding it, so the full text indexes find the
candidates (prefilter) and a regular expression (word_regex) decides on their stored texts, a
mail's text cut to its body_part (stored_texts). A proximity term of whole words asks the index
for its two words anywhere; the expression counts the words between as runs of letters and
digits.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce
from typing import Any, get_args

from sqlalchemy import ColumnElement, Text, and_, cast, func, literal, literal_column, or_
from sqlalchemy.dialects.postgresql import TSQUERY

from mailrobbe.api.schemas import BodyPart, QueryKey, QueryTerm, SearchField
from mailrobbe.db.models import TEXT_SEARCH_CONFIG, Document, Mail

FIELDS: tuple[SearchField, ...] = get_args(SearchField)
# The weights of a mail's text by the parts body_part looks at (D226), and of the places of
# document.tsv (D171); every weight each tsvector carries, with which a query needs none.
BODY_WEIGHTS: dict[BodyPart, str] = {"clean": "BC", "own": "B", "full": "BCD"}
DOCUMENT_WEIGHTS: dict[SearchField, str] = {"filename": "A", "attachment": "B"}
MAIL_TSV_WEIGHTS = "ABCD"
DOCUMENT_TSV_WEIGHTS = "AB"
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
_NO_RANGES: ColumnElement[Any] = literal_column("'{}'::int4multirange")
# The ranges giving mail.tsv a weight beyond A and B (D226): C the quotes, D the standard blocks.
_RANGES = {"C": Mail.history, "D": Mail.blocks}


def mail_weights(body_part: BodyPart) -> dict[SearchField, str]:
    """The places of mail.tsv by weight, its text the parts body_part looks at (D226)."""
    return {"subject": "A", "body": BODY_WEIGHTS[body_part]}


@dataclass(frozen=True, slots=True)
class Words:
    """A word, a quoted phrase or a proximity term of q as typed, without its quotes and its
    minus."""

    text: str  # the word, or the words separated by single spaces
    phrase: bool = False  # written in quotes
    negated: bool = False  # written with a leading minus: must not occur
    distance: int | None = None  # a proximity term "a b"~N (D229): N, text its two words

    def websearch(self) -> str:
        """The words as websearch_to_tsquery reads them; a proximity term as its two words,
        each quoted, which occur wherever it holds, without a minus (websearch has no form of a
        negated one): what the index is asked with whole words, and the words to mark."""
        if self.distance is not None:
            return " ".join(f'"{word}"' for word in self.text.split())
        written = f'"{self.text}"' if self.phrase else self.text
        return f"-{written}" if self.negated else written


@dataclass(frozen=True, slots=True)
class FullText:
    """The full text words of q with the list's options (MailFilters.scope, whole_word,
    min_hits, body_part)."""

    search: str  # the free words as websearch_to_tsquery reads them (text_search); "" without
    # The free words as alternatives (or) of words that must all hold, in q's order; a group
    # may hold negated words only. () without free words.
    groups: tuple[tuple[Words, ...], ...]
    fields: frozenset[SearchField]  # where the free words are looked for; all four by default
    placed: tuple[tuple[SearchField, Words], ...]  # betreff:, text:, anhang:, datei:, in order
    whole_word: bool
    min_hits: int | None
    body_part: BodyPart = "clean"  # the parts of the mail's own text looked at (D226)
    near: tuple[Words, ...] = ()  # the proximity terms (D229) in q's order, looked for in fields

    def exact(self, words: Words) -> bool:
        """Whether words are looked for as written (D173, D341): all of them with whole_word,
        otherwise a quoted word or phrase."""
        return self.whole_word or words.phrase

    @property
    def mixed(self) -> bool:
        """Whether some free words are looked for as written and others by their stems (D341)."""
        return not self.whole_word and any(w.phrase for group in self.groups for w in group)

    @property
    def counted(self) -> tuple[tuple[Words, frozenset[SearchField]], ...]:
        """The words whose occurrences count for min_hits and MailHitCounts (D174, D176), each
        with the places it is looked for: the free words and the proximity terms that are not
        negated in fields, the placed ones that are not negated in their place. A word typed
        twice counts once."""
        found: dict[tuple[Words, frozenset[SearchField]], None] = {}
        for group in self.groups:
            for words in group:
                if not words.negated:
                    found[words, self.fields] = None
        for field, words in self.placed:
            if not words.negated:
                found[words, frozenset((field,))] = None
        for words in self.near:
            if not words.negated:
                found[words, self.fields] = None
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
    body_part: BodyPart = "clean",
) -> FullText | None:
    """The full text part of q's terms with the options; None when q has no full text words
    (free, placed or near each other), and then the options have no effect."""
    search = text_search(terms)
    placed = tuple(
        (PLACE_OF[term.key], _words(term, negated=term.negated))
        for term in terms
        if term.key in PLACE_OF and term.value.strip()
    )
    near = tuple(
        Words(text=term.value, negated=term.negated, distance=term.distance)
        for term in terms
        if term.key == "near"
    )
    if not search and not placed and not near:
        return None
    return FullText(
        search=search,
        groups=_groups(terms),
        fields=frozenset(scope) or frozenset(FIELDS),
        placed=placed,
        whole_word=whole_word,
        min_hits=min_hits,
        body_part=body_part,
        near=near,
    )


def text_search(terms: Sequence[QueryTerm]) -> str:
    """q's free words as websearch_to_tsquery reads them; "" without any."""
    return " ".join(_phrase(term) for term in terms if term.key == "text")


def _phrase(term: QueryTerm) -> str:
    """A text term for websearch_to_tsquery: quoted tokens stay phrases, a leading minus stays
    before the quotes (inside them websearch_to_tsquery would drop it)."""
    if '"' not in term.raw:
        return term.value
    if term.raw.startswith("-"):
        return f'-"{term.value[1:]}"'
    return f'"{term.value}"'


def _groups(terms: Sequence[QueryTerm]) -> tuple[tuple[Words, ...], ...]:
    """The free words as websearch_to_tsquery (PostgreSQL 16) groups them: "or" (any case,
    unquoted) after a word and before another separates alternatives; first, last or after
    another "or" it is the word "or" (`or a or or b or` is `(or & a) | (or & b & or)`)."""
    texts = [term for term in terms if term.key == "text"]
    groups: list[list[Words]] = [[]]
    after_word = False
    for index, term in enumerate(texts):
        last = index == len(texts) - 1
        if after_word and not last and '"' not in term.raw and term.value.lower() == "or":
            groups.append([])
            after_word = False
            continue
        words = _words(term, negated=term.raw.startswith("-"))
        if words.text:
            groups[-1].append(words)
        after_word = True
    return tuple(tuple(group) for group in groups if group)


def _words(term: QueryTerm, negated: bool) -> Words:
    value = term.value[1:] if term.key == "text" and negated else term.value
    return Words(text=" ".join(value.split()), phrase='"' in term.raw, negated=negated)


# Whole words (D173) ---------------------------------------------------------------------------


def word_regex(words: Words) -> str:
    """A regular expression of PostgreSQL (ARE) for the words as written, to be used without
    regard to case (~*, the flag i): not inside a longer word, any characters other than letters
    and digits between the words of a phrase, and between the two words of a proximity term, in
    either order, at most its distance of words (runs of letters and digits) as well."""
    parts = [_escaped(part) for part in words.text.split()]
    if words.distance is None:
        body = "[^[:alnum:]]+".join(parts)
    else:
        between = f"(?:[^[:alnum:]]+[[:alnum:]]+){{0,{words.distance}}}[^[:alnum:]]+"
        body = f"(?:{between.join(parts)}|{between.join(reversed(parts))})"
    return f"(?<![[:alnum:]]){body}(?![[:alnum:]])"


def word_regex_python(words: Words) -> re.Pattern[str]:
    """word_regex for Python's re, ignoring case, for texts read back (snippets)."""
    parts = [re.escape(part) for part in words.text.split()]
    if words.distance is None:
        body = r"[\W_]+".join(parts)
    else:
        between = rf"(?:[\W_]+[^\W_]+){{0,{words.distance}}}[\W_]+"
        body = f"(?:{between.join(parts)}|{between.join(reversed(parts))})"
    return re.compile(rf"(?<![^\W_]){body}(?![^\W_])", re.IGNORECASE)


def _escaped(text: str) -> str:
    return "".join("\\" + char if char in _SPECIAL else char for char in text)


# SQL ------------------------------------------------------------------------------------------


def ts_query(search: str) -> ColumnElement[Any]:
    """The tsquery of words written as websearch_to_tsquery reads them."""
    return func.websearch_to_tsquery(TEXT_SEARCH, search)


def words_query(words: Words, whole_word: bool = False) -> ColumnElement[Any]:
    """The tsquery the index is asked for words: as websearch_to_tsquery reads them, a
    proximity term near_query, or with whole words its two words anywhere, since then the
    expression decides on the texts (D173)."""
    if words.distance is None or whole_word:
        return ts_query(words.websearch())
    return near_query(words)


def near_query(words: Words) -> ColumnElement[Any]:
    """The two words of a proximity term at most its distance of words apart, in either order
    (D229): the OR of the phrases at the distances 1 to distance + 1 both ways, each word
    stemmed as in a phrase (a stop word has no lexeme and leaves the other word alone).
    Immutable, so PostgreSQL computes it once while planning, as ts_query."""
    assert words.distance is not None, "a proximity term"
    first, second = (func.phraseto_tsquery(TEXT_SEARCH, word) for word in words.text.split())
    phrases = [
        func.tsquery_phrase(before, after, literal(distance), type_=TSQUERY)
        for distance in range(1, words.distance + 2)
        for before, after in ((first, second), (second, first))
    ]
    return reduce(lambda found, phrase: found.op("||")(phrase), phrases)


def weighted(query: ColumnElement[Any], weights: str) -> ColumnElement[Any]:
    """query with every lexeme limited to these weights ("A", "BC", ...; D171, D226). Immutable
    like query, so PostgreSQL computes it once while planning and the GIN index serves it,
    rechecking the weights on the rows it finds."""
    labelled = func.regexp_replace(cast(query, Text), _LEXEME, rf"\1:{weights}", "g")
    return cast(labelled, TSQUERY)


def mail_matches(query: ColumnElement[Any], chosen: str, monotone: bool) -> ColumnElement[bool]:
    """What mail.tsv is asked for query in the weights chosen (D171, D226): query as it is when
    they are every weight, as before D171, or when mail_recheck decides the rest; else its
    lexemes limited to them (weighted), which the GIN index answers with a recheck reading each
    candidate's tsvector."""
    whole = Mail.tsv.bool_op("@@")
    if chosen == MAIL_TSV_WEIGHTS or _rechecked(chosen, monotone):
        return whole(query)
    return whole(weighted(query, chosen))


def mail_recheck(
    query: ColumnElement[Any], chosen: str, monotone: bool
) -> ColumnElement[bool] | None:
    """What a mail matched by mail_matches must hold besides, so that mail.tsv holds query in
    the weights chosen; None when mail_matches decides alone. If the mail holds query, it holds
    it there: it has no range giving it a weight outside them, or holds the weighted query, or
    does not hold query at all (the last two one tsquery, the tsvector read once). PostgreSQL
    decides a mail without those ranges by its columns, so that it reads its tsvector no more
    than the index does; and the condition holds for a mail found by its documents only, which
    lets it stand beside the documents' side (filters.full_text)."""
    if not _rechecked(chosen, monotone):
        return None
    plain = [column.is_(None) for weight, column in _RANGES.items() if weight not in chosen]
    either = func.tsquery_or(weighted(query, chosen), func.tsquery_not(query), type_=TSQUERY)
    return or_(and_(*plain), Mail.tsv.bool_op("@@")(either))


def _rechecked(chosen: str, monotone: bool) -> bool:
    """Whether the index is asked query as it is and the mails with ranges are rechecked.

    A mail without ranges carries A and B only, C where it has history and D where it has
    blocks (mailrobbe_mail_tsv). So when chosen holds A and B and query is monotone (no negated
    word, so that it holds wherever its weighted form does), the index is asked query exactly
    as before D226, and only a mail whose ranges may give it a weight outside chosen must hold
    the weighted form too. A query with a negated word may hold in chosen and not in the whole
    tsvector (the word in a block), and keeps the weighted form alone."""
    return chosen != MAIL_TSV_WEIGHTS and monotone and {"A", "B"} <= set(chosen)


def document_matches(query: ColumnElement[Any], chosen: str) -> ColumnElement[bool]:
    """document.tsv holds query in the weights chosen: as it is when they are both, as before
    D171."""
    every = chosen == DOCUMENT_TSV_WEIGHTS
    return Document.tsv.bool_op("@@")(query if every else weighted(query, chosen))


def weights(fields: frozenset[SearchField], places: dict[SearchField, str]) -> str:
    """The weights of the fields among places (mail_weights or DOCUMENT_WEIGHTS), sorted; ""
    when none of them is there."""
    return "".join(sorted("".join(places[field] for field in fields if field in places)))


def stored_texts(body_part: BodyPart) -> dict[SearchField, ColumnElement[Any]]:
    """The stored text of each place, in which whole words are decided and counted (D173): a
    mail's subject and its text cut to the parts body_part looks at (mailrobbe_cut, D226), a
    document's file names and text. mailrobbe_cut gives the text itself where the ranges are
    NULL or empty, so a mail without them costs nothing more."""
    body: ColumnElement[Any] = Mail.body_text.expression
    if body_part == "clean":
        body = func.mailrobbe_cut(Mail.body_text, Mail.blocks, type_=Text)
    elif body_part == "own":
        both = func.coalesce(Mail.history, _NO_RANGES).op("+")(
            func.coalesce(Mail.blocks, _NO_RANGES)
        )
        body = func.mailrobbe_cut(Mail.body_text, both, type_=Text)
    return {
        "subject": Mail.subject.expression,
        "body": body,
        "filename": Document.names.expression,
        "attachment": Document.extracted_text.expression,
    }

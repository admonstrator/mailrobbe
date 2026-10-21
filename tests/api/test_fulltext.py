"""The full text part of a search (D170 to D176): groups, places, counted words, patterns."""

import re

import pytest

from mailrobbe.api.fulltext import (
    DOCUMENT_WEIGHTS,
    FIELDS,
    MAIL_WEIGHTS,
    FullText,
    Words,
    full_text_search,
    text_search,
    weights,
    word_regex,
    word_regex_python,
)
from mailrobbe.api.query import parse_query


def _search(q: str, **options: object) -> FullText:
    found = full_text_search(parse_query(q), **options)  # type: ignore[arg-type]
    assert found is not None
    return found


def test_no_words_no_search() -> None:
    assert full_text_search(parse_query("from:anna has:attachment")) is None
    assert full_text_search([], ["subject"], True, 3) is None


def test_search_text_is_unchanged() -> None:
    q = 'Neger -negere "großer Austausch" or Umvolkung from:anna'
    assert text_search(parse_query(q)) == 'Neger -negere "großer Austausch" or Umvolkung'
    assert _search(q).search == text_search(parse_query(q))


def test_groups_follow_websearch() -> None:
    search = _search('or a b OR "c d" -e or or f or')
    assert search.groups == (
        (Words("a"), Words("b")),
        (Words("c d", phrase=True), Words("e", negated=True)),
        (Words("f"),),
    )


def test_a_quoted_or_is_a_word() -> None:
    assert _search('a "or" b').groups == ((Words("a"), Words("or", phrase=True), Words("b")),)


def test_or_alone_searches_the_word() -> None:
    search = _search("or")
    assert search.search == "or" and search.groups == ()


def test_places_default_to_all() -> None:
    assert _search("Neger").fields == frozenset(FIELDS)
    assert _search("Neger", scope=["subject", "body"]).fields == {"subject", "body"}


def test_placed_words() -> None:
    search = _search('Neger -datei:NEG betreff:"finale Fassung"')
    assert search.placed == (
        ("filename", Words("NEG", negated=True)),
        ("subject", Words("finale Fassung", phrase=True)),
    )
    assert _search("datei:NEG").search == ""


def test_counted_words() -> None:
    search = _search("a -b or a c anhang:d -datei:e", scope=["body"])
    assert search.counted == (
        (Words("a"), frozenset({"body"})),
        (Words("c"), frozenset({"body"})),
        (Words("d"), frozenset({"attachment"})),
    )


def test_prefilter() -> None:
    assert _search('a -b or "c d"').prefilter() == 'a or "c d"'
    assert _search("a or -b").prefilter() is None
    assert _search("datei:x").prefilter() is None


def test_weights() -> None:
    assert weights(frozenset(FIELDS), MAIL_WEIGHTS) == "AB"
    assert weights(frozenset({"attachment"}), MAIL_WEIGHTS) == ""
    assert weights(frozenset({"attachment", "filename"}), DOCUMENT_WEIGHTS) == "AB"
    assert weights(frozenset({"filename", "body"}), DOCUMENT_WEIGHTS) == "A"


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Neger", True),
        ("NEGER!", True),
        ("die Neger-Witze", True),
        ("Scan_NEGER_01.pdf", True),
        ("Negern", False),
        ("Negerin", False),
        ("negere", False),
        ("Kneger", False),
        ("Neger1", False),
        ("négère", False),
    ],
)
def test_python_word_pattern(text: str, found: bool) -> None:
    assert bool(word_regex_python(Words("Neger")).search(text)) is found


def test_phrases_allow_any_separator() -> None:
    pattern = word_regex_python(Words("großer Austausch", phrase=True))
    assert pattern.search("der Große Austausch") is None
    assert pattern.search("vom GROSSER  Austausch") is None  # ß is no ss
    assert pattern.search("vom großer,\nAustausch")


def test_special_characters_are_escaped() -> None:
    assert word_regex(Words("C++ (neu)")) == (
        r"(?<![[:alnum:]])C\+\+[^[:alnum:]]+\(neu\)(?![[:alnum:]])"
    )
    assert word_regex_python(Words("C++ (neu)")).search("in C++ (neu) geschrieben")
    assert re.escape("a.b") == r"a\.b"

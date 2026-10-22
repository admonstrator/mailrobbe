"""The full text part of a search (D170 to D176, D226, D229): groups, places, the parts of the
text, proximity terms, counted words, patterns."""

import re

import pytest

from mailrobbe.api.fulltext import (
    DOCUMENT_WEIGHTS,
    FIELDS,
    FullText,
    Words,
    full_text_search,
    mail_weights,
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


def test_a_minus_before_a_phrase_stays_outside_the_quotes() -> None:
    search = _search('Neger -"Neger raus" "-x y"')
    assert search.search == 'Neger -"Neger raus" "-x y"'
    assert search.groups == (
        (
            Words("Neger"),
            Words("Neger raus", phrase=True, negated=True),
            Words("-x y", phrase=True),
        ),
    )


def test_groups_follow_websearch() -> None:
    # websearch_to_tsquery: 'or' & 'a' & 'b' | 'c' <-> 'd' & !'e' | 'or' & 'f' & 'or'
    search = _search('or a b OR "c d" -e or or f or')
    assert search.groups == (
        (Words("or"), Words("a"), Words("b")),
        (Words("c d", phrase=True), Words("e", negated=True)),
        (Words("or"), Words("f"), Words("or")),
    )


def test_a_quoted_or_is_a_word() -> None:
    assert _search('a "or" b').groups == ((Words("a"), Words("or", phrase=True), Words("b")),)


def test_or_alone_searches_the_word() -> None:
    search = _search("or")
    assert search.search == "or" and search.groups == ((Words("or"),),)
    assert search.prefilter() == "or"


def test_or_after_or_is_a_word() -> None:
    # websearch_to_tsquery: 'a' | 'or' | 'b', and 'a' | 'or' & 'b'
    assert _search("a or or or b").groups == ((Words("a"),), (Words("or"),), (Words("b"),))
    assert _search("a or or b").prefilter() == "a or or b"
    assert _search("-a or").groups == ((Words("a", negated=True), Words("or")),)


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
    assert weights(frozenset(FIELDS), mail_weights("clean")) == "ABC"
    assert weights(frozenset({"attachment"}), mail_weights("clean")) == ""
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


def test_the_parts_are_weights_of_the_text() -> None:
    assert mail_weights("clean") == {"subject": "A", "body": "BC"}
    assert mail_weights("own") == {"subject": "A", "body": "B"}
    assert mail_weights("full") == {"subject": "A", "body": "BCD"}
    assert weights(frozenset(FIELDS), mail_weights("full")) == "ABCD"
    assert weights(frozenset({"body"}), mail_weights("own")) == "B"
    assert _search("Spende", body_part="own").body_part == "own"
    assert _search("Spende").body_part == "clean"


def test_a_proximity_term_alone_is_a_search() -> None:
    search = _search('"Spende bar"~2', scope=["body"])
    assert (search.search, search.groups, search.placed) == ("", (), ())
    assert search.near == (Words("Spende bar", distance=2),)
    assert search.counted == ((Words("Spende bar", distance=2), frozenset({"body"})),)
    assert search.prefilter() is None


def test_proximity_terms_count_unless_negated() -> None:
    search = _search('Rat -"Spende bar"~2 "Rat Spende"~1 datei:Liste')
    assert search.near == (
        Words("Spende bar", negated=True, distance=2),
        Words("Rat Spende", distance=1),
    )
    every = frozenset(FIELDS)
    assert search.counted == (
        (Words("Rat"), every),
        (Words("Liste"), frozenset({"filename"})),
        (Words("Rat Spende", distance=1), every),
    )
    assert search.search == "Rat"  # never part of the free words


def test_a_proximity_term_asks_websearch_for_its_two_words() -> None:
    assert Words("Spende bar", distance=2).websearch() == '"Spende" "bar"'
    assert Words("Spende bar", negated=True, distance=2).websearch() == '"Spende" "bar"'


@pytest.mark.parametrize(
    ("text", "distance", "found"),
    [
        ("Spende bar", 1, True),
        ("bar, die Spende", 1, True),  # either order
        ("Spende in bar", 1, True),
        ("Spende ganz in bar", 1, False),
        ("Spende ganz in bar", 2, True),
        ("Spende-bar", 1, True),
        ("SPENDE\n\nBAR", 1, True),
        ("Spenden bar", 3, False),  # whole words only
        ("Spende barfuß", 3, False),
        ("Spende " + "Rat " * 20 + "bar", 20, True),
        ("Spende " + "Rat " * 21 + "bar", 20, False),
        ("Spende Rat_2 bar", 1, False),  # _ separates, as it does for the words themselves
    ],
)
def test_python_proximity_pattern(text: str, distance: int, found: bool) -> None:
    pattern = word_regex_python(Words("Spende bar", distance=distance))
    assert bool(pattern.search(text)) is found


def test_the_proximity_pattern_of_postgresql() -> None:
    between = r"(?:[^[:alnum:]]+[[:alnum:]]+){0,2}[^[:alnum:]]+"
    assert word_regex(Words("Spende bar", distance=2)) == (
        rf"(?<![[:alnum:]])(?:Spende{between}bar|bar{between}Spende)(?![[:alnum:]])"
    )

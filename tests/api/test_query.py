"""The search syntax (D20): operators, quoting, raw substrings, Message-IDs and errors."""

from datetime import date

import pytest

from mailrobbe.api.query import QueryError, parse_day, parse_query


def _terms(q: str) -> list[tuple[str, str, str]]:
    return [(term.key, term.value, term.raw) for term in parse_query(q)]


def test_every_operator() -> None:
    q = (
        "from:anna to:@stadtwerke.example cc:Bert domain:elbtal.example subject:Vertrag "
        "has:attachment dkim:no_key after:2024-01-31 before:01.02.2025"
    )
    assert _terms(q) == [
        ("from", "anna", "from:anna"),
        ("to", "@stadtwerke.example", "to:@stadtwerke.example"),
        ("cc", "Bert", "cc:Bert"),
        ("domain", "elbtal.example", "domain:elbtal.example"),
        ("subject", "Vertrag", "subject:Vertrag"),
        ("has", "attachment", "has:attachment"),
        ("dkim", "no_key", "dkim:no_key"),
        ("after", "2024-01-31", "after:2024-01-31"),
        ("before", "01.02.2025", "before:01.02.2025"),
    ]


def test_operator_names_and_enumerated_values_ignore_case() -> None:
    assert _terms("FROM:Anna Has:Attachment DKIM:Pass") == [
        ("from", "Anna", "FROM:Anna"),
        ("has", "attachment", "Has:Attachment"),
        ("dkim", "pass", "DKIM:Pass"),
    ]


def test_full_text_words_and_phrases() -> None:
    assert _terms('  Angebot   "exakte Phrase" Rückfrage ') == [
        ("text", "Angebot", "Angebot"),
        ("text", "exakte Phrase", '"exakte Phrase"'),
        ("text", "Rückfrage", "Rückfrage"),
    ]


def test_quoted_operator_values() -> None:
    assert _terms('subject:"finale Fassung" from:"Keller, Anna" x') == [
        ("subject", "finale Fassung", 'subject:"finale Fassung"'),
        ("from", "Keller, Anna", 'from:"Keller, Anna"'),
        ("text", "x", "x"),
    ]


def test_an_unclosed_quote_runs_to_the_end() -> None:
    assert _terms('subject:"finale Fassung ohne Ende') == [
        ("subject", "finale Fassung ohne Ende", 'subject:"finale Fassung ohne Ende'),
    ]


def test_unknown_prefixes_and_empty_operators_are_full_text() -> None:
    assert _terms('Re: AW:Termin https://example.test/a from: subject:"" "from:x"') == [
        ("text", "Re:", "Re:"),
        ("text", "AW:Termin", "AW:Termin"),
        ("text", "https://example.test/a", "https://example.test/a"),
        ("text", "from:", "from:"),
        ("text", "subject:", 'subject:""'),
        ("text", "from:x", '"from:x"'),
    ]


def test_a_bare_message_id() -> None:
    assert _terms("<20220415.abc$1@info.example> <kein-at> Text") == [
        ("message_id", "<20220415.abc$1@info.example>", "<20220415.abc$1@info.example>"),
        ("text", "<kein-at>", "<kein-at>"),
        ("text", "Text", "Text"),
    ]


def test_raw_is_the_exact_substring() -> None:
    q = 'Vertrag  subject:"finale  Fassung"\tfrom:anna  <a@b.example>'
    terms = parse_query(q)
    assert [term.raw for term in terms] == [
        "Vertrag",
        'subject:"finale  Fassung"',
        "from:anna",
        "<a@b.example>",
    ]
    position = 0
    for term in terms:  # in order, each found in q after the previous one
        position = q.index(term.raw, position) + len(term.raw)
    removed = q.replace(terms[1].raw, "")
    assert [term.raw for term in parse_query(removed)] == [
        term.raw for index, term in enumerate(terms) if index != 1
    ]


def test_empty_query() -> None:
    assert parse_query("") == []
    assert parse_query(" \t ") == []


@pytest.mark.parametrize(
    "q, term",
    [
        ("Vertrag has:anhang", "has:anhang"),
        ("dkim:ok", "dkim:ok"),
        ("dkim:checked", "dkim:checked"),
        ("after:2024-13-01", "after:2024-13-01"),
        ("before:31.02.2024", "before:31.02.2024"),
        ("after:gestern", "after:gestern"),
        ('before:"2024 01 01"', 'before:"2024 01 01"'),
    ],
)
def test_unusable_operator_values_name_the_term(q: str, term: str) -> None:
    with pytest.raises(QueryError) as error:
        parse_query(q)
    assert error.value.term == term
    assert str(error.value).endswith(term)


def test_parse_day() -> None:
    assert parse_day("2024-02-29") == date(2024, 2, 29)
    assert parse_day("2024-2-9") == date(2024, 2, 9)
    assert parse_day("29.02.2024") == date(2024, 2, 29)
    assert parse_day("1.3.2024") == date(2024, 3, 1)
    assert parse_day("2023-02-29") is None
    assert parse_day("02/03/2024") is None
    assert parse_day("2024-01-01T00:00") is None


def test_placed_words_have_german_operator_names() -> None:
    assert _terms('betreff:Neger TEXT:"großer Austausch" anhang:Quittung datei:NEG') == [
        ("in_subject", "Neger", "betreff:Neger"),
        ("in_body", "großer Austausch", 'TEXT:"großer Austausch"'),
        ("in_attachment", "Quittung", "anhang:Quittung"),
        ("in_filename", "NEG", "datei:NEG"),
    ]


def test_internal_keys_are_no_operator_names() -> None:
    assert _terms("in_subject:x") == [("text", "in_subject:x", "in_subject:x")]


def test_a_minus_negates_operators_and_message_ids() -> None:
    terms = parse_query("-datei:NEG -from:anna -<a@b.example> Neger -negere")
    assert [(t.key, t.value, t.raw, t.negated) for t in terms] == [
        ("in_filename", "NEG", "-datei:NEG", True),
        ("from", "anna", "-from:anna", True),
        ("message_id", "<a@b.example>", "-<a@b.example>", True),
        ("text", "Neger", "Neger", False),
        ("text", "-negere", "-negere", False),  # websearch_to_tsquery reads the minus
    ]


def test_a_negated_operator_without_value_is_a_word() -> None:
    assert _terms("-from: -") == [("text", "-from:", "-from:"), ("text", "-", "-")]


def test_a_negated_operator_checks_its_value() -> None:
    with pytest.raises(QueryError) as caught:
        parse_query("-dkim:maybe")
    assert caught.value.term == "-dkim:maybe"

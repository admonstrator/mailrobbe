# ruff: noqa: RUF001  (typographic quotes and dashes are what these tests are about)
"""Checking instead of believing (D304): the answer read by the schema, tags and theme hints
checked against the text."""

import json
from collections.abc import Sequence

import pytest

from mailrobbe.ai.model import (
    QUOTE_MAX_CHARS,
    SUMMARY_MAX_HINTS,
    SUMMARY_MAX_TAGS,
    TAG_MAX_CHARS,
    THEME_HINTS_PER_THEME,
    ThemeHint,
)
from mailrobbe.ai.services import AnswerError
from mailrobbe.ai.summarize.answer import (
    Answer,
    answer_schema,
    check_answer,
    check_tags,
    check_themes,
    limit_hints,
    read_answer,
)
from mailrobbe.themes import load_themes

THEMES = load_themes()
FIRST, SECOND = THEMES[0], THEMES[1]


def answer(
    summary: str = "Kurz.", tags: Sequence[object] = (), themes: Sequence[object] = ()
) -> str:
    return json.dumps({"summary": summary, "tags": list(tags), "themes": list(themes)})


def test_the_schema_is_strict_and_names_the_theme_keys() -> None:
    schema = answer_schema(["spenden", "vereine"])
    assert schema["required"] == ["summary", "tags", "themes"]
    assert schema["additionalProperties"] is False
    item = schema["properties"]["themes"]["items"]
    assert item["properties"]["theme"]["enum"] == ["spenden", "vereine"]
    assert item["required"] == ["theme", "quote"] and item["additionalProperties"] is False
    assert schema["properties"]["tags"]["maxItems"] == SUMMARY_MAX_TAGS
    assert schema["properties"]["themes"]["maxItems"] == SUMMARY_MAX_HINTS
    assert "enum" not in answer_schema([])["properties"]["themes"]["items"]["properties"]["theme"]


@pytest.mark.parametrize(
    "wrapped",
    [
        "{body}",
        "```json\n{body}\n```",
        "<think>Erst überlegen: {{nicht das}}</think>\n{body}",
        "<THINK>lange Gedanken</THINK>Hier ist die Antwort: {body} Ende.",
        "Vorweg {{kaputt: ]}} und dann {body}",
    ],
)
def test_the_first_complete_object_counts_without_thinking_and_fences(wrapped: str) -> None:
    body = answer(" Eine Zusammenfassung. ", ["Spenden"], [{"theme": "a", "quote": "b"}])
    read = read_answer(wrapped.replace("{body}", body).replace("{{", "{").replace("}}", "}"))
    assert read == Answer("Eine Zusammenfassung.", ["Spenden"], [("a", "b")], 0, 0)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "no JSON object in the answer: an empty answer"),
        ("<think>noch nicht fertig", "no JSON object"),
        ("[1, 2]", "no JSON object"),
        ('{"tags": [], "themes": []}', "no text under summary"),
        ('{"summary": 3, "tags": [], "themes": []}', "no text under summary"),
        ('{"summary": "", "tags": "Spenden", "themes": []}', "no list under tags or themes"),
        ('{"summary": "", "tags": []}', "no list under tags or themes"),
    ],
)
def test_an_answer_without_the_schemas_keys_is_an_answer_error(text: str, message: str) -> None:
    with pytest.raises(AnswerError, match=message):
        read_answer(text)


def test_malformed_tags_and_themes_are_counted() -> None:
    read = read_answer(
        answer(
            tags=["Spenden", 3, None],
            themes=[{"theme": "a", "quote": "b"}, {"theme": "a"}, "c", {"theme": 1, "quote": "d"}],
        )
    )
    assert (read.tags, read.malformed_tags) == (["Spenden"], 2)
    assert (read.themes, read.malformed_themes) == ([("a", "b")], 3)


def test_tags_are_tidied_kept_once_by_key_and_limited() -> None:
    labels = [
        "  Spenden-Quittung ",
        "spenden quittung",
        "Größe",
        "groesse",
        "",
        "  ",
        "x" * (TAG_MAX_CHARS + 1),
        "Verein\n Vorstand",
    ]
    kept, dropped = check_tags(labels)
    assert kept == ["Spenden-Quittung", "Größe", "Verein Vorstand"]
    assert dropped == 1
    many = [f"Schlagwort {n}" for n in range(SUMMARY_MAX_TAGS + 3)]
    kept, dropped = check_tags(many)
    assert (kept, dropped) == (many[:SUMMARY_MAX_TAGS], 3)


TEXT = (
    "Der Vorstand bestätigt den Eingang der Spende über 500 Euro.\n"
    "Die „Spendenquittung“ folgt – wie immer –  im März.\n"
    "Er sagte: ‚Das ist  erledigt‘."
)
HEAD = "Art: E-Mail\nBetreff: Quittung für den Förderverein"


def hints(*found: tuple[str, str]) -> tuple[list[ThemeHint], int]:
    return check_themes(found, text=TEXT, head=HEAD, themes=THEMES)


def test_a_quote_is_found_in_the_text_as_it_stands_there() -> None:
    (hint,), dropped = hints((FIRST.key, "Eingang der Spende über 500 Euro"))
    assert dropped == 0
    assert hint.theme == FIRST.key
    assert hint.position == TEXT.index("Eingang")
    assert hint.quote == "Eingang der Spende über 500 Euro"


def test_quotes_compare_marks_dashes_spaces_and_case_as_one() -> None:
    found, dropped = hints(
        (FIRST.key, 'die "spendenquittung" folgt - wie immer - im märz'),
        (FIRST.key, "»Das ist erledigt«"),
    )
    assert dropped == 0
    first, second = found
    start = TEXT.index("Die „Spendenquittung")
    assert first.position == start
    assert first.quote == "Die „Spendenquittung“ folgt – wie immer –  im März"
    assert second.quote == "Das ist  erledigt"
    assert second.position == TEXT.index("Das ist")


def test_a_quote_with_marks_and_ellipses_around_it_is_found_without_them() -> None:
    (hint,), _ = hints((FIRST.key, "„…den Eingang der Spende…“"))
    assert hint.quote == "den Eingang der Spende"


def test_a_quote_only_in_the_head_has_no_position() -> None:
    (hint,), _ = hints((FIRST.key, "Quittung für den Förderverein"))
    assert (hint.quote, hint.position) == ("Quittung für den Förderverein", None)


def test_a_theme_is_known_by_its_key_or_its_name() -> None:
    found, dropped = hints((FIRST.name.upper(), "Vorstand"), ("unbekannt", "Vorstand"))
    assert [hint.theme for hint in found] == [FIRST.key]
    assert dropped == 1


def test_quotes_not_in_the_text_too_long_or_too_short_are_dropped() -> None:
    found, dropped = hints(
        (FIRST.key, "Eingang der Spende über 900 Euro"),
        (FIRST.key, "Vorstand " * (QUOTE_MAX_CHARS // 9 + 1)),
        (FIRST.key, "D"),
        (FIRST.key, "„“"),
    )
    assert (found, dropped) == ([], 4)


def test_the_same_place_once_and_at_most_three_per_theme() -> None:
    quote = (FIRST.key, "Vorstand")
    many = [(FIRST.key, word) for word in ("Eingang", "Spende", "Euro", "März", "erledigt")]
    found, dropped = hints(quote, quote, (SECOND.key, "Vorstand"), *many)
    kept, beyond = limit_hints(found)
    assert dropped == 0
    assert THEME_HINTS_PER_THEME == 3
    assert [(hint.theme, hint.quote) for hint in kept] == [
        (FIRST.key, "Vorstand"),
        (SECOND.key, "Vorstand"),
        (FIRST.key, "Eingang"),
        (FIRST.key, "Spende"),
    ]
    assert beyond == 3  # Euro, März, erledigt; the second "Vorstand" is the same place
    assert len([hint for hint in kept if hint.theme == FIRST.key]) == THEME_HINTS_PER_THEME


def test_check_answer_counts_every_drop() -> None:
    read = read_answer(
        answer(
            "Zusammenfassung.",
            ["Spenden", "x" * (TAG_MAX_CHARS + 1), 7],
            [{"theme": FIRST.key, "quote": "Vorstand"}, {"theme": FIRST.key, "quote": "fehlt"}, 1],
        )
    )
    checked = check_answer(read, text=TEXT, head=HEAD, themes=THEMES)
    assert (checked.summary, checked.tags) == ("Zusammenfassung.", ["Spenden"])
    assert [hint.quote for hint in checked.themes] == ["Vorstand"]
    assert (checked.dropped_tags, checked.dropped_themes) == (2, 2)

import pytest

from mailrobbe.ai.model import NO_TEXT_MARK
from mailrobbe.ai.ocr.guards import LOOP_LINES, clean_answer, cut_loop, is_no_text
from mailrobbe.ai.prompts import load_prompts


def test_the_prompt_file_has_a_version_and_names_the_answer_without_writing() -> None:
    prompts = load_prompts()
    assert prompts.version >= 1
    assert NO_TEXT_MARK in prompts.ocr
    assert "[unleserlich]" in prompts.ocr
    assert prompts.ocr == prompts.ocr.strip()


@pytest.mark.parametrize(
    "answer", ["", "  \n", NO_TEXT_MARK, "[kein text].", " [KEIN  TEXT] \n", "[kein Text]..."]
)
def test_no_writing_in_its_spellings(answer: str) -> None:
    assert is_no_text(answer)
    assert clean_answer(answer).text == ""


def test_a_text_that_mentions_the_mark_is_kept() -> None:
    assert clean_answer(f"Seite 2\n{NO_TEXT_MARK}").text == f"Seite 2\n{NO_TEXT_MARK}"


@pytest.mark.parametrize(
    ("answer", "text"),
    [
        ("<think>\nLet me read.\n</think>\n\nBetreff: Spende", "Betreff: Spende"),
        ("<THINK>a</THINK>Text<think>b</think>", "Text"),
        ("<think>unfinished thinking cut by its limit", ""),
        ("```\nZeile 1\nZeile 2\n```", "Zeile 1\nZeile 2"),
        ("```markdown\n| Datum | Betrag |\n|---|---|\n```", "| Datum | Betrag |\n|---|---|"),
        ("Text mit ```code``` darin", "Text mit ```code``` darin"),
        ("<think>x</think>```text\n[kein Text]\n```", ""),
    ],
)
def test_thinking_and_a_surrounding_fence_are_removed(answer: str, text: str) -> None:
    assert clean_answer(answer).text == text


def test_a_line_repeated_five_times_is_cut_after_its_first() -> None:
    answer = "Kopf\n" + "Spende 50 €\n" * LOOP_LINES + "Rest"
    assert cut_loop(answer) == ("Kopf\nSpende 50 €", True)
    cleaned = clean_answer(answer)
    assert (cleaned.text, cleaned.looped) == ("Kopf\nSpende 50 €", True)


def test_four_repeats_and_empty_lines_are_no_loop() -> None:
    four = "Kopf\n" + "Spende\n" * (LOOP_LINES - 1) + "Ende"
    assert cut_loop(four) == (four, False)
    blank = "a" + "\n" * 9 + "b"
    assert cut_loop(blank) == (blank, False)
    table = "| x |\n|---|\n" + "|  |\n" * 3
    assert cut_loop(table) == (table, False)


def test_a_loop_at_the_end_and_with_trailing_spaces() -> None:
    assert cut_loop("Ja \nJa\nJa  \nJa\nJa") == ("Ja", True)

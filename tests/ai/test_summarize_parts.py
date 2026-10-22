"""Long texts in parts (D303): the size of a part and where a text is cut."""

import math

from mailrobbe.ai.model import CHARS_PER_TOKEN, SUMMARY_ANSWER_TOKENS
from mailrobbe.ai.summarize.parts import MARGIN_TOKENS, cut, part_chars


def test_a_part_holds_the_context_less_prompt_answer_and_margin() -> None:
    fixed = 3500  # 1,000 tokens
    expected = (8192 - SUMMARY_ANSWER_TOKENS - MARGIN_TOKENS - 1000) * CHARS_PER_TOKEN
    assert part_chars(8192, fixed) == math.floor(expected)
    assert part_chars(8192, fixed + 1) < part_chars(8192, fixed)
    assert part_chars(16384, fixed) > part_chars(8192, fixed)
    assert part_chars(2048, 20_000) == 0


def test_a_text_that_fits_is_one_part_and_one_without_words_none() -> None:
    (part,) = cut("  Ein kurzer Text.\n", 100)
    assert (part.number, part.start, part.text) == (1, 2, "Ein kurzer Text.")
    assert cut(" \n\t ", 100) == []
    assert cut("", 100) == []


def test_a_text_is_cut_at_the_last_paragraph_end_in_the_second_half() -> None:
    first = "Erster Absatz mit einigen Wörtern."
    second = "Zweiter Absatz, etwas länger als der erste."
    third = "Dritter Absatz."
    text = f"{first}\n\n{second}\n \n{third}"
    parts = cut(text, len(first) + len(second) + 10)
    assert [part.text for part in parts] == [f"{first}\n\n{second}", third]
    for part in parts:
        assert text[part.start : part.start + len(part.text)] == part.text


def test_without_a_paragraph_end_a_part_ends_at_a_line_a_space_or_where_it_is_full() -> None:
    lines = "Zeile eins hier\nZeile zwei hier\nZeile drei hier"
    assert [part.text for part in cut(lines, 34)] == [
        "Zeile eins hier\nZeile zwei hier",
        "Zeile drei hier",
    ]
    words = "eins zwei drei vier fünf sechs"
    assert [part.text for part in cut(words, 12)] == ["eins zwei", "drei vier", "fünf sechs"]
    assert [part.text for part in cut("abcdefghij", 4)] == ["abcd", "efgh", "ij"]


def test_a_paragraph_end_in_the_first_half_is_not_taken() -> None:
    text = "ab\n\n" + "x " * 40
    parts = cut(text, 40)
    assert parts[0].text.startswith("ab\n\nx x")
    assert all(len(part.text) <= 40 for part in parts)


def test_the_parts_cover_every_word_in_order_with_their_offsets() -> None:
    paragraphs = [
        f"Absatz {n}: " + " ".join(f"wort{n}x{i}" for i in range(n % 7 + 3)) for n in range(60)
    ]
    text = "\n\n".join(paragraphs)
    parts = cut(text, 300)
    assert len(parts) > 5
    assert [part.number for part in parts] == list(range(1, len(parts) + 1))
    assert all(0 < len(part.text) <= 300 for part in parts)
    assert " ".join(part.text for part in parts).split() == text.split()
    for part in parts:
        assert text[part.start : part.start + len(part.text)] == part.text

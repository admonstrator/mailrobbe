"""passwords.candidates (D234): the word after a keyword, in German and English, with the line(s)
it stands in; no word lists, no guessing (D207)."""

import pytest

from mailrobbe.passwords.candidates import PASSWORD_MAX_LENGTH, Candidate, candidates


def values(text: str) -> list[str]:
    return [candidate.value for candidate in candidates(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Kennwort: Hafen-2019", "Hafen-2019"),
        ("Das Kennwort ist Hafen-2019", "Hafen-2019"),
        ("Das Passwort lautet Nordlicht7", "Nordlicht7"),
        ("Das Passwort lautet: Nordlicht7", "Nordlicht7"),
        ("Passwort = Nordlicht7", "Nordlicht7"),
        ("pwd=geheim", "geheim"),
        ("PW: abc123", "abc123"),
        ("Ihr Pw ist abc123", "abc123"),
        ("PIN 4711", "4711"),
        ("Die PIN lautet 4711", "4711"),
        ("Zugangscode: X-99", "X-99"),
        ("Der Code ist 5555", "5555"),
        ("Passphrase = lange-phrase", "lange-phrase"),
        ("Pass: Seefahrt", "Seefahrt"),
        ("password: s3cret!", "s3cret!"),
        ("the new password: s3cret!", "s3cret!"),
        ("Your PASSWORD: s3cret!", "s3cret!"),
        ("Passcode: 2468", "2468"),
        ("KENNWORT: Hafen-2019", "Hafen-2019"),
        ("Kennworts: Hafen-2019", "Hafen-2019"),
        ("The password is s3cret!", "s3cret!"),
        # a few words between the keyword and its separator
        ("Das Passwort für das ZIP lautet: Hafen-2019", "Hafen-2019"),
        ("Das Kennwort für die Tabelle ist Rosen-17", "Rosen-17"),
        ("The password for the zip file is: abc123", "abc123"),
        # "ist" and "is" only as whole words
        ("Kennwort istanbul99", "istanbul99"),
    ],
)
def test_the_word_after_a_keyword(text: str, expected: str) -> None:
    assert values(text) == [expected]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('Passwort: "Doppelt-2"', "Doppelt-2"),
        ("Passwort: 'Einfach-3'", "Einfach-3"),
        ("Kennwort: „Gänsefüßchen4“", "Gänsefüßchen4"),
        ("Kennwort: »Winkel5«", "Winkel5"),
        ("Kennwort: ‚Halb6‘", "Halb6"),  # noqa: RUF001
        ("Kennwort: `Gravis7`", "Gravis7"),
        ("Das Passwort ist (Klammer8)", "Klammer8"),
        ("Kennwort: [Eckig9]", "Eckig9"),
    ],
)
def test_quotes_around_the_value_are_left_out(text: str, expected: str) -> None:
    assert values(text) == [expected]


def test_the_value_on_the_next_line_with_both_lines_as_evidence() -> None:
    text = "Hallo Bert,\ndas Kennwort lautet:\n  Sommer2024\nGruß Anna"
    assert list(candidates(text)) == [Candidate("Sommer2024", "das Kennwort lautet:\n  Sommer2024")]
    assert values("Kennwort:\r\n'Quoted-1'") == ["Quoted-1"]  # any line end
    assert values("Das Passwort ist\nSommer2024") == ["Sommer2024"]


def test_sentence_punctuation_is_tried_with_and_without() -> None:
    found = list(candidates("Hallo,\nIhr PW lautet: Neu-1. Danke!"))
    context = "Ihr PW lautet: Neu-1. Danke!"
    assert found == [Candidate("Neu-1.", context), Candidate("Neu-1", context)]
    assert values("Password: abc, PIN: 1234; Code: 9") == ["abc,", "abc", "1234;", "1234", "9"]


def test_each_value_once_with_the_line_of_its_first_place() -> None:
    text = "Kennwort: abc\nzur Erinnerung, Kennwort: abc\nPIN: 42"
    assert list(candidates(text)) == [Candidate("abc", "Kennwort: abc"), Candidate("42", "PIN: 42")]


def test_a_long_line_is_cut_as_evidence() -> None:
    text = "x " * 200 + "Kennwort: Hafen-2019 " + "y " * 200
    [found] = candidates(text)
    assert found.value == "Hafen-2019"
    assert len(found.context) == 300 and found.context.endswith("...")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Kein Hinweis in diesem Text.",
        "Kennwort:",
        "Kennwort:   \n\n",
        "Bitte das Passwort, das du kennst.",
        "Wie lautet das Kennwort?",
        "Das Kennwort.",
        # a keyword inside a word is none
        "Wir passen das an.",
        "Die Passwortänderung ist erledigt.",
        "Der Barcode liegt bei.",
        "Die Pinnwand im Flur.",
        "Ein Kompass: Nord",
        # the value after an empty line is too far
        "Kennwort:\n\nHafen-2019",
        # longer than a password people type: not even its beginning
        "Kennwort: " + "x" * (PASSWORD_MAX_LENGTH + 1),
    ],
)
def test_no_candidate(text: str) -> None:
    assert values(text) == []


def test_the_longest_value() -> None:
    longest = "y" * PASSWORD_MAX_LENGTH
    assert values(f"Kennwort: {longest}") == [longest]


def test_a_candidate_does_not_swallow_the_next_keyword() -> None:
    text = "Das Kennwort für Bericht.zip von neulich:\nKennwort: qcmg5uu3dk"
    assert values(text)[-1] == "qcmg5uu3dk"
    assert values("Zugangsdaten für Vertrag.zip:\nZugangscode: Verein2025!")[-1] == "Verein2025!"


def test_prose_after_a_keyword_is_a_candidate_too() -> None:
    """No guessing (D207): a wrong candidate costs one try, the file decides."""
    assert values("Das Kennwort schicke ich dir morgen.") == ["schicke"]

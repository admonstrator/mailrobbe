"""The keys alias suggestions compare (D30): normalize_name and normalize_local_part."""

import pytest

from mailrobbe.persons.suggestions import ROLE_LOCAL_PARTS, normalize_local_part, normalize_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Anna Schmidt", "anna schmidt"),
        ("ANNA SCHMIDT", "anna schmidt"),
        ("Schmidt, Anna", "anna schmidt"),  # Nachname, Vorname turned around
        ("Schmidt,Anna", "anna schmidt"),
        ("Müller-Lüdenscheidt, Hans-Jürgen", "hans-jürgen müller-lüdenscheidt"),
        ("  Anna \t  Schmidt  ", "anna schmidt"),  # surplus whitespace
        ("Anna\u00a0Schmidt", "anna schmidt"),  # a no-break space is whitespace too
        ('"Anna Schmidt"', "anna schmidt"),
        ("'Anna Schmidt'", "anna schmidt"),
        ("„Anna Schmidt“", "anna schmidt"),
        ("«Anna Schmidt»", "anna schmidt"),
        ("Dr. Anna Schmidt", "dr. anna schmidt"),
        ("Schmidt, Dr. Anna", "dr. anna schmidt"),
        ("Anna Schmidt (Bergmann Bau)", "anna schmidt (bergmann bau)"),
        ("Schmidt, Anna, Vertrieb", "schmidt, anna, vertrieb"),  # two commas: left as is
        ("Anna", None),  # one word
        ("anna.schmidt", None),  # the local part as a name: one word
        ("Schmidt,", None),  # turned around, one word is left
        (",", None),
        ("", None),
        ("   ", None),
        ("anna@a.example", None),
        ("Anna Schmidt <anna@a.example>", None),
        ("Anna Schmidt via anna@a.example", None),
    ],
)
def test_normalize_name(name: str, expected: str | None) -> None:
    assert normalize_name(name) == expected


@pytest.mark.parametrize(
    ("local_part", "expected"),
    [
        ("anna.schmidt", "anna.schmidt"),
        ("Anna.Schmidt", "anna.schmidt"),
        ("anna.schmidt+newsletter", "anna.schmidt"),  # +suffix removed
        ("anna+a+b", "anna"),
        ("a.schmidt", "a.schmidt"),
        ("info", None),  # role addresses
        ("INFO", None),
        ("info+shop", None),
        ("noreply", None),
        ("no-reply", None),
        ("Buchhaltung", None),
        ("+newsletter", None),  # nothing left
        ("", None),
    ],
)
def test_normalize_local_part(local_part: str, expected: str | None) -> None:
    assert normalize_local_part(local_part) == expected


def test_role_local_parts_are_normalized() -> None:
    assert all(part == part.lower() and "+" not in part for part in ROLE_LOCAL_PARTS)

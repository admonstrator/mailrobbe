from datetime import date

import pytest

from mailrobbe.topics.model import (
    UNITS,
    Unit,
    cluster_label,
    cluster_query,
    period_end,
    period_start,
    usable_lexeme,
)


@pytest.mark.parametrize(
    ("lexeme", "usable"),
    [
        ("spend", True),
        ("verfassungsfeind", True),
        ("großspend", True),
        ("joão", True),
        ("ab", False),  # too short
        ("x" * 41, False),
        ("2019", False),
        ("covid19", False),
        ("e-mail", False),  # hyphenated: its parts are lexemes of their own
        ("info@verein.example", False),
        ("verein.example", False),
        ("https://example.org", False),
    ],
)
def test_usable_lexemes(lexeme: str, usable: bool) -> None:
    assert usable_lexeme(lexeme) is usable


@pytest.mark.parametrize(
    ("day", "unit", "start", "end"),
    [
        (date(2024, 2, 17), "month", date(2024, 2, 1), date(2024, 2, 29)),
        (date(2023, 12, 31), "month", date(2023, 12, 1), date(2023, 12, 31)),
        (date(2024, 5, 3), "quarter", date(2024, 4, 1), date(2024, 6, 30)),
        (date(2024, 11, 30), "quarter", date(2024, 10, 1), date(2024, 12, 31)),
        (date(2024, 7, 9), "year", date(2024, 1, 1), date(2024, 12, 31)),
    ],
)
def test_periods(day: date, unit: Unit, start: date, end: date) -> None:
    assert unit in UNITS
    assert period_start(day, unit) == start
    assert period_end(start, unit) == end


def test_cluster_label_and_query() -> None:
    labels = ["Spende", "Quittung", "Bargeld", "Konto", "Kasse", "Beleg"]
    assert cluster_label(labels) == "Spende, Quittung, Bargeld"
    assert cluster_query(labels) == "Spende or Quittung or Bargeld or Konto or Kasse"

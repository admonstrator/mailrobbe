"""The periods and their ranking (D142, D143), without the database."""

from datetime import date

import pytest

from mailrobbe.topics import periods
from mailrobbe.topics.keyness import keyness
from mailrobbe.topics.model import Term, Unit
from mailrobbe.topics.periods import Period, PeriodTerm, period_mails, rank_terms


def test_the_mails_of_every_period_come_from_the_months() -> None:
    months = {date(2023, 11, 1): 4, date(2023, 12, 1): 6, date(2024, 1, 1): 5, date(2024, 5, 1): 1}
    assert period_mails(months) == {
        ("month", date(2023, 11, 1)): 4,
        ("month", date(2023, 12, 1)): 6,
        ("month", date(2024, 1, 1)): 5,
        ("month", date(2024, 5, 1)): 1,
        ("quarter", date(2023, 10, 1)): 10,
        ("quarter", date(2024, 1, 1)): 5,
        ("quarter", date(2024, 4, 1)): 1,
        ("year", date(2023, 1, 1)): 10,
        ("year", date(2024, 1, 1)): 6,
    }
    assert period_mails({}) == {}


MONTH: Period = ("month", date(2024, 3, 1))
QUARTER: Period = ("quarter", date(2024, 1, 1))
TOTAL = 1_000
PERIODS: dict[Period, int] = {MONTH: 40, QUARTER: 100}
TERMS = {
    lexeme: Term(lexeme, label, mails)
    for lexeme, label, mails in [
        ("sommerf", "Sommerfest", 10),
        ("umzug", "Umzug", 10),  # the same figures as Sommerfest: after it by label
        ("abend", "Abend", 10),  # as well, but its label sorts first
        ("verein", "Verein", 500),  # everywhere: does not stand out
        ("signatur", "Signatur", 40),  # in every mail of the month: common
        ("selten", "selten", 20),
    ]
}


def rows(*found: tuple[Period, str, int]) -> list[tuple[Unit, date, str, int]]:
    return [(unit, start, lexeme, a) for (unit, start), lexeme, a in found]


def test_terms_are_ranked_by_score_then_label() -> None:
    found = rows(
        (MONTH, "umzug", 8),
        (MONTH, "sommerf", 8),
        (MONTH, "abend", 8),
        (MONTH, "selten", 9),
        (MONTH, "verein", 20),
        (MONTH, "signatur", 40),
        (QUARTER, "selten", 12),
    )
    ranked = rank_terms(found, PERIODS, TERMS, TOTAL)
    tied = keyness(8, 40, 10, TOTAL)
    rare = keyness(9, 40, 20, TOTAL)
    assert tied is not None and rare is not None and tied.score > rare.score
    assert ranked[MONTH] == [
        PeriodTerm("abend", 8, tied.score),
        PeriodTerm("sommerf", 8, tied.score),
        PeriodTerm("umzug", 8, tied.score),
        PeriodTerm("selten", 9, rare.score),
    ]
    common = keyness(40, 40, 40, TOTAL)
    assert common is not None and common.common  # stands out, but listed apart, not here
    assert keyness(20, 40, 500, TOTAL) is None
    quarter = keyness(12, 100, 20, TOTAL)
    assert quarter is not None and ranked[QUARTER] == [PeriodTerm("selten", 12, quarter.score)]


def test_a_period_keeps_its_first_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(periods, "PERIOD_TERMS", 2)
    found = rows((MONTH, "umzug", 8), (MONTH, "sommerf", 8), (MONTH, "abend", 8))
    ranked = rank_terms(found, PERIODS, TERMS, TOTAL)
    assert [term.lexeme for term in ranked[MONTH]] == ["abend", "sommerf"]


def test_a_period_without_terms_standing_out_has_no_list() -> None:
    assert rank_terms(rows((MONTH, "verein", 20)), PERIODS, TERMS, TOTAL) == {}

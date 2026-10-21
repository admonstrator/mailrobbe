import math

import pytest

from mailrobbe.topics.keyness import MIN_SCORE, keyness


def test_a_term_twice_as_frequent_with_enough_mails_stands_out() -> None:
    # 30 of 100 mails here, 270 of the other 9,900 (2.7 %): eleven times as frequent.
    found = keyness(30, 100, 300, 10_000)
    assert found is not None
    assert found.mails == 30
    assert found.share == pytest.approx(0.3)
    assert found.rest_share == pytest.approx(270 / 9_900)
    assert found.ratio == pytest.approx(0.3 / (270 / 9_900))
    expected = 2 * (30 * math.log(30 / 3) + 270 * math.log(270 / 297))
    assert found.score == pytest.approx(expected)
    assert not found.common


@pytest.mark.parametrize(
    ("a", "n", "df", "total"),
    [
        (2, 10, 2, 10_000),  # fewer than three mails
        (10, 100, 600, 10_000),  # 10 % here, 6 % elsewhere: less than twice as frequent
        (50, 10_000, 60, 10_000),  # the scope is the whole archive
        (3, 9_000, 3, 10_000),  # nearly the whole archive: G2 below the threshold
        (3, 0, 3, 10_000),  # an empty scope
    ],
)
def test_terms_that_do_not_stand_out(a: int, n: int, df: int, total: int) -> None:
    assert keyness(a, n, df, total) is None


def test_a_term_found_only_here_has_no_ratio() -> None:
    found = keyness(5, 50, 5, 10_000)
    assert found is not None
    assert found.ratio is None
    assert found.rest_share == 0
    assert found.score >= MIN_SCORE


def test_a_vocabulary_counted_before_newer_mails_is_raised_to_the_scope() -> None:
    assert keyness(8, 40, 5, 10_000) == keyness(8, 40, 8, 10_000)


def test_terms_in_more_than_half_of_twenty_mails_are_common() -> None:
    common = keyness(15, 20, 40, 10_000)
    assert common is not None and common.common
    small = keyness(9, 10, 40, 10_000)  # more than half, but of fewer than 20 mails
    assert small is not None and not small.common


def test_estimates_from_a_sample_are_rounded() -> None:
    found = keyness(12.4, 300.0, 200, 50_000)
    assert found is not None
    assert found.mails == 12

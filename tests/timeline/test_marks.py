"""timeline.marks: outliers against the moving mean and silence (D93), each rule at its edges."""

import pytest

from mailrobbe.api.schemas import TimelineBucket, TimelineOutlier
from mailrobbe.timeline.marks import (
    HIGH_FACTOR,
    HIGH_MARGIN,
    HISTORY,
    LOW_FACTOR,
    LOW_MEAN,
    SILENT_ACTIVE_SHARE,
    SILENT_BUCKETS,
    SILENT_MAILS,
    SILENT_WINDOW,
    outliers,
    silent_from,
)


def marked(
    counts: list[int], bucket: TimelineBucket = "month", low: range | None = None
) -> list[tuple[int, str, float]]:
    """The marks as tuples; low may be marked everywhere unless `low` says otherwise."""
    allowed = range(len(counts)) if low is None else low
    return [(mark.index, mark.kind, mark.expected) for mark in outliers(counts, bucket, allowed)]


def test_thresholds_are_those_of_d93() -> None:
    days, weeks, months = HISTORY["day"], HISTORY["week"], HISTORY["month"]
    assert (days, weeks, months) == ((7, 14, 21, 28), tuple(range(1, 9)), (1, 2, 3, 4, 5, 6))
    assert (HIGH_FACTOR, HIGH_MARGIN, LOW_MEAN, LOW_FACTOR) == (3, 5, 5, 3)
    assert SILENT_BUCKETS == {"day": 21, "week": 6, "month": 3}
    assert SILENT_WINDOW == {"day": 28, "week": 8, "month": 6}
    assert (SILENT_ACTIVE_SHARE, SILENT_MAILS) == (0.5, 5)


def test_no_mark_without_the_full_history() -> None:
    assert marked([10] * 5 + [100]) == []  # six months are needed
    assert marked([10] * 6 + [100]) == [(6, "high", 10.0)]
    assert marked([10] * 7 + [100], "week") == []
    assert marked([10] * 8 + [100], "week") == [(8, "high", 10.0)]
    assert marked([0] * 27 + [100], "day") == []


def test_days_compare_the_same_weekday_of_four_weeks() -> None:
    counts = [0] * 29
    for index in (0, 7, 14, 21):
        counts[index] = 10
    counts[28] = 10  # the four weekdays before have 10 each; the days just before have none
    assert marked(counts, "day") == []
    counts[28] = 30
    assert marked(counts, "day") == [(28, "high", 10.0)]
    counts[28] = 3  # at most a third of 10
    assert marked(counts, "day") == [(28, "low", 10.0)]


def test_high_needs_three_times_the_mean_and_five_more() -> None:
    assert marked([10] * 6 + [30]) == [(6, "high", 10.0)]
    assert marked([10] * 6 + [29]) == []
    # A small mean: three times is not enough, the five more decide.
    assert marked([1] * 6 + [5]) == []
    assert marked([1] * 6 + [6]) == [(6, "high", 1.0)]
    assert marked([2] * 6 + [6]) == []
    assert marked([2] * 6 + [7]) == [(6, "high", 2.0)]


def test_a_mean_of_zero_is_high_from_five_mails() -> None:
    assert marked([0] * 8 + [4], "week") == []
    assert marked([0] * 8 + [5], "week") == [(8, "high", 0.0)]
    assert marked([0] * 9) == []


def test_low_only_from_a_mean_of_five() -> None:
    assert marked([5] * 6 + [1]) == [(6, "low", 5.0)]
    assert marked([4] * 6 + [0]) == []  # the mean is below five
    assert marked([6] * 6 + [2]) == [(6, "low", 6.0)]  # exactly a third
    assert marked([6] * 6 + [3]) == []


def test_the_mean_is_that_of_the_buckets_before() -> None:
    counts = [1, 2, 3, 4, 5, 16, 60]
    assert marked(counts) == [(6, "high", 31 / 6)]
    rising = marked([10] * 6 + [40, 40])  # the second 40 is compared with a mean of 15
    assert rising == [(6, "high", 10.0)]
    assert outliers([10] * 6 + [40], "month", range(7)) == [
        TimelineOutlier(index=6, kind="high", expected=10.0)
    ]


def test_low_only_in_wholly_covered_buckets_high_everywhere() -> None:
    def kinds(counts: list[int], low: range | None = None) -> list[tuple[int, str]]:
        return [(index, kind) for index, kind, _ in marked(counts, low=low)]

    counts = [6] * 6 + [1, 30, 1, 1]
    assert kinds(counts) == [(6, "low"), (7, "high"), (8, "low"), (9, "low")]
    # The end lies in bucket 8 before its last day, bucket 9 is after it: neither is low.
    assert kinds(counts, range(8)) == [(6, "low"), (7, "high")]
    # date_from cuts bucket 6 as well (bucket 0 on the real axis): only the high one is left.
    assert kinds(counts, range(7, 8)) == [(7, "high")]
    assert kinds(counts, range(0)) == [(7, "high")]


@pytest.mark.parametrize(
    ("counts", "end", "expected"),
    [
        ([3, 3, 3, 3, 3, 3, 0, 0, 0], 8, 6),  # reaches the end
        ([3, 3, 3, 3, 3, 3, 0, 0], 7, None),  # too short: two months
        ([3, 3, 3, 3, 3, 3, 0, 1, 0, 0], 9, None),  # broken by a mail: two months after it
        ([3, 3, 3, 3, 3, 3, 0, 0, 0, 4], 8, 6),  # a mail after the end does not break it
        ([3, 3, 3, 3, 3, 3, 0, 0, 0, 0, 0], 8, 6),  # date_to before the axis's end
        ([3, 3, 3, 3, 3, 3, 0, 0, 3], 8, None),  # a mail in the end bucket
        ([3, 3, 3, 3, 3, 3, 0, 0, 0], -1, None),  # the end is before the axis
        ([0, 0, 0, 0, 0, 0, 0, 0, 0], 8, None),  # never active
        ([0, 0, 0, 9, 0, 9, 0, 0, 0], 8, None),  # two of six months: not half
        ([0, 0, 0, 2, 1, 2, 0, 0, 0], 8, 6),  # three of six months, five mails
        ([0, 0, 0, 2, 1, 1, 0, 0, 0], 8, None),  # three of six months, four mails
        ([3, 3, 3, 0, 0, 0], 5, 3),  # months before the axis count as without mail
    ],
)
def test_silence_by_month(counts: list[int], end: int, expected: int | None) -> None:
    assert silent_from(counts, "month", end) == expected


def test_silence_by_week_and_day() -> None:
    weeks = [0, 0, 0, 0, 2, 2, 2, 2] + [0] * 6
    assert silent_from(weeks, "week", 13) == 8
    assert silent_from(weeks[:-1], "week", 12) is None  # five weeks
    assert silent_from([0, 0, 0, 0, 0, 2, 2, 2] + [0] * 6, "week", 13) is None  # three of eight
    assert silent_from([0, 0, 0, 0, 1, 1, 1, 1] + [0] * 6, "week", 13) is None  # four mails
    days = [1, 0] * 14 + [0] * 21
    assert silent_from(days, "day", 48) == 27  # the run starts at the last day without mail
    assert silent_from([1, 0] * 14 + [0] * 19, "day", 46) is None  # 20 days: 21 are needed

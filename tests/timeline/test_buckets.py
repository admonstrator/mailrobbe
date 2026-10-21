"""timeline.buckets: bucket starts, the axis, the automatic bucket and coarsening (D91)."""

from datetime import date, timedelta

import pytest

from mailrobbe.api.schemas import MAX_TIMELINE_BUCKETS, TimelineBucket
from mailrobbe.timeline.buckets import (
    DAY_SPAN,
    WEEK_SPAN,
    axis,
    bucket_count,
    bucket_start,
    choose,
    position,
    sum_days,
)

D = date


@pytest.mark.parametrize(
    ("day", "bucket", "start"),
    [
        (D(2021, 3, 4), "day", D(2021, 3, 4)),
        (D(2021, 3, 4), "week", D(2021, 3, 1)),  # a Thursday: its Monday
        (D(2021, 3, 1), "week", D(2021, 3, 1)),
        (D(2021, 3, 7), "week", D(2021, 3, 1)),  # Sunday ends the ISO week
        (D(2021, 1, 1), "week", D(2020, 12, 28)),  # ISO week 53 of 2020
        (D(2021, 1, 3), "week", D(2020, 12, 28)),
        (D(2021, 1, 4), "week", D(2021, 1, 4)),  # week 1 of 2021
        (D(2024, 2, 29), "month", D(2024, 2, 1)),
        (D(2021, 12, 31), "month", D(2021, 12, 1)),
    ],
)
def test_bucket_start(day: date, bucket: TimelineBucket, start: date) -> None:
    assert bucket_start(day, bucket) == start


def test_weeks_run_across_the_year_end_through_week_53() -> None:
    starts = axis(D(2020, 12, 20), D(2021, 1, 10), "week")
    assert starts == [D(2020, 12, 14), D(2020, 12, 21), D(2020, 12, 28), D(2021, 1, 4)]
    assert D(2020, 12, 28).isocalendar()[:2] == (2020, 53)
    days = {D(2020, 12, 31): 2, D(2021, 1, 3): 3, D(2021, 1, 4): 1, D(2020, 12, 20): 4}
    assert sum_days(days, starts, "week") == [4, 0, 5, 1]


def test_months_run_across_the_year_end_and_a_leap_february() -> None:
    starts = axis(D(2023, 12, 31), D(2024, 3, 1), "month")
    assert starts == [D(2023, 12, 1), D(2024, 1, 1), D(2024, 2, 1), D(2024, 3, 1)]
    days = {D(2024, 2, 29): 2, D(2024, 2, 1): 1, D(2024, 3, 1): 5, D(2023, 12, 31): 1}
    assert sum_days(days, starts, "month") == [1, 0, 3, 5]
    assert axis(D(2023, 2, 28), D(2023, 3, 1), "month") == [D(2023, 2, 1), D(2023, 3, 1)]


def test_days_have_no_gaps_and_days_off_the_axis_are_left_out() -> None:
    starts = axis(D(2024, 2, 27), D(2024, 3, 2), "day")
    assert starts == [D(2024, 2, 27) + timedelta(days=n) for n in range(5)]
    days = {D(2024, 2, 29): 7, D(2024, 3, 3): 9, D(2024, 2, 26): 9}
    assert sum_days(days, starts, "day") == [0, 0, 7, 0, 0]


def test_one_day_is_one_bucket_of_each_kind() -> None:
    for bucket in ("day", "week", "month"):
        assert axis(D(2022, 6, 15), D(2022, 6, 15), bucket) == [
            bucket_start(D(2022, 6, 15), bucket)
        ]


@pytest.mark.parametrize("bucket", ["day", "week", "month"])
def test_bucket_count_is_the_length_of_the_axis(bucket: TimelineBucket) -> None:
    first = D(2019, 12, 30)
    for days in (0, 1, 6, 7, 30, 31, 365, 1000):
        last = first + timedelta(days=days)
        assert bucket_count(first, last, bucket) == len(axis(first, last, bucket))


def test_the_axis_reaches_the_last_possible_day() -> None:
    assert axis(D(9999, 11, 15), D(9999, 12, 31), "month") == [D(9999, 11, 1), D(9999, 12, 1)]
    assert axis(D(9999, 12, 30), D(9999, 12, 31), "day")[-1] == D(9999, 12, 31)


@pytest.mark.parametrize(
    ("span", "bucket"),
    [
        (1, "day"),
        (DAY_SPAN, "day"),
        (DAY_SPAN + 1, "week"),
        (WEEK_SPAN, "week"),
        (WEEK_SPAN + 1, "month"),
        (20 * 365, "month"),
    ],
)
def test_the_span_chooses_the_bucket(span: int, bucket: TimelineBucket) -> None:
    first = D(2021, 1, 1)
    assert choose(first, first + timedelta(days=span - 1), None) == (bucket, False)


def test_thresholds_are_those_of_d91() -> None:
    assert (DAY_SPAN, WEEK_SPAN, MAX_TIMELINE_BUCKETS) == (120, 156 * 7, 1500)


def test_a_requested_bucket_stays_up_to_the_limit() -> None:
    first = D(2020, 1, 1)
    assert choose(first, first + timedelta(days=MAX_TIMELINE_BUCKETS - 1), "day") == (
        "day",
        False,
    )
    assert choose(first, first, "month") == ("month", False)
    assert choose(first, first + timedelta(days=200), "day") == ("day", False)  # not auto


def test_a_requested_bucket_above_the_limit_is_coarsened() -> None:
    first = D(2020, 1, 1)  # a Wednesday
    assert choose(first, first + timedelta(days=MAX_TIMELINE_BUCKETS), "day") == ("week", True)
    monday = D(2019, 12, 30)
    weeks = monday + timedelta(weeks=MAX_TIMELINE_BUCKETS - 1)
    assert choose(monday, weeks, "week") == ("week", False)
    assert choose(monday, weeks + timedelta(days=7), "week") == ("month", True)
    # Too many weeks as well: day goes on to month.
    assert choose(monday, weeks + timedelta(days=7), "day") == ("month", True)
    # Months are never coarsened, however many there are.
    assert choose(D(1800, 1, 1), D(2020, 1, 1), "month") == ("month", False)


def test_position_finds_the_bucket_of_a_day() -> None:
    starts = axis(D(2021, 1, 1), D(2021, 4, 30), "month")
    assert position(starts, D(2020, 12, 31)) == -1
    assert position(starts, D(2021, 1, 1)) == 0
    assert position(starts, D(2021, 2, 28)) == 1
    assert position(starts, D(2021, 4, 30)) == 3
    assert position([], D(2021, 1, 1)) == -1

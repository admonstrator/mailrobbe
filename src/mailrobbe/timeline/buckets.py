"""Buckets of the timeline (D91): UTC days, ISO weeks (Monday to Sunday) and calendar months.

The database counts the matching mails per UTC day; these functions choose the bucket of an
axis, lay out its bucket starts without gaps and sum the days into them. An axis runs from a
first to a last day, both inside it; its first bucket is the one holding the first day.
"""

import bisect
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from mailrobbe.api.schemas import MAX_TIMELINE_BUCKETS, TimelineBucket

# Without a chosen bucket the span of the axis decides, in days with both ends counted (D91).
DAY_SPAN = 120  # up to 120 days: by day
WEEK_SPAN = 156 * 7  # up to 156 weeks: by week; longer: by month

# The next coarser bucket, for a chosen one that gives more than MAX_TIMELINE_BUCKETS.
_COARSER: dict[TimelineBucket, TimelineBucket] = {"day": "week", "week": "month"}


def bucket_start(day: date, bucket: TimelineBucket) -> date:
    """The first day of the bucket holding day: itself, its week's Monday, its month's 1st."""
    if bucket == "day":
        return day
    if bucket == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def next_start(start: date, bucket: TimelineBucket) -> date:
    """The first day of the bucket after the one that starts on start."""
    if bucket == "day":
        return start + timedelta(days=1)
    if bucket == "week":
        return start + timedelta(days=7)
    return date(start.year + start.month // 12, start.month % 12 + 1, 1)


def bucket_count(first: date, last: date, bucket: TimelineBucket) -> int:
    """The number of buckets of the axis from first to last."""
    start, end = bucket_start(first, bucket), bucket_start(last, bucket)
    if bucket == "month":
        return (end.year - start.year) * 12 + end.month - start.month + 1
    return (end - start).days // (7 if bucket == "week" else 1) + 1


def choose(
    first: date, last: date, requested: TimelineBucket | None
) -> tuple[TimelineBucket, bool]:
    """The bucket of the axis from first to last, and whether the requested one gave more than
    MAX_TIMELINE_BUCKETS and was replaced by a coarser one (months never are)."""
    if requested is None:
        span = (last - first).days + 1
        return ("day" if span <= DAY_SPAN else "week" if span <= WEEK_SPAN else "month"), False
    bucket = requested
    while bucket in _COARSER and bucket_count(first, last, bucket) > MAX_TIMELINE_BUCKETS:
        bucket = _COARSER[bucket]
    return bucket, bucket != requested


def axis(first: date, last: date, bucket: TimelineBucket) -> list[date]:
    """The first day of every bucket from the one holding first to the one holding last."""
    starts = [bucket_start(first, bucket)]
    for _ in range(bucket_count(first, last, bucket) - 1):
        starts.append(next_start(starts[-1], bucket))
    return starts


def sum_days(days: Mapping[date, int], starts: Sequence[date], bucket: TimelineBucket) -> list[int]:
    """The counts per day summed into the buckets of starts; days off the axis are left out."""
    index = {start: position for position, start in enumerate(starts)}
    counts = [0] * len(starts)
    for day, count in days.items():
        position = index.get(bucket_start(day, bucket))
        if position is not None:
            counts[position] += count
    return counts


def position(starts: Sequence[date], day: date) -> int:
    """The index of the bucket of starts holding day (not after the axis); -1 before it."""
    return bisect.bisect_right(starts, day) - 1


def covered(
    starts: Sequence[date], bucket: TimelineBucket, first: date | None, end: date | None
) -> range:
    """The indexes of the buckets of starts that lie wholly within the days from first (None: no
    bound) to end (None: no day at all): not the first bucket when first cuts it, not the bucket
    holding end unless end is its last day, none after it."""
    if end is None or not starts:
        return range(0)
    low = 0 if first is None or starts[0] >= first else 1
    high = position(starts, end)
    if end < date.max and bucket_start(end + timedelta(days=1), bucket) <= end:
        high -= 1  # the day after end is in its bucket: end is not the bucket's last day
    return range(low, high + 1)

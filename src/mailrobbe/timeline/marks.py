"""Marks of a timeline series (D93): buckets far above or below the moving mean, and silence.

A bucket is compared with the mean of the buckets before it on the axis (HISTORY); a bucket
with less history than that gets no mark. A series falls silent when it has no mail from one
bucket up to the end bucket (the one holding date_to or the archive's end, whichever is
earlier) after steady activity in the window before; buckets after the end, which hold mails
dated in the future, do not count. The comparisons use whole numbers, so a bucket exactly at a
threshold is marked. The rules are simple enough for the screen to retell them.
"""

from collections.abc import Sequence

from mailrobbe.api.schemas import TimelineBucket, TimelineOutlier

# The buckets a moving mean is taken over, as distances back from the bucket compared.
HISTORY: dict[TimelineBucket, tuple[int, ...]] = {
    "day": (7, 14, 21, 28),  # the same weekday of the four weeks before
    "week": tuple(range(1, 9)),  # the eight weeks before
    "month": tuple(range(1, 7)),  # the six months before
}
HIGH_FACTOR = 3  # high: at least three times the mean ...
HIGH_MARGIN = 5  # ... and at least five mails more than the mean
LOW_MEAN = 5  # low: only against a mean of at least five mails ...
LOW_FACTOR = 3  # ... and at most a third of it
# Silence: no mail for at least this many buckets up to the end (21 days, 6 weeks, 3 months) ...
SILENT_BUCKETS: dict[TimelineBucket, int] = {"day": 21, "week": 6, "month": 3}
# ... after the window just before it (28 days, 8 weeks, 6 months; buckets before the axis hold
# no matching mail) ...
SILENT_WINDOW: dict[TimelineBucket, int] = {"day": 28, "week": 8, "month": 6}
SILENT_ACTIVE_SHARE = 0.5  # ... had mails in at least half of its buckets ...
SILENT_MAILS = 5  # ... and at least five mails in all


def outliers(counts: Sequence[int], bucket: TimelineBucket) -> list[TimelineOutlier]:
    """The buckets of counts far above (high) or below (low) the mean of their history."""
    history = HISTORY[bucket]
    size = len(history)
    found = []
    for index in range(max(history), len(counts)):
        count = counts[index]
        past = sum(counts[index - back] for back in history)  # the mean is past / size
        if count * size >= HIGH_FACTOR * past and count * size >= past + HIGH_MARGIN * size:
            found.append(TimelineOutlier(index=index, kind="high", expected=past / size))
        elif past >= LOW_MEAN * size and LOW_FACTOR * count * size <= past:
            found.append(TimelineOutlier(index=index, kind="low", expected=past / size))
    return found


def silent_from(counts: Sequence[int], bucket: TimelineBucket, end: int) -> int | None:
    """The index of the bucket from which counts has no mail up to the end bucket `end` (-1:
    the end is before the axis), when the series was steadily active before; None otherwise."""
    if end < 0 or counts[end]:
        return None
    start = end
    while start > 0 and not counts[start - 1]:
        start -= 1
    window_size = SILENT_WINDOW[bucket]
    window = counts[max(0, start - window_size) : start]
    active = sum(1 for count in window if count)
    if (
        end - start + 1 < SILENT_BUCKETS[bucket]
        or active < SILENT_ACTIVE_SHARE * window_size
        or sum(window) < SILENT_MAILS
    ):
        return None
    return start

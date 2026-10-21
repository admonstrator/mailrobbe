"""Calendar days written in the text (D81): 15.03.2019, 15.3.19, 15. März 2019, 15. Mär. 2019,
15 March 2019, March 15, 2019 and 2019-03-15.

Two-digit years 00 to 39 are 20xx, 40 to 99 19xx; only valid days between 1900 and 2099 count.
Versions and numbers with more parts (1.2.3, 10.0.19041) are no dates, and a two-digit year needs
a two-digit day or month (1.2.33 is a version more often than a day). Key ISO (2019-03-15), label
German (15.03.2019).
"""

import re
from datetime import date

from mailrobbe.entities.occurrences import Occurrences
from mailrobbe.enums import EntityKind

MONTHS = {
    "Januar": 1, "Jänner": 1, "Jan": 1, "January": 1, "Februar": 2, "Feb": 2, "February": 2,
    "März": 3, "Mär": 3, "Mrz": 3, "March": 3, "Mar": 3, "April": 4, "Apr": 4, "Mai": 5,
    "May": 5, "Juni": 6, "Jun": 6, "June": 6, "Juli": 7, "Jul": 7, "July": 7, "August": 8,
    "Aug": 8, "September": 9, "Sep": 9, "Sept": 9, "Oktober": 10, "Okt": 10, "October": 10,
    "Oct": 10, "November": 11, "Nov": 11, "Dezember": 12, "Dez": 12, "December": 12, "Dec": 12,
}  # fmt: skip
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
# The lookahead lets the scan pass every position that starts no date at once; without it, each
# position enters the four alternatives and their lookbehinds (twice the time per text).
_FIRST = "".join(sorted({month[0] for month in MONTHS}))
_DATE = re.compile(
    rf"""
    (?=[\d{_FIRST}])
    (?:
      (?<![\w.,-])(?P<iso_year>\d{{4}})-(?P<iso_month>\d{{2}})-(?P<iso_day>\d{{2}})(?!-?\d)
    | (?<![\w.,])(?P<day>\d{{1,2}})\.(?P<month>\d{{1,2}})\.(?P<year>\d{{4}}|\d{{2}})(?![\d]|[.,]\d)
    | (?<![\w.,])(?P<long_day>\d{{1,2}})(?:\.|st|nd|rd|th)?[ \t\u00a0]?
      (?P<long_month>{_MONTH})\.?,?[ \t\u00a0]+(?P<long_year>\d{{4}})(?!\d)
    | (?<![\w])(?P<us_month>{_MONTH})\.?[ \t\u00a0]+(?P<us_day>\d{{1,2}})(?:st|nd|rd|th)?,?
      [ \t\u00a0]+(?P<us_year>\d{{4}})(?!\d)
    )
    """,
    re.VERBOSE,
)


def find_dates(found: Occurrences) -> None:
    for match in _DATE.finditer(found.text):
        day = _day(match)
        if day is not None and found.free(*match.span()):
            found.add(EntityKind.DATE, day.isoformat(), f"{day:%d.%m.%Y}", *match.span())


def _day(match: re.Match[str]) -> date | None:
    groups = match.groupdict()
    if groups["iso_year"]:
        year, month, day = groups["iso_year"], groups["iso_month"], groups["iso_day"]
    elif groups["year"]:
        year, month, day = groups["year"], groups["month"], groups["day"]
        if len(year) == 2:
            if len(day) == 1 and len(month) == 1:
                return None
            year = f"{20 if int(year) < 40 else 19}{year}"
    elif groups["long_year"]:
        year, day = groups["long_year"], groups["long_day"]
        month = str(MONTHS[groups["long_month"]])
    else:
        year, day = groups["us_year"], groups["us_day"]
        month = str(MONTHS[groups["us_month"]])
    if not 1900 <= int(year) <= 2099:
        return None
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None

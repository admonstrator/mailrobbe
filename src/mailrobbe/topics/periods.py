"""The terms that stand out in every month, quarter and year (D142, D143; step topic_periods).

Every period with mails is compared with the whole archive: n is its mails, a the mails of it
holding a term, df the term's mails and N the archive's (undated mails count for df and N, not
for a period). The mails of every period come from the mails per month and model.period_start;
the term counts of every period are summed in one statement from topic_tmp_month, the pass of
step topic_terms, and only rows with a >= MIN_SCOPE_MAILS whose share could stand out at all
(a / n >= MIN_RATIO * (df - a) / (N - n), the first rule of keyness, in exact integers) leave the
database. keyness.keyness decides; common terms (a signature, a list's footer) are not kept for
periods. The PERIOD_TERMS terms with the highest G2 are kept per period, ties by label in Python
string order, then by lexeme.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.topics.keyness import MIN_RATIO, MIN_SCOPE_MAILS, keyness
from mailrobbe.topics.model import PERIOD_TERMS, UNITS, Term, Unit, period_start

Period = tuple[Unit, date]  # unit and first day

_PERIOD_TABLE = (
    text("""
        CREATE TEMP TABLE topic_tmp_period (
            unit text NOT NULL, period_start date NOT NULL, month date NOT NULL,
            mails integer NOT NULL
        ) ON COMMIT DROP
    """),
    text("""
        INSERT INTO topic_tmp_period (unit, period_start, month, mails)
        SELECT * FROM unnest(CAST(:units AS text[]), CAST(:starts AS date[]),
            CAST(:months AS date[]), CAST(:mails AS integer[]))
    """),
)
# One row per period and term of the vocabulary (topic_tmp_term) that may stand out. The
# products stay below 2^53, so float8 compares them exactly.
_PERIOD_TERMS = text("""
    SELECT p.unit, p.period_start, c.lexeme, sum(c.mails)::integer AS a
    FROM topic_tmp_month c
    JOIN topic_tmp_period p ON p.month = c.month
    JOIN topic_tmp_term t ON t.lexeme = c.lexeme
    GROUP BY p.unit, p.period_start, p.mails, c.lexeme, t.mails
    HAVING sum(c.mails) >= :min_mails
       AND sum(c.mails)::float8 * (:total - p.mails)
           >= :ratio * (t.mails - sum(c.mails))::float8 * p.mails
""")


@dataclass(frozen=True, slots=True)
class PeriodTerm:
    lexeme: str
    mails: int  # a
    score: float  # G2


def period_mails(months: Mapping[date, int]) -> dict[Period, int]:
    """The mails of every month, quarter and year with mails, from the mails per month."""
    mails: Counter[Period] = Counter()
    for month, count in months.items():
        for unit in UNITS:
            mails[unit, period_start(month, unit)] += count
    return dict(mails)


def rank_terms(
    rows: Iterable[tuple[Unit, date, str, int]],
    periods: Mapping[Period, int],
    terms: Mapping[str, Term],
    total: int,
) -> dict[Period, list[PeriodTerm]]:
    """The PERIOD_TERMS terms standing out most in each period, from (unit, start, lexeme, a)
    rows; periods: their mails (n), terms: the vocabulary (df), total: N."""
    found: defaultdict[Period, list[tuple[float, str, str, int]]] = defaultdict(list)
    for unit, start, lexeme, a in rows:
        term = terms[lexeme]
        figures = keyness(a, periods[unit, start], term.mails, total)
        if figures is not None and not figures.common:
            found[unit, start].append((-figures.score, term.label, lexeme, figures.mails))
    return {
        period: [
            PeriodTerm(lexeme, mails, -score)
            for score, _, lexeme, mails in sorted(items)[:PERIOD_TERMS]
        ]
        for period, items in found.items()
    }


async def rank_periods(
    session: AsyncSession, months: Mapping[date, int], terms: Mapping[str, Term], total: int
) -> tuple[dict[Period, int], dict[Period, list[PeriodTerm]]]:
    """Every period with its mails, and its terms standing out most (module docstring); reads
    topic_tmp_month and topic_tmp_term of step topic_terms."""
    periods = period_mails(months)
    rows = [
        (unit, period_start(month, unit), month, periods[unit, period_start(month, unit)])
        for month in months
        for unit in UNITS
    ]
    create, insert = _PERIOD_TABLE
    await session.execute(create)
    await session.execute(
        insert,
        {
            "units": [row[0] for row in rows],
            "starts": [row[1] for row in rows],
            "months": [row[2] for row in rows],
            "mails": [row[3] for row in rows],
        },
    )
    counts = await session.execute(
        _PERIOD_TERMS, {"min_mails": MIN_SCOPE_MAILS, "total": total, "ratio": MIN_RATIO}
    )
    found = [(unit, start, lexeme, a) for unit, start, lexeme, a in counts]
    return periods, rank_terms(found, periods, terms, total)

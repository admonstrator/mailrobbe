"""Topics: terms that stand out per period, in a selection, and clusters of terms (milestone 13,
D140 to D148). Models are in schemas.py. Routes: GET /api/topics/periods, /api/topics/terms,
/api/topics/clusters.

The periods and the clusters are read as the topics phase stored them (D146), from the small
topic tables only: a period's terms in one statement with their periods, the clusters with their
terms in one and their months in another. A term's figures are those keyness.keyness gives for
its stored mails against the period's mails, the term's archive mails (topic_term.mails) and the
archive's (topic_state.mails), the same figures the phase ranked it by.

The terms of a selection (D144) are counted on request. Its conditions are the mail list's
(mails._where, then filters.resolve_contents, as the facets and the timeline take them) and "no
duplicate"; without any condition the selection is the archive, against which nothing stands
out. Under the count budget of the mail list (D19), each statement in a savepoint of its own:
the selection's mails are counted, and the ids of TOPIC_SAMPLE of them are taken in the order of
hashint8(id), all of them in a smaller selection, else a sample spread over the whole selection
that is the same at every request. Then the sample's mails per lexeme (the aggregate first, then
topic_term by lexeme, so that only the vocabulary is looked up), at least MIN_SCOPE_MAILS of
them, scaled to the selection's mails when sampled, against the archive as the topics phase
last counted it. When the count runs out of time but the sample does not, a sample of fewer than
TOPIC_SAMPLE + 1 mails is the whole selection and counts it; a full one is the scope itself, n
its mails and a as counted: the selection's other mails then count with the rest of the archive,
which makes the selection's terms stand out less, not more. When the sample or the terms run out
of time, the lists are empty and timed_out is set.
"""

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Executable,
    and_,
    any_,
    func,
    literal,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import AppSettings, Session
from mailrobbe.api.documents import _all_unless_canceled
from mailrobbe.api.filters import resolve_contents, unfiltered
from mailrobbe.api.mails import _count_budget, _terms, _unless_canceled, _where
from mailrobbe.api.schemas import (
    TOPIC_SAMPLE,
    TopicCluster,
    TopicClusters,
    TopicClusterTerm,
    TopicMonth,
    TopicPeriod,
    TopicPeriodParams,
    TopicPeriods,
    TopicState,
    TopicTerm,
    TopicTermParams,
    TopicTerms,
)
from mailrobbe.db.models import Mail
from mailrobbe.db.models import TopicCluster as ClusterRow
from mailrobbe.db.models import TopicClusterMonth as ClusterMonthRow
from mailrobbe.db.models import TopicClusterTerm as ClusterTermRow
from mailrobbe.db.models import TopicPeriod as PeriodRow
from mailrobbe.db.models import TopicPeriodTerm as PeriodTermRow
from mailrobbe.db.models import TopicState as StateRow
from mailrobbe.db.models import TopicTerm as TermRow
from mailrobbe.topics.keyness import MIN_SCOPE_MAILS, Keyness, keyness
from mailrobbe.topics.model import period_end, period_start

router = APIRouter(prefix="/api/topics", tags=["topics"])

_NOTHING = TopicState(computed_at=None, mails=0, terms=0, clusters=0)
_ORIGINAL = Mail.is_duplicate_of.is_(None)


async def _state(session: AsyncSession) -> TopicState:
    found = await session.execute(
        select(StateRow.computed_at, StateRow.mails, StateRow.terms, StateRow.clusters)
    )
    row = found.one_or_none()
    if row is None:
        return _NOTHING
    return TopicState(
        computed_at=row.computed_at, mails=row.mails, terms=row.terms, clusters=row.clusters
    )


def _term(row: Any, found: Keyness) -> TopicTerm:
    """A term of a scope from its row of topic_term (lexeme, label, themes) and its figures."""
    return TopicTerm(
        term=row.lexeme,
        label=row.label,
        mails=found.mails,
        share=found.share,
        rest_share=found.rest_share,
        ratio=found.ratio,
        score=found.score,
        themes=row.themes,
    )


# Periods -------------------------------------------------------------------------------------


@router.get("/periods")
async def periods(params: Annotated[TopicPeriodParams, Query()], session: Session) -> TopicPeriods:
    state = await _state(session)
    unit = params.unit
    where = [PeriodRow.unit == unit]
    # Periods start on the first day of their unit: one overlaps date_from when it starts at or
    # after the start of the period holding date_from.
    if params.date_from is not None:
        where.append(PeriodRow.period_start >= period_start(params.date_from, unit))
    if params.date_to is not None:
        where.append(PeriodRow.period_start <= params.date_to)
    ranked = and_(
        PeriodTermRow.unit == PeriodRow.unit,
        PeriodTermRow.period_start == PeriodRow.period_start,
        PeriodTermRow.rank <= params.limit,
    )
    rows = await session.execute(
        select(
            PeriodRow.period_start,
            PeriodRow.mails.label("period_mails"),
            PeriodTermRow.mails,
            TermRow.lexeme,
            TermRow.label,
            TermRow.mails.label("archive_mails"),
            TermRow.themes,
        )
        .outerjoin(PeriodTermRow, ranked)
        .outerjoin(TermRow, TermRow.id == PeriodTermRow.term_id)
        .where(*where)
        .order_by(PeriodRow.period_start.desc(), PeriodTermRow.rank)
    )
    found: dict[date, TopicPeriod] = {}
    for row in rows:
        period = found.get(row.period_start)
        if period is None:
            period = found[row.period_start] = TopicPeriod(
                start=row.period_start,
                end=period_end(row.period_start, unit),
                mails=row.period_mails,
                terms=[],
            )
        if row.lexeme is None:
            continue
        # The phase stored what keyness found for these figures; never None for its rows.
        figures = keyness(row.mails, row.period_mails, row.archive_mails, state.mails)
        if figures is not None:
            period.terms.append(_term(row, figures))
    return TopicPeriods(state=state, unit=unit, periods=list(found.values()))


# Terms of a selection ------------------------------------------------------------------------


@router.get("/terms")
async def terms(
    params: Annotated[TopicTermParams, Query()], session: Session, settings: AppSettings
) -> TopicTerms:
    state = await _state(session)
    # Duplicates never count here, whether the list hides them or not.
    filters = params.model_copy(update={"hide_duplicates": False})
    where = _where(filters, _terms(params.q), settings)
    if unfiltered(where):
        return _terms_of(state, state.mails)
    where = await resolve_contents(session, [*where, _ORIGINAL])
    await _count_budget(session, settings)
    row = await _unless_canceled(session, select(func.count()).select_from(Mail).where(*where))
    mails = None if row is None else int(row[0])
    by_hash = (
        select(Mail.id)
        .where(*where)
        .order_by(func.hashint8(Mail.id), Mail.id)
        .limit(TOPIC_SAMPLE + 1)
    )
    sample = await _all_unless_canceled(session, by_hash)
    if sample is None:
        return _terms_of(state, mails, timed_out=True)
    sampled = len(sample) > TOPIC_SAMPLE
    ids = [found.id for found in sample[:TOPIC_SAMPLE]]
    if mails is None and not sampled:  # the sample is the whole selection
        mails = len(ids)
    if not ids or state.computed_at is None:
        return _terms_of(state, mails)
    counts = await _all_unless_canceled(session, _lexeme_counts(ids))
    if counts is None:
        return _terms_of(state, mails, timed_out=True)
    size = len(ids) if mails is None else mails  # n; a is scaled to it (D144)
    standing: list[TopicTerm] = []
    common: list[TopicTerm] = []
    for counted in counts:
        figures = keyness(counted.a * size / len(ids), size, counted.mails, state.mails)
        if figures is not None:
            (common if figures.common else standing).append(_term(counted, figures))
    standing.sort(key=lambda term: (-term.score, term.label, term.term))
    common.sort(key=lambda term: (-term.mails, term.label, term.term))
    return TopicTerms(
        state=state,
        mails=mails,
        counted=len(ids),
        sampled=sampled,
        terms=standing[: params.limit],
        common=common[: params.limit],
        timed_out=False,
    )


def _terms_of(state: TopicState, mails: int | None, timed_out: bool = False) -> TopicTerms:
    """A selection whose terms were not counted."""
    return TopicTerms(
        state=state,
        mails=mails,
        counted=0,
        sampled=False,
        terms=[],
        common=[],
        timed_out=timed_out,
    )


def _lexeme_counts(mail_ids: Sequence[int]) -> Executable:
    """The terms of the vocabulary in at least MIN_SCOPE_MAILS of these mails, with their rows
    of topic_term and a, the mails holding them. tsvector_to_array leaves the positions out,
    which makes the count a third faster than unnest(tsv)."""
    words = func.unnest(func.tsvector_to_array(Mail.tsv)).table_valued("lexeme").render_derived("u")
    ids: ColumnElement[Any] = literal(list(mail_ids), ARRAY(BigInteger))
    counted = (
        select(words.c.lexeme, func.count().label("a"))
        .select_from(Mail)
        .join(words, true())
        .where(Mail.id == any_(ids))
        .group_by(words.c.lexeme)
        .having(func.count() >= MIN_SCOPE_MAILS)
        .subquery("counted")
    )
    return select(
        TermRow.lexeme, TermRow.label, TermRow.mails, TermRow.themes, counted.c.a
    ).join_from(counted, TermRow, TermRow.lexeme == counted.c.lexeme)


# Clusters ------------------------------------------------------------------------------------


@router.get("/clusters")
async def clusters(session: Session) -> TopicClusters:
    state = await _state(session)
    rows = await session.execute(
        select(
            ClusterRow.id,
            ClusterRow.label,
            ClusterRow.query,
            ClusterRow.mails,
            ClusterRow.first_date,
            ClusterRow.last_date,
            ClusterTermRow.weight,
            TermRow.lexeme,
            TermRow.label.label("term_label"),
            TermRow.mails.label("term_mails"),
            TermRow.themes,
        )
        .outerjoin(ClusterTermRow, ClusterTermRow.cluster_id == ClusterRow.id)
        .outerjoin(TermRow, TermRow.id == ClusterTermRow.term_id)
        .order_by(ClusterRow.rank, ClusterTermRow.rank)
    )
    found: dict[int, TopicCluster] = {}
    for row in rows:
        cluster = found.get(row.id)
        if cluster is None:
            cluster = found[row.id] = TopicCluster(
                id=row.id,
                label=row.label,
                query=row.query,
                mails=row.mails,
                first_date=row.first_date,
                last_date=row.last_date,
                terms=[],
                months=[],
            )
        if row.lexeme is not None:
            cluster.terms.append(
                TopicClusterTerm(
                    term=row.lexeme,
                    label=row.term_label,
                    mails=row.term_mails,
                    weight=row.weight,
                    themes=row.themes,
                )
            )
    months = await session.execute(
        select(ClusterMonthRow.cluster_id, ClusterMonthRow.month, ClusterMonthRow.mails).order_by(
            ClusterMonthRow.cluster_id, ClusterMonthRow.month
        )
    )
    for cluster_id, month, count in months:
        if cluster_id in found:
            found[cluster_id].months.append(TopicMonth(month=month, mails=count))
    return TopicClusters(state=state, clusters=list(found.values()))

"""The topics phase of an import (D146): when the archive changed since the topics were computed,
count, label, rank and group the terms and replace the stored results in one transaction.

    waiting         the fingerprint of the archive as it is now: TOPICS_VERSION, [topics] ignore,
                    the single-word terms of the themes' word fields with their keys, the
                    number, largest id and duplicates of the mails, and the standard blocks the
                    last blocks step applied (paragraph_block.standard with PARAGRAPH_VERSION,
                    D225: the terms leave them out) (a few aggregates, no text read), compared
                    with topic_state.fingerprint
    topic_terms     vocabulary.count_terms: one pass over mail.tsv counting every lexeme per UTC
                    month, N and the mails per month, the vocabulary (D141)
    topic_labels    labels.read_labels: the text of every mail once, each term's spelling written
                    most as its label
    topic_periods   periods.rank_periods: the PERIOD_TERMS terms that stand out most in every
                    month, quarter and year with mails (D142, D143)
    topic_clusters  clusters.find_clusters over the vocabulary (D145)
    store           topic_term, topic_period, topic_period_term, topic_cluster,
                    topic_cluster_term and topic_cluster_month emptied and filled again,
                    topic_term analysed, the one topic_state row written, then the one commit

Everything runs in one session and one transaction; the intermediate data lives in temporary
tables (topic_tmp_*, dropped at the end of the transaction), so until the commit the screens show
the previous results. A stop, checked between the steps and between the batches of the label
pass, rolls the transaction back and keeps them: the next import computes again, since its
fingerprint still differs. Every step reads each mail or each lexeme of mail.tsv a bounded number
of times; the big aggregate of topic_terms may take WORK_MEM.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe import themes
from mailrobbe.db.models import PARAGRAPH_VERSION
from mailrobbe.jobrun import Steps
from mailrobbe.topics import clusters
from mailrobbe.topics.labels import read_labels
from mailrobbe.topics.model import (
    TOPICS_VERSION,
    UNITS,
    Cluster,
    Term,
    cluster_label,
    cluster_query,
)
from mailrobbe.topics.periods import Period, PeriodTerm, rank_periods
from mailrobbe.topics.vocabulary import count_terms, theme_words

log = logging.getLogger(__name__)

STEPS = ("topic_terms", "topic_labels", "topic_periods", "topic_clusters")  # in order
WORK_MEM = "256MB"  # for the aggregates of this transaction (SET LOCAL)

# Each count from an index where one serves: the primary key, the partial one of duplicates.
_ARCHIVE = text("""
    SELECT (SELECT count(*) FROM mail), (SELECT max(id) FROM mail),
           (SELECT count(*) FROM mail WHERE is_duplicate_of IS NOT NULL)
""")
# The standard blocks applied to the mails' ranges: a mail's blocks follow from its stored text,
# its paragraphs' split (PARAGRAPH_VERSION) and this set, so the set stands for all of them.
_BLOCKS = text("""
    SELECT count(*), md5(COALESCE(string_agg(CAST(hash AS text), ',' ORDER BY hash), ''))
    FROM paragraph_block WHERE standard
""")
_STORED = text("SELECT fingerprint FROM topic_state WHERE id = 1")

# The stored results, children first; DELETE keeps the readers of the screens going until the
# commit, where TRUNCATE would make them wait.
_FORGET = tuple(
    text(f"DELETE FROM {table}")
    for table in (
        "topic_cluster_month",
        "topic_cluster_term",
        "topic_cluster",
        "topic_period_term",
        "topic_period",
        "topic_term",
    )
)
_TERMS = text("""
    INSERT INTO topic_term (lexeme, label, mails)
    SELECT * FROM unnest(CAST(:lexemes AS text[]), CAST(:labels AS text[]),
        CAST(:mails AS integer[]))
""")
_TERM_THEMES = text("""
    UPDATE topic_term t SET themes = u.themes
    FROM (
        SELECT lexeme, array_agg(key ORDER BY ordinal) AS themes
        FROM unnest(CAST(:lexemes AS text[]), CAST(:keys AS text[])) WITH ORDINALITY
            AS u(lexeme, key, ordinal)
        GROUP BY lexeme
    ) AS u
    WHERE t.lexeme = u.lexeme
""")
_PERIODS = text("""
    INSERT INTO topic_period (unit, period_start, mails)
    SELECT * FROM unnest(CAST(:units AS text[]), CAST(:starts AS date[]),
        CAST(:mails AS integer[]))
""")
_PERIOD_TERMS = text("""
    INSERT INTO topic_period_term (unit, period_start, rank, term_id, mails, score)
    SELECT u.unit, u.period_start, u.rank, t.id, u.mails, u.score
    FROM unnest(CAST(:units AS text[]), CAST(:starts AS date[]), CAST(:ranks AS smallint[]),
            CAST(:lexemes AS text[]), CAST(:mails AS integer[]), CAST(:scores AS real[]))
        AS u(unit, period_start, rank, lexeme, mails, score)
    JOIN topic_term t ON t.lexeme = u.lexeme
""")
_CLUSTERS = text("""
    INSERT INTO topic_cluster (rank, label, query, mails, first_date, last_date)
    SELECT * FROM unnest(CAST(:ranks AS smallint[]), CAST(:labels AS text[]),
        CAST(:queries AS text[]), CAST(:mails AS integer[]), CAST(:firsts AS timestamptz[]),
        CAST(:lasts AS timestamptz[]))
""")
_CLUSTER_TERMS = text("""
    INSERT INTO topic_cluster_term (cluster_id, rank, term_id, weight)
    SELECT c.id, u.rank, t.id, u.weight
    FROM unnest(CAST(:clusters AS smallint[]), CAST(:ranks AS smallint[]),
            CAST(:lexemes AS text[]), CAST(:weights AS real[]))
        AS u(cluster, rank, lexeme, weight)
    JOIN topic_cluster c ON c.rank = u.cluster
    JOIN topic_term t ON t.lexeme = u.lexeme
""")
_CLUSTER_MONTHS = text("""
    INSERT INTO topic_cluster_month (cluster_id, month, mails)
    SELECT c.id, u.month, u.mails
    FROM unnest(CAST(:clusters AS smallint[]), CAST(:months AS date[]),
            CAST(:mails AS integer[]))
        AS u(cluster, month, mails)
    JOIN topic_cluster c ON c.rank = u.cluster
""")
_STATE = text("""
    INSERT INTO topic_state (id, fingerprint, computed_at, mails, terms, clusters, seconds)
    VALUES (1, :fingerprint, clock_timestamp(), :mails, :terms, :clusters, :seconds)
    ON CONFLICT (id) DO UPDATE SET
        fingerprint = EXCLUDED.fingerprint, computed_at = EXCLUDED.computed_at,
        mails = EXCLUDED.mails, terms = EXCLUDED.terms, clusters = EXCLUDED.clusters,
        seconds = EXCLUDED.seconds
""")


@dataclass(frozen=True, slots=True)
class TopicsResult:
    """What one compute_topics stored, for the import's summary and the tests."""

    terms: int  # the vocabulary
    periods: int  # periods of all units with mails
    clusters: int
    seconds: float


async def waiting(session: AsyncSession) -> str | None:
    """The fingerprint of the archive as it is now when the stored topics were computed for
    another one (or never), else None: nothing to do."""
    mails, last_id, duplicates = (await session.execute(_ARCHIVE)).one()
    blocks, digest = (await session.execute(_BLOCKS)).one()
    archive = {
        "version": TOPICS_VERSION,
        "ignore": list(themes.load_topic_ignore()),
        "themes": [list(pair) for pair in theme_words()],
        "mails": [mails, last_id, duplicates],
        "blocks": [PARAGRAPH_VERSION, blocks, digest],
    }
    fingerprint = hashlib.sha256(json.dumps(archive, ensure_ascii=False).encode()).hexdigest()
    return None if await session.scalar(_STORED) == fingerprint else fingerprint


async def compute_topics(
    sessionmaker: async_sessionmaker[AsyncSession],
    fingerprint: str,
    stop: asyncio.Event,
    steps: Steps,
) -> TopicsResult | None:
    """Compute and store every topic for the archive of fingerprint, reporting the STEPS; None
    when a stop came first (the stored results stay as they were)."""
    started = time.monotonic()
    async with sessionmaker() as session:
        await session.execute(text(f"SET LOCAL work_mem = '{WORK_MEM}'"))
        result = await _compute(session, fingerprint, stop, steps, started)
        if result is None:
            await session.rollback()
            log.info("topics: stopped, the topics computed before stay")
        else:
            await session.commit()
    return result


async def _compute(
    session: AsyncSession, fingerprint: str, stop: asyncio.Event, steps: Steps, started: float
) -> TopicsResult | None:
    """The steps and the replacement in session's transaction, without its commit."""
    with steps.step("topic_terms"):
        counted = await count_terms(session)
    log.info(
        "topics: %d mails (%d undated) in %d months, %d lexemes in enough mails, "
        "vocabulary of %d terms (left out: %s)",
        counted.total,
        counted.undated,
        len(counted.months),
        counted.frequent,
        len(counted.mails),
        ", ".join(f"{count} {rule}" for rule, count in counted.left_out.items()),
    )
    if stop.is_set():
        return None

    with steps.step("topic_labels", unit="mails", total=counted.total) as step:
        labelled = await read_labels(session, counted.mails, stop, step)
    if labelled is None:
        return None
    labels, spellings = labelled
    vocabulary = {
        lexeme: Term(lexeme, labels.get(lexeme, lexeme), mails, counted.themes.get(lexeme, ()))
        for lexeme, mails in counted.mails.items()
    }
    log.info(
        "topics: read the texts of %d mails, %d spellings label %d of %d terms",
        counted.total,
        spellings,
        len(labels),
        len(vocabulary),
    )
    if stop.is_set():
        return None

    with steps.step("topic_periods"):
        periods, ranked = await rank_periods(session, counted.months, vocabulary, counted.total)
    log.info(
        "topics: %s ranked, %d terms listed",
        ", ".join(f"{sum(1 for unit, _ in periods if unit == kind)} {kind}s" for kind in UNITS),
        sum(len(terms) for terms in ranked.values()),
    )
    if stop.is_set():
        return None

    with steps.step("topic_clusters"):
        found = await clusters.find_clusters(session, vocabulary, counted.total)
    log.info("topics: %d clusters", len(found))
    if stop.is_set():
        return None

    await _store(session, vocabulary, periods, ranked, found)
    result = TopicsResult(
        terms=len(vocabulary),
        periods=len(periods),
        clusters=len(found),
        seconds=time.monotonic() - started,
    )
    await session.execute(
        _STATE,
        {
            "fingerprint": fingerprint,
            "mails": counted.total,
            "terms": result.terms,
            "clusters": result.clusters,
            "seconds": result.seconds,
        },
    )
    return result


async def _store(
    session: AsyncSession,
    vocabulary: Mapping[str, Term],
    periods: Mapping[Period, int],
    ranked: Mapping[Period, list[PeriodTerm]],
    found: Sequence[Cluster],
) -> None:
    """Replace the stored results (module docstring), all but topic_state."""
    for statement in _FORGET:
        await session.execute(statement)
    terms = sorted(vocabulary.values(), key=lambda term: term.lexeme)
    await session.execute(
        _TERMS,
        {
            "lexemes": [term.lexeme for term in terms],
            "labels": [term.label for term in terms],
            "mails": [term.mails for term in terms],
        },
    )
    themed = [(term.lexeme, key) for term in terms for key in term.themes]
    if themed:
        await session.execute(
            _TERM_THEMES,
            {"lexemes": [lexeme for lexeme, _ in themed], "keys": [key for _, key in themed]},
        )
    await session.execute(text("ANALYZE topic_term"))
    await session.execute(
        _PERIODS,
        {
            "units": [unit for unit, _ in periods],
            "starts": [start for _, start in periods],
            "mails": list(periods.values()),
        },
    )
    listed = [
        (unit, start, rank, term)
        for (unit, start), terms_of_period in ranked.items()
        for rank, term in enumerate(terms_of_period, 1)
    ]
    await session.execute(
        _PERIOD_TERMS,
        {
            "units": [unit for unit, _, _, _ in listed],
            "starts": [start for _, start, _, _ in listed],
            "ranks": [rank for _, _, rank, _ in listed],
            "lexemes": [term.lexeme for _, _, _, term in listed],
            "mails": [term.mails for _, _, _, term in listed],
            "scores": [term.score for _, _, _, term in listed],
        },
    )
    await _store_clusters(session, vocabulary, found)


async def _store_clusters(
    session: AsyncSession, vocabulary: Mapping[str, Term], found: Sequence[Cluster]
) -> None:
    """The clusters in the order found (rank 1 first), with their terms and months."""
    if not found:
        return
    labels = [[vocabulary[lexeme].label for lexeme, _ in cluster.terms] for cluster in found]
    await session.execute(
        _CLUSTERS,
        {
            "ranks": list(range(1, len(found) + 1)),
            "labels": [cluster_label(names) for names in labels],
            "queries": [cluster_query(names) for names in labels],
            "mails": [cluster.mails for cluster in found],
            "firsts": [cluster.first_date for cluster in found],
            "lasts": [cluster.last_date for cluster in found],
        },
    )
    terms = [
        (rank, term_rank, lexeme, weight)
        for rank, cluster in enumerate(found, 1)
        for term_rank, (lexeme, weight) in enumerate(cluster.terms, 1)
    ]
    await session.execute(
        _CLUSTER_TERMS,
        {
            "clusters": [rank for rank, _, _, _ in terms],
            "ranks": [term_rank for _, term_rank, _, _ in terms],
            "lexemes": [lexeme for _, _, lexeme, _ in terms],
            "weights": [weight for _, _, _, weight in terms],
        },
    )
    months = [
        (rank, month, mails)
        for rank, cluster in enumerate(found, 1)
        for month, mails in cluster.months
    ]
    await session.execute(
        _CLUSTER_MONTHS,
        {
            "clusters": [rank for rank, _, _ in months],
            "months": [month for _, month, _ in months],
            "mails": [mails for _, _, mails in months],
        },
    )

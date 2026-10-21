"""Clusters of terms that stand together in the archive's mails (D145).

    candidates  the CLUSTER_CANDIDATES terms of the vocabulary with most mails among those in at
                least CLUSTER_MIN_MAILS mails and at most CLUSTER_MAX_SHARE of them, ties by
                lexeme; their rank is their number in the graph and the order Louvain visits
                them in. Rarer terms make chance pairs, commoner ones link everything.
    pairs       one pass over mail.tsv of the mails that are no duplicates: PostgreSQL gives each
                mail's candidates through = ANY over the candidates as one array parameter, which
                it hashes once for a statement planned for its parameters (a temporary table
                joined in each mail's subquery made it hash the mail's lexemes and read every
                candidate instead, 30 times slower), and the main process counts the pairs of a
                mail with 2 to MAIL_MAX_TERMS of them in a triangle of counters, 4 bytes per pair
                of candidates whatever the archive's size: 18 MB for 3,000. A mail with more (a
                newsletter, a digest, long minutes) would link words that have nothing to do
                with each other and does not count.
    links       a pair in at least LINK_MIN_MAILS mails whose normalised pointwise mutual
                information log(p(ab) / (p(a) p(b))) / -log(p(ab)), with p the share of the
                archive's mails, is at least LINK_MIN_NPMI: 1 when two terms only come together,
                0 when they meet as often as chance has it. Its weight is that figure.
    grouping    louvain.louvain over the links; a community of at least CLUSTER_MIN_TERMS terms
                is a cluster, described by its CLUSTER_TERMS strongest terms (the sum of their
                links inside it, ties by lexeme).
    mails       a second pass over mail.tsv finds, for every cluster at once, the mails that are
                no duplicates holding any of its first CLUSTER_QUERY_TERMS lexemes, as many as
                model.cluster_query of their labels finds in the mails' own text, counted per
                UTC month with the first and last date. One pass for all clusters reads every
                tsv once; a search per cluster would read the mails of each through ix_mail_tsv,
                a quarter of the archive for a cluster of five common terms, a hundred times.

Every step is in a fixed order, so the same archive gives the same clusters. find_clusters runs
inside the transaction of the topics phase and only reads.
"""

import asyncio
import math
from array import array
from collections.abc import Mapping, Sequence
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.topics.louvain import Link, louvain
from mailrobbe.topics.model import (
    CLUSTER_CANDIDATES,
    CLUSTER_LIMIT,
    CLUSTER_MAX_SHARE,
    CLUSTER_MIN_MAILS,
    CLUSTER_MIN_TERMS,
    CLUSTER_QUERY_TERMS,
    CLUSTER_TERMS,
    LINK_MIN_MAILS,
    LINK_MIN_NPMI,
    MAIL_MAX_TERMS,
    Cluster,
    Term,
)

_PARTITION = 10_000  # mails per batch of the stream

# Each mail's candidates; mails with fewer than two or more than :most do not count.
_CANDIDATES = text("""
    SELECT found FROM mail m CROSS JOIN LATERAL (
        SELECT array_agg(u.lexeme) AS found FROM unnest(tsvector_to_array(m.tsv)) AS u(lexeme)
        WHERE u.lexeme = ANY(CAST(:candidates AS text[]))
    ) AS s
    WHERE m.is_duplicate_of IS NULL AND cardinality(found) BETWEEN 2 AND :most
""").execution_options(yield_per=_PARTITION)

# Per cluster and UTC month (NULL: undated) the mails holding any of the clusters' lexemes, each
# owned by one cluster (:owners, in the order of :lexemes).
_MAILS = text("""
    SELECT s.cluster, date_trunc('month', m.date_utc AT TIME ZONE 'UTC')::date AS month,
        count(*) AS mails, min(m.date_utc) AS first_date, max(m.date_utc) AS last_date
    FROM mail m CROSS JOIN LATERAL (
        SELECT DISTINCT
            (CAST(:owners AS integer[]))[array_position(CAST(:lexemes AS text[]), u.lexeme)]
                AS cluster
        FROM unnest(tsvector_to_array(m.tsv)) AS u(lexeme)
        WHERE u.lexeme = ANY(CAST(:lexemes AS text[]))
    ) AS s
    WHERE m.is_duplicate_of IS NULL
    GROUP BY 1, 2
""")


async def find_clusters(
    session: AsyncSession, vocabulary: Mapping[str, Term], total: int
) -> list[Cluster]:
    """The clusters over the vocabulary (lexeme -> Term) of an archive of total mails that are
    no duplicates, most mails first, ties by their first lexeme, at most CLUSTER_LIMIT. Reads
    mail.tsv through session."""
    candidates = candidate_terms(vocabulary, total)
    if len(candidates) < CLUSTER_MIN_TERMS:
        return []
    pairs = await _count_pairs(session, candidates)
    mails = [vocabulary[lexeme].mails for lexeme in candidates]
    links = await asyncio.to_thread(find_links, pairs, mails, total)
    community = await asyncio.to_thread(louvain, len(candidates), links)
    groups = strongest_terms(candidates, links, community)
    if not groups:
        return []
    clusters = await _with_mails(session, groups)
    clusters.sort(key=lambda cluster: (-cluster.mails, cluster.terms[0][0]))
    return clusters[:CLUSTER_LIMIT]


def candidate_terms(vocabulary: Mapping[str, Term], total: int) -> list[str]:
    """The lexemes the clusters are made of, by rank."""
    usable = [
        (-term.mails, lexeme)
        for lexeme, term in vocabulary.items()
        if CLUSTER_MIN_MAILS <= term.mails <= CLUSTER_MAX_SHARE * total
    ]
    return [lexeme for _, lexeme in sorted(usable)[:CLUSTER_CANDIDATES]]


def _offsets(size: int) -> list[int]:
    """Where pair (i, j), i < j, of size candidates is in the triangle: offsets[i] + j."""
    return [i * (2 * size - i - 1) // 2 - i - 1 for i in range(size)]


async def _count_pairs(session: AsyncSession, candidates: Sequence[str]) -> array[int]:
    """The mails holding each pair of candidates, as a triangle (see _offsets). A partition is
    counted in a thread, so that the run keeps reporting meanwhile (D110)."""
    size = len(candidates)
    rank = {lexeme: number for number, lexeme in enumerate(candidates)}
    offsets = _offsets(size)
    pairs = array("i", [0]) * (size * (size - 1) // 2)
    params = {"candidates": list(candidates), "most": MAIL_MAX_TERMS}
    async for partition in (await session.stream(_CANDIDATES, params)).partitions():
        found = [row[0] for row in partition]
        await asyncio.to_thread(_add_pairs, found, rank, offsets, pairs)
    return pairs


def _add_pairs(
    mails: Sequence[Sequence[str]],
    rank: Mapping[str, int],
    offsets: Sequence[int],
    pairs: array[int],
) -> None:
    """Count the pairs of candidates of each mail into the triangle."""
    for found in mails:
        ranks = sorted(rank[lexeme] for lexeme in found)
        for position, first in enumerate(ranks):
            offset = offsets[first]
            for second in ranks[position + 1 :]:
                pairs[offset + second] += 1


def find_links(pairs: array[int], mails: Sequence[int], total: int) -> list[Link]:
    """The links between candidates (by rank), weighted by their NPMI, in rank order."""
    size = len(mails)
    links = []
    offsets = _offsets(size)
    for first in range(size - 1):
        offset = offsets[first]
        for second in range(first + 1, size):
            both = pairs[offset + second]
            if both < LINK_MIN_MAILS or both >= total:
                continue
            together = both / total
            chance = mails[first] * mails[second] / (total * total)
            weight = math.log(together / chance) / -math.log(together)
            if weight >= LINK_MIN_NPMI:
                links.append((first, second, weight))
    return links


def strongest_terms(
    candidates: Sequence[str], links: Sequence[Link], community: Sequence[int]
) -> list[tuple[tuple[str, float], ...]]:
    """The terms of each community of at least CLUSTER_MIN_TERMS candidates with their strength,
    the CLUSTER_TERMS strongest first; communities in the order of their first candidate."""
    strength = [0.0] * len(candidates)
    for first, second, weight in links:
        if community[first] == community[second]:
            strength[first] += weight
            strength[second] += weight
    members: dict[int, list[int]] = {}
    for node, number in enumerate(community):
        members.setdefault(number, []).append(node)
    groups = []
    for nodes in members.values():
        if len(nodes) < CLUSTER_MIN_TERMS:
            continue
        terms = sorted(((candidates[node], strength[node]) for node in nodes), key=_strongest)
        groups.append(tuple(terms[:CLUSTER_TERMS]))
    return groups


def _strongest(term: tuple[str, float]) -> tuple[float, str]:
    return -term[1], term[0]


async def _with_mails(
    session: AsyncSession, groups: Sequence[tuple[tuple[str, float], ...]]
) -> list[Cluster]:
    """The clusters with the mails of their query terms, counted in one pass."""
    lexemes, owners = [], []
    for number, terms in enumerate(groups):
        for lexeme, _ in terms[:CLUSTER_QUERY_TERMS]:
            lexemes.append(lexeme)
            owners.append(number)
    mails = [0] * len(groups)
    months: list[dict[date, int]] = [{} for _ in groups]
    first: list[datetime | None] = [None] * len(groups)
    last: list[datetime | None] = [None] * len(groups)
    rows = await session.execute(_MAILS, {"lexemes": lexemes, "owners": owners})
    for number, month, count, first_date, last_date in rows:
        mails[number] += count
        if month is None:
            continue
        months[number][month] = count
        first[number] = min(first_date, first[number] or first_date)
        last[number] = max(last_date, last[number] or last_date)
    return [
        Cluster(
            terms=terms,
            mails=mails[number],
            first_date=first[number],
            last_date=last[number],
            months=tuple(sorted(months[number].items())),
        )
        for number, terms in enumerate(groups)
    ]

"""GET /api/topics/periods, /api/topics/terms and /api/topics/clusters (D142 to D145).

The archive is the imported one with topic tables written in SQL (_topic_rows), so that the API
is tested without the topics phase: the vocabulary is every usable lexeme of the mails that are no
duplicates, periods and clusters are made up from terms in 15 to 30 mails (PICKS). Expected terms
of a selection are counted in SQL written apart from api/topics.py, their figures are those of
keyness.keyness, tested on its own in tests/topics.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api import topics
from mailrobbe.api.schemas import TOPIC_SELECTION_TERMS, TOPIC_TERMS
from mailrobbe.topics.keyness import keyness
from mailrobbe.topics.model import Unit, period_end
from tests.api.conftest import _client, _execute, api_settings
from tests.api.test_mails import FULL_TEXT, Params, get, rows, takes_part
from tests.api.test_timeline import MEMBER, busiest, common_word
from tests.conftest import GeneratedArchive, _temporary_database

pytestmark = pytest.mark.db

Json = dict[str, Any]

COMPUTED_AT = "2026-10-01T12:00:00Z"
# (unit, first day): (mails, [(pick, mails holding it)] by rank)
PERIODS: dict[tuple[str, date], tuple[int, list[tuple[int, int]]]] = {
    ("month", date(2023, 12, 1)): (20, [(5, 6)]),
    ("month", date(2024, 1, 1)): (50, [(1, 12), (2, 10), (3, 8)]),
    ("month", date(2024, 2, 1)): (40, [(4, 9), (1, 7)]),
    ("month", date(2024, 3, 1)): (30, []),
    ("quarter", date(2023, 10, 1)): (20, [(5, 6)]),
    ("quarter", date(2024, 1, 1)): (120, [(1, 19)]),
    ("year", date(2023, 1, 1)): (20, [(5, 6)]),
    ("year", date(2024, 1, 1)): (120, [(2, 15)]),
}
# id: (rank, label, query, mails, first date, last date, [(pick, weight)], [(month, mails)])
CLUSTERS: dict[int, tuple[Any, ...]] = {
    7: (
        2,
        "Erste, Zweite, Dritte",
        "Erste or Zweite or Dritte or Vierte",
        40,
        "2023-05-02T08:00:00Z",
        "2023-05-30T17:00:00Z",
        [(5, 1.75), (6, 1.5), (7, 1.25), (8, 1.0)],
        [("2023-05-01", 40)],
    ),
    3: (
        1,
        "Eins, Zwei, Drei",
        "Eins or Zwei or Drei or Vier",
        55,
        "2023-01-05T10:00:00Z",
        "2024-02-01T00:00:00Z",
        [(1, 3.5), (2, 2.25), (3, 2.0), (4, 1.5)],
        [("2023-01-01", 5), ("2024-02-01", 50)],
    ),
    5: (3, "Ohne, Datum", "Ohne or Datum", 12, None, None, [(k, 0.5) for k in range(9, 13)], []),
}
# The terms periods and clusters are made of: in 15 to 30 mails, by mails and lexeme.
PICKS = (
    "SELECT id, lexeme, label, mails, themes,"
    ' row_number() OVER (ORDER BY mails DESC, lexeme COLLATE "C") AS k'
    " FROM topic_term WHERE mails BETWEEN 15 AND 30"
)
CLEAR = [
    "DELETE FROM topic_state",
    "DELETE FROM topic_cluster",
    "DELETE FROM topic_period",
    "DELETE FROM topic_term",
]


def _topic_rows() -> list[str]:
    periods = ", ".join(
        f"('{unit}', '{start}', {mails})" for (unit, start), (mails, _) in PERIODS.items()
    )
    ranked = ", ".join(
        f"('{unit}', DATE '{start}', {rank}, {k}, {a})"
        for (unit, start), (_, terms) in PERIODS.items()
        for rank, (k, a) in enumerate(terms, 1)
    )
    clusters = ", ".join(
        f"({cluster_id}, {rank}, '{label}', '{query}', {mails}, "
        + ", ".join("NULL" if day is None else f"'{day}'" for day in (first, last))
        + ")"
        for cluster_id, (rank, label, query, mails, first, last, *_) in CLUSTERS.items()
    )
    terms = ", ".join(
        f"({cluster_id}, {rank}, {k}, {weight})"
        for cluster_id, (*_, weighted, _) in CLUSTERS.items()
        for rank, (k, weight) in enumerate(weighted, 1)
    )
    months = ", ".join(
        f"({cluster_id}, DATE '{month}', {mails})"
        for cluster_id, (*_, counted) in CLUSTERS.items()
        for month, mails in counted
    )
    return [
        *CLEAR,  # what the import's topics phase stored
        # the vocabulary: every lexeme of letters in at least three mails that are no duplicates
        """INSERT INTO topic_term (lexeme, label, mails)
            SELECT lexeme, initcap(lexeme), count(*)
            FROM mail, unnest(tsvector_to_array(tsv)) AS lexeme
            WHERE is_duplicate_of IS NULL AND lexeme ~ '^[[:alpha:]]{3,40}$'
            GROUP BY lexeme HAVING count(*) >= 3""",
        f"""INSERT INTO topic_state (id, fingerprint, computed_at, mails, terms, clusters, seconds)
            SELECT 1, 'test', '{COMPUTED_AT}',
                (SELECT count(*) FROM mail WHERE is_duplicate_of IS NULL), count(*),
                {len(CLUSTERS)}, 1.5
            FROM topic_term""",
        f"CREATE TEMP TABLE pick AS {PICKS}",
        """UPDATE topic_term SET themes = '{spenden,gewalt}'
            WHERE id = (SELECT id FROM pick WHERE k = 1)""",
        f"INSERT INTO topic_period (unit, period_start, mails) VALUES {periods}",
        # the scores are figures of the API (keyness), not of the table
        f"""INSERT INTO topic_period_term (unit, period_start, rank, term_id, mails, score)
            SELECT t.unit, t.start, t.rank, pick.id, t.a, 0
            FROM (VALUES {ranked}) AS t(unit, start, rank, k, a) JOIN pick ON pick.k = t.k""",
        f"""INSERT INTO topic_cluster (id, rank, label, query, mails, first_date, last_date)
            OVERRIDING SYSTEM VALUE VALUES {clusters}""",
        f"""INSERT INTO topic_cluster_term (cluster_id, rank, term_id, weight)
            SELECT t.cluster_id, t.rank, pick.id, t.weight
            FROM (VALUES {terms}) AS t(cluster_id, rank, k, weight) JOIN pick ON pick.k = t.k""",
        f"INSERT INTO topic_cluster_month (cluster_id, month, mails) VALUES {months}",
        "ANALYZE",
    ]


@pytest.fixture(scope="session")
def topic_database_url(database_server_url: str, imported_database_url: str) -> Iterator[str]:
    """A copy of the imported archive with the topics of _topic_rows. Read only."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        asyncio.run(_execute(url, _topic_rows()))
        yield url


@pytest.fixture
async def topic_client(
    topic_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings(topic_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


async def picks(url: str) -> dict[int, Any]:
    return {row.k: row for row in await rows(url, PICKS)}


async def archive_mails(url: str) -> int:
    found = await rows(url, "SELECT count(*) AS n FROM mail WHERE is_duplicate_of IS NULL")
    total: int = found[0].n
    return total


def term(row: Any, a: float, n: float, total: int) -> Json:
    """A term as the API shows it, from its row of topic_term."""
    found = keyness(a, n, row.mails, total)
    assert found is not None, row.lexeme
    return {
        "term": row.lexeme,
        "label": row.label,
        "mails": found.mails,
        "share": found.share,
        "rest_share": found.rest_share,
        "ratio": found.ratio,
        "score": found.score,
        "themes": row.themes,
    }


async def state(url: str) -> Json:
    found = await rows(url, "SELECT count(*) AS n FROM topic_term")
    return {
        "computed_at": COMPUTED_AT,
        "mails": await archive_mails(url),
        "terms": found[0].n,
        "clusters": len(CLUSTERS),
    }


# Periods -------------------------------------------------------------------------------------


async def expected_periods(
    url: str,
    unit: Unit,
    limit: int = TOPIC_TERMS,
    first: date = date.min,
    last: date = date.max,
) -> Json:
    """The periods of PERIODS overlapping first to last, newest first."""
    picked, total = await picks(url), await archive_mails(url)
    found = []
    for (each, start), (mails, ranked) in sorted(PERIODS.items(), reverse=True):
        end = period_end(start, unit)
        if each != unit or end < first or start > last:
            continue
        terms = [term(picked[k], a, mails, total) for k, a in ranked[:limit]]
        found.append(
            {"start": start.isoformat(), "end": end.isoformat(), "mails": mails, "terms": terms}
        )
    return {"state": await state(url), "unit": unit, "periods": found}


@pytest.mark.parametrize("unit", ["month", "quarter", "year"])
async def test_periods_newest_first_with_the_figures_of_keyness(
    topic_client: httpx.AsyncClient, topic_database_url: str, unit: Unit
) -> None:
    found = await get(topic_client, "/api/topics/periods", [("unit", unit)])
    assert found == await expected_periods(topic_database_url, unit)


async def test_periods_default_to_months(
    topic_client: httpx.AsyncClient, topic_database_url: str
) -> None:
    found = await get(topic_client, "/api/topics/periods")
    assert found == await expected_periods(topic_database_url, "month")
    assert [period["end"] for period in found["periods"]] == [
        "2024-03-31",
        "2024-02-29",
        "2024-01-31",
        "2023-12-31",
    ]
    assert found["periods"][0]["terms"] == []
    assert found["periods"][2]["terms"][0]["themes"] == ["spenden", "gewalt"]


@pytest.mark.parametrize(
    ("unit", "params", "first", "last"),
    [
        (
            "month",
            [("date_from", "2024-01-15"), ("date_to", "2024-02-10")],
            "2024-01-15",
            "2024-02-10",
        ),
        ("month", [("date_from", "2024-02-01")], "2024-02-01", None),
        ("month", [("date_to", "2023-12-31")], None, "2023-12-31"),
        (
            "quarter",
            [("date_from", "2023-11-20"), ("date_to", "2023-11-20")],
            "2023-11-20",
            "2023-11-20",
        ),
        ("year", [("date_from", "2025-01-01")], "2025-01-01", None),
    ],
)
async def test_periods_overlapping_the_days(
    topic_client: httpx.AsyncClient,
    topic_database_url: str,
    unit: Unit,
    params: Params,
    first: str | None,
    last: str | None,
) -> None:
    found = await get(topic_client, "/api/topics/periods", [("unit", unit), *params])
    bounds = (
        date.fromisoformat(first) if first else date.min,
        date.fromisoformat(last) if last else date.max,
    )
    assert found == await expected_periods(topic_database_url, unit, TOPIC_TERMS, *bounds)


async def test_periods_with_fewer_terms(
    topic_client: httpx.AsyncClient, topic_database_url: str
) -> None:
    found = await get(topic_client, "/api/topics/periods", [("limit", "1")])
    assert found == await expected_periods(topic_database_url, "month", 1)
    assert [len(period["terms"]) for period in found["periods"]] == [0, 1, 1, 1]


async def test_period_parameters_are_checked(topic_client: httpx.AsyncClient) -> None:
    for params in ([("unit", "week")], [("limit", "0")], [("limit", "31")]):
        await get(topic_client, "/api/topics/periods", params, status=422)


# Terms of a selection ------------------------------------------------------------------------


async def expected_terms(
    url: str,
    where: str,
    limit: int = TOPIC_SELECTION_TERMS,
    sample: int | None = None,
    **params: Any,
) -> Json:
    """The terms of the mails that are no duplicates matching where (SQL on mail), counted over
    the first `sample` of them by hashint8(id) when there are more."""
    selection = f"SELECT id FROM mail WHERE is_duplicate_of IS NULL AND ({where})"
    mails = len(await rows(url, selection, **params))
    counted = mails if sample is None else min(sample, mails)
    sampled = f"{selection} ORDER BY hashint8(id), id LIMIT {counted}"
    counts = await rows(
        url,
        "SELECT t.lexeme, t.label, t.mails, t.themes, c.a FROM (SELECT lexeme, count(*) AS a"
        " FROM mail, unnest(tsvector_to_array(ts_filter(tsv, '{a,b,c}'))) AS lexeme"
        f" WHERE id IN ({sampled})"
        " GROUP BY lexeme HAVING count(*) >= 3) c JOIN topic_term t ON t.lexeme = c.lexeme",
        **params,
    )
    total = await archive_mails(url)
    standing: list[Json] = []
    common: list[Json] = []
    for row in counts:
        found = keyness(row.a * mails / counted, mails, row.mails, total)
        if found is not None:
            (common if found.common else standing).append(
                term(row, row.a * mails / counted, mails, total)
            )
    standing.sort(key=lambda each: (-each["score"], each["label"], each["term"]))
    common.sort(key=lambda each: (-each["mails"], each["label"], each["term"]))
    return {
        "state": await state(url),
        "mails": mails,
        "counted": counted,
        "sampled": counted < mails,
        "terms": standing[:limit],
        "common": common[:limit],
        "timed_out": False,
    }


async def lexeme_of(url: str, word: str) -> str:
    found = await rows(
        url, "SELECT (tsvector_to_array(to_tsvector('german', :w)))[1] AS lexeme", w=word
    )
    lexeme: str = found[0].lexeme
    return lexeme


async def test_the_terms_of_a_person(
    topic_client: httpx.AsyncClient, topic_database_url: str
) -> None:
    url = topic_database_url
    (person,) = await busiest(url)
    found = await get(topic_client, "/api/topics/terms", [("person", str(person))])
    assert found == await expected_terms(url, takes_part(MEMBER), p=person)
    assert found["terms"] and not found["sampled"]
    sent = await get(
        topic_client, "/api/topics/terms", [("person", str(person)), ("person_role", "sent")]
    )
    assert sent == await expected_terms(url, takes_part(MEMBER, "pa.role = 'from'"), p=person)
    assert sent["mails"] < found["mails"]


async def test_the_terms_of_a_search_list_the_word_as_common(
    topic_client: httpx.AsyncClient, topic_database_url: str
) -> None:
    url = topic_database_url
    word = await common_word(url)
    found = await get(topic_client, "/api/topics/terms", [("q", word), ("limit", "5")])
    assert found == await expected_terms(url, FULL_TEXT, 5, w=word)
    assert await lexeme_of(url, word) in [each["term"] for each in found["common"]]
    assert len(found["terms"]) == 5


async def test_the_terms_of_a_period(
    topic_client: httpx.AsyncClient, topic_database_url: str
) -> None:
    url = topic_database_url
    days = await rows(
        url,
        "SELECT (min(date_utc) AT TIME ZONE 'UTC')::date AS first,"
        " (percentile_disc(0.2) WITHIN GROUP (ORDER BY date_utc) AT TIME ZONE 'UTC')::date AS last"
        " FROM mail",
    )
    first, last = days[0].first, days[0].last
    params = [("date_from", first.isoformat()), ("date_to", last.isoformat())]
    found = await get(topic_client, "/api/topics/terms", params)
    where = "(date_utc AT TIME ZONE 'UTC')::date BETWEEN :first AND :last"
    assert found == await expected_terms(url, where, first=first, last=last)
    assert found["mails"] > 20


@pytest.mark.parametrize("params", [[], [("hide_duplicates", "true")], [("q", "  ")]])
async def test_nothing_stands_out_in_the_whole_archive(
    topic_client: httpx.AsyncClient, topic_database_url: str, params: Params
) -> None:
    found = await get(topic_client, "/api/topics/terms", params)
    assert found == {
        "state": await state(topic_database_url),
        "mails": await archive_mails(topic_database_url),
        "counted": 0,
        "sampled": False,
        "terms": [],
        "common": [],
        "timed_out": False,
    }


async def test_a_large_selection_is_counted_over_a_sample(
    topic_client: httpx.AsyncClient, topic_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = topic_database_url
    monkeypatch.setattr(topics, "TOPIC_SAMPLE", 40)
    (person,) = await busiest(url)
    params = [("person", str(person))]
    found = await get(topic_client, "/api/topics/terms", params)
    assert found == await expected_terms(url, takes_part(MEMBER), sample=40, p=person)
    assert (found["counted"], found["sampled"]) == (40, True)
    assert found["mails"] > 40
    assert await get(topic_client, "/api/topics/terms", params) == found


async def test_without_the_count_the_sample_is_the_scope(
    topic_client: httpx.AsyncClient, topic_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = topic_database_url

    async def canceled(*_: Any) -> None:
        return None

    monkeypatch.setattr(topics, "_unless_canceled", canceled)  # the count of the selection
    (person,) = await busiest(url)
    params = [("person", str(person))]
    # A sample of all the selection's mails counts them.
    found = await get(topic_client, "/api/topics/terms", params)
    assert found == await expected_terms(url, takes_part(MEMBER), p=person)
    # A sample of some: its terms against the rest of the archive, the selection's other mails
    # included.
    monkeypatch.setattr(topics, "TOPIC_SAMPLE", 40)
    found = await get(topic_client, "/api/topics/terms", params)
    sample = await rows(
        url,
        f"SELECT id FROM mail WHERE is_duplicate_of IS NULL AND {takes_part(MEMBER)}"
        " ORDER BY hashint8(id), id LIMIT 40",
        p=person,
    )
    scope = await expected_terms(url, "id = ANY(:ids)", ids=[row.id for row in sample])
    assert found == {**scope, "mails": None, "sampled": True}


async def test_terms_run_out_of_time(
    topic_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    url = topic_database_url
    settings = api_settings(url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(update={"api_count_timeout": 0.3})
    (person,) = await busiest(url)
    params = [("person", str(person))]
    expected = await expected_terms(url, takes_part(MEMBER), p=person)
    nothing = {**expected, "counted": 0, "terms": [], "common": [], "timed_out": True}
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async for client in _client(settings):
            async with engine.connect() as other:
                # The counting of the terms joins topic_term: it waits; the mails are counted.
                await other.execute(text("LOCK TABLE topic_term IN ACCESS EXCLUSIVE MODE"))
                assert await get(client, "/api/topics/terms", params) == nothing
                await other.rollback()
                # Now the count and the sample wait too.
                await other.execute(text("LOCK TABLE mail IN ACCESS EXCLUSIVE MODE"))
                assert await get(client, "/api/topics/terms", params) == {**nothing, "mails": None}
                # The whole archive and the stored periods do not read mail.
                assert (await get(client, "/api/topics/terms"))["timed_out"] is False
                assert (await get(client, "/api/topics/periods"))["periods"]
                await other.rollback()
            assert await get(client, "/api/topics/terms", params) == expected
    finally:
        await engine.dispose()


async def test_terms_take_the_list_errors(topic_client: httpx.AsyncClient) -> None:
    error = await get(topic_client, "/api/topics/terms", [("q", "dkim:maybe")], status=400)
    assert error["detail"]["code"] == "invalid_query"
    error = await get(topic_client, "/api/topics/terms", [("person_role", "sent")], status=400)
    assert error["detail"]["code"] == "invalid_filter"
    await get(topic_client, "/api/topics/terms", [("limit", "0")], status=422)
    await get(topic_client, "/api/topics/terms", [("limit", "101")], status=422)


# Clusters ------------------------------------------------------------------------------------


async def test_clusters_by_rank_with_their_terms_and_months(
    topic_client: httpx.AsyncClient, topic_database_url: str
) -> None:
    picked = await picks(topic_database_url)
    expected = []
    for cluster_id, (_, label, query, mails, first, last, weighted, months) in sorted(
        CLUSTERS.items(), key=lambda item: item[1][0]
    ):
        terms = [
            {
                "term": picked[k].lexeme,
                "label": picked[k].label,
                "mails": picked[k].mails,
                "weight": weight,
                "themes": picked[k].themes,
            }
            for k, weight in weighted
        ]
        expected.append(
            {
                "id": cluster_id,
                "label": label,
                "query": query,
                "mails": mails,
                "first_date": first,
                "last_date": last,
                "terms": terms,
                "months": [{"month": month, "mails": count} for month, count in months],
            }
        )
    found = await get(topic_client, "/api/topics/clusters")
    assert found == {"state": await state(topic_database_url), "clusters": expected}
    assert [cluster["id"] for cluster in found["clusters"]] == [3, 7, 5]


# Before the first computation ----------------------------------------------------------------


async def test_before_the_topics_are_computed_everything_is_empty(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    url = mutable_database_url
    await _execute(url, CLEAR)
    nothing = {"computed_at": None, "mails": 0, "terms": 0, "clusters": 0}
    (person,) = await busiest(url)
    mails = len(
        await rows(
            url,
            f"SELECT id FROM mail WHERE is_duplicate_of IS NULL AND {takes_part(MEMBER)}",
            p=person,
        )
    )
    settings = api_settings(url, generated_archive, tmp_path / "no-frontend")
    async for client in _client(settings):
        periods = await get(client, "/api/topics/periods", [("unit", "year")])
        assert periods == {"state": nothing, "unit": "year", "periods": []}
        assert await get(client, "/api/topics/clusters") == {"state": nothing, "clusters": []}
        empty = {"state": nothing, "counted": 0, "sampled": False, "terms": [], "common": []}
        assert await get(client, "/api/topics/terms") == {**empty, "mails": 0, "timed_out": False}
        selection = await get(client, "/api/topics/terms", [("person", str(person))])
        assert selection == {**empty, "mails": mails, "timed_out": False}

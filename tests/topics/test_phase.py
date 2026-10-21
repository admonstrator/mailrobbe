"""The topics phase (D141 to D143, D146) on the hand-made SAMPLE (tests/topics/conftest.py): when
it computes, the vocabulary and its labels, the periods, the clusters as stored, the replacement
in one transaction, and stops."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import migrate, themes
from mailrobbe.jobrun import Steps
from mailrobbe.themes import Theme
from mailrobbe.topics import clusters, labels, phase
from mailrobbe.topics.keyness import keyness
from mailrobbe.topics.labels import Progress
from mailrobbe.topics.model import UNITS, Cluster, Term, period_start
from tests.topics.conftest import (
    SAMPLE,
    SAMPLE_IGNORE,
    SAMPLE_THEMES,
    SAMPLE_TOTAL,
    M,
    compute,
    fingerprint_now,
    insert_mails,
    rows,
    stored,
    value,
)

pytestmark = pytest.mark.db


async def terms_of(url: str) -> dict[str, tuple[str, int, list[str]]]:
    """lexeme -> (label, mails, themes) of the stored vocabulary."""
    found = await rows(url, "SELECT lexeme, label, mails, themes FROM topic_term")
    return {lexeme: (label, mails, themes) for lexeme, label, mails, themes in found}


async def period_terms(url: str, unit: str, start: date) -> list[tuple[str, int, float]]:
    """(lexeme, a, G2) of a period, by rank."""
    return await rows(
        url,
        """SELECT t.lexeme, p.mails, p.score FROM topic_period_term p
           JOIN topic_term t ON t.id = p.term_id
           WHERE p.unit = :unit AND p.period_start = :start ORDER BY p.rank""",
        unit=unit,
        start=start,
    )


async def mails_holding(url: str, lexeme: str) -> int:
    """Mails, duplicates included, whose tsv holds the lexeme: it was there to be left out."""
    return int(
        await value(
            url,
            "SELECT count(*) FROM mail WHERE tsv @@ CAST(quote_literal(:lexeme) AS tsquery)",
            lexeme=lexeme,
        )
    )


# When the phase computes --------------------------------------------------------------------------


async def test_waiting_until_computed_and_again_after_a_change(
    sample_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = sample_url
    first = await fingerprint_now(url)
    assert first is not None and len(first) == 64  # no topic_state yet
    assert await fingerprint_now(url) == first  # the same archive, the same fingerprint
    assert await compute(url) is not None
    assert await fingerprint_now(url) is None  # nothing to do

    monkeypatch.setattr(themes, "load_topic_ignore", lambda: (*SAMPLE_IGNORE, "Verein"))
    edited = await fingerprint_now(url)
    assert edited not in (None, first)
    monkeypatch.setattr(themes, "load_topic_ignore", lambda: SAMPLE_IGNORE)
    more = (*SAMPLE_THEMES, Theme("neu", "Neu", "red", "", ("Umzug", "zwei Worte"), ()))
    monkeypatch.setattr(themes, "load_themes", lambda: more)
    assert await fingerprint_now(url) not in (None, first, edited)
    phrases = (*SAMPLE_THEMES, Theme("neu", "Neu", "red", "", ("zwei Worte",), ()))
    monkeypatch.setattr(themes, "load_themes", lambda: phrases)
    assert await fingerprint_now(url) is None  # a phrase gives no term, so it changes nothing
    monkeypatch.setattr(themes, "load_themes", lambda: SAMPLE_THEMES)

    await insert_mails(url, [M("Umzug Verein", date(2024, 4, 2))], path="later.mbox")
    later = await fingerprint_now(url)
    assert later not in (None, first, edited)
    assert await compute(url) is not None
    assert await fingerprint_now(url) is None


async def test_an_empty_archive_is_computed_once(
    empty_database_url: str, sample_themes: None
) -> None:
    url = empty_database_url
    await asyncio.to_thread(migrate.upgrade, "head", url)
    result = await compute(url)
    assert result is not None and (result.terms, result.periods, result.clusters) == (0, 0, 0)
    assert await rows(url, "SELECT id, mails, terms, clusters FROM topic_state") == [(1, 0, 0, 0)]
    assert await fingerprint_now(url) is None


# The vocabulary (D141) ----------------------------------------------------------------------------


async def test_the_vocabulary_follows_its_rules(computed_url: str) -> None:
    url = computed_url
    terms = await terms_of(url)
    left_out = {
        "4711": 3,  # a number
        "covid19": 3,  # digits in it
        "kassenwart@verein.example": 3,  # an address
        "verein.example": 3,  # a host
        "about": 3,  # English stop words
        "which": 3,
        "besprech": 3,  # "Besprechungen", the stem of the ignored "Besprechung"
        "wilhelmin": SAMPLE_TOTAL + 1,  # the names of the correspondents
        "oberhub": 3,
        "zwillingswort": 3,  # in two mails and a duplicate of one of them
    }
    for lexeme, mails in left_out.items():
        assert await mails_holding(url, lexeme) == mails, lexeme
        assert lexeme not in terms, lexeme
    assert terms["brunhild"] == ("Brunhilde", 3, [])  # only mentioned; one mail is undated
    # The stem of "Paula Spender", a name, is the stem of single-word theme terms ("Spende",
    # "Spenden"), with the themes in their file order; "in bar" is a phrase, not a word.
    assert terms["spend"] == ("Spenden", 6, ["spenden", "geld"])
    assert terms["kass"] == ("Kasse", 4, ["geld"])
    assert set(terms) == {
        "brunhild", "frau", "jahresmotto", "kass", "kassenwart", "kopi", "numm", "ruckmeld",
        "schreibt", "sommerf", "spend", "umzug", "verein", "vereinsnachricht",
    }  # fmt: skip
    assert all(mails >= 3 for _, mails, _ in terms.values())
    assert await value(url, "SELECT terms FROM topic_state") == len(terms)


async def test_labels_are_the_spellings_written_most(computed_url: str) -> None:
    terms = await terms_of(computed_url)
    assert terms["ruckmeld"][0] == "Rückmeldung"  # twice, "Rückmeldungen" once
    assert terms["sommerf"][0] == "Sommerfest"
    assert terms["spend"][0] == "Spenden"  # four times, "Spende" twice
    assert terms["kass"][0] == "Kasse"  # as often as "kasse": capitals first
    # "kassenwart" is written four times in each of its mails, but in addresses and links.
    assert terms["kassenwart"][0] == "Kassenwart"


# Periods (D142, D143) -----------------------------------------------------------------------------


async def test_every_period_with_mails_and_its_mails(computed_url: str) -> None:
    expected: dict[tuple[str, date], int] = {}
    for mail in SAMPLE:
        if mail.day is not None and mail.duplicate_of is None:
            for unit in UNITS:
                key = (unit, period_start(mail.day, unit))
                expected[key] = expected.get(key, 0) + 1
    found = await rows(computed_url, "SELECT unit, period_start, mails FROM topic_period")
    assert {(unit, start): mails for unit, start, mails in found} == expected
    assert len(expected) == 15 + 5 + 2
    assert expected["month", date(2023, 7, 1)] == 6
    assert expected["year", date(2023, 1, 1)] == 39
    assert await value(computed_url, "SELECT mails FROM topic_state") == SAMPLE_TOTAL == 49


async def test_a_word_of_one_month_ranks_first_there(computed_url: str) -> None:
    url = computed_url
    total = SAMPLE_TOTAL
    # Sommerfest: in the six July mails only.
    july = await period_terms(url, "month", date(2023, 7, 1))
    assert [(lexeme, a) for lexeme, a, _ in july] == [("sommerf", 6)]
    figures = keyness(6, 6, 6, total)
    assert figures is not None and july[0][2] == pytest.approx(figures.score, rel=1e-6)
    third = await period_terms(url, "quarter", date(2023, 7, 1))  # 12 mails
    figures = keyness(6, 12, 6, total)
    assert figures is not None and third[0][:2] == ("sommerf", 6)
    assert third[0][2] == pytest.approx(figures.score, rel=1e-6)
    assert keyness(6, 39, 6, total) is None  # in a year of 39 mails it does not stand out
    assert await period_terms(url, "year", date(2023, 1, 1)) == []
    for month in (1, 6, 8, 12):  # months with nothing of their own
        assert await period_terms(url, "month", date(2023, month, 1)) == []


async def test_a_word_of_one_year_in_its_quarter_and_year(computed_url: str) -> None:
    url = computed_url
    figures = keyness(9, 9, 9, SAMPLE_TOTAL)
    assert figures is not None
    for unit in ("quarter", "year"):
        [(lexeme, a, score)] = await period_terms(url, unit, date(2024, 1, 1))
        assert (lexeme, a) == ("umzug", 9) and score == pytest.approx(figures.score, rel=1e-6)
    assert keyness(3, 3, 9, SAMPLE_TOTAL) is None  # three of its nine mails in each month
    assert await period_terms(url, "month", date(2024, 1, 1)) == []


async def test_common_terms_are_not_kept_for_periods(computed_url: str) -> None:
    # Jahresmotto is in every mail of 2023: it stands out there, but in all of its mails.
    figures = keyness(39, 39, 39, SAMPLE_TOTAL)
    assert figures is not None and figures.common
    assert await period_terms(computed_url, "year", date(2023, 1, 1)) == []


# Clusters (D145) ----------------------------------------------------------------------------------

TWO_CLUSTERS = [
    Cluster(
        terms=(("spend", 2.5), ("kass", 1.25), ("kassenwart", 1.0), ("ruckmeld", 0.75)),
        mails=12,
        first_date=datetime(2023, 1, 3, 12, tzinfo=UTC),
        last_date=datetime(2023, 12, 3, 12, tzinfo=UTC),
        months=((date(2023, 1, 1), 2), (date(2023, 3, 1), 4), (date(2023, 12, 1), 6)),
    ),
    Cluster(
        terms=(("umzug", 1.5), ("sommerf", 1.5), ("brunhild", 0.5), ("frau", 0.5), ("numm", 0.25)),
        mails=5,
        first_date=None,
        last_date=None,
        months=(),
    ),
]


async def test_clusters_are_stored_in_their_order(
    sample_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[dict[str, Term], int]] = []

    async def two_clusters(
        session: AsyncSession, vocabulary: Mapping[str, Term], total: int
    ) -> list[Cluster]:
        calls.append((dict(vocabulary), total))
        return TWO_CLUSTERS

    monkeypatch.setattr(clusters, "find_clusters", two_clusters)
    result = await compute(sample_url)
    assert result is not None and (result.clusters, result.terms) == (2, 14)
    [(vocabulary, total)] = calls
    assert total == SAMPLE_TOTAL
    assert vocabulary["spend"] == Term("spend", "Spenden", 6, ("spenden", "geld"))
    assert vocabulary["umzug"] == Term("umzug", "Umzug", 9)

    url = sample_url
    found = await rows(
        url,
        """SELECT rank, label, query, mails, first_date, last_date FROM topic_cluster
           ORDER BY rank""",
    )
    assert found == [
        (
            1,
            "Spenden, Kasse, Kassenwart",
            "Spenden or Kasse or Kassenwart or Rückmeldung",
            12,
            datetime(2023, 1, 3, 12, tzinfo=UTC),
            datetime(2023, 12, 3, 12, tzinfo=UTC),
        ),
        (2, "Umzug, Sommerfest, Brunhilde", "Umzug or Sommerfest or Brunhilde or Frau or Nummer", 5,
         None, None),
    ]  # fmt: skip
    cluster_terms = await rows(
        url,
        """SELECT c.rank, ct.rank, t.lexeme, ct.weight FROM topic_cluster_term ct
           JOIN topic_cluster c ON c.id = ct.cluster_id JOIN topic_term t ON t.id = ct.term_id
           ORDER BY c.rank, ct.rank""",
    )
    assert cluster_terms == [
        (rank, term_rank, lexeme, weight)
        for rank, cluster in enumerate(TWO_CLUSTERS, 1)
        for term_rank, (lexeme, weight) in enumerate(cluster.terms, 1)
    ]
    months = await rows(
        url,
        """SELECT c.rank, m.month, m.mails FROM topic_cluster_month m
           JOIN topic_cluster c ON c.id = m.cluster_id ORDER BY c.rank, m.month""",
    )
    assert months == [(1, month, mails) for month, mails in TWO_CLUSTERS[0].months]
    assert await value(url, "SELECT clusters FROM topic_state") == 2


# The replacement and stops (D146) -----------------------------------------------------------------

LATER = [M("Umzug Verein Ostereier", date(2024, 4, 2 + day)) for day in range(3)]


async def test_a_new_computation_replaces_every_stored_result(
    computed_copy_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = computed_copy_url
    monkeypatch.setattr(clusters, "find_clusters", _first_cluster)
    # Once more with a cluster, so that one is replaced too.
    assert await compute(url, fingerprint="with a cluster") is not None
    before = await stored(url)
    assert before["clusters"] and before["cluster_terms"] and before["cluster_months"]
    await insert_mails(url, LATER, path="later.mbox")
    result = await compute(url)
    after = await stored(url)

    assert result is not None and result.terms == len(after["terms"]) == 15
    assert result.periods == len(after["periods"]) == 22 + 2  # April 2024 and its quarter
    [(state_id, fingerprint, computed_at, mails)] = after["state"]
    [(_, old_fingerprint, old_computed_at, _)] = before["state"]
    assert (state_id, mails) == (1, SAMPLE_TOTAL + 3)
    assert fingerprint != old_fingerprint and computed_at > old_computed_at
    assert await fingerprint_now(url) is None
    terms = await terms_of(url)
    assert terms["osterei"] == ("Ostereier", 3, [])
    assert terms["umzug"][1] == 12
    old_ids = {row[0] for row in before["terms"]}
    assert not old_ids & {row[0] for row in after["terms"]}  # every row is new
    old_clusters = {row[0] for row in before["clusters"]}
    assert not old_clusters & {row[0] for row in after["clusters"]}
    assert {row[0] for row in after["cluster_terms"]} == {row[0] for row in after["clusters"]}
    assert await period_terms(url, "month", date(2024, 4, 1)) != []


async def _first_cluster(
    session: AsyncSession, vocabulary: Mapping[str, Term], total: int
) -> list[Cluster]:
    return TWO_CLUSTERS[:1]


async def test_a_stop_before_the_first_step_ends_keeps_the_stored_topics(
    computed_copy_url: str,
) -> None:
    url = computed_copy_url
    before = await stored(url)
    await insert_mails(url, LATER, path="later.mbox")
    waiting = await fingerprint_now(url)
    stop = asyncio.Event()
    stop.set()
    steps = Steps(stop)
    assert await compute(url, stop=stop, steps=steps) is None
    assert await stored(url) == before
    assert await fingerprint_now(url) == waiting  # the next import computes again
    statuses = {step.key: step.status for step in steps.snapshot()}
    assert statuses == {"topic_terms": "done"}  # the others not even started


async def test_a_stop_during_the_labels_keeps_the_stored_topics(
    computed_copy_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = computed_copy_url
    before = await stored(url)
    await insert_mails(url, LATER, path="later.mbox")
    stop = asyncio.Event()
    monkeypatch.setattr(labels, "BATCH_MAILS", 10)
    read_labels = labels.read_labels

    async def stopping(
        session: AsyncSession, terms: Any, stop: asyncio.Event, step: Progress
    ) -> tuple[dict[str, str], int] | None:
        class Stopping:
            def advance(self, count: int = 1) -> None:
                step.advance(count)
                stop.set()  # after the first batch of ten mails

        return await read_labels(session, terms, stop, Stopping())

    monkeypatch.setattr(phase, "read_labels", stopping)
    steps = Steps(stop)
    plan = list(phase.STEPS)
    steps.plan(*plan)
    assert await compute(url, stop=stop, steps=steps) is None
    assert await stored(url) == before
    snapshot = {step.key: step for step in steps.snapshot()}
    assert [snapshot[key].status for key in plan] == ["done", "stopped", "waiting", "waiting"]
    labels_step = snapshot["topic_labels"]
    assert (labels_step.unit, labels_step.done, labels_step.total) == ("mails", 10, 52)


async def test_a_stop_in_the_last_step_keeps_the_stored_topics(
    computed_copy_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = computed_copy_url
    before = await stored(url)
    await insert_mails(url, LATER, path="later.mbox")
    stop = asyncio.Event()

    async def stopping(
        session: AsyncSession, vocabulary: Mapping[str, Term], total: int
    ) -> list[Cluster]:
        stop.set()
        return TWO_CLUSTERS

    monkeypatch.setattr(clusters, "find_clusters", stopping)
    assert await compute(url, stop=stop) is None
    assert await stored(url) == before


async def test_the_steps_of_a_computation(sample_url: str) -> None:
    steps = Steps()
    steps.plan(*phase.STEPS)
    result = await compute(sample_url, steps=steps)
    assert result is not None and result.seconds > 0
    snapshot = steps.snapshot()
    assert [(step.key, step.status) for step in snapshot] == [(key, "done") for key in phase.STEPS]
    units = {step.key: (step.unit, step.done, step.total) for step in snapshot}
    assert units == {
        "topic_terms": (None, 0, None),  # one long statement: the database's activity shows
        "topic_labels": ("mails", SAMPLE_TOTAL, SAMPLE_TOTAL),
        "topic_periods": (None, 0, None),
        "topic_clusters": (None, 0, None),
    }

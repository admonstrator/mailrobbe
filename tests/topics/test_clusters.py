"""Clusters (D145): the candidates, links and groups on their own, then find_clusters on a small
archive written into the test database: two word fields, words that meet only in mails with too
many terms or in duplicates, and a word of a field also found alone."""

import math
from array import array
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.db.models import Mail, MboxFile
from mailrobbe.topics import clusters
from mailrobbe.topics.clusters import (
    _offsets,
    candidate_terms,
    find_clusters,
    find_links,
    strongest_terms,
)
from mailrobbe.topics.model import Cluster, Term


def npmi(both: int, a: int, b: int, total: int) -> float:
    return math.log(both * total / (a * b)) / -math.log(both / total)


def vocabulary(**mails: int) -> dict[str, Term]:
    return {
        lexeme: Term(lexeme=lexeme, label=lexeme.title(), mails=n) for lexeme, n in mails.items()
    }


def triangle(size: int, counts: dict[tuple[int, int], int]) -> array[int]:
    pairs = array("i", [0]) * (size * (size - 1) // 2)
    offsets = _offsets(size)
    for (first, second), count in counts.items():
        pairs[offsets[first] + second] = count
    return pairs


# Candidates, links and groups ----------------------------------------------------------------


def test_candidates_are_the_terms_with_most_mails_within_the_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1,000 mails: a candidate is in 10 to 50 of them.
    terms = vocabulary(selten=9, knapp=10, mittel=30, auch=30, oft=50, zuoft=51)
    assert candidate_terms(terms, 1_000) == ["oft", "auch", "mittel", "knapp"]
    monkeypatch.setattr(clusters, "CLUSTER_CANDIDATES", 2)
    assert candidate_terms(terms, 1_000) == ["oft", "auch"]


def test_the_triangle_has_a_place_for_every_pair() -> None:
    size = 5
    offsets = _offsets(size)
    places = [offsets[i] + j for i in range(size) for j in range(i + 1, size)]
    assert places == list(range(size * (size - 1) // 2))


def test_links_need_enough_mails_and_npmi() -> None:
    # Four candidates of an archive of 1,000 mails, in 20, 20, 20 and 400 mails.
    mails = [20, 20, 20, 400]
    pairs = triangle(4, {(0, 1): 15, (0, 2): 2, (1, 2): 3, (2, 3): 20, (0, 3): 8})
    links = find_links(pairs, mails, 1_000)
    assert [(i, j) for i, j, _ in links] == [(0, 1), (1, 2)]
    assert links[0][2] == pytest.approx(npmi(15, 20, 20, 1_000))
    assert links[1][2] == pytest.approx(npmi(3, 20, 20, 1_000))
    # (0, 2): two mails only; (2, 3): every mail of the rarer term, but the commoner one is in
    # 40 % of the archive, NPMI 0.25; (0, 3): fewer than chance has it.
    assert npmi(20, 20, 400, 1_000) < 0.3


def test_groups_keep_their_strongest_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = ["a", "b", "c", "d", "e", "f", "g", "h"]
    community = [0, 0, 0, 0, 0, 1, 1, 1]  # the second group has too few terms
    links = [(0, 1, 0.5), (0, 2, 0.5), (1, 2, 0.5), (3, 4, 0.75), (0, 3, 0.25), (5, 6, 1.0)]
    links += [(6, 7, 1.0), (4, 5, 0.75)]  # between the groups: no strength
    assert strongest_terms(candidates, links, community) == [
        (("a", 1.25), ("b", 1.0), ("c", 1.0), ("d", 1.0), ("e", 0.75)),
    ]
    monkeypatch.setattr(clusters, "CLUSTER_TERMS", 3)
    assert strongest_terms(candidates, links, community) == [(("a", 1.25), ("b", 1.0), ("c", 1.0))]


# find_clusters -------------------------------------------------------------------------------

ROCKS = ("basalt", "gneis", "granit", "quarz")  # in every rock mail, as are their lexemes
MARBLE = "marmor"  # in every rock mail and in three of its own
MUSIC = ("fagott", "sopran", "tenor", "trommel", "tuba")
ZOO = ("zebra", "okapi", "lemur", "giraff")  # lexemes; giraff is the stem of Giraffe
TOTAL = 400  # mails that are no duplicates


def at(year: int, month: int, day: int = 10) -> datetime:
    return datetime(year, month, day, 9, 30, tzinfo=UTC)


async def write_archive(session: AsyncSession) -> None:
    """Rock and music mails, zoo words each alone in ten mails and together only in three
    digests (with every other word: fourteen candidates) and in three duplicates, and empty
    mails up to TOTAL."""
    mbox = MboxFile(path="topics.mbox", size_bytes=1)
    session.add(mbox)
    await session.flush()
    rocks = " ".join((*ROCKS, MARBLE))
    texts: list[tuple[str, datetime | None]] = []
    texts += [(rocks, at(2023, 1, day)) for day in range(1, 6)]
    texts += [(rocks, at(2023, 3, day)) for day in range(1, 7)]
    texts += [(rocks, None)]
    texts += [("Marmor", at(2022, 6)) for _ in range(3)]
    texts += [(" ".join(MUSIC), at(2024, 6, day)) for day in range(1, 15)]
    texts += [(word, at(2022, 1)) for word in ("Zebra", "Okapi", "Lemur", "Giraffe") * 10]
    digest = " ".join((rocks, *MUSIC, "Zebra Okapi Lemur Giraffe"))
    texts += [(digest, at(2023, 3, 20)) for _ in range(3)]
    texts += [("", at(2020, 1)) for _ in range(TOTAL - len(texts))]
    mails = [
        Mail(
            mbox_file_id=mbox.id,
            byte_offset=offset,
            byte_length=1,
            raw_sha256=f"{offset:064x}",
            subject=None,
            body_text=body,
            date_utc=date_utc,
        )
        for offset, (body, date_utc) in enumerate(texts)
    ]
    session.add_all(mails)
    await session.flush()
    original = mails[0].id
    session.add_all(
        Mail(
            mbox_file_id=mbox.id,
            byte_offset=TOTAL + number,
            byte_length=1,
            raw_sha256=f"{TOTAL + number:064x}",
            body_text="Zebra Okapi Lemur Giraffe Quarz Fagott",
            date_utc=at(2021, 1),
            is_duplicate_of=original,
        )
        for number in range(3)
    )
    await session.flush()


async def archive_vocabulary(session: AsyncSession) -> dict[str, Term]:
    """Every lexeme of the mails that are no duplicates with its mails, as the phase counts."""
    rows = await session.execute(
        text(
            "SELECT lexeme, count(*) FROM mail, unnest(tsvector_to_array(tsv)) AS lexeme"
            " WHERE is_duplicate_of IS NULL GROUP BY lexeme"
        )
    )
    return {lexeme: Term(lexeme=lexeme, label=lexeme, mails=n) for lexeme, n in rows}


def lexemes(found: list[Cluster]) -> list[list[str]]:
    return [[lexeme for lexeme, _ in cluster.terms] for cluster in found]


def strengths(found: list[Cluster]) -> list[list[float]]:
    return [[strength for _, strength in cluster.terms] for cluster in found]


@pytest.mark.db
async def test_clusters_of_a_small_archive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await write_archive(db_session)
    terms = await archive_vocabulary(db_session)
    assert {lexeme: terms[lexeme].mails for lexeme in (*ROCKS, MARBLE, "tuba", "zebra")} == {
        **dict.fromkeys(ROCKS, 15),
        MARBLE: 18,
        "tuba": 17,
        "zebra": 13,
    }
    monkeypatch.setattr(clusters, "MAIL_MAX_TERMS", 10)  # the digests have fourteen
    found = await find_clusters(db_session, terms, TOTAL)
    # Rocks: twelve rock mails (one undated, in no month), three digests, three of marble.
    assert [(c.mails, c.first_date, c.last_date, c.months) for c in found] == [
        (
            18,
            at(2022, 6),
            at(2023, 3, 20),
            ((date(2022, 6, 1), 3), (date(2023, 1, 1), 5), (date(2023, 3, 1), 9)),
        ),
        (17, at(2023, 3, 20), at(2024, 6, 14), ((date(2023, 3, 1), 3), (date(2024, 6, 1), 14))),
    ]
    assert lexemes(found) == [[*ROCKS, MARBLE], list(MUSIC)]
    rock = 3 * npmi(12, 15, 15, TOTAL) + npmi(12, 15, 18, TOTAL)
    marble = 4 * npmi(12, 15, 18, TOTAL)
    assert strengths(found) == [
        pytest.approx([rock, rock, rock, rock, marble]),
        pytest.approx([4 * npmi(14, 17, 17, TOTAL)] * 5),
    ]
    assert await find_clusters(db_session, terms, TOTAL) == found


@pytest.mark.db
async def test_a_cluster_counts_the_mails_of_its_first_terms(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await write_archive(db_session)
    terms = await archive_vocabulary(db_session)
    monkeypatch.setattr(clusters, "MAIL_MAX_TERMS", 10)
    monkeypatch.setattr(clusters, "CLUSTER_QUERY_TERMS", 4)  # marble, the fifth, is left out
    rock = (await find_clusters(db_session, terms, TOTAL))[1]
    assert lexemes([rock]) == [[*ROCKS, MARBLE]]
    assert (rock.mails, rock.first_date) == (15, at(2023, 1, 1))
    assert rock.months == ((date(2023, 1, 1), 5), (date(2023, 3, 1), 9))


@pytest.mark.db
async def test_mails_with_many_candidates_would_join_words_that_meet_nowhere_else(
    db_session: AsyncSession,
) -> None:
    # With the digests counted, the zoo words meet in three mails, enough for links.
    await write_archive(db_session)
    terms = await archive_vocabulary(db_session)
    found = await find_clusters(db_session, terms, TOTAL)
    assert lexemes(found) == [sorted(ZOO), [*ROCKS, MARBLE], list(MUSIC)]
    assert found[0].mails == 43


@pytest.mark.db
async def test_too_few_candidates_make_no_clusters(db_session: AsyncSession) -> None:
    await write_archive(db_session)
    terms = await archive_vocabulary(db_session)
    # In an archive of 100 mails, every word is in more than 5 % of them.
    assert await find_clusters(db_session, terms, 100) == []
    assert await find_clusters(db_session, {}, TOTAL) == []

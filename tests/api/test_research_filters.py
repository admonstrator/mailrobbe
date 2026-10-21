"""The research filters (review, tag, collection, has_note, flagged) in the mail list, its
summary, the neighbours and the CSV export; the research fields of the list items; the
overview's counts; the themes' searches.

One copy of the imported archive per module gets a research file written in SQL: tags, Akten,
marks and notes on contents picked by their rank in SHA-256 order, a tag on every content of
byte-identical copies, and research data on a content that is in no mail. Expected results come
from SQL on the research tables. WALK_ROWS and CONTENT_ROWS are lowered in some tests, so that
the walk runs out, or no content set is small enough to be listed (filters.resolve_contents).
"""

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api import filters
from mailrobbe.themes import load_themes
from tests.api.conftest import _client, api_settings
from tests.api.test_mails import Params, export, get, ids, listed, page_ids, pages, rows
from tests.conftest import GeneratedArchive, _temporary_database

pytestmark = pytest.mark.db

GONE = "f" * 64  # a content that is in no mail of the archive
RESEARCH_FILE = [
    """CREATE TEMP TABLE content AS
        SELECT raw_sha256 AS sha, row_number() OVER (ORDER BY raw_sha256) AS n
        FROM (SELECT DISTINCT raw_sha256 FROM mail) contents""",
    """INSERT INTO tag (id, name, color) OVERRIDING SYSTEM VALUE
        VALUES (1, 'Rar', 'red'), (2, 'häufig', 'blue'), (3, 'Leer', 'gray')""",
    f"""INSERT INTO mail_tag (tag_id, mail_sha256)
        SELECT 1, sha FROM content WHERE n IN (5, 50, 500)
        UNION SELECT 1, raw_sha256 FROM mail GROUP BY raw_sha256 HAVING count(*) > 1
        UNION SELECT 2, sha FROM content WHERE n % 7 = 0
        UNION SELECT 2, '{GONE}'""",
    """INSERT INTO collection (id, name) OVERRIDING SYSTEM VALUE
        VALUES (1, 'Akte A'), (2, 'Akte B')""",
    f"""INSERT INTO collection_mail (collection_id, mail_sha256)
        SELECT 1, sha FROM content WHERE n % 11 = 0 UNION SELECT 1, '{GONE}'""",
    f"""INSERT INTO mail_mark (mail_sha256, flagged, review)
        SELECT sha, n % 9 = 0,
               (CASE WHEN n % 17 = 0 THEN 'irrelevant' WHEN n % 13 = 0 THEN 'relevant'
                     WHEN n % 5 = 0 THEN 'seen' END)::review_status
        FROM content WHERE n % 5 = 0 OR n % 9 = 0 OR n % 13 = 0 OR n % 17 = 0
        UNION ALL SELECT '{GONE}', true, 'relevant'""",
    f"""INSERT INTO note (mail_sha256, body)
        SELECT sha, 'Notiz ' || n FROM content WHERE n % 19 = 0
        UNION ALL SELECT sha, 'Zweite Notiz ' || n FROM content WHERE n % 38 = 0
        UNION ALL SELECT '{GONE}', 'Notiz ohne Mail'""",
]
# The research filters as SQL on mail.
TAGGED = "raw_sha256 IN (SELECT mail_sha256 FROM mail_tag WHERE tag_id IN ({}))"
IN_AKTE = "raw_sha256 IN (SELECT mail_sha256 FROM collection_mail WHERE collection_id IN ({}))"
REVIEWED = "raw_sha256 IN (SELECT mail_sha256 FROM mail_mark WHERE review IN ({}))"
SEEN = REVIEWED.format("'seen'")
UNREVIEWED = (
    "NOT EXISTS (SELECT 1 FROM mail_mark k WHERE k.mail_sha256 = mail.raw_sha256"
    " AND k.review IS NOT NULL)"
)
FLAGGED = "raw_sha256 IN (SELECT mail_sha256 FROM mail_mark WHERE flagged)"
NOTED = "raw_sha256 IN (SELECT mail_sha256 FROM note)"
WITH_PERSON = (
    "id IN (SELECT pa.mail_id FROM participation pa JOIN person p ON p.id = pa.person_id"
    " WHERE p.id = :person OR p.merged_into = :person)"
)
CASES: dict[str, tuple[Params, str]] = {
    "seen": ([("review", "seen")], SEEN),
    "relevant-or-irrelevant": (
        [("review", "relevant"), ("review", "irrelevant")],
        REVIEWED.format("'relevant', 'irrelevant'"),
    ),
    "unreviewed": ([("review", "unreviewed")], UNREVIEWED),
    "unreviewed-or-seen": (
        [("review", "unreviewed"), ("review", "seen")],
        f"({UNREVIEWED} OR {SEEN})",
    ),
    "rare-tag": ([("tag", "1")], TAGGED.format("1")),
    "either-tag": ([("tag", "1"), ("tag", "2")], TAGGED.format("1, 2")),
    "empty-tag": ([("tag", "3")], "false"),
    "akte": ([("collection", "1")], IN_AKTE.format("1")),
    "empty-akte": ([("collection", "2")], "false"),
    "has-note": ([("has_note", "true")], NOTED),
    "flagged": ([("flagged", "true")], FLAGGED),
    "tag-and-akte": (
        [("tag", "2"), ("collection", "1")],
        f"{TAGGED.format('2')} AND {IN_AKTE.format('1')}",
    ),
    "tag-and-seen": ([("tag", "2"), ("review", "seen")], f"{TAGGED.format('2')} AND {SEEN}"),
    "tag-and-dkim": (
        [("tag", "2"), ("dkim", "pass")],
        f"{TAGGED.format('2')} AND dkim_status = 'pass'",
    ),
    "note-and-date": (
        [("has_note", "true"), ("date_from", "2021-01-01")],
        f"{NOTED} AND date_utc >= '2021-01-01'",
    ),
    "unreviewed-and-attachment": (
        [("review", "unreviewed"), ("q", "has:attachment")],
        f"{UNREVIEWED} AND has_attachments",
    ),
    "flagged-and-word": ([("flagged", "true"), ("q", "Angebot")], f"{FLAGGED} AND {{word}}"),
}
WORD = "tsv @@ websearch_to_tsquery('german', 'Angebot')"


@pytest.fixture(scope="module")
def research_url(database_server_url: str, imported_database_url: str) -> Iterator[str]:
    """A copy of the imported archive with the research file above, for this module."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        asyncio.run(_write(url, RESEARCH_FILE))
        yield url


async def _write(url: str, statements: list[str]) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture
async def research(
    research_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Read-only client on the module's archive with research file."""
    settings = api_settings(research_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


@pytest.fixture
def sizes(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    walk_rows, content_rows = request.param
    monkeypatch.setattr(filters, "WALK_ROWS", walk_rows)
    monkeypatch.setattr(filters, "CONTENT_ROWS", content_rows)


# The bounded walk and the listed contents at their defaults and lowered.
SIZED = pytest.mark.parametrize(
    "sizes",
    [(filters.WALK_ROWS, filters.CONTENT_ROWS), (7, filters.CONTENT_ROWS), (7, 2)],
    ids=["default", "short-walk", "nothing-listed"],
    indirect=True,
)


async def busiest_person(url: str) -> int:
    found = await rows(
        url,
        "SELECT person_id FROM participation GROUP BY person_id"
        " ORDER BY count(DISTINCT mail_id) DESC, person_id LIMIT 1",
    )
    return int(found[0].person_id)


def _where(case: str) -> str:
    return CASES[case][1].replace("{word}", WORD)


# List, summary, neighbours, CSV --------------------------------------------------------------


@pytest.mark.parametrize(
    ("sizes", "sort"),
    [
        ((filters.WALK_ROWS, filters.CONTENT_ROWS), "date_desc"),
        ((filters.WALK_ROWS, filters.CONTENT_ROWS), "date_asc"),
        ((7, filters.CONTENT_ROWS), "date_asc"),
        ((7, 2), "date_desc"),
    ],
    ids=["default", "default-oldest-first", "short-walk", "nothing-listed"],
    indirect=["sizes"],
)
@pytest.mark.parametrize("case", list(CASES))
async def test_research_filters_select_what_sql_selects(
    research: httpx.AsyncClient, research_url: str, sizes: None, sort: str, case: str
) -> None:
    params, _ = CASES[case]
    expected = await ids(research_url, _where(case), sort)
    assert await listed(research, [*params, ("sort", sort)]) == expected
    summary = await get(research, "/api/mails/summary", params)
    assert (summary["total"], summary["exact"]) == (len(expected), True)


@SIZED
@pytest.mark.parametrize("case", ["rare-tag", "either-tag", "akte", "seen", "has-note", "flagged"])
async def test_with_the_busiest_person(
    research: httpx.AsyncClient, research_url: str, sizes: None, case: str
) -> None:
    """A person PostgreSQL misestimates, with a research filter; resolve_contents in action."""
    person = await busiest_person(research_url)
    params, where = CASES[case]
    expected = await ids(research_url, f"{where} AND {WITH_PERSON}", person=person)
    assert expected
    with_person = [*params, ("person", str(person))]
    assert await listed(research, with_person) == expected
    summary = await get(research, "/api/mails/summary", with_person)
    assert summary["total"] == len(expected)
    persons = await rows(
        research_url,
        f"SELECT count(DISTINCT coalesce(p.merged_into, p.id)) AS n FROM participation pa"
        f" JOIN person p ON p.id = pa.person_id JOIN mail ON mail.id = pa.mail_id"
        f" WHERE {where} AND mail.{WITH_PERSON}",
        person=person,
    )
    assert summary["persons"] == persons[0].n


@SIZED
@pytest.mark.parametrize("case", ["either-tag", "unreviewed-or-seen", "tag-and-akte"])
async def test_neighbours_agree_with_the_pages(
    research: httpx.AsyncClient, sizes: None, case: str
) -> None:
    params = CASES[case][0]
    found = await listed(research, params)
    assert len(found) > 2
    for index in sorted({0, 1, len(found) // 2, len(found) - 2, len(found) - 1}):
        neighbours = await get(research, f"/api/mails/{found[index]}/neighbors", params)
        assert neighbours == {
            "prev_id": found[index - 1] if index > 0 else None,
            "next_id": found[index + 1] if index + 1 < len(found) else None,
            "position": index + 1,
        }


async def test_neighbours_of_a_mail_outside_a_research_filter(
    research: httpx.AsyncClient, research_url: str
) -> None:
    every = await ids(research_url)
    tagged = set(await ids(research_url, TAGGED.format("2")))
    outside = next(i for i in range(len(every) // 2, len(every)) if every[i] not in tagged)
    before = [mail_id for mail_id in every[:outside] if mail_id in tagged]
    after = [mail_id for mail_id in every[outside + 1 :] if mail_id in tagged]
    neighbours = await get(research, f"/api/mails/{every[outside]}/neighbors", [("tag", "2")])
    assert neighbours == {"prev_id": before[-1], "next_id": after[0], "position": None}


@pytest.mark.parametrize("case", ["either-tag", "unreviewed-or-seen", "has-note"])
async def test_csv_holds_the_filtered_list(
    research: httpx.AsyncClient, research_url: str, case: str
) -> None:
    params, _ = CASES[case]
    exported = await export(research, [*params, ("sort", "date_asc")])
    assert [int(row[0]) for row in exported] == await ids(research_url, _where(case), "date_asc")


async def test_unknown_tags_and_akten_match_nothing(research: httpx.AsyncClient) -> None:
    for params in ([("tag", "987654")], [("collection", "987654")]):
        page = await get(research, "/api/mails", params)
        assert page["items"] == []
    error = await get(research, "/api/mails", [("review", "maybe")], status=422)
    assert error["detail"][0]["loc"][:2] == ["query", "review"]


# List items -----------------------------------------------------------------------------------


async def test_items_carry_review_tags_and_notes(
    research: httpx.AsyncClient, research_url: str
) -> None:
    expected = {
        row.id: row
        for row in await rows(
            research_url,
            "SELECT m.id, k.review::text AS review, coalesce(k.flagged, false) AS flagged,"
            " ARRAY(SELECT t.id FROM mail_tag mt JOIN tag t ON t.id = mt.tag_id"
            "  WHERE mt.mail_sha256 = m.raw_sha256 ORDER BY lower(t.name), t.id) AS tags,"
            " (SELECT count(*) FROM note n WHERE n.mail_sha256 = m.raw_sha256) AS notes"
            " FROM mail m LEFT JOIN mail_mark k ON k.mail_sha256 = m.raw_sha256",
        )
    }
    seen: Counter[str] = Counter()
    for page in await pages(research, [], 200):
        for item in page["items"]:
            row = expected[item["id"]]
            shown = (item["review"], item["flagged"], item["tags"], item["notes"])
            assert shown == (row.review, row.flagged, row.tags, row.notes), item["id"]
            seen.update(
                ["reviewed"] * bool(item["review"])
                + ["two tags"] * (len(item["tags"]) == 2)
                + ["two notes"] * (item["notes"] == 2)
            )
    assert all(seen[key] for key in ("reviewed", "two tags", "two notes")), seen
    # Tags by name ignoring case: häufig (2) before Rar (1).
    assert [2, 1] in [row.tags for row in expected.values()]


async def test_byte_identical_copies_share_their_research_data(
    research: httpx.AsyncClient, research_url: str
) -> None:
    copies = await rows(
        research_url,
        "SELECT array_agg(id ORDER BY id) AS ids FROM mail GROUP BY raw_sha256 HAVING count(*) > 1",
    )
    assert copies
    page = await get(research, "/api/mails", [("tag", "1"), ("limit", "200")])
    tagged = set(page_ids(page))
    for group in copies:
        assert set(group.ids) <= tagged
        items = [await get(research, f"/api/mails/{mail_id}") for mail_id in group.ids]
        assert len({str(item["research"]) for item in items}) == 1


# Overview -------------------------------------------------------------------------------------


async def test_overview_counts_are_the_list_totals(
    research: httpx.AsyncClient, research_url: str
) -> None:
    overview = await get(research, "/api/research")

    async def total(params: Params) -> int:
        summary = await get(research, "/api/mails/summary", params)
        assert summary["exact"]
        return int(summary["total"])

    assert [(tag["name"], tag["mails"]) for tag in overview["tags"]] == [
        ("häufig", await total([("tag", "2")])),
        ("Leer", 0),
        ("Rar", await total([("tag", "1")])),
    ]
    assert {c["name"]: c["mails"] for c in overview["collections"]} == {
        "Akte A": await total([("collection", "1")]),
        "Akte B": 0,
    }
    assert list(overview["review"]) == ["unreviewed", "seen", "relevant", "irrelevant"]
    for key, count in overview["review"].items():
        assert count == await total([("review", key)]), key
    assert overview["flagged"] == await total([("flagged", "true")])
    # The content in no mail counts nowhere; its notes count, as notes are listed without mail.
    notes = await rows(research_url, "SELECT count(*) AS n FROM note")
    assert overview["notes"] == notes[0].n
    assert sum(overview["review"].values()) == (await get(research, "/api/stats"))["mails"]
    assert overview["starter_missing"] > 0


# Themes ---------------------------------------------------------------------------------------


async def test_every_theme_search_runs(research: httpx.AsyncClient) -> None:
    for theme in load_themes():
        for search in theme.searches:
            params = parse_qsl(search.query)
            await get(research, "/api/mails", params)
            summary = await get(research, "/api/mails/summary", params)
            assert summary["exact"], search.name


async def test_theme_searches_find_inflections_and_phrases(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    """German full text as the themes' comment promises: an inflected form matches its word,
    a quoted phrase only its words in that order."""
    written = await rows(mutable_database_url, "SELECT id FROM mail ORDER BY id LIMIT 3")
    bodies = [
        "Die Barspenden kamen gestückelt in drei Umschlägen.",
        "Am Tag X stehen alle bereit.",
        "X sagt, der Tag sei noch nicht gekommen.",
    ]
    for row, body in zip(written, bodies, strict=True):
        await rows(
            mutable_database_url,
            "UPDATE mail SET body_text = :body WHERE id = :id",
            body=body,
            id=row.id,
        )
    searches = {s.name: s for theme in load_themes() for s in theme.searches}
    money = searches["Spendenaffären: Bargeld, Stückelung, Strohleute"]
    coup = searches["Verfassungsfeindlichkeit: Umsturz und Tag X"]
    settings = api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        found_money = await listed(http, parse_qsl(money.query))
        found_coup = await listed(http, parse_qsl(coup.query))
    first, second, third = (row.id for row in written)
    assert first in found_money
    assert second in found_coup
    assert third not in found_coup

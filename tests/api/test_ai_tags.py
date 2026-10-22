"""AI tags and themes in the lists (milestone 17, D309, D310): the mail list's filters ai_tag and
ai_theme with its summary, neighbours, CSV and selection, the document list's ai_tag, the facets,
the tag lookup and adopting an AI tag as a team tag.

The summaries are written in SQL over a copy of the imported archive (AI_ROWS), as an AI run
stores them, so that the API is tested apart from the run. Expected results come from SQL on
the result tables written apart from api/filters.py and api/ai_tags.py (DESCRIBES).
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import make_url, pool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailrobbe.api import ai_tags, documents, filters
from mailrobbe.api.schemas import AI_FACET_TAGS, MailFilters, MailSelection
from mailrobbe.api.selection import resolve_selection
from mailrobbe.config import Settings
from tests.api.conftest import _client, _execute, api_settings
from tests.api.test_mails import Params, export, get, ids, listed, page_ids, pages, rows
from tests.conftest import GeneratedArchive, _temporary_database

pytestmark = pytest.mark.db

# Originals are numbered in list order, oldest first (r); documents with text by the mails
# carrying them (d). A summary is kept for every fourth original's content and for each content
# with a byte-identical duplicate, so that duplicates have cases; result ids are r, documents'
# 1000 + d. Tags: 1 on every eighth original and on the document carried most, 2 on every
# twelfth, on the contents with duplicates and on d=2, 3 on the three oldest summaries only, 4
# and 5 on d=3, 6 on d=4, 7 only on a discarded and a replaced result, 8 on none. Theme hints:
# gewalt on every sixteenth original (twice on every 32nd), rassismus on d=2, a theme on the
# discarded result and one no longer in themes.toml.
AI_ROWS = [
    """CREATE TEMP TABLE r AS SELECT id, raw_sha256,
        row_number() OVER (ORDER BY coalesce(date_utc, '-infinity'), id) AS r
        FROM mail WHERE is_duplicate_of IS NULL""",
    """CREATE TEMP TABLE s AS SELECT DISTINCT ON (raw_sha256) raw_sha256, r FROM r
        WHERE r % 4 = 0 OR raw_sha256 IN (SELECT raw_sha256 FROM mail
            WHERE is_duplicate_of IS NOT NULL)
        ORDER BY raw_sha256, r""",
    """CREATE TEMP TABLE d AS SELECT id, sha256, row_number() OVER (ORDER BY mails DESC, id) AS d
        FROM document WHERE sha256 IS NOT NULL AND text_status = 'text'""",
    """INSERT INTO ai_tag (id, key, label) OVERRIDING SYSTEM VALUE
        VALUES (1, 'spende', 'Spende'), (2, 'parteitag', 'Parteitag'), (3, 'selten', 'Selten'),
               (4, '100% sicher', '100% sicher'), (5, 'a b', 'a_b'), (6, 'axb', 'axb'),
               (7, 'verworfen', 'Verworfen'), (8, 'ohne', 'Ohne')""",
    """INSERT INTO ai_result (id, kind, target, target_sha256, engine, model, body)
        OVERRIDING SYSTEM VALUE
        SELECT r, CAST('summarize' AS ai_task_kind), 'mail', raw_sha256, 'text', 'qwen3:14b',
            'Zusammenfassung' FROM s
        UNION ALL SELECT 1000 + d, 'summarize', 'document', sha256, 'text', 'qwen3:14b', 'Text'
            FROM d WHERE d <= 4""",
    # a discarded summary of a content without a valid one, a replaced one of a content with one
    """INSERT INTO ai_result (id, kind, target, target_sha256, engine, model, body, state)
        OVERRIDING SYSTEM VALUE
        SELECT 2000, CAST('summarize' AS ai_task_kind), 'mail', raw_sha256, 'text', 'qwen3:14b',
            'Alt', CAST('discarded' AS ai_result_state)
            FROM r WHERE r = (SELECT min(r) FROM r WHERE raw_sha256 NOT IN (SELECT raw_sha256
                FROM s))
        UNION ALL SELECT 2001, 'summarize', 'mail', raw_sha256, 'text', 'qwen3:14b', 'Alt',
            'replaced' FROM s WHERE r = (SELECT max(r) FROM s)""",
    """INSERT INTO ai_tag_link (result_id, tag_id)
        SELECT r, 1 FROM s WHERE r % 8 = 0
        UNION SELECT 1000 + d, 1 FROM d WHERE d = 1
        UNION SELECT r, 2 FROM s WHERE r % 12 = 0
            OR raw_sha256 IN (SELECT raw_sha256 FROM mail WHERE is_duplicate_of IS NOT NULL)
        UNION SELECT 1000 + d, 2 FROM d WHERE d = 2
        UNION SELECT r, 3 FROM s WHERE r IN (SELECT r FROM s ORDER BY r LIMIT 3)
        UNION SELECT 1000 + d, tag FROM d, (VALUES (4), (5)) t (tag) WHERE d = 3
        UNION SELECT 1000 + d, 6 FROM d WHERE d = 4
        UNION SELECT id, tag FROM ai_result, (VALUES (1), (7)) t (tag) WHERE id >= 2000""",
    """INSERT INTO ai_theme_hint (result_id, theme, quote, position)
        SELECT r, 'gewalt', 'Drohung', 10 FROM s WHERE r % 16 = 0
        UNION ALL SELECT r, 'gewalt', 'Waffen', NULL FROM s WHERE r % 32 = 0
        UNION ALL SELECT 1000 + d, 'rassismus', 'Austausch', 3 FROM d WHERE d = 2
        UNION ALL SELECT 2000, 'verfassungsfeindlichkeit', 'Tag X', 0
        UNION ALL SELECT min(r), 'nicht-mehr', 'Alt', 0 FROM s""",
    "ANALYZE",
]

# (mail_id, result_id): every valid summary describing a mail, its own content's or one of its
# attachments' documents'.
DESCRIBES = (
    "(SELECT m.id AS mail_id, r.id AS result_id FROM mail m JOIN ai_result r"
    " ON r.target = 'mail' AND r.target_sha256 = m.raw_sha256"
    " WHERE r.kind = 'summarize' AND r.state = 'valid'"
    " UNION SELECT a.mail_id, r.id FROM attachment a JOIN document d ON d.id = a.document_id"
    " JOIN ai_result r ON r.target = 'document' AND r.target_sha256 = d.sha256"
    " WHERE r.kind = 'summarize' AND r.state = 'valid')"
)
TAGGED = (
    f"id IN (SELECT x.mail_id FROM {DESCRIBES} x JOIN ai_tag_link l ON l.result_id = x.result_id"
    " WHERE l.tag_id = {})"
)
THEMED = (
    f"id IN (SELECT x.mail_id FROM {DESCRIBES} x JOIN ai_theme_hint h"
    " ON h.result_id = x.result_id WHERE h.theme = '{}')"
)
CASES: dict[str, tuple[Params, str]] = {
    "own-and-document": ([("ai_tag", "1")], TAGGED.format(1)),
    "with-duplicates": ([("ai_tag", "2")], TAGGED.format(2)),
    "rare-and-old": ([("ai_tag", "3")], TAGGED.format(3)),
    "only-a-document": ([("ai_tag", "4")], TAGGED.format(4)),
    "two-tags": ([("ai_tag", "1"), ("ai_tag", "2")], f"{TAGGED.format(1)} AND {TAGGED.format(2)}"),
    "same-tag-twice": ([("ai_tag", "1"), ("ai_tag", "1")], TAGGED.format(1)),
    "discarded-and-replaced": ([("ai_tag", "7")], "false"),
    "no-summary": ([("ai_tag", "8")], "false"),
    "unknown": ([("ai_tag", "999")], "false"),
    "beyond-bigint": ([("ai_tag", str(2**70))], "false"),
    "theme": ([("ai_theme", "gewalt")], THEMED.format("gewalt")),
    "theme-of-a-document": ([("ai_theme", "rassismus")], THEMED.format("rassismus")),
    "theme-of-a-discarded": ([("ai_theme", "verfassungsfeindlichkeit")], "false"),
    "theme-and-tag": (
        [("ai_theme", "gewalt"), ("ai_tag", "1")],
        f"{THEMED.format('gewalt')} AND {TAGGED.format(1)}",
    ),
    "tag-and-date": (
        [("ai_tag", "2"), ("date_from", "2020-01-01")],
        f"{TAGGED.format(2)} AND date_utc >= '2020-01-01'",
    ),
    "tag-without-duplicates": (
        [("ai_tag", "2"), ("hide_duplicates", "true")],
        f"{TAGGED.format(2)} AND is_duplicate_of IS NULL",
    ),
}


@pytest.fixture(scope="session")
def ai_database_url(database_server_url: str, imported_database_url: str) -> Iterator[str]:
    """A copy of the imported archive with the summaries of AI_ROWS. Read only."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        asyncio.run(_execute(url, AI_ROWS))
        yield url


@pytest.fixture
async def ai_client(
    ai_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings(ai_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


@pytest.fixture
def ai_mutable_url(database_server_url: str, ai_database_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url, make_url(ai_database_url).database) as url:
        yield url


@pytest.fixture
async def ai_mutable_client(
    ai_mutable_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings(ai_mutable_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


@pytest.fixture
def walk_rows(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(filters, "WALK_ROWS", request.param)
    return int(request.param)


@pytest.fixture
def collections(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts first_ids's falls back to collecting every match."""
    calls: list[int] = []
    collected = filters._collected

    async def counted(*args: Any, **kwargs: Any) -> list[int]:
        calls.append(1)
        return await collected(*args, **kwargs)

    monkeypatch.setattr(filters, "_collected", counted)
    return calls


# The mail list ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "walk_rows", [filters.WALK_ROWS, 7], ids=["default", "short-walk"], indirect=True
)
@pytest.mark.parametrize("sort", ["date_desc", "date_asc"])
@pytest.mark.parametrize("case", list(CASES))
async def test_ai_filters_select_what_sql_selects(
    ai_client: httpx.AsyncClient, ai_database_url: str, walk_rows: int, sort: str, case: str
) -> None:
    params, where = CASES[case]
    expected = await ids(ai_database_url, where, sort)
    assert await listed(ai_client, [*params, ("sort", sort)]) == expected
    summary = await get(ai_client, "/api/mails/summary", params)
    assert (summary["total"], summary["exact"]) == (len(expected), True)


async def test_the_cases_are_not_empty(ai_database_url: str) -> None:
    """Guards the expectations above: each case that should match does, and the duplicates
    and the documents have cases."""
    for case, (_, where) in CASES.items():
        if where != "false":
            assert await ids(ai_database_url, where), case
    copies = await rows(
        ai_database_url,
        "SELECT d.id FROM mail d JOIN mail o ON o.id = d.is_duplicate_of"
        " WHERE d.raw_sha256 = o.raw_sha256",
    )
    assert copies
    assert {row.id for row in copies} <= set(await ids(ai_database_url, TAGGED.format(2)))


async def test_a_common_tag_fills_its_pages_by_walking(
    ai_client: httpx.AsyncClient, ai_database_url: str, collections: list[int]
) -> None:
    """The walk form finds the matches itself: no page falls back to collecting them."""
    for params, where in [CASES["own-and-document"], CASES["with-duplicates"], CASES["theme"]]:
        expected = await ids(ai_database_url, where)
        found = await pages(ai_client, params, 5)
        assert [mail_id for page in found[:-1] for mail_id in page_ids(page)] == (
            expected[: 5 * (len(found) - 1)]
        )
        assert len(found) > 2
    assert collections == [1, 1, 1]  # only the last, short page of each list


async def test_a_rare_tag_beyond_the_walk_is_collected(
    ai_client: httpx.AsyncClient,
    ai_database_url: str,
    collections: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tag 3 is on the three oldest summaries, behind the newest WALK_ROWS of date_desc."""
    monkeypatch.setattr(filters, "WALK_ROWS", 100)
    expected = await ids(ai_database_url, TAGGED.format(3))
    page = await get(ai_client, "/api/mails", CASES["rare-and-old"][0])
    assert page_ids(page) == expected and len(expected) >= 3
    assert collections == [1]


async def test_an_unknown_theme_is_an_invalid_filter(ai_client: httpx.AsyncClient) -> None:
    for path in ("/api/mails", "/api/mails/summary", "/api/ai/facets"):
        error = await get(ai_client, path, [("ai_theme", "nicht-mehr")], status=400)
        assert error["detail"]["code"] == "invalid_filter"
    await get(ai_client, "/api/mails", [("ai_tag", "x")], status=422)


async def test_neighbours_agree_with_the_pages(ai_client: httpx.AsyncClient) -> None:
    params = CASES["own-and-document"][0]
    found = await listed(ai_client, params)
    assert len(found) > 2
    for index in sorted({0, 1, len(found) // 2, len(found) - 1}):
        neighbours = await get(ai_client, f"/api/mails/{found[index]}/neighbors", params)
        assert neighbours == {
            "prev_id": found[index - 1] if index > 0 else None,
            "next_id": found[index + 1] if index + 1 < len(found) else None,
            "position": index + 1,
        }


async def test_csv_and_selection_hold_the_filtered_mails(
    ai_client: httpx.AsyncClient, ai_database_url: str
) -> None:
    params, where = CASES["theme-of-a-document"]
    exported = await export(ai_client, [*params, ("sort", "date_asc")])
    expected = await ids(ai_database_url, where, "date_asc")
    assert [int(row[0]) for row in exported] == expected
    engine = create_async_engine(ai_database_url, poolclass=pool.NullPool)
    try:
        async with AsyncSession(engine) as session:
            settings = Settings(database_url=ai_database_url)
            selection = MailSelection(filters=MailFilters(ai_tag=[2], ai_theme=["rassismus"]))
            mails = await resolve_selection(session, settings, selection, 10_000)
    finally:
        await engine.dispose()
    both = f"{TAGGED.format(2)} AND {THEMED.format('rassismus')}"
    assert [mail.id for mail in mails] == await ids(ai_database_url, both, "date_asc")


# The document list -----------------------------------------------------------------------------


async def test_the_document_list_filters_by_ai_tags(
    ai_client: httpx.AsyncClient, ai_database_url: str
) -> None:
    numbered = {
        row.d: row.id
        for row in await rows(
            ai_database_url,
            "SELECT id, sha256, row_number()"
            " OVER (ORDER BY mails DESC, id) AS d FROM document WHERE sha256 IS NOT NULL"
            " AND text_status = 'text'",
        )
    }
    for params, expected in [
        ([("ai_tag", "1")], [numbered[1]]),  # the document's own summary, not its mails'
        ([("ai_tag", "4")], [numbered[3]]),
        ([("ai_tag", "4"), ("ai_tag", "5")], [numbered[3]]),
        ([("ai_tag", "4"), ("ai_tag", "6")], []),
        ([("ai_tag", "7")], []),
        ([("ai_tag", "3")], []),  # only on mails
        ([("ai_tag", str(2**70))], []),
    ]:
        page = await get(ai_client, "/api/documents", params)
        assert [item["id"] for item in page["items"]] == expected, params
        summary = await get(ai_client, "/api/documents/summary", params)
        assert summary["total"] == len(expected)
    kind = (await get(ai_client, f"/api/documents/{numbered[3]}"))["kind"]
    other = "image" if kind != "image" else "pdf"
    for params, expected in [
        ([("ai_tag", "4"), ("kind", kind)], [numbered[3]]),
        ([("ai_tag", "4"), ("kind", other)], []),
    ]:
        page = await get(ai_client, "/api/documents", params)
        assert [item["id"] for item in page["items"]] == expected


# Facets ----------------------------------------------------------------------------------------


async def expected_tags(url: str, where: str = "true", limit: int = AI_FACET_TAGS) -> list[Any]:
    found = await rows(
        url,
        f"SELECT t.id, t.label, count(DISTINCT x.mail_id) AS mails FROM {DESCRIBES} x"
        " JOIN ai_tag_link l ON l.result_id = x.result_id JOIN ai_tag t ON t.id = l.tag_id"
        f" WHERE x.mail_id IN (SELECT id FROM mail WHERE {where})"
        f' GROUP BY t.id, t.label ORDER BY mails DESC, t.label COLLATE "C", t.id LIMIT {limit}',
    )
    return [{"id": row.id, "label": row.label, "mails": row.mails} for row in found]


async def expected_themes(url: str, where: str = "true") -> list[Any]:
    found = await rows(
        url,
        f"SELECT h.theme, count(DISTINCT x.mail_id) AS mails FROM {DESCRIBES} x"
        " JOIN ai_theme_hint h ON h.result_id = x.result_id"
        f" WHERE x.mail_id IN (SELECT id FROM mail WHERE {where}) GROUP BY h.theme",
    )
    mails = {row.theme: row.mails for row in found}
    names = {"rassismus": "Rassismus", "gewalt": "Gewalt"}  # in the order of themes.toml
    return [
        {"key": key, "label": name, "mails": mails[key]}
        for key, name in names.items()
        if mails.get(key, 0) > 0
    ]


async def test_facets_without_filters_count_every_described_mail(
    ai_client: httpx.AsyncClient, ai_database_url: str
) -> None:
    facets = await get(ai_client, "/api/ai/facets")
    assert (facets["mails"], facets["sampled"]) == (None, False)
    assert facets["tags"] == await expected_tags(ai_database_url)
    assert facets["themes"] == await expected_themes(ai_database_url)


@pytest.mark.parametrize(
    "params, where",
    [
        ([("hide_duplicates", "true")], "is_duplicate_of IS NULL"),
        ([("ai_tag", "1")], TAGGED.format(1)),
        ([("dkim", "pass")], "dkim_status = 'pass'"),
    ],
)
async def test_facets_count_the_mails_of_a_filter(
    ai_client: httpx.AsyncClient, ai_database_url: str, params: Params, where: str
) -> None:
    matched = await ids(ai_database_url, where)
    facets = await get(ai_client, "/api/ai/facets", params)
    assert (facets["mails"], facets["sampled"]) == (len(matched), False)
    assert facets["tags"] == await expected_tags(ai_database_url, where)
    assert facets["themes"] == await expected_themes(ai_database_url, where)


async def test_facets_of_a_large_filter_count_a_sample(
    ai_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ai_tags, "FACET_MAILS", 30)
    facets = await get(ai_client, "/api/ai/facets", [("ai_tag", "2")])
    assert (facets["mails"], facets["sampled"]) == (30, True)
    assert facets["tags"][0] == {"id": 2, "label": "Parteitag", "mails": 30}


async def test_facets_without_filters_fall_back_to_a_sample(
    ai_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    run = documents._all_unless_canceled

    async def first_canceled(*args: Any) -> Any:
        calls.append(1)
        return None if len(calls) == 1 else await run(*args)  # every described mail

    monkeypatch.setattr(ai_tags, "_all_unless_canceled", first_canceled)
    monkeypatch.setattr(ai_tags, "FACET_MAILS", 100)
    facets = await get(ai_client, "/api/ai/facets")
    assert (facets["mails"], facets["sampled"]) == (100, True)

    async def canceled(*_: Any) -> None:
        return None

    monkeypatch.setattr(ai_tags, "_all_unless_canceled", canceled)
    facets = await get(ai_client, "/api/ai/facets")
    assert facets == {"tags": [], "themes": [], "mails": None, "sampled": False}


async def test_no_facets_without_summaries(client: httpx.AsyncClient) -> None:
    for params in ([], [("hide_duplicates", "true")]):
        facets = await get(client, "/api/ai/facets", params)
        assert (facets["tags"], facets["themes"]) == ([], [])


# The tag lookup ------------------------------------------------------------------------------


async def test_tags_by_id_keep_the_order_given(
    ai_client: httpx.AsyncClient, ai_database_url: str
) -> None:
    counts = {tag["id"]: tag for tag in await expected_tags(ai_database_url, limit=100)}
    found = await get(
        ai_client,
        "/api/ai/tags",
        [("id", "3"), ("id", "1"), ("id", "999"), ("id", "2"), ("id", "1"), ("id", str(2**70))],
    )
    assert found == [counts[3], counts[1], counts[2]]
    # a tag no valid summary has: its label, no mails
    found = await get(ai_client, "/api/ai/tags", [("id", "7"), ("id", "8")])
    assert found == [
        {"id": 7, "label": "Verworfen", "mails": 0},
        {"id": 8, "label": "Ohne", "mails": 0},
    ]
    assert (
        len(await get(ai_client, "/api/ai/tags", [("id", "1"), ("id", "2"), ("limit", "1")])) == 1
    )


async def test_tags_by_part_of_their_label(
    ai_client: httpx.AsyncClient, ai_database_url: str
) -> None:
    by_label = await get(ai_client, "/api/ai/tags", [("q", "%")])
    assert [tag["id"] for tag in by_label] == [4]
    by_label = await get(ai_client, "/api/ai/tags", [("q", "_")])
    assert [tag["id"] for tag in by_label] == [5]
    by_label = await get(ai_client, "/api/ai/tags", [("q", " SPENDE ")])
    assert [tag["id"] for tag in by_label] == [1]
    assert await get(ai_client, "/api/ai/tags", [("q", "nirgends")]) == []
    assert await get(ai_client, "/api/ai/tags", [("q", "Verworfen")]) == []  # no mails
    every = await expected_tags(ai_database_url, limit=100)
    assert await get(ai_client, "/api/ai/tags", [("limit", "50")]) == every
    assert (
        await get(ai_client, "/api/ai/tags", [("q", "e"), ("limit", "2")])
        == [tag for tag in every if "e" in tag["label"].lower()][:2]
    )
    await get(ai_client, "/api/ai/tags", [("limit", "0")], status=422)
    await get(ai_client, "/api/ai/tags", [("limit", "51")], status=422)


async def test_tag_counts_is_the_count_of_the_lookup(ai_database_url: str) -> None:
    engine = create_async_engine(ai_database_url, poolclass=pool.NullPool)
    try:
        async with AsyncSession(engine) as session:
            counted = await ai_tags.tag_counts(session, [1, 2, 3, 7, 999])
    finally:
        await engine.dispose()
    every = await expected_tags(ai_database_url, limit=100)
    expected = [(tag["id"], tag["mails"]) for tag in every if tag["id"] in (1, 2, 3)]
    assert [(tag.id, tag.mails) for tag in counted] == [*expected, (7, 0)]
    assert [tag.label for tag in counted][-1] == "Verworfen"


# Adopting an AI tag ----------------------------------------------------------------------------


async def adopt(
    client: httpx.AsyncClient, tag_id: int, body: dict[str, Any], status: int = 200
) -> Any:
    response = await client.post(
        f"/api/ai/tags/{tag_id}/adopt", json=body, headers={"X-Mailrobbe-Editor": "Aaron"}
    )
    assert response.status_code == status, response.text
    return response.json()


async def team_tag(url: str, tag_id: int) -> tuple[Any, list[Any]]:
    """The team tag and its links, by content."""
    tag = (await rows(url, "SELECT name, color, created_by FROM tag WHERE id = :id", id=tag_id))[0]
    links = await rows(
        url,
        "SELECT mail_sha256, added_by FROM mail_tag WHERE tag_id = :id ORDER BY mail_sha256",
        id=tag_id,
    )
    return tag, links


async def contents(url: str, where: str) -> list[str]:
    found = await rows(url, f"SELECT DISTINCT raw_sha256 FROM mail WHERE {where} ORDER BY 1")
    return [row.raw_sha256 for row in found]


async def test_adopting_for_one_mail(
    ai_mutable_client: httpx.AsyncClient, ai_mutable_url: str
) -> None:
    mail = (await ids(ai_mutable_url, TAGGED.format(1)))[0]
    adopted = await adopt(ai_mutable_client, 1, {"mail_id": mail})
    assert adopted["created"] is True and adopted["mails"] == 1
    tag, links = await team_tag(ai_mutable_url, adopted["tag_id"])
    assert (tag.name, tag.color, tag.created_by) == ("Spende", "blue", "Aaron")
    assert [(link.mail_sha256, link.added_by) for link in links] == [
        (sha, "Aaron") for sha in await contents(ai_mutable_url, f"id = {mail}")
    ]
    again = await adopt(ai_mutable_client, 1, {"mail_id": mail})
    assert again == {"tag_id": adopted["tag_id"], "created": False, "mails": 0}
    detail = await get(ai_mutable_client, f"/api/mails/{mail}")
    assert [tag["name"] for tag in detail["research"]["tags"]] == ["Spende"]


async def test_adopting_for_every_mail_carrying_it(
    ai_mutable_client: httpx.AsyncClient, ai_mutable_url: str
) -> None:
    """Every mail with the AI tag, hidden ones too, gets the team tag of the same name in any
    case; mails that had it are not counted."""
    response = await ai_mutable_client.post("/api/tags", json={"name": "PARTEITAG", "color": "red"})
    team = response.json()["id"]
    carrying = await ids(ai_mutable_url, TAGGED.format(2), "date_asc")
    first, hidden = carrying[0], carrying[-1]
    await ai_mutable_client.post(f"/api/mails/{first}/tags", json={"add": [team]})
    await _execute(
        ai_mutable_url,
        [
            "INSERT INTO hide_rule (id, domain) OVERRIDING SYSTEM VALUE VALUES (1, 'x.example')",
            f"INSERT INTO mail_hidden (rule_id, mail_id) VALUES (1, {hidden})",
        ],
    )
    assert hidden not in await listed(ai_mutable_client, [("ai_tag", "2")])
    adopted = await adopt(ai_mutable_client, 2, {})
    same = await rows(
        ai_mutable_url,
        "SELECT count(*) AS n FROM mail WHERE raw_sha256 = (SELECT raw_sha256 FROM mail"
        " WHERE id = :id)",
        id=first,
    )
    assert adopted == {"tag_id": team, "created": False, "mails": len(carrying) - same[0].n}
    _, links = await team_tag(ai_mutable_url, team)
    assert [link.mail_sha256 for link in links] == await contents(ai_mutable_url, TAGGED.format(2))
    assert len(await rows(ai_mutable_url, "SELECT id FROM tag")) == 1


async def test_adopting_for_the_mails_of_a_filter(
    ai_mutable_client: httpx.AsyncClient, ai_mutable_url: str
) -> None:
    where = f"{TAGGED.format(1)} AND is_duplicate_of IS NULL AND dkim_status = 'pass'"
    expected = await ids(ai_mutable_url, where)
    assert expected
    adopted = await adopt(
        ai_mutable_client, 1, {"filters": {"hide_duplicates": True, "dkim": ["pass"]}}
    )
    assert adopted["created"] is True and adopted["mails"] == len(expected)
    _, links = await team_tag(ai_mutable_url, adopted["tag_id"])
    assert [link.mail_sha256 for link in links] == await contents(ai_mutable_url, where)


async def test_adopting_refuses_what_it_cannot_do(
    ai_mutable_client: httpx.AsyncClient, ai_mutable_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    refused: list[tuple[int, dict[str, Any], int, str]] = [
        (999, {}, 404, "not_found"),
        (1, {"mail_id": 10**9}, 404, "not_found"),
        (1, {"mail_id": 1, "filters": {}}, 400, "invalid_selection"),
        (8, {}, 400, "empty_selection"),  # no mail carries it
        (1, {"filters": {"ai_theme": ["nicht-mehr"]}}, 400, "invalid_filter"),
    ]
    for tag_id, body, status, code in refused:
        error = await adopt(ai_mutable_client, tag_id, body, status)
        assert error["detail"]["code"] == code, (tag_id, body)
    monkeypatch.setattr(ai_tags, "BULK_LIMIT", 3)
    error = await adopt(ai_mutable_client, 2, {}, 400)
    assert error["detail"]["code"] == "too_many_mails"
    assert await rows(ai_mutable_url, "SELECT id FROM tag") == []  # no team tag made
    response = await ai_mutable_client.post(f"/api/ai/tags/{2**70}/adopt", json={})
    assert response.status_code == 422

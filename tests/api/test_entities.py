"""The entity API (D84 to D89): the entity list with its sorts, filters and paging, its summary,
refs, an entity's page, the facets of the mail list and the entities of one mail.

The archive is the imported one with the synthetic entities of tests/api/conftest.py
(ENTITY_ROWS). Expected results come from SQL on the entity and mention tables written apart
from api/entities.py; snippets are checked against the stored texts.
"""

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api import documents, entities, paging
from mailrobbe.api.entities import mention_snippet
from mailrobbe.api.schemas import (
    ENTITY_PERSONS_LIMIT,
    ENTITY_REFS_LIMIT,
    ENTITY_RELATED_LIMIT,
    ENTITY_SAMPLES,
    ENTITY_SNIPPET_LENGTH,
    FACET_LIMIT,
)
from mailrobbe.entities.model import scan_version
from mailrobbe.enums import EntityKind
from tests.api.conftest import _client, api_settings
from tests.api.test_entity_filters import MENTIONED, MENTIONS
from tests.api.test_mails import Params, at, get, ids, rows
from tests.api.test_paging import check_jumps
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

Item = dict[str, Any]
KINDS = [kind.value for kind in EntityKind]
ORDER = {
    "mails": "mails DESC, id DESC",
    "recent": "COALESCE(first_date, '-infinity') DESC, id DESC",
    "oldest": "COALESCE(first_date, '-infinity') ASC, id ASC",
    "value": "value DESC, id DESC",
    "label": 'lower(label) COLLATE "C" ASC, id ASC',
}
PAGE = 4  # not a divisor of the number of entities, so the last page is short
# The mentioning mails of :entity that are no duplicates (the figures' mails, D85).
COUNTED = (
    f"SELECT DISTINCT x.mail_id FROM {MENTIONS} x JOIN mail m ON m.id = x.mail_id"
    " WHERE x.entity_id = :entity AND m.is_duplicate_of IS NULL"
)
ELLIPSIS = "…"


async def entity_pages(client: httpx.AsyncClient, params: Params, limit: int = PAGE) -> list[Any]:
    """Every page of the entity list, following next_cursor from the first page."""
    found: list[Any] = []
    cursor = None
    while True:
        page = await get(client, "/api/entities", [*params, ("limit", str(limit)), *at(cursor)])
        assert (page["prev_cursor"] is None) == (cursor is None)
        found.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return found


async def entity_ids(url: str, where: str = "true", sort: str = "mails") -> list[int]:
    found = await rows(url, f"SELECT id FROM entity WHERE {where} ORDER BY {ORDER[sort]}")
    return [row.id for row in found]


def item_ids(found: Sequence[Any]) -> list[int]:
    return [item["id"] for page in found for item in page["items"]]


# The list ------------------------------------------------------------------------------------


@pytest.mark.parametrize("sort", list(ORDER))
async def test_every_sort_pages_both_ways(
    entity_client: httpx.AsyncClient, entity_database_url: str, sort: str
) -> None:
    where, limit = ("value IS NOT NULL", 2) if sort == "value" else ("true", PAGE)  # amounts
    expected = await entity_ids(entity_database_url, where, sort)
    forward = await entity_pages(entity_client, [("sort", sort)], limit)
    assert item_ids(forward) == expected
    assert len(expected) % limit != 0 and len(forward) > 2
    # From the last page back to the first, prev_cursor gives each page again.
    cursor = forward[-1]["prev_cursor"]
    for page in reversed(forward[:-1]):
        back = await get(
            entity_client, "/api/entities", [("sort", sort), ("limit", str(limit)), *at(cursor)]
        )
        assert back["items"] == page["items"]
        assert back["next_cursor"] is not None
        cursor = back["prev_cursor"]
    assert cursor is None


async def test_items_carry_the_stored_figures(
    entity_client: httpx.AsyncClient, entity_database_url: str
) -> None:
    stored = await rows(entity_database_url, "SELECT * FROM entity")
    listed = {
        item["id"]: item for page in await entity_pages(entity_client, []) for item in page["items"]
    }
    assert set(listed) == {row.id for row in stored}
    for row in stored:
        item = listed[row.id]
        assert item["kind"] == row.kind and item["label"] == row.label
        assert item["detail"] == row.detail and item["currency"] == row.currency
        assert item["value"] == (None if row.value is None else float(row.value))
        assert (item["mails"], item["documents"]) == (row.mails, row.documents)
        for field in ("first_date", "last_date"):
            stamp = getattr(row, field)
            assert item[field] == (
                None if stamp is None else stamp.isoformat().replace("+00:00", "Z")
            )


LIST_CASES: dict[str, tuple[Params, str]] = {
    "part-of-a-label": ([("q", "GMBH")], "label ILIKE '%gmbh%'"),
    "part-with-umlaut": ([("q", "Köl")], "label LIKE '%Köl%'"),
    "percent-is-no-wildcard": ([("q", "%")], "false"),
    "underscore-is-no-wildcard": ([("q", "_")], "false"),
    "blank": ([("q", "  ")], "true"),
    "kind": ([("kind", "amount")], "kind = 'amount'"),
    "kinds": ([("kind", "person"), ("kind", "term")], "kind IN ('person', 'term')"),
    "detail": ([("detail", "spenden")], "detail = 'spenden'"),
    "value-range": (
        [("value_min", "250"), ("value_max", "5000")],
        "value >= 250 AND value <= 5000",
    ),
    "value-fraction": ([("value_min", "1234.561")], "value >= 1234.561"),
    "kind-and-part": ([("kind", "amount"), ("q", "EUR")], "kind = 'amount' AND label LIKE '%EUR%'"),
}


@pytest.mark.parametrize("sort", ["mails", "label", "value"])
@pytest.mark.parametrize("case", list(LIST_CASES))
async def test_list_filters_select_what_sql_selects(
    entity_client: httpx.AsyncClient, entity_database_url: str, case: str, sort: str
) -> None:
    params, where = LIST_CASES[case]
    if sort == "value":
        where = f"({where}) AND value IS NOT NULL"
    expected = await entity_ids(entity_database_url, where, sort)
    assert item_ids(await entity_pages(entity_client, [*params, ("sort", sort)], 2)) == expected


async def test_list_cursor_errors(entity_client: httpx.AsyncClient) -> None:
    page = await get(entity_client, "/api/entities", [("limit", "2")])
    cursor = page["next_cursor"]
    for params in ([("cursor", "nonsense")], [("cursor", cursor), ("sort", "label")]):
        error = await get(entity_client, "/api/entities", params, status=400)
        assert error["detail"]["code"] == "invalid_cursor"
    await get(entity_client, "/api/entities", [("sort", "size")], status=422)
    await get(entity_client, "/api/entities", [("kind", "weapon")], status=422)


@pytest.mark.parametrize("sort", list(ORDER))
async def test_list_jumps_agree_with_its_keyset_pages(
    entity_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, sort: str
) -> None:
    monkeypatch.setattr(paging, "FORWARD_ROWS", 0)  # each jump counts, then the nearer end
    for params in ([], [("q", "e")], [("kind", "amount")]):
        await check_jumps(
            entity_client, "/api/entities", [*params, ("sort", sort)], 3, numbered_last=False
        )


async def test_the_list_counts_itself_where_the_summary_does_not(
    entity_client: httpx.AsyncClient, entity_database_url: str
) -> None:
    # A tab alone: EntitySummary counts it (D193).
    tab = await get(entity_client, "/api/entities", [("kind", "amount")])
    assert (tab["total"], tab["exact"]) == (None, False)
    for params, where in (
        ([("q", "GMBH")], "label ILIKE '%gmbh%'"),
        ([("detail", "spenden")], "detail = 'spenden'"),
        ([("kind", "amount"), ("value_min", "250")], "kind = 'amount' AND value >= 250"),
    ):
        page = await get(entity_client, "/api/entities", [*params, ("limit", "1")])
        expected = len(await entity_ids(entity_database_url, where))
        assert (page["total"], page["exact"]) == (expected, True), params


# Summary and refs ----------------------------------------------------------------------------


async def test_summary_counts_kinds_and_waiting_texts(
    entity_client: httpx.AsyncClient, entity_database_url: str
) -> None:
    kinds = await rows(entity_database_url, "SELECT kind, count(*) AS n FROM entity GROUP BY kind")
    waiting = await rows(
        entity_database_url,
        "SELECT (SELECT count(*) FROM mail m WHERE NOT EXISTS (SELECT 1 FROM mail_entity_scan s"
        "  WHERE s.mail_id = m.id AND s.version = :version)) AS mails,"
        " (SELECT count(*) FROM document d WHERE d.text_status IN ('text', 'timeout')"
        "  AND NOT EXISTS (SELECT 1 FROM document_entity_scan s WHERE s.document_id = d.id"
        "  AND s.version = :version AND s.extracted_at IS NOT DISTINCT FROM d.extracted_at))"
        " AS documents",
        version=scan_version(),
    )
    summary = await get(entity_client, "/api/entities/summary")
    assert summary == {
        "kinds": {kind: dict((row.kind, row.n) for row in kinds).get(kind, 0) for kind in KINDS},
        "mails_waiting": waiting[0].mails,
        "documents_waiting": waiting[0].documents,
    }
    assert 0 < summary["mails_waiting"] < 600 and summary["documents_waiting"] > 0


async def test_refs_in_the_order_asked(entity_client: httpx.AsyncClient) -> None:
    refs = await get(
        entity_client,
        "/api/entities/refs",
        [("id", "6"), ("id", "999"), ("id", "2"), ("id", "6"), ("id", str(2**70))],
    )
    assert refs == [
        {"id": 6, "kind": "organization", "label": "Muster GmbH", "detail": None},
        {"id": 2, "kind": "amount", "label": "1.234,56 EUR", "detail": None},
    ]
    assert await get(entity_client, "/api/entities/refs") == []
    many = [("id", str(i)) for i in range(ENTITY_REFS_LIMIT + 1)]
    error = await get(entity_client, "/api/entities/refs", many, status=400)
    assert error["detail"]["code"] == "invalid_filter"
    assert len(await get(entity_client, "/api/entities/refs", many[:-1])) == 19


# One entity ----------------------------------------------------------------------------------


async def detail(client: httpx.AsyncClient, entity_id: int) -> Item:
    found: Item = await get(client, f"/api/entities/{entity_id}")
    return found


async def expected_persons(url: str, entity_id: int) -> tuple[list[tuple[int, int]], ...]:
    """(root, mails) of the senders and of the recipients, most mails first, then by root."""
    found = await rows(
        url,
        "SELECT coalesce(p.merged_into, p.id) AS root, pa.role = 'from' AS sent,"
        " count(DISTINCT pa.mail_id) AS mails FROM participation pa"
        " JOIN person p ON p.id = pa.person_id"
        f" WHERE pa.mail_id IN ({COUNTED}) GROUP BY 1, 2",
        entity=entity_id,
    )
    senders = sorted(((r.root, r.mails) for r in found if r.sent), key=lambda r: (-r[1], r[0]))
    recipients = sorted(
        ((r.root, r.mails) for r in found if not r.sent), key=lambda r: (-r[1], r[0])
    )
    return senders, recipients


@pytest.mark.parametrize("entity_id", [1, 2, 3, 6, 7, 9, 16, 17])
async def test_the_page_of_an_entity(
    entity_client: httpx.AsyncClient, entity_database_url: str, entity_id: int
) -> None:
    page = await detail(entity_client, entity_id)
    stored = (await rows(entity_database_url, "SELECT * FROM entity WHERE id = :e", e=entity_id))[0]
    assert (page["key"], page["label"], page["mails"]) == (stored.key, stored.label, stored.mails)
    contexts = await rows(
        entity_database_url,
        "SELECT count(*) FILTER (WHERE c & 1 <> 0) AS cash,"
        " count(*) FILTER (WHERE c & 2 <> 0) AS donation,"
        " count(*) FILTER (WHERE c & 4 <> 0) AS receipt"
        f" FROM (SELECT x.mail_id, bit_or(x.context) AS c FROM {MENTIONS} x"
        f" WHERE x.mail_id IN ({COUNTED}) AND x.entity_id = :entity GROUP BY 1) y",
        entity=entity_id,
    )
    assert page["contexts"] == dict(contexts[0]._mapping)
    years = await rows(
        entity_database_url,
        "SELECT date_part('year', date_utc AT TIME ZONE 'UTC')::integer AS year,"
        f" count(*) AS mails FROM mail WHERE id IN ({COUNTED}) AND date_utc IS NOT NULL"
        " GROUP BY 1 ORDER BY 1",
        entity=entity_id,
    )
    assert page["years"] == [{"year": row.year, "mails": row.mails} for row in years]
    assert sum(year["mails"] for year in page["years"]) <= stored.mails
    senders, recipients = await expected_persons(entity_database_url, entity_id)
    assert [(p["person"]["person_id"], p["mails"]) for p in page["senders"]] == (
        senders[:ENTITY_PERSONS_LIMIT]
    )
    assert [(p["person"]["person_id"], p["mails"]) for p in page["recipients"]] == (
        recipients[:ENTITY_PERSONS_LIMIT]
    )
    assert (page["sender_count"], page["recipient_count"]) == (len(senders), len(recipients))
    assert page["persons_sampled"] is False
    related = await rows(
        entity_database_url,
        f"SELECT x.entity_id AS id, count(DISTINCT x.mail_id) AS mails FROM {MENTIONS} x"
        f" WHERE x.mail_id IN ({COUNTED}) AND x.entity_id <> :entity GROUP BY 1",
        entity=entity_id,
    )
    expected = sorted(((row.id, row.mails) for row in related), key=lambda r: (-r[1], -r[0]))
    assert [(c["entity"]["id"], c["mails"]) for c in page["related"]] == (
        expected[:ENTITY_RELATED_LIMIT]
    )
    await check_samples(entity_database_url, entity_id, page["samples"])


async def check_samples(url: str, entity_id: int, samples: list[Item]) -> None:
    """The earliest mentioning mails that are no duplicates, undated ones last, with the text
    around the mention: the mail's own, else in the document of the lowest id."""
    earliest = await rows(
        url,
        f"SELECT id, subject FROM mail WHERE id IN ({COUNTED})"
        " ORDER BY date_utc ASC NULLS LAST, id LIMIT :n",
        entity=entity_id,
        n=ENTITY_SAMPLES,
    )
    assert [sample["mail"]["id"] for sample in samples] == [row.id for row in earliest]
    for sample, mail in zip(samples, earliest, strict=True):
        assert sample["mail"]["subject"] == mail.subject
        shown = await rows(
            url,
            "SELECT * FROM (SELECT me.position, NULL::bigint AS document_id, NULL AS name,"
            " concat(m.subject, E'\\n', m.body_text) AS text FROM mail_entity me"
            " JOIN mail m ON m.id = me.mail_id WHERE me.entity_id = :entity AND me.mail_id = :mail"
            " UNION ALL SELECT de.position, d.id, d.name, d.extracted_text FROM attachment a"
            " JOIN document_entity de ON de.document_id = a.document_id"
            " JOIN document d ON d.id = de.document_id"
            " WHERE de.entity_id = :entity AND a.mail_id = :mail) x"
            " ORDER BY document_id NULLS FIRST LIMIT 1",
            entity=entity_id,
            mail=mail.id,
        )
        assert (sample["document_id"], sample["document_name"]) == (
            shown[0].document_id,
            shown[0].name,
        )
        check_snippet(sample["snippet"], shown[0].text, shown[0].position)


def check_snippet(snippet: str | None, stored: str, position: int) -> None:
    collapsed = " ".join(stored.split())
    if not collapsed:
        assert snippet is None
        return
    assert snippet is not None and len(snippet) <= ENTITY_SNIPPET_LENGTH
    core = snippet.removeprefix(ELLIPSIS).removesuffix(ELLIPSIS)
    assert core and core in collapsed
    assert " ".join(stored[position : position + 40].split())[:12] in core
    assert snippet.startswith(ELLIPSIS) == (not collapsed.startswith(core))
    assert snippet.endswith(ELLIPSIS) == (not collapsed.endswith(core))


async def test_archive_persons(entity_client: httpx.AsyncClient, entity_database_url: str) -> None:
    named = await rows(
        entity_database_url,
        "SELECT p.id, p.canonical_email, p.display_name FROM entity e"
        " JOIN person p ON lower(p.display_name) = e.key WHERE e.id = 7",
    )
    assert len(named) == 1  # the label is the name in capitals
    assert (await detail(entity_client, 7))["archive_person"] == {
        "person_id": named[0].id,
        "email": named[0].canonical_email,
        "name": named[0].display_name,
        "label": None,
    }
    assert (await detail(entity_client, 8))["archive_person"] is None  # several have the name
    root = await rows(
        entity_database_url,
        "SELECT r.id, r.canonical_email, r.display_name FROM entity e"
        " JOIN person_email pe ON pe.email = e.key JOIN person p ON p.id = pe.person_id"
        " JOIN person r ON r.id = p.merged_into WHERE e.id = 9",
    )
    assert (await detail(entity_client, 9))["archive_person"] == {
        "person_id": root[0].id,
        "email": root[0].canonical_email,
        "name": root[0].display_name,
        "label": None,
    }
    assert (await detail(entity_client, 6))["archive_person"] is None


async def test_samples_put_undated_mails_last_and_cut_deep_mentions(
    entity_client: httpx.AsyncClient, entity_database_url: str
) -> None:
    person = await detail(entity_client, 7)  # in the original mails k = 10, 20, 30; 10 undated
    assert [sample["mail"]["date"] is None for sample in person["samples"]] == [False, False, True]
    amount = await detail(entity_client, 3)  # 301 characters into the longer bodies
    assert any(sample["snippet"].startswith(ELLIPSIS) for sample in amount["samples"])
    document = await detail(entity_client, 2)  # at the start of the document carried most
    assert all(sample["document_id"] is not None for sample in document["samples"])
    assert all(not sample["snippet"].startswith(ELLIPSIS) for sample in document["samples"])


async def test_persons_and_related_over_a_sample(
    entity_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entities, "FACET_MAILS", 5)
    page = await detail(entity_client, 6)
    assert page["persons_sampled"] is True
    assert all(p["mails"] <= 5 for p in [*page["senders"], *page["recipients"]])
    assert all(c["mails"] <= 5 for c in page["related"])
    assert page["mails"] > 5 and sum(year["mails"] for year in page["years"]) > 5  # all counted


async def test_entity_errors(entity_client: httpx.AsyncClient) -> None:
    error = await get(entity_client, "/api/entities/999", status=404)
    assert error["detail"]["code"] == "not_found"
    await get(entity_client, "/api/entities/x", status=422)
    await get(entity_client, f"/api/entities/{2**63}", status=422)


# "w000 w001 ... w199": word i at 5 i
WORDS = " ".join(f"w{i:03}" for i in range(200))


def words(start: int, stop: int) -> str:
    return " ".join(f"w{i:03}" for i in range(start, stop))


@pytest.mark.parametrize(
    ("around", "at", "cut", "expected"),
    [
        ("Betreff\nHallo   Welt,\n\nbitte zahlen", 8, False, "Betreff Hallo Welt, bitte zahlen"),
        ("", 0, False, None),
        ("\n", 0, False, None),
        ("x" * 50 + " Spende " + "y" * 20, 51, True, ELLIPSIS + "Spende " + "y" * 20),
        (WORDS[: 2 * ENTITY_SNIPPET_LENGTH + 1], 0, False, words(0, 40) + ELLIPSIS),
        (
            WORDS[300 : 300 + 2 * ENTITY_SNIPPET_LENGTH + 1],  # 200 characters before w100
            ENTITY_SNIPPET_LENGTH,
            True,
            ELLIPSIS + words(90, 129) + ELLIPSIS,
        ),
    ],
    ids=["whole-text", "empty", "blank", "cut-before", "cut-after", "cut-both"],
)
def test_mention_snippet(around: str, at: int, cut: bool, expected: str | None) -> None:
    snippet = mention_snippet(around, at, cut)
    assert snippet == expected
    assert snippet is None or len(snippet) <= ENTITY_SNIPPET_LENGTH


# Entities of one mail ------------------------------------------------------------------------


async def test_the_entities_of_a_mail(
    entity_client: httpx.AsyncClient, entity_database_url: str
) -> None:
    both = await rows(
        entity_database_url,
        "SELECT me.mail_id FROM mail_entity me JOIN attachment a ON a.mail_id = me.mail_id"
        " JOIN document_entity de ON de.document_id = a.document_id AND de.entity_id = 6"
        " WHERE me.entity_id = 6 ORDER BY 1 LIMIT 1",
    )
    assert both, "a mail with entity 6 in its text and in an attachment"
    mails = [both[0].mail_id, *(await ids(entity_database_url, "true"))[:40]]
    for mail_id in mails:
        expected = await rows(
            entity_database_url,
            "SELECT DISTINCT e.id, e.kind, e.label, e.detail, x.occurrences, x.context,"
            " x.document_id, d.name AS document_name FROM (SELECT entity_id, mail_id, occurrences,"
            " context, NULL::bigint AS document_id FROM mail_entity UNION ALL SELECT de.entity_id,"
            " a.mail_id, de.occurrences, de.context, de.document_id FROM document_entity de"
            " JOIN attachment a ON a.document_id = de.document_id) x"
            " JOIN entity e ON e.id = x.entity_id LEFT JOIN document d ON d.id = x.document_id"
            " WHERE x.mail_id = :mail",
            mail=mail_id,
        )
        order = sorted(
            expected,
            key=lambda r: (
                KINDS.index(r.kind),
                -r.occurrences,
                r.label,
                r.document_id is not None,
                r.document_id or 0,
                r.id,
            ),
        )
        found = await get(entity_client, f"/api/mails/{mail_id}/entities")
        assert found == [
            {
                "entity": {"id": r.id, "kind": r.kind, "label": r.label, "detail": r.detail},
                "occurrences": r.occurrences,
                "context": [
                    key
                    for bit, key in ((1, "cash"), (2, "donation"), (4, "receipt"))
                    if r.context & bit
                ],
                "document_id": r.document_id,
                "document_name": r.document_name,
            }
            for r in order
        ]
    first = await get(entity_client, f"/api/mails/{both[0].mail_id}/entities")
    sources = [item["document_id"] for item in first if item["entity"]["id"] == 6]
    assert len(sources) == 2 and None in sources  # in the text and in an attachment
    error = await get(entity_client, "/api/mails/987654321/entities", status=404)
    assert error["detail"]["code"] == "not_found"


# Facets ---------------------------------------------------------------------------------------


async def expected_facets(url: str, where: str, limit: int = FACET_LIMIT, **params: Any) -> Any:
    """Per kind, the entities most mentioned in the matching mails, with those mails."""
    found = await rows(
        url,
        f"SELECT e.id, e.kind, count(DISTINCT x.mail_id) AS mails FROM {MENTIONS} x"
        " JOIN entity e ON e.id = x.entity_id"
        f" WHERE x.mail_id IN (SELECT id FROM mail WHERE {where}) GROUP BY e.id, e.kind",
        **params,
    )
    kinds: defaultdict[str, list[tuple[int, int]]] = defaultdict(list)
    for row in sorted(found, key=lambda r: (KINDS.index(r.kind), -r.mails, -r.id)):
        kinds[row.kind].append((row.id, row.mails))
    return {kind: counts[:limit] for kind, counts in kinds.items()}


def counts(facets: Item) -> dict[str, list[tuple[int, int]]]:
    return {
        kind: [(c["entity"]["id"], c["mails"]) for c in found]
        for kind, found in facets["kinds"].items()
    }


async def test_facets_without_filters_are_the_stored_figures(
    entity_client: httpx.AsyncClient, entity_database_url: str
) -> None:
    for limit in (FACET_LIMIT, 1):
        stored = await rows(
            entity_database_url,
            "SELECT id, kind, mails FROM entity WHERE mails > 0 ORDER BY mails DESC, id DESC",
        )
        expected: defaultdict[str, list[tuple[int, int]]] = defaultdict(list)
        for row in sorted(stored, key=lambda r: KINDS.index(r.kind)):
            if len(expected[row.kind]) < limit:
                expected[row.kind].append((row.id, row.mails))
        facets = await get(entity_client, "/api/mails/facets", [("limit", str(limit)), ("q", " ")])
        assert (facets["mails"], facets["sampled"]) == (None, False)
        assert counts(facets) == expected
        assert list(facets["kinds"]) == [kind for kind in KINDS if kind in expected]
    only = await get(
        entity_client, "/api/mails/facets", [("kind", "term"), ("kind", "amount"), ("limit", "2")]
    )
    assert list(only["kinds"]) == ["amount", "term"]
    assert only["kinds"]["amount"][0]["entity"] == {
        "id": 1,
        "kind": "amount",
        "label": "5.000,00 EUR",
        "detail": None,
    }


FACET_CASES: dict[str, tuple[Params, str]] = {
    "entity": ([("entity", "1")], MENTIONED.format(1)),
    "word": (
        [("q", "Angebot")],
        "tsv @@ websearch_to_tsquery('german', 'Angebot')"
        " OR id IN (SELECT a.mail_id FROM attachment a JOIN document d ON d.id = a.document_id"
        " WHERE d.tsv @@ websearch_to_tsquery('german', 'Angebot'))",
    ),
    "duplicates-hidden": (
        [("entity", "6"), ("hide_duplicates", "true")],
        f"{MENTIONED.format(6)} AND is_duplicate_of IS NULL",
    ),
    "dkim": ([("dkim", "pass")], "dkim_status = 'pass'"),
    "nothing": ([("entity", "999")], "false"),
}


@pytest.mark.parametrize("case", list(FACET_CASES))
async def test_facets_count_the_mails_of_a_filter(
    entity_client: httpx.AsyncClient, entity_database_url: str, case: str
) -> None:
    params, where = FACET_CASES[case]
    matched = await ids(entity_database_url, where)
    facets = await get(entity_client, "/api/mails/facets", params)
    assert (facets["mails"], facets["sampled"]) == (len(matched), False)
    assert counts(facets) == await expected_facets(entity_database_url, where)
    limited = await get(
        entity_client, "/api/mails/facets", [*params, ("limit", "50"), ("kind", "organization")]
    )
    expected = await expected_facets(entity_database_url, where, 50)
    assert counts(limited) == {k: v for k, v in expected.items() if k == "organization"}


async def test_facets_of_a_large_filter_count_a_sample(
    entity_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entities, "FACET_MAILS", 50)
    facets = await get(entity_client, "/api/mails/facets", [("entity", "6")])
    assert (facets["mails"], facets["sampled"]) == (50, True)
    assert facets["kinds"]["organization"][0] == {
        "entity": {"id": 6, "kind": "organization", "label": "Muster GmbH", "detail": None},
        "mails": 50,
    }
    assert all(c["mails"] <= 50 for found in facets["kinds"].values() for c in found)


async def test_facets_fall_back_to_a_smaller_sample(
    entity_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    run = documents._all_unless_canceled

    async def first_canceled(*args: Any) -> Any:
        calls.append(1)
        return None if len(calls) == 2 else await run(*args)  # the counting of FACET_MAILS

    monkeypatch.setattr(entities, "_all_unless_canceled", first_canceled)
    monkeypatch.setattr(entities, "FACET_FALLBACK", 20)
    facets = await get(entity_client, "/api/mails/facets", [("entity", "6")])
    assert (facets["mails"], facets["sampled"]) == (20, True)
    assert facets["kinds"]["organization"][0]["mails"] == 20
    assert len(calls) == 3

    async def canceled(*_: Any) -> None:
        return None

    monkeypatch.setattr(entities, "_all_unless_canceled", canceled)
    facets = await get(entity_client, "/api/mails/facets", [("entity", "6")])
    assert facets == {"kinds": {}, "mails": None, "sampled": False}


async def test_facets_run_out_of_time(
    entity_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    settings = api_settings(entity_database_url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(update={"api_count_timeout": 0.3})
    engine = create_async_engine(entity_database_url, poolclass=pool.NullPool)
    try:
        async for client in _client(settings):
            async with engine.connect() as other:
                # The counting reads mail_entity: it waits, twice, and there are no facets.
                await other.execute(text("LOCK TABLE mail_entity IN ACCESS EXCLUSIVE MODE"))
                facets = await get(client, "/api/mails/facets", [("entity", "16")])
                assert facets == {"kinds": {}, "mails": None, "sampled": False}
                # The figures of entity, unfiltered, are not in the way.
                assert (await get(client, "/api/mails/facets"))["kinds"]
                await other.rollback()
            facets = await get(client, "/api/mails/facets", [("entity", "16")])
            assert facets["mails"] == 3 and facets["kinds"]
    finally:
        await engine.dispose()


async def test_facets_take_the_list_errors(entity_client: httpx.AsyncClient) -> None:
    error = await get(entity_client, "/api/mails/facets", [("q", "dkim:maybe")], status=400)
    assert error["detail"]["code"] == "invalid_query"
    error = await get(entity_client, "/api/mails/facets", [("person_role", "sent")], status=400)
    assert error["detail"]["code"] == "invalid_filter"
    await get(entity_client, "/api/mails/facets", [("limit", "51")], status=422)

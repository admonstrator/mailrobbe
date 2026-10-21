"""The mail list's entity filters (D86): entity, amount_min and amount_context in the list, its
summary, the neighbours, the CSV export and the selection of bulk changes and exports.

The archive is the imported one with the synthetic entities of tests/api/conftest.py
(ENTITY_ROWS). Expected results come from SQL on the mention tables written apart from
api/filters.py. WALK_ROWS is lowered in some tests, so that the bounded walk runs out and every
match is collected; first_ids's two paths are watched where it matters which one ran.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailrobbe.api import filters
from mailrobbe.api.schemas import MailFilters, MailSelection
from mailrobbe.api.selection import resolve_selection
from mailrobbe.config import Settings
from tests.api.test_mails import Params, export, get, ids, listed, page_ids, pages, rows

pytestmark = pytest.mark.db

# Every mention: in the mail's own text, or in a document one of its attachments carries.
MENTIONS = (
    "(SELECT entity_id, mail_id, context FROM mail_entity UNION ALL"
    " SELECT de.entity_id, a.mail_id, de.context FROM document_entity de"
    " JOIN attachment a ON a.document_id = de.document_id)"
)
MENTIONED = f"id IN (SELECT mail_id FROM {MENTIONS} x WHERE x.entity_id = {{}})"
AMOUNT = (
    f"id IN (SELECT x.mail_id FROM {MENTIONS} x JOIN entity e ON e.id = x.entity_id"
    " WHERE e.kind = 'amount' AND {})"
)
WORD = (
    "(tsv @@ websearch_to_tsquery('german', 'Angebot') OR id IN (SELECT a.mail_id"
    " FROM attachment a JOIN document d ON d.id = a.document_id"
    " WHERE d.tsv @@ websearch_to_tsquery('german', 'Angebot')))"
)
WITH_PERSON = (
    "id IN (SELECT pa.mail_id FROM participation pa JOIN person p ON p.id = pa.person_id"
    " WHERE p.id = :person OR p.merged_into = :person)"
)
CARRIES = "id IN (SELECT mail_id FROM attachment WHERE document_id = :document)"
# (parameters, SQL on mail). Entity 6 is in a third of the mails and in the document carried
# most, 2 only in that document, 1 in the mails' texts and in another document, 16 in the three
# oldest mails, 999 does not exist; amounts 1 to 4 and 17 carry contexts (ENTITY_ROWS).
CASES: dict[str, tuple[Params, str]] = {
    "common": ([("entity", "6")], MENTIONED.format(6)),
    "through-a-document": ([("entity", "2")], MENTIONED.format(2)),
    "text-and-document": ([("entity", "1")], MENTIONED.format(1)),
    "two-entities": (
        [("entity", "6"), ("entity", "1")],
        f"{MENTIONED.format(6)} AND {MENTIONED.format(1)}",
    ),
    "same-entity-twice": ([("entity", "1"), ("entity", "1")], MENTIONED.format(1)),
    "rare": ([("entity", "16")], MENTIONED.format(16)),
    "unknown": ([("entity", "999")], "false"),
    "beyond-bigint": ([("entity", str(2**70))], "false"),
    "unknown-and-common": ([("entity", "6"), ("entity", "999")], "false"),
    "amount-min": ([("amount_min", "1000")], AMOUNT.format("e.value >= 1000")),
    "amount-min-fraction": ([("amount_min", "1234.561")], AMOUNT.format("e.value >= 1234.561")),
    "amount-min-zero": ([("amount_min", "0")], AMOUNT.format("true")),
    "amount-min-huge": ([("amount_min", "1e30")], "false"),
    "cash": ([("amount_context", "cash")], AMOUNT.format("x.context & 1 <> 0")),
    "donation-or-receipt": (
        [("amount_context", "donation"), ("amount_context", "receipt")],
        AMOUNT.format("x.context & 6 <> 0"),
    ),
    "amount-min-and-receipt": (
        [("amount_min", "1000"), ("amount_context", "receipt")],
        AMOUNT.format("e.value >= 1000 AND x.context & 4 <> 0"),
    ),
    "entity-and-date": (
        [("entity", "6"), ("date_from", "2020-01-01")],
        f"{MENTIONED.format(6)} AND date_utc >= '2020-01-01'",
    ),
    "entity-and-word": ([("entity", "6"), ("q", "Angebot")], f"{MENTIONED.format(6)} AND {WORD}"),
    "entity-and-dkim": (
        [("entity", "13"), ("dkim", "pass")],
        f"{MENTIONED.format(13)} AND dkim_status = 'pass'",
    ),
    "amount-and-attachment": (
        [("amount_context", "cash"), ("q", "has:attachment")],
        f"{AMOUNT.format('x.context & 1 <> 0')} AND has_attachments",
    ),
    "entity-without-duplicates": (
        [("entity", "6"), ("hide_duplicates", "true")],
        f"{MENTIONED.format(6)} AND is_duplicate_of IS NULL",
    ),
}


@pytest.fixture
def walk_rows(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(filters, "WALK_ROWS", request.param)
    return int(request.param)


WALKS = pytest.mark.parametrize(
    "walk_rows", [filters.WALK_ROWS, 7], ids=["default", "short-walk"], indirect=True
)


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


async def busiest_person(url: str) -> int:
    found = await rows(
        url,
        "SELECT person_id FROM participation GROUP BY person_id"
        " ORDER BY count(DISTINCT mail_id) DESC, person_id LIMIT 1",
    )
    return int(found[0].person_id)


async def busiest_document(url: str) -> int:
    found = await rows(url, "SELECT id FROM document ORDER BY mails DESC, id LIMIT 1")
    return int(found[0].id)


# List and summary ----------------------------------------------------------------------------


@WALKS
@pytest.mark.parametrize("sort", ["date_desc", "date_asc"])
@pytest.mark.parametrize("case", list(CASES))
async def test_entity_filters_select_what_sql_selects(
    entity_client: httpx.AsyncClient,
    entity_database_url: str,
    walk_rows: int,
    sort: str,
    case: str,
) -> None:
    params, where = CASES[case]
    expected = await ids(entity_database_url, where, sort)
    assert await listed(entity_client, [*params, ("sort", sort)]) == expected
    summary = await get(entity_client, "/api/mails/summary", params)
    assert (summary["total"], summary["exact"]) == (len(expected), True)


async def test_the_cases_are_not_empty(entity_database_url: str) -> None:
    """Guards the expectations above: each case that should match does."""
    for case, (_, where) in CASES.items():
        if where != "false" and case != "amount-min-huge":
            assert await ids(entity_database_url, where), case


@WALKS
async def test_with_a_person_and_a_document(
    entity_client: httpx.AsyncClient, entity_database_url: str, walk_rows: int
) -> None:
    person = await busiest_person(entity_database_url)
    document = await busiest_document(entity_database_url)
    for params, where in [
        ([("entity", "6"), ("person", str(person))], f"{MENTIONED.format(6)} AND {WITH_PERSON}"),
        (
            [("amount_min", "0"), ("person", str(person))],
            f"{AMOUNT.format('true')} AND {WITH_PERSON}",
        ),
        ([("entity", "1"), ("document", str(document))], f"{MENTIONED.format(1)} AND {CARRIES}"),
        ([("entity", "2"), ("document", str(document))], f"{MENTIONED.format(2)} AND {CARRIES}"),
    ]:
        expected = await ids(entity_database_url, where, person=person, document=document)
        assert await listed(entity_client, params) == expected, params
        summary = await get(entity_client, "/api/mails/summary", params)
        assert summary["total"] == len(expected)


async def test_a_common_entity_fills_its_pages_by_walking(
    entity_client: httpx.AsyncClient, entity_database_url: str, collections: list[int]
) -> None:
    """The walk form finds the matches itself: no page falls back to collecting them."""
    for params, where in [CASES["common"], CASES["amount-min-zero"], CASES["two-entities"]]:
        expected = await ids(entity_database_url, where)
        found = await pages(entity_client, params, 10)
        assert [mail_id for page in found[:-1] for mail_id in page_ids(page)] == (
            expected[: 10 * (len(found) - 1)]
        )
        assert len(found) > 2
    assert collections == [1, 1, 1]  # only the last, short page of each list


async def test_a_rare_entity_beyond_the_walk_is_collected(
    entity_client: httpx.AsyncClient,
    entity_database_url: str,
    collections: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entity 16 is in the three oldest mails, behind the newest WALK_ROWS of date_desc."""
    monkeypatch.setattr(filters, "WALK_ROWS", 100)
    expected = await ids(entity_database_url, MENTIONED.format(16))
    page = await get(entity_client, "/api/mails", CASES["rare"][0])
    assert page_ids(page) == expected and len(expected) == 3
    assert collections == [1]


async def test_amount_parameters_are_checked(entity_client: httpx.AsyncClient) -> None:
    await get(entity_client, "/api/mails", [("amount_min", "-1")], status=422)
    await get(entity_client, "/api/mails", [("amount_context", "bribe")], status=422)
    await get(entity_client, "/api/mails", [("entity", "x")], status=422)
    assert (await get(entity_client, "/api/mails", [("amount_min", "inf")]))["items"] == []


# Neighbours, CSV, selection --------------------------------------------------------------------


@WALKS
@pytest.mark.parametrize("case", ["text-and-document", "amount-min-and-receipt"])
async def test_neighbours_agree_with_the_pages(
    entity_client: httpx.AsyncClient, walk_rows: int, case: str
) -> None:
    params = CASES[case][0]
    found = await listed(entity_client, params)
    assert len(found) > 2
    for index in sorted({0, 1, len(found) // 2, len(found) - 1}):
        neighbours = await get(entity_client, f"/api/mails/{found[index]}/neighbors", params)
        assert neighbours == {
            "prev_id": found[index - 1] if index > 0 else None,
            "next_id": found[index + 1] if index + 1 < len(found) else None,
            "position": index + 1,
        }


async def test_csv_holds_the_filtered_list(
    entity_client: httpx.AsyncClient, entity_database_url: str
) -> None:
    params, where = CASES["donation-or-receipt"]
    exported = await export(entity_client, [*params, ("sort", "date_asc")])
    assert [int(row[0]) for row in exported] == await ids(entity_database_url, where, "date_asc")


@pytest.fixture
async def entity_session(entity_database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(entity_database_url, poolclass=pool.NullPool)
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()


async def test_bulk_changes_and_exports_select_the_filtered_mails(
    entity_session: AsyncSession, entity_database_url: str
) -> None:
    settings = Settings(database_url=entity_database_url)
    selection = MailSelection(filters=MailFilters(entity=[1], amount_context=["cash"]))
    mails = await resolve_selection(entity_session, settings, selection, 10_000)
    where = f"{MENTIONED.format(1)} AND {AMOUNT.format('x.context & 1 <> 0')}"
    assert [mail.id for mail in mails] == await ids(entity_database_url, where, "date_asc")

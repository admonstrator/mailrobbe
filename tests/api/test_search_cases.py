"""The search cases (tests/api/search_cases.py) and the SQL helpers of api/fulltext.py."""

import httpx
import pytest
from sqlalchemy import Text, cast, func, literal, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.fulltext import TEXT_SEARCH, Words, ts_query, weighted, word_regex
from tests.api.conftest import search_ids


async def test_neger_finds_stems_and_file_names(search_client: httpx.AsyncClient) -> None:
    ids = await search_ids(search_client)
    assert len(ids) == 10
    page = (await search_client.get("/api/mails", params={"q": "Neger", "sort": "date_asc"})).json()
    found = {item["id"] for item in page["items"]}
    assert found == {ids[n] for n in range(8)}


@pytest.mark.parametrize(
    ("text", "weights", "found"),
    [
        ("Neger", "A", True),
        ("Neger", "B", False),
        ("Negern", "AB", True),
    ],
)
async def test_weighted(db_session: AsyncSession, text: str, weights: str, found: bool) -> None:
    vector = func.setweight(func.to_tsvector(TEXT_SEARCH, text), literal_column("'A'::\"char\""))
    query = weighted(ts_query("Neger"), weights)
    assert await db_session.scalar(select(vector.bool_op("@@")(query))) is found


async def test_weighted_phrases(db_session: AsyncSession) -> None:
    query = weighted(ts_query('"großer Austausch"'), "B")
    assert await db_session.scalar(select(cast(query, Text))) == "'gross':B <-> 'austausch':B"


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Neger", 1),
        ("NEGER! die Neger-Witze, Scan_NEGER_01", 3),
        ("Negern Negerin negere Kneger Neger1 négère", 0),
    ],
)
async def test_word_regex(db_session: AsyncSession, text: str, found: int) -> None:
    count = func.regexp_count(literal(text), word_regex(Words("Neger")), 1, "i")
    assert await db_session.scalar(select(count)) == found


async def test_word_regex_accents(db_session: AsyncSession) -> None:
    count = func.regexp_count(literal("Négère NÉGÈRE negere"), word_regex(Words("négère")), 1, "i")
    assert await db_session.scalar(select(count)) == 2

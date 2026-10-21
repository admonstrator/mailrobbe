from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailrobbe.api.schemas import MailFilters, MailSelection
from mailrobbe.api.selection import resolve_selection
from mailrobbe.config import Settings

pytestmark = pytest.mark.db


@pytest.fixture
async def session(imported_database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(imported_database_url, poolclass=pool.NullPool)
    async with AsyncSession(engine) as db:
        yield db
    await engine.dispose()


@pytest.fixture
def settings(imported_database_url: str) -> Settings:
    return Settings(database_url=imported_database_url)


async def _code(session: AsyncSession, settings: Settings, selection: MailSelection, limit: int):
    with pytest.raises(HTTPException) as raised:
        await resolve_selection(session, settings, selection, limit)
    detail = raised.value.detail
    assert isinstance(detail, dict)
    return raised.value.status_code, detail["code"]


async def test_filters_select_the_mails_the_list_shows_oldest_first(
    session: AsyncSession, settings: Settings, client: httpx.AsyncClient
) -> None:
    params = {"dkim": "pass", "sort": "date_asc", "limit": "200"}
    listed = [
        item["id"] for item in (await client.get("/api/mails", params=params)).json()["items"]
    ]
    selection = MailSelection(filters=MailFilters(dkim=["pass"]))
    mails = await resolve_selection(session, settings, selection, 10_000)
    assert [mail.id for mail in mails[:200]] == listed
    assert all(len(mail.raw_sha256) == 64 for mail in mails)


async def test_ids_come_in_list_order_whatever_the_given_order(
    session: AsyncSession, settings: Settings
) -> None:
    everything = await resolve_selection(
        session, settings, MailSelection(filters=MailFilters()), 10_000
    )
    picked = [everything[9].id, everything[2].id, everything[5].id, everything[2].id]
    mails = await resolve_selection(session, settings, MailSelection(ids=picked), 10)
    assert mails == [everything[2], everything[5], everything[9]]


async def test_errors(session: AsyncSession, settings: Settings) -> None:
    some = await resolve_selection(session, settings, MailSelection(filters=MailFilters()), 10_000)
    ids = [mail.id for mail in some[:3]]
    assert await _code(session, settings, MailSelection(), 10) == (400, "invalid_selection")
    both = MailSelection(ids=ids, filters=MailFilters())
    assert await _code(session, settings, both, 10) == (400, "invalid_selection")
    assert await _code(session, settings, MailSelection(ids=[*ids, 987654321]), 10) == (
        404,
        "not_found",
    )
    assert await _code(session, settings, MailSelection(ids=ids), 2) == (400, "too_many_mails")
    nothing = MailSelection(filters=MailFilters(q="Wortohnetreffer"))
    assert await _code(session, settings, nothing, 10) == (400, "empty_selection")
    broken = MailSelection(filters=MailFilters(q="dkim:maybe"))
    assert await _code(session, settings, broken, 10) == (400, "invalid_query")
    role = MailSelection(filters=MailFilters(person_role="sent"))
    assert await _code(session, settings, role, 10) == (400, "invalid_filter")

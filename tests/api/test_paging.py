"""Jumps to a page by number (D193, api/paging.py): the rule of the nearer end on a list in memory,
and the mail list's jumps against its keyset pages, with filters, a search, research filters
and hidden mails. check_jumps is the test every list that jumps runs (persons, documents and
entities in their own test modules).

paging.FORWARD_ROWS is lowered to 0 in some tests, so that every jump counts the list first and
reads the pages of its second half from the end, as a jump far into a large archive does;
WALK_ROWS is lowered (walk_rows) so that jumps read by OFFSET instead of the bounded walk.
"""

import contextlib
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import Executable, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api import documents, filters, mails, paging
from mailrobbe.config import Settings
from tests.api.conftest import _client, api_settings
from tests.api.test_mails import Params, at, get, rows
from tests.conftest import GeneratedArchive

LIMIT = 97  # not a divisor of the number of mails, so the last page is short


# The rule, on a list in memory ----------------------------------------------------------------


class _Session:
    """Just enough of a session for a jump that is given its total: the statement timeout."""

    async def scalar(self, statement: object) -> str:
        return "0"

    async def execute(self, statement: object) -> None:
        return None

    def begin_nested(self) -> contextlib.nullcontext[None]:
        return contextlib.nullcontext()


def _reader(rows: Sequence[int], reads: list[tuple[int, int, bool]]) -> paging.Read:
    async def read(offset: int, limit: int, reverse: bool) -> list[int]:
        reads.append((offset, limit, reverse))
        ordered = list(reversed(rows)) if reverse else list(rows)
        return ordered[offset : offset + limit]

    return read


async def _jump(
    rows: Sequence[int], page: int | None, last: bool, limit: int, *, total: bool
) -> tuple[paging.Jump, list[tuple[int, int, bool]]]:
    """A jump over rows, given their total or (total false) a count statement it must not run."""
    reads: list[tuple[int, int, bool]] = []
    session = cast(AsyncSession, _Session())
    count: Executable | int = len(rows) if total else select(1)
    jumped = await paging.jump(
        session, Settings(), _reader(rows, reads), count, page=page, last=last, limit=limit
    )
    return jumped, reads


@pytest.mark.parametrize("total", [0, 1, 7, 70, 71, 1000])
async def test_a_jump_passes_at_most_half_the_list(total: int) -> None:
    rows = list(range(100, 100 + total))
    limit = 7
    pages = max(1, -(-total // limit))
    for page in range(1, pages + 3):
        jumped, reads = await _jump(rows, page, False, limit, total=True)
        number = min(page, pages)
        assert jumped.page == number
        assert jumped.rows == rows[(number - 1) * limit : number * limit]
        assert jumped.before == (number > 1)
        assert jumped.after == (number < pages)
        assert all(offset <= total / 2 for offset, _, _ in reads), (page, reads)
        # From the end where fewer rows lie behind the page than before it.
        behind = total - (number - 1) * limit - len(jumped.rows)
        assert any(reverse for _, _, reverse in reads) == ((number - 1) * limit > behind)


async def test_the_last_page_with_and_without_a_total() -> None:
    rows = list(range(1, 51))
    numbered, _ = await _jump(rows, None, True, 7, total=True)
    assert (numbered.page, numbered.rows, numbered.before, numbered.after) == (8, [50], True, False)
    # Without a total: the last 7 rows, read from the end like a first page.
    unnumbered, reads = await _jump(rows, None, True, 7, total=False)
    assert (unnumbered.page, unnumbered.rows) == (None, list(range(44, 51)))
    assert (unnumbered.before, unnumbered.after, reads) == (True, False, [(0, 8, True)])
    short, _ = await _jump(rows[:5], None, True, 7, total=False)
    assert (short.rows, short.before, short.after) == (rows[:5], False, False)


# The mail list ----------------------------------------------------------------------------------


def walk_rows(monkeypatch: pytest.MonkeyPatch, rows: int) -> None:
    """WALK_ROWS wherever a list reads it: the bounded walk, and the jumps that use it."""
    for module in (filters, mails, documents):
        monkeypatch.setattr(module, "WALK_ROWS", rows)


def _items(page: Any) -> list[Any]:
    return list(page["items"])


async def keyset_pages(
    client: httpx.AsyncClient, path: str, params: Params, limit: int
) -> list[Any]:
    """Every page of a list by Weiter, from the first page."""
    found: list[Any] = []
    cursor = None
    while True:
        page = await get(client, path, [*params, ("limit", str(limit)), *at(cursor)])
        found.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return found


async def check_jumps(
    client: httpx.AsyncClient, path: str, params: Params, limit: int, *, numbered_last: bool
) -> None:
    """Every page of the list by number is its page by Weiter, with cursors to its neighbours; a
    page beyond the end is the last one, and the last page (last) holds the last `limit` rows,
    numbered where the list knows its total."""
    forward = await keyset_pages(client, path, params, limit)
    listed = [item for page in forward for item in _items(page)]
    sized = [*params, ("limit", str(limit))]
    assert forward[0]["page"] == 1
    assert all(page["page"] is None for page in forward[1:])
    for number, expected in enumerate(forward, 1):
        page = await get(client, path, [*sized, ("page", str(number))])
        assert _items(page) == _items(expected), number
        assert page["page"] == number
        assert (page["prev_cursor"] is None) == (number == 1)
        assert (page["next_cursor"] is None) == (number == len(forward))
        if page["next_cursor"] is not None:
            following = await get(client, path, [*sized, *at(page["next_cursor"])])
            assert _items(following) == _items(forward[number])
        if page["prev_cursor"] is not None:
            preceding = await get(client, path, [*sized, *at(page["prev_cursor"])])
            assert _items(preceding) == _items(forward[number - 2])
    beyond = await get(client, path, [*sized, ("page", str(len(forward) + 3))])
    assert (_items(beyond), beyond["page"]) == (_items(forward[-1]), len(forward))
    last = await get(client, path, [*sized, ("last", "true")])
    assert last["next_cursor"] is None
    if numbered_last:
        assert (_items(last), last["page"]) == (_items(forward[-1]), len(forward))
        return
    assert (_items(last), last["page"]) == (listed[-limit:], None)
    assert (last["prev_cursor"] is None) == (len(listed) <= limit)
    if last["prev_cursor"] is not None:
        preceding = await get(client, path, [*sized, *at(last["prev_cursor"])])
        assert _items(preceding) == listed[-2 * limit : -limit]


MAIL_LISTS: list[tuple[str, Params]] = [
    ("all", []),
    ("dkim", [("dkim", "pass"), ("dkim", "no_key")]),
    ("attachments", [("q", "has:attachment"), ("hide_duplicates", "true")]),
    ("search", [("q", "Angebot")]),
    ("nothing", [("q", "zzzkeinwortzzz")]),
]


@pytest.mark.db
@pytest.mark.parametrize(
    ("forward_rows", "walk"),
    [(paging.FORWARD_ROWS, filters.WALK_ROWS), (0, filters.WALK_ROWS), (0, 7)],
    ids=["forward", "counted", "counted-offset"],
)
@pytest.mark.parametrize("sort", ["date_desc", "date_asc"])
@pytest.mark.parametrize(
    "params", [params for _, params in MAIL_LISTS], ids=[name for name, _ in MAIL_LISTS]
)
async def test_mail_list_jumps_agree_with_its_keyset_pages(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    params: Params,
    sort: str,
    forward_rows: int,
    walk: int,
) -> None:
    monkeypatch.setattr(paging, "FORWARD_ROWS", forward_rows)
    walk_rows(monkeypatch, walk)
    await check_jumps(client, "/api/mails", [*params, ("sort", sort)], LIMIT, numbered_last=False)


@pytest.mark.db
async def test_a_jump_with_research_filters_and_hidden_mails(
    mutable_database_url: str, mutable_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A rule hides every third mail; notes keep some of them visible (D203); a tag marks every
    # fifth mail, hidden or not.
    statements = [
        "INSERT INTO hide_rule (id, name, automated) OVERRIDING SYSTEM VALUE"
        " VALUES (1, 'Rundschreiben', true)",
        "INSERT INTO mail_hidden (rule_id, mail_id) SELECT 1, id FROM mail WHERE id % 3 = 0",
        "INSERT INTO note (mail_sha256, body) SELECT raw_sha256, 'Rat' FROM mail WHERE id % 9 = 0",
        "INSERT INTO tag (id, name, color) OVERRIDING SYSTEM VALUE VALUES (1, 'Spende', 'red')",
        "INSERT INTO mail_tag (tag_id, mail_sha256)"
        " SELECT DISTINCT 1, raw_sha256 FROM mail WHERE id % 5 = 0",
        "ANALYZE",
    ]
    for statement in statements:
        await rows(mutable_database_url, statement)
    visible = await keyset_pages(mutable_client, "/api/mails", [], LIMIT)
    every = await keyset_pages(mutable_client, "/api/mails", [("include_hidden", "true")], LIMIT)
    assert sum(map(len, map(_items, visible))) < sum(map(len, map(_items, every)))
    # Hidden mails as a list of ids (mails.BY_ID_LIMIT) and, beyond it, as the filter itself.
    cases = [(paging.FORWARD_ROWS, filters.WALK_ROWS, mails.BY_ID_LIMIT), (0, 7, 10**6), (0, 7, 0)]
    for forward_rows, walk, by_id in cases:
        monkeypatch.setattr(paging, "FORWARD_ROWS", forward_rows)
        walk_rows(monkeypatch, walk)
        monkeypatch.setattr(mails, "BY_ID_LIMIT", by_id)
        for params in ([], [("include_hidden", "true")], [("tag", "1")], [("has_note", "true")]):
            await check_jumps(mutable_client, "/api/mails", params, LIMIT, numbered_last=False)


@pytest.mark.db
async def test_a_jump_and_a_cursor_do_not_go_together(client: httpx.AsyncClient) -> None:
    first = await get(client, "/api/mails", [("limit", "10")])
    for jump in (("page", "3"), ("last", "true")):
        params = [("limit", "10"), jump, *at(first["next_cursor"])]
        error = await get(client, "/api/mails", params, status=400)
        assert error["detail"]["code"] == "invalid_cursor"
    # The first page by number is the first page.
    assert await get(client, "/api/mails", [("limit", "10"), ("page", "1")]) == first
    await get(client, "/api/mails", [("page", "0")], status=422)


@pytest.mark.db
async def test_a_jump_that_runs_out_of_time(
    imported_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow_total(session: AsyncSession, count: Executable) -> int:
        """A count longer than the budget, which statement_timeout stops."""
        await session.execute(text("SELECT pg_sleep(5)"))
        return 0

    monkeypatch.setattr(paging, "FORWARD_ROWS", 0)
    settings = api_settings(imported_database_url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(update={"api_count_timeout": 0.3})
    params = [("limit", "10"), ("page", "3")]
    async for client in _client(settings):
        first = await get(client, "/api/mails", [("limit", "10")])
        with monkeypatch.context() as slow:
            slow.setattr(paging, "_total", slow_total)
            started = time.monotonic()
            error = await get(client, "/api/mails", params, status=400)
            assert error["detail"]["code"] == "page_too_far"
            assert time.monotonic() - started < 3
            # The first and the last page are reached without counting.
            assert await get(client, "/api/mails", [("limit", "10")]) == first
            last = await get(client, "/api/mails", [("limit", "10"), ("last", "true")])
            assert len(last["items"]) == 10 and last["next_cursor"] is None
        page = await get(client, "/api/mails", params)
        assert page["page"] == 3 and page["prev_cursor"] and page["next_cursor"]

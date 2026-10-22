"""Jumps to a page by its number (D193), shared by the lists that page by keyset (D19).

Zurück and Weiter stay keyset steps; a jump names the page instead: page N holds the rows from
(N-1)*limit on in the list order. They are read by OFFSET from the nearer end, a page of the
second half in reverse order from the end and then flipped, so that no jump passes more than
half the list. Which end is nearer needs the list's total: a jump within the first FORWARD_ROWS
rows reads forward without one (passing them costs about what counting would), a jump beyond
them counts the list first, and a list that knows its total passes it in. A page beyond the end
becomes the last page. Counting and reading run under the count budget of D19
(MAILROBBE_API_COUNT_TIMEOUT), the whole jump within one budget: what does not answer in time is
400 page_too_far instead of a wait, and the UI offers the first and the last page.

The last page (`last`) of a list that knows its total is the page of that number. Elsewhere it is
read from the end like a first page in reverse, without counting, so it is reached even where
the total is not known; it then holds the last `limit` rows and has no number. Each list reads
its rows (Read) and builds the cursors of a jumped page from its first and last row like those
of any page, so Zurück and Weiter go on by keyset from there.
"""

import math
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Executable, Select, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import api_error
from mailrobbe.api.schemas import COUNT_LIMIT
from mailrobbe.config import Settings

# Rows a jump passes from the start without counting the list first: the pages a list numbers
# with "mehr als 10.000" (D19) are reached without the count that ran out of time there.
FORWARD_ROWS = COUNT_LIMIT
QUERY_CANCELED = "57014"  # SQLSTATE of a statement stopped by statement_timeout

# Rows of a list from an offset: (offset, limit, reverse) -> at most limit rows after the first
# offset ones in list order, or with reverse in the reverse order (from the end).
Read = Callable[[int, int, bool], Awaitable[Sequence[Any]]]


@dataclass(frozen=True, slots=True)
class Jump:
    """The page a jump read: its rows in list order, its number (None for the last page read
    from the end), and whether the list has rows before and after it."""

    rows: list[Any]
    page: int | None
    before: bool
    after: bool


def wanted(page: int | None, last: bool) -> bool:
    """Whether the request asks for a jump: the last page, or a page after the first."""
    return last or (page is not None and page > 1)


async def jump(
    session: AsyncSession,
    settings: Settings,
    read: Read,
    count: Executable | int,
    *,
    page: int | None,
    last: bool,
    limit: int,
) -> Jump:
    """The page of a jump: the last page with last, else page `page` (from 1) of `limit` rows.
    count: the list's total, or a statement whose one row holds it."""
    if last and not isinstance(count, int):  # a first page in reverse: nothing is passed
        rows = list(await read(0, limit + 1, True))
        return Jump(rows[:limit][::-1], None, before=len(rows) > limit, after=False)
    try:
        async with _Budget(session, settings.api_count_timeout) as budget:
            if isinstance(count, int):
                number = max(1, math.ceil(count / limit)) if last else page or 1
                return await _from_nearer_end(budget, read, count, number, limit)
            number = page or 1
            offset = (number - 1) * limit
            if offset <= FORWARD_ROWS:
                rows = list(await budget.run(lambda: read(offset, limit + 1, False)))
                if rows or offset == 0:
                    return Jump(rows[:limit], number, before=offset > 0, after=len(rows) > limit)
            statement = count
            total = await budget.run(lambda: _total(session, statement))
            return await _from_nearer_end(budget, read, total, number, limit)
    except _OutOfTime as error:
        message = "the page was not found within the count budget"
        raise api_error(400, "page_too_far", message) from error


async def bounded_total(
    session: AsyncSession, settings: Settings, matching: Select[Any]
) -> tuple[int | None, bool]:
    """How many rows matching selects, under the count budget of D19 as the summaries count:
    (total, True) when exact, (COUNT_LIMIT, False) for more, (None, False) when even counting
    up to COUNT_LIMIT runs out of time."""
    exact = await _counted(session, settings, select(func.count()).select_from(matching.subquery()))
    if exact is not None:
        return exact, True
    bounded = matching.limit(COUNT_LIMIT + 1).subquery()
    total = await _counted(session, settings, select(func.count()).select_from(bounded))
    if total is None:
        return None, False
    return min(total, COUNT_LIMIT), total <= COUNT_LIMIT


async def _counted(session: AsyncSession, settings: Settings, count: Executable) -> int | None:
    """The total of count within a budget of its own; None when it runs out."""
    try:
        async with _Budget(session, settings.api_count_timeout) as budget:
            return await budget.run(lambda: _total(session, count))
    except _OutOfTime:
        return None


async def custom_plans(session: AsyncSession) -> None:
    """Plans the rest of the request's statements for their parameters. A list of ids a jump
    tests (`id != ALL(...)`) is hashed in a plan made for its values only; the generic plan a
    prepared statement may switch to tests it element by element, for every row passed."""
    await session.execute(select(func.set_config("plan_cache_mode", "force_custom_plan", True)))


async def _total(session: AsyncSession, count: Executable) -> int:
    return int((await session.execute(count)).scalar_one())


async def _from_nearer_end(
    budget: "_Budget", read: Read, total: int, page: int, limit: int
) -> Jump:
    """Page `page` of a list of `total` rows, the last one for a page beyond it."""
    page = min(page, max(1, math.ceil(total / limit)))
    offset = (page - 1) * limit
    size = max(0, min(limit, total - offset))  # the last page may hold fewer
    behind = total - offset - size
    rows: list[Any] = []
    if size and offset <= behind:
        rows = list(await budget.run(lambda: read(offset, size, False)))
    elif size:
        rows = list(await budget.run(lambda: read(behind, size, True)))[::-1]
    return Jump(rows, page, before=offset > 0, after=behind > 0)


class _OutOfTime(Exception):
    """A statement of a budget was canceled, or no time was left for it."""


class _Budget:
    """The count budget of one jump or count: each statement gets the time left of it, and
    running out raises _OutOfTime. Restores the session's statement timeout on leaving."""

    def __init__(self, session: AsyncSession, seconds: float) -> None:
        self._session = session
        self._deadline = time.monotonic() + seconds
        self._previous = "0"

    async def __aenter__(self) -> "_Budget":
        self._previous = str(
            await self._session.scalar(select(func.current_setting("statement_timeout")))
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._timeout(self._previous)

    async def _timeout(self, value: str) -> None:
        await self._session.execute(select(func.set_config("statement_timeout", value, True)))

    async def run[T](self, work: Callable[[], Awaitable[T]]) -> T:
        """work's result within the time left, in a savepoint that a canceled statement rolls
        back, so the session stays usable."""
        left = self._deadline - time.monotonic()
        if left <= 0:
            raise _OutOfTime
        await self._timeout(str(max(1, round(left * 1000))))
        try:
            async with self._session.begin_nested():
                return await work()
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) != QUERY_CANCELED:
                raise
            raise _OutOfTime from error

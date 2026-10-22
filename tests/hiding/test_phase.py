"""The step hidden (D221) on the hand-made archive: every rule computed again, new mails and a
merge covered, a disabled rule emptied, a failing rule left as it was while the others go on, a
stop between rules, and the figures afterwards."""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import ColumnElement, literal_column, make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mailrobbe import migrate
from mailrobbe.hiding import model, phase
from mailrobbe.hiding.model import read_figures
from mailrobbe.jobrun import Step
from tests.conftest import _temporary_database
from tests.hiding.archive import M, insert_archive, merge

pytestmark = pytest.mark.db

RULES = (
    "INSERT INTO hide_rule (domain) VALUES ('newsletter.example')",
    "INSERT INTO hide_rule (person_id)"
    " SELECT id FROM person WHERE canonical_email = 'anna@a.example'",
    "INSERT INTO hide_rule (automated, enabled) VALUES (true, false)",
)


@asynccontextmanager
async def sessions(url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def execute(url: str, *statements: str) -> None:
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        for statement in statements:
            await session.execute(text(statement))


async def hidden(url: str) -> dict[int, set[str]]:
    """The names of the mails in mail_hidden by rule id, every rule listed."""
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        rules = await session.scalars(text("SELECT id FROM hide_rule ORDER BY id"))
        found: dict[int, set[str]] = {rule: set() for rule in rules}
        rows = await session.execute(
            text(
                "SELECT h.rule_id, m.raw_sha256 FROM mail_hidden h JOIN mail m ON m.id = h.mail_id"
            )
        )
        for rule_id, name in rows:
            found[rule_id].add(name)
        return found


async def run(url: str, stop: asyncio.Event | None = None) -> tuple[int, Step]:
    step = Step()
    async with sessions(url) as sessionmaker:
        computed = await phase.refresh_hidden(sessionmaker, stop or asyncio.Event(), step)
    return computed, step


@pytest.fixture(scope="module")
def template_url(database_server_url: str) -> Iterator[str]:
    """The archive and the rules, none computed yet."""
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)

        async def fill() -> None:
            async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
                await insert_archive(session)
            await execute(url, *RULES)

        asyncio.run(fill())
        yield url


@pytest.fixture
def url(database_server_url: str, template_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url, make_url(template_url).database) as copy:
        yield copy


NEWS = {"news1", "news2", "sub"}
ANNA = {"anna", "alias", "council"}


async def test_the_step_computes_every_rule_and_the_figures(url: str) -> None:
    computed, step = await run(url)
    assert (computed, step.done, step.total) == (3, 3, 3)
    assert list((await hidden(url)).values()) == [NEWS, ANNA, set()]
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        mails = list(await session.scalars(text("SELECT mails FROM hide_rule ORDER BY id")))
        figures = await read_figures(session)
    assert mails == [3, 3, 0]
    assert figures is not None
    assert (figures.mails, figures.dkim) == (6, {"pass": 4, "no_key": 1, "fail": 1})


async def test_new_mails_and_a_merge_are_covered(url: str) -> None:
    await run(url)
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        await insert_archive(session, {"later": M("news@newsletter.example", "Neu", 20)}, 1)
        await merge(session, "bert@a_b.example", "anna@a.example")
    await run(url)
    assert list((await hidden(url)).values()) == [NEWS | {"later"}, ANNA | {"bert"}, set()]


async def test_a_disabled_rule_is_emptied_and_an_enabled_one_filled(url: str) -> None:
    await run(url)
    await execute(
        url,
        "UPDATE hide_rule SET enabled = NOT enabled",
        "INSERT INTO mail_hidden SELECT 1, id FROM mail WHERE raw_sha256 = 'bert'",  # stale row
    )
    await run(url)
    assert list((await hidden(url)).values()) == [set(), set(), {"bot"}]


async def test_a_failing_rule_stays_as_it_was_and_the_others_go_on(
    url: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    await run(url)
    await execute(
        url,
        "UPDATE hide_rule SET domain = 'mail.newsletter.example' WHERE id = 1",
        "UPDATE hide_rule SET enabled = true WHERE id = 3",
    )
    matches = model.matches

    def failing(rule: Any) -> ColumnElement[bool]:
        if rule.id == 2:
            return literal_column("1 / 0 = 1")  # division by zero when it runs
        return matches(rule)

    monkeypatch.setattr(model, "matches", failing)
    with caplog.at_level(logging.WARNING, logger="mailrobbe.hiding.phase"):
        computed, step = await run(url)
    assert (computed, step.done) == (2, 3)
    assert list((await hidden(url)).values()) == [{"sub"}, ANNA, {"bot"}]
    assert "rule 2 left as it was" in caplog.text and "division by zero" in caplog.text


async def test_a_stop_ends_the_step_between_rules(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = asyncio.Event()
    store_rule = model.store_rule

    async def store_then_stop(session: AsyncSession, rule_id: int) -> Any:
        stop.set()
        return await store_rule(session, rule_id)

    monkeypatch.setattr(phase, "store_rule", store_then_stop)
    computed, step = await run(url, stop)
    assert (computed, step.done, step.total) == (1, 1, 3)
    assert list((await hidden(url)).values()) == [NEWS, set(), set()]
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        figures = await read_figures(session)
    assert figures is not None and figures.mails == 3  # counted after the stop too

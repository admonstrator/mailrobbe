"""Alias suggestions (D30) on small hand-built archives; the keys are in test_normalize.py."""

from itertools import combinations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import aggregates
from mailrobbe.importer.finalize import finalize
from mailrobbe.persons.merge import dismiss_suggestion, merge_persons, unmerge_person
from mailrobbe.persons.suggestions import MAX_GROUP, refresh_alias_suggestions
from tests.importer.doubles import fetch
from tests.persons.helpers import ids, mail, snapshot, store, suggestions

pytestmark = pytest.mark.db

SENDER = "sender@s.example"


async def _receive(session: AsyncSession, *addresses: str) -> dict[str, int]:
    """One mail from SENDER to each address (with its name, if given); finalize; person ids."""
    await store(session, [mail(SENDER, to=[address]) for address in addresses])
    await finalize(session)
    return await ids(session)


async def test_a_display_name_both_use_suggests_a_pair(db_session: AsyncSession) -> None:
    await _receive(
        db_session,
        "Anna Schmidt <anna@a.example>",
        "Schmidt, Anna <a.schmidt@b.example>",
        "'anna  schmidt' <as@c.example>",
        "Anna <anna@d.example>",  # one word: no name to share
        "anna@e.example <q@e.example>",  # an address as name
        "anna@e.example <r@f.example>",
    )
    assert await suggestions(db_session) == {
        ("a.schmidt@b.example", "anna@a.example"): ("anna schmidt", None),
        ("a.schmidt@b.example", "as@c.example"): ("anna schmidt", None),
        ("anna@a.example", "as@c.example"): ("anna schmidt", None),
        ("anna@a.example", "anna@d.example"): (None, "anna"),
    }


async def test_a_local_part_both_have_suggests_a_pair(db_session: AsyncSession) -> None:
    await _receive(
        db_session,
        "Anna Schmidt <anna.schmidt@a.example>",
        "Anna Schmidt <anna.schmidt@mail.test>",  # name and local part: one row, both reasons
        "anna.schmidt+shop@b.example",  # without its +suffix: the same local part
        "info@a.example",  # role addresses never
        "info@b.example",
        "noreply@a.example",
        "noreply@b.example",
    )
    assert await suggestions(db_session) == {
        ("anna.schmidt+shop@b.example", "anna.schmidt@a.example"): (None, "anna.schmidt"),
        ("anna.schmidt+shop@b.example", "anna.schmidt@mail.test"): (None, "anna.schmidt"),
        ("anna.schmidt@a.example", "anna.schmidt@mail.test"): ("anna schmidt", "anna.schmidt"),
    }


async def test_a_pair_records_the_smallest_name_it_shares(db_session: AsyncSession) -> None:
    await store(
        db_session,
        [
            mail(SENDER, to=["Zora Zett <z1@a.example>", "Anna Zett <z2@b.example>"]),
            mail(SENDER, to=["Anna Zett <z1@a.example>", "Zora Zett <z2@b.example>"]),
        ],
    )
    await finalize(db_session)
    assert await suggestions(db_session) == {("z1@a.example", "z2@b.example"): ("anna zett", None)}


async def test_a_key_of_more_than_max_group_persons_suggests_nothing(
    db_session: AsyncSession,
) -> None:
    common = [f"Max Muster <max{i}@m{i}.example>" for i in range(MAX_GROUP + 1)]
    rare = [f"Eva Muster <eva{i}@e{i}.example>" for i in range(MAX_GROUP)]
    await _receive(db_session, *common, *rare)

    eva = sorted(address.partition("<")[2].rstrip(">") for address in rare)
    assert await suggestions(db_session) == {
        pair: ("eva muster", None) for pair in combinations(eva, 2)
    }


async def test_a_merge_can_bring_a_key_within_the_limit(db_session: AsyncSession) -> None:
    common = [f"Max Muster <max{i}@m{i}.example>" for i in range(MAX_GROUP + 1)]
    person = await _receive(db_session, *common)
    assert await suggestions(db_session) == {}

    await merge_persons(db_session, person["max0@m0.example"], [person["max1@m1.example"]])
    # five roots share the name now: pairs also between persons the merge did not touch
    roots = ["max0@m0.example", *(f"max{i}@m{i}.example" for i in range(2, MAX_GROUP + 1))]
    expected = {pair: ("max muster", None) for pair in combinations(sorted(roots), 2)}
    assert await suggestions(db_session) == expected
    merged = await snapshot(db_session)
    await aggregates.refresh_aggregates(db_session)
    assert await snapshot(db_session) == merged


async def test_aliases_are_no_pair_and_lend_their_keys_to_the_root(
    db_session: AsyncSession,
) -> None:
    person = await _receive(
        db_session,
        "A. S. <as@a.example>",
        "Anna Schmidt <anna@b.example>",
        "Anna Schmidt <schmidt@c.example>",
    )
    await merge_persons(db_session, person["as@a.example"], [person["anna@b.example"]])
    assert await suggestions(db_session) == {
        ("as@a.example", "schmidt@c.example"): ("anna schmidt", None)
    }

    await unmerge_person(db_session, person["anna@b.example"])
    assert await suggestions(db_session) == {
        ("anna@b.example", "schmidt@c.example"): ("anna schmidt", None)
    }


async def test_a_dismissed_pair_is_never_suggested_again(db_session: AsyncSession) -> None:
    person = await _receive(
        db_session,
        "Anna Schmidt <anna@a.example>",
        "Anna Schmidt <anna@b.example>",
        "Anna Schmidt <schmidt@c.example>",
    )
    a, b, c = (person[x] for x in ("anna@a.example", "anna@b.example", "schmidt@c.example"))
    await dismiss_suggestion(db_session, b, a)

    assert await fetch(db_session, "SELECT person_a, person_b FROM alias_dismissal") == [
        (min(a, b), max(a, b))
    ]
    pairs = {("anna@a.example", "schmidt@c.example"), ("anna@b.example", "schmidt@c.example")}
    assert set(await suggestions(db_session)) == pairs
    await refresh_alias_suggestions(db_session)
    assert set(await suggestions(db_session)) == pairs

    # merged into another person, the dismissed one still is not its alias
    await merge_persons(db_session, c, [b])
    assert await suggestions(db_session) == {}
    await unmerge_person(db_session, b)
    assert set(await suggestions(db_session)) == pairs

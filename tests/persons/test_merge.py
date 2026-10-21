"""Merging, unmerging and dismissing (D28), and that the refresh for the persons concerned
gives exactly what a full refresh does (D33), edges included (D36)."""

import random
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import aggregates
from mailrobbe.importer.finalize import finalize
from mailrobbe.persons.merge import (
    MergeError,
    UnknownPerson,
    dismiss_suggestion,
    merge_persons,
    unmerge_person,
)
from mailrobbe.persons.roots import member_ids, resolve_root
from tests.importer.doubles import fetch
from tests.persons.helpers import Entry, ids, mail, snapshot, stats, store, suggestions

pytestmark = pytest.mark.db

PEOPLE = (
    "Anna Schmidt <anna@a.example>",
    "Schmidt, Anna <anna.schmidt@mail.test>",
    "Anna Schmidt <schmidt@b.example>",
    "Bert Brandt <bert@b.example>",
    "B. Brandt <bert@mail.test>",
    "Carl Clausen <carl@c.example>",
    "Dora Dorn <dora@d.example>",
    "Dora Dorn <dd@e.example>",
)
ANNA, ANNA_MAIL, SCHMIDT, BERT, BERT_MAIL, CARL, DORA, DD = (
    person.partition("<")[2].rstrip(">") for person in PEOPLE
)
# Every refresh of the edges stamps its time into global_stats (D36); the rest must not change.
_GLOBAL_FIGURES = """
    SELECT key, CASE WHEN key = 'edges' THEN value - 'refreshed_at' ELSE value END
    FROM global_stats ORDER BY key
"""


def _archive(seed: int, count: int = 80) -> list[Entry]:
    """Mails between PEOPLE in every role, over several years, some undated or duplicates."""
    rng = random.Random(seed)
    entries = []
    for index in range(count):
        sender, *others = rng.sample(PEOPLE, rng.randint(2, 5))
        roles: dict[str, list[str]] = {"to": [], "cc": [], "bcc": []}
        for other in others:
            roles[rng.choice(("to", "to", "cc", "bcc"))].append(other)
        if rng.random() < 0.1:
            roles["cc"].append(sender)  # a copy to oneself
        date = datetime(rng.randint(2015, 2022), rng.randint(1, 12), 1, tzinfo=UTC)
        repeat = index > 0 and rng.random() < 0.08  # a duplicate of the mail before (D16)
        entries.append(
            mail(
                sender,
                **roles,
                date=None if rng.random() < 0.1 else date,
                dkim=rng.choice(("pass", "pass", "fail", "unsigned", None)),
                message_id=f"<{index - 1 if repeat else index}@a.example>",
            )
        )
    return entries


async def _prepare(session: AsyncSession, seed: int = 1) -> dict[str, int]:
    await store(session, _archive(seed))
    await finalize(session)
    return await ids(session)


async def _assert_consistent(session: AsyncSession) -> None:
    """merged_into names roots only, and a full refresh changes nothing the partial ones did."""
    chained = await fetch(
        session,
        "SELECT a.id FROM person a JOIN person r ON r.id = a.merged_into "
        "WHERE r.merged_into IS NOT NULL",
    )
    assert chained == []
    partial = await snapshot(session)
    figures = await fetch(session, _GLOBAL_FIGURES)
    await aggregates.refresh_aggregates(session)
    assert await snapshot(session) == partial
    assert await fetch(session, _GLOBAL_FIGURES) == figures


async def test_merge_and_unmerge_keep_roots_and_figures(db_session: AsyncSession) -> None:
    person = await _prepare(db_session)
    sent_before = {email: row[0] for email, row in (await stats(db_session)).items()}

    assert await merge_persons(db_session, person[ANNA], [person[ANNA_MAIL]]) == person[ANNA]
    await _assert_consistent(db_session)
    assert await merge_persons(db_session, person[DORA], [person[DD]]) == person[DORA]
    await _assert_consistent(db_session)
    # a root that has an alias already: both move to the target
    assert await merge_persons(db_session, person[BERT], [person[ANNA]]) == person[BERT]
    await _assert_consistent(db_session)
    assert await member_ids(db_session, person[BERT]) == [
        person[BERT],
        *sorted((person[ANNA], person[ANNA_MAIL])),
    ]
    # an alias as the target stands for its root; several sources at once
    target = await merge_persons(db_session, person[ANNA], [person[CARL], person[DORA]])
    assert target == person[BERT]
    await _assert_consistent(db_session)
    assert {email for email in await stats(db_session)} == {BERT, SCHMIDT, BERT_MAIL}

    # unmerged, an address is a person of its own again, with its own figures
    assert await unmerge_person(db_session, person[DD]) == person[BERT]
    await _assert_consistent(db_session)
    assert await unmerge_person(db_session, person[ANNA]) == person[BERT]
    await _assert_consistent(db_session)
    assert await resolve_root(db_session, person[ANNA_MAIL]) == person[BERT]
    for email in (ANNA, DD):
        assert (await stats(db_session))[email][0] == sent_before[email]


async def test_any_sequence_of_merges_and_unmerges(db_session: AsyncSession) -> None:
    person = await _prepare(db_session, seed=2)
    rng = random.Random(3)
    everyone = sorted(person.values())
    for _ in range(30):
        aliases = [
            row[0] for row in await fetch(db_session, "SELECT id FROM person WHERE merged_into > 0")
        ]
        if aliases and rng.random() < 0.35:
            await unmerge_person(db_session, rng.choice(aliases))
        else:
            target, *sources = rng.sample(everyone, rng.randint(2, 3))
            roots = {await resolve_root(db_session, x) for x in sources}
            if await resolve_root(db_session, target) in roots:
                with pytest.raises(MergeError):
                    await merge_persons(db_session, target, sources)
                continue
            await merge_persons(db_session, target, sources)
        await _assert_consistent(db_session)


async def test_dismissing_stores_the_pair_of_roots(db_session: AsyncSession) -> None:
    person = await _prepare(db_session)
    await merge_persons(db_session, person[CARL], [person[ANNA_MAIL]])
    assert (ANNA, CARL) in await suggestions(db_session)  # "anna schmidt" through the alias

    await dismiss_suggestion(db_session, person[ANNA_MAIL], person[ANNA])
    pair = sorted((person[ANNA], person[CARL]))
    assert await fetch(db_session, "SELECT person_a, person_b FROM alias_dismissal") == [
        tuple(pair)
    ]
    assert (ANNA, CARL) not in await suggestions(db_session)
    await _assert_consistent(db_session)
    await dismiss_suggestion(db_session, person[ANNA], person[CARL])  # once is enough
    assert len(await fetch(db_session, "SELECT * FROM alias_dismissal")) == 1


async def test_impossible_merges_change_nothing(db_session: AsyncSession) -> None:
    person = await _prepare(db_session)
    await merge_persons(db_session, person[ANNA], [person[ANNA_MAIL]])
    before = await snapshot(db_session)
    unknown = max(person.values()) + 1

    with pytest.raises(MergeError):
        await merge_persons(db_session, person[ANNA], [person[ANNA]])
    with pytest.raises(MergeError):
        await merge_persons(db_session, person[ANNA_MAIL], [person[BERT], person[ANNA]])
    with pytest.raises(MergeError):
        await unmerge_person(db_session, person[ANNA])  # a root, no alias
    with pytest.raises(MergeError):
        await dismiss_suggestion(db_session, person[ANNA], person[ANNA_MAIL])
    with pytest.raises(UnknownPerson) as raised:
        await merge_persons(db_session, person[ANNA], [person[BERT], unknown])
    assert raised.value.person_id == unknown
    with pytest.raises(UnknownPerson):
        await merge_persons(db_session, unknown, [person[BERT]])
    with pytest.raises(UnknownPerson):
        await unmerge_person(db_session, unknown)
    with pytest.raises(UnknownPerson):
        await dismiss_suggestion(db_session, person[BERT], unknown)

    assert await snapshot(db_session) == before
    assert await fetch(db_session, "SELECT count(*) FROM person WHERE merged_into > 0") == [(1,)]

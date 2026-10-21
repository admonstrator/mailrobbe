"""Merging, unmerging and dismissing (D28), the merge log, undoing merges and merging every
certain suggestion (D162, D163), and that the refresh for the persons concerned gives exactly
what a full refresh does (D33), edges included (D36)."""

import random
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import aggregates
from mailrobbe.importer.finalize import finalize
from mailrobbe.persons.merge import (
    MERGE_GROUP,
    CertainMerge,
    MergeError,
    MergePlan,
    MergeUndone,
    Undo,
    UnknownMerge,
    UnknownPerson,
    certain_groups,
    dismiss_suggestion,
    merge_certain,
    merge_persons,
    undo_batch,
    undo_merge,
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
SENDER = "sender@s.example"
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


# The merge log, undoing merges and merging every certain suggestion (D162, D163) ---------------


async def _roots(session: AsyncSession) -> dict[str, str | None]:
    """merged_into of every person, by address."""
    rows = await fetch(
        session,
        "SELECT p.canonical_email, r.canonical_email FROM person p "
        "LEFT JOIN person r ON r.id = p.merged_into",
    )
    return dict(rows)


async def _merges(session: AsyncSession) -> list[tuple[Any, ...]]:
    """person_merge with its members: id, target, batch, editor, undone by, (member, before)."""
    rows = await fetch(
        session,
        "SELECT pm.id, t.canonical_email, pm.batch_id, pm.editor, pm.undone_by,"
        " array_agg(ARRAY[p.canonical_email, b.canonical_email])"
        " FROM person_merge pm JOIN person t ON t.id = pm.target"
        " JOIN person_merge_member m ON m.merge_id = pm.id JOIN person p ON p.id = m.person_id"
        " LEFT JOIN person b ON b.id = m.previous_root GROUP BY 1, 2 ORDER BY 1",
    )
    return [(*row[:5], sorted(tuple(pair) for pair in row[5])) for row in rows]


async def test_every_merge_is_logged(db_session: AsyncSession) -> None:
    person = await _prepare(db_session)
    await merge_persons(db_session, person[ANNA], [person[ANNA_MAIL]], "Lena Vogt")
    await merge_persons(db_session, person[BERT], [person[ANNA_MAIL], person[CARL]])
    [first, second] = await _merges(db_session)
    assert first[1:] == (ANNA, None, "Lena Vogt", None, [(ANNA_MAIL, None)])
    # The whole root of a source moves, each person with where it pointed before.
    members = sorted([(ANNA, None), (ANNA_MAIL, ANNA), (CARL, None)])
    assert second[1:] == (BERT, None, None, None, members)


@pytest.mark.parametrize("order", ["first_merge_first", "last_merge_first"])
async def test_undoing_merges_in_either_order_gives_back_the_start(
    db_session: AsyncSession, order: str
) -> None:
    person = await _prepare(db_session)
    await merge_persons(db_session, person[ANNA], [person[ANNA_MAIL]])
    start, figures = await _roots(db_session), await snapshot(db_session)
    await merge_persons(db_session, person[BERT], [person[ANNA]])  # A into B
    await merge_persons(db_session, person[CARL], [person[BERT]])  # B into C
    _, into_bert, into_carl = (row[0] for row in await _merges(db_session))

    if order == "first_merge_first":
        assert await undo_merge(db_session, into_bert, "Lena Vogt") == Undo(merges=1, persons=2)
        # A is a root again with its alias; B stays in C.
        roots = await _roots(db_session)
        assert (roots[ANNA], roots[ANNA_MAIL], roots[BERT]) == (None, ANNA, CARL)
        await _assert_consistent(db_session)
        assert await undo_merge(db_session, into_carl) == Undo(merges=1, persons=1)
    else:
        assert await undo_merge(db_session, into_carl) == Undo(merges=1, persons=3)
        roots = await _roots(db_session)
        assert (roots[BERT], roots[ANNA], roots[ANNA_MAIL], roots[CARL]) == (None, BERT, BERT, None)
        await _assert_consistent(db_session)
        assert await undo_merge(db_session, into_bert) == Undo(merges=1, persons=2)
    assert await _roots(db_session) == start
    assert await snapshot(db_session) == figures
    await _assert_consistent(db_session)
    undone = {row[0]: row[4] for row in await _merges(db_session)}
    assert undone[into_bert] == ("Lena Vogt" if order == "first_merge_first" else None)

    for merge_id in (into_bert, into_carl):
        with pytest.raises(MergeUndone):
            await undo_merge(db_session, merge_id)
    with pytest.raises(UnknownMerge):
        await undo_merge(db_session, into_carl + 100)
    assert await _roots(db_session) == start


async def test_undoing_a_merge_after_an_address_was_split_off(db_session: AsyncSession) -> None:
    person = await _prepare(db_session)
    await merge_persons(db_session, person[ANNA], [person[ANNA_MAIL]])
    start = await _roots(db_session)
    await merge_persons(db_session, person[BERT], [person[ANNA]])
    [_, into_bert] = (row[0] for row in await _merges(db_session))
    await unmerge_person(db_session, person[ANNA])  # its alias stays with BERT
    assert await undo_merge(db_session, into_bert) == Undo(merges=1, persons=1)
    assert await _roots(db_session) == start  # the alias went back to ANNA
    await _assert_consistent(db_session)


async def _certain_archive(session: AsyncSession) -> dict[str, int]:
    """Certain suggestions in groups of two and three, uncertain ones, and mails to tell the
    targets: the person with most mails, the lower id on a tie."""
    entries = [
        *(mail(SENDER, to=[f"Anna Schmidt <anna.schmidt@{d}.example>"]) for d in "abc"),
        mail(SENDER, to=["Anna Schmidt <anna.schmidt@c.example>"]),  # c has most mails
        *(mail(SENDER, to=[f"Bert Brandt <bert.brandt@{d}.example>"]) for d in "de"),  # tie
        mail(SENDER, to=["Max Mustermann <max.mustermann@kv.partei.example>"]),
        mail(SENDER, to=["Max Mustermann <m.mustermann@partei.example>"]),
        mail(SENDER, to=["Olaf Stern <olaf@f.example>"]),  # uncertain: the name alone
        mail(SENDER, to=["Olaf Stern <os@g.example>"]),
    ]
    await store(session, entries)
    await finalize(session)
    return await ids(session)


async def test_merging_every_certain_suggestion_as_one_batch(db_session: AsyncSession) -> None:
    person = await _certain_archive(db_session)
    start, figures = await _roots(db_session), await snapshot(db_session)
    anna = [f"anna.schmidt@{d}.example" for d in "abc"]
    tie = [
        sorted((person["bert.brandt@d.example"], person["bert.brandt@e.example"])),
        sorted((person["max.mustermann@kv.partei.example"], person["m.mustermann@partei.example"])),
    ]
    groups = [(person[anna[2]], sorted((person[anna[0]], person[anna[1]])))]
    groups += [(lower, [higher]) for lower, higher in tie]
    assert await certain_groups(db_session) == MergePlan(groups=sorted(groups), left_out=[])

    done = await merge_certain(db_session, "Lena Vogt")
    assert (done.merges, done.persons, done.left_out_groups) == (3, 4, 0)
    roots = await _roots(db_session)
    assert [roots[a] for a in anna] == [anna[2], anna[2], None]
    assert roots["olaf@f.example"] is None and roots["os@g.example"] is None
    logged = await _merges(db_session)
    assert {(row[2], row[3]) for row in logged} == {(done.batch_id, "Lena Vogt")}
    await _assert_consistent(db_session)
    # Nothing certain is left; the uncertain pair is still there.
    assert (await certain_groups(db_session)).groups == []
    assert set(await suggestions(db_session)) == {("olaf@f.example", "os@g.example")}
    assert done.batch_id is not None

    assert await undo_batch(db_session, done.batch_id, "Lena Vogt") == Undo(merges=3, persons=4)
    assert await _roots(db_session) == start
    assert await snapshot(db_session) == figures
    with pytest.raises(MergeUndone):
        await undo_batch(db_session, done.batch_id)
    with pytest.raises(UnknownMerge):
        await undo_batch(db_session, done.batch_id + 1)

    # One merge of a later batch undone alone; the batch undoes the rest.
    again = await merge_certain(db_session)
    assert again.batch_id is not None
    first = min(row[0] for row in await _merges(db_session) if row[2] == again.batch_id)
    alone = await undo_merge(db_session, first)
    rest = Undo(merges=2, persons=again.persons - alone.persons)
    assert await undo_batch(db_session, again.batch_id) == rest
    assert await _roots(db_session) == start


async def test_a_group_larger_than_merge_group_is_left_out(db_session: AsyncSession) -> None:
    # Four persons share name and local part, three more another; one alias links the groups.
    entries = [
        *(mail(SENDER, to=[f"Anna Schmidt <anna.schmidt@{d}.example>"]) for d in "abcd"),
        *(mail(SENDER, to=[f"Bert Brandt <bert.brandt@{d}.example>"]) for d in "efg"),
    ]
    await store(db_session, entries)
    await finalize(db_session)
    person = await ids(db_session)
    await merge_persons(
        db_session, person["anna.schmidt@a.example"], [person["bert.brandt@e.example"]]
    )
    plan = await certain_groups(db_session)
    assert plan.groups == []
    assert [len(group) for group in plan.left_out] == [MERGE_GROUP + 1]
    before = await _roots(db_session)
    done = await merge_certain(db_session)
    assert done == CertainMerge(None, 0, 0, 1, MERGE_GROUP + 1)
    assert await _roots(db_session) == before

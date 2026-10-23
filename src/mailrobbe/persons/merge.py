"""The user's writes on persons (D28, D162, D163): merging, undoing a merge, unmerging an
address, dismissing a suggestion.

Each runs in the caller's transaction and never commits. Merging, undoing and unmerging refresh
the aggregates of the persons concerned before they return (D33), so the caller reads the new
figures at once. Each takes the persons lock (roots.lock_persons) before it reads a root, so
they run one at a time and after a refresh that is under way: two merges at once could
otherwise re-point a person at a root that the other one merges away.

Every merge is logged (D163): person_merge names the root merged into, the editor (D54) and the
batch of "Alle sicheren zusammenführen" (merge_certain, D162, or with ai the pairs the text model
was sure of, D326) it belongs to;
person_merge_member every person it moved with its merged_into before. Undoing a merge puts
back the members that still belong to its target's current root, each to where it pointed
before (the current root of that person, unless it is the one undone from), and marks the merge
undone; the log keeps it. Unmerging one address (D28) logs nothing and stays possible for
merges from before the log.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects import postgresql

from mailrobbe.aggregates import refresh_aggregates
from mailrobbe.db.models import (
    AliasDismissal,
    AliasSuggestion,
    MergeBatch,
    Person,
    PersonMerge,
)
from mailrobbe.enums import AliasVerdict
from mailrobbe.persons.roots import Executor, lock_persons, resolve_root

MERGE_GROUP = 5  # persons joined by certain suggestions that are merged in one go (D162)
AI_MERGE_GROUP = 6  # persons joined by sure verdicts of the alias check (D326): its groups

# Certain suggestions between persons with figures, the ones the suggestion list shows, with the
# mails of both; suggestions are refreshed after every merge, so both are roots.
_CERTAIN = text("""
    SELECT s.person_a, s.person_b, a.mails, b.mails
    FROM alias_suggestion s
    JOIN person_stats a ON a.person_id = s.person_a
    JOIN person_stats b ON b.person_id = s.person_b
    WHERE s.tier = 'certain'
""")
# The newest verdict of every pair of roots the alias check judged (D323), with the mails of
# both: a sure verdict same joins two persons, different or unclear keeps them apart (D326).
_VERDICTS = text("""
    WITH latest AS (
        SELECT DISTINCT ON (least(ra, rb), greatest(ra, rb))
            least(ra, rb) AS a, greatest(ra, rb) AS b, c.verdict::text AS verdict, c.certain
        FROM alias_check c
        JOIN LATERAL (SELECT coalesce(merged_into, id) AS ra FROM person WHERE id = c.person_a) x
            ON true
        JOIN LATERAL (SELECT coalesce(merged_into, id) AS rb FROM person WHERE id = c.person_b) y
            ON true
        WHERE ra <> rb
        ORDER BY least(ra, rb), greatest(ra, rb), c.created_at DESC
    )
    SELECT l.a, l.b, sa.mails, sb.mails, l.verdict, l.certain
    FROM latest l
    JOIN person_stats sa ON sa.person_id = l.a
    JOIN person_stats sb ON sb.person_id = l.b
""")
_DISMISSED = text("""
    SELECT coalesce(a.merged_into, a.id), coalesce(b.merged_into, b.id)
    FROM alias_dismissal d JOIN person a ON a.id = d.person_a JOIN person b ON b.id = d.person_b
""")
_LOG = text("""
    INSERT INTO person_merge (target, batch_id, editor)
    SELECT unnest(CAST(:targets AS bigint[])), CAST(:batch AS bigint), CAST(:editor AS text)
    RETURNING id, target
""")
# Every person of a source's root, with where it pointed before.
_MEMBERS = text("""
    INSERT INTO person_merge_member (merge_id, person_id, previous_root)
    SELECT m.merge_id, p.id, p.merged_into
    FROM unnest(CAST(:merges AS bigint[]), CAST(:sources AS bigint[])) AS m (merge_id, source)
    JOIN person p ON p.id = m.source OR p.merged_into = m.source
""")
_MOVE = text("""
    UPDATE person p SET merged_into = m.target
    FROM unnest(CAST(:sources AS bigint[]), CAST(:targets AS bigint[])) AS m (source, target)
    WHERE p.id = m.source OR p.merged_into = m.source
""")
# The members of merges as they are now: their root, their target's root and the root of the
# person they pointed at before.
_UNDO = text("""
    SELECT m.merge_id, m.person_id, m.previous_root, coalesce(p.merged_into, p.id) AS root,
           coalesce(t.merged_into, t.id) AS target_root, coalesce(q.merged_into, q.id) AS before
    FROM person_merge_member m
    JOIN person_merge pm ON pm.id = m.merge_id
    JOIN person p ON p.id = m.person_id
    JOIN person t ON t.id = pm.target
    LEFT JOIN person q ON q.id = m.previous_root
    WHERE m.merge_id = ANY(CAST(:merges AS bigint[]))
""")
_PUT_BACK = text("""
    UPDATE person p SET merged_into = m.root
    FROM unnest(CAST(:persons AS bigint[]), CAST(:roots AS bigint[])) AS m (person, root)
    WHERE p.id = m.person
""")
_UNDONE = text("""
    UPDATE person_merge SET undone_at = now(), undone_by = :editor
    WHERE id = ANY(CAST(:merges AS bigint[]))
""")


class UnknownPerson(LookupError):
    def __init__(self, person_id: int) -> None:
        super().__init__(f"no person with id {person_id}")
        self.person_id = person_id


class UnknownMerge(LookupError):
    """No logged merge, or no batch of merges, with this id."""


class MergeError(ValueError):
    """Not possible: a person merged into itself, or unmerging a person that is no alias."""


class MergeUndone(ValueError):
    """The merge, or every merge of the batch, was undone already."""


@dataclass(frozen=True, slots=True)
class MergePlan:
    """What merge_certain merges: each group as its target and the roots merged into it."""

    groups: list[tuple[int, list[int]]]  # by target id
    left_out: list[list[int]]  # larger than MERGE_GROUP, or holding a dismissed pair


@dataclass(frozen=True, slots=True)
class CertainMerge:
    batch_id: int | None  # None when there was nothing to merge
    merges: int
    persons: int  # roots that became aliases
    left_out_groups: int
    left_out_persons: int


@dataclass(frozen=True, slots=True)
class Undo:
    merges: int  # merges marked undone
    persons: int  # persons put back


async def merge_persons(
    db: Executor, target: int, sources: Sequence[int], editor: str | None = None
) -> int:
    """Merge the sources and their aliases into target's root and log it; returns that root."""
    await lock_persons(db)
    root = await _root(db, target)
    merged = sorted({await _root(db, source) for source in sources})
    if root in merged:
        raise MergeError(f"person {target} cannot be merged into itself")
    await _merge(db, [(root, merged)], None, editor)
    await refresh_aggregates(db, [root, *merged])
    return root


async def certain_groups(db: Executor, ai: bool = False) -> MergePlan:
    """The persons joined by certain suggestions, in groups (D162), or with ai by the verdicts the
    text model was sure of (D326): merged into the one with the most mails, the lower id on a tie.
    A group holding a dismissed pair, or with ai a pair judged different or unclear, is left out,
    as is one larger than its limit."""
    mails: dict[int, int] = {}
    joined: list[tuple[int, int]] = []
    apart = {(min(a, b), max(a, b)) for a, b in await db.execute(_DISMISSED)}
    if ai:
        for a, b, mails_a, mails_b, verdict, certain in await db.execute(_VERDICTS):
            if verdict != AliasVerdict.SAME:
                apart.add((a, b))
            elif certain:
                mails[a], mails[b] = mails_a, mails_b
                joined.append((a, b))
    else:
        for a, b, mails_a, mails_b in await db.execute(_CERTAIN):
            mails[a], mails[b] = mails_a, mails_b
            joined.append((a, b))
    parent: dict[int, int] = {}

    def find(person: int) -> int:
        while parent[person] != person:
            parent[person] = parent[parent[person]]
            person = parent[person]
        return person

    for a, b in joined:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        parent[find(a)] = find(b)
    found: defaultdict[int, list[int]] = defaultdict(list)
    for person in sorted(parent):
        found[find(person)].append(person)
    limit = AI_MERGE_GROUP if ai else MERGE_GROUP
    groups, left_out = [], []
    for members in found.values():
        split = any((a, b) in apart for a in members for b in members if a < b)
        if len(members) > limit or split:
            left_out.append(members)
            continue
        target = min(members, key=lambda person: (-mails[person], person))
        groups.append((target, [person for person in members if person != target]))
    return MergePlan(sorted(groups), left_out)


async def merge_certain(db: Executor, editor: str | None = None, ai: bool = False) -> CertainMerge:
    """Merge every group of certain_groups as one batch, then refresh the aggregates once."""
    await lock_persons(db)
    plan = await certain_groups(db, ai)
    batch_id = None
    if plan.groups:
        batch_id = await db.scalar(
            postgresql.insert(MergeBatch).values(editor=editor).returning(MergeBatch.id)
        )
        await _merge(db, plan.groups, batch_id, editor)
        concerned = [person for target, sources in plan.groups for person in (target, *sources)]
        await refresh_aggregates(db, concerned)
    return CertainMerge(
        batch_id=batch_id,
        merges=len(plan.groups),
        persons=sum(len(sources) for _, sources in plan.groups),
        left_out_groups=len(plan.left_out),
        left_out_persons=sum(map(len, plan.left_out)),
    )


async def undo_merge(db: Executor, merge_id: int, editor: str | None = None) -> Undo:
    """Undo one logged merge (D163)."""
    await lock_persons(db)
    found = (
        await db.execute(select(PersonMerge.undone_at).where(PersonMerge.id == merge_id))
    ).first()
    if found is None:
        raise UnknownMerge(f"no merge with id {merge_id}")
    if found.undone_at is not None:
        raise MergeUndone(f"merge {merge_id} was undone already")
    return await _undo(db, [merge_id], editor)


async def undo_batch(db: Executor, batch_id: int, editor: str | None = None) -> Undo:
    """Undo every merge of a batch that is not undone yet (D162), refreshing once."""
    await lock_persons(db)
    if await db.scalar(select(MergeBatch.id).where(MergeBatch.id == batch_id)) is None:
        raise UnknownMerge(f"no batch of merges with id {batch_id}")
    merges = list(
        await db.scalars(
            select(PersonMerge.id).where(
                PersonMerge.batch_id == batch_id, PersonMerge.undone_at.is_(None)
            )
        )
    )
    if not merges:
        raise MergeUndone(f"every merge of batch {batch_id} was undone already")
    return await _undo(db, merges, editor)


async def unmerge_person(db: Executor, person_id: int) -> int:
    """Make an alias a person of its own again; returns the root it was merged into."""
    await lock_persons(db)
    found = (await db.execute(select(Person.merged_into).where(Person.id == person_id))).first()
    if found is None:
        raise UnknownPerson(person_id)
    root = found[0]
    if root is None:
        raise MergeError(f"person {person_id} is not merged into another")
    await db.execute(update(Person).where(Person.id == person_id).values(merged_into=None))
    await refresh_aggregates(db, [root, person_id])
    return int(root)


async def dismiss_suggestion(db: Executor, first: int, second: int) -> None:
    """Never suggest these two persons (their roots) as one again."""
    await lock_persons(db)
    roots = await _root(db, first), await _root(db, second)
    if roots[0] == roots[1]:
        raise MergeError(f"persons {first} and {second} are one person already")
    a, b = sorted(roots)
    insert = postgresql.insert(AliasDismissal).values(person_a=a, person_b=b)
    await db.execute(insert.on_conflict_do_nothing())
    await db.execute(
        delete(AliasSuggestion).where(AliasSuggestion.person_a == a, AliasSuggestion.person_b == b)
    )


async def _merge(
    db: Executor, groups: Sequence[tuple[int, Sequence[int]]], batch: int | None, editor: str | None
) -> None:
    """Log and make the merges of disjoint groups: every root of sources (with its aliases)
    into its target root."""
    rows = await db.execute(
        _LOG, {"targets": [target for target, _ in groups], "batch": batch, "editor": editor}
    )
    merge_of = {target: merge_id for merge_id, target in rows}
    pairs = [(source, target) for target, sources in groups for source in sources]
    params: dict[str, Any] = {
        "merges": [merge_of[target] for _, target in pairs],
        "sources": [source for source, _ in pairs],
        "targets": [target for _, target in pairs],
    }
    await db.execute(_MEMBERS, params)
    await db.execute(_MOVE, params)


async def _undo(db: Executor, merges: Sequence[int], editor: str | None) -> Undo:
    """Undo these merges, not undone yet, and refresh the persons concerned once.

    Each merge is undone against the persons as they are now. The merges of one batch moved
    disjoint groups, so undoing one of them changes nothing another one reads.
    """
    members: defaultdict[int, list[Any]] = defaultdict(list)
    for row in await db.execute(_UNDO, {"merges": list(merges)}):
        members[row.merge_id].append(row)
    back: dict[int, int | None] = {}  # person -> its merged_into after the undo
    concerned: set[int] = set()
    for rows in members.values():
        root = rows[0].target_root
        concerned.add(root)
        moving = {row.person_id for row in rows if row.root == root and row.person_id != root}
        for row in rows:
            if row.person_id not in moving:
                continue
            if row.previous_root is None or row.previous_root in moving:
                back[row.person_id] = row.previous_root  # a root again, or with it
            elif row.before != root:
                back[row.person_id] = row.before  # its root of before has moved on
    if back:
        await db.execute(_PUT_BACK, {"persons": list(back), "roots": list(back.values())})
    await db.execute(_UNDONE, {"merges": list(merges), "editor": editor})
    concerned.update(back, (root for root in back.values() if root is not None))
    await refresh_aggregates(db, sorted(concerned))
    return Undo(merges=len(merges), persons=len(back))


async def _root(db: Executor, person_id: int) -> int:
    root = await resolve_root(db, person_id)
    if root is None:
        raise UnknownPerson(person_id)
    return root

"""The user's writes on persons (D28): merging addresses, unmerging one, dismissing a suggestion.

Each runs in the caller's transaction and never commits. Merging and unmerging refresh the
aggregates of the persons concerned before they return (D33), so the caller reads the new
figures at once.
"""

from collections.abc import Sequence

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects import postgresql

from mailrobbe.aggregates import refresh_aggregates
from mailrobbe.db.models import AliasDismissal, AliasSuggestion, Person
from mailrobbe.persons.roots import Executor, resolve_root


class UnknownPerson(LookupError):
    def __init__(self, person_id: int) -> None:
        super().__init__(f"no person with id {person_id}")
        self.person_id = person_id


class MergeError(ValueError):
    """Not possible: a person merged into itself, or unmerging a person that is no alias."""


async def merge_persons(db: Executor, target: int, sources: Sequence[int]) -> int:
    """Merge the sources and their aliases into target's root; returns that root."""
    root = await _root(db, target)
    merged = {await _root(db, source) for source in sources}
    if root in merged:
        raise MergeError(f"person {target} cannot be merged into itself")
    await db.execute(
        update(Person)
        .where(or_(Person.id.in_(merged), Person.merged_into.in_(merged)))
        .values(merged_into=root)
    )
    await refresh_aggregates(db, [root, *sorted(merged)])
    return root


async def unmerge_person(db: Executor, person_id: int) -> int:
    """Make an alias a person of its own again; returns the root it was merged into."""
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
    roots = await _root(db, first), await _root(db, second)
    if roots[0] == roots[1]:
        raise MergeError(f"persons {first} and {second} are one person already")
    a, b = sorted(roots)
    insert = postgresql.insert(AliasDismissal).values(person_a=a, person_b=b)
    await db.execute(insert.on_conflict_do_nothing())
    await db.execute(
        delete(AliasSuggestion).where(AliasSuggestion.person_a == a, AliasSuggestion.person_b == b)
    )


async def _root(db: Executor, person_id: int) -> int:
    root = await resolve_root(db, person_id)
    if root is None:
        raise UnknownPerson(person_id)
    return root

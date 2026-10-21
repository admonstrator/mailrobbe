"""Alias suggestions (D30): pairs of root persons that may be the same person."""

from collections.abc import Collection

from mailrobbe.persons.roots import Executor


async def refresh_alias_suggestions(db: Executor, persons: Collection[int] | None = None) -> None:
    """Recompute alias_suggestion as a whole, or the pairs touching these persons.

    persons is read as in refresh_person_stats. Dismissed pairs (alias_dismissal) and persons
    of one root are never suggested.
    """
    return None  # placeholder of the milestone 5 contract

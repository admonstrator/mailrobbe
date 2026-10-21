"""person_stats and person_year of the root persons (D29)."""

from collections.abc import Collection

from mailrobbe.persons.roots import Executor


async def refresh_person_stats(db: Executor, persons: Collection[int] | None = None) -> None:
    """Recompute the figures of every root person, or only those of these persons.

    persons may name roots and former roots or aliases (after a merge or unmerge): the figures
    of each one's current root are recomputed, the rows of those that are no longer roots are
    deleted. Counts contacts from edge, so it runs after graph.edges.refresh_edges.
    """
    return None  # placeholder of the milestone 5 contract

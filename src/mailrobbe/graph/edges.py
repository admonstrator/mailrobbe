"""edge, edge_year and person.kind, recomputed from the imported mails (D36, D39).

Edges join root persons (coalesce(person.merged_into, person.id)) and count mails that are no
duplicates: the sender to each To/Bcc recipient in mails_a_to_b or mails_b_to_a, to each Cc
recipient in mails_cc, once per mail and pair (To before Cc), never a person to itself and never
recipients among themselves; the pass_* counters count the same for mails whose DKIM check
passed. edge_year holds the same counters per UTC year of date_utc; undated mails are only in
edge. global_stats gets a row "edges" with the number of pairs and the time of the refresh.

refresh_edges runs in the caller's transaction and never commits.
"""

from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

Executor = AsyncSession | AsyncConnection


async def refresh_edges(db: Executor, persons: Collection[int] | None = None) -> None:
    """Recompute edges and person kinds: all of them, or those touching some persons.

    persons may hold root persons and addresses merged into them or split off again; every edge
    touching one of them or its current root is deleted and counted again, and person.kind is
    recomputed for those roots. Serialised with other refreshes by an advisory lock.
    """
    raise NotImplementedError

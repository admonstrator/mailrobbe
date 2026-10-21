"""The root person of an address (D28).

person.merged_into always names a root, never another alias: merging re-points the aliases of
a merged person too. So the root of an address is one coalesce, in SQL and in every query.

Merges and the refreshes of person figures and suggestions take the transaction-level advisory
lock LOCK_KEY first (lock_persons), so they run one after another: a merge during a finalize
waits for its refresh, and two merges at once cannot leave merged_into naming an alias.
"""

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.db.models import Person

Executor = AsyncSession | AsyncConnection

ROOT: ColumnElement[int] = func.coalesce(Person.merged_into, Person.id)

LOCK_KEY = int.from_bytes(b"mrperson", "big")


async def lock_persons(db: Executor) -> None:
    """Wait for the persons lock, held until the transaction ends; granted at once if held."""
    await db.execute(select(func.pg_advisory_xact_lock(LOCK_KEY)))


async def resolve_root(db: Executor, person_id: int) -> int | None:
    """The root of this person (itself when it is one); None when there is no such person."""
    return await db.scalar(select(ROOT).where(Person.id == person_id))


async def member_ids(db: Executor, root: int) -> list[int]:
    """The root and every person merged into it, root first, then by id."""
    rows = await db.scalars(
        select(Person.id)
        .where(or_(Person.id == root, Person.merged_into == root))  # both indexed, unlike ROOT
        .order_by(Person.merged_into.is_not(None), Person.id)
    )
    return list(rows)

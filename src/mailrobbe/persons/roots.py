"""The root person of an address (D28).

person.merged_into always names a root, never another alias: merging re-points the aliases of
a merged person too. So the root of an address is one coalesce, in SQL and in every query.
"""

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.db.models import Person

Executor = AsyncSession | AsyncConnection

ROOT: ColumnElement[int] = func.coalesce(Person.merged_into, Person.id)


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

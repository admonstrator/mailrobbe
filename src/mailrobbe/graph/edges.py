"""edge and edge_year between root persons (milestone 6, SPEC 3.3).

Placeholder until milestone 6 lands: the persons side (milestone 5) calls it in
aggregates.refresh_aggregates, so the call order is fixed already.
"""

from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


async def refresh_edges(
    db: AsyncSession | AsyncConnection, persons: Collection[int] | None = None
) -> None:
    """Recompute the edges (all, or those touching these persons and their roots); never commits."""
    return None

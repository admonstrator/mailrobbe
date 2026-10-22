"""The import's step hidden (D221): the mails of every enabled hide rule computed again, so new
mails and the addresses merges gave a person are covered. Database only."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.jobrun import Step

STEP = "hidden"


async def refresh_hidden(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event, step: Step
) -> int:
    """The step hidden; the rules computed. Contract stub: milestone 18 fills it."""
    return 0

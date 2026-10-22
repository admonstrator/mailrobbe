"""The import's steps paragraphs and blocks (D224, D225). Database only: the stored texts
(mail.body_text) are split, nothing is read from the MBOX files."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.config import Settings
from mailrobbe.jobrun import Step

STEPS = ("paragraphs", "blocks")  # in order


async def waiting(session: AsyncSession) -> int:
    """Mails not split by the current PARAGRAPH_VERSION. Contract stub: milestone 18 fills it."""
    return 0


async def split_mails(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event, step: Step
) -> int:
    """The step paragraphs; the mails split. Contract stub."""
    return 0


async def find_blocks(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    stop: asyncio.Event,
    step: Step,
) -> int:
    """The step blocks; the mails whose ranges changed. Contract stub."""
    return 0

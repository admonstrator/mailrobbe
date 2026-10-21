"""The near phase of an import (D153), from the database alone; nothing is read from the MBOX
files.

    near_texts   the fingerprint (model.fingerprint) of every mail without a mail_near row or
                 with one of an older NEAR_VERSION, from mail.subject and mail.body_text
    near_groups  mail_near.group_id recomputed for every mail in one statement, rows written
                 only where it changed; then the figures in global_stats 'near'

A stop (D46) ends near_texts between two batches: the fingerprints stored so far stay, and the
groups are left as they were until the next import.
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.jobrun import Step

STEPS = ("near_texts", "near_groups")  # in order


async def waiting(session: AsyncSession) -> int:
    """Mails without a fingerprint of the current NEAR_VERSION."""
    return 0  # milestone 14: near duplicates


async def fingerprint_mails(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event, step: Step
) -> int:
    """The step near_texts: fingerprint the waiting mails; the mails stored."""
    raise NotImplementedError("milestone 14: near duplicates")


async def group_mails(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event, step: Step
) -> int:
    """The step near_groups: recompute the groups and the figures; the mails in a group."""
    return 0  # milestone 14: near duplicates

"""The topics phase of an import (D146).

Contract stub: waiting() says there is nothing to do, so the import skips the phase's steps.
The phase itself (fingerprint, the passes over mail.tsv and the texts, the periods, the clusters
and the final replacement of the stored results) follows.
"""

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.jobrun import Steps

STEPS = ("topic_terms", "topic_labels", "topic_periods", "topic_clusters")  # in order


@dataclass(frozen=True, slots=True)
class TopicsResult:
    """What one compute_topics stored, for the import's summary and the tests."""

    terms: int  # the vocabulary
    periods: int  # periods of all units with mails
    clusters: int
    seconds: float


async def waiting(session: AsyncSession) -> str | None:
    """The fingerprint of the archive as it is now when the stored topics were computed for
    another one (or never), else None: nothing to do."""
    return None


async def compute_topics(
    sessionmaker: async_sessionmaker[AsyncSession],
    fingerprint: str,
    stop: asyncio.Event,
    steps: Steps,
) -> TopicsResult | None:
    """Compute and store every topic for the archive of fingerprint, reporting the STEPS; None
    when a stop came first (the stored results stay as they were)."""
    raise NotImplementedError

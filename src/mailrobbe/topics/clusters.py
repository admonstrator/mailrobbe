"""Clusters of terms that stand together in the archive's mails (D145).

Contract stub: find_clusters finds none yet.
"""

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.topics.model import Cluster, Term


async def find_clusters(
    session: AsyncSession, vocabulary: Mapping[str, Term], total: int
) -> list[Cluster]:
    """The clusters over the vocabulary (lexeme -> Term) of an archive of total mails that are
    no duplicates, most mails first, at most CLUSTER_LIMIT. Reads mail.tsv through session."""
    return []

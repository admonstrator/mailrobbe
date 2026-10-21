"""How often q's full text words occur in a mail, by place (D174, D176): the count min_hits
compares and the figures the mail list and the mail detail show, from the same words
(FullText.counted) and by the same rules.

Contract: the functions below are filled by the counting work; filters.py and mails.py call
them. This module must not import filters.py, which imports it.
"""

from collections.abc import Sequence

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.fulltext import FullText
from mailrobbe.api.schemas import MailHitCounts


def hit_count(search: FullText) -> ColumnElement[int]:
    """The occurrences of search's counted words in the mail (correlated to mail) and the
    texts and file names of its attachments' documents, each in its places (D174)."""
    raise NotImplementedError("min_hits is counted by the counting work (D174)")


async def page_hits(
    session: AsyncSession, mail_ids: Sequence[int], search: FullText
) -> dict[int, MailHitCounts]:
    """The counts by place of the mails of a page, every one of mail_ids present (D176)."""
    raise NotImplementedError("hits by place are counted by the counting work (D176)")

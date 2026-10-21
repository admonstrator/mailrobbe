"""Near duplicates in the mail list and the mail detail (D153), read from mail_near."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import NearMail


@dataclass(slots=True)
class NearGroup:
    """A mail's group as MailDetail shows it; group_id None: the mail is in no group."""

    group_id: int | None = None
    mails: list[NearMail] = field(default_factory=list)  # the others, oldest first, NEAR_LIMIT
    size: int = 0  # the whole group, this mail included; 0 without a group


async def near_counts(session: AsyncSession, mail_ids: Sequence[int]) -> dict[int, int]:
    """For the mails of a list page: the other mails of each one's group; mails without one
    are left out."""
    return {}  # milestone 14: near duplicates


async def near_group(session: AsyncSession, mail_id: int) -> NearGroup:
    """The group of near duplicates of one mail."""
    return NearGroup()  # milestone 14: near duplicates

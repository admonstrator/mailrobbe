"""Seam to the DKIM check of milestone 3 (mailrobbe.dkim), agreed with that milestone.

Until mailrobbe.dkim is merged every function here is a no-op: no checker, so imported mails
keep dkim_status NULL ("not checked yet") and the DKIM command checks them later. Whichever of
the two milestones merges second replaces the three function bodies with the calls
load_dns_cache, DkimChecker.from_settings and upsert_dns_cache; nothing else changes.
"""

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.config import Settings
from mailrobbe.enums import DkimStatus


class DkimVerdict(Protocol):
    @property
    def status(self) -> DkimStatus:
        """Overall status of the mail, for mail.dkim_status."""
        ...

    def result_rows(self, mail_id: int, checked_at: datetime) -> list[dict[str, Any]]:
        """One dict per signature, keyed by dkim_result column names; empty when unsigned."""
        ...


class DkimChecker(Protocol):
    def check(self, raw: bytes) -> DkimVerdict:
        """Verify every DKIM-Signature of a message (mailrobbe.mbox semantics); never raises."""
        ...

    def take_new_answers(self) -> list[Any]:
        """DNS answers fetched since the last call, for save_answers."""
        ...


async def load_preload(session: AsyncSession) -> Any:
    """Main process, once per run: the cached DNS answers handed to every worker (picklable)."""
    return None


def create_checker(settings: Settings, preload: Any) -> DkimChecker | None:
    """Once per worker process; None means mails are imported without a DKIM check."""
    return None


async def save_answers(session: AsyncSession, answers: list[Any]) -> None:
    """Per batch, inside the batch transaction: persist the checker's new DNS answers."""
    return None

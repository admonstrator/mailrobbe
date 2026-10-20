"""DKIM results and the DNS cache in PostgreSQL (dkim_result, dns_cache, mail.dkim_status).

The functions take an AsyncSession or AsyncConnection and run inside the caller's transaction;
they never commit. The importer writes result rows itself (MailVerdict.result_rows) and uses
load_dns_cache/upsert_dns_cache; the recheck command and the API use save_verdicts.
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.dkim.model import DnsAnswer, MailVerdict

Executor = AsyncSession | AsyncConnection


async def load_dns_cache(db: Executor) -> list[DnsAnswer]:
    """Every dns_cache row as an answer with from_cache=True (temp_error with dns_timeout)."""
    raise NotImplementedError


async def upsert_dns_cache(db: Executor, answers: Iterable[DnsAnswer]) -> None:
    """Insert or replace dns_cache rows by name; answers with ttl 0 are skipped."""
    raise NotImplementedError


async def save_verdicts(
    db: Executor, verdicts: Iterable[tuple[int, MailVerdict]], checked_at: datetime | None = None
) -> None:
    """Replace the dkim_result rows of each mail and set mail.dkim_status.

    checked_at defaults to the current time, the same for every row of the call.
    """
    raise NotImplementedError

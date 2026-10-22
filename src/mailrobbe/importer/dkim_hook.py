"""Seam to the DKIM check of milestone 3 (mailrobbe.dkim), agreed with that milestone.

The importer sees DKIM only through these protocols and three functions: the main process loads
the cached DNS answers and the candidate keys of deleted selectors once (D101: new mails are
checked against them too), every worker process builds one checker from them, and each batch
persists the answers its checker had to look up, inside the batch transaction.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.config import Settings
from mailrobbe.dkim import checker, store
from mailrobbe.dkim.keys.store import keep_cached_keys, load_candidates
from mailrobbe.dkim.model import DnsAnswer, KeyCandidates
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


@dataclass(frozen=True, slots=True)
class Preload:
    """What every worker's checker starts from (picklable)."""

    answers: list[DnsAnswer]  # dns_cache
    candidates: KeyCandidates = field(default_factory=dict)  # keys of deleted selectors by name


async def load_preload(session: AsyncSession) -> Preload:
    """Main process, once per run: the cached DNS answers and candidate keys for every worker;
    found answers not kept as keys yet are kept first (D106)."""
    await keep_cached_keys(session)
    return Preload(await store.load_dns_cache(session), await load_candidates(session))


def create_checker(settings: Settings, preload: Preload) -> DkimChecker | None:
    """Once per worker process; None means mails are imported without a DKIM check."""
    return checker.DkimChecker.from_settings(
        settings, preload=preload.answers, candidates=preload.candidates
    )


async def save_answers(session: AsyncSession, answers: list[Any]) -> None:
    """Per batch, inside the batch transaction: persist the checker's new DNS answers.

    Workers look up the same keys in different orders; written in name order, concurrent batch
    transactions lock the dns_cache rows in one order and cannot deadlock.
    """
    await store.upsert_dns_cache(session, sorted(answers, key=lambda answer: answer.name))

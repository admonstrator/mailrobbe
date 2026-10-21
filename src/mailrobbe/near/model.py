"""The fingerprint of near duplicates and the figures of the near phase (D152, D153): the
contract between the phase, the API and the dashboard."""

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.db.models import GlobalStats

Executor = AsyncSession | AsyncConnection

FIGURES_KEY = "near"  # global_stats key of NearFigures
MIN_WORDS = 10  # a text with fewer words gets no fingerprint, so "Danke" never pairs (D152)


def fingerprint_text(subject: str | None, text: str | None) -> str | None:
    """What two near duplicates have in common (D152): the subject without reply and forward
    prefixes and list tags, and the text with quote markers, the header block of a forwarded or
    original message and a first greeting line removed, case folded, words of letters and
    digits joined by single spaces. A text whose own part is empty (a forward or quote without
    a word added) gives what it forwards. None when the text has fewer than MIN_WORDS words."""
    raise NotImplementedError("milestone 14: near duplicates")


def fingerprint(subject: str | None, text: str | None) -> bytes | None:
    """The SHA-256 of fingerprint_text, as stored in mail_near.fingerprint."""
    normalised = fingerprint_text(subject, text)
    return None if normalised is None else hashlib.sha256(normalised.encode()).digest()


@dataclass(frozen=True, slots=True)
class NearFigures:
    """What the last near phase found (D153)."""

    computed_at: datetime  # when the phase ended
    groups: int  # groups of near duplicates
    mails: int  # mails in them that are no duplicates
    hidden: int  # mails collapse_near leaves out: in a group but not its first, duplicates too

    def to_json(self) -> dict[str, Any]:
        return asdict(self) | {"computed_at": self.computed_at.isoformat()}

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "NearFigures":
        return cls(
            computed_at=datetime.fromisoformat(value["computed_at"]),
            groups=value["groups"],
            mails=value["mails"],
            hidden=value["hidden"],
        )


async def read_figures(db: Executor) -> NearFigures | None:
    """The figures of the last near phase; None when none ran yet."""
    value = await db.scalar(select(GlobalStats.value).where(GlobalStats.key == FIGURES_KEY))
    return None if value is None else NearFigures.from_json(value)


async def write_figures(db: Executor, figures: NearFigures) -> None:
    """Store the figures of a phase, in the caller's transaction."""
    statement = postgresql.insert(GlobalStats).values(key=FIGURES_KEY, value=figures.to_json())
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[GlobalStats.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
    )

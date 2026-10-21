"""The fingerprint of near duplicates and the figures of the near phase (D152, D153): the
contract between the phase, the API and the dashboard."""

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe import quotes
from mailrobbe.db.models import GlobalStats

Executor = AsyncSession | AsyncConnection

FIGURES_KEY = "near"  # global_stats key of NearFigures
MIN_WORDS = 10  # a text with fewer words gets no fingerprint, so "Danke" never pairs (D152)

# Reply and forward prefixes, also with a counter (AW[2]:, Re^2:), and list tags in brackets.
_PREFIXES = re.compile(
    r"(?:(?:re|aw|wg|fw|fwd|tr|sv|vs|antw|antwort)\s*(?:\[\d+\]|\(\d+\)|\^\d+)?\s*:"
    r"|\[[^\]]*\])\s*",
    re.I,
)
# A first line that only greets: the same text sent to several people one by one differs there.
_GREETING = re.compile(
    r"(?:hallo|hi|hey|liebe[rs]?|sehr geehrte[rs]?|guten (?:tag|morgen|abend)|dear|hello|moin"
    r"|servus)\b.{0,60}",
    re.I,
)
_WORD = re.compile(r"[^\W_]+")  # letters and digits


def fingerprint_text(subject: str | None, text: str | None) -> str | None:
    """What two near duplicates have in common (D152): the subject without reply and forward
    prefixes and list tags, and the text with quote markers, the attributions and the header
    blocks of forwarded or original messages removed (quotes.unquoted_lines) and a first
    greeting line, case folded, words of letters and digits joined by single spaces. So a text
    without a word of its own (a forward or quote) gives what it forwards. None when the text
    has fewer than MIN_WORDS words."""
    lines = quotes.unquoted_lines(text or "")
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is not None and _GREETING.fullmatch(lines[first].strip()):
        del lines[first]
    words = _WORD.findall("\n".join(lines).casefold())
    if len(words) < MIN_WORDS:
        return None
    title = (subject or "").strip()
    while match := _PREFIXES.match(title):
        title = title[match.end() :]
    return " ".join(_WORD.findall(title.casefold())) + "\n" + " ".join(words)


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

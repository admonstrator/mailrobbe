"""The paragraphs of a mail's text and their hashes (D224), and the figures of the blocks step:
the one rule the import's steps, the mail detail and the API share. The rule is pure and
deterministic; a change to it must raise db.models.PARAGRAPH_VERSION, so every mail is split
again (test_model pins the hash of one text).

quotes.split_text cuts a text into segments, and each segment is cut at blank lines into
paragraphs: runs of lines that hold something besides quote markers. The separator line of a
signature ("-- ", also quoted) belongs to no paragraph, so a signature written with and without
it is one paragraph. A paragraph counts when its normalised form (the quote markers at the line
starts removed, case folded, every run of white space one space) has at least MIN_CHARS
characters; its hash is the first 8 bytes of the SHA-256 of that form, big endian, signed:

    quoted  its segment is a quote, an original or a forward
    tail    not quoted, and in a signature, or among the last TAIL_PARAGRAPHS paragraphs of the
            own text (its text and signature segments, short paragraphs counted too) but not its
            first: where the blocks step detects standard blocks (D225)

history gives the ranges of the quoted segments, merged, as mail.history keeps them (D226).
Offsets count characters (code points) of the text, ranges are half open.

A hash is a signed 64-bit integer in the database (mail_paragraph.hash) and 16 lower-case hex
digits of its unsigned value in the API (schemas.BLOCK_HASH_PATTERN).
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe import quotes
from mailrobbe.db.models import GlobalStats

Executor = AsyncSession | AsyncConnection

MIN_CHARS = 30  # characters of the normalised form a paragraph needs to count
TAIL_PARAGRAPHS = 3  # the last paragraphs of the own text where standard blocks are detected
FIGURES_KEY = "blocks"  # global_stats key of BlockFigures

_QUOTED: frozenset[quotes.Kind] = frozenset({"quote", "original", "forward"})
_OWN: frozenset[quotes.Kind] = frozenset({"text", "signature"})
_MARKERS = re.compile(r"^\s*(?:>\s?)+")  # as quotes.unquoted_lines removes them
_SPACE = re.compile(r"\s+")
_DELIMITERS = ("-- ", "--")  # a signature's separator line, as quotes.split_text knows it
_MASK = (1 << 64) - 1

Range = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Paragraph:
    start: int  # character offset of its first line in the text
    end: int  # the end of its last line, before the line break
    hash: int
    quoted: bool
    tail: bool


def normalise(text: str) -> str:
    """What makes two paragraphs the same: no quote markers at the line starts, case folded,
    every run of white space one space, none at the ends."""
    lines = (_MARKERS.sub("", line) for line in text.split("\n"))
    return _SPACE.sub(" ", "\n".join(lines).casefold()).strip()


def paragraph_hash(text: str) -> int | None:
    """The hash of a paragraph as written; None when it is too short to count."""
    normalised = normalise(text)
    return _hash(normalised) if len(normalised) >= MIN_CHARS else None


def _blank(line: str) -> bool:
    """Whether a line ends a paragraph: nothing but quote markers and white space on it, or a
    signature's separator."""
    bare = _MARKERS.sub("", line)
    return not bare.strip() or bare.rstrip("\r\n") in _DELIMITERS


def paragraphs(text: str, segments: Sequence[quotes.Segment] | None = None) -> list[Paragraph]:
    """Every paragraph of the text that counts, in text order (module docstring); segments are
    quotes.split_text(text) when the caller has them already."""
    runs = _runs(text, quotes.split_text(text) if segments is None else segments)
    own = [index for index, (_, _, kind) in enumerate(runs) if kind in _OWN]
    last = {index: rank for rank, index in enumerate(own)}
    found = []
    for index, (start, end, kind) in enumerate(runs):
        normalised = normalise(text[start:end])
        if len(normalised) < MIN_CHARS:
            continue
        rank = last.get(index)
        tail = rank is not None and (
            kind == "signature" or (rank >= len(own) - TAIL_PARAGRAPHS and rank > 0)
        )
        found.append(Paragraph(start, end, _hash(normalised), kind in _QUOTED, tail))
    return found


def history(text: str, segments: Sequence[quotes.Segment] | None = None) -> list[Range]:
    """The ranges of the quotes, originals and forwards, adjacent ones merged."""
    ranges: list[Range] = []
    for segment in quotes.split_text(text) if segments is None else segments:
        if segment.kind not in _QUOTED or segment.end <= segment.start:
            continue
        if ranges and ranges[-1][1] == segment.start:
            ranges[-1] = (ranges[-1][0], segment.end)
        else:
            ranges.append((segment.start, segment.end))
    return ranges


def multirange(ranges: Sequence[Range]) -> str | None:
    """The int4multirange literal of ranges; None for none, as the columns keep no empty one."""
    if not ranges:
        return None
    return "{" + ",".join(f"[{start},{end})" for start, end in ranges) + "}"


def _runs(text: str, segments: Sequence[quotes.Segment]) -> list[tuple[int, int, quotes.Kind]]:
    """(start, end, segment kind) of every run of lines up to a blank line within a segment."""
    runs: list[tuple[int, int, quotes.Kind]] = []
    index = 0  # the segment holding the line
    reading = -1  # the segment of the run being read; -1: none
    offset = 0
    for line in text.split("\n"):
        while index < len(segments) and segments[index].end <= offset:
            index += 1
        if index == len(segments) or _blank(line):
            reading = -1
        elif reading == index:
            runs[-1] = (runs[-1][0], offset + len(line), runs[-1][2])
        else:
            reading = index
            runs.append((offset, offset + len(line), segments[index].kind))
        offset += len(line) + 1
    return runs


def _hash(normalised: str) -> int:
    digest = hashlib.sha256(normalised.encode("utf-8", "surrogatepass")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def hash_hex(value: int) -> str:
    """The API's form of a stored hash."""
    return format(value & _MASK, "016x")


def parse_hash(text: str) -> int:
    """The stored form of an API hash (16 hex digits, as BLOCK_HASH_PATTERN checks)."""
    value = int(text, 16)
    return value - (1 << 64) if value >= 1 << 63 else value


@dataclass(frozen=True, slots=True)
class BlockFigures:
    """What the last blocks step applied (D225), the stored part of schemas.BlockSummary."""

    computed_at: datetime  # when the step ended
    blocks: int  # standard blocks
    detected: int  # of these, by the rule
    marked: int  # of these, by hand only
    dismissed: int  # detected and taken back
    mails: int  # mails that are no duplicates holding at least one standard block

    def to_json(self) -> dict[str, Any]:
        return asdict(self) | {"computed_at": self.computed_at.isoformat()}

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "BlockFigures":
        return cls(
            computed_at=datetime.fromisoformat(value["computed_at"]),
            blocks=value["blocks"],
            detected=value["detected"],
            marked=value["marked"],
            dismissed=value["dismissed"],
            mails=value["mails"],
        )


async def read_figures(db: Executor) -> BlockFigures | None:
    """The figures of the last blocks step; None when none ran yet."""
    value = await db.scalar(select(GlobalStats.value).where(GlobalStats.key == FIGURES_KEY))
    return None if value is None else BlockFigures.from_json(value)


async def write_figures(db: Executor, figures: BlockFigures) -> None:
    """Store the figures of a step, in the caller's transaction."""
    statement = postgresql.insert(GlobalStats).values(key=FIGURES_KEY, value=figures.to_json())
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[GlobalStats.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
    )

# ruff: noqa: RUF001  (typographic quotes and dashes are folded)
"""Checking instead of believing (D304), pure: a text model's answer read by the summary's JSON
schema and checked against the text it was given.

    read     the answer is the JSON object of answer_schema. A service without structured answers
             may wrap it: think blocks (<think>...</think>, also one its length cut open) and
             code fences are removed and the first complete JSON object counts. A missing or
             mistyped key is an AnswerError, an attempt of the task (D184)
    tags     strings with their spaces tidied; longer than TAG_MAX_CHARS dropped (not cut), equal
             by model.tag_key once, at most SUMMARY_MAX_TAGS
    themes   only the keys of themes.toml (a theme's name is taken for its key); each with a quote
             of at most QUOTE_MAX_CHARS that stands in the text, compared case folded, with runs
             of whitespace as one space and every kind of quotation mark, apostrophe and dash as
             one; kept as the text spells it with its position there, or, found only in the head
             (subject, file name), without one; the same place once and THEME_HINTS_PER_THEME per
             theme (limit_hints)

What does not pass is dropped and counted, never repaired: a summary's tags and hints are what the
model said and the text shows.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from mailrobbe.ai.model import (
    QUOTE_MAX_CHARS,
    SUMMARY_MAX_HINTS,
    SUMMARY_MAX_TAGS,
    TAG_MAX_CHARS,
    THEME_HINTS_PER_THEME,
    ThemeHint,
    tag_key,
)
from mailrobbe.ai.services import AnswerError
from mailrobbe.themes import Theme

QUOTE_MIN_CHARS = 2  # a shorter quote stands anywhere and shows nothing
_DETAIL = 200  # characters of an answer in an error

_THINK = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```[\w-]*")
# Compared as one kind each (D304): quotation marks, apostrophes, dashes. Invisible characters a
# PDF's text may hold between letters are left out.
_DOUBLE = '"„“”‟«»″'
_SINGLE = "'‚‘’‛‹›′`´"
_DASHES = "-‐‑‒–—―−"
_FOLD = str.maketrans(
    {**dict.fromkeys(_DOUBLE, '"'), **dict.fromkeys(_SINGLE, "'"), **dict.fromkeys(_DASHES, "-")}
)
_INVISIBLE = frozenset("­​‌‍⁠﻿")
_EDGES = _DOUBLE + _SINGLE + "…"


def answer_schema(theme_keys: Sequence[str]) -> dict[str, Any]:
    """The JSON schema of an answer (D304): summary, tags, and themes with their quotes, the
    theme by one of these keys. Strict: every key required, no others; at most SUMMARY_MAX_TAGS
    tags and SUMMARY_MAX_HINTS themes, so a service bound to the schema cannot list on and on."""
    theme: dict[str, Any] = {"type": "string"}
    if theme_keys:
        theme["enum"] = list(theme_keys)
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}, "maxItems": SUMMARY_MAX_TAGS},
            "themes": {
                "type": "array",
                "maxItems": SUMMARY_MAX_HINTS,
                "items": {
                    "type": "object",
                    "properties": {"theme": theme, "quote": {"type": "string"}},
                    "required": ["theme", "quote"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "tags", "themes"],
        "additionalProperties": False,
    }


@dataclass(frozen=True, slots=True)
class Answer:
    """An answer as read, before the checks."""

    summary: str
    tags: list[str]  # the strings among the tags
    themes: list[tuple[str, str]]  # theme and quote as the model wrote them
    malformed_tags: int  # tags that are no strings
    malformed_themes: int  # themes that are no objects of a theme and a quote


def read_answer(answer: str) -> Answer:
    """The answer's JSON object (module docstring); raises AnswerError."""
    found = answer_object(answer)
    if found is None:
        raise AnswerError(f"no JSON object in the answer: {shown(answer)}")
    summary, tags, themes = found.get("summary"), found.get("tags"), found.get("themes")
    if not isinstance(summary, str):
        raise AnswerError(f"the answer has no text under summary: {shown(answer)}")
    if not isinstance(tags, list) or not isinstance(themes, list):
        raise AnswerError(f"the answer has no list under tags or themes: {shown(answer)}")
    labels = [tag for tag in tags if isinstance(tag, str)]
    hints = [
        (item["theme"], item["quote"])
        for item in themes
        if isinstance(item, dict)
        and isinstance(item.get("theme"), str)
        and isinstance(item.get("quote"), str)
    ]
    return Answer(
        summary=summary.strip(),
        tags=labels,
        themes=hints,
        malformed_tags=len(tags) - len(labels),
        malformed_themes=len(themes) - len(hints),
    )


def answer_object(answer: str) -> dict[str, Any] | None:
    """The first complete JSON object of an answer, without think blocks and code fences; the
    alias check (ai.aliases.step) reads its answers so too."""
    return _first_object(_FENCE.sub("", _THINK.sub("", answer)))


def _first_object(text: str) -> dict[str, Any] | None:
    """The first complete JSON object in text, trying from each "{"."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start >= 0:
        try:
            found, _ = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
            continue
        return found if isinstance(found, dict) else None
    return None


def shown(answer: str) -> str:
    """The start of an answer for an error message."""
    return " ".join(answer.split())[:_DETAIL] or "an empty answer"


@dataclass(frozen=True, slots=True)
class Checked:
    """An answer after the checks."""

    summary: str
    tags: list[str]
    themes: list[ThemeHint]  # position: offset in the text checked against; None: in the head
    dropped_tags: int
    dropped_themes: int


def check_answer(answer: Answer, *, text: str, head: str, themes: Sequence[Theme]) -> Checked:
    """The answer's tags and theme hints checked (module docstring) against text, the text the
    model was given after the head lines head."""
    tags, dropped_tags = check_tags(answer.tags)
    hints, dropped_themes = check_themes(answer.themes, text=text, head=head, themes=themes)
    kept, beyond = limit_hints(hints)
    return Checked(
        summary=answer.summary,
        tags=tags,
        themes=kept,
        dropped_tags=dropped_tags + answer.malformed_tags,
        dropped_themes=dropped_themes + beyond + answer.malformed_themes,
    )


def check_tags(labels: Sequence[str]) -> tuple[list[str], int]:
    """The tags kept, in their order, and how many were dropped (too long, beyond the limit)."""
    kept: list[str] = []
    keys: set[str] = set()
    dropped = 0
    for label in labels:
        label = " ".join(label.split())
        key = tag_key(label)
        if not key or key in keys:
            continue
        if len(label) > TAG_MAX_CHARS or len(kept) == SUMMARY_MAX_TAGS:
            dropped += 1
            continue
        keys.add(key)
        kept.append(label)
    return kept, dropped


def check_themes(
    found: Sequence[tuple[str, str]], *, text: str, head: str, themes: Sequence[Theme]
) -> tuple[list[ThemeHint], int]:
    """The hints whose theme is known and whose quote stands in text (with its position) or in
    head (without), each place once; and how many were dropped."""
    keys = {tag_key(name): theme.key for theme in themes for name in (theme.key, theme.name)}
    in_text, in_head = _Folded(text), _Folded(head)
    hints: list[ThemeHint] = []
    dropped = 0
    for theme, quote in found:
        key = keys.get(tag_key(theme))
        wanted = _bare(quote)
        if key is None or len(wanted) > QUOTE_MAX_CHARS:
            dropped += 1
            continue
        span = in_text.find(wanted)
        if span is not None:
            hints.append(ThemeHint(theme=key, quote=text[span[0] : span[1]], position=span[0]))
            continue
        span = in_head.find(wanted)
        if span is not None:
            hints.append(ThemeHint(theme=key, quote=head[span[0] : span[1]], position=None))
            continue
        dropped += 1
    return hints, dropped


def _bare(quote: str) -> str:
    """A quote without the quotation marks and ellipses a model may put around it."""
    bare = quote.strip().strip(_EDGES).strip()
    return bare.removeprefix("...").removesuffix("...").strip()


def limit_hints(hints: Sequence[ThemeHint]) -> tuple[list[ThemeHint], int]:
    """The hints in their order, the same theme and place (its position, or the quote of one in
    the head) once, at most THEME_HINTS_PER_THEME per theme; and how many were beyond."""
    kept: list[ThemeHint] = []
    places: set[tuple[str, int | str]] = set()
    counts: dict[str, int] = {}
    beyond = 0
    for hint in hints:
        place = (hint.theme, hint.quote if hint.position is None else hint.position)
        if place in places:
            continue
        if counts.get(hint.theme, 0) == THEME_HINTS_PER_THEME:
            beyond += 1
            continue
        places.add(place)
        counts[hint.theme] = counts.get(hint.theme, 0) + 1
        kept.append(hint)
    return kept, beyond


class _Folded:
    """A text as quotes are compared with it (module docstring), with the offset in the text of
    each character it holds."""

    def __init__(self, text: str) -> None:
        chars: list[str] = []
        self.origins: list[int] = []
        space = False
        for index, char in enumerate(text):
            if char in _INVISIBLE:
                continue
            if char.isspace():
                if not space:
                    chars.append(" ")
                    self.origins.append(index)
                space = True
                continue
            space = False
            for folded in char.translate(_FOLD).casefold():
                chars.append(folded)
                self.origins.append(index)
        self.text = "".join(chars)

    def find(self, quote: str) -> tuple[int, int] | None:
        """Where quote first stands in the text: start and end offsets there, or None."""
        wanted = _Folded(quote).text.strip()
        if len(wanted) < QUOTE_MIN_CHARS:
            return None
        at = self.text.find(wanted)
        if at < 0:
            return None
        return self.origins[at], self.origins[at + len(wanted) - 1] + 1

"""Long texts in parts (D303), pure: a text too long for the model's context beside the prompt
and the answer is cut into parts that fit.

A part may hold the context the model was loaded with, less what goes with every part (the system
prompt, the instruction, the head lines and the markers), the answer (SUMMARY_ANSWER_TOKENS) and
a margin for the chat template, counted at CHARS_PER_TOKEN characters per token: no tokenizer is
at hand for every model; the answer itself may use all the context leaves (answer_tokens). A text
longer than that is cut at the last paragraph end (a blank line) in the second half of a part,
else at the last line end, else at the last space, else where the part is full; each part keeps
its offset in the text, so a quote found in it is found in the text. The run reads at most
SUMMARY_MAX_PARTS of them.
"""

import math
import re
from dataclasses import dataclass

from mailrobbe.ai.model import CHARS_PER_TOKEN, SUMMARY_ANSWER_MAX_TOKENS, SUMMARY_ANSWER_TOKENS

MARGIN_TOKENS = 256  # the chat template around the messages, and a reserve for the estimate
MIN_PART_CHARS = 2000  # a context leaving less for a part is too small to summarise in parts

_PARAGRAPH = re.compile(r"\n[ \t\r\f\v]*\n")


@dataclass(frozen=True, slots=True)
class Part:
    number: int  # from 1
    start: int  # offset of its first character in the text
    text: str


def part_chars(context_tokens: int, fixed_chars: int) -> int:
    """Characters of text a request may carry beside fixed_chars of prompt, head and markers."""
    tokens = (
        context_tokens
        - SUMMARY_ANSWER_TOKENS
        - MARGIN_TOKENS
        - math.ceil(fixed_chars / CHARS_PER_TOKEN)
    )
    return max(0, math.floor(tokens * CHARS_PER_TOKEN))


def answer_tokens(context_tokens: int, prompt_chars: int) -> int:
    """max_tokens of a request carrying prompt_chars of system and user message: what the context
    leaves beside them, at least SUMMARY_ANSWER_TOKENS, at most SUMMARY_ANSWER_MAX_TOKENS."""
    left = context_tokens - MARGIN_TOKENS - math.ceil(prompt_chars / CHARS_PER_TOKEN)
    return min(max(left, SUMMARY_ANSWER_TOKENS), SUMMARY_ANSWER_MAX_TOKENS)


def cut(text: str, size: int) -> list[Part]:
    """The text in parts of at most size characters (module docstring), without the whitespace
    between them; one part for a text that fits, none for one without a word."""
    assert size > 0
    parts: list[Part] = []
    start = _next_word(text, 0)
    while start < len(text):
        end = len(text) if len(text) - start <= size else _end(text, start, start + size)
        piece = text[start:end].rstrip()
        parts.append(Part(len(parts) + 1, start, piece))
        start = _next_word(text, end)
    return parts


def _end(text: str, start: int, limit: int) -> int:
    """Where a part from start ends at the latest at limit (module docstring)."""
    half = start + (limit - start) // 2
    ends = [found.end() for found in _PARAGRAPH.finditer(text, half, limit)]
    if ends:
        return ends[-1]
    for mark in ("\n", " "):
        found = text.rfind(mark, half, limit)
        if found >= 0:
            return found + 1
    return limit


def _next_word(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position

"""Guards against bad answers of a vision model (D184), pure: what the answer's text becomes.

A model may think aloud (<think>...</think>, also left open when the length limit cut it), wrap
the text in a code fence although the prompt says not to, answer "[kein Text]" in its own way
(with a period, other case), or fall into a loop and write the same line again and again until
its limit. The cut at the length limit itself is the caller's (vision.read_page): it fails the
page, never a partial text.
"""

import re
from dataclasses import dataclass

from mailrobbe.ai.model import NO_TEXT_MARK

LOOP_LINES = 5  # the same non-empty line this often in a row is a loop

_THINK = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"\A```[\w-]*[ \t]*\n(.*?)\n?```\Z", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Cleaned:
    text: str  # "" for a page without writing
    looped: bool  # a repeated line was cut


def clean_answer(answer: str) -> Cleaned:
    """The page text of a model's answer: thinking and a surrounding code fence removed, the
    answer for no writing turned into "", a loop cut after the first line of its run."""
    text = _THINK.sub("", answer).strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    if is_no_text(text):
        return Cleaned("", False)
    text, looped = cut_loop(text)
    return Cleaned(text, looped)


def is_no_text(text: str) -> bool:
    """Whether the answer says the page has no writing: empty, or NO_TEXT_MARK in any case,
    with spaces or a trailing period."""
    plain = " ".join(text.split()).rstrip(".").strip()
    return not plain or plain.casefold() == NO_TEXT_MARK.casefold()


def cut_loop(text: str) -> tuple[str, bool]:
    """The text up to and including the first line of the first run of LOOP_LINES or more equal
    non-empty lines, and whether it was cut."""
    lines = text.split("\n")
    keys = [line.strip() for line in lines]
    start = 0
    for index in range(1, len(lines) + 1):
        if index < len(lines) and keys[index] and keys[index] == keys[start]:
            continue
        if index - start >= LOOP_LINES and keys[start]:
            return "\n".join(lines[: start + 1]).rstrip(), True
        start = index
    return text, False

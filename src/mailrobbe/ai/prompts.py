"""The prompts of ai.toml (D189), read once, with the version every result stores."""

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from mailrobbe.ai.model import NO_TEXT_MARK

AI_FILE = Path(__file__).parent.parent / "ai.toml"


class PromptsError(ValueError):
    """ai.toml cannot be used; the message says why."""


@dataclass(frozen=True, slots=True)
class Prompts:
    version: int  # ai_result.prompt_version
    ocr: str  # for the vision model, one page picture at a time


@cache
def load_prompts() -> Prompts:
    """The prompts of ai.toml; raises PromptsError when it lacks one or the OCR prompt does not
    name the answer for a page without writing (NO_TEXT_MARK)."""
    with AI_FILE.open("rb") as file:
        data = tomllib.load(file)
    version, ocr = data.get("version"), data.get("ocr")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise PromptsError("ai.toml: version must be a whole number from 1")
    if not isinstance(ocr, str) or not ocr.strip():
        raise PromptsError("ai.toml: the ocr prompt is missing")
    if NO_TEXT_MARK not in ocr:
        raise PromptsError(f"ai.toml: the ocr prompt must name the answer {NO_TEXT_MARK}")
    return Prompts(version=version, ocr=ocr.strip())

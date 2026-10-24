"""The prompts of ai.toml (D189, D306), read once, with the versions every result stores."""

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from mailrobbe.ai.model import NO_TEXT_MARK

AI_FILE = Path(__file__).parent.parent / "ai.toml"
# Where the material stands in a summary request (D306): ai.summarize writes the markers, the
# system prompt must name them.
MATERIAL_START = "<<<MATERIAL"
MATERIAL_END = "MATERIAL>>>"
# What the prompt of the alias check must hold (D322): the answer's keys and verdicts, the markers.
_ALIAS_NEEDS = (
    MATERIAL_START,
    MATERIAL_END,
    '"persons"',
    '"members"',
    '"sure"',
    '"reason"',
)
# What the prompt of the questions about persons must hold (D347).
_QUESTION_NEEDS = (MATERIAL_START, MATERIAL_END, '"answer"')
# What each summary prompt must hold; ai.summarize fills the placeholders with str.replace, never
# with str.format, so the JSON braces of the system prompt stay as written.
_SUMMARY_NEEDS = {
    "system": ("{themes}", "{tags}", MATERIAL_START, MATERIAL_END, '"summary"', '"tags"'),
    "part": ("{number}", "{total}"),
    "combine": ("{total}",),
    "short": (),
    "thread": (),
}


class PromptsError(ValueError):
    """ai.toml cannot be used; the message says why."""


@dataclass(frozen=True, slots=True)
class SummaryPrompts:
    version: int  # ai_result.prompt_version of a summary
    system: str  # with {themes} and {tags}
    part: str  # before one part of a long text, with {number} and {total}
    combine: str  # before the parts' summaries, with {total}
    short: str  # before a mail with little own text: tags and theme hints only
    thread: str  # before a thread, and after the combining instruction of a long one (D316)


@dataclass(frozen=True, slots=True)
class AliasPrompts:
    version: int  # alias_check.prompt_version (D323)
    system: str  # the material, what the model reads about two persons, follows as the user's


@dataclass(frozen=True, slots=True)
class QuestionPrompts:
    version: int  # person_question.prompt_version (D347)
    system: str  # the material and the question follow as the user's


@dataclass(frozen=True, slots=True)
class Prompts:
    version: int  # ai_result.prompt_version of an OCR result
    ocr: str  # for the vision model, one page picture at a time
    summarize: SummaryPrompts
    aliases: AliasPrompts
    questions: QuestionPrompts


@cache
def load_prompts() -> Prompts:
    """The prompts of ai.toml; raises PromptsError when it lacks one, the OCR prompt does not
    name the answer for a page without writing (NO_TEXT_MARK), a summary prompt lacks what
    _SUMMARY_NEEDS names, the prompt of the alias check what _ALIAS_NEEDS names or that of the
    questions what _QUESTION_NEEDS names."""
    with AI_FILE.open("rb") as file:
        data = tomllib.load(file)
    version, ocr = data.get("version"), data.get("ocr")
    if not _version(version):
        raise PromptsError("ai.toml: version must be a whole number from 1")
    assert isinstance(version, int)
    if not isinstance(ocr, str) or not ocr.strip():
        raise PromptsError("ai.toml: the ocr prompt is missing")
    if NO_TEXT_MARK not in ocr:
        raise PromptsError(f"ai.toml: the ocr prompt must name the answer {NO_TEXT_MARK}")
    return Prompts(
        version=version,
        ocr=ocr.strip(),
        summarize=_summarize(data.get("summarize")),
        aliases=_aliases(data.get("aliases")),
        questions=_questions(data.get("questions")),
    )


def _version(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _summarize(table: Any) -> SummaryPrompts:
    if not isinstance(table, dict):
        raise PromptsError("ai.toml: the table [summarize] is missing")
    if not _version(table.get("version")):
        raise PromptsError("ai.toml: summarize.version must be a whole number from 1")
    texts: dict[str, str] = {}
    for name, needs in _SUMMARY_NEEDS.items():
        prompt = table.get(name)
        if not isinstance(prompt, str) or not prompt.strip():
            raise PromptsError(f"ai.toml: the prompt summarize.{name} is missing")
        missing = [need for need in needs if need not in prompt]
        if missing:
            raise PromptsError(f"ai.toml: summarize.{name} must hold {', '.join(missing)}")
        texts[name] = prompt.strip()
    return SummaryPrompts(version=table["version"], **texts)


def _aliases(table: Any) -> AliasPrompts:
    if not isinstance(table, dict):
        raise PromptsError("ai.toml: the table [aliases] is missing")
    if not _version(table.get("version")):
        raise PromptsError("ai.toml: aliases.version must be a whole number from 1")
    prompt = table.get("system")
    if not isinstance(prompt, str) or not prompt.strip():
        raise PromptsError("ai.toml: the prompt aliases.system is missing")
    missing = [need for need in _ALIAS_NEEDS if need not in prompt]
    if missing:
        raise PromptsError(f"ai.toml: aliases.system must hold {', '.join(missing)}")
    return AliasPrompts(version=table["version"], system=prompt.strip())


def _questions(table: Any) -> QuestionPrompts:
    if not isinstance(table, dict):
        raise PromptsError("ai.toml: the table [questions] is missing")
    if not _version(table.get("version")):
        raise PromptsError("ai.toml: questions.version must be a whole number from 1")
    prompt = table.get("system")
    if not isinstance(prompt, str) or not prompt.strip():
        raise PromptsError("ai.toml: the prompt questions.system is missing")
    missing = [need for need in _QUESTION_NEEDS if need not in prompt]
    if missing:
        raise PromptsError(f"ai.toml: questions.system must hold {', '.join(missing)}")
    return QuestionPrompts(version=table["version"], system=prompt.strip())

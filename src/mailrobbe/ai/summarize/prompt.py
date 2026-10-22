# ruff: noqa: RUF001  (German typography and the defused markers are meant)
"""The requests of a summary (D305, D306): the system prompt filled with the run's vocabulary,
the material between its markers, and the user message.

The prompts are ai.toml's [summarize] (ai.prompts), the themes themes.toml's. The vocabulary is
read once per run (load_vocabulary), so the system prompt is the same in every request of a run
and a service may keep it cached. Placeholders are filled in one pass, never with str.format: the
system prompt holds the braces of a JSON example, and a tag's name may hold anything.

The material always stands between prompts.MATERIAL_START and MATERIAL_END, after the
instruction: head lines, a blank line, the text. A marker inside the material is defused (its
angle brackets made single guillemets, the length kept), so a document cannot end its material
and speak as the instruction.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.ai.model import VOCABULARY_TAGS, tag_key
from mailrobbe.ai.prompts import MATERIAL_END, MATERIAL_START, SummaryPrompts
from mailrobbe.themes import Theme, load_themes

NO_TAGS = "(noch keine)"  # {tags} without any tag

_TEAM_TAGS = text("SELECT name FROM tag ORDER BY lower(name), name")
# The AI tags of most valid summaries (D305).
_AI_TAGS = text("""
    SELECT t.label FROM ai_tag t
    JOIN ai_tag_link l ON l.tag_id = t.id
    JOIN ai_result r ON r.id = l.result_id AND r.state = 'valid'
    GROUP BY t.id, t.label
    ORDER BY count(*) DESC, t.id
    LIMIT :limit
""")
_PLACEHOLDER = re.compile(r"\{(themes|tags|number|total)\}")
_MARKER = re.compile(r"<<<\s*MATERIAL|MATERIAL\s*>>>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """What the system prompt offers: the themes, and the tags a model should take where one
    fits (the team's, then the most used AI tags)."""

    themes: tuple[Theme, ...]
    tags: tuple[str, ...]


async def load_vocabulary(session: AsyncSession) -> Vocabulary:
    """The themes, the team's tags by name, and the VOCABULARY_TAGS AI tags of most valid
    summaries that are not a team tag already (by tag_key)."""
    team = list((await session.execute(_TEAM_TAGS)).scalars())
    known = {tag_key(name) for name in team}
    found = (await session.execute(_AI_TAGS, {"limit": VOCABULARY_TAGS})).scalars()
    machine = [label for label in found if tag_key(label) not in known]
    return Vocabulary(load_themes(), (*team, *machine))


def fill(prompt: str, **values: str | int) -> str:
    """The prompt with its placeholders ({themes}, {tags}, {number}, {total}) filled in one
    pass; a placeholder without a value stays."""
    return _PLACEHOLDER.sub(lambda found: str(values.get(found[1], found[0])), prompt)


def system_prompt(prompts: SummaryPrompts, vocabulary: Vocabulary) -> str:
    """The system prompt of every request of a run."""
    themes = "\n".join(
        f"{theme.key}: {theme.name} – {theme.description}" for theme in vocabulary.themes
    )
    return fill(prompts.system, themes=themes, tags=", ".join(vocabulary.tags) or NO_TAGS)


def material(head: Sequence[str], body: str) -> str:
    """The head lines, a blank line and the text, with any marker inside defused."""
    lines = "\n".join(head)
    joined = f"{lines}\n\n{body}" if body.strip() else lines
    return _MARKER.sub(lambda found: found[0].replace("<", "‹").replace(">", "›"), joined)


def user_message(instruction: str, between: str) -> str:
    """The instruction (none for a text in one request) and the material between the markers."""
    framed = f"{MATERIAL_START}\n{between}\n{MATERIAL_END}"
    return f"{instruction.strip()}\n\n{framed}" if instruction.strip() else framed

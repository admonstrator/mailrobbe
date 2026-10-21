"""The research themes of themes.toml (D64): word fields and search templates.

themes.toml is the one source of the themes and their word fields; the research file creates a
tag and saved searches from each theme on request, the Akten screen shows the word fields, and
later milestones (entities, anomalies, topic discovery) read them here too. load_themes checks
the file: keys and names unique, colours from TagColor, every search understood by the search
syntax.
"""

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, cast, get_args
from urllib.parse import urlencode

from mailrobbe.api.query import QueryError, parse_query
from mailrobbe.api.schemas import TagColor
from mailrobbe.enums import EntityContext

THEMES_FILE = Path(__file__).with_name("themes.toml")


class ThemesError(ValueError):
    """themes.toml cannot be used; the message names the theme or search."""


@dataclass(frozen=True, slots=True)
class ThemeSearch:
    name: str
    q: str  # text of the search field

    @property
    def query(self) -> str:
        """The query string of the mail list for this search (SavedSearch.query)."""
        return urlencode({"q": self.q})


@dataclass(frozen=True, slots=True)
class Theme:
    key: str
    name: str  # also the name of its tag
    color: TagColor
    description: str
    terms: tuple[str, ...]  # the word field
    searches: tuple[ThemeSearch, ...]


@cache
def load_themes(path: Path = THEMES_FILE) -> tuple[Theme, ...]:
    """The themes in file order."""
    with path.open("rb") as file:
        data = tomllib.load(file)
    themes = tuple(_theme(entry) for entry in data.get("theme", []))
    for label, values in (
        ("theme key", [theme.key for theme in themes]),
        ("theme name", [theme.name.casefold() for theme in themes]),
        ("search name", [s.name.casefold() for theme in themes for s in theme.searches]),
    ):
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise ThemesError(f"{path.name}: {label} used twice: {', '.join(duplicates)}")
    return themes


def _theme(entry: dict[str, Any]) -> Theme:
    key = str(entry.get("key", "?"))
    try:
        color = str(entry["color"])
        if color not in get_args(TagColor):
            raise ThemesError(f"theme {key}: colour {color} is none of {get_args(TagColor)}")
        theme = Theme(
            key=str(entry["key"]),
            name=str(entry["name"]),
            color=cast(TagColor, color),
            description=str(entry.get("description", "")),
            terms=tuple(str(term) for term in entry.get("terms", [])),
            searches=tuple(
                ThemeSearch(name=str(search["name"]), q=str(search["q"]))
                for search in entry.get("search", [])
            ),
        )
    except (KeyError, TypeError) as error:
        raise ThemesError(f"theme {key}: missing or wrong field {error}") from None
    for search in theme.searches:
        try:
            parse_query(search.q)
        except QueryError as error:
            raise ThemesError(f"theme {key}, search {search.name}: {error}") from None
    return theme


# The lists of [entity_context] (D82), by the context they mark.
ENTITY_CONTEXT_LISTS = {
    "cash": EntityContext.CASH,
    "donation": EntityContext.DONATION,
    "receipt": EntityContext.RECEIPT,
}


@cache
def load_entity_context(path: Path = THEMES_FILE) -> dict[EntityContext, tuple[str, ...]]:
    """The words of [entity_context] that mark an amount, IBAN or account number (D82): each of
    the three lists present, with words that are non-empty and not used twice in one list."""
    with path.open("rb") as file:
        data = tomllib.load(file)
    table = data.get("entity_context")
    if not isinstance(table, dict):
        raise ThemesError(f"{path.name}: the table [entity_context] is missing")
    contexts: dict[EntityContext, tuple[str, ...]] = {}
    for name, context in ENTITY_CONTEXT_LISTS.items():
        words = table.get(name)
        if not isinstance(words, list) or not words:
            raise ThemesError(f"[entity_context]: the list {name} is missing or empty")
        if not all(isinstance(word, str) and word.strip() for word in words):
            raise ThemesError(f"[entity_context] {name}: every word must be a non-empty text")
        folded = [word.casefold() for word in words]
        duplicates = sorted({word for word in folded if folded.count(word) > 1})
        if duplicates:
            raise ThemesError(f"[entity_context] {name}: used twice: {', '.join(duplicates)}")
        contexts[context] = tuple(words)
    unknown = sorted(set(table) - set(ENTITY_CONTEXT_LISTS))
    if unknown:
        raise ThemesError(f"[entity_context]: unknown lists {', '.join(unknown)}")
    return contexts


@cache
def load_topic_ignore(path: Path = THEMES_FILE) -> tuple[str, ...]:
    """The words of [topics] ignore that the topics leave out (D141), in file order: non-empty
    texts, none used twice ignoring case. The topics phase compares their stems, so one form of
    a word leaves out all of its forms."""
    with path.open("rb") as file:
        data = tomllib.load(file)
    table = data.get("topics")
    if not isinstance(table, dict):
        raise ThemesError(f"{path.name}: the table [topics] is missing")
    words = table.get("ignore", [])
    if not isinstance(words, list) or not all(
        isinstance(word, str) and word.strip() for word in words
    ):
        raise ThemesError("[topics] ignore: every word must be a non-empty text")
    folded = [word.casefold() for word in words]
    duplicates = sorted({word for word in folded if folded.count(word) > 1})
    if duplicates:
        raise ThemesError(f"[topics] ignore: used twice: {', '.join(duplicates)}")
    unknown = sorted(set(table) - {"ignore"})
    if unknown:
        raise ThemesError(f"[topics]: unknown keys {', '.join(unknown)}")
    return tuple(words)

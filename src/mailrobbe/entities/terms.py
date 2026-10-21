"""Theme terms (D83) and the context words of amounts and accounts (D82), matched alike.

Both come from themes.toml: the word field of every theme (load_themes) and the lists of
[entity_context] (load_entity_context). A word matches as a whole word, any case, single words
also with a German inflection ending (-e, -en, -er, -es, -em, -n, -s, -ern); a phrase matches as
written in any case, its words separated by any whitespace; a word written in capitals (NSU, NPD,
HH) matches only as written; words that are numbers are left out, as in the theme searches.

One pass over the words of a text finds both: the term entities, and the places of context words
that context.py assigns to the amounts, IBANs and account numbers in their sentences.
"""

import re
from dataclasses import dataclass
from functools import cache

from mailrobbe.entities.occurrences import Occurrences
from mailrobbe.enums import EntityContext, EntityKind
from mailrobbe.themes import load_entity_context, load_themes

ENDINGS = ("e", "en", "er", "es", "em", "n", "s", "ern")
_WORD = re.compile(r"\w+")


@dataclass(frozen=True, slots=True)
class Term:
    """A word of a theme's word field as an entity."""

    key: str  # "<theme key>:<case-folded term>"
    label: str  # as written in themes.toml
    theme: str


Target = Term | EntityContext


@dataclass(frozen=True, slots=True)
class _Phrase:
    pattern: re.Pattern[str]  # matched at the start of its first word
    words: frozenset[str]  # its words, lowercased: a text without one of them has no match
    targets: tuple[Target, ...]


class WordMatcher:
    """Words and phrases, each with what it stands for, matched as the module docstring says."""

    def __init__(self, words: list[tuple[str, Target]]) -> None:
        single: dict[str, list[Target]] = {}
        exact: dict[str, list[Target]] = {}
        phrases: dict[str, dict[str, list[Target]]] = {}  # first word: phrase: targets
        for word, target in words:
            parts = _WORD.findall(word)
            if not parts or word.isdigit():
                continue
            if len(parts) > 1:
                phrases.setdefault(parts[0].lower(), {}).setdefault(word, []).append(target)
            elif word.isupper() and len(word) > 1:
                exact.setdefault(word, []).append(target)
            else:
                for form in _forms(word):
                    single.setdefault(form, []).append(target)
        self._single = {form: tuple(targets) for form, targets in single.items()}
        self._exact = {word: tuple(targets) for word, targets in exact.items()}
        self._phrases = {
            first: tuple(
                _Phrase(
                    _phrase_pattern(phrase),
                    frozenset(part.lower() for part in _WORD.findall(phrase)),
                    tuple(targets),
                )
                for phrase, targets in sorted(by_phrase.items(), key=lambda item: -len(item[0]))
            )
            for first, by_phrase in phrases.items()
        }

    def find(self, text: str) -> list[tuple[int, int, Target]]:
        """Every match in text order: start, end and what it stands for."""
        found: list[tuple[int, int, Target]] = []
        # First which words and phrases can match at all, from the set of the text's words: most
        # texts have none, and their words are not looked at one by one in Python.
        words = _WORD.findall(text)
        lowered = set(map(str.lower, words))
        single = lowered & self._single.keys()
        exact = self._exact.keys() & words
        phrases = {
            first: candidates
            for first in lowered & self._phrases.keys()
            if (
                candidates := [phrase for phrase in self._phrases[first] if phrase.words <= lowered]
            )
        }
        if not (single or exact or phrases):
            return found
        for match in _WORD.finditer(text):
            word = match.group()
            lower = word.lower()
            if lower in single:
                found.extend((match.start(), match.end(), target) for target in self._single[lower])
            if word in exact:
                found.extend((match.start(), match.end(), target) for target in self._exact[word])
            for phrase in phrases.get(lower, ()):
                hit = phrase.pattern.match(text, match.start())
                if hit:
                    found.extend((hit.start(), hit.end(), target) for target in phrase.targets)
                    break
        return found


def _forms(word: str) -> set[str]:
    """A single word and its inflected forms, lowercased (and case-folded, so that GROSS finds
    groß and the other way round)."""
    forms = {word.lower(), word.casefold()}
    return {form + ending for form in forms for ending in ("", *ENDINGS)}


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """The words of the phrase as written, any whitespace between them, punctuation kept."""
    pieces: list[str] = []
    position = 0
    for match in _WORD.finditer(phrase):
        gap = phrase[position : match.start()].strip()
        if pieces:
            pieces.append(rf"\s*{re.escape(gap)}\s*" if gap else r"\s+")
        pieces.append(re.escape(match.group()))
        position = match.end()
    flags = 0 if phrase.isupper() else re.IGNORECASE
    return re.compile("".join(pieces) + r"(?!\w)", flags)


@cache
def matcher() -> WordMatcher:
    """The terms of every theme and the context words, from themes.toml."""
    words: list[tuple[str, Target]] = []
    seen: set[str] = set()
    for theme in load_themes():
        for term in theme.terms:
            key = f"{theme.key}:{' '.join(term.casefold().split())}"
            if key not in seen:
                seen.add(key)
                words.append((term, Term(key, term, theme.key)))
    for context, context_words in load_entity_context().items():
        words += [(word, context) for word in context_words]
    return WordMatcher(words)


def find_terms(found: Occurrences) -> list[tuple[int, int, EntityContext]]:
    """Add the theme terms of the text outside the spans claimed so far (URLs, addresses), and
    return where its context words stand."""
    contexts: list[tuple[int, int, EntityContext]] = []
    for start, end, target in matcher().find(found.text):
        if not found.free(start, end):
            continue
        if isinstance(target, Term):
            found.add(
                EntityKind.TERM, target.key, target.label, start, end,
                detail=target.theme, claim=False,
            )  # fmt: skip
        else:
            contexts.append((start, end, target))
    return contexts

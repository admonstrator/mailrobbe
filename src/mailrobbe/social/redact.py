"""The one rule what a social media image blacks out (D215, D216).

A Redactor is built for one mail and one set of options and then applied to every text the card
shows: the subject, the participant lines, the body and the attachments' file names. It knows
three sources of what is personal:

    the mail's participants   every address of From, To, Cc and Bcc, the display name used with
                              it, the name and role the team gave it (D156), the words of those
                              names and the parts of the local parts, from MIN_WORD characters
                              on, so a signature and a salutation are covered too
    the entities of the text  the kinds of the chosen categories (model.KINDS), every occurrence
                              as entities.extract_entities finds them (D80, D81)
    the team's own terms      what was typed into the dialog

Every occurrence is replaced by BLOCK characters in the text itself, before anything is drawn:
the picture never holds a redacted name, not under a bar and not in a stray pixel, and a test
can read the text the renderer is given. The number of blocks follows the length of what they
cover, so the bars look like the text they replace, but never beyond MAX_BLOCKS.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from mailrobbe.entities.extract import extract_entities
from mailrobbe.enums import EntityKind, ParticipationRole
from mailrobbe.export.records import ExportMail
from mailrobbe.social.model import (
    KINDS,
    MIN_TERM,
    CardOptions,
    Redaction,
    RedactionKind,
)

BLOCK = "\N{FULL BLOCK}"
BLOCK_RATIO = 0.55  # blocks per character covered: a block is wider than an average letter
MIN_BLOCKS = 2
MAX_BLOCKS = 14
MIN_WORD = 4  # characters of a word of a name or of a local part's part that is a term of its own
# Which category a place belongs to when two of them cover it: the first of RedactionKind.
ORDER = {kind: rank for rank, kind in enumerate(RedactionKind)}
_PARTS = re.compile(r"[^\W_]{2,}", re.UNICODE)  # words of a name, parts of a local part


@dataclass(frozen=True, slots=True)
class Redacted:
    """One text with every place blacked out, and what that covered."""

    text: str
    redaction: Redaction


class Redactor:
    """What one image blacks out; apply() holds for every text of the same card."""

    def __init__(self, terms: Iterable[str], kinds: Iterable[EntityKind], own: Iterable[str]):
        self._terms = {
            RedactionKind.PARTICIPANT: _pattern(terms),
            RedactionKind.TERM: _pattern(own),
        }
        chosen = set(kinds)
        self._kinds = {
            kind: category
            for category, kinds_of in KINDS.items()
            for kind in kinds_of
            if kind in chosen
        }

    def apply(self, text: str) -> Redacted:
        """text with every occurrence replaced by blocks, and the places counted per category."""
        if not text:
            return Redacted("", Redaction())
        # Overlapping places become one bar with the first category of ORDER: a sender's address
        # is found as a participant and as an e-mail address of the text, and counts as the
        # participant it is.
        spans = sorted(
            (span for span in self._spans(text) if span[1] > span[0]),
            key=lambda span: (span[0], ORDER[span[2]], -span[1]),
        )
        kept: list[tuple[int, int, RedactionKind]] = []
        for start, end, kind in spans:
            if kept and start < kept[-1][1]:
                last = kept[-1]
                kept[-1] = (last[0], max(last[1], end), last[2])
            else:
                kept.append((start, end, kind))
        counts: dict[RedactionKind, int] = {}
        pieces: list[str] = []
        at = 0
        for start, end, kind in kept:
            pieces.append(text[at:start])
            pieces.append(_blocks(end - start))
            counts[kind] = counts.get(kind, 0) + 1
            at = end
        pieces.append(text[at:])
        return Redacted("".join(pieces), Redaction(counts))

    def _spans(self, text: str) -> Iterator[tuple[int, int, RedactionKind]]:
        for kind, pattern in self._terms.items():
            if pattern is not None:
                for found in pattern.finditer(text):
                    yield found.start(), found.end(), kind
        if not self._kinds:
            return
        # A domain is recorded where its URL or address starts, without a range of its own
        # (entities.contact.add_domains); apply() drops those empty spans.
        for entity in extract_entities(text):
            category = self._kinds.get(entity.kind)
            if category is not None:
                for start, end in entity.spans:
                    yield start, end, category


def redactor(mail: ExportMail, options: CardOptions) -> Redactor:
    """The Redactor of one image (D215): the participants when they are blacked out, the entity
    kinds of the chosen categories, and the team's own terms."""
    return Redactor(
        participant_terms(mail) if options.participants else (),
        options.kinds(),
        [term.strip() for term in options.terms],
    )


def participant_terms(mail: ExportMail) -> list[str]:
    """Everything that names a participant of this mail: its addresses, the display names and
    labels used with them, and the words of those, longest first."""
    terms: set[str] = set()
    for role in ParticipationRole:
        for person in mail.participants.get(role, []):
            terms.add(person.email)
            terms.update(_words(person.email.partition("@")[0]))
            if person.name:
                terms.add(person.name)
                terms.update(_words(person.name))
            label = mail.labels.get(person.person_id)
            if label is None:
                continue
            for value in (label.name, label.role):
                if value:
                    terms.add(value)
                    terms.update(_words(value))
    return sorted(terms, key=lambda term: (-len(term), term))


def _words(value: str) -> list[str]:
    """The words of a name or the parts of a local part that are terms of their own: a name is
    written in other forms than the header's ("Hallo Jürgen", "Weiß, Jürgen"), and a local part
    holds the name as a rule (j.weiss@, juergen.weiss@)."""
    return [part for part in _PARTS.findall(value) if len(part) >= MIN_WORD]


def _pattern(terms: Iterable[str]) -> re.Pattern[str] | None:
    """One pattern for these terms, longest first, so the longest match wins; None for none.
    Terms below MIN_TERM characters are left out: they would black out half a text."""
    usable = sorted(
        {term.strip() for term in terms if len(term.strip()) >= MIN_TERM},
        key=lambda term: (-len(term), term),
    )
    if not usable:
        return None
    return re.compile("|".join(re.escape(term) for term in usable), re.IGNORECASE)


def _blocks(length: int) -> str:
    return BLOCK * max(MIN_BLOCKS, min(MAX_BLOCKS, round(length * BLOCK_RATIO)))

"""The labels of the terms (D141, step topic_labels): the spelling written most often.

Stems lose umlauts and endings ("ruckmeld"), so a term is shown as the spelling of its lexeme
that the mails use most ("Rückmeldung"), which is also the word the mail list searches for. The
pass reads the subject and text of every mail that is no duplicate once, in id order and in
batches of a server-side cursor, removes e-mail addresses and links, and counts every word of
MIN_LENGTH to MAX_LENGTH letters as written. Whenever PENDING_SPELLINGS spellings wait, and at the
end, their lowercase forms not stemmed yet are stemmed with ts_lexize('german_stem'), the
dictionary mail.tsv takes words through, STEM_BATCH per statement; the counts of spellings whose
stem is a term are kept, the others are dropped and stemmed again should they come back. The
memory held is thus the spellings of the vocabulary's terms and at most PENDING_SPELLINGS (plus
one batch) more, never every word of the archive.

A term's label is its spelling written most often; of spellings written equally often, the first
in Python string order, which puts capitals first: "Spenden" before "spenden", as German writes
the nouns that most topics are. A term without any spelling (its words only ever written inside
an address or next to digits) keeps its lexeme.
"""

import asyncio
import re
from collections import Counter
from collections.abc import Collection, Iterable
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.topics.model import MAX_LENGTH, MIN_LENGTH

BATCH_MAILS = 1_000  # mails per batch of the cursor; the step advances per batch
PENDING_SPELLINGS = 200_000  # spellings counted before they are stemmed
STEM_BATCH = 20_000  # lowercase forms per ts_lexize statement

# A whole token (between white space) holding an @, :// or www.: an address, also behind
# "mailto:" or in brackets, or a link. Only a token's start can begin a match, so the scan stays
# linear in the text however long a token is.
_ADDRESSES = re.compile(r"(?<!\S)\S*?(?:@|://|www\.)\S*", re.IGNORECASE)
# Letters only, not touching other letters or digits, as the parser of mail.tsv sees a word:
# hyphens and underscores separate ("Spenden-Quittung", "Bewerbung_Schäfer.pdf"), and a word with
# digits is a number to it ("abc123").
_WORD = re.compile(rf"(?<![^\W_])[^\W\d_]{{{MIN_LENGTH},{MAX_LENGTH}}}(?![^\W_])")

_TEXTS = text("SELECT subject, body_text FROM mail WHERE is_duplicate_of IS NULL ORDER BY id")
_STEMS = text("""
    SELECT w, (ts_lexize('german_stem', w))[1] FROM unnest(CAST(:words AS text[])) AS w
""")


class Progress(Protocol):
    """What the pass counts the mails read into: the import's step (jobrun.Step, unit mails)."""

    def advance(self, count: int = 1) -> None: ...


def words(text: str) -> list[str]:
    """The words of a text as written, without those of addresses and links."""
    return _WORD.findall(_ADDRESSES.sub(" ", text))


class Spellings:
    """The spellings of a vocabulary's terms as written, counted over texts (module docstring)."""

    def __init__(self, terms: Collection[str]) -> None:
        self._terms = terms
        self._pending: Counter[str] = Counter()  # counted since the last stem()
        self._lexemes: dict[str, str] = {}  # lowercase form -> its term
        self._counts: Counter[str] = Counter()  # spellings of terms

    @property
    def pending(self) -> int:
        return len(self._pending)

    @property
    def spellings(self) -> int:
        """Spellings of terms counted so far (stemmed)."""
        return len(self._counts)

    def add(self, text: str) -> None:
        self._pending.update(words(text))

    def add_mails(self, rows: Iterable[tuple[str | None, str | None]]) -> None:
        """The subject and text of each mail."""
        for subject, body_text in rows:
            if subject:
                self.add(subject)
            if body_text:
                self.add(body_text)

    async def stem(self, session: AsyncSession) -> None:
        """Stem the pending spellings and keep those of terms."""
        new = list({spelling.lower() for spelling in self._pending} - self._lexemes.keys())
        for start in range(0, len(new), STEM_BATCH):
            rows = await session.execute(_STEMS, {"words": new[start : start + STEM_BATCH]})
            for word, lexeme in rows:
                if lexeme in self._terms:
                    self._lexemes[word] = lexeme
        for spelling, count in self._pending.items():
            if spelling.lower() in self._lexemes:
                self._counts[spelling] += count
        self._pending.clear()

    def labels(self) -> dict[str, str]:
        """Each term with a spelling -> its label; call after stem()."""
        best: dict[str, tuple[int, str]] = {}
        for spelling, count in self._counts.items():
            lexeme = self._lexemes[spelling.lower()]
            held = best.get(lexeme)
            if held is None or count > held[0] or (count == held[0] and spelling < held[1]):
                best[lexeme] = (count, spelling)
        return {lexeme: spelling for lexeme, (_, spelling) in best.items()}


async def read_labels(
    session: AsyncSession, terms: Collection[str], stop: asyncio.Event, step: Progress
) -> tuple[dict[str, str], int] | None:
    """The labels of terms (lexemes) found in the texts of every mail that is no duplicate, and
    the number of spellings counted for them; None when stop was set between two batches."""
    spellings = Spellings(terms)
    result = await session.stream(_TEXTS)
    # The size is given here: the yield_per option of a text() statement does not reach the
    # partitions of a session's stream, which would then be every row at once.
    async for batch in result.partitions(BATCH_MAILS):
        # The words of a batch take a moment of CPU: the run keeps reporting meanwhile.
        await asyncio.to_thread(spellings.add_mails, [(row[0], row[1]) for row in batch])
        step.advance(len(batch))
        if stop.is_set():
            await result.close()
            return None
        if spellings.pending >= PENDING_SPELLINGS:
            await spellings.stem(session)
    await spellings.stem(session)
    return spellings.labels(), spellings.spellings

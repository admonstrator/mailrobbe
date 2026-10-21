"""The occurrences found in one text while the finders run, and the spans they claim (D81).

Every finder of extract adds what it finds here. A finder that claims a span keeps the finders
after it out of that span: one span of text gives one entity of the most specific kind (an IBAN
is not also an account or a phone, a URL's digits are no phone, an amount's number is no date).
Occurrences of one kind and key become one Found: its label and position those of the first
occurrence in the text, its context the union of its occurrences' contexts.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from mailrobbe.entities.model import ENTITIES_PER_TEXT, KEY_LIMIT, NO_CONTEXT, Found
from mailrobbe.enums import EntityContext, EntityKind

# Kinds whose occurrences carry contexts (D82).
CONTEXT_KINDS = frozenset({EntityKind.AMOUNT, EntityKind.IBAN, EntityKind.ACCOUNT})
_KIND_ORDER = {kind: index for index, kind in enumerate(EntityKind)}
_ONES = b"\x01" * 4096


@dataclass(slots=True)
class _Entry:
    kind: EntityKind
    key: str
    label: str
    position: int
    value: Decimal | None
    currency: str | None
    detail: str | None
    occurrences: int = 1
    context: EntityContext = NO_CONTEXT
    spans: list[tuple[int, int]] = field(default_factory=list)  # CONTEXT_KINDS only


class Occurrences:
    """What the finders found in `text` so far."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._claimed = bytearray(len(text))
        self._entries: dict[tuple[EntityKind, str], _Entry] = {}
        # Position and host of every URL and e-mail address, for their domains.
        self.hosts: list[tuple[int, str]] = []

    def free(self, start: int, end: int) -> bool:
        """No finder before claimed any character of text[start:end]."""
        return self._claimed.find(1, start, end) < 0

    def claim(self, start: int, end: int) -> None:
        while start < end:
            step = min(end - start, len(_ONES))
            self._claimed[start : start + step] = _ONES[:step]
            start += step

    def add(
        self,
        kind: EntityKind,
        key: str,
        label: str,
        start: int,
        end: int,
        *,
        value: Decimal | None = None,
        currency: str | None = None,
        detail: str | None = None,
        claim: bool = True,
    ) -> None:
        """One occurrence at text[start:end]; with claim, the span is no other entity's. A key or
        label above KEY_LIMIT is no entity (its span is still claimed)."""
        if claim:
            self.claim(start, end)
        if len(key) > KEY_LIMIT or len(label) > KEY_LIMIT:
            return
        entry = self._entries.get((kind, key))
        if entry is None:
            entry = _Entry(kind, key, label, start, value, currency, detail)
            self._entries[kind, key] = entry
        else:
            entry.occurrences += 1
            if start < entry.position:  # finders of one kind may not run in text order
                entry.position, entry.label = start, label
        if kind in CONTEXT_KINDS:
            entry.spans.append((start, end))

    def contextual(self) -> list[_Entry]:
        """The entries whose occurrences carry contexts (context.mark sets them)."""
        return [entry for entry in self._entries.values() if entry.kind in CONTEXT_KINDS]

    def found(self) -> list[Found]:
        """One Found per kind and key, by first position, at most ENTITIES_PER_TEXT."""
        entries = sorted(
            self._entries.values(),
            key=lambda entry: (entry.position, _KIND_ORDER[entry.kind], entry.key),
        )
        return [
            Found(
                kind=entry.kind,
                key=entry.key,
                label=entry.label,
                position=entry.position,
                occurrences=entry.occurrences,
                context=entry.context,
                value=entry.value,
                currency=entry.currency,
                detail=entry.detail,
            )
            for entry in entries[:ENTITIES_PER_TEXT]
        ]

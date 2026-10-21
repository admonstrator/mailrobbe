"""What the extraction gives, and which text of a mail it reads (D80, D81).

extract.extract_entities(text) returns one Found per kind and key, in the order of their first
occurrence. Positions are character offsets into the text it was given: for a mail the text of
scanned_text, for a document its extracted_text, so that the API can show a snippet around a
mention from the same columns.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from functools import cache

from mailrobbe.db.models import ENTITY_VERSION
from mailrobbe.enums import EntityContext, EntityKind
from mailrobbe.themes import load_themes

KEY_LIMIT = 200  # characters of entity.key and entity.label; longer values are not entities
ENTITIES_PER_TEXT = 2_000  # entities kept per text, the first ones by position
CURRENCIES = ("EUR", "USD", "CHF", "GBP", "DEM")  # entity.currency of amounts (D81)
NO_CONTEXT = EntityContext(0)


@dataclass(frozen=True, slots=True)
class Found:
    """An entity in one text: its identity, how often and where first, and in which contexts."""

    kind: EntityKind
    key: str  # normalised (D81); unique within the kind
    label: str  # display form
    position: int  # offset of the first occurrence in the text
    occurrences: int  # at least 1
    context: EntityContext = NO_CONTEXT  # union over the occurrences (D82)
    value: Decimal | None = None  # amount: the sum, two decimals
    currency: str | None = None  # amount: one of CURRENCIES
    detail: str | None = None  # see db.models.Entity.detail


@cache
def scan_version() -> int:
    """The version a scan records (mail_entity_scan.version, D84): ENTITY_VERSION together with
    everything the extraction reads besides the text (the word lists of themes.toml and the
    gazetteers in data/), as a positive 31-bit number. A text scanned by another version is
    scanned again at the next import."""
    digest = hashlib.sha256(str(ENTITY_VERSION).encode())
    for theme in load_themes():
        digest.update("\n".join((theme.key, *theme.terms)).encode())
    return int.from_bytes(digest.digest()[:4], "big") & 0x7FFFFFFF


def scanned_text(subject: str | None, body_text: str | None) -> str:
    """The text of a mail the extraction reads: the subject, a line break, the stored text."""
    return f"{subject or ''}\n{body_text or ''}"

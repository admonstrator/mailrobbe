"""What a social media image is asked for and what its redaction covered (D214, D215).

The contract between api/social.py, redact.py and render.py: an image is one mail plus
CardOptions, and every answer says what was blacked out (Redaction), so the dialog can show it
before anyone publishes the picture.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from mailrobbe.enums import EntityKind

TERM_LIMIT = 200  # characters of one term of the team's own
TERMS_LIMIT = 20  # terms of the team's own per image
MIN_TERM = 3  # a shorter term blacks out too much of a text to be meant


class CardShape(StrEnum):
    """The formats the export offers (D214); a longer text is cut, never the picture."""

    SQUARE = "square"  # 1080 x 1080
    WIDE = "wide"  # 1200 x 675, a link card
    PORTRAIT = "portrait"  # 1080 x 1350, the tallest post


SHAPES: dict[CardShape, tuple[int, int]] = {
    CardShape.SQUARE: (1080, 1080),
    CardShape.WIDE: (1200, 675),
    CardShape.PORTRAIT: (1080, 1350),
}


class RedactionKind(StrEnum):
    """Why a place in the picture is blacked out (D215), in the order the dialog lists them."""

    PARTICIPANT = "participant"  # an address or name of From, To, Cc or Bcc, or its label (D156)
    CONTACT = "contact"  # an address, phone number, IBAN or account number in the text
    NAME = "name"  # a person's name in the text
    ORGANIZATION = "organization"  # an organisation, a place, a URL or a domain in the text
    TERM = "term"  # a term the team typed in


# The entity kinds of each category (D215); PARTICIPANT comes from the mail's participants.
KINDS: dict[RedactionKind, frozenset[EntityKind]] = {
    RedactionKind.CONTACT: frozenset(
        {EntityKind.EMAIL, EntityKind.PHONE, EntityKind.IBAN, EntityKind.ACCOUNT}
    ),
    RedactionKind.NAME: frozenset({EntityKind.PERSON}),
    RedactionKind.ORGANIZATION: frozenset(
        {EntityKind.ORGANIZATION, EntityKind.PLACE, EntityKind.URL, EntityKind.DOMAIN}
    ),
}


@dataclass(frozen=True, slots=True)
class CardOptions:
    """What the image shows and what it blacks out; the defaults of D215."""

    shape: CardShape = CardShape.PORTRAIT
    participants: bool = True  # black out From, To, Cc and Bcc with their names and labels
    contacts: bool = True  # addresses, phone numbers, IBANs and account numbers in the text
    names: bool = True  # persons' names in the text
    organizations: bool = False  # organisations, places, URLs and domains in the text
    terms: Sequence[str] = ()  # the team's own terms, at most TERMS_LIMIT
    quotes: bool = False  # show the quoted text too, grey as a mail client shows it
    dkim: bool = True  # the DKIM seal beside the date
    checksum: bool = True  # the first digits of the mail's SHA-256 in the footer (D61)

    def kinds(self) -> frozenset[EntityKind]:
        """The entity kinds this redaction covers."""
        chosen = {
            RedactionKind.CONTACT: self.contacts,
            RedactionKind.NAME: self.names,
            RedactionKind.ORGANIZATION: self.organizations,
        }
        return frozenset().union(*(KINDS[kind] for kind, on in chosen.items() if on))


@dataclass(frozen=True, slots=True)
class Redaction:
    """What a redaction blacked out: how many places per category, in every text of the card."""

    counts: dict[RedactionKind, int] = field(default_factory=dict)

    @property
    def places(self) -> int:
        return sum(self.counts.values())

    def __add__(self, other: "Redaction") -> "Redaction":
        counts = dict(self.counts)
        for kind, count in other.counts.items():
            counts[kind] = counts.get(kind, 0) + count
        return Redaction(counts)

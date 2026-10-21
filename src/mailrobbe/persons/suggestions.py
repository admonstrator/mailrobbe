"""Alias suggestions (D30): pairs of root persons that may be the same person.

Two roots are suggested when they share a key: a display name used with one of their addresses
(person_email.display_names, normalize_name) or the local part of one of their addresses
(normalize_local_part). A key that more than MAX_GROUP roots share is too generic and suggests
nothing. A pair records the smallest name and local part it shares. Dismissed pairs are never
suggested; alias_dismissal is read through the roots of its persons, so a dismissal still holds
after either person was merged into another. Addresses of one root are never a pair.

The keys are grouped here rather than in SQL, so the rules exist once: there are a few thousand
persons, not millions. A refresh for some persons computes every pair as well, since a merge
changes the groups of its keys and with them pairs between other persons (a name of six roots
suggests nothing, after a merge of two of them it suggests the other four as pairs); only rows
that change are written.
"""

import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence, Set
from itertools import combinations
from typing import Any

from sqlalchemy import text

from mailrobbe.persons.roots import Executor, lock_persons
from mailrobbe.persons.sync import sync_rows

MAX_GROUP = 5  # roots sharing a key; more and it suggests nothing
# Shared mailboxes and automated senders, also those of the test data generator.
ROLE_LOCAL_PARTS = frozenset(
    {
        "admin", "benachrichtigung", "bewerbung", "billing", "buchhaltung", "contact",
        "do-not-reply", "donotreply", "einkauf", "empfang", "hallo", "hello", "info", "jobs",
        "kontakt", "kundenservice", "listmaster", "mail", "mailer-daemon", "mailing", "mailman",
        "news", "newsletter", "no-reply", "noreply", "notification", "notifications", "office",
        "personal", "post", "postmaster", "presse", "rechnung", "sales", "service", "support",
        "system", "team", "vertrieb", "webmaster",
    }
)  # fmt: skip
_QUOTES = re.compile("[\"'`´‘’‚“”„«»‹›]")  # noqa: RUF001  (they are meant)

_KEYS = text("""
    SELECT coalesce(p.merged_into, p.id), e.email, ARRAY(SELECT jsonb_object_keys(e.display_names))
    FROM person p JOIN person_email e ON e.person_id = p.id
""")
_DISMISSED = text("""
    SELECT coalesce(a.merged_into, a.id), coalesce(b.merged_into, b.id)
    FROM alias_dismissal d JOIN person a ON a.id = d.person_a JOIN person b ON b.id = d.person_b
""")
_FRESH = """
    SELECT * FROM unnest(
        CAST(:person_a AS bigint[]), CAST(:person_b AS bigint[]),
        CAST(:same_name AS text[]), CAST(:same_local_part AS text[])
    ) AS f (person_a, person_b, same_name, same_local_part)
"""


def normalize_name(name: str) -> str | None:
    """A display name as suggestions compare it; None when it is no name of a person.

    Lowercased, quotes removed, "Nachname, Vorname" (exactly one comma) turned around, runs of
    whitespace made one space; it must keep at least two words and contain no @.
    """
    plain = _QUOTES.sub("", name).lower()
    if "@" in plain:
        return None
    if plain.count(",") == 1:
        last, first = plain.split(",")
        plain = f"{first} {last}"
    words = plain.split()
    return " ".join(words) if len(words) >= 2 else None


def normalize_local_part(local_part: str) -> str | None:
    """The local part of an address as suggestions compare it; None for role addresses.

    Lowercased and without a +suffix; info@, noreply@ and the other ROLE_LOCAL_PARTS give None.
    """
    base = local_part.lower().partition("+")[0]
    return base if base and base not in ROLE_LOCAL_PARTS else None


async def refresh_alias_suggestions(db: Executor, persons: Collection[int] | None = None) -> None:
    """Recompute alias_suggestion as a whole, or after a change of these persons.

    persons is read as in refresh_person_stats; every pair is computed either way (see the
    module docstring), so the result is that of a full refresh. Dismissed pairs
    (alias_dismissal) and persons of one root are never suggested.
    """
    if persons is not None and not persons:
        return
    await lock_persons(db)
    addresses = await db.execute(_KEYS)
    dismissed = {(min(a, b), max(a, b)) for a, b in await db.execute(_DISMISSED)}
    pairs = _pairs(addresses, dismissed)
    columns: dict[str, list[Any]] = {
        "person_a": [a for a, _ in pairs],
        "person_b": [b for _, b in pairs],
        "same_name": [name for name, _ in pairs.values()],
        "same_local_part": [local_part for _, local_part in pairs.values()],
    }
    keys, values = ("person_a", "person_b"), ("same_name", "same_local_part")
    await sync_rows(db, "alias_suggestion", keys, values, _FRESH, columns)


def _pairs(
    addresses: Iterable[tuple[int, str, Sequence[str]]], dismissed: Set[tuple[int, int]]
) -> dict[tuple[int, int], list[str | None]]:
    """The smallest name and local part each pair of roots shares (None: none), by address."""
    names: defaultdict[str, set[int]] = defaultdict(set)
    local_parts: defaultdict[str, set[int]] = defaultdict(set)
    for root, email, used in addresses:
        local_part = normalize_local_part(email.rpartition("@")[0])
        if local_part is not None:
            local_parts[local_part].add(root)
        for name in filter(None, map(normalize_name, used)):
            names[name].add(root)
    pairs: dict[tuple[int, int], list[str | None]] = {}
    for reason, groups in enumerate((names, local_parts)):
        for key, roots in groups.items():
            if not 2 <= len(roots) <= MAX_GROUP:
                continue
            for pair in combinations(sorted(roots), 2):
                if pair not in dismissed:
                    shared = pairs.setdefault(pair, [None, None])
                    smallest = shared[reason]
                    if smallest is None or key < smallest:
                        shared[reason] = key
    return pairs

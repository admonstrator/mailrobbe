"""The pairs the alias check asks about (D321): pure but for read_candidates.

Pairs of root persons that are humans, from two sources:

    suggested  every open alias suggestion of tier uncertain (persons.suggestions); the certain
               ones need no second opinion
    loose      pairs that share a loose key and no suggestion: the surname (the last word of an
               address's main name, folded) with the first letter of the first name, so "Hans
               Müller", "Hans-Peter Mueller" and "Heinz Müller" share "mueller h". A key of more
               than LOOSE_GROUP roots is a common name and gives nothing, as MAX_GROUP does for
               the suggestions

Pairs with a check (alias_check) or a dismissal (alias_dismissal) are left out, both read through
the roots of their persons. Order: suggestions with name and local part, other suggestions, loose
pairs; within each, the pair whose busier person has more mails first, then by ids.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from itertools import combinations

from sqlalchemy import text

from mailrobbe.enums import AliasTier
from mailrobbe.persons.roots import Executor
from mailrobbe.persons.suggestions import address_keys, fold

LOOSE_GROUP = 4  # roots sharing a loose key; more and it gives no pair

_WORDS = re.compile(r"[a-z]+")
# Every address of a human root with its display names.
_ADDRESSES = text("""
    SELECT r.id, e.email, e.display_names
    FROM person_email e JOIN person p ON p.id = e.person_id
    JOIN person r ON r.id = coalesce(p.merged_into, p.id)
    WHERE r.kind IS NULL
""")
_SUGGESTIONS = text("""
    SELECT person_a, person_b, tier::text AS tier,
        same_name IS NOT NULL AND same_local_part IS NOT NULL AS both
    FROM alias_suggestion
""")
# Pairs not to ask about, through the roots of their persons.
_LEFT_OUT = text("""
    SELECT least(coalesce(a.merged_into, a.id), coalesce(b.merged_into, b.id)),
        greatest(coalesce(a.merged_into, a.id), coalesce(b.merged_into, b.id))
    FROM (SELECT person_a, person_b FROM alias_check
          UNION SELECT person_a, person_b FROM alias_dismissal) d
    JOIN person a ON a.id = d.person_a JOIN person b ON b.id = d.person_b
""")
_MAILS = text("""
    SELECT person_id, mails FROM person_stats WHERE person_id = ANY(CAST(:ids AS bigint[]))
""")


@dataclass(frozen=True, slots=True)
class Candidate:
    """A pair to ask about: roots a < b."""

    a: int
    b: int
    suggested: bool  # an open suggestion; else a loose pair
    both: bool = False  # suggested by name and local part
    mails: int = 0  # of the busier person


def loose_key(name: str) -> str | None:
    """The loose key of a main name: folded surname and first initial; None for one word."""
    words = _WORDS.findall(fold(name))
    return f"{words[-1]} {words[0][0]}" if len(words) >= 2 else None


def loose_pairs(addresses: Iterable[tuple[int, str, Mapping[str, int]]]) -> set[tuple[int, int]]:
    """The pairs of roots sharing a loose key of LOOSE_GROUP roots at most, from the addresses
    (root, address, display names); role addresses and shared mailboxes have no main name."""
    groups: defaultdict[str, set[int]] = defaultdict(set)
    for root, email, used in addresses:
        keys = address_keys(email, tuple(used.items()))
        name = keys[1] if keys is not None else None
        key = loose_key(name) if name is not None else None
        if key is not None:
            groups[key].add(root)
    return {
        pair
        for roots in groups.values()
        if 2 <= len(roots) <= LOOSE_GROUP
        for pair in combinations(sorted(roots), 2)
    }


def order(
    suggestions: Iterable[tuple[int, int, AliasTier, bool]],
    loose: Set[tuple[int, int]],
    left_out: Set[tuple[int, int]],
    mails: Mapping[int, int],
) -> list[Candidate]:
    """The candidates in the order they are asked about (module docstring), from the suggestions
    (a, b, tier, both), the loose pairs, the pairs left out and the mails per root."""
    suggested = {(a, b) for a, b, *_ in suggestions}
    found = [
        Candidate(a, b, True, both)
        for a, b, tier, both in suggestions
        if tier is AliasTier.UNCERTAIN and (a, b) not in left_out
    ]
    found += [Candidate(a, b, False) for a, b in loose - suggested - left_out]
    ranked = [
        Candidate(c.a, c.b, c.suggested, c.both, max(mails.get(c.a, 0), mails.get(c.b, 0)))
        for c in found
    ]
    return sorted(ranked, key=lambda c: (not c.suggested, not c.both, -c.mails, c.a, c.b))


async def read_candidates(db: Executor) -> list[Candidate]:
    """Every pair to ask about now, in order; about as long as a refresh of the suggestions
    takes to find its keys."""
    addresses = (await db.execute(_ADDRESSES)).all()
    suggestions = [
        (row.person_a, row.person_b, AliasTier(row.tier), row.both)
        for row in await db.execute(_SUGGESTIONS)
    ]
    left_out = {(a, b) for a, b in await db.execute(_LEFT_OUT)}
    loose = loose_pairs((root, email, used) for root, email, used in addresses)
    roots = {root for pair in loose for root in pair} | {
        root for a, b, *_ in suggestions for root in (a, b)
    }
    found = await db.execute(_MAILS, {"ids": sorted(roots)})
    mails = {row.person_id: row.mails for row in found}
    return order(suggestions, loose, left_out, mails)

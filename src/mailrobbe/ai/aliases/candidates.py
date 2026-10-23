"""The groups of persons the alias check asks about (D321, D324): pure but for read_groups.

Pairs of root persons that are humans come from two sources:

    suggested  every open alias suggestion of tier uncertain (persons.suggestions); the certain
               ones need no second opinion
    loose      roots whose addresses share a loose key: the surname (the last word of an
               address's main name, persons.suggestions.normalize_name: titles dropped,
               "Nachname, Vorname" turned around, folded; for an address without one its most
               used display name, initials allowed) with the first letter of the first name,
               so "Dr. Thomas Hermann", "Thomas Hermann", "T. Hermann" and "Hermann, Thomas"
               share "hermann t". Within a key only first names that fit join (fitting:
               "Thomas" and "T.", "Hans" and "Hans-Peter", not "Matthias" and "Miriam"), the
               cheap sorting before any request (D324). A key of more than GROUP_MAX roots is a
               common name and gives nothing

Pairs with a check of the current prompt or a verdict same (alias_check) or a dismissal
(alias_dismissal) are left out, all read through the roots of their persons. The open pairs are
joined into groups: the persons they connect, asked about in one request, when they are at most
GROUP_MAX; a larger cluster is asked about by its loose keys and its remaining pairs. Order:
groups holding a suggestion with name and local part, other suggestions, loose groups; within
each, the group whose busiest person has more mails first, then by ids.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from itertools import combinations

from sqlalchemy import text

from mailrobbe.enums import AliasTier
from mailrobbe.persons.roots import Executor
from mailrobbe.persons.suggestions import address_keys, fold, normalize_name

GROUP_MAX = 6  # persons asked about in one request

Pair = tuple[int, int]

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
# Pairs not to ask about, through the roots of their persons: dismissed, judged one person, or
# checked with the current prompt (an older prompt's other verdicts are asked again, D325).
_LEFT_OUT = text("""
    SELECT least(coalesce(a.merged_into, a.id), coalesce(b.merged_into, b.id)),
        greatest(coalesce(a.merged_into, a.id), coalesce(b.merged_into, b.id))
    FROM (SELECT person_a, person_b FROM alias_check
          WHERE prompt_version >= :version OR verdict = 'same'
          UNION SELECT person_a, person_b FROM alias_dismissal) d
    JOIN person a ON a.id = d.person_a JOIN person b ON b.id = d.person_b
""")
_MAILS = text("""
    SELECT person_id, mails FROM person_stats WHERE person_id = ANY(CAST(:ids AS bigint[]))
""")


@dataclass(frozen=True, slots=True)
class Group:
    """Roots to ask about together, ascending."""

    members: tuple[int, ...]
    suggested: bool = False  # holds an open suggestion; else loose pairs only
    both: bool = False  # holds a suggestion by name and local part
    mails: int = 0  # of the busiest person


def loose_key(name: str) -> str | None:
    """The loose key of a main name: folded surname and first initial; None for one word."""
    words = _WORDS.findall(fold(name))
    return f"{words[-1]} {words[0][0]}" if len(words) >= 2 else None


def loose_sets(addresses: Iterable[tuple[int, str, Mapping[str, int]]]) -> list[frozenset[int]]:
    """The roots sharing a loose key whose first names fit (fitting), 2 to GROUP_MAX of them,
    from the addresses (root, address, display names); role addresses and shared mailboxes have
    no main name."""
    keys: defaultdict[str, defaultdict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for root, email, used in addresses:
        found = address_keys(email, tuple(used.items()))
        if found is None:
            continue
        name = found[1] or _initialled(used)
        key = loose_key(name) if name is not None else None
        if name is not None and key is not None:
            keys[key][root].add(_WORDS.findall(fold(name))[0])
    sets = []
    for firsts in keys.values():
        if len(firsts) > GROUP_MAX:
            continue
        pairs = [
            (a, b)
            for a, b in combinations(sorted(firsts), 2)
            if any(fitting(x, y) for x in firsts[a] for y in firsts[b])
        ]
        sets += [cluster for cluster in _clusters(pairs) if len(cluster) >= 2]
    return sorted(sets, key=sorted)


def fitting(first: str, other: str) -> bool:
    """Whether two folded first names may be one person's: the same, an initial of the other,
    one the start of the other ("hans", "hans-peter" as "hans"), or one letter apart from four
    letters on ("thomas", "tomas"). "matthias" and "miriam" are not, so they are not asked."""
    if first == other or len(first) == 1 or len(other) == 1:
        return True
    if first.startswith(other) or other.startswith(first):
        return True
    return min(len(first), len(other)) >= 4 and _one_apart(first, other)


def _one_apart(first: str, other: str) -> bool:
    """One letter changed, added or dropped."""
    if abs(len(first) - len(other)) > 1:
        return False
    if len(first) == len(other):
        return sum(a != b for a, b in zip(first, other, strict=True)) == 1
    short, long = sorted((first, other), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def _initialled(used: Mapping[str, int]) -> str | None:
    """The most used display name of two words or more, for an address without a main name:
    "Dr. T. Hermann" is none for the suggestions, but has a loose key."""
    names = [(mails, name) for name, mails in used.items() if normalize_name(name) is not None]
    return normalize_name(max(names, key=lambda item: (item[0], item[1]))[1]) if names else None


def groups(
    suggestions: Iterable[tuple[int, int, AliasTier, bool]],
    loose: Iterable[frozenset[int]],
    left_out: Set[Pair],
    mails: Mapping[int, int],
) -> list[Group]:
    """The groups in the order they are asked about (module docstring), from the suggestions
    (a, b, tier, both), the sets of a loose key, the pairs left out and the mails per root."""
    loose = list(loose)
    suggested: dict[Pair, bool] = {
        (a, b): both
        for a, b, tier, both in suggestions
        if tier is AliasTier.UNCERTAIN and (a, b) not in left_out
    }
    certain = {(a, b) for a, b, tier, _ in suggestions if tier is AliasTier.CERTAIN}
    open_pairs = set(suggested)
    for roots in loose:
        open_pairs |= {p for p in combinations(sorted(roots), 2) if p not in left_out | certain}
    found: list[frozenset[int]] = []
    for cluster in _clusters(open_pairs):
        if len(cluster) <= GROUP_MAX:
            found.append(cluster)
            continue
        covered: set[Pair] = set()
        for roots in loose:
            part = roots & cluster
            inside = {p for p in combinations(sorted(part), 2) if p in open_pairs}
            if inside - covered:
                found.append(part)
                covered |= inside
        found += [frozenset(p) for p in sorted(open_pairs - covered) if set(p) <= cluster]
    ranked = []
    for members in found:
        pairs = set(combinations(sorted(members), 2))
        ranked.append(
            Group(
                tuple(sorted(members)),
                suggested=bool(pairs & suggested.keys()),
                both=any(suggested.get(p, False) for p in pairs),
                mails=max(mails.get(root, 0) for root in members),
            )
        )
    return sorted(ranked, key=lambda g: (not g.suggested, not g.both, -g.mails, g.members))


def _clusters(pairs: Iterable[Pair]) -> list[frozenset[int]]:
    """The connected persons of these pairs."""
    parent: dict[int, int] = {}

    def find(person: int) -> int:
        while parent[person] != person:
            parent[person] = parent[parent[person]]
            person = parent[person]
        return person

    for a, b in pairs:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        parent[find(a)] = find(b)
    found: defaultdict[int, set[int]] = defaultdict(set)
    for person in parent:
        found[find(person)].add(person)
    return sorted((frozenset(members) for members in found.values()), key=sorted)


async def read_groups(db: Executor, version: int) -> list[Group]:
    """Every group to ask about now with the prompt of this version, in order; about as long as
    a refresh of the suggestions takes to find its keys."""
    addresses = (await db.execute(_ADDRESSES)).all()
    suggestions = [
        (row.person_a, row.person_b, AliasTier(row.tier), row.both)
        for row in await db.execute(_SUGGESTIONS)
    ]
    left_out = {(a, b) for a, b in await db.execute(_LEFT_OUT, {"version": version})}
    loose = loose_sets((root, email, used) for root, email, used in addresses)
    roots = {root for members in loose for root in members} | {
        root for a, b, *_ in suggestions for root in (a, b)
    }
    found = await db.execute(_MAILS, {"ids": sorted(roots)})
    mails = {row.person_id: row.mails for row in found}
    return groups(suggestions, loose, left_out, mails)

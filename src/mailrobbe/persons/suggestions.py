"""Alias suggestions (D30, D160, D161): pairs of root persons that may be the same person.

Keys. Each address of a root gives at most two: its main name (main_name: a person's name,
person_name, used in at least half of the mails that name the address) and its local part
(normalize_local_part). Functional mailboxes give none at all: a local part with a word of
ROLE_LOCAL_PARTS or ROLE_STEMS (also inside a compound or between separators), every address of
a root of kind list or automated (D39), and a shared mailbox, used under the names of two
persons that each have a real share of its mails (shared_mailbox). A key that more than
MAX_GROUP roots share is too generic and suggests nothing.

Tiers. A pair is certain when the names agree and the two roots share contacts. The names agree
when the pair shares a main name and a local part, or when its main name is held by these two
roots alone and each has an address with that name whose local part is made from it
(made_from_name) at the same registered domain (registered_domain). Namesakes have that too, so
the pair must also share contacts (share_contacts): the persons each root has edges with, other
than each other, counting only humans (person.kind NULL) and no hubs. A hub has edges with
HUB_SHARE of all roots and at least HUB_CONTACTS (person_stats.contacts), as the archive's owner
does, and shares contacts with everybody; a pair with a hub as one of its roots stays uncertain
for the same reason. The contacts are read for the roots of the pairs whose names agree only, in
one query over edge, after the edges and person_stats of the same refresh
(aggregates.refresh_aggregates): about 0.6 s for 5,000 such pairs among 80,000 persons with 1.6
million edges. Every other pair sharing a key is uncertain. A pair records the smallest name and
local part it shares; reason() says from the row why it was suggested.

Dismissed pairs are never suggested; alias_dismissal is read through the roots of its persons,
so a dismissal still holds after either person was merged into another. Addresses of one root
are never a pair. The keys are found and grouped here rather than in SQL, so the rules exist
once: at 80,000 persons (about 100,000 addresses) that takes about three seconds, and about one
in a process that did it before, since address_keys keeps the keys of the addresses it saw. A
refresh for some persons computes every pair as well, since a merge changes the groups of its
keys and with them pairs between other persons (a name of six roots suggests nothing, after a
merge of two of them it suggests the other four as pairs); only rows that change are written.
global_stats 'alias_suggestions' names the RULES of the latest refresh, which tells the
suggestion list whether the suggestions it shows were computed by these rules at all
(migration 0014 deleted the ones from before the tiers).
"""

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Set
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import combinations
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased

from mailrobbe.db.models import GlobalStats, Person, PersonEmail
from mailrobbe.enums import AliasTier, PersonKind
from mailrobbe.persons.roots import Executor, lock_persons
from mailrobbe.persons.sync import sync_rows

MAX_GROUP = 5  # roots sharing a key; more and it suggests nothing
SHARED_SHARE = 0.2  # a name with this share of an address's named mails (and at least
SHARED_MAILS = 2  # this many) is a real user of it; two persons' names make a shared mailbox
STATS_KEY = "alias_suggestions"  # global_stats: {"rules": RULES} of the latest refresh
RULES = 3  # of keys and tiers; 1 was D30's without tiers, 2 had tiers without contacts
# A certain pair shares this many contacts that count, and at least this share of the contacts
# of the root with fewer (D160): with these, no certain pair of the generated archives is wrong.
SHARED_CONTACTS = 2
CONTACT_OVERLAP = 0.2
HUB_SHARE = 0.1  # a root with edges to this share of all roots, and to at least
HUB_CONTACTS = 50  # this many, is a hub whose contacts tell nothing about it

# Words of a function or organisation, folded (lowercase, ä as ae, ß as ss). A local part with one
# of them between separators is a functional mailbox, and a name with one is no person's name.
ROLE_LOCAL_PARTS = frozenset(
    {
        # shared mailboxes and automated senders, also those of the test data generator
        "admin", "benachrichtigung", "bewerbung", "billing", "buchhaltung", "contact",
        "do-not-reply", "donotreply", "einkauf", "empfang", "hallo", "hello", "info", "jobs",
        "kontakt", "kundenservice", "listmaster", "mail", "mailer-daemon", "mailing", "mailman",
        "news", "newsletter", "no-reply", "noreply", "notification", "notifications", "office",
        "personal", "post", "postmaster", "presse", "rechnung", "sales", "service", "support",
        "system", "team", "vertrieb", "webmaster",
        # offices and boards of associations and parties
        "abteilung", "alle", "anfrage", "anfragen", "anmeldung", "archiv", "bundesvorstand",
        "buero", "bv", "datenschutz", "edv", "finanzen", "fraktion", "geschaeftsfuehrung",
        "geschaeftsstelle", "helpdesk", "hilfe", "it", "kasse", "kreisverband", "kv",
        "landesverband", "landesvorstand", "leitung", "lv", "mitglieder", "mitgliederverwaltung",
        "mitgliedschaft", "orga", "organisation", "ortsverband", "ov", "postfach", "poststelle",
        "pressestelle", "redaktion", "schatzmeister", "schatzmeisterei", "sekretariat", "spenden",
        "technik", "termine", "verteiler", "verwaltung", "vorsitz", "vorsitzende", "vorsitzender",
        "vorstand", "zentrale", "zentralpostfach",
        # organisations, legal forms, parties and names that act for someone else
        "ag", "amt", "auftrag", "bundestag", "co", "corp", "ev", "gbr", "gemeinde", "gmbh",
        "inc", "kg", "landtag", "llc", "ltd", "mbh", "ohg", "partei", "plc", "stadt", "ug",
        "verein", "via", "afd", "bsw", "cdu", "csu", "dgb", "dkp", "fdp", "gruene", "jusos",
        "julis", "mlpd", "npd", "oedp", "piraten", "spd", "verdi",
    }
)  # fmt: skip
# Parts of compounds that make a word functional wherever they stand: zentralpostfach,
# landesgeschaeftsstelle, fraktionsbuero, mitgliederservice, sportverein.
ROLE_STEMS = (
    "abteilung", "akademie", "buchhaltung", "buero", "fraktion", "geschaeftsstelle",
    "gewerkschaft", "gruppe", "initiative", "institut", "intranet", "kanzlei", "kundenservice",
    "ministerium", "mitglieder", "newsletter", "noreply", "partei", "postfach", "poststelle",
    "redaktion", "schatzmeister", "sekretariat", "service", "spenden", "stiftung", "support",
    "verband", "verein", "verlag", "verwaltung", "vorsitz", "vorstand", "zentral",
)  # fmt: skip
# Academic titles, left out of a name: "Dr. Anna Schmidt" is "anna schmidt".
_TITLES = frozenset({"dr", "prof", "dipl", "ing", "med", "phil", "rer", "nat", "jur", "habil"})
# Two-label public suffixes: the registered domain of a.partei.co.uk is partei.co.uk.
_PUBLIC_SUFFIXES = frozenset(
    {
        "ac.at", "co.at", "gv.at", "or.at", "ac.uk", "co.uk", "gov.uk", "me.uk", "org.uk",
        "com.au", "net.au", "org.au", "co.nz", "co.jp", "co.za", "com.br", "com.tr", "com.cn",
    }
)  # fmt: skip
_QUOTES = re.compile("[\"'`´‘’‚“”„«»‹›]")  # noqa: RUF001  (they are meant)
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")  # an addition such as "(Vertrieb)"
_ON_BEHALF = re.compile(r"\b(?:via|im auftrag)\b|\bi\. ?[av]\.")  # also inside brackets
_SEPARATORS = re.compile(r"[^a-z]+")
_NO_LETTERS = re.compile(r"[\W\d_]+")
_DIGIT = re.compile(r"\d")
_TWO_WORDS = re.compile(r"\S[\s,]+\S")  # what normalize_name needs at least
_STEMS = re.compile("|".join(ROLE_STEMS))
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

SuggestionReason = Literal[
    "name_and_local_part",
    "name_fits_addresses",
    "name_and_local_part_few_contacts",
    "name",
    "local_part",
    "ai",  # no rule suggests the pair; the alias check found it and judged it one (D323)
]

_ROOT = aliased(Person)
_KEYS = (
    select(_ROOT.id, PersonEmail.email, PersonEmail.display_names, _ROOT.kind)
    .select_from(Person)
    .join(PersonEmail, PersonEmail.person_id == Person.id)
    .join(_ROOT, _ROOT.id == func.coalesce(Person.merged_into, Person.id))
)
_DISMISSED = text("""
    SELECT coalesce(a.merged_into, a.id), coalesce(b.merged_into, b.id)
    FROM alias_dismissal d JOIN person a ON a.id = d.person_a JOIN person b ON b.id = d.person_b
""")
# The contacts of these roots, per root (every edge counts at least one mail), and the roots
# that never count as one: no humans (D39) and hubs.
_CONTACTS = text("""
    SELECT r.id, array_agg(e.other)
    FROM unnest(CAST(:roots AS bigint[])) AS r (id) CROSS JOIN LATERAL (
        SELECT person_b AS other FROM edge WHERE person_a = r.id
        UNION ALL
        SELECT person_a FROM edge WHERE person_b = r.id
    ) e
    GROUP BY r.id
""")
_NOT_COUNTED = text("""
    SELECT id FROM person WHERE merged_into IS NULL AND kind IS NOT NULL
    UNION SELECT person_id FROM person_stats WHERE contacts >= :hub
""")
_FRESH = """
    SELECT * FROM unnest(
        CAST(:person_a AS bigint[]), CAST(:person_b AS bigint[]),
        CAST(:same_name AS text[]), CAST(:same_local_part AS text[]),
        CAST(:tier AS alias_tier[])
    ) AS f (person_a, person_b, same_name, same_local_part, tier)
"""


@dataclass(frozen=True, slots=True)
class Suggestion:
    same_name: str | None  # the smallest main name both share
    same_local_part: str | None  # the smallest local part both share
    tier: AliasTier


def fold(text: str) -> str:
    """Lowercase, umlauts as mail systems spell them (ä as ae, ß as ss), other accents dropped."""
    lowered = text.lower()
    if lowered.isascii():
        return lowered
    decomposed = unicodedata.normalize("NFKD", lowered.translate(_FOLD))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_name(name: str) -> str | None:
    """A display name as suggestions compare it; None when it keeps fewer than two words.

    Lowercased, quotes, an addition in brackets and academic titles removed, "Nachname, Vorname"
    (exactly one comma) turned around, runs of whitespace made one space; it must contain no @.
    """
    plain = _BRACKETS.sub(" ", _QUOTES.sub("", name).lower())
    if "@" in plain:
        return None
    if plain.count(",") == 1:
        last, first = plain.split(",")
        plain = f"{first} {last}"
    words = [word for word in plain.split() if not _title(word)]
    return " ".join(words) if len(words) >= 2 else None


def person_name(name: str) -> str | None:
    """normalize_name of a display name that is a person's name (D161); None for any other.

    It needs two words of two letters or more, no digit, and no word of a function or
    organisation (ROLE_LOCAL_PARTS, ROLE_STEMS); "via" and "im Auftrag" also count in brackets.
    """
    key = normalize_name(name)
    if key is None or _DIGIT.search(name) or _ON_BEHALF.search(name.lower()):
        return None
    words = key.split()
    if sum(len(_NO_LETTERS.sub("", word)) >= 2 for word in words) < 2:
        return None
    return None if any(map(_functional, words)) else key


def normalize_local_part(local_part: str) -> str | None:
    """The local part of an address as suggestions compare it; None for a functional mailbox.

    Lowercased and without a +suffix; the role addresses (role_address) give None.
    """
    base = local_part.lower().partition("+")[0]
    return base if base and not role_address(base) else None


def role_address(local_part: str) -> bool:
    """Whether the local part names a functional mailbox: info@, kv.musterstadt@,
    zentralpostfach@, geschaeftsstelle-nord@, a word of ROLE_LOCAL_PARTS or ROLE_STEMS in it."""
    return _functional(local_part.lower().partition("+")[0])


def main_name(display_names: Mapping[str, int]) -> str | None:
    """The address's main name: the person's name used most (display_names: name -> mails;
    the smaller one on a tie), when it is used in at least half of the mails that name the
    address; None without one.

    A name made only of its words counts as a use of it: "Felix", "felix.schmid" and
    "Dr. Felix Schmid" for "felix schmid".
    """
    return _main_name(display_names, _person_names(display_names))


def shared_mailbox(display_names: Mapping[str, int]) -> bool:
    """Whether two persons' names each have a real share of the address's named mails; a name
    whose words all are in the other's is the same person ("anna schmidt", "anna maria schmidt")."""
    return _shared(display_names, _person_names(display_names))


def made_from_name(local_part: str, name: str) -> bool:
    """Whether the local part is first and last name, or initial and last name, of name, in
    either order, with or without separators: max.mustermann, m.mustermann, mustermann_max;
    of several first names all, the first or their initials (hans-juergen, hans, hj)."""
    compact = re.sub(r"[._-]", "", fold(local_part))
    if not compact.isalpha():
        return False
    for spelling in (fold(name), _plain(name)):
        words = [runs for runs in map(_runs, spelling.split()) if runs]
        if len(words) < 2:
            continue
        for given, last in ((words[:-1], words[-1]), (words[1:], words[0])):
            surname, runs = "".join(last), [run for word in given for run in word]
            firsts = {
                "".join(given[0]),
                "".join(runs),
                runs[0],
                runs[0][0],
                "".join(r[0] for r in runs),
            }
            if any(compact in (first + surname, surname + first) for first in firsts):
                return True
    return False


def registered_domain(domain: str) -> str:
    """The domain an organisation registered: partei.de for kv-nord.partei.de."""
    labels = domain.lower().rstrip(".").split(".")
    size = 3 if ".".join(labels[-2:]) in _PUBLIC_SUFFIXES else 2
    return ".".join(labels[-size:])


def share_contacts(shared: int, mine: int, theirs: int) -> bool:
    """Whether two roots share enough contacts for a certain pair (D160): shared contacts of
    the ones that count (see the module docstring), of which one root has mine and the other
    theirs, each without the other root."""
    return shared >= SHARED_CONTACTS and shared >= CONTACT_OVERLAP * min(mine, theirs)


def reason(same_name: str | None, same_local_part: str | None, tier: AliasTier) -> SuggestionReason:
    """Why a stored suggestion was made: the signs its row records. A pair whose name fits
    both addresses but that shares too few contacts reads as one of the same name alone."""
    certain = tier is AliasTier.CERTAIN
    if same_name is not None and same_local_part is not None:
        return "name_and_local_part" if certain else "name_and_local_part_few_contacts"
    if same_name is not None:
        return "name_fits_addresses" if certain else "name"
    return "local_part"


async def refresh_alias_suggestions(db: Executor, persons: Collection[int] | None = None) -> None:
    """Recompute alias_suggestion as a whole, or after a change of these persons.

    persons is read as in refresh_person_stats; every pair is computed either way (see the
    module docstring), so the result is that of a full refresh. Dismissed pairs
    (alias_dismissal) and persons of one root are never suggested.
    """
    if persons is not None and not persons:
        return
    await lock_persons(db)
    addresses = (await db.execute(_KEYS)).all()
    dismissed = {(min(a, b), max(a, b)) for a, b in await db.execute(_DISMISSED)}
    pairs = suggest(addresses, dismissed)
    roots = len({root for root, *_ in addresses})
    await _check_contacts(db, pairs, max(HUB_CONTACTS, HUB_SHARE * roots))
    columns: dict[str, list[Any]] = {
        "person_a": [a for a, _ in pairs],
        "person_b": [b for _, b in pairs],
        "same_name": [pair.same_name for pair in pairs.values()],
        "same_local_part": [pair.same_local_part for pair in pairs.values()],
        "tier": [pair.tier.value for pair in pairs.values()],
    }
    keys, values = ("person_a", "person_b"), ("same_name", "same_local_part", "tier")
    await sync_rows(db, "alias_suggestion", keys, values, _FRESH, columns)
    statement = postgresql.insert(GlobalStats).values(key=STATS_KEY, value={"rules": RULES})
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[GlobalStats.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
    )


@lru_cache(maxsize=1 << 18)  # every refresh reads every address again, a merge's too
def address_keys(
    email: str, display_names: tuple[tuple[str, int], ...]
) -> tuple[str | None, str | None] | None:
    """The keys of an address with these display names (name, mails): its local part
    (normalize_local_part) and main name; None for a role address or a shared mailbox."""
    local = email.rpartition("@")[0]
    names = dict(display_names)
    persons = _person_names(names)
    if role_address(local) or _shared(names, persons):
        return None
    return normalize_local_part(local), _main_name(names, persons)


def suggest(
    addresses: Iterable[tuple[int, str, Mapping[str, int], PersonKind | None]],
    dismissed: Set[tuple[int, int]],
) -> dict[tuple[int, int], Suggestion]:
    """Every pair of roots that shares a key, with its tier as the names give it, from the
    addresses: root, address, display names (name -> mails) and the root's kind. A certain pair
    still needs the contacts (see refresh_alias_suggestions)."""
    names: defaultdict[str, set[int]] = defaultdict(set)
    local_parts: defaultdict[str, set[int]] = defaultdict(set)
    # (root, main name) -> local part and domain of its addresses with that name
    named: defaultdict[tuple[int, str], list[tuple[str, str]]] = defaultdict(list)
    for root, email, used, kind in addresses:
        keys = None if kind is not None else address_keys(email, tuple(used.items()))
        if keys is None:
            continue
        local_part, name = keys
        if local_part is not None:
            local_parts[local_part].add(root)
        if name is not None:
            names[name].add(root)
            if local_part is not None:
                named[root, name].append((local_part, email.rpartition("@")[2]))
    shared: dict[tuple[int, int], list[str | None]] = {}
    for sign, groups in enumerate((names, local_parts)):
        for key, roots in groups.items():
            if not 2 <= len(roots) <= MAX_GROUP:
                continue
            for pair in combinations(sorted(roots), 2):
                if pair not in dismissed:
                    smallest = shared.setdefault(pair, [None, None])
                    current = smallest[sign]
                    if current is None or key < current:
                        smallest[sign] = key
    fits = set()  # the pairs of a main name held by both alone, made into both local parts
    for name, roots in names.items():
        if len(roots) == 2:
            a, b = sorted(roots)
            if _organisations(named[a, name], name) & _organisations(named[b, name], name):
                fits.add((a, b))
    return {
        pair: Suggestion(
            name,
            local_part,
            AliasTier.CERTAIN
            if (name is not None and local_part is not None) or pair in fits
            else AliasTier.UNCERTAIN,
        )
        for pair, (name, local_part) in shared.items()
    }


async def _check_contacts(
    db: Executor, pairs: dict[tuple[int, int], Suggestion], hub: float
) -> None:
    """Make the certain pairs uncertain whose roots include a hub (a root with at least hub
    contacts) or share too few contacts, reading the contacts of their other roots only."""
    certain = [pair for pair, found in pairs.items() if found.tier is AliasTier.CERTAIN]
    if not certain:
        return
    left_out = set(await db.scalars(_NOT_COUNTED, {"hub": hub}))
    roots = {root for pair in certain for root in pair}
    hubs = roots & left_out  # the roots of suggestions are humans
    contacts = {
        root: frozenset(other for other in others if other not in left_out)
        for root, others in await db.execute(_CONTACTS, {"roots": sorted(roots - hubs)})
    }
    none: frozenset[int] = frozenset()
    for a, b in certain:
        mine, theirs = contacts.get(a, none), contacts.get(b, none)
        sizes = len(mine) - (b in mine), len(theirs) - (a in theirs)
        if a in hubs or b in hubs or not share_contacts(len(mine & theirs), *sizes):
            pairs[a, b] = replace(pairs[a, b], tier=AliasTier.UNCERTAIN)


def _main_name(display_names: Mapping[str, int], persons: Mapping[str, int]) -> str | None:
    """main_name, given the person names (_person_names) of display_names."""
    if not persons:
        return None
    name, used = min(persons.items(), key=lambda item: (-item[1], item[0]))
    total = sum(display_names.values())
    if 2 * used < total:
        own = _words(name)
        used = sum(mails for raw, mails in display_names.items() if _words(raw) <= own)
    return name if 2 * used >= total else None


def _shared(display_names: Mapping[str, int], persons: Mapping[str, int]) -> bool:
    """shared_mailbox, given the person names (_person_names) of display_names."""
    floor = max(SHARED_MAILS, SHARED_SHARE * sum(display_names.values()))
    users = [set(name.split()) for name, mails in persons.items() if mails >= floor]
    return any(not (a <= b or b <= a) for a, b in combinations(users, 2))


def _organisations(addresses: Iterable[tuple[str, str]], name: str) -> set[str]:
    """The registered domains of the addresses (local part, domain) made from name."""
    return {registered_domain(domain) for local, domain in addresses if made_from_name(local, name)}


def _title(word: str) -> bool:
    """Whether a lowercased word is an academic title: dr., prof., dr.-ing."""
    if "." not in word and "-" not in word:
        return word in _TITLES
    runs = _runs(word)
    return bool(runs) and all(run in _TITLES for run in runs)


@lru_cache(maxsize=1 << 16)  # the words of names and local parts repeat: first names, surnames
def _functional(text: str) -> bool:
    """Whether text, a local part or a word of a name, is or holds a word of a function: as a
    whole, its letters alone (e.V.), or one of its runs of letters (kv.nord)."""
    folded = fold(text)
    runs = _runs(folded)
    letters = "".join(runs)
    if folded in ROLE_LOCAL_PARTS or letters in ROLE_LOCAL_PARTS:
        return True
    return any(run in ROLE_LOCAL_PARTS for run in runs) or _STEMS.search(letters) is not None


def _runs(text: str) -> list[str]:
    return [run for run in _SEPARATORS.split(text) if run]


def _words(name: str) -> frozenset[str]:
    """The runs of letters of a display name, folded, without brackets and titles; a name
    without letters gets a word no name has, so that it counts as the use of none."""
    words = frozenset(run for run in _runs(_BRACKETS.sub(" ", fold(name))) if run not in _TITLES)
    return words or frozenset({"@"})


def _person_names(display_names: Mapping[str, int]) -> Counter[str]:
    names: Counter[str] = Counter()
    for raw, mails in display_names.items():
        key = person_name(raw) if _TWO_WORDS.search(raw) else None
        if key is not None:
            names[key] += mails
    return names


def _plain(text: str) -> str:
    """Lowercase without accents: ü as u, the other spelling of fold."""
    decomposed = unicodedata.normalize("NFKD", text.lower().replace("ß", "ss"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))

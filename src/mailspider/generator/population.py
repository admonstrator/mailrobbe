"""Persons, mailboxes, domains and mailing lists of a generated archive (SPEC 3.6).

The archive is the export of one organisation: one or two internal domains hold a large share of
the persons, the rest are partner organisations, freemail users and automated senders. Activity
weights follow a power law, so a few hubs take part in many mails and a long tail in very few.
Every domain is below a reserved TLD.
"""

import bisect
import random
import unicodedata
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from functools import lru_cache

from mailspider.generator import vocabulary as vocab
from mailspider.generator.config import GeneratorConfig
from mailspider.generator.model import Address, Domain, DomainKind, MailKind

ERAS = 3  # a person's mail program may change between the first, middle and last third


@dataclass(frozen=True, slots=True)
class Zone:
    base: int  # minutes east of UTC outside daylight saving time
    dst: str = ""  # "eu", "us" or "" for none


ZONES: dict[str, Zone] = {
    "Europe/Berlin": Zone(60, "eu"),
    "Europe/London": Zone(0, "eu"),
    "America/New_York": Zone(-300, "us"),
    "Asia/Kolkata": Zone(330),
    "Asia/Tokyo": Zone(540),
    "UTC": Zone(0),
}


def utc_offset(zone: str, instant: datetime) -> timedelta:
    """Offset of `zone` at a UTC instant (current EU and US daylight saving rules)."""
    spec = ZONES[zone]
    minutes = spec.base
    if spec.dst:
        start, end = _dst_window(spec.dst, instant.year)
        if start <= instant < end:
            minutes += 60
    return timedelta(minutes=minutes)


@lru_cache(maxsize=512)
def _dst_window(rule: str, year: int) -> tuple[datetime, datetime]:
    if rule == "eu":  # last Sunday of March and of October, 01:00 UTC
        return _sunday(year, 3, -1, 1), _sunday(year, 10, -1, 1)
    # US: second Sunday of March 02:00 EST, first Sunday of November 02:00 EDT
    return _sunday(year, 3, 2, 7), _sunday(year, 11, 1, 6)


def _sunday(year: int, month: int, nth: int, hour: int) -> datetime:
    if nth > 0:
        first = date(year, month, 1)
        day = first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (nth - 1))
    else:
        last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
        day = last - timedelta(days=(last.weekday() - 6) % 7)
    return datetime.combine(day, time(hour), tzinfo=UTC)


_TRANSLIT = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ł": "l",
     "Ł": "L", "ø": "o", "Ø": "O", "æ": "ae", "\u0131": "i", "'": ""}
)  # fmt: skip


def transliterate(text: str) -> str:
    """Lowercase ASCII form of a name as mail systems spell it: 'Jürgen Groß' -> 'juergen gross'."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_TRANSLIT))
    return "".join(c for c in decomposed if c.isascii() and (c.isalnum() or c in " -.")).lower()


def _label(words: Sequence[str]) -> str:
    return "-".join(transliterate(word).replace(" ", "-") for word in words)


_NAME_WORDS: dict[str, str] = {
    _label([word]): word
    for word in (
        *vocab.INTERNAL_PREFIXES,
        *vocab.SUBSIDIARY_WORDS,
        *vocab.ORG_PREFIXES_DE,
        *vocab.ORG_WORDS_DE,
        *vocab.ORG_PREFIXES_EN,
        *vocab.ORG_WORDS_EN,
        *(word for words, _, _, _ in vocab.SERVICES for word in words),
        *(word for words, _, _ in vocab.LIST_HOSTS for word in words),
    )
}
_EN_PREFIXES = frozenset(_label([word]) for word in vocab.ORG_PREFIXES_EN)
_LIST_HOST_LABELS = frozenset(_label(words) for words, _, _ in vocab.LIST_HOSTS)
_FREEMAIL = frozenset(vocab.FREEMAIL_STEMS)


def _registered_label(domain: str) -> str:
    labels = domain.split(".")
    return labels[-2] if len(labels) > 1 else labels[0]


def is_freemail(domain: str) -> bool:
    return _registered_label(domain).rstrip("0123456789") in _FREEMAIL


def brand(domain: str) -> str:
    """Short organisation name behind a generated domain: 'Bergmann Möbel'."""
    parts = _registered_label(domain).rstrip("0123456789").split("-")
    return " ".join(_NAME_WORDS.get(part, part.capitalize()) for part in parts)


def org_name(domain: str) -> str | None:
    """Full organisation name with legal form, None for freemail providers."""
    if is_freemail(domain):
        return None
    label = _registered_label(domain)
    if label in _LIST_HOST_LABELS:
        return f"{brand(domain)} e.V."
    english = label.split("-")[0] in _EN_PREFIXES
    forms = vocab.LEGAL_FORMS_EN if english else vocab.LEGAL_FORMS_DE
    return f"{brand(domain)} {forms[zlib.crc32(label.encode()) % len(forms)]}"


class PersonKind(StrEnum):
    HUMAN = "human"
    ROLE = "role"  # shared mailbox such as info@ or buchhaltung@
    SERVICE = "service"  # automated sender of newsletters, notifications or invoices


@dataclass(frozen=True, slots=True)
class Person:
    index: int
    kind: PersonKind
    name: str  # canonical display name
    domain: Domain
    community: int  # department, or the department an outside contact mostly deals with
    weight: float  # activity; heavy-tailed over all persons
    language: str
    zone: str
    clients: tuple[str, ...]  # mail program per era of the date range, oldest first
    # Every mailbox of the person as its display-name variants, canonical first. Index 0 is the
    # main mailbox; `private` and `previous` point at aliases shown with the same names.
    mailboxes: tuple[tuple[Address, ...], ...]
    recipient_cum: tuple[float, ...]  # cumulative variant weights when others address the person
    sender_cum: tuple[float, ...]  # cumulative variant weights in the person's own From header
    private: int | None = None  # private freemail mailbox
    previous: int | None = None  # mailbox used before `moved` (old employer or old domain)
    moved: datetime | None = None
    service: MailKind | None = None  # what an automated sender sends
    theme: str = ""  # what its notifications are about: parcel, ticket, list, intranet, ...

    @property
    def email(self) -> str:
        return self.mailboxes[0][0].email

    @property
    def internal(self) -> bool:
        return self.domain.internal

    def mailbox(self, when: datetime) -> int:
        if self.previous is not None and self.moved is not None and when < self.moved:
            return self.previous
        return 0

    def address(self, mailbox: int, rng: random.Random, *, sender: bool = False) -> Address:
        cum = self.sender_cum if sender else self.recipient_cum
        variants = self.mailboxes[mailbox]
        return variants[bisect.bisect_right(cum, rng.random() * cum[-1])]


@dataclass(frozen=True, slots=True)
class MailingList:
    address: Address
    list_id: str  # List-Id without angle brackets
    tag: str | None  # subject tag added by a hosted list, e.g. "[diskussion]"
    members: tuple[int, ...]  # person indexes
    member_cum: tuple[float, ...]

    def pick_member(self, rng: random.Random) -> int:
        position = bisect.bisect_right(self.member_cum, rng.random() * self.member_cum[-1])
        return self.members[position]


@dataclass(frozen=True, slots=True)
class Population:
    domains: tuple[Domain, ...]
    persons: tuple[Person, ...]
    lists: tuple[MailingList, ...]
    departments: tuple[str, ...]  # community names


def build_population(config: GeneratorConfig, rng: random.Random) -> Population:
    return _Builder(config, rng).build()


_LOCAL = "\0local"  # display-name variant that repeats the mailbox's local part
_ALPHA = 0.85  # power-law exponent of the activity weights
_HUBS = 3  # most active people: always insiders
_CLIENTS = {
    "internal": (("outlook", 0.82), ("thunderbird", 0.07), ("apple", 0.06), ("mobile", 0.05)),
    "org": (("outlook", 0.6), ("thunderbird", 0.14), ("apple", 0.1), ("webmail", 0.1),
            ("mobile", 0.06)),
    "org-en": (("outlook", 0.55), ("apple", 0.2), ("webmail", 0.2), ("mobile", 0.05)),
    "freemail": (("webmail", 0.5), ("apple", 0.16), ("mobile", 0.18), ("thunderbird", 0.16)),
    "role": (("outlook", 0.6), ("webmail", 0.25), ("thunderbird", 0.15)),
}  # fmt: skip
_FOREIGN_ZONES = (
    ("Europe/London", 0.4),
    ("America/New_York", 0.3),
    ("Europe/Berlin", 0.1),
    ("Asia/Kolkata", 0.1),
    ("Asia/Tokyo", 0.1),
)
_FREEMAIL_PATTERNS = (
    ("{first}.{last}", 3.0),
    ("{first}{last}", 1.5),
    ("{first}.{last}{yy}", 2.0),
    ("{f}.{last}{yy}", 1.0),
    ("{last}.{first}", 1.0),
    ("{first}_{last}", 0.6),
    ("{first}{yyyy}", 0.8),
)
_ORG_PATTERNS = (
    ("{first}.{last}", 0.6),
    ("{f}.{last}", 0.2),
    ("{f}{last}", 0.12),
    ("{last}", 0.08),
)


def _weighted[T](rng: random.Random, options: Sequence[tuple[T, float]]) -> T:
    total = sum(weight for _, weight in options)
    point = rng.random() * total
    for value, weight in options:
        point -= weight
        if point < 0:
            return value
    return options[-1][0]


def _allocate(total: int, weights: Sequence[float]) -> list[int]:
    """Split `total` proportionally to `weights` (largest remainder, deterministic)."""
    scale = sum(weights)
    if total <= 0 or scale <= 0:
        return [0] * len(weights)
    raw = [total * weight / scale for weight in weights]
    counts = [int(value) for value in raw]
    order = sorted(range(len(raw)), key=lambda i: raw[i] - counts[i], reverse=True)
    for i in order[: total - sum(counts)]:
        counts[i] += 1
    return counts


def _cumulative(weights: Sequence[float]) -> tuple[float, ...]:
    total = 0.0
    out = []
    for weight in weights:
        total += weight
        out.append(total)
    return tuple(out)


@dataclass(slots=True)
class _Draft:
    """A person before weights and indexes are final."""

    kind: PersonKind
    domain: Domain
    language: str
    zone: str
    profile: str  # client distribution key
    first: str
    last: str
    variants: list[tuple[str | None, float, float]]  # display name, as recipient, as sender
    locals_: list[str]  # local part per mailbox
    domains: list[Domain]  # domain per mailbox
    community: int = 0
    service: MailKind | None = None
    theme: str = ""
    private: int | None = None
    previous: int | None = None
    moved: datetime | None = None
    clients: tuple[str, ...] = ()


class _Builder:
    def __init__(self, config: GeneratorConfig, rng: random.Random) -> None:
        self.config = config
        self.rng = rng
        self.used: set[str] = set()
        self.drafts: list[_Draft] = []
        self.languages: dict[str, str] = {}  # domain -> language of its organisation
        self.zones: dict[str, str] = {}  # domain -> time zone of a foreign organisation
        self.policies: dict[str, str] = {}  # domain -> local part pattern
        self.comma_style: set[str] = set()  # domains whose directory shows "Last, First"

    def build(self) -> Population:
        internal, orgs, freemail, services = self._domains()
        domains = (*internal, *orgs, *freemail, *services)
        counts = self._person_counts(internal, orgs, freemail, services)
        departments = self._departments(counts, internal)
        for domain in domains:
            self._fill(domain, counts[domain.name], len(departments), services)
        self._aliases(internal, orgs, freemail)
        persons = self._finish()
        lists = self._lists(persons, internal, services, departments)
        return Population(domains, persons, lists, departments)

    # Domains -----------------------------------------------------------------------------

    def _domains(self) -> tuple[list[Domain], list[Domain], list[Domain], list[Domain]]:
        rng = self.rng
        total = self.config.domains
        n_internal = 1 if total < 8 else 2
        rest = total - n_internal
        n_freemail = 0 if rest < 2 else max(1, round(rest * 0.06))
        n_service = 0 if rest < 3 else max(1, round(rest * 0.2))
        n_org = rest - n_freemail - n_service

        prefix = rng.choice(vocab.INTERNAL_PREFIXES)
        internal = [self._domain([prefix], DomainKind.ORGANISATION, "example", internal=True)]
        if n_internal == 2:
            words = [prefix, rng.choice(vocab.SUBSIDIARY_WORDS)]
            internal.append(self._domain(words, DomainKind.ORGANISATION, "example", internal=True))
        for domain in internal:
            self.languages[domain.name] = "de"
            if rng.random() < 0.5:
                self.comma_style.add(domain.name)

        combos = [(p, w, "de") for p in vocab.ORG_PREFIXES_DE for w in vocab.ORG_WORDS_DE]
        combos_en = [(p, w, "en") for p in vocab.ORG_PREFIXES_EN for w in vocab.ORG_WORDS_EN]
        rng.shuffle(combos)
        rng.shuffle(combos_en)
        orgs = []
        for i in range(n_org):
            pool = combos_en if rng.random() < 0.2 and combos_en else combos
            first, word, language = pool.pop() if pool else (f"Firma{i}", "Gruppe", "de")
            domain = self._domain([first, word], DomainKind.ORGANISATION, self._tld())
            self.languages[domain.name] = language
            if language == "en":
                self.zones[domain.name] = _weighted(rng, _FOREIGN_ZONES)
            if rng.random() < 0.2:
                self.comma_style.add(domain.name)
            orgs.append(domain)

        stems = list(vocab.FREEMAIL_STEMS)
        rng.shuffle(stems)
        freemail = []
        for i in range(n_freemail):
            stem = stems[i % len(stems)] + (str(i // len(stems) + 23) if i >= len(stems) else "")
            freemail.append(self._domain([stem], DomainKind.FREEMAIL, self._tld()))

        catalogue: list[tuple[tuple[str, ...], str]] = [
            *((words, sub) for words, _, sub, _ in vocab.SERVICES),
            *((words, "lists") for words, _, _ in vocab.LIST_HOSTS),
        ]
        rng.shuffle(catalogue)
        services = []
        for i in range(n_service):
            service_words, sub = catalogue[i % len(catalogue)]
            if i >= len(catalogue):
                sub = f"{sub or 'mail'}{i // len(catalogue) + 1}"
            services.append(self._domain(service_words, DomainKind.SERVICE, self._tld(), sub=sub))
        return internal, orgs, freemail, services

    def _tld(self) -> str:
        return "test" if self.rng.random() < 0.3 else "example"

    def _domain(
        self,
        words: Sequence[str],
        kind: DomainKind,
        tld: str,
        *,
        internal: bool = False,
        sub: str = "",
    ) -> Domain:
        base = _label(words)
        name = f"{sub}.{base}.{tld}" if sub else f"{base}.{tld}"
        number = 2
        while name in self.used:
            name = f"{sub}.{base}{number}.{tld}" if sub else f"{base}{number}.{tld}"
            number += 1
        self.used.add(name)
        return Domain(name, kind, internal)

    # Persons -----------------------------------------------------------------------------

    def _person_counts(
        self,
        internal: list[Domain],
        orgs: list[Domain],
        freemail: list[Domain],
        services: list[Domain],
    ) -> dict[str, int]:
        rng = self.rng
        groups = [(internal, 0.42), (orgs, 0.33), (freemail, 0.2), (services, 0.05)]
        extra = self.config.persons - self.config.domains
        per_group = _allocate(extra, [share if domains else 0.0 for domains, share in groups])
        # Automated senders need at most two mailboxes per domain; the rest go to people.
        spill = max(0, per_group[3] - len(services))
        per_group[3] -= spill
        per_group[1 if orgs else 0] += spill

        counts: dict[str, int] = {}
        for (domains, _), group_extra in zip(groups, per_group, strict=True):
            if not domains:
                continue
            if domains is internal:
                weights = [0.78, 0.22][: len(domains)]
            elif domains is services:
                weights = [1.0] * len(domains)
            else:
                ranks = list(range(len(domains)))
                rng.shuffle(ranks)
                exponent = 1.0 if domains is freemail else 0.8
                weights = [1.0 / (rank + 1) ** exponent for rank in ranks]
            for domain, count in zip(domains, _allocate(group_extra, weights), strict=True):
                counts[domain.name] = 1 + count
        return counts

    def _departments(self, counts: dict[str, int], internal: list[Domain]) -> tuple[str, ...]:
        staff = sum(counts[domain.name] for domain in internal)
        size = max(1, min(len(vocab.DEPARTMENTS), round(staff / 20)))
        return vocab.DEPARTMENTS[:size]

    def _fill(self, domain: Domain, count: int, departments: int, services: list[Domain]) -> None:
        rng = self.rng
        if domain.kind is DomainKind.SERVICE:
            label = _registered_label(domain.name)
            kind, theme = next(
                ((k, t) for words, k, _, t in vocab.SERVICES if _label(words) == label),
                ("list", "list"),
            )
            locals_ = rng.sample(vocab.SERVICE_LOCALS[kind], len(vocab.SERVICE_LOCALS[kind]))
            for i in range(count):
                self._add_service(domain, kind, theme, locals_[i % len(locals_)], i)
            return
        roles = 0
        system = 0
        if domain.internal:
            system = 1 if count >= 10 else 0
            roles = min(4, count // 25)
        elif domain.kind is DomainKind.ORGANISATION:
            roles = 1 if rng.random() < 0.4 else 0
        community = rng.randrange(departments)
        for _ in range(system):
            self._add_system(domain)
        role_names = rng.sample(vocab.ROLE_MAILBOXES, min(roles, len(vocab.ROLE_MAILBOXES)))
        for local, label in role_names:
            self._add_role(domain, local, label, rng.randrange(departments))
        humans = count - system - len(role_names)
        names: set[tuple[str, str]] = set()
        weights = [1.0 / (i + 1) ** 0.5 for i in range(departments)]
        for _ in range(humans):
            if domain.internal:
                member_of = _weighted(rng, list(enumerate(weights)))
            elif domain.kind is DomainKind.FREEMAIL or rng.random() < 0.2:
                member_of = rng.randrange(departments)
            else:
                member_of = community
            self._add_human(domain, member_of, names)

    def _add_human(self, domain: Domain, community: int, names: set[tuple[str, str]]) -> None:
        rng = self.rng
        org_language = self.languages.get(domain.name, "de")
        international = rng.random() < (0.85 if org_language == "en" else 0.08)
        for _ in range(20):
            if international:
                first, last = rng.choice(vocab.FIRST_NAMES_INTL), rng.choice(vocab.SURNAMES_INTL)
            else:
                first, last = rng.choice(vocab.FIRST_NAMES_DE), rng.choice(vocab.SURNAMES_DE)
            if (first, last) not in names:
                break
        names.add((first, last))
        if org_language == "en":
            language = "en"
        else:
            language = "en" if international and rng.random() < 0.25 else "de"
        zone = self.zones.get(domain.name, "Europe/Berlin")
        if zone == "Europe/Berlin" and rng.random() < 0.04:
            zone = "UTC"  # a misconfigured client or webmail that writes UTC dates

        title = rng.choice(vocab.ACADEMIC_TITLES) if rng.random() < 0.04 else ""
        plain = f"{first} {last}"
        canonical = f"{title} {plain}" if title else plain
        comma = domain.name in self.comma_style
        variants: list[tuple[str | None, float, float]] = [
            (canonical, 5.0, 3.0 if comma else 16.0),
            (f"{last}, {first}", 2.5 if domain.internal else 1.0, 16.0 if comma else 0.4),
            (None, 2.0, 0.6),
            (_LOCAL, 0.6, 0.4),
            (first, 0.4, 0.0),
        ]
        if title:
            variants.append((plain, 2.0, 0.0))
        if domain.kind is DomainKind.ORGANISATION and not domain.internal:
            variants.append((f"{plain} ({brand(domain.name)})", 0.3, 0.0))

        if domain.kind is DomainKind.FREEMAIL:
            local = self._freemail_local(first, last, domain)
            profile = "freemail"
        else:
            local = self._org_local(first, last, domain)
            profile = "internal" if domain.internal else ("org-en" if language == "en" else "org")
        self.drafts.append(
            _Draft(
                PersonKind.HUMAN,
                domain,
                language,
                zone,
                profile,
                first,
                last,
                variants,
                [local],
                [domain],
                community=community,
            )
        )

    def _add_role(self, domain: Domain, local: str, label: str, community: int) -> None:
        organisation = org_name(domain.name) or domain.name
        variants: list[tuple[str | None, float, float]] = [
            (f"{label} {brand(domain.name)}", 3.0, 10.0),
            (organisation, 1.0, 4.0),
            (None, 2.0, 1.0),
            (_LOCAL, 0.5, 0.2),
        ]
        local = self._unique_local(local, domain)
        language = self.languages.get(domain.name, "de")
        zone = "Europe/Berlin" if language == "de" else "Europe/London"
        self.drafts.append(
            _Draft(
                PersonKind.ROLE,
                domain,
                language,
                zone,
                "role",
                "",
                "",
                variants,
                [local],
                [domain],
                community=community,
            )
        )

    def _add_system(self, domain: Domain) -> None:
        local = self._unique_local(self.rng.choice(("noreply", "no-reply", "system")), domain)
        draft = _Draft(
            PersonKind.SERVICE,
            domain,
            "de",
            "Europe/Berlin",
            "",
            "",
            "",
            [(f"{brand(domain.name)} Intranet", 1.0, 1.0)],
            [local],
            [domain],
            service=MailKind.NOTIFICATION,
            theme="intranet",
            clients=("system",) * ERAS,
        )
        self.drafts.append(draft)

    def _add_service(self, domain: Domain, kind: str, theme: str, local: str, number: int) -> None:
        rng = self.rng
        name = brand(domain.name)
        if kind == "list":
            service, display = MailKind.NOTIFICATION, f"{name} Mailing-Listen"
        else:
            service = MailKind(kind)
            suffix = {"newsletter": " Newsletter", "invoice": " Kundenservice"}.get(kind, "")
            display = name + (suffix if number or rng.random() < 0.5 else "")
        local = self._unique_local(local, domain)
        zone = "UTC" if rng.random() < 0.5 else "Europe/Berlin"
        client = "bulk" if service is MailKind.NEWSLETTER else "system"
        self.drafts.append(
            _Draft(
                PersonKind.SERVICE,
                domain,
                "de" if rng.random() < 0.85 else "en",
                zone,
                "",
                "",
                "",
                [(display, 1.0, 1.0)],
                [local],
                [domain],
                service=service,
                theme=theme,
                clients=(client,) * ERAS,
            )
        )

    def _org_local(self, first: str, last: str, domain: Domain) -> str:
        pattern = self.policies.get(domain.name)
        if pattern is None:
            pattern = "{first}.{last}" if domain.internal else _weighted(self.rng, _ORG_PATTERNS)
            self.policies[domain.name] = pattern
        return self._unique_local(_fill_pattern(pattern, first, last, self.rng), domain)

    def _freemail_local(self, first: str, last: str, domain: Domain) -> str:
        pattern = _weighted(self.rng, _FREEMAIL_PATTERNS)
        return self._unique_local(_fill_pattern(pattern, first, last, self.rng), domain)

    def _unique_local(self, local: str, domain: Domain) -> str:
        candidate = local
        number = 2
        while f"{candidate}@{domain.name}" in self.used:
            candidate = f"{local}{number}"
            number += 1
        self.used.add(f"{candidate}@{domain.name}")
        return candidate

    def _aliases(self, internal: list[Domain], orgs: list[Domain], freemail: list[Domain]) -> None:
        rng = self.rng
        config = self.config
        start = datetime.combine(config.date_from, time(), tzinfo=UTC)
        span = datetime.combine(config.date_to, time(), tzinfo=UTC) - start
        for draft in self.drafts:
            if draft.kind is not PersonKind.HUMAN:
                continue
            first, last = draft.first, draft.last
            if draft.domain.internal and freemail and rng.random() < 0.12:
                domain = freemail[min(int(rng.expovariate(0.7)), len(freemail) - 1)]
                draft.locals_.append(self._freemail_local(first, last, domain))
                draft.domains.append(domain)
                draft.private = len(draft.locals_) - 1
            old: Domain | None = None
            if draft.domain is internal[0] and len(internal) > 1 and rng.random() < 0.15:
                old = internal[1]
            elif not draft.domain.internal and orgs and rng.random() < 0.03:
                old = rng.choice(orgs)
            if old is not None and old is not draft.domain:
                draft.locals_.append(self._org_local(first, last, old))
                draft.domains.append(old)
                draft.previous = len(draft.locals_) - 1
                draft.moved = start + span * rng.uniform(0.25, 0.75)

    def _finish(self) -> tuple[Person, ...]:
        rng = self.rng
        # Rank people by a biased shuffle: insiders tend to be the hubs of their own archive.
        # Automated senders are ranked among themselves, with a flatter curve.
        keys = [
            rng.random()
            * (0.6 if d.kind is PersonKind.ROLE else 1.0)
            * (0.2 if d.domain.internal else 1.0)
            for d in self.drafts
        ]
        insiders = [
            i for i, d in enumerate(self.drafts) if d.kind is PersonKind.HUMAN and d.domain.internal
        ]
        for i in sorted(insiders, key=keys.__getitem__)[:_HUBS]:
            keys[i] -= 1.0  # the archive's owners lead, whatever the shuffle says
        rank: dict[int, int] = {}
        for automated in (False, True):
            group = [
                i for i, d in enumerate(self.drafts) if (d.kind is PersonKind.SERVICE) == automated
            ]
            for position, draft_index in enumerate(sorted(group, key=keys.__getitem__)):
                rank[draft_index] = position
        persons = []
        for index, draft in enumerate(self.drafts):
            mailboxes = tuple(
                tuple(
                    Address(
                        f"{local}@{domain.name}",
                        local if display == _LOCAL else display,
                    )
                    for display, _, _ in draft.variants
                )
                for local, domain in zip(draft.locals_, draft.domains, strict=True)
            )
            clients = draft.clients or self._clients(draft.profile)
            persons.append(
                Person(
                    index=index,
                    kind=draft.kind,
                    name=str(draft.variants[0][0]),
                    domain=draft.domain,
                    community=draft.community,
                    weight=1.0 / (rank[index] + 1) ** (0.5 if draft.service else _ALPHA),
                    language=draft.language,
                    zone=draft.zone,
                    clients=clients,
                    mailboxes=mailboxes,
                    recipient_cum=_cumulative([to for _, to, _ in draft.variants]),
                    sender_cum=_cumulative([own for _, _, own in draft.variants]),
                    private=draft.private,
                    previous=draft.previous,
                    moved=draft.moved,
                    service=draft.service,
                    theme=draft.theme,
                )
            )
        return tuple(persons)

    def _clients(self, profile: str) -> tuple[str, ...]:
        options = _CLIENTS[profile]
        clients = [_weighted(self.rng, options)]
        while len(clients) < ERAS:
            keep = self.rng.random() < 0.7
            clients.append(clients[-1] if keep else _weighted(self.rng, options))
        return tuple(clients)

    # Lists -------------------------------------------------------------------------------

    def _lists(
        self,
        persons: tuple[Person, ...],
        internal: list[Domain],
        services: list[Domain],
        departments: tuple[str, ...],
    ) -> tuple[MailingList, ...]:
        rng = self.rng
        if self.config.persons < 10:
            return ()
        count = max(1, min(30, self.config.persons // 100))
        hosts = [d for d in services if d.name.startswith("lists.")]
        staff = [p for p in persons if p.kind is PersonKind.HUMAN and p.internal]
        outsiders = [p for p in persons if p.kind is PersonKind.HUMAN and not p.internal]
        if not staff:
            return ()
        lists: list[MailingList] = []
        used_locals: set[str] = set()
        for number in range(count):
            hosted = bool(hosts) and bool(outsiders) and number % 3 == 2
            if hosted:
                host = hosts[number // 3 % len(hosts)]
                label = host.name.split(".")[-2]
                local, title = next(
                    (local, title)
                    for words, local, title in vocab.LIST_HOSTS
                    if _label(words) == label
                )
                inside = rng.sample(staff, min(len(staff), rng.randint(2, 8)))
                outside = rng.sample(outsiders, min(len(outsiders), rng.randint(8, 40)))
                members = [*inside, *outside]
                display = f"{brand(host.name)} {title}".strip()
                domain_name, tag = host.name, f"[{local}]"
            else:
                domain_name = internal[0].name
                if number == 0:
                    local, display = "alle", "Alle Mitarbeitenden"
                    members = sorted(staff, key=lambda p: -p.weight)[:80]
                else:
                    department = departments[(number - 1) % len(departments)]
                    local = "team-" + _label([department])
                    display = f"Team {department}"
                    members = [p for p in staff if p.community == departments.index(department)]
                    members = members[:60] or staff[:10]
                tag = None
            local = _unique_name(local, domain_name, used_locals)
            lists.append(
                MailingList(
                    address=Address(f"{local}@{domain_name}", display),
                    list_id=f"{local}.{domain_name}",
                    tag=tag,
                    members=tuple(p.index for p in members),
                    member_cum=_cumulative([p.weight for p in members]),
                )
            )
        return tuple(lists)


def _unique_name(base: str, domain: str, used: set[str]) -> str:
    name = base
    number = 2
    while f"{name}@{domain}" in used:
        name = f"{base}{number}"
        number += 1
    used.add(f"{name}@{domain}")
    return name


def _fill_pattern(pattern: str, first: str, last: str, rng: random.Random) -> str:
    first_l = transliterate(first).replace(" ", "")
    last_l = transliterate(last).replace(" ", "")
    year = rng.randint(1955, 2002)
    return pattern.format(
        first=first_l, last=last_l, f=first_l[:1], yy=f"{year % 100:02d}", yyyy=year
    )

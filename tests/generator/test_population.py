from collections import Counter
from datetime import UTC, datetime, timedelta

from mailrobbe.generator.config import GeneratorConfig
from mailrobbe.generator.model import DomainKind, PlannedMail, stage_rng
from mailrobbe.generator.population import (
    PersonKind,
    Population,
    build_population,
    transliterate,
    utc_offset,
)

RESERVED = (".example", ".test")


def _participants(mail: PlannedMail) -> set[str]:
    return {a.email for a in (mail.sender, *mail.to, *mail.cc, *mail.bcc)}


def test_counts_and_reserved_domains(
    gen_config: GeneratorConfig, gen_population: Population
) -> None:
    population = gen_population
    assert len(population.persons) == gen_config.persons
    assert len(population.domains) == gen_config.domains
    names = {domain.name for domain in population.domains}
    assert len(names) == len(population.domains)
    assert all(name.endswith(RESERVED) for name in names)
    for person in population.persons:
        for variants in person.mailboxes:
            for address in variants:
                assert address.domain in names
                assert address.email.isascii()
                assert address.email == address.email.lower()
    assert all(lst.address.domain in names for lst in population.lists)
    kinds = Counter(domain.kind for domain in population.domains)
    assert kinds[DomainKind.FREEMAIL] >= 2
    assert kinds[DomainKind.SERVICE] >= 5


def test_internal_domains_hold_a_large_share(gen_population: Population) -> None:
    internal = [domain for domain in gen_population.domains if domain.internal]
    assert 1 <= len(internal) <= 2
    insiders = sum(person.internal for person in gen_population.persons)
    assert insiders / len(gen_population.persons) > 0.3


def test_activity_is_heavy_tailed(gen_plan: list[PlannedMail]) -> None:
    seen: Counter[str] = Counter()
    for mail in gen_plan:
        seen.update(_participants(mail))
    ranked = [count for _, count in seen.most_common()]
    hubs = ranked[: max(1, len(ranked) // 100)]
    # the top 1 % of addresses take part in a large share of all mails ...
    assert sum(hubs) / len(gen_plan) > 0.4
    # ... while a long tail appears in only one to three mails
    assert sum(count <= 3 for count in ranked) / len(ranked) > 0.2


def test_hubs_are_insiders(gen_population: Population) -> None:
    people = [p for p in gen_population.persons if p.kind is not PersonKind.SERVICE]
    top = sorted(people, key=lambda p: p.weight, reverse=True)[:3]
    assert all(person.internal for person in top)


def test_german_names_dominate_with_transliterated_local_parts(
    gen_population: Population,
) -> None:
    humans = [p for p in gen_population.persons if p.kind is PersonKind.HUMAN]
    assert sum(p.language == "de" for p in humans) / len(humans) > 0.6
    umlauts = [p for p in humans if any(c in p.name for c in "äöüÄÖÜß")]
    assert len(umlauts) > len(humans) * 0.05
    for person in umlauts:
        assert person.email.isascii()
    assert transliterate("Jürgen Groß") == "juergen gross"
    assert transliterate("Zoë Łukasz-Öztürk").isascii()


def test_local_part_patterns(gen_population: Population) -> None:
    locals_ = [p.email.partition("@")[0] for p in gen_population.persons]
    assert any("." in local for local in locals_)  # max.mueller
    assert any(local.isalpha() and len(local) > 6 for local in locals_)  # mmueller
    roles = {p.email.partition("@")[0] for p in gen_population.persons if p.kind is PersonKind.ROLE}
    automated = {
        p.email.partition("@")[0] for p in gen_population.persons if p.kind is PersonKind.SERVICE
    }
    assert roles & {"info", "buchhaltung", "vertrieb", "einkauf", "personal", "empfang", "office"}
    assert automated & {"noreply", "no-reply", "newsletter"}


def test_aliases_share_the_display_name(gen_population: Population) -> None:
    privates = [p for p in gen_population.persons if p.private is not None]
    previous = [p for p in gen_population.persons if p.previous is not None]
    assert privates and previous
    domains = {d.name: d for d in gen_population.domains}
    for person in privates:
        private = person.mailboxes[person.private or 0][0]
        assert domains[private.domain].kind is DomainKind.FREEMAIL
    for person in privates + previous:
        names = {variants[0].display_name for variants in person.mailboxes}
        assert names == {person.name}
        assert len({variants[0].domain for variants in person.mailboxes}) >= 2
    assert all(p.moved is not None for p in previous)


def test_display_name_variants(gen_population: Population) -> None:
    humans = [p for p in gen_population.persons if p.kind is PersonKind.HUMAN]
    shown = [{a.display_name for a in p.mailboxes[0]} for p in humans]
    assert any(any(name and ", " in name for name in names) for names in shown)  # Müller, Max
    assert any(None in names for names in shown)  # bare address
    for person, names in zip(humans, shown, strict=True):
        local = person.email.partition("@")[0]
        if local in names:  # the local part shown as a name
            break
    else:
        raise AssertionError("no address shown with its local part as display name")


def test_mostly_central_european_zones(gen_population: Population) -> None:
    zones = Counter(p.zone for p in gen_population.persons)
    assert zones["Europe/Berlin"] / len(gen_population.persons) > 0.5
    assert len(zones) >= 3


def test_daylight_saving_offsets() -> None:
    winter = datetime(2020, 1, 15, 12, tzinfo=UTC)
    summer = datetime(2020, 7, 15, 12, tzinfo=UTC)
    assert utc_offset("Europe/Berlin", winter) == timedelta(hours=1)
    assert utc_offset("Europe/Berlin", summer) == timedelta(hours=2)
    assert utc_offset("America/New_York", summer) == timedelta(hours=-4)
    # the EU switch: last Sunday of March 2020 was the 29th, at 01:00 UTC
    assert utc_offset("Europe/Berlin", datetime(2020, 3, 29, 0, 59, tzinfo=UTC)).seconds == 3600
    assert utc_offset("Europe/Berlin", datetime(2020, 3, 29, 1, 0, tzinfo=UTC)).seconds == 7200


def test_mailing_lists(gen_population: Population) -> None:
    lists = gen_population.lists
    assert lists
    for lst in lists:
        local, _, domain = lst.address.email.partition("@")
        assert lst.list_id == f"{local}.{domain}"
        assert lst.members
    assert any(lst.tag for lst in lists)  # a hosted list with a subject tag


def test_population_is_deterministic(gen_config: GeneratorConfig) -> None:
    first = build_population(gen_config, stage_rng(gen_config.seed, "population"))
    second = build_population(gen_config, stage_rng(gen_config.seed, "population"))
    assert first == second
    other = build_population(gen_config, stage_rng(gen_config.seed + 1, "population"))
    assert [p.email for p in other.persons] != [p.email for p in first.persons]

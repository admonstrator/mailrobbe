"""The person figures and suggestions (with their tiers) of the generated archive against its
ground truth.

The manifest gives sender, To, Cc, Bcc, date and expected DKIM result of every mail; the
importer stores exactly these participants, and dates the importer cannot parse fall back to
the MBOX separator, which carries the planned date (tests/importer/test_import_e2e.py). The
population, rebuilt from the generator config, says which addresses belong to one person.

The tests that write work on a copy (archive_copy_url), on connections of their own, since they
need committed data and, for the locks, two transactions at once.
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from itertools import combinations
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from mailrobbe import aggregates
from mailrobbe.generator.model import stage_rng
from mailrobbe.generator.population import build_population
from mailrobbe.persons.merge import merge_persons, unmerge_person
from mailrobbe.persons.stats import refresh_person_stats
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

TABLES = ("person_stats", "person_year", "alias_suggestion")
# Measured on this archive (D160): all 8 pairs of addresses of one generator person are
# suggested, 7 of them certain, and every one of the 8 suggestions is right (before the tiers
# there was a ninth, two automated senders of one domain with the same name). The floors leave
# room for changes of the generator; a certain suggestion must almost never be wrong, since
# "Alle sicheren zusammenführen" merges them unseen (D162).
RECALL_FLOOR = 0.75
PRECISION_FLOOR = 0.6
CERTAIN_RECALL_FLOOR = 0.6
CERTAIN_PRECISION_FLOOR = 0.85


@pytest.fixture
async def archive(archive_database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(archive_database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


@pytest.fixture
async def copy_engine(archive_copy_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(archive_copy_url, poolclass=pool.NullPool)
    yield engine
    await engine.dispose()


def _expected(manifest: list[dict[str, Any]]) -> tuple[dict[str, tuple[Any, ...]], dict[Any, Any]]:
    """person_stats and person_year by address, from the manifest; contacts are the addresses
    a mail joins with its sender (D36)."""
    figures: dict[str, list[Any]] = {}
    contacts: defaultdict[str, set[str]] = defaultdict(set)
    years: defaultdict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    for record in manifest:
        roles: defaultdict[str, set[str]] = defaultdict(set)
        roles[record["sender"]].add("from")
        for role in ("to", "cc", "bcc"):
            for email in record[role]:
                roles[email].add(role)
        for email in roles:
            figures.setdefault(email, [0, 0, 0, None, None, 0])
        if record["duplicate_of"] is not None:
            continue
        date = datetime.fromisoformat(record["date"]).astimezone(UTC)
        for email in roles.keys() - {record["sender"]}:
            contacts[email].add(record["sender"])
            contacts[record["sender"]].add(email)
        for email, held in roles.items():
            entry = figures[email]
            sent = "from" in held
            entry[0 if sent else 1] += 1
            entry[2] += held == {"cc"}
            entry[3] = date if entry[3] is None else min(entry[3], date)
            entry[4] = date if entry[4] is None else max(entry[4], date)
            entry[5] += sent and record["dkim"]["expected"] == "pass"  # every mail is checked
            years[email, date.year][0 if sent else 1] += 1
    stats = {
        email: (
            sent,
            received,
            cc_only,
            len(contacts[email]),
            first,
            last,
            passed / sent if sent else None,
        )
        for email, (sent, received, cc_only, first, last, passed) in figures.items()
    }
    return stats, {key: tuple(value) for key, value in years.items()}


async def test_figures_match_the_manifest(
    archive: AsyncConnection, generated_archive: GeneratedArchive
) -> None:
    expected_stats, expected_years = _expected(generated_archive.manifest)
    rows = await archive.execute(
        text(
            "SELECT p.canonical_email, s.sent, s.received, s.cc_only, s.contacts, s.first_date, "
            "s.last_date, s.dkim_pass_ratio FROM person_stats s JOIN person p ON p.id = s.person_id"
        )
    )
    stats = {email: tuple(values) for email, *values in rows}
    assert stats.keys() == expected_stats.keys()
    for email, (*counts, share) in stats.items():
        *expected_counts, expected_share = expected_stats[email]
        assert counts == expected_counts, email
        assert share == pytest.approx(expected_share, rel=1e-6), email
    years = await archive.execute(
        text(
            "SELECT p.canonical_email, y.year, y.sent, y.received "
            "FROM person_year y JOIN person p ON p.id = y.person_id"
        )
    )
    assert {(email, year): (sent, received) for email, year, sent, received in years} == (
        expected_years
    )


async def _suggested_pairs(
    connection: AsyncConnection, tier: str | None = None
) -> set[tuple[str, str]]:
    """The suggested pairs by their addresses; of one tier, or of both."""
    rows = await connection.execute(
        text(
            "SELECT a.canonical_email, b.canonical_email FROM alias_suggestion s "
            "JOIN person a ON a.id = s.person_a JOIN person b ON b.id = s.person_b "
            "WHERE s.tier::text = coalesce(:tier, s.tier::text)"
        ),
        {"tier": tier},
    )
    return {(min(a, b), max(a, b)) for a, b in rows}


def _owners(archive: GeneratedArchive) -> dict[str, int]:
    """The generator person of every mailbox address."""
    population = build_population(archive.config, stage_rng(archive.config.seed, "population"))
    return {
        variants[0].email: person.index
        for person in population.persons
        for variants in person.mailboxes
    }


async def test_suggestions_find_the_aliases_of_the_generator(
    archive: AsyncConnection, generated_archive: GeneratedArchive
) -> None:
    owners = _owners(generated_archive)
    present = set(await archive.scalars(text("SELECT canonical_email FROM person")))
    by_person: defaultdict[int, list[str]] = defaultdict(list)
    for email in sorted(present & owners.keys()):
        by_person[owners[email]].append(email)
    aliases = {pair for emails in by_person.values() for pair in combinations(emails, 2)}
    suggested = await _suggested_pairs(archive)
    same_person = {(a, b) for a, b in suggested if owners.get(a, -1) == owners.get(b, -2)}

    assert aliases, "the archive has addresses of one person"
    assert len(aliases & suggested) / len(aliases) >= RECALL_FLOOR
    assert len(same_person) / len(suggested) >= PRECISION_FLOOR

    certain = await _suggested_pairs(archive, "certain")
    assert len(aliases & certain) / len(aliases) >= CERTAIN_RECALL_FLOOR
    assert len(same_person & certain) / len(certain) >= CERTAIN_PRECISION_FLOOR


async def test_the_tiers_of_the_generated_archive(
    archive: AsyncConnection, generated_archive: GeneratedArchive
) -> None:
    """The measurement above as it is now; a change of the rules or the generator shows here."""
    owners = _owners(generated_archive)
    found = {}
    for tier in ("certain", "uncertain"):
        pairs = await _suggested_pairs(archive, tier)
        right = sum(owners.get(a, -1) == owners.get(b, -2) for a, b in pairs)
        found[tier] = (len(pairs), right)
    assert found == {"certain": (7, 7), "uncertain": (1, 1)}


async def _committed(engine: AsyncEngine, work: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    """work(connection, *args) in a transaction of its own, committed."""
    async with engine.connect() as connection:
        result = await work(connection, *args)
        await connection.commit()
    return result


async def _tables(engine: AsyncEngine) -> dict[str, list[Any]]:
    async with engine.connect() as connection:
        return {
            table: sorted(map(tuple, await connection.execute(text(f"SELECT * FROM {table}"))))
            for table in TABLES
        }


async def _ids(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT canonical_email, id FROM person"))
        return {email: person_id for email, person_id in rows}


async def test_merging_the_suggested_aliases_equals_a_full_refresh(
    copy_engine: AsyncEngine, generated_archive: GeneratedArchive
) -> None:
    await _committed(copy_engine, aggregates.refresh_aggregates)
    person = await _ids(copy_engine)
    owners = _owners(generated_archive)
    async with copy_engine.connect() as connection:
        pairs = sorted(await _suggested_pairs(connection))
    accepted: defaultdict[int, set[str]] = defaultdict(set)  # what the user would merge
    for a, b in pairs:
        if owners.get(a, -1) == owners.get(b, -2):
            accepted[owners[a]].update((a, b))
    assert accepted
    for target, *sources in map(sorted, accepted.values()):
        await _committed(copy_engine, merge_persons, person[target], [person[x] for x in sources])
    # then a wrong merge, undone: the busiest address into one that is no alias
    async with copy_engine.connect() as connection:
        busiest = await connection.scalar(
            text("SELECT person_id FROM person_stats ORDER BY mails DESC, person_id LIMIT 1")
        )
    other = next(
        email for email in sorted(person) if all(email not in x for x in accepted.values())
    )
    await _committed(copy_engine, merge_persons, person[other], [busiest])
    await _committed(copy_engine, unmerge_person, busiest)
    partial = await _tables(copy_engine)

    await _committed(copy_engine, aggregates.refresh_aggregates)
    assert await _tables(copy_engine) == partial


async def _waiting_for_a_lock(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        for _ in range(200):
            waiting = await connection.scalar(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
            )
            if waiting:
                return
            await asyncio.sleep(0.02)
    raise AssertionError("nothing waits for the persons lock")


async def test_a_merge_waits_for_a_running_refresh(copy_engine: AsyncEngine) -> None:
    person = await _ids(copy_engine)
    first, second = sorted(person.values())[:2]
    async with copy_engine.connect() as refreshing:
        await refresh_person_stats(refreshing)  # holds the persons lock until it commits
        merging = asyncio.create_task(_committed(copy_engine, merge_persons, first, [second]))
        await _waiting_for_a_lock(copy_engine)
        assert not merging.done()
        await refreshing.commit()
    assert await merging == first
    async with copy_engine.connect() as connection:
        rows = await connection.execute(text("SELECT person_id FROM person_stats"))
        assert second not in set(rows.scalars())


async def test_concurrent_merges_keep_merged_into_naming_roots(copy_engine: AsyncEngine) -> None:
    person = await _ids(copy_engine)
    a, b, c = sorted(person.values())[:3]
    async with copy_engine.connect() as one:
        await merge_persons(one, a, [b])  # b into a, not committed yet
        other = asyncio.create_task(_committed(copy_engine, merge_persons, c, [a]))
        await _waiting_for_a_lock(copy_engine)
        await one.commit()
    await other
    async with copy_engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT id, merged_into FROM person WHERE id = ANY(:ids)"), {"ids": [a, b, c]}
        )
        assert {person_id: root for person_id, root in rows} == {a: c, b: c, c: None}

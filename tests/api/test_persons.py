"""The persons API (D28 to D33, D160 to D163): list, profile, contacts, mail counts,
suggestions, merges, the merge log and undoing merges.

The tests run on copies of the imported archive whose aggregate rows are replaced by a seed:
person_stats, person_year, edge and alias_suggestion get rows chosen here (ties, persons without
a name, a date or figures, a stale row of an alias), and some addresses are merged, so that
every order and field can be computed independently of api/persons.py. Whatever
refresh_aggregates wrote there is deleted first. Mail counts are checked against the mail list's
summary, the mail counts of aliases and the display names against SQL on participation and
person_email.
"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Collection, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api.schemas import DISPLAY_NAME_LIMIT, MERGE_LIMIT, SUGGESTION_LIMIT, TOP_CONTACTS
from tests.api.conftest import _client, api_settings
from tests.conftest import GeneratedArchive, _temporary_database

pytestmark = pytest.mark.db

Params = Sequence[tuple[str, str]]
Json = dict[str, Any]
BASE = datetime(2015, 3, 1, 12, tzinfo=UTC)
SORTS = ["mails", "name", "recent"]
UNKNOWN = 987654321
TIERS = ["certain", "uncertain"]
EDITOR = {"X-Mailrobbe-Editor": "Lena%20Vogt"}
SEARCHED_NAME = "Zacharias Quellenhof"  # in no address
# Mails in which busy's addresses take several roles, which the tabs tell apart (D29): Cc and To,
# Cc and Bcc, To and From, and Bcc of a mail from `other`.
MORE_ROLES = """
    INSERT INTO participation (mail_id, person_id, role)
    WITH mine AS (SELECT pa.mail_id, pa.person_id, pa.role FROM participation pa
                  JOIN mail m ON m.id = pa.mail_id AND m.is_duplicate_of IS NULL)
    (SELECT mail_id, CAST(:first AS bigint), 'to'::participation_role FROM mine
     WHERE person_id = :busy AND role = 'cc' AND NOT EXISTS (SELECT 1 FROM participation x
      WHERE x.mail_id = mine.mail_id AND x.person_id IN (:busy, :first, :second) AND x.role <> 'cc')
     ORDER BY mail_id LIMIT 1)
    UNION ALL
    (SELECT mail_id, :second, 'bcc' FROM mine
     WHERE person_id = :busy AND role = 'cc' AND NOT EXISTS (SELECT 1 FROM participation x
      WHERE x.mail_id = mine.mail_id AND x.person_id IN (:busy, :first, :second) AND x.role <> 'cc')
     ORDER BY mail_id DESC LIMIT 1)
    UNION ALL
    (SELECT mail_id, :first, 'from' FROM mine
     WHERE person_id = :busy AND role = 'to' AND NOT EXISTS (SELECT 1 FROM participation x
      WHERE x.mail_id = mine.mail_id AND x.person_id IN (:busy, :first, :second)
      AND x.role = 'from')
     ORDER BY mail_id LIMIT 1)
    UNION ALL
    (SELECT mail_id, :busy, 'bcc' FROM mine
     WHERE person_id = :other AND role = 'from' AND NOT EXISTS (SELECT 1 FROM participation x
      WHERE x.mail_id = mine.mail_id AND x.person_id IN (:busy, :first, :second))
     ORDER BY mail_id LIMIT 1)
"""


async def fetch(url: str, sql: str, **params: Any) -> list[Any]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(text(sql), params)).all())
    finally:
        await engine.dispose()


async def execute(url: str, *statements: tuple[str, Any]) -> None:
    """Each (sql, parameters) in one transaction; a list of parameters runs it for each."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            for sql, params in statements:
                if not isinstance(params, list) or params:
                    await connection.execute(text(sql), params)
    finally:
        await engine.dispose()


def stamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def reason(name: str | None, local: str | None, tier: str) -> str:
    """Why a suggestion was made, from its row (D160)."""
    if name is not None and local is not None:
        return "name_and_local_part" if tier == "certain" else "name_and_local_part_few_contacts"
    if name is not None:
        return "name_fits_addresses" if tier == "certain" else "name"
    return "local_part"


# The seed ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Seed:
    """What the seed wrote, next to the persons as they are after it."""

    url: str
    people: dict[int, Any]  # every person: id, canonical_email, display_name, domain, merged_into
    stats: dict[int, Json]  # person_stats rows by person id (dates as datetime)
    years: dict[int, list[tuple[int, int, int]]]  # person_year rows by person: year, sent, received
    edges: list[Json]  # edge rows
    suggestions: list[tuple[int, int, str | None, str | None, str]]  # alias_suggestion rows
    aliases: dict[int, list[int]]  # root -> the persons merged into it
    busy: int  # a root with two aliases, years, more contacts than TOP_CONTACTS, suggestions
    other: int  # a root with one alias
    unaggregated: list[int]  # roots without a person_stats row
    stale: int  # an alias that has a person_stats row of its own, never listed

    @property
    def listed(self) -> list[int]:
        """The roots the person list shows: those with figures."""
        return sorted(p for p in self.stats if self.people[p].merged_into is None)

    def figures(self, person_id: int) -> Json:
        row = self.stats[person_id]
        return {
            **row,
            "mails": row["sent"] + row["received"],
            "first_date": stamp(row["first_date"]),
            "last_date": stamp(row["last_date"]),
        }

    def summary(self, person_id: int) -> Json:
        person = self.people[person_id]
        return {
            "id": person_id,
            "name": person.display_name,
            "email": person.canonical_email,
            "domain": person.domain,
            "aliases": len(self.aliases.get(person_id, [])),
            "figures": self.figures(person_id),
            "label": None,
        }

    def mails(self, person_id: int) -> int:
        return int(self.stats[person_id]["sent"] + self.stats[person_id]["received"])

    def contacts(self, root: int) -> list[Json]:
        """The edges of root as Contact, most mails first, then the higher id."""
        found = []
        for edge in self.edges:
            if root not in (edge["a"], edge["b"]):
                continue
            mine = edge["a"] == root
            other = edge["b"] if mine else edge["a"]
            person = self.people[other]
            found.append(
                {
                    "person": {
                        "person_id": other,
                        "email": person.canonical_email,
                        "name": person.display_name,
                        "label": None,
                    },
                    "domain": person.domain,
                    "mails": edge["a_to_b"] + edge["b_to_a"] + edge["cc"],
                    "sent": edge["a_to_b"] if mine else edge["b_to_a"],
                    "received": edge["b_to_a"] if mine else edge["a_to_b"],
                    "cc": edge["cc"],
                    "first_date": stamp(edge["first"]),
                    "last_date": stamp(edge["last"]),
                }
            )
        return sorted(found, key=lambda c: (c["mails"], c["person"]["person_id"]), reverse=True)

    def suggestion_page(self, tier: str) -> list[Json]:
        """The suggestions of a tier as AliasSuggestion, in the order of the suggestion list."""
        items = []
        for a, b, name, local, kind in self.suggestions:
            if kind != tier:
                continue
            first, second = (b, a) if self.mails(b) > self.mails(a) else (a, b)
            key = (name is not None and local is not None, self.mails(first), first, second)
            items.append((key, first, second, name, local))
        return [
            {
                "first": self.summary(first),
                "second": self.summary(second),
                "same_name": name,
                "same_local_part": local,
                "tier": tier,
                "reason": reason(name, local, tier),
            }
            for _, first, second, name, local in sorted(items, reverse=True)
        ]

    def counts(self, root: int | None = None) -> Json:
        """The suggestions per tier, of root or of all."""
        tiers = [row[4] for row in self.suggestions if root is None or root in row[:2]]
        return {tier: tiers.count(tier) for tier in TIERS}

    def candidates(self, root: int) -> list[Json]:
        """The suggestions with root as AliasCandidate: certain ones first, then the other
        person's mails."""
        found = [
            (b if a == root else a, name, local, tier)
            for a, b, name, local, tier in self.suggestions
            if root in (a, b)
        ]
        found.sort(key=lambda c: (c[3] == "certain", self.mails(c[0]), c[0]), reverse=True)
        return [
            {
                "person": self.summary(other),
                "same_name": name,
                "same_local_part": local,
                "tier": tier,
                "reason": reason(name, local, tier),
            }
            for other, name, local, tier in found[:SUGGESTION_LIMIT]
        ]


async def _seed(url: str) -> Seed:
    ranked = [
        row.id
        for row in await fetch(
            url,
            "SELECT person_id AS id FROM participation GROUP BY 1 ORDER BY count(*) DESC, 1",
        )
    ]
    busy, other = ranked[0], ranked[1]
    aliases = {busy: [ranked[3], ranked[7]], other: [ranked[10]]}
    unaggregated = ranked[30:32]
    await execute(
        url,
        *(
            (f"DELETE FROM {table}", {})
            for table in ("alias_suggestion", "person_year", "person_stats", "edge_year", "edge")
        ),
        ("UPDATE person SET merged_into = NULL", {}),
        (
            "UPDATE person SET merged_into = :root WHERE id = :alias",
            [{"root": r, "alias": a} for r, members in aliases.items() for a in members],
        ),
        ("UPDATE person SET display_name = NULL WHERE id = ANY(:ids)", {"ids": ranked[20:23]}),
        (
            "UPDATE person SET display_name = :name WHERE id = :alias",
            {"name": SEARCHED_NAME, "alias": aliases[busy][1]},
        ),
        (
            MORE_ROLES,
            {"busy": busy, "first": aliases[busy][0], "second": aliases[busy][1], "other": other},
        ),
    )
    people = {
        row.id: row
        for row in await fetch(
            url, "SELECT id, canonical_email, display_name, domain, merged_into FROM person"
        )
    }
    roots = sorted(p for p, row in people.items() if row.merged_into is None)
    stats: dict[int, Json] = {}
    for root in roots:
        if root in unaggregated:
            continue
        sent, received = (60, 45) if root == busy else (root * 7 % 5, root * 3 % 4)
        dated = root % 5 != 0
        stats[root] = {
            "sent": sent,
            "received": received,
            "cc_only": min(received, root % 2),
            "contacts": root % 6,
            "first_date": BASE + timedelta(days=root) if dated else None,
            "last_date": BASE + timedelta(days=400 + root % 9) if dated else None,
            "dkim_pass_ratio": None if root % 3 == 0 else (root % 5) / 4,
        }
    stale = aliases[busy][0]
    stale_row = {**stats[busy], "sent": 99}
    years = {busy: [(2016, 5, 0), (2015, 3, 4), (2018, 0, 2)], other: [(2019, 1, 1)]}
    others = [root for root in stats if root not in (busy, other)]
    edges = [
        {
            "a": min(busy, contact),
            "b": max(busy, contact),
            "a_to_b": index % 4,
            "b_to_a": index * 2 % 3,
            "cc": index % 2,
            "first": None if index == 0 else BASE + timedelta(days=index),
            "last": None if index == 0 else BASE + timedelta(days=100 + index),
        }
        # From both ends of the ids, so that busy is person_a of some edges, person_b of others.
        for index, contact in enumerate([other, *others[:6], *others[-6:]])
    ]
    # An edge without busy, with more mails than any of its own.
    edges.append(
        {
            "a": others[0],
            "b": others[1],
            "a_to_b": 50,
            "b_to_a": 0,
            "cc": 0,
            "first": None,
            "last": None,
        }
    )
    c = others[6:-6]
    pairs = [
        (busy, c[0], "anna beispiel", "anna", "certain"),
        (busy, c[1], "anna beispiel", None, "certain"),
        (busy, c[2], None, "anna", "uncertain"),
        (other, c[3], None, "otto", "uncertain"),
        (c[4], c[5], "bert muster", "bert", "certain"),
        (c[6], c[7], "carl ober", "carl", "uncertain"),  # too few shared contacts
        (c[8], c[9], "dora reich", None, "uncertain"),
        (c[10], c[11], "emil sander", "emil", "certain"),
    ]
    suggestions = [(min(a, b), max(a, b), *keys) for a, b, *keys in pairs]
    figures = "sent, received, cc_only, contacts, first_date, last_date, dkim_pass_ratio"
    await execute(
        url,
        (
            f"INSERT INTO person_stats (person_id, {figures}) VALUES (:person_id, :sent,"
            " :received, :cc_only, :contacts, :first_date, :last_date, :dkim_pass_ratio)",
            [{"person_id": p, **row} for p, row in [*stats.items(), (stale, stale_row)]],
        ),
        (
            "INSERT INTO person_year (person_id, year, sent, received)"
            " VALUES (:person_id, :year, :sent, :received)",
            [
                {"person_id": p, "year": year, "sent": sent, "received": received}
                for p, rows in years.items()
                for year, sent, received in rows
            ],
        ),
        (
            "INSERT INTO edge (person_a, person_b, mails_a_to_b, mails_b_to_a, mails_cc,"
            " first_date, last_date) VALUES (:a, :b, :a_to_b, :b_to_a, :cc, :first, :last)",
            edges,
        ),
        (
            "INSERT INTO alias_suggestion (person_a, person_b, same_name, same_local_part,"
            " tier) VALUES (:a, :b, :name, :local, CAST(:tier AS alias_tier))",
            [
                {"a": a, "b": b, "name": name, "local": local, "tier": tier}
                for a, b, name, local, tier in suggestions
            ],
        ),
    )
    return Seed(
        url=url,
        people=people,
        stats=stats,
        years=years,
        edges=edges,
        suggestions=suggestions,
        aliases=aliases,
        busy=busy,
        other=other,
        unaggregated=unaggregated,
        stale=stale,
    )


@pytest.fixture(scope="module")
def seed(database_server_url: str, imported_database_url: str) -> Iterator[Seed]:
    """A seeded copy of the imported archive, shared by the module's read-only tests."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        yield asyncio.run(_seed(url))


@pytest.fixture
async def seeded(
    seed: Seed, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Client on the shared seeded copy. Read only."""
    async for http in _client(api_settings(seed.url, generated_archive, tmp_path / "no-frontend")):
        yield http


@pytest.fixture
def writable_url(database_server_url: str, seed: Seed) -> Iterator[str]:
    """A copy of the seeded database for one test that writes."""
    with _temporary_database(database_server_url, make_url(seed.url).database) as url:
        yield url


@pytest.fixture
async def writable(
    writable_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings(writable_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


async def get(client: httpx.AsyncClient, path: str, params: Params = (), status: int = 200) -> Any:
    response = await client.get(path, params=list(params))
    assert response.status_code == status, response.text
    return response.json()


async def post(
    client: httpx.AsyncClient,
    path: str,
    body: Any,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> Any:
    response = await client.post(path, json=body, headers=headers)
    assert response.status_code == status, response.text
    return None if status == 204 else response.json()


def at(cursor: str | None) -> Params:
    return [] if cursor is None else [("cursor", cursor)]


async def pages(client: httpx.AsyncClient, path: str, params: Params, limit: int) -> list[Any]:
    """Every page, following next_cursor from the first one."""
    found: list[Any] = []
    cursor = None
    while True:
        page = await get(client, path, [*params, ("limit", str(limit)), *at(cursor)])
        found.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return found


# The person list -----------------------------------------------------------------------------


async def expected_order(
    seed: Seed, sort: str, persons: Collection[int] | None = None
) -> list[int]:
    listed = seed.listed if persons is None else [p for p in seed.listed if p in persons]
    if sort == "mails":
        return sorted(listed, key=lambda p: (seed.mails(p), p), reverse=True)
    if sort == "recent":
        oldest = datetime.min.replace(tzinfo=UTC)
        return sorted(listed, key=lambda p: (seed.stats[p]["last_date"] or oldest, p), reverse=True)
    # The database's collation decides the order of names.
    found = await fetch(
        seed.url,
        "SELECT id FROM person WHERE id = ANY(:ids)"
        " ORDER BY lower(COALESCE(display_name, canonical_email)), id",
        ids=listed,
    )
    return [row.id for row in found]


@pytest.mark.parametrize("sort", SORTS)
async def test_the_person_list_pages_in_each_order(
    seeded: httpx.AsyncClient, seed: Seed, sort: str
) -> None:
    expected = await expected_order(seed, sort)
    assert expected[0] == seed.busy or sort != "mails"
    assert seed.stale not in expected and not set(seed.unaggregated) & set(expected)
    forward = await pages(seeded, "/api/persons", [("sort", sort)], 7)
    items = [item for page in forward for item in page["items"]]
    assert [item["id"] for item in items] == expected
    assert items == [seed.summary(person) for person in expected]
    assert {page["total"] for page in forward} == {len(expected)}
    assert forward[0]["prev_cursor"] is None
    assert all(page["prev_cursor"] for page in forward[1:])

    cursor = forward[-1]["prev_cursor"]
    for page in reversed(forward[:-1]):
        back = await get(seeded, "/api/persons", [("sort", sort), ("limit", "7"), *at(cursor)])
        assert back["items"] == page["items"]
        assert back["next_cursor"] is not None
        cursor = back["prev_cursor"]
    assert cursor is None


async def test_the_person_list_defaults_to_most_mails(
    seeded: httpx.AsyncClient, seed: Seed
) -> None:
    page = await get(seeded, "/api/persons")
    assert [item["id"] for item in page["items"]] == (await expected_order(seed, "mails"))[:50]
    assert page["total"] == len(seed.listed)


def matching(seed: Seed, q: str) -> set[int]:
    """Roots with an address or display name, own or of an alias, containing q (any case)."""
    part = q.strip().lower()
    return {
        person.merged_into or person.id
        for person in seed.people.values()
        if part in person.canonical_email.lower() or part in (person.display_name or "").lower()
    }


async def test_the_search_matches_addresses_and_names_of_roots_and_aliases(
    seeded: httpx.AsyncClient, seed: Seed
) -> None:
    alias = seed.people[seed.aliases[seed.busy][1]]
    named = next(
        p
        for p in seed.people.values()
        if p.id in seed.listed and p.display_name and p.display_name.split()[-1][:4].isascii()
    )
    cases = [
        alias.canonical_email.split("@")[0].upper(),  # finds the alias's root
        SEARCHED_NAME.split()[1].upper(),  # the alias's display name only
        f"  {named.display_name.split()[-1][:4].lower()} ",
        seed.people[seed.busy].domain,
        "_",  # a literal underscore, not any character
        "%",
        "zzz-nobody",
    ]
    for q in cases:
        expected = await expected_order(seed, "mails", matching(seed, q))
        for sort in SORTS:
            found = await pages(seeded, "/api/persons", [("q", q), ("sort", sort)], 5)
            ids = [item["id"] for page in found for item in page["items"]]
            assert sorted(ids) == sorted(expected), q
            assert {page["total"] for page in found} == {len(expected)}, q
        assert ids or q not in cases[:4], q
    first = await get(seeded, "/api/persons", [("q", cases[0])])
    assert seed.busy in [item["id"] for item in first["items"]]
    everybody = await get(seeded, "/api/persons", [("q", "   "), ("limit", "1")])
    assert everybody["total"] == len(seed.listed)


async def test_a_person_cursor_is_bound_to_sort_and_search(
    seeded: httpx.AsyncClient, seed: Seed
) -> None:
    page = await get(seeded, "/api/persons", [("limit", "3")])
    cursor = page["next_cursor"]
    # The same cursor with a name where the mail count belongs: still no database error.
    data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    data["k"][0] = "x"
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    for params in (
        [("sort", "name"), ("cursor", cursor)],
        [("q", "a"), ("cursor", cursor)],
        [("cursor", "bm90IGEgY3Vyc29y")],
        [("cursor", "!!")],
        [("cursor", forged)],
    ):
        error = await get(seeded, "/api/persons", params, status=400)
        assert error["detail"]["code"] == "invalid_cursor"
    searched = await get(seeded, "/api/persons", [("q", "a"), ("limit", "2")])
    again = await get(seeded, "/api/persons", [("q", " a "), *at(searched["next_cursor"])])
    assert again["items"]


@pytest.mark.parametrize("limit", ["0", "201"])
async def test_person_pages_are_bounded(seeded: httpx.AsyncClient, limit: str) -> None:
    await get(seeded, "/api/persons", [("limit", limit)], status=422)


# Profile ---------------------------------------------------------------------------------------


async def expected_aliases(seed: Seed, root: int) -> list[Json]:
    found = await fetch(
        seed.url,
        "SELECT p.id, p.canonical_email, p.display_name, (SELECT count(DISTINCT pa.mail_id)"
        "  FROM participation pa JOIN mail m ON m.id = pa.mail_id"
        "  WHERE pa.person_id = p.id AND m.is_duplicate_of IS NULL) AS mails"
        " FROM person p WHERE p.merged_into = :root",
        root=root,
    )
    return [
        {
            "person_id": row.id,
            "email": row.canonical_email,
            "name": row.display_name,
            "mails": row.mails,
            "label": None,
        }
        for row in sorted(found, key=lambda row: (row.mails, row.id), reverse=True)
    ]


async def expected_display_names(seed: Seed, root: int) -> list[Json]:
    found = await fetch(
        seed.url,
        "SELECT n.key AS name, sum(n.value::bigint) AS mails FROM person_email e,"
        " jsonb_each_text(e.display_names) n WHERE e.person_id IN"
        " (SELECT id FROM person WHERE id = :root OR merged_into = :root)"
        " GROUP BY 1 ORDER BY 2 DESC, 1",
        root=root,
    )
    return [{"name": row.name, "mails": row.mails} for row in found]


async def test_the_profile_of_a_person_with_aliases(seeded: httpx.AsyncClient, seed: Seed) -> None:
    root, person = seed.busy, seed.people[seed.busy]
    aliases = await expected_aliases(seed, root)
    assert {alias["person_id"] for alias in aliases} == set(seed.aliases[root])
    assert all(alias["mails"] > 0 for alias in aliases)
    names = await expected_display_names(seed, root)
    assert len(names) > 1
    contacts = seed.contacts(root)
    assert len(contacts) > TOP_CONTACTS
    sides = {edge["a"] == root for edge in seed.edges if root in (edge["a"], edge["b"])}
    assert sides == {True, False}
    expected = {
        "id": root,
        "name": person.display_name,
        "email": person.canonical_email,
        "domain": person.domain,
        "aliases": aliases,
        "display_names": names[:DISPLAY_NAME_LIMIT],
        "figures": seed.figures(root),
        "years": [
            {"year": year, "sent": sent, "received": received}
            for year, sent, received in sorted(seed.years[root])
        ],
        "top_contacts": contacts[:TOP_CONTACTS],
        "suggestions": seed.candidates(root),
        "suggestion_counts": {"certain": 2, "uncertain": 1},
        "merges": [],
        "label": None,
    }
    assert seed.counts(root) == expected["suggestion_counts"]
    assert [c["tier"] for c in expected["suggestions"]] == ["certain", "certain", "uncertain"]
    for requested in (root, *seed.aliases[root]):
        assert await get(seeded, f"/api/persons/{requested}") == expected, requested


async def test_the_profile_of_a_person_without_figures(
    seeded: httpx.AsyncClient, seed: Seed
) -> None:
    root = seed.unaggregated[0]
    profile = await get(seeded, f"/api/persons/{root}")
    assert profile["id"] == root
    assert profile["figures"] is None
    assert (profile["aliases"], profile["years"], profile["top_contacts"]) == ([], [], [])
    assert profile["suggestions"] == []
    assert profile["suggestion_counts"] == {"certain": 0, "uncertain": 0}
    assert profile["merges"] == []
    assert profile["display_names"] == await expected_display_names(seed, root)

    other = await get(seeded, f"/api/persons/{seed.other}")
    assert [alias["person_id"] for alias in other["aliases"]] == seed.aliases[seed.other]
    assert other["top_contacts"] == seed.contacts(seed.other)
    assert other["suggestions"] == seed.candidates(seed.other)
    assert other["suggestion_counts"] == seed.counts(seed.other)


async def test_unknown_and_invalid_person_ids(seeded: httpx.AsyncClient) -> None:
    for path in ("", "/contacts", "/mail-counts"):
        error = await get(seeded, f"/api/persons/{UNKNOWN}{path}", status=404)
        assert error["detail"]["code"] == "not_found"
    for path in ("/api/persons/abc", f"/api/persons/{2**63}", f"/api/persons/{2**63}/contacts"):
        await get(seeded, path, status=422)


# Contacts --------------------------------------------------------------------------------------


async def test_contacts_page_through_every_edge(seeded: httpx.AsyncClient, seed: Seed) -> None:
    expected = seed.contacts(seed.busy)
    assert len({c["mails"] for c in expected}) < len(expected)  # ties, ordered by id
    for requested in (seed.busy, seed.aliases[seed.busy][0]):
        found = await pages(seeded, f"/api/persons/{requested}/contacts", [], 4)
        assert [c for page in found for c in page["items"]] == expected
        assert {page["total"] for page in found} == {len(expected)}
        assert all(page["next_cursor"] for page in found[:-1])
    unconnected = seed.unaggregated[0]
    assert await get(seeded, f"/api/persons/{unconnected}/contacts") == {
        "items": [],
        "next_cursor": None,
        "total": 0,
    }

    first = await get(seeded, f"/api/persons/{seed.busy}/contacts", [("limit", "2")])
    persons = await get(seeded, "/api/persons", [("limit", "2")])
    for path, cursor in (
        (f"/api/persons/{seed.other}/contacts", first["next_cursor"]),
        (f"/api/persons/{seed.busy}/contacts", persons["next_cursor"]),
        (f"/api/persons/{seed.busy}/contacts", "e30"),
    ):
        error = await get(seeded, path, [("cursor", cursor)], status=400)
        assert error["detail"]["code"] == "invalid_cursor"


# Alias suggestions -----------------------------------------------------------------------------


@pytest.mark.parametrize("tier", TIERS)
async def test_suggestions_page_in_order(seeded: httpx.AsyncClient, seed: Seed, tier: str) -> None:
    expected = seed.suggestion_page(tier)
    reasons = {
        "certain": {"name_and_local_part", "name_fits_addresses"},
        "uncertain": {"name_and_local_part_few_contacts", "name", "local_part"},
    }
    assert {item["reason"] for item in expected} == reasons[tier]
    found = await pages(seeded, "/api/persons/suggestions", [("tier", tier)], 3)
    assert len(found) > 1
    assert [item for page in found for item in page["items"]] == expected
    assert {page["total"] for page in found} == {len(expected)}
    assert {json.dumps(page["counts"]) for page in found} == {json.dumps(seed.counts())}
    assert {page["computed"] for page in found} == {True}
    for item in expected:
        assert item["first"]["figures"]["mails"] >= item["second"]["figures"]["mails"]


async def test_the_suggestion_list_shows_certain_ones_by_default(
    seeded: httpx.AsyncClient, seed: Seed
) -> None:
    page = await get(seeded, "/api/persons/suggestions")
    assert page["items"] == seed.suggestion_page("certain")
    assert page["counts"] == seed.counts() == {"certain": 4, "uncertain": 4}

    certain = await get(seeded, "/api/persons/suggestions", [("limit", "1")])
    persons = await get(seeded, "/api/persons", [("limit", "2")])
    for params in (
        [("cursor", persons["next_cursor"])],
        [("cursor", "!!")],
        [("tier", "uncertain"), ("cursor", certain["next_cursor"])],
    ):
        error = await get(seeded, "/api/persons/suggestions", params, status=400)
        assert error["detail"]["code"] == "invalid_cursor"
    await get(seeded, "/api/persons/suggestions", [("tier", "maybe")], status=422)


async def test_suggestions_that_were_never_computed(
    writable: httpx.AsyncClient, writable_url: str
) -> None:
    empty: Json = {
        "items": [],
        "next_cursor": None,
        "total": 0,
        "counts": {"certain": 0, "uncertain": 0},
        "computed": False,
    }
    # Suggestions of older rules, then none at all.
    for change in (
        "UPDATE global_stats SET value = '{\"rules\": 1}' WHERE key = 'alias_suggestions'",
        "DELETE FROM global_stats WHERE key = 'alias_suggestions'",
    ):
        await execute(writable_url, ("DELETE FROM alias_suggestion", {}), (change, {}))
        assert await get(writable, "/api/persons/suggestions") == empty


# Mail counts -----------------------------------------------------------------------------------


async def test_mail_counts_match_the_mail_list(seeded: httpx.AsyncClient, seed: Seed) -> None:
    plain = next(p for p in seed.listed if p not in seed.aliases)
    cases = [(seed.busy, seed.other), (seed.other, seed.busy), (plain, seed.busy)]
    counted: list[Json] = []
    for person, contact in cases:
        year = (
            await fetch(
                seed.url,
                "SELECT extract(year FROM m.date_utc AT TIME ZONE 'UTC')::int AS year"
                " FROM participation pa JOIN person p ON p.id = pa.person_id"
                " JOIN mail m ON m.id = pa.mail_id"
                " WHERE (p.id = :p OR p.merged_into = :p) AND m.date_utc IS NOT NULL"
                " GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1",
                p=person,
            )
        )[0].year
        for year_params, between in (
            ([], []),
            ([("year", str(year))], []),
            ([], [("contact", str(contact))]),
            ([("year", str(year))], [("contact", str(contact))]),
        ):
            counts = await get(
                seeded, f"/api/persons/{person}/mail-counts", [*year_params, *between]
            )
            for alias in seed.aliases.get(person, []):
                path = f"/api/persons/{alias}/mail-counts"
                assert await get(seeded, path, [*year_params, *between]) == counts
            filters = [("person", str(person)), ("hide_duplicates", "true")]
            if year_params:
                filters += [("date_from", f"{year}-01-01"), ("date_to", f"{year}-12-31")]
            if between:
                filters += [("between", str(person)), ("between", str(contact))]
            for tab, role in (
                ("all", None),
                ("sent", "sent"),
                ("received", "received"),
                ("cc", "cc"),
            ):
                roles = [] if role is None else [("person_role", role)]
                summary = await get(seeded, "/api/mails/summary", [*filters, *roles])
                assert summary["exact"] is True
                assert counts[tab] == summary["total"], (person, year_params, between, tab)
            assert counts["all"] == counts["sent"] + counts["received"]
            counted.append(counts)
    assert all(counts["all"] for counts in counted[:2])
    assert any(counts["cc"] for counts in counted) and any(counts["sent"] for counts in counted)


async def test_mail_counts_of_unknown_contacts_and_far_years(
    seeded: httpx.AsyncClient, seed: Seed
) -> None:
    none = {"all": 0, "sent": 0, "received": 0, "cc": 0}
    path = f"/api/persons/{seed.busy}/mail-counts"
    assert await get(seeded, path, [("contact", str(UNKNOWN))]) == none
    assert await get(seeded, path, [("year", "9999")]) == none
    assert await get(seeded, path, [("year", "1")]) == none
    await get(seeded, path, [("year", "10000")], status=422)


async def test_mail_counts_run_out_of_time(
    writable_url: str, generated_archive: GeneratedArchive, seed: Seed, tmp_path: Path
) -> None:
    settings = api_settings(writable_url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(update={"api_count_timeout": 0.3})
    engine = create_async_engine(writable_url, poolclass=pool.NullPool)
    path = f"/api/persons/{seed.busy}/mail-counts"
    try:
        async for client in _client(settings):
            async with engine.connect() as other:
                await other.execute(text("LOCK TABLE participation IN ACCESS EXCLUSIVE MODE"))
                unknown = {"all": None, "sent": None, "received": None, "cc": None}
                assert await get(client, path) == unknown
                await other.rollback()
            assert (await get(client, path))["all"]
    finally:
        await engine.dispose()


# Merging, unmerging, dismissing --------------------------------------------------------------


async def merged_into(url: str) -> dict[int, int | None]:
    return {
        row.id: row.merged_into for row in await fetch(url, "SELECT id, merged_into FROM person")
    }


def assert_flat(roots: dict[int, int | None]) -> None:
    """merged_into always names a root (D28)."""
    for person, root in roots.items():
        assert root is None or roots[root] is None, person


async def test_merge_moves_the_sources_and_their_aliases(
    writable: httpx.AsyncClient, writable_url: str, seed: Seed
) -> None:
    plain = next(p for p in seed.listed if p not in seed.aliases)
    target_alias = seed.aliases[seed.busy][1]
    # The target given by an alias stands for its root; a source given twice counts once.
    request = {"target": target_alias, "sources": [seed.other, plain, plain]}
    profile = await post(writable, "/api/persons/merge", request)
    moved = {*seed.aliases[seed.busy], seed.other, *seed.aliases[seed.other], plain}
    assert profile["id"] == seed.busy
    assert {alias["person_id"] for alias in profile["aliases"]} == moved
    assert profile == await get(writable, f"/api/persons/{seed.busy}")
    roots = await merged_into(writable_url)
    assert {person for person, root in roots.items() if root == seed.busy} == moved
    assert roots[seed.busy] is None
    assert_flat(roots)
    found = await pages(writable, "/api/persons", [], 200)
    listed = [item["id"] for page in found for item in page["items"]]
    assert seed.other not in listed and plain not in listed and seed.busy in listed


async def test_merges_that_cannot_be(
    writable: httpx.AsyncClient, writable_url: str, seed: Seed
) -> None:
    before = await merged_into(writable_url)
    alias = seed.aliases[seed.busy][0]
    for request, status, code in (
        ({"target": seed.busy, "sources": [alias]}, 400, "invalid_merge"),
        ({"target": alias, "sources": [seed.other, seed.busy]}, 400, "invalid_merge"),
        ({"target": seed.busy, "sources": [seed.other, UNKNOWN]}, 404, "not_found"),
        ({"target": UNKNOWN, "sources": [seed.other]}, 404, "not_found"),
    ):
        error = await post(writable, "/api/persons/merge", request, status)
        assert error["detail"]["code"] == code, request
    invalid: list[Json] = [
        {"target": seed.busy, "sources": []},
        {"target": seed.busy, "sources": [seed.other] * (MERGE_LIMIT + 1)},
        {"target": seed.busy},
    ]
    for body in invalid:
        await post(writable, "/api/persons/merge", body, 422)
    assert await merged_into(writable_url) == before


async def test_unmerge_makes_an_alias_a_person_again(
    writable: httpx.AsyncClient, writable_url: str, seed: Seed
) -> None:
    alias, kept = seed.aliases[seed.busy]
    profile = await post(writable, f"/api/persons/{alias}/unmerge", None)
    assert profile["id"] == seed.busy
    assert [a["person_id"] for a in profile["aliases"]] == [kept]
    roots = await merged_into(writable_url)
    assert roots[alias] is None and roots[kept] == seed.busy
    assert (await get(writable, f"/api/persons/{alias}"))["id"] == alias

    for person, status, code in (
        (alias, 400, "invalid_merge"),
        (seed.busy, 400, "invalid_merge"),
        (UNKNOWN, 404, "not_found"),
    ):
        error = await post(writable, f"/api/persons/{person}/unmerge", None, status)
        assert error["detail"]["code"] == code
    assert await merged_into(writable_url) == roots


async def test_dismissing_a_suggestion(
    writable: httpx.AsyncClient, writable_url: str, seed: Seed
) -> None:
    first, second, *_ = next(s for s in seed.suggestions if seed.busy in s[:2])
    other = second if first == seed.busy else first
    alias = seed.aliases[seed.busy][0]
    # Given by an alias, the suggestion of its root is dismissed.
    dismiss = {"persons": [other, alias]}
    assert await post(writable, "/api/persons/suggestions/dismiss", dismiss, 204) is None
    pair = sorted((seed.busy, other))
    stored = await fetch(writable_url, "SELECT person_a, person_b FROM alias_dismissal")
    assert [tuple(row) for row in stored] == [tuple(pair)]
    left = await fetch(
        writable_url,
        "SELECT 1 FROM alias_suggestion WHERE person_a = :a AND person_b = :b",
        a=pair[0],
        b=pair[1],
    )
    assert left == []
    page = await get(writable, "/api/persons/suggestions")
    assert page["counts"] == {**seed.counts(), "certain": seed.counts()["certain"] - 1}
    profile = await get(writable, f"/api/persons/{seed.busy}")
    assert other not in [c["person"]["id"] for c in profile["suggestions"]]
    # Again: nothing changes.
    await post(writable, "/api/persons/suggestions/dismiss", {"persons": [seed.busy, other]}, 204)
    assert len(await fetch(writable_url, "SELECT 1 FROM alias_dismissal")) == 1

    for persons, status, code in (
        ([seed.busy, alias], 400, "invalid_merge"),
        ([seed.busy, UNKNOWN], 404, "not_found"),
    ):
        error = await post(
            writable, "/api/persons/suggestions/dismiss", {"persons": persons}, status
        )
        assert error["detail"]["code"] == code
    for persons in ([seed.busy], [seed.busy, other, alias]):
        await post(writable, "/api/persons/suggestions/dismiss", {"persons": persons}, 422)


# Merging every certain suggestion, the merge log, undoing merges -----------------------------


def ref(seed: Seed, person_id: int) -> Json:
    person = seed.people[person_id]
    return {"person_id": person_id, "email": person.canonical_email, "name": person.display_name}


async def test_merging_every_certain_suggestion_and_undoing_the_run(
    writable: httpx.AsyncClient, writable_url: str, seed: Seed
) -> None:
    before = await merged_into(writable_url)
    certain = [(a, b) for a, b, *_, tier in seed.suggestions if tier == "certain"]
    # busy and its two certain suggestions are one group, merged into busy (most mails); the
    # other two pairs into the one with more mails, the lower id on a tie.
    groups = {seed.busy: sorted({p for pair in certain if seed.busy in pair for p in pair})}
    for a, b in certain:
        if seed.busy not in (a, b):
            groups[min((a, b), key=lambda p: (-seed.mails(p), p))] = [a, b]
    moved = {p: target for target, members in groups.items() for p in members if p != target}
    plan = {"merges": 3, "persons": 4, "left_out_groups": 0, "left_out_persons": 0}
    assert len(moved) == 4
    assert await get(writable, "/api/persons/merge-certain") == plan

    done = await post(writable, "/api/persons/merge-certain", None, headers=EDITOR)
    assert done == {**plan, "batch_id": done["batch_id"]}
    roots = await merged_into(writable_url)
    assert {p: roots[p] for p in moved} == moved
    assert_flat(roots)
    log = await get(writable, "/api/persons/merges")
    assert (log["total"], log["next_cursor"]) == (3, None)
    ids = [item["id"] for item in log["items"]]
    assert ids == sorted(ids, reverse=True)
    assert sorted(item["target"]["person_id"] for item in log["items"]) == sorted(groups)
    for item in log["items"]:
        target = item["target"]
        assert target == ref(seed, target["person_id"])
        assert item["moved"] == [
            ref(seed, p) for p in groups[target["person_id"]] if p != target["person_id"]
        ]
        assert (item["batch_id"], item["editor"]) == (done["batch_id"], "Lena Vogt")
        assert (item["undone_at"], item["undone_by"]) == (None, None)
    [batch] = log["batches"]
    assert {key: batch[key] for key in ("id", "editor", "merges", "undone")} == {
        "id": done["batch_id"],
        "editor": "Lena Vogt",
        "merges": 3,
        "undone": 0,
    }
    profile = await get(writable, f"/api/persons/{seed.busy}")
    [merge] = profile["merges"]
    assert merge == next(item for item in log["items"] if item["target"]["person_id"] == seed.busy)

    undo = f"/api/persons/merge-batches/{done['batch_id']}/undo"
    assert await post(writable, undo, None, headers=EDITOR) == {"merges": 3, "persons": 4}
    assert await merged_into(writable_url) == before
    log = await get(writable, "/api/persons/merges")
    assert {item["undone_by"] for item in log["items"]} == {"Lena Vogt"}
    assert all(item["undone_at"] for item in log["items"])
    assert log["batches"][0]["undone"] == 3
    assert (await get(writable, f"/api/persons/{seed.busy}"))["merges"] == []

    for path in (undo, f"/api/persons/merges/{merge['id']}/undo"):
        error = await post(writable, path, None, 409)
        assert error["detail"]["code"] == "merge_undone"
    for path in (
        f"/api/persons/merges/{UNKNOWN}/undo",
        f"/api/persons/merge-batches/{UNKNOWN}/undo",
    ):
        error = await post(writable, path, None, 404)
        assert error["detail"]["code"] == "not_found"
    await post(writable, f"/api/persons/merges/{2**63}/undo", None, 422)
    assert await merged_into(writable_url) == before


async def test_groups_too_large_or_with_a_dismissed_pair_are_left_out(
    writable: httpx.AsyncClient, writable_url: str, seed: Seed
) -> None:
    chain = [p for p in seed.listed if p not in (seed.busy, seed.other)][-6:]
    # Six persons joined by certain suggestions, and two of them dismissed apart.
    await execute(
        writable_url,
        ("DELETE FROM alias_suggestion", {}),
        (
            "INSERT INTO alias_suggestion (person_a, person_b, same_name, same_local_part, tier)"
            " VALUES (:a, :b, 'kai lenz', 'kai', 'certain')",
            [
                {"a": min(pair), "b": max(pair)}
                for pair in [*pairwise(chain), (seed.other, seed.busy)]
            ],
        ),
        (
            "INSERT INTO alias_dismissal (person_a, person_b) VALUES (:a, :b)",
            {"a": min(seed.busy, seed.other), "b": max(seed.busy, seed.other)},
        ),
    )
    plan = await get(writable, "/api/persons/merge-certain")
    assert plan == {"merges": 0, "persons": 0, "left_out_groups": 2, "left_out_persons": 8}
    before = await merged_into(writable_url)
    assert await post(writable, "/api/persons/merge-certain", None) == {**plan, "batch_id": None}
    assert await merged_into(writable_url) == before
    assert (await get(writable, "/api/persons/merges"))["total"] == 0


async def test_a_merge_is_logged_and_undone_after_a_later_one(
    writable: httpx.AsyncClient, writable_url: str, seed: Seed
) -> None:
    before = await merged_into(writable_url)
    first, second = [p for p in seed.listed if p not in seed.aliases][:2]
    # other (with its alias) into first, then first into second.
    request = {"target": first, "sources": [seed.other]}
    profile = await post(writable, "/api/persons/merge", request, headers=EDITOR)
    [merge] = profile["merges"]
    members = sorted([seed.other, *seed.aliases[seed.other]])
    assert merge["moved"] == [ref(seed, p) for p in members]
    assert (merge["target"], merge["editor"], merge["batch_id"]) == (
        ref(seed, first),
        "Lena Vogt",
        None,
    )
    await post(writable, "/api/persons/merge", {"target": second, "sources": [first]})
    page = await get(writable, "/api/persons/merges", [("limit", "1")])
    assert (page["total"], page["batches"]) == (2, [])
    [later] = page["items"]
    rest = await get(writable, "/api/persons/merges", [("cursor", page["next_cursor"])])
    assert rest["items"] == [merge]
    assert rest["next_cursor"] is None
    assert (later["target"], later["editor"]) == (ref(seed, second), None)
    assert later["moved"] == [ref(seed, p) for p in sorted([first, *members])]

    # Undoing the first takes other and its alias out of second; first stays in it.
    undone = await post(writable, f"/api/persons/merges/{merge['id']}/undo", None)
    assert undone == {"merges": 1, "persons": len(members)}
    roots = await merged_into(writable_url)
    assert roots[seed.other] is None
    assert [roots[p] for p in seed.aliases[seed.other]] == [seed.other]
    assert roots[first] == second
    assert [m["id"] for m in (await get(writable, f"/api/persons/{second}"))["merges"]] == [
        later["id"]
    ]
    await post(writable, f"/api/persons/merges/{later['id']}/undo", None)
    assert await merged_into(writable_url) == before

    suggestions = await get(writable, "/api/persons/suggestions", [("limit", "1")])
    for cursor in ("!!", suggestions["next_cursor"]):
        error = await get(writable, "/api/persons/merges", [("cursor", cursor)], status=400)
        assert error["detail"]["code"] == "invalid_cursor"

"""Near duplicates in the API (D153): the filters collapse_near and near_group in the list, its
summary, the CSV and the timeline, the mark of the list's items and the group in the detail.

The archive is the imported one with groups written in SQL as the near phase would store them
(NEAR_ROWS): the mails that are no duplicates and share a subject form a group, whose id is the
smallest of their ids, and duplicates join the group of their original. Expected results are
computed apart from api/filters.py: the matches of a condition in SQL, then per group the first
of them in ascending list order.
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import make_url

from mailrobbe.api import filters
from mailrobbe.api.schemas import NEAR_LIMIT, RECIPIENT_PREVIEW
from tests.api.conftest import _client, _execute, api_settings
from tests.api.test_mails import (
    FULL_TEXT,
    Params,
    export,
    get,
    ids,
    listed,
    page_ids,
    rows,
    takes_part,
)
from tests.conftest import GeneratedArchive, _temporary_database

pytestmark = pytest.mark.db

NEAR_ROWS = [
    "UPDATE mail_near SET group_id = NULL WHERE group_id IS NOT NULL",
    """WITH shared AS (
        SELECT subject, min(id) AS group_id FROM mail WHERE is_duplicate_of IS NULL
        GROUP BY subject HAVING count(*) > 1),
    grouped AS (
        SELECT m.id, s.group_id FROM mail m JOIN shared s ON s.subject = m.subject
        WHERE m.is_duplicate_of IS NULL
        UNION ALL
        SELECT d.id, s.group_id FROM mail d JOIN mail m ON m.id = d.is_duplicate_of
        JOIN shared s ON s.subject = m.subject)
    UPDATE mail_near n SET group_id = g.group_id FROM grouped g WHERE g.id = n.mail_id""",
    "ANALYZE mail_near",
]
PERSON = "(p.id = :person OR p.merged_into = :person)"


@pytest.fixture(scope="module")
def near_database_url(database_server_url: str, imported_database_url: str) -> Iterator[str]:
    """A copy of the imported archive with the groups of NEAR_ROWS. Read only."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        asyncio.run(_execute(url, NEAR_ROWS))
        yield url


@pytest.fixture
async def near_client(
    near_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings(near_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


@pytest.fixture
def walk_rows(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(filters, "WALK_ROWS", request.param)
    return int(request.param)


WALKS = pytest.mark.parametrize(
    "walk_rows", [filters.WALK_ROWS, 7], ids=["default", "short-walk"], indirect=True
)


async def groups(url: str) -> dict[int, list[int]]:
    """The members of each group in ascending list order."""
    found = await rows(
        url,
        """SELECT n.group_id, m.id FROM mail_near n JOIN mail m ON m.id = n.mail_id
           WHERE n.group_id IS NOT NULL
           ORDER BY n.group_id, COALESCE(m.date_utc, '-infinity'), m.id""",
    )
    members: defaultdict[int, list[int]] = defaultdict(list)
    for row in found:
        members[row.group_id].append(row.id)
    return dict(members)


async def collapsed(url: str, where: str, sort: str = "date_desc", **params: Any) -> list[int]:
    """The matches of where in list order, of each group only the first in ascending order."""
    matches = await ids(url, where, sort, **params)
    matching = set(matches)
    members = (await groups(url)).values()
    first = {
        next(mail_id for mail_id in group if mail_id in matching)
        for group in members
        if matching.intersection(group)
    }
    grouped = {mail_id for group in members for mail_id in group}
    return [mail_id for mail_id in matches if mail_id not in grouped or mail_id in first]


async def a_later_persons_copy(url: str) -> tuple[int, int, int]:
    """A group, a later member of it and the root person of that member's sender, who takes
    part in no earlier member of the group."""
    found = await rows(
        url,
        """SELECT pa.mail_id, COALESCE(p.merged_into, p.id) AS root, pa.role
           FROM participation pa JOIN person p ON p.id = pa.person_id
           JOIN mail_near n ON n.mail_id = pa.mail_id WHERE n.group_id IS NOT NULL""",
    )
    persons: defaultdict[int, set[int]] = defaultdict(set)
    senders: dict[int, int] = {}
    for row in found:
        persons[row.mail_id].add(row.root)
        if row.role == "from":
            senders[row.mail_id] = row.root
    for group_id, members in sorted((await groups(url)).items()):
        for index, mail_id in enumerate(members[1:], 1):
            sender = senders.get(mail_id)
            earlier = set().union(*(persons[other] for other in members[:index]))
            if sender is not None and sender not in earlier:
                return group_id, mail_id, sender
    raise AssertionError("no group has a later member with a sender of its own")


async def test_the_fixture_has_groups_with_duplicates(near_database_url: str) -> None:
    members = await groups(near_database_url)
    assert len(members) > 5 and max(len(each) for each in members.values()) > 2
    [duplicates] = await rows(
        near_database_url,
        """SELECT count(*) AS n FROM mail_near n JOIN mail m ON m.id = n.mail_id
           WHERE n.group_id IS NOT NULL AND m.is_duplicate_of IS NOT NULL""",
    )
    assert duplicates.n > 0


@WALKS
@pytest.mark.parametrize("sort", ["date_desc", "date_asc"])
async def test_collapse_near_keeps_the_first_match_of_each_group(
    near_client: httpx.AsyncClient, near_database_url: str, walk_rows: int, sort: str
) -> None:
    url = near_database_url
    [split] = await rows(
        url,
        """SELECT percentile_disc(0.5) WITHIN GROUP (ORDER BY date_utc) AS day
           FROM mail JOIN mail_near n ON n.mail_id = mail.id WHERE n.group_id IS NOT NULL""",
    )
    midnight = datetime.combine(split.day.date(), time(), UTC)
    group_id, later, person = await a_later_persons_copy(url)
    [subject] = await rows(url, "SELECT subject FROM mail WHERE id = :id", id=group_id)
    word = subject.subject.split()[-1]
    members = ",".join(map(str, (await groups(url))[group_id]))
    cases: list[tuple[Params, str, dict[str, Any]]] = [
        ([], "true", {}),
        ([("person", str(person))], takes_part(PERSON), {"person": person}),
        (
            [("date_from", midnight.date().isoformat())],
            "COALESCE(date_utc, '-infinity') >= :day",
            {"day": midnight},
        ),
        ([("dkim", "pass")], "dkim_status = 'pass'", {}),
        ([("q", word)], FULL_TEXT, {"w": word}),
        ([("hide_duplicates", "true")], "is_duplicate_of IS NULL", {}),
        ([("near_group", str(group_id))], f"id IN ({members})", {}),
    ]
    for params, where, values in cases:
        expected = await collapsed(url, where, sort, **values)
        if not params or params[0][0] == "near_group":
            assert len(expected) < len(await ids(url, where, **values)), params
        found = await listed(near_client, [*params, ("collapse_near", "true"), ("sort", sort)])
        assert found == expected, params
        summary = await get(near_client, "/api/mails/summary", [*params, ("collapse_near", "true")])
        assert (summary["total"], summary["exact"]) == (len(expected), True), params
    # The person's copy stays when another got the first one; without the filter the first, which
    # is the earliest member, not necessarily the one whose id names the group.
    first = (await groups(url))[group_id][0]
    alone = await listed(near_client, [("person", str(person)), ("collapse_near", "true")])
    assert later in alone and first not in alone
    assert first in await listed(near_client, [("collapse_near", "true")])
    assert later not in await listed(near_client, [("collapse_near", "true")])


async def test_near_group_lists_the_group(
    near_client: httpx.AsyncClient, near_database_url: str
) -> None:
    for group_id, members in sorted((await groups(near_database_url)).items())[:5]:
        found = await listed(near_client, [("near_group", str(group_id)), ("sort", "date_asc")])
        assert found == members
    assert await listed(near_client, [("near_group", "0")]) == []


async def test_list_items_count_the_other_mails_of_their_group(
    near_client: httpx.AsyncClient, near_database_url: str
) -> None:
    size = {
        mail_id: len(members)
        for members in (await groups(near_database_url)).values()
        for mail_id in members
    }
    page = await get(near_client, "/api/mails", [("limit", "200")])
    assert {item["id"]: item["near_count"] for item in page["items"]} == {
        mail_id: size.get(mail_id, 1) - 1 for mail_id in page_ids(page)
    }
    assert any(item["near_count"] for item in page["items"])


async def test_the_detail_shows_the_group(
    near_client: httpx.AsyncClient, near_database_url: str
) -> None:
    url = near_database_url
    members = max((await groups(url)).values(), key=len)
    mail_id = members[-1]
    detail = await get(near_client, f"/api/mails/{mail_id}")
    group_id = (await rows(url, "SELECT group_id FROM mail_near WHERE mail_id = :id", id=mail_id))[
        0
    ].group_id
    assert (detail["near_group"], detail["near_size"]) == (group_id, len(members))
    others = [other for other in members if other != mail_id][:NEAR_LIMIT]
    assert [near["id"] for near in detail["near"]] == others
    found = await rows(
        url,
        """SELECT m.id, m.subject, m.dkim_status, m.is_duplicate_of IS NOT NULL AS dup,
               pa.role, p.id AS person, p.canonical_email AS email,
               COALESCE(pa.display_name, p.display_name) AS name
           FROM mail m JOIN participation pa ON pa.mail_id = m.id
           JOIN person p ON p.id = pa.person_id WHERE m.id = ANY(:ids)""",
        ids=others,
    )
    for near in detail["near"]:
        mine = [row for row in found if row.id == near["id"]]
        recipients = {row.person for row in mine if row.role != "from"}
        assert near["subject"] == mine[0].subject
        assert near["is_duplicate"] == mine[0].dup
        assert near["dkim_status"] == mine[0].dkim_status
        assert near["sender"]["person_id"] in {row.person for row in mine if row.role == "from"}
        assert near["recipient_count"] == len([row for row in mine if row.role != "from"])
        assert len(near["recipients"]) == min(RECIPIENT_PREVIEW, near["recipient_count"])
        assert {ref["person_id"] for ref in near["recipients"]} <= recipients
    assert any(near["is_duplicate"] for near in detail["near"]) or not any(row.dup for row in found)
    # A mail in no group
    [single] = await rows(url, "SELECT mail_id FROM mail_near WHERE group_id IS NULL LIMIT 1")
    detail = await get(near_client, f"/api/mails/{single.mail_id}")
    assert (detail["near_group"], detail["near"], detail["near_size"]) == (None, [], 0)


async def test_the_csv_and_the_timeline_take_collapse_near(
    near_client: httpx.AsyncClient, near_database_url: str
) -> None:
    params = [("collapse_near", "true")]
    exported = await export(near_client, [*params, ("sort", "date_asc")])
    expected = await collapsed(near_database_url, "true", "date_asc")
    assert [int(row[0]) for row in exported] == expected
    timeline = await get(near_client, "/api/timeline", params)
    dated = set(await ids(near_database_url, "date_utc IS NOT NULL"))
    assert timeline["total"]["total"] == len([m for m in expected if m in dated])

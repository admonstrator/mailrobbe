"""The research file's writes and views (D53 to D61): tags, Akten, saved searches, marks,
links, bulk changes, permalinks, the overview's starter set and the themes.

Writes go to a copy of the imported archive per test (mutable_client). The research filters,
the list items' research fields and the overview's counts are in test_research_filters.py,
notes in test_research_notes.py.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import pool, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api import research
from mailrobbe.api.deps import EDITOR_HEADER
from mailrobbe.api.schemas import COLLECTION_PERSONS, PERMALINK_DIGITS
from mailrobbe.db.models import Mail
from mailrobbe.themes import load_themes
from tests.api.conftest import _client, api_settings
from tests.api.test_mails import rows
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

ANNA = {EDITOR_HEADER: "Anna%20M%C3%BCller"}  # percent-encoded, as the web UI sends it


async def call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: Any = None,
    status: int = 200,
    editor: dict[str, str] | None = ANNA,
) -> Any:
    response = await client.request(method, path, json=body, headers=editor or {})
    assert response.status_code == status, response.text
    return response.json() if response.content else None


async def error(
    client: httpx.AsyncClient, method: str, path: str, body: Any, status: int, code: str
) -> str:
    """The message of an expected API error."""
    detail = (await call(client, method, path, body, status))["detail"]
    assert detail["code"] == code, detail
    return str(detail["message"])


async def copies(url: str) -> list[list[int]]:
    """Ids of byte-identical mails, one list per content with more than one mail."""
    found = await rows(
        url,
        "SELECT array_agg(id ORDER BY id) AS ids FROM mail GROUP BY raw_sha256"
        " HAVING count(*) > 1 ORDER BY min(id)",
    )
    assert found
    return [row.ids for row in found]


async def single_mails(url: str, count: int) -> list[int]:
    """Ids of mails whose content is in no other mail, oldest id first."""
    found = await rows(
        url,
        "SELECT min(id) AS id FROM mail GROUP BY raw_sha256 HAVING count(*) = 1"
        " ORDER BY 1 LIMIT :count",
        count=count,
    )
    return [row.id for row in found]


async def research_of(client: httpx.AsyncClient, mail_id: int) -> Any:
    return (await call(client, "GET", f"/api/mails/{mail_id}"))["research"]


@pytest.fixture
async def anonymous(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """A second client on the same copy as mutable_client."""
    settings = api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


# Tags -----------------------------------------------------------------------------------------


async def test_tags_are_created_changed_and_deleted(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    http = mutable_client
    tag = await call(http, "POST", "/api/tags", {"name": "  Vertrag  ", "color": "red"}, 201)
    assert (tag["name"], tag["color"], tag["description"], tag["mails"]) == (
        "Vertrag",
        "red",
        "",
        0,
    )
    assert tag["created_by"] == "Anna Müller"
    nameless = await call(http, "POST", "/api/tags", {"name": "Spende"}, 201, editor={})
    assert (nameless["created_by"], nameless["color"]) == (None, "blue")

    for name in ("vertrag", " VERTRAG"):
        message = await error(http, "POST", "/api/tags", {"name": name}, 409, "duplicate_name")
        assert f"named {name.strip()!r} exists already" in message
    await error(
        http, "PATCH", f"/api/tags/{nameless['id']}", {"name": "VERTRAG"}, 409, "duplicate_name"
    )
    for body in ({"name": "   "}, {"name": ""}, {"color": "purple"}, {"name": "x" * 61}):
        await call(http, "POST", "/api/tags", body, 422)
    await call(http, "PATCH", f"/api/tags/{tag['id']}", {"name": " \t"}, 422)

    mail_id = (await single_mails(mutable_database_url, 1))[0]
    await call(http, "POST", f"/api/mails/{mail_id}/tags", {"add": [tag["id"]]})
    # Only the fields sent change; the own name in another case is no conflict.
    changed = await call(http, "PATCH", f"/api/tags/{tag['id']}", {"name": "VERTRAG"})
    assert (changed["name"], changed["color"], changed["mails"]) == ("VERTRAG", "red", 1)
    changed = await call(
        http, "PATCH", f"/api/tags/{tag['id']}", {"color": "teal", "description": "Verträge"}
    )
    assert (changed["name"], changed["color"], changed["description"]) == (
        "VERTRAG",
        "teal",
        "Verträge",
    )
    assert changed["created_at"] == tag["created_at"]

    await call(http, "DELETE", f"/api/tags/{tag['id']}", status=204)
    assert (await research_of(http, mail_id))["tags"] == []
    await error(http, "PATCH", f"/api/tags/{tag['id']}", {"name": "x"}, 404, "not_found")
    await error(http, "DELETE", f"/api/tags/{tag['id']}", None, 404, "not_found")
    await call(http, "DELETE", f"/api/tags/{2**63}", status=422)
    overview = await call(http, "GET", "/api/research")
    assert [t["name"] for t in overview["tags"]] == ["Spende"]


# Akten ----------------------------------------------------------------------------------------


async def test_akten_and_their_detail(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    http, url = mutable_client, mutable_database_url
    akte = await call(http, "POST", "/api/collections", {"name": " Akte Nord "}, 201)
    assert (akte["name"], akte["description"], akte["mails"]) == ("Akte Nord", "", 0)
    assert akte["created_by"] == "Anna Müller"
    assert akte["updated_at"] == akte["created_at"]
    await error(http, "POST", "/api/collections", {"name": "akte nord"}, 409, "duplicate_name")
    other = await call(http, "POST", "/api/collections", {"name": "Akte Süd"}, 201, editor={})
    assert other["created_by"] is None
    await error(
        http,
        "PATCH",
        f"/api/collections/{other['id']}",
        {"name": "AKTE NORD"},
        409,
        "duplicate_name",
    )

    # Members: a few single mails, a pair of byte-identical copies, a content not in the archive.
    singles = await single_mails(url, 4)
    pair = (await copies(url))[0]
    members = [*singles, pair[0]]
    for mail_id in members:
        await call(http, "POST", f"/api/mails/{mail_id}/collections", {"add": [akte["id"]]})
    await rows(
        url,
        "INSERT INTO collection_mail (collection_id, mail_sha256) VALUES (:id, :sha)",
        id=akte["id"],
        sha="e" * 64,
    )
    detail = await call(http, "GET", f"/api/collections/{akte['id']}")
    in_akte = [*singles, *pair]
    figures = (
        await rows(
            url,
            "SELECT min(date_utc) AS date_min, max(date_utc) AS date_max FROM mail"
            " WHERE id = ANY(:ids)",
            ids=in_akte,
        )
    )[0]
    assert detail["mails"] == len(in_akte)
    assert detail["missing"] == 1
    assert (detail["date_min"], detail["date_max"]) == (
        _iso(figures.date_min),
        _iso(figures.date_max),
    )
    expected = await rows(
        url,
        "SELECT coalesce(p.merged_into, p.id) AS root, count(DISTINCT pa.mail_id) AS mails"
        " FROM participation pa JOIN person p ON p.id = pa.person_id"
        " WHERE pa.mail_id = ANY(:ids) GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT :limit",
        ids=in_akte,
        limit=COLLECTION_PERSONS,
    )
    assert [(p["person"]["person_id"], p["mails"]) for p in detail["persons"]] == [
        (row.root, row.mails) for row in expected
    ]
    assert all(p["person"]["email"] for p in detail["persons"])
    assert _at(detail["updated_at"]) > _at(akte["updated_at"])

    # Saved searches of the Akte, by name; deleting the Akte keeps them, without it.
    for name in ("b Suche", "A Suche"):
        body = {"name": name, "query": "q=Vertrag", "collection_id": akte["id"]}
        await call(http, "POST", "/api/searches", body, 201)
    detail = await call(http, "GET", f"/api/collections/{akte['id']}")
    assert [s["name"] for s in detail["searches"]] == ["A Suche", "b Suche"]

    # updated_at moves on every change of fields or members, not on a change to nothing.
    stamps = [_at(detail["updated_at"])]
    for method, path, body in (
        ("PATCH", f"/api/collections/{akte['id']}", {"description": "Nordseite"}),
        ("PATCH", f"/api/collections/{akte['id']}", {"name": "Akte Nord 2"}),
        ("POST", f"/api/mails/{singles[0]}/collections", {"remove": [akte["id"]]}),
        (
            "POST",
            "/api/mails/bulk",
            {"ids": singles[:2], "action": "collection_add", "collection_id": akte["id"]},
        ),
    ):
        await call(http, method, path, body)
        stamps.append(
            _at((await call(http, "GET", f"/api/collections/{akte['id']}"))["updated_at"])
        )
    assert stamps == sorted(set(stamps))
    unchanged = await call(http, "PATCH", f"/api/collections/{akte['id']}", {"name": "Akte Nord 2"})
    assert _at(unchanged["updated_at"]) == stamps[-1]
    await call(http, "POST", f"/api/mails/{singles[1]}/collections", {"add": [akte["id"]]})
    assert (
        _at((await call(http, "GET", f"/api/collections/{akte['id']}"))["updated_at"]) == stamps[-1]
    )

    overview = await call(http, "GET", "/api/research")
    assert [c["name"] for c in overview["collections"]] == ["Akte Nord 2", "Akte Süd"]
    assert overview["collections"][0]["mails"] == len(in_akte)

    await call(http, "DELETE", f"/api/collections/{akte['id']}", status=204)
    searches = (await call(http, "GET", "/api/research"))["searches"]
    assert [(s["name"], s["collection_id"]) for s in searches] == [
        ("A Suche", None),
        ("b Suche", None),
    ]
    assert (await research_of(http, singles[1]))["collections"] == []
    for method, path in (("GET", ""), ("PATCH", ""), ("DELETE", "")):
        await error(
            http,
            method,
            f"/api/collections/{akte['id']}{path}",
            {} if method == "PATCH" else None,
            404,
            "not_found",
        )


async def test_an_empty_akte(mutable_client: httpx.AsyncClient) -> None:
    akte = await call(mutable_client, "POST", "/api/collections", {"name": "Leer"}, 201)
    detail = await call(mutable_client, "GET", f"/api/collections/{akte['id']}")
    assert (detail["mails"], detail["missing"], detail["date_min"], detail["date_max"]) == (
        0,
        0,
        None,
        None,
    )
    assert (detail["persons"], detail["searches"]) == ([], [])


# Saved searches -------------------------------------------------------------------------------


async def test_saved_searches(mutable_client: httpx.AsyncClient) -> None:
    http = mutable_client
    akte = await call(http, "POST", "/api/collections", {"name": "Akte"}, 201)
    await error(
        http, "POST", "/api/searches", {"name": "S", "collection_id": 987654}, 404, "not_found"
    )
    search = await call(
        http,
        "POST",
        "/api/searches",
        {"name": " Spenden ", "query": "q=Spende", "collection_id": akte["id"]},
        201,
    )
    assert (search["name"], search["query"], search["collection_id"], search["created_by"]) == (
        "Spenden",
        "q=Spende",
        akte["id"],
        "Anna Müller",
    )
    plain = await call(http, "POST", "/api/searches", {"name": "Alles"}, 201, editor={})
    assert (plain["query"], plain["collection_id"], plain["created_by"]) == ("", None, None)
    await error(http, "POST", "/api/searches", {"name": "SPENDEN"}, 409, "duplicate_name")
    await error(
        http, "PATCH", f"/api/searches/{plain['id']}", {"name": "spenden"}, 409, "duplicate_name"
    )
    await call(http, "POST", "/api/searches", {"name": "  "}, 422)

    path = f"/api/searches/{search['id']}"
    changed = await call(http, "PATCH", path, {"query": "q=Barspende"})
    assert (changed["name"], changed["query"], changed["collection_id"]) == (
        "Spenden",
        "q=Barspende",
        akte["id"],
    )
    assert _at(changed["updated_at"]) > _at(search["updated_at"])
    await error(http, "PATCH", path, {"collection_id": 987654}, 404, "not_found")
    detached = await call(http, "PATCH", path, {"collection_id": None})
    assert detached["collection_id"] is None
    attached = await call(http, "PATCH", path, {"collection_id": akte["id"]})
    assert attached["collection_id"] == akte["id"]

    overview = await call(http, "GET", "/api/research")
    assert [s["name"] for s in overview["searches"]] == ["Alles", "Spenden"]
    await call(http, "DELETE", path, status=204)
    await error(http, "DELETE", path, None, 404, "not_found")
    await error(http, "PATCH", path, {"name": "x"}, 404, "not_found")


# Marks ----------------------------------------------------------------------------------------


async def test_marks_keep_what_is_left_out_and_are_shared_by_copies(
    mutable_client: httpx.AsyncClient, anonymous: httpx.AsyncClient, mutable_database_url: str
) -> None:
    http = mutable_client
    first, second = (await copies(mutable_database_url))[0][:2]
    path = f"/api/mails/{first}/mark"
    flagged = await call(http, "PUT", path, {"flagged": True})
    assert (flagged["flagged"], flagged["flagged_by"], flagged["review"]) == (
        True,
        "Anna Müller",
        None,
    )
    assert flagged["flagged_at"] is not None and flagged["review_at"] is None

    reviewed = await call(anonymous, "PUT", path, {"review": "relevant"}, editor={})
    assert reviewed["flagged"] and reviewed["flagged_by"] == "Anna Müller"
    assert reviewed["flagged_at"] == flagged["flagged_at"]
    assert (reviewed["review"], reviewed["review_by"]) == ("relevant", None)
    assert reviewed["review_at"] is not None

    # The same value again changes nothing, a new one records who and when.
    again = await call(http, "PUT", path, {"review": "relevant", "flagged": True})
    assert again == reviewed
    seen = await call(http, "PUT", path, {"review": "seen"})
    assert (seen["review"], seen["review_by"]) == ("seen", "Anna Müller")
    assert _at(seen["review_at"]) > _at(reviewed["review_at"])
    assert (await research_of(http, second))["mark"] == seen
    page = await call(http, "GET", "/api/mails?review=seen")
    assert {first, second} <= {item["id"] for item in page["items"]}

    unreviewed = await call(http, "PUT", f"/api/mails/{second}/mark", {"review": None})
    assert (unreviewed["review"], unreviewed["review_by"], unreviewed["review_at"]) == (
        None,
        None,
        None,
    )
    assert unreviewed["flagged"]
    nothing = await call(http, "PUT", path, {"flagged": False})
    assert nothing == {
        "flagged": False,
        "flagged_by": None,
        "flagged_at": None,
        "review": None,
        "review_by": None,
        "review_at": None,
    }
    assert await call(http, "PUT", path, {}) == nothing
    marks = await rows(mutable_database_url, "SELECT count(*) AS n FROM mail_mark")
    assert marks[0].n == 0  # a mark holding nothing is no row

    await call(http, "PUT", path, {"review": "maybe"}, 422)
    await error(http, "PUT", "/api/mails/987654321/mark", {"flagged": True}, 404, "not_found")


# Links ----------------------------------------------------------------------------------------


async def test_links_add_and_remove_tags_and_akten(
    mutable_client: httpx.AsyncClient, anonymous: httpx.AsyncClient, mutable_database_url: str
) -> None:
    http, url = mutable_client, mutable_database_url
    tags = [
        (await call(http, "POST", "/api/tags", {"name": name}, 201))["id"]
        for name in ("zeta", "Alpha", "beta")
    ]
    first, second = (await copies(url))[0][:2]
    path = f"/api/mails/{first}/tags"
    shown = await call(http, "POST", path, {"add": tags})
    assert [t["name"] for t in shown] == ["Alpha", "beta", "zeta"]
    assert await call(anonymous, "POST", path, {"add": tags[:1]}, editor={}) == shown  # idempotent
    added = await rows(url, "SELECT added_by FROM mail_tag WHERE tag_id = :id", id=tags[0])
    assert [row.added_by for row in added] == ["Anna Müller"]

    # Unknown ids change nothing, also next to known ones.
    for body in (
        {"add": [987654]},
        {"remove": [tags[0], 987654]},
        {"add": [tags[0]], "remove": [987654]},
    ):
        await error(http, "POST", path, body, 404, "not_found")
    assert await call(http, "POST", path, {}) == shown
    # Add and remove in one call; an id in both ends up removed.
    after = await call(
        http, "POST", f"/api/mails/{second}/tags", {"add": [tags[1]], "remove": [tags[1], tags[2]]}
    )
    assert [t["name"] for t in after] == ["zeta"]
    assert [t["name"] for t in (await research_of(http, first))["tags"]] == ["zeta"]
    assert await call(http, "POST", path, {"remove": [tags[1]]}) == after

    akten = [
        (await call(http, "POST", "/api/collections", {"name": name}, 201))["id"]
        for name in ("Nord", "akte Süd")
    ]
    path = f"/api/mails/{first}/collections"
    refs = await call(anonymous, "POST", path, {"add": akten}, editor={})
    assert refs == [{"id": akten[1], "name": "akte Süd"}, {"id": akten[0], "name": "Nord"}]
    added = await rows(url, "SELECT added_by FROM collection_mail")
    assert [row.added_by for row in added] == [None, None]
    await error(http, "POST", path, {"add": [987654]}, 404, "not_found")
    assert await call(http, "POST", path, {"remove": [akten[0]]}) == refs[:1]
    assert (await research_of(http, second))["collections"] == refs[:1]
    for kind in ("tags", "collections"):
        await error(http, "POST", f"/api/mails/987654321/{kind}", {"add": []}, 404, "not_found")


# Bulk changes ---------------------------------------------------------------------------------


async def test_bulk_changes_by_ids_and_by_filters(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    http, url = mutable_client, mutable_database_url
    tag = (await call(http, "POST", "/api/tags", {"name": "Prüfen"}, 201))["id"]
    akte = (await call(http, "POST", "/api/collections", {"name": "Akte"}, 201))["id"]
    pair = (await copies(url))[0][:2]
    singles = await single_mails(url, 3)

    def bulk(**body: Any) -> dict[str, Any]:
        return {"ids": [*pair, *singles], **body}

    result = await call(http, "POST", "/api/mails/bulk", bulk(action="tag_add", tag_id=tag))
    assert result == {"mails": 5, "changed": 4}  # byte-identical copies are one content
    assert await call(http, "POST", "/api/mails/bulk", bulk(action="tag_add", tag_id=tag)) == {
        "mails": 5,
        "changed": 0,
    }
    tagged = await call(http, "GET", f"/api/mails?tag={tag}&limit=200")
    assert sorted(item["id"] for item in tagged["items"]) == sorted([*pair, *singles])

    # By filters: exactly the mails the list shows.
    by_tag = {"filters": {"tag": [tag]}}
    assert await call(
        http, "POST", "/api/mails/bulk", {**by_tag, "action": "review", "review": "relevant"}
    ) == {
        "mails": 5,
        "changed": 4,
    }
    assert await call(
        http, "POST", "/api/mails/bulk", {**by_tag, "action": "flag", "flagged": True}
    ) == {
        "mails": 5,
        "changed": 4,
    }
    marks = await rows(url, "SELECT review::text, review_by, flagged_by FROM mail_mark")
    assert {(m.review, m.review_by, m.flagged_by) for m in marks} == {
        ("relevant", "Anna Müller", "Anna Müller")
    }
    assert await call(
        http,
        "POST",
        "/api/mails/bulk",
        {**by_tag, "action": "collection_add", "collection_id": akte},
    ) == {"mails": 5, "changed": 4}
    assert (await call(http, "GET", f"/api/collections/{akte}"))["mails"] == 5
    reviewed = {"filters": {"review": ["relevant"], "collection": [akte]}}
    assert await call(
        http, "POST", "/api/mails/bulk", {**reviewed, "action": "review", "review": None}
    ) == {
        "mails": 5,
        "changed": 4,
    }
    assert await call(http, "POST", "/api/mails/bulk", bulk(action="flag", flagged=False)) == {
        "mails": 5,
        "changed": 4,
    }
    assert (await rows(url, "SELECT count(*) AS n FROM mail_mark"))[0].n == 0
    assert await call(
        http, "POST", "/api/mails/bulk", bulk(action="collection_remove", collection_id=akte)
    ) == {
        "mails": 5,
        "changed": 4,
    }
    assert await call(
        http, "POST", "/api/mails/bulk", {**by_tag, "action": "tag_remove", "tag_id": tag}
    ) == {
        "mails": 5,
        "changed": 4,
    }
    overview = await call(http, "GET", "/api/research")
    assert (overview["tags"][0]["mails"], overview["collections"][0]["mails"]) == (0, 0)


async def test_bulk_errors(
    mutable_client: httpx.AsyncClient, mutable_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    http = mutable_client
    tag = (await call(http, "POST", "/api/tags", {"name": "T"}, 201))["id"]
    ids = await single_mails(mutable_database_url, 3)
    for body in (
        {"ids": ids, "action": "tag_add"},
        {"ids": ids, "action": "collection_remove"},
        {"ids": ids, "action": "flag"},
        {"ids": ids, "action": "flag", "flagged": None},
        {"ids": ids, "action": "review"},
        {"ids": ids, "filters": {}, "action": "tag_add", "tag_id": tag},
        {"action": "tag_add", "tag_id": tag},
    ):
        await error(http, "POST", "/api/mails/bulk", body, 400, "invalid_selection")
    await error(
        http,
        "POST",
        "/api/mails/bulk",
        {"ids": ids, "action": "tag_add", "tag_id": 987654},
        404,
        "not_found",
    )
    await error(
        http,
        "POST",
        "/api/mails/bulk",
        {"ids": ids, "action": "collection_add", "collection_id": 987654},
        404,
        "not_found",
    )
    await error(
        http,
        "POST",
        "/api/mails/bulk",
        {"ids": [*ids, 987654321], "action": "flag", "flagged": True},
        404,
        "not_found",
    )
    await error(
        http,
        "POST",
        "/api/mails/bulk",
        {"filters": {"tag": [tag]}, "action": "flag", "flagged": True},
        400,
        "empty_selection",
    )
    await error(
        http,
        "POST",
        "/api/mails/bulk",
        {"filters": {"q": "dkim:maybe"}, "action": "flag", "flagged": True},
        400,
        "invalid_query",
    )
    await call(http, "POST", "/api/mails/bulk", {"ids": ids, "action": "rename"}, 422)
    monkeypatch.setattr(research, "BULK_LIMIT", 2)
    message = await error(
        http,
        "POST",
        "/api/mails/bulk",
        {"ids": ids, "action": "tag_add", "tag_id": tag},
        400,
        "too_many_mails",
    )
    assert "2" in message
    await error(
        http,
        "POST",
        "/api/mails/bulk",
        {"filters": {}, "action": "flag", "flagged": True},
        400,
        "too_many_mails",
    )
    assert (await call(http, "GET", "/api/research"))["tags"][0]["mails"] == 0  # nothing changed


# Permalinks -----------------------------------------------------------------------------------


async def test_permalinks(mutable_client: httpx.AsyncClient, mutable_database_url: str) -> None:
    http, url = mutable_client, mutable_database_url
    pair = (await copies(url))[0]
    sha = (await rows(url, "SELECT raw_sha256 FROM mail WHERE id = :id", id=pair[0]))[0].raw_sha256
    duplicates = await rows(
        url,
        "SELECT id FROM mail WHERE raw_sha256 = :sha AND is_duplicate_of IS NULL ORDER BY id",
        sha=sha,
    )
    original = duplicates[0].id if duplicates else pair[0]
    for prefix in (sha[:PERMALINK_DIGITS], sha[:12], sha, sha[:20].upper()):
        target = await call(http, "GET", f"/api/permalink/{prefix}")
        assert target == {"mail_id": original, "raw_sha256": sha}
    for prefix in (sha[:11], sha + "0", "g" * 16, "0x" + sha[:14]):
        message = await error(http, "GET", f"/api/permalink/{prefix}", None, 404, "not_found")
        assert "12 to 64 hex digits" in message
    await error(http, "GET", "/api/permalink/" + "0" * 64, None, 404, "not_found")

    # Two contents sharing 14 digits: ambiguous with 12 to 14, unique from 15 on.
    single = (await single_mails(url, 1))[0]
    twin = sha[:14] + ("0" if sha[14] != "0" else "1") + sha[15:]
    await rows(url, "UPDATE mail SET raw_sha256 = :twin WHERE id = :id", twin=twin, id=single)
    for prefix in (sha[:12], sha[:14]):
        await error(http, "GET", f"/api/permalink/{prefix}", None, 409, "ambiguous_permalink")
    assert (await call(http, "GET", f"/api/permalink/{sha[:15]}"))["mail_id"] == original
    assert (await call(http, "GET", f"/api/permalink/{twin[:15]}"))["mail_id"] == single
    # The last prefix before the end of the hex range has no upper bound.
    await rows(url, "UPDATE mail SET raw_sha256 = :top WHERE id = :id", top="f" * 64, id=single)
    assert (await call(http, "GET", "/api/permalink/" + "f" * 12))["mail_id"] == single


async def test_permalinks_are_a_range_of_the_sha256_index(mutable_database_url: str) -> None:
    """Under any collation: LIKE 'prefix%' would scan the table outside the C collation."""
    statement = select(Mail.id).where(*research._starting_with("0123456789ab"))
    engine = create_async_engine(mutable_database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            literal = {"literal_binds": True}
            sql = str(statement.compile(dialect=connection.dialect, compile_kwargs=literal))
            await connection.execute(text("SET enable_seqscan = off"))
            await connection.execute(text("SET enable_bitmapscan = off"))
            plan = "\n".join(row[0] for row in await connection.execute(text(f"EXPLAIN {sql}")))
    finally:
        await engine.dispose()
    assert "Index Scan using ix_mail_raw_sha256" in plan, plan
    bounds = "Index Cond: ((raw_sha256 >= '0123456789ab'::text) AND (raw_sha256 < '0123456789ac'"
    assert bounds in plan, plan


# Overview, themes and starter set --------------------------------------------------------------


async def test_the_overview_of_an_empty_research_file(mutable_client: httpx.AsyncClient) -> None:
    overview = await call(mutable_client, "GET", "/api/research")
    mails = (await call(mutable_client, "GET", "/api/stats"))["mails"]
    assert overview["review"] == {"unreviewed": mails, "seen": 0, "relevant": 0, "irrelevant": 0}
    assert (overview["tags"], overview["collections"], overview["searches"]) == ([], [], [])
    assert (overview["flagged"], overview["notes"]) == (0, 0)
    themes = load_themes()
    assert overview["starter_missing"] == len(themes) + sum(len(t.searches) for t in themes)


async def test_themes_are_listed(mutable_client: httpx.AsyncClient) -> None:
    listed = await call(mutable_client, "GET", "/api/research/themes")
    assert [(t["key"], t["name"], t["color"], len(t["terms"])) for t in listed] == [
        (t.key, t.name, t.color, len(t.terms)) for t in load_themes()
    ]
    assert listed[0]["searches"][0] == {
        "name": load_themes()[0].searches[0].name,
        "query": load_themes()[0].searches[0].query,
    }


async def test_the_starter_set_is_created_once(mutable_client: httpx.AsyncClient) -> None:
    http = mutable_client
    themes = load_themes()
    # A tag and a search of the set exist already, in another case: they stay as they are.
    kept = await call(
        http, "POST", "/api/tags", {"name": themes[0].name.upper(), "color": "gray"}, 201
    )
    search = themes[1].searches[0]
    await call(
        http, "POST", "/api/searches", {"name": search.name.lower(), "query": "q=eigen"}, 201
    )
    overview = await call(http, "POST", "/api/research/starter")
    assert overview["starter_missing"] == 0
    tags = {t["name"]: t for t in overview["tags"]}
    assert len(tags) == len(themes)
    assert tags[themes[0].name.upper()] == {**kept, "mails": 0}
    for theme in themes[1:]:
        tag = tags[theme.name]
        assert (tag["color"], tag["description"], tag["created_by"], tag["mails"]) == (
            theme.color,
            theme.description,
            "Anna Müller",
            0,
        )
    searches = {s["name"]: s for s in overview["searches"]}
    assert len(searches) == sum(len(t.searches) for t in themes)
    assert searches[search.name.lower()]["query"] == "q=eigen"
    for theme in themes:
        for each in theme.searches[1:] if theme is themes[1] else theme.searches:
            found = searches[each.name]
            assert (found["query"], found["collection_id"]) == (each.query, None)
    again = await call(http, "POST", "/api/research/starter", editor={})
    assert again == overview


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)

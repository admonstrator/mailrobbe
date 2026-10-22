"""Hide rules over HTTP (D221 to D223): the routes with their validation and editor, the mails a
saved rule hides against SQL, the list and its summary with and without include_hidden, D203's
keeping at once after a note, an Akte, a bookmark or "relevant", the mail detail, the preview and
the suggestions.

Expected results come from SQL written independently of hiding/model.py, on the generated
archive, which has mailing lists and automated senders (D39). Writes go to a copy per test.
"""

from datetime import datetime
from typing import Any

import httpx
import pytest

from mailrobbe.api.deps import EDITOR_HEADER
from mailrobbe.api.schemas import HIDE_EXAMPLES, HIDE_SUGGESTIONS
from tests.api.test_mails import get, ids, listed, pages, rows
from tests.api.test_research import call, error

pytestmark = pytest.mark.db

RULES = "/api/hide-rules"
BERT = {EDITOR_HEADER: "Bert"}
# D203: the content is in an Akte, has a note, is bookmarked or "relevant" (SQL on mail).
KEPT = (
    "(raw_sha256 IN (SELECT mail_sha256 FROM collection_mail)"
    " OR raw_sha256 IN (SELECT mail_sha256 FROM note)"
    " OR raw_sha256 IN (SELECT mail_sha256 FROM mail_mark WHERE flagged OR review = 'relevant'))"
)
SENT_BY = (
    "EXISTS (SELECT 1 FROM participation pa JOIN person p ON p.id = pa.person_id"
    " WHERE pa.mail_id = mail.id AND pa.role = 'from' AND {person})"
)
WITH_TERMS = (
    "EXISTS (SELECT 1 FROM mail_signal s WHERE s.mail_id = mail.id AND s.signal LIKE 'term:%')"
)


async def largest_lists(url: str) -> list[str]:
    found = await rows(
        url,
        "SELECT list_id FROM mail WHERE list_id IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC, 1",
    )
    assert len(found) >= 2, "the generated archive has mailing lists"
    return [row.list_id for row in found]


async def busiest_senders(url: str) -> list[Any]:
    """Persons by the mails they sent, most first: id, address, domain."""
    return await rows(
        url,
        "SELECT p.id, p.canonical_email AS email, p.domain FROM participation pa"
        " JOIN person p ON p.id = pa.person_id WHERE pa.role = 'from'"
        " GROUP BY p.id ORDER BY count(*) DESC, p.id LIMIT 3",
    )


async def count(url: str, where: str, **params: Any) -> int:
    return len(await ids(url, where, **params))


async def rule_mails(url: str) -> dict[int, set[int]]:
    found: dict[int, set[int]] = {}
    for row in await rows(url, "SELECT rule_id, mail_id FROM mail_hidden"):
        found.setdefault(row.rule_id, set()).add(row.mail_id)
    return found


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


# Routes ---------------------------------------------------------------------------------------


async def test_rules_are_created_listed_changed_and_deleted(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    assert await call(mutable_client, "GET", RULES) == {"rules": [], "hidden": 0, "kept": 0}
    list_id = (await largest_lists(url))[0]
    on_list = set(await ids(url, "list_id = :l", l=list_id))
    automated = set(await ids(url, "automated"))
    assert on_list and automated

    body = {
        "name": "  Rundbrief ",
        "list_id": f" <{list_id.upper()}> ",
        "sender": " ",
        "subject": "",
    }
    created = await call(mutable_client, "POST", RULES, body, 201)
    assert {key: created[key] for key in ("name", "sender", "list_id", "subject")} == {
        "name": "Rundbrief",
        "sender": None,
        "list_id": list_id,
        "subject": None,
    }
    assert created["enabled"] is True and created["automated"] is False
    assert (created["created_by"], created["updated_by"]) == ("Anna Müller", "Anna Müller")
    assert created["mails"] == len(on_list) and created["computed_at"] is not None
    assert created["person"] is None and created["subject_match"] == "contains"

    bots = await call(mutable_client, "POST", RULES, {"automated": True}, 201, editor=None)
    assert (bots["created_by"], bots["mails"]) == (None, len(automated))
    assert await rule_mails(url) == {created["id"]: on_list, bots["id"]: automated}
    listing = await call(mutable_client, "GET", RULES)
    assert [rule["id"] for rule in listing["rules"]] == [bots["id"], created["id"]]  # newest first
    assert (listing["hidden"], listing["kept"]) == (len(on_list | automated), 0)

    # disabled: no mails, the criteria kept; the editor of the change, the maker stays
    change = {**body, "enabled": False}
    disabled = await call(mutable_client, "PUT", f"{RULES}/{created['id']}", change, editor=BERT)
    assert (disabled["enabled"], disabled["mails"], disabled["list_id"]) == (False, 0, list_id)
    assert (disabled["created_by"], disabled["updated_by"]) == ("Anna Müller", "Bert")
    assert at(disabled["updated_at"]) > at(created["updated_at"])
    assert disabled["created_at"] == created["created_at"]
    assert await rule_mails(url) == {bots["id"]: automated}
    assert (await call(mutable_client, "GET", RULES))["hidden"] == len(automated)

    # enabled again with other criteria: computed anew
    change = {"list_id": list_id, "subject": "Re:", "subject_match": "starts", "enabled": True}
    changed = await call(mutable_client, "PUT", f"{RULES}/{created['id']}", change)
    replies = set(await ids(url, "list_id = :l AND subject ILIKE 're:%'", l=list_id))
    assert (changed["name"], changed["mails"]) == (None, len(replies))
    assert (await rule_mails(url)).get(created["id"], set()) == replies

    await call(mutable_client, "DELETE", f"{RULES}/{bots['id']}", status=204)
    listing = await call(mutable_client, "GET", RULES)
    assert [rule["id"] for rule in listing["rules"]] == [created["id"]]
    assert listing["hidden"] == len(replies)
    assert set(await rule_mails(url)) <= {created["id"]}  # the deleted rule's rows are gone

    for method in ("PUT", "DELETE"):
        message = await error(mutable_client, method, f"{RULES}/987654321", body, 404, "not_found")
        assert "987654321" in message
    await call(mutable_client, "DELETE", f"{RULES}/x", status=422)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": "Rat"},
        {"sender": "  ", "domain": "", "list_id": "<>", "subject": " "},
        {"automated": False, "subject_match": "starts"},
    ],
)
async def test_a_rule_needs_a_criterion(client: httpx.AsyncClient, body: dict[str, Any]) -> None:
    for method, path in (("POST", RULES), ("POST", f"{RULES}/preview"), ("PUT", f"{RULES}/1")):
        message = await error(client, method, path, body, 400, "invalid_rule")
        assert "at least one criterion" in message
    assert (await call(client, "GET", RULES))["rules"] == []


async def test_a_rule_names_a_person_that_exists(client: httpx.AsyncClient) -> None:
    body = {"person_id": 987654321}
    for path in (RULES, f"{RULES}/preview"):
        message = await error(client, "POST", path, body, 400, "invalid_rule")
        assert "987654321" in message
    await call(client, "POST", RULES, {"subject": "Rat", "subject_match": "regex"}, 422)


async def test_saved_rules_hide_what_sql_selects(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    first, second, third = await busiest_senders(url)
    # an alias: the rule names the merged person, its root's mails count
    await rows(
        url, "UPDATE person SET merged_into = :root WHERE id = :id", root=first.id, id=second.id
    )
    list_id = (await largest_lists(url))[0]
    cases: list[tuple[dict[str, Any], str]] = [
        ({"sender": f" {third.email.upper()} "}, SENT_BY.format(person=f"p.id = {third.id}")),
        ({"person_id": second.id}, SENT_BY.format(person=f"p.id IN ({first.id}, {second.id})")),
        (
            {"domain": f"@{first.domain.upper()}"},
            SENT_BY.format(
                person=f"(p.domain = '{first.domain}' OR p.domain LIKE '%.{first.domain}')"
            ),
        ),
        ({"list_id": list_id}, f"list_id = '{list_id}'"),
        ({"automated": True}, "automated"),
        ({"subject": " RECHNUNG "}, "subject ILIKE '%rechnung%'"),
        ({"subject": "aw:", "subject_match": "starts"}, "subject ILIKE 'aw:%'"),
        ({"subject": "100%"}, "strpos(lower(subject), '100%') > 0"),
        (
            {"domain": first.domain, "subject": "Re:", "subject_match": "starts"},
            SENT_BY.format(person=f"p.domain = '{first.domain}'") + " AND subject ILIKE 're:%'",
        ),
    ]
    sizes = []
    for body, where in cases:
        expected = set(await ids(url, where))
        sizes.append(len(expected))
        rule = await call(mutable_client, "POST", RULES, body, 201)
        assert rule["mails"] == len(expected), body
        assert (await rule_mails(url)).get(rule["id"], set()) == expected, body
        if "person_id" in body:
            assert rule["person"]["person_id"] == second.id
            assert rule["person"]["email"] == second.email
        await call(mutable_client, "DELETE", f"{RULES}/{rule['id']}", status=204)
    assert all(sizes[:7]), sizes  # every criterion alone matches mails of the archive


# Lists, summaries and the detail --------------------------------------------------------------


async def test_lists_leave_hidden_mails_out_and_show_kept_ones_at_once(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    list_id = (await largest_lists(url))[0]
    rule = await call(mutable_client, "POST", RULES, {"list_id": list_id}, 201)
    assert await listed(mutable_client, []) == await ids(
        url, "list_id IS DISTINCT FROM :l", l=list_id
    )
    everything = [("include_hidden", "true")]
    assert await listed(mutable_client, everything) == await ids(url)

    # five mails of the list, each with a content of its own (D53: research data is by content)
    contents = await rows(
        url,
        "SELECT min(id) AS id FROM mail WHERE list_id = :l GROUP BY raw_sha256 ORDER BY 1 LIMIT 5",
        l=list_id,
    )
    noted, filed, flagged, relevant, seen = (row.id for row in contents)
    await call(mutable_client, "POST", f"/api/mails/{noted}/notes", {"body": "Rat"}, 201)
    akte = await call(mutable_client, "POST", "/api/collections", {"name": "Spende"}, 201)
    await call(mutable_client, "POST", f"/api/mails/{filed}/collections", {"add": [akte["id"]]})
    await call(mutable_client, "PUT", f"/api/mails/{flagged}/mark", {"flagged": True})
    await call(mutable_client, "PUT", f"/api/mails/{relevant}/mark", {"review": "relevant"})
    await call(mutable_client, "PUT", f"/api/mails/{seen}/mark", {"review": "seen"})
    hidden_where = f"list_id IS NOT DISTINCT FROM :l AND NOT {KEPT}"  # never NULL
    shown = await ids(url, f"NOT ({hidden_where})", l=list_id)
    assert {noted, filed, flagged, relevant} <= set(shown) and seen not in shown
    assert await listed(mutable_client, []) == shown

    hidden = await count(url, hidden_where, l=list_id)
    kept = await count(url, f"list_id = :l AND {KEPT}", l=list_id)
    listing = await call(mutable_client, "GET", RULES)
    assert (listing["hidden"], listing["kept"]) == (hidden, kept) and kept >= 4

    # the detail: the rule, and whether the mail stays visible
    detail = await call(mutable_client, "GET", f"/api/mails/{noted}")
    assert detail["list_id"] == list_id
    assert detail["hidden"]["kept"] is True
    assert [info["id"] for info in detail["hidden"]["rules"]] == [rule["id"]]
    assert (await call(mutable_client, "GET", f"/api/mails/{seen}"))["hidden"]["kept"] is False
    other = (await ids(url, "list_id IS DISTINCT FROM :l", l=list_id))[0]
    assert (await call(mutable_client, "GET", f"/api/mails/{other}"))["hidden"] is None

    # a disabled rule hides nothing
    await call(
        mutable_client, "PUT", f"{RULES}/{rule['id']}", {"list_id": list_id, "enabled": False}
    )
    assert (await call(mutable_client, "GET", f"/api/mails/{seen}"))["hidden"] is None
    assert await listed(mutable_client, []) == await ids(url)


async def test_summaries_count_the_hidden_mails(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    list_id = (await largest_lists(url))[0]
    archive = await get(mutable_client, "/api/mails/summary")
    assert archive["hidden"] == 0
    await call(mutable_client, "POST", RULES, {"list_id": list_id}, 201)
    await call(mutable_client, "POST", RULES, {"automated": True}, 201)
    on_list = await ids(url, "list_id = :l", l=list_id)
    await call(mutable_client, "POST", f"/api/mails/{on_list[-1]}/notes", {"body": "Rat"}, 201)
    hidden_where = f"(list_id IS NOT DISTINCT FROM :l OR automated) AND NOT {KEPT}"

    async def dkim_counts(where: str) -> dict[str, int]:
        found = await rows(
            url,
            "SELECT COALESCE(dkim_status::text, 'unchecked') AS dkim, count(*) AS n FROM mail"
            f" WHERE {where} GROUP BY 1",
            l=list_id,
        )
        counts = {row.dkim: row.n for row in found}
        return {key: counts.get(key, 0) for key in archive["dkim"]}

    hidden = await count(url, hidden_where, l=list_id)
    assert hidden > 0
    # no filter: the archive's figures less the hidden mails; persons, domains and dates stay
    summary = await get(mutable_client, "/api/mails/summary")
    assert summary == {
        **archive,
        "total": archive["total"] - hidden,
        "dkim": await dkim_counts(f"NOT ({hidden_where})"),
        "hidden": hidden,
    }
    everything = await get(mutable_client, "/api/mails/summary", [("include_hidden", "true")])
    assert everything == {**archive, "hidden": None}

    # a filter: the hidden matches counted beside the others
    passed = "dkim_status = 'pass'"
    summary = await get(mutable_client, "/api/mails/summary", [("dkim", "pass")])
    visible = await count(url, f"{passed} AND NOT ({hidden_where})", l=list_id)
    assert (summary["total"], summary["exact"]) == (visible, True)
    assert summary["dkim"]["pass"] == visible
    assert summary["hidden"] == await count(url, f"{passed} AND {hidden_where}", l=list_id)
    params = [("dkim", "pass"), ("include_hidden", "true")]
    summary = await get(mutable_client, "/api/mails/summary", params)
    assert (summary["total"], summary["hidden"]) == (await count(url, passed), None)


# Preview and suggestions ----------------------------------------------------------------------


async def test_the_preview_shows_what_a_rule_would_hide(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    with_terms = await rows(
        url,
        f"SELECT list_id FROM mail WHERE list_id IS NOT NULL AND {WITH_TERMS}"
        " GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1",
    )
    list_id = with_terms[0].list_id if with_terms else (await largest_lists(url))[0]
    newest = await ids(url, "list_id = :l", l=list_id)
    await call(mutable_client, "POST", f"/api/mails/{newest[0]}/notes", {"body": "Rat"}, 201)
    body = {"list_id": f"<{list_id}>"}
    preview = await call(mutable_client, "POST", f"{RULES}/preview", body)
    assert preview["mails"] == len(newest)
    assert preview["kept"] == await count(url, f"list_id = :l AND {KEPT}", l=list_id) > 0
    assert preview["with_terms"] == await count(url, f"list_id = :l AND {WITH_TERMS}", l=list_id)
    everything = [("include_hidden", "true")]
    examples = preview["examples"]
    assert [item["id"] for item in examples] == newest[:HIDE_EXAMPLES]
    assert examples[0]["notes"] == 1 and examples[0]["sender"] is not None  # as the list shows it
    items = [item for page in await pages(mutable_client, everything) for item in page["items"]]
    assert examples[0] == next(item for item in items if item["id"] == newest[0])

    # nothing written
    assert (await call(mutable_client, "GET", RULES))["rules"] == []
    assert await rule_mails(url) == {}
    nothing = await call(mutable_client, "POST", f"{RULES}/preview", {"subject": "zzzz-nichts"})
    assert nothing == {"mails": 0, "kept": 0, "with_terms": 0, "examples": []}


async def test_suggestions_name_lists_and_automated_senders_no_rule_names(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url

    async def expected(lists: list[str], persons: list[int]) -> list[tuple[Any, ...]]:
        found = [
            ("list", row.list_id, None, row.n)
            for row in await rows(
                url,
                "SELECT list_id, count(*) AS n FROM mail WHERE list_id IS NOT NULL"
                " AND NOT (list_id = ANY(CAST(:lists AS text[])))"
                " GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT :limit",
                lists=lists,
                limit=HIDE_SUGGESTIONS,
            )
        ] + [
            ("sender", None, row.id, row.sent)
            for row in await rows(
                url,
                "SELECT p.id, s.sent FROM person p JOIN person_stats s ON s.person_id = p.id"
                " WHERE p.merged_into IS NULL AND p.kind IN ('list', 'automated') AND s.sent > 0"
                " AND NOT (p.id = ANY(CAST(:persons AS bigint[])))"
                " ORDER BY s.sent DESC, p.id LIMIT :limit",
                persons=persons,
                limit=HIDE_SUGGESTIONS,
            )
        ]
        return sorted(found, key=lambda suggestion: -suggestion[3])

    async def suggested() -> list[tuple[Any, ...]]:
        found = await call(mutable_client, "GET", f"{RULES}/suggestions")
        return [
            (
                item["kind"],
                item["list_id"],
                item["person"] and item["person"]["person_id"],
                item["mails"],
            )
            for item in found
        ]

    before = await suggested()
    assert before == await expected([], [])
    lists = [item for item in before if item[0] == "list"]
    senders = [item for item in before if item[0] == "sender"]
    assert len(lists) >= 2 and len(senders) >= 2, "the generated archive has both (D39)"
    first_list, second_list = lists[0][1], lists[1][1]
    first_sender, second_sender = senders[0][2], senders[1][2]
    (address,) = await rows(
        url, "SELECT canonical_email FROM person WHERE id = :id", id=second_sender
    )

    await call(mutable_client, "POST", RULES, {"list_id": first_list}, 201)
    disabled = await call(mutable_client, "POST", RULES, {"list_id": second_list}, 201)
    change = {"list_id": second_list, "enabled": False}
    await call(mutable_client, "PUT", f"{RULES}/{disabled['id']}", change)
    await call(mutable_client, "POST", RULES, {"person_id": first_sender}, 201)
    await call(mutable_client, "POST", RULES, {"sender": address.canonical_email}, 201)
    after = await suggested()
    assert after == await expected([first_list], [first_sender, second_sender])
    assert any(item[1] == second_list for item in after)  # a disabled rule names nothing

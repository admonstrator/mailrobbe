"""GET /api/mails, its summary, the neighbours of a mail and the CSV export (D19 to D21, D25).

Expected results come from SQL written independently of api/filters.py, or from the manifest.
WALK_ROWS is lowered in some tests, so that the bounded walk runs out and every match is
collected, as for a rare filter in a large archive.
"""

import csv
import io
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api import filters
from mailrobbe.api.mails import CSV_HEADER
from mailrobbe.api.schemas import RECIPIENT_PREVIEW
from mailrobbe.enums import ParticipationRole
from tests.api.conftest import _client, api_settings
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

Params = Sequence[tuple[str, str]]
ORDER = {
    "date_desc": "COALESCE(date_utc, '-infinity') DESC, id DESC",
    "date_asc": "COALESCE(date_utc, '-infinity') ASC, id ASC",
}
SORTS = list(ORDER)
PAGE = 37  # not a divisor of the number of mails, so the last page is short
# A participant matching `person` (SQL on person p) takes part in role `role` (SQL on pa).
TAKES_PART = (
    "EXISTS (SELECT 1 FROM participation pa JOIN person p ON p.id = pa.person_id"
    " WHERE pa.mail_id = mail.id AND {role} AND {person})"
)
SENDER = "pa.role = 'from'"
RECIPIENT = "pa.role IN ('to', 'cc', 'bcc')"


def takes_part(person: str, role: str = "true") -> str:
    return TAKES_PART.format(role=role, person=person)


def in_domain(domain_param: str) -> str:
    return f"(p.domain = :{domain_param} OR p.domain LIKE '%.' || :{domain_param})"


async def rows(url: str, sql: str, **params: Any) -> list[Any]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql), params)
            found = list(result.all()) if result.returns_rows else []
            await connection.commit()
            return found
    finally:
        await engine.dispose()


async def ids(url: str, where: str = "true", sort: str = "date_desc", **params: Any) -> list[int]:
    """Ids of the mails matching an SQL condition, in list order."""
    found = await rows(url, f"SELECT id FROM mail WHERE {where} ORDER BY {ORDER[sort]}", **params)
    return [row.id for row in found]


async def get(client: httpx.AsyncClient, path: str, params: Params = (), status: int = 200) -> Any:
    response = await client.get(path, params=list(params))
    assert response.status_code == status, response.text
    return response.json()


async def pages(client: httpx.AsyncClient, params: Params, limit: int = 200) -> list[Any]:
    """Every page of the list, following next_cursor from the first page."""
    found: list[Any] = []
    cursor = None
    while True:
        page = await get(client, "/api/mails", [*params, ("limit", str(limit)), *at(cursor)])
        assert (page["prev_cursor"] is None) == (cursor is None)
        found.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return found


def at(cursor: str | None) -> Params:
    return [] if cursor is None else [("cursor", cursor)]


def page_ids(page: Any) -> list[int]:
    return [item["id"] for item in page["items"]]


async def listed(client: httpx.AsyncClient, params: Params) -> list[int]:
    return [mail_id for page in await pages(client, params) for mail_id in page_ids(page)]


async def manifest_ids(url: str, archive: GeneratedArchive) -> list[tuple[dict[str, Any], int]]:
    """Each manifest record with the id of its imported mail."""
    found = await rows(
        url,
        "SELECT f.path, m.byte_offset, m.id FROM mail m JOIN mbox_file f ON f.id = m.mbox_file_id",
    )
    by_place = {(row.path, row.byte_offset): row.id for row in found}
    return [(record, by_place[record["file"], record["offset"]]) for record in archive.manifest]


# Paging -------------------------------------------------------------------------------------


@pytest.mark.parametrize("walk_rows", [filters.WALK_ROWS, 7])
@pytest.mark.parametrize("sort", SORTS)
@pytest.mark.parametrize(
    ("params", "where"),
    [
        ([], "true"),
        ([("dkim", "pass"), ("dkim", "no_key")], "dkim_status IN ('pass', 'no_key')"),
        ([("q", "has:attachment")], "has_attachments"),
    ],
    ids=["all", "dkim", "attachments"],
)
async def test_pages_visit_every_mail_once_forward_and_back(
    client: httpx.AsyncClient,
    imported_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    params: Params,
    where: str,
    sort: str,
    walk_rows: int,
) -> None:
    monkeypatch.setattr(filters, "WALK_ROWS", walk_rows)
    params = [*params, ("sort", sort)]
    forward = await pages(client, params, PAGE)
    assert [i for page in forward for i in page_ids(page)] == await ids(
        imported_database_url, where, sort
    )
    assert len(forward) > 2
    assert {len(page["items"]) for page in forward[:-1]} == {PAGE}

    cursor = forward[-1]["prev_cursor"]
    for expected in reversed(forward[:-1]):
        page = await get(client, "/api/mails", [*params, ("limit", str(PAGE)), *at(cursor)])
        assert page_ids(page) == page_ids(expected)
        assert page["next_cursor"] is not None
        cursor = page["prev_cursor"]
    assert cursor is None  # back on the first page


async def test_next_then_prev_returns_the_same_page(client: httpx.AsyncClient) -> None:
    first = await get(client, "/api/mails", [("limit", "10")])
    second = await get(client, "/api/mails", [("limit", "10"), *at(first["next_cursor"])])
    third = await get(client, "/api/mails", [("limit", "10"), *at(second["next_cursor"])])
    back = await get(client, "/api/mails", [("limit", "10"), *at(third["prev_cursor"])])
    assert page_ids(back) == page_ids(second)
    assert back["next_cursor"] == second["next_cursor"]


async def test_unknown_parameters_are_ignored(client: httpx.AsyncClient) -> None:
    plain = await get(client, "/api/mails")
    assert await get(client, "/api/mails", [("colour", "blue")]) == plain


# Filters ------------------------------------------------------------------------------------

STATIC_FILTERS: list[tuple[Params, str]] = [
    ([("dkim", "fail")], "dkim_status = 'fail'"),
    ([("dkim", "pass"), ("dkim", "unsigned")], "dkim_status IN ('pass', 'unsigned')"),
    (
        [("dkim", "unchecked"), ("dkim", "temp_error")],
        "dkim_status IS NULL OR dkim_status = 'temp_error'",
    ),
    ([("q", "DKIM:no_key")], "dkim_status = 'no_key'"),
    ([("has_attachment", "true")], "has_attachments"),
    ([("in_thread", "true")], "thread_id IS NOT NULL"),
    ([("hide_duplicates", "true")], "is_duplicate_of IS NULL"),
    (
        [("date_from", "2016-03-01"), ("date_to", "2019-10-31")],
        "date_utc >= '2016-03-01Z' AND date_utc < '2019-11-01Z'",
    ),
    (
        [("q", "after:1.3.2016 before:2019-11-01")],
        "date_utc >= '2016-03-01Z' AND date_utc < '2019-11-01Z'",
    ),
    ([("q", "before:2014-01-01")], "date_utc < '2014-01-01Z'"),
    ([("q", "subject:re")], "subject ILIKE '%re%'"),
    ([("q", 'subject:"0%"')], "subject ILIKE '%0\\%%'"),
    (
        [("q", "has:attachment dkim:pass"), ("hide_duplicates", "true")],
        "has_attachments AND dkim_status = 'pass' AND is_duplicate_of IS NULL",
    ),
]


@pytest.mark.parametrize("walk_rows", [filters.WALK_ROWS, 7])
@pytest.mark.parametrize(
    ("params", "where"),
    STATIC_FILTERS,
    ids=["&".join(f"{key}={value}" for key, value in params) for params, _ in STATIC_FILTERS],
)
async def test_filters_select_what_sql_selects(
    client: httpx.AsyncClient,
    imported_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    params: Params,
    where: str,
    walk_rows: int,
) -> None:
    monkeypatch.setattr(filters, "WALK_ROWS", walk_rows)
    assert await listed(client, params) == await ids(imported_database_url, where)


async def test_participant_filters_select_what_sql_selects(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    url = imported_database_url

    async def top(role: str) -> Any:
        found = await rows(
            url,
            "SELECT p.id, p.canonical_email, p.domain FROM participation pa"
            " JOIN person p ON p.id = pa.person_id"
            " WHERE pa.role = CAST(:role AS participation_role)"
            " GROUP BY p.id ORDER BY count(*) DESC, p.id LIMIT 1",
            role=role,
        )
        return found[0]

    sender, receiver, copied = await top("from"), await top("to"), await top("cc")
    part = sender.canonical_email.split("@")[0]
    pair = (
        await rows(
            url,
            "SELECT s.person_id AS a, r.person_id AS b FROM participation s"
            " JOIN participation r ON r.mail_id = s.mail_id AND r.role = 'to'"
            " WHERE s.role = 'from' AND r.person_id <> s.person_id"
            " GROUP BY 1, 2 ORDER BY count(*) DESC, 1, 2 LIMIT 1",
        )
    )[0]
    domains = [
        row.domain
        for row in await rows(
            url,
            "SELECT p.domain FROM participation pa JOIN person p ON p.id = pa.person_id"
            " WHERE pa.role = 'from' GROUP BY 1 ORDER BY count(DISTINCT pa.mail_id) DESC, 1"
            " LIMIT 2",
        )
    ]
    word = (
        await rows(
            url,
            "SELECT w FROM (SELECT regexp_split_to_table(lower(subject), '[^a-zäöüß]+') AS w"
            " FROM mail) t WHERE length(w) >= 6 GROUP BY w ORDER BY count(*) DESC, w LIMIT 1",
        )
    )[0].w
    message_id = (
        await rows(
            url,
            "SELECT message_id FROM mail WHERE is_duplicate_of IS NOT NULL"
            " AND message_id ~ '^<[^<>\\s@]+@[^<>\\s]+>$' ORDER BY id LIMIT 1",
        )
    )[0].message_id
    mbox_file = (await rows(url, "SELECT id FROM mbox_file ORDER BY path OFFSET 1 LIMIT 1"))[0].id
    named = (
        "(strpos(lower(p.canonical_email), lower(:part)) > 0"
        " OR strpos(lower(COALESCE(p.display_name, '')), lower(:part)) > 0)"
    )
    pattern = {"part": part}

    cases: list[tuple[str, Params, str, dict[str, Any]]] = [
        ("from", [("q", f"from:{part.upper()}")], takes_part(named, SENDER), pattern),
        (
            "to",
            [("q", f"to:{receiver.canonical_email}")],
            takes_part("p.canonical_email ILIKE :address", "pa.role = 'to'"),
            {"address": receiver.canonical_email},
        ),
        (
            "cc",
            [("q", f"cc:{copied.canonical_email}")],
            takes_part("p.canonical_email ILIKE :address", "pa.role = 'cc'"),
            {"address": copied.canonical_email},
        ),
        (
            "domain",
            [("q", f"domain:@{sender.domain}")],
            takes_part(in_domain("d")),
            {"d": sender.domain},
        ),
        (
            "sender_domain",
            [("sender_domain", domains[0]), ("sender_domain", domains[1].upper())],
            takes_part("p.domain IN (:d0, :d1)", SENDER),
            {"d0": domains[0], "d1": domains[1]},
        ),
        ("person", [("person", str(pair.a))], takes_part("p.id = :a"), {"a": pair.a}),
        (
            "persons",
            [("person", str(pair.a)), ("person", str(pair.b))],
            f"{takes_part('p.id = :a')} AND {takes_part('p.id = :b')}",
            {"a": pair.a, "b": pair.b},
        ),
        (
            "between",
            [("between", str(pair.b)), ("between", str(pair.a))],
            f"({takes_part('p.id = :a', SENDER)} AND {takes_part('p.id = :b', RECIPIENT)})"
            f" OR ({takes_part('p.id = :b', SENDER)} AND {takes_part('p.id = :a', RECIPIENT)})",
            {"a": pair.a, "b": pair.b},
        ),
        ("mbox_file", [("mbox_file", str(mbox_file))], "mbox_file_id = :f", {"f": mbox_file}),
        ("message_id", [("q", message_id)], "message_id = :m", {"m": message_id}),
        ("text", [("q", word)], "tsv @@ websearch_to_tsquery('german', :w)", {"w": word}),
        (
            "phrase",
            [("q", f'"{word}" {word}')],
            "tsv @@ websearch_to_tsquery('german', :w)",
            {"w": word},
        ),
        (
            "combined",
            [("q", f"from:{part} {word}"), ("dkim", "pass"), ("dkim", "no_key")],
            f"{takes_part(named, SENDER)} AND dkim_status IN ('pass', 'no_key')"
            " AND tsv @@ websearch_to_tsquery('german', :w)",
            {**pattern, "w": word},
        ),
    ]
    for name, params, where, values in cases:
        expected = await ids(url, where, **values)
        assert expected, f"{name}: the archive has no such mail"
        assert await listed(client, params) == expected, name


async def test_filters_agree_with_the_manifest(
    client: httpx.AsyncClient, imported_database_url: str, generated_archive: GeneratedArchive
) -> None:
    records = await manifest_ids(imported_database_url, generated_archive)
    failed = {mail_id for record, mail_id in records if record["dkim"]["expected"] == "fail"}
    originals = {mail_id for record, mail_id in records if record["duplicate_of"] is None}
    attached = {mail_id for record, mail_id in records if record["attachments"]}
    assert failed and attached and len(originals) < len(records)

    assert set(await listed(client, [("dkim", "fail")])) == failed
    assert set(await listed(client, [("hide_duplicates", "true")])) == originals
    assert set(await listed(client, [("has_attachment", "true")])) == attached


async def test_external_needs_and_uses_the_internal_domains(
    client: httpx.AsyncClient,
    imported_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
) -> None:
    error = await get(client, "/api/mails", [("external", "true")], status=400)
    assert error["detail"]["code"] == "invalid_filter"

    domain = (
        await rows(
            imported_database_url,
            "SELECT domain FROM person GROUP BY domain ORDER BY count(*) DESC, domain LIMIT 1",
        )
    )[0].domain
    internal, external = in_domain("d"), f"NOT {in_domain('d')}"
    where = (
        f"({takes_part(internal, SENDER)} AND {takes_part(external, RECIPIENT)})"
        f" OR ({takes_part(external, SENDER)} AND {takes_part(internal, RECIPIENT)})"
    )
    expected = await ids(imported_database_url, where, d=domain)
    assert expected

    settings = api_settings(imported_database_url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(update={"internal_domains": f" {domain.upper()} , other.test"})
    async for owner in _client(settings):
        assert await listed(owner, [("external", "true")]) == expected


# List items ---------------------------------------------------------------------------------


async def test_items_show_the_mail_and_its_participants(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    page = await get(client, "/api/mails", [("limit", "200"), ("sort", "date_asc")])
    items = {item["id"]: item for item in page["items"]}
    mails = await rows(
        imported_database_url,
        "SELECT id, date_utc, subject, dkim_status::text AS dkim, has_attachments, thread_id,"
        " is_duplicate_of, byte_length, mbox_file_id FROM mail WHERE id = ANY(:ids)",
        ids=list(items),
    )
    people = await rows(
        imported_database_url,
        "SELECT pa.mail_id, pa.role::text AS role, p.id, p.canonical_email,"
        " COALESCE(pa.display_name, p.display_name) AS name"
        " FROM participation pa JOIN person p ON p.id = pa.person_id WHERE pa.mail_id = ANY(:ids)",
        ids=list(items),
    )
    roles = [role.value for role in ParticipationRole]
    order: dict[int, list[Any]] = {}
    for person in sorted(
        people,
        key=lambda p: (
            roles.index(p.role),
            p.name is None,
            (p.name or "").casefold(),
            p.canonical_email,
        ),
    ):
        order.setdefault(person.mail_id, []).append(person)
    assert any(len(order.get(mail_id, [])) > RECIPIENT_PREVIEW + 1 for mail_id in items)

    def ref(person: Any) -> dict[str, Any]:
        return {"person_id": person.id, "email": person.canonical_email, "name": person.name}

    for mail in mails:
        item = items[mail.id]
        participants = order.get(mail.id, [])
        senders = [p for p in participants if p.role == "from"]
        recipients = [p for p in participants if p.role != "from"]
        assert item == {
            "id": mail.id,
            "date": None
            if mail.date_utc is None
            else mail.date_utc.isoformat().replace("+00:00", "Z"),
            "subject": mail.subject,
            "dkim_status": mail.dkim,
            "has_attachments": mail.has_attachments,
            "sender": ref(senders[0]) if senders else None,
            "recipients": [ref(person) for person in recipients[:RECIPIENT_PREVIEW]],
            "recipient_count": len(recipients),
            "thread_id": mail.thread_id,
            "is_duplicate": mail.is_duplicate_of is not None,
            "flagged": False,
            "size": mail.byte_length,
            "mbox_file_id": mail.mbox_file_id,
            "person_role": None,
        }


async def test_query_terms_are_echoed(client: httpx.AsyncClient) -> None:
    q = 'from:anna  subject:"finale Fassung" Hallo'
    page = await get(client, "/api/mails", [("q", q)])
    assert page["query_terms"] == [
        {"key": "from", "value": "anna", "raw": "from:anna"},
        {"key": "subject", "value": "finale Fassung", "raw": 'subject:"finale Fassung"'},
        {"key": "text", "value": "Hallo", "raw": "Hallo"},
    ]


@pytest.mark.parametrize(
    ("path", "params", "code", "naming"),
    [
        ("/api/mails", [("q", "Hallo has:pdf")], "invalid_query", "has:pdf"),
        ("/api/mails/summary", [("q", "before:2020-13-01")], "invalid_query", "before:2020-13-01"),
        ("/api/mails/export.csv", [("q", "dkim:maybe")], "invalid_query", "dkim:maybe"),
        ("/api/mails", [("between", "1")], "invalid_filter", "between"),
        (
            "/api/mails/summary",
            [("between", "1"), ("between", "2"), ("between", "3")],
            "invalid_filter",
            "between",
        ),
        (
            "/api/mails/1/neighbors",
            [("external", "true")],
            "invalid_filter",
            "MAILROBBE_INTERNAL_DOMAINS",
        ),
        ("/api/mails", [("cursor", "bm90IGEgY3Vyc29y")], "invalid_cursor", "malformed"),
        ("/api/mails", [("cursor", "!!")], "invalid_cursor", "malformed"),
    ],
)
async def test_bad_requests_name_the_problem(
    client: httpx.AsyncClient, path: str, params: Params, code: str, naming: str
) -> None:
    error = await get(client, path, params, status=400)
    assert error["detail"]["code"] == code
    assert naming in error["detail"]["message"]


async def test_a_cursor_is_bound_to_its_sort_order(client: httpx.AsyncClient) -> None:
    page = await get(client, "/api/mails", [("limit", "5")])
    error = await get(
        client, "/api/mails", [("sort", "date_asc"), *at(page["next_cursor"])], status=400
    )
    assert error["detail"]["code"] == "invalid_cursor"


@pytest.mark.parametrize("limit", ["0", "201"])
async def test_page_size_is_bounded(client: httpx.AsyncClient, limit: str) -> None:
    await get(client, "/api/mails", [("limit", limit)], status=422)


# Summary ------------------------------------------------------------------------------------


async def test_unfiltered_summary_is_the_whole_archive(
    client: httpx.AsyncClient, imported_database_url: str, generated_archive: GeneratedArchive
) -> None:
    summary = await get(client, "/api/mails/summary", [("q", "  "), ("sort", "date_asc")])
    expected = Counter(record["dkim"]["expected"] for record in generated_archive.manifest)
    assert summary["total"] == len(generated_archive.manifest)
    assert summary["exact"] is True
    assert summary["dkim"] == {key: expected.get(key, 0) for key in summary["dkim"]}
    assert set(summary["dkim"]) == {"pass", "fail", "no_key", "unsigned", "temp_error", "unchecked"}
    figures = (
        await rows(
            imported_database_url,
            "SELECT (SELECT count(*) FROM person WHERE merged_into IS NULL) AS persons,"
            " (SELECT count(DISTINCT domain) FROM person) AS domains,"
            " min(date_utc) AS date_min, max(date_utc) AS date_max FROM mail",
        )
    )[0]
    assert (summary["persons"], summary["domains"]) == (figures.persons, figures.domains)
    assert summary["date_min"] == figures.date_min.isoformat().replace("+00:00", "Z")
    assert summary["date_max"] == figures.date_max.isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize(
    ("params", "where"),
    [
        ([("dkim", "fail")], "dkim_status = 'fail'"),
        (
            [("q", "has:attachment before:2020-01-01")],
            "has_attachments AND date_utc < '2020-01-01Z'",
        ),
        (
            [("in_thread", "true"), ("dkim", "pass")],
            "thread_id IS NOT NULL AND dkim_status = 'pass'",
        ),
        ([("q", "subject:zzzz-nothing")], "false"),
    ],
)
async def test_filtered_summary_counts_exactly(
    client: httpx.AsyncClient, imported_database_url: str, params: Params, where: str
) -> None:
    summary = await get(client, "/api/mails/summary", params)
    counts = await rows(
        imported_database_url,
        f"SELECT COALESCE(dkim_status::text, 'unchecked') AS dkim, count(*) FROM mail"
        f" WHERE {where} GROUP BY 1",
    )
    figures = (
        await rows(
            imported_database_url,
            f"WITH m AS (SELECT id, date_utc FROM mail WHERE {where}),"
            " people AS (SELECT p.* FROM person p WHERE EXISTS (SELECT 1 FROM participation pa"
            "  JOIN m ON m.id = pa.mail_id WHERE pa.person_id = p.id))"
            " SELECT (SELECT count(*) FROM m) AS total,"
            " (SELECT count(DISTINCT COALESCE(merged_into, id)) FROM people) AS persons,"
            " (SELECT count(DISTINCT domain) FROM people) AS domains,"
            " (SELECT min(date_utc) FROM m) AS date_min, (SELECT max(date_utc) FROM m) AS date_max",
        )
    )[0]

    def stamp(value: Any) -> str | None:
        return None if value is None else value.isoformat().replace("+00:00", "Z")

    assert summary == {
        "total": figures.total,
        "exact": True,
        "dkim": {key: dict(counts).get(key, 0) for key in summary["dkim"]},
        "persons": figures.persons,
        "domains": figures.domains,
        "date_min": stamp(figures.date_min),
        "date_max": stamp(figures.date_max),
    }
    assert len(summary["dkim"]) == 6


async def test_summary_falls_back_when_counting_runs_out_of_time(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    settings = api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(update={"api_count_timeout": 0.3})
    passed = len(await ids(mutable_database_url, "dkim_status = 'pass'"))
    params = [("dkim", "pass")]
    unknown = {"dkim": None, "persons": None, "domains": None, "date_min": None, "date_max": None}
    engine = create_async_engine(mutable_database_url, poolclass=pool.NullPool)
    try:
        async for client in _client(settings):
            async with engine.connect() as other:
                # The aggregate reads participation: it waits, then the bounded count answers.
                await other.execute(text("LOCK TABLE participation IN ACCESS EXCLUSIVE MODE"))
                summary = await get(client, "/api/mails/summary", params)
                assert summary == {"total": passed, "exact": True, **unknown}
                # Now the bounded count waits too.
                await other.execute(text("LOCK TABLE mail IN ACCESS EXCLUSIVE MODE"))
                summary = await get(client, "/api/mails/summary", params)
                assert summary == {"total": None, "exact": False, **unknown}
                await other.rollback()
            summary = await get(client, "/api/mails/summary", params)
            assert summary["exact"] is True
            assert summary["dkim"]["pass"] == summary["total"] == passed
    finally:
        await engine.dispose()


# Neighbours ---------------------------------------------------------------------------------


@pytest.mark.parametrize("walk_rows", [filters.WALK_ROWS, 7])
@pytest.mark.parametrize("sort", SORTS)
async def test_neighbours_agree_with_the_pages(
    client: httpx.AsyncClient,
    imported_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    sort: str,
    walk_rows: int,
) -> None:
    monkeypatch.setattr(filters, "WALK_ROWS", walk_rows)
    params = [("dkim", "pass"), ("dkim", "no_key"), ("sort", sort)]
    found = [i for page in await pages(client, params, PAGE) for i in page_ids(page)]
    edges = {0, len(found) - 1} | {
        k * PAGE + d for k in range(1, len(found) // PAGE + 1) for d in (-1, 0)
    }
    for index in sorted(edge for edge in edges if edge < len(found)):
        neighbours = await get(client, f"/api/mails/{found[index]}/neighbors", params)
        assert neighbours == {
            "prev_id": found[index - 1] if index > 0 else None,
            "next_id": found[index + 1] if index + 1 < len(found) else None,
            "position": index + 1,
        }


async def test_neighbours_of_a_mail_outside_the_list(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    every = await ids(imported_database_url)
    matching = set(await ids(imported_database_url, "dkim_status = 'pass'"))
    outside = next(
        index for index in range(len(every) // 2, len(every)) if every[index] not in matching
    )
    before = [mail_id for mail_id in every[:outside] if mail_id in matching]
    after = [mail_id for mail_id in every[outside + 1 :] if mail_id in matching]
    neighbours = await get(client, f"/api/mails/{every[outside]}/neighbors", [("dkim", "pass")])
    assert neighbours == {"prev_id": before[-1], "next_id": after[0], "position": None}


async def test_neighbours_of_an_unknown_mail(client: httpx.AsyncClient) -> None:
    error = await get(client, "/api/mails/987654321/neighbors", status=404)
    assert error["detail"]["code"] == "not_found"


# CSV export ---------------------------------------------------------------------------------


async def export(client: httpx.AsyncClient, params: Params = ()) -> list[list[str]]:
    response = await client.get("/api/mails/export.csv", params=list(params))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="mailrobbe-mails.csv"'
    assert response.content.startswith(b"\xef\xbb\xbfID;Datum;DKIM;")
    assert response.content.endswith(b"\r\n")
    found = list(
        csv.reader(io.StringIO(response.content.decode("utf-8-sig"), newline=""), delimiter=";")
    )
    assert tuple(found[0]) == CSV_HEADER
    return found[1:]


async def test_csv_holds_the_filtered_list(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    params = [("q", "has:attachment"), ("sort", "date_asc")]
    exported = await export(client, params)
    summary = await get(client, "/api/mails/summary", params)
    assert len(exported) == summary["total"]
    assert [int(row[0]) for row in exported] == await ids(
        imported_database_url, "has_attachments", "date_asc"
    )
    mails = {
        row.id: row
        for row in await rows(
            imported_database_url,
            "SELECT m.id, m.date_utc, COALESCE(m.dkim_status::text, 'unchecked') AS dkim,"
            " m.subject, m.message_id, f.path, m.byte_offset,"
            " ARRAY(SELECT p.canonical_email FROM participation pa JOIN person p ON p.id ="
            "  pa.person_id WHERE pa.mail_id = m.id AND pa.role = 'from') AS senders,"
            " ARRAY(SELECT p.canonical_email FROM participation pa JOIN person p ON p.id ="
            "  pa.person_id WHERE pa.mail_id = m.id AND pa.role <> 'from'"
            "  ORDER BY pa.role, p.canonical_email) AS recipients"
            " FROM mail m JOIN mbox_file f ON f.id = m.mbox_file_id WHERE m.has_attachments",
        )
    }
    for row in exported:
        mail = mails[int(row[0])]
        assert row[1] == ("" if mail.date_utc is None else mail.date_utc.isoformat())
        assert row[2] == mail.dkim
        assert row[4] in mail.senders or (row[4] == "" and not mail.senders)
        assert row[5] == ", ".join(mail.recipients)
        subject = mail.subject or ""
        assert row[6] == ("'" + subject if subject.startswith(("=", "+", "-", "@")) else subject)
        assert row[7:] == ["ja", mail.message_id or "", mail.path, str(mail.byte_offset)]


async def test_csv_of_everything_matches_the_summary(client: httpx.AsyncClient) -> None:
    exported = await export(client)
    summary = await get(client, "/api/mails/summary")
    assert len(exported) == summary["total"]
    assert {row[7] for row in exported} == {"ja", "nein"}


async def test_csv_cells_never_start_a_formula(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    first, second, third = (await ids(mutable_database_url))[:3]
    await rows(
        mutable_database_url,
        "UPDATE mail SET subject = CASE id WHEN :a THEN '=HYPERLINK(\"x\")' WHEN :b THEN"
        " '+49 351' WHEN :c THEN 'Bericht = fertig' END WHERE id IN (:a, :b, :c)",
        a=first,
        b=second,
        c=third,
    )
    exported = {int(row[0]): row for row in await export(mutable_client)}
    assert exported[first][6] == '\'=HYPERLINK("x")'
    assert exported[second][6] == "'+49 351"
    assert exported[third][6] == "Bericht = fertig"


# Filters on data the archive does not have yet ----------------------------------------------


async def test_flagged_filter_and_items(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    flagged, unflagged = (await ids(mutable_database_url))[5:7]
    await rows(
        mutable_database_url,
        "INSERT INTO mail_note (mail_id, flagged, note) VALUES (:a, true, ''), (:b, false, 'x')",
        a=flagged,
        b=unflagged,
    )
    page = await get(mutable_client, "/api/mails", [("flagged", "true")])
    assert page_ids(page) == [flagged]
    assert page["items"][0]["flagged"] is True
    summary = await get(mutable_client, "/api/mails/summary", [("flagged", "true")])
    assert summary["total"] == 1
    items = (await get(mutable_client, "/api/mails", [("limit", "10")]))["items"]
    assert {item["id"]: item["flagged"] for item in items}[unflagged] is False


async def test_person_filter_includes_merged_addresses(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    # a: the busiest address; b: one that also has mails without a
    pair = (
        await rows(
            mutable_database_url,
            "WITH a AS (SELECT person_id FROM participation GROUP BY 1 ORDER BY count(*) DESC, 1"
            " LIMIT 1) SELECT (SELECT person_id FROM a) AS a, p.person_id AS b"
            " FROM participation p WHERE p.person_id <> (SELECT person_id FROM a)"
            " AND NOT EXISTS (SELECT 1 FROM participation x WHERE x.mail_id = p.mail_id"
            "  AND x.person_id = (SELECT person_id FROM a))"
            " GROUP BY p.person_id ORDER BY count(*) DESC, p.person_id LIMIT 1",
        )
    )[0]
    await rows(
        mutable_database_url, "UPDATE person SET merged_into = :a WHERE id = :b", a=pair.a, b=pair.b
    )
    expected = await ids(mutable_database_url, takes_part("p.id IN (:a, :b)"), a=pair.a, b=pair.b)
    alone = await ids(mutable_database_url, takes_part("p.id = :a"), a=pair.a)
    assert len(expected) > len(alone)
    assert await listed(mutable_client, [("person", str(pair.a))]) == expected


# A person's mails (D32) -----------------------------------------------------------------------

ROLES = ["sent", "received", "cc"]


def person_role(person: str, role: str) -> str:
    """D29 in SQL for the person matching `person` (on person p): sent, received, Cc only."""
    if role == "sent":
        return takes_part(person, SENDER)
    if role == "received":
        return f"{takes_part(person, RECIPIENT)} AND NOT {takes_part(person, SENDER)}"
    copied = takes_part(person, "pa.role = 'cc'")
    return f"{copied} AND NOT {takes_part(person, "pa.role IN ('from', 'to', 'bcc')")}"


async def first_roles(url: str, person: str, **params: Any) -> dict[int, str]:
    """mail id -> the first role (from, to, cc, bcc) of the person matching `person` in it."""
    found = await rows(
        url,
        "SELECT pa.mail_id, min(pa.role)::text AS role FROM participation pa"
        f" JOIN person p ON p.id = pa.person_id WHERE {person} GROUP BY 1",
        **params,
    )
    return {row.mail_id: row.role for row in found}


async def items(client: httpx.AsyncClient, params: Params) -> list[Any]:
    return [item for page in await pages(client, params) for item in page["items"]]


async def cc_person(url: str) -> int:
    """The address in Cc most often; it also sends and receives."""
    found = await rows(
        url,
        "SELECT person_id FROM participation WHERE role = 'cc' GROUP BY 1"
        " ORDER BY count(*) DESC, 1 LIMIT 1",
    )
    return int(found[0].person_id)


@pytest.mark.parametrize("walk_rows", [filters.WALK_ROWS, 7])
async def test_person_role_selects_what_sql_selects(
    client: httpx.AsyncClient,
    imported_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    walk_rows: int,
) -> None:
    monkeypatch.setattr(filters, "WALK_ROWS", walk_rows)
    url = imported_database_url
    person = await cc_person(url)
    found: dict[str, list[int]] = {}
    for role in ROLES:
        params = [("person", str(person)), ("person_role", role)]
        where = person_role("p.id = :a", role)
        expected = await ids(url, where, a=person)
        assert expected, role
        found[role] = await listed(client, params)
        assert found[role] == expected, role
        originals = await ids(url, f"({where}) AND is_duplicate_of IS NULL", a=person)
        assert await listed(client, [*params, ("hide_duplicates", "true")]) == originals, role
    every = await ids(url, takes_part("p.id = :a"), a=person)
    assert sorted(found["sent"] + found["received"]) == sorted(every)
    assert set(found["cc"]) <= set(found["received"])


async def test_person_role_in_summary_neighbours_and_export(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    params = [("person", str(await cc_person(imported_database_url))), ("person_role", "received")]
    found = await listed(client, params)
    assert len(found) > 3
    assert (await get(client, "/api/mails/summary", params))["total"] == len(found)
    neighbours = await get(client, f"/api/mails/{found[1]}/neighbors", params)
    assert neighbours == {"prev_id": found[0], "next_id": found[2], "position": 2}
    assert [int(row[0]) for row in await export(client, params)] == found


async def test_items_name_the_person_role(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    person = await cc_person(imported_database_url)
    expected = await first_roles(imported_database_url, "p.id = :a", a=person)
    shown = {
        item["id"]: item["person_role"] for item in await items(client, [("person", str(person))])
    }
    assert shown == expected
    assert {"from", "to", "cc"} <= set(shown.values())
    for role, first in (("sent", {"from"}), ("cc", {"cc"}), ("received", {"to", "cc", "bcc"})):
        params = [("person", str(person)), ("person_role", role)]
        assert {item["person_role"] for item in await items(client, params)} <= first, role
    other = (
        await rows(
            imported_database_url,
            "SELECT o.person_id FROM participation pa JOIN participation o ON o.mail_id ="
            " pa.mail_id AND o.person_id <> pa.person_id WHERE pa.person_id = :a"
            " GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1",
            a=person,
        )
    )[0].person_id
    both = await get(client, "/api/mails", [("person", str(person)), ("person", str(other))])
    assert both["items"]
    assert {item["person_role"] for item in both["items"]} == {None}


@pytest.mark.parametrize(
    "params",
    [[("person_role", "sent")], [("person_role", "cc"), ("person", "1"), ("person", "2")]],
    ids=["no person", "two persons"],
)
async def test_person_role_needs_exactly_one_person(
    client: httpx.AsyncClient, params: Params
) -> None:
    for path in ("/api/mails", "/api/mails/summary", "/api/mails/export.csv"):
        error = await get(client, path, params, status=400)
        assert error["detail"]["code"] == "invalid_filter"
        assert "person_role" in error["detail"]["message"]
    await get(client, "/api/mails", [("person_role", "everything"), ("person", "1")], status=422)


async def test_person_role_counts_merged_addresses(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    # a sends to b more often than anyone to anyone; b becomes an alias of a.
    pair = (
        await rows(
            url,
            "SELECT s.person_id AS a, r.person_id AS b FROM participation s"
            " JOIN participation r ON r.mail_id = s.mail_id AND r.role = 'to'"
            " WHERE s.role = 'from' AND r.person_id <> s.person_id"
            " GROUP BY 1, 2 ORDER BY count(*) DESC, 1, 2 LIMIT 1",
        )
    )[0]
    alone = {role: await ids(url, person_role("p.id = :a", role), a=pair.a) for role in ROLES}
    of_a = await first_roles(url, "p.id = :a", a=pair.a)
    await rows(url, "UPDATE person SET merged_into = :a WHERE id = :b", a=pair.a, b=pair.b)
    members = "(p.id = :a OR p.merged_into = :a)"
    changed = []
    for role in ROLES:
        expected = await ids(url, person_role(members, role), a=pair.a)
        params = [("person", str(pair.a)), ("person_role", role)]
        assert await listed(mutable_client, params) == expected, role
        changed += [role] if expected != alone[role] else []
    assert changed
    shown = {
        item["id"]: item["person_role"]
        for item in await items(mutable_client, [("person", str(pair.a))])
    }
    assert shown == await first_roles(url, members, a=pair.a)
    assert set(shown) - set(of_a)  # mails of b alone, with b's role

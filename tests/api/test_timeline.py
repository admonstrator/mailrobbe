"""GET /api/timeline and /api/timeline/first-mentions on the generated archive (D90 to D95).

Expected figures come from SQL written apart from api/timeline.py: bucket counts from
date_trunc over the UTC day, the axis from generate_series, series from participation and
thread_id, first mentions from DISTINCT ON. The marks are those of timeline.marks, tested on
their own in tests/timeline; here only how the API applies them.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api.schemas import MAX_TIMELINE_SERIES
from mailrobbe.timeline import buckets, marks
from tests.api.conftest import _client, api_settings
from tests.api.test_mails import FULL_TEXT, SENDER, Params, get, rows, takes_part
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

Json = dict[str, Any]

# The person :p or one of its aliases (SQL on person p).
MEMBER = "(p.id = :p OR p.merged_into = :p)"
# A part of an address or display name, as from: matches it (D20).
NAMED = (
    "(strpos(lower(p.canonical_email), lower(:part)) > 0"
    " OR strpos(lower(COALESCE(p.display_name, '')), lower(:part)) > 0)"
)
ARCHIVE_END = (
    "SELECT (max(date_utc) AT TIME ZONE 'UTC')::date AS day FROM mail"
    " WHERE (date_utc AT TIME ZONE 'UTC')::date <= (now() AT TIME ZONE 'UTC')::date"
)
NOTHING = ("q", "subject:zzzz-nothing")


async def bucketed(url: str, bucket: str, where: str, **params: Any) -> dict[date, int]:
    """The matching dated mails per bucket start; date_trunc's weeks start on Monday."""
    found = await rows(
        url,
        f"SELECT date_trunc('{bucket}', date_utc AT TIME ZONE 'UTC')::date AS start,"
        f" count(*) AS n FROM mail WHERE date_utc IS NOT NULL AND ({where}) GROUP BY 1",
        **params,
    )
    return {row.start: row.n for row in found}


async def axis(url: str, bucket: str, first: date, last: date) -> list[str]:
    """The bucket starts from the bucket of first to that of last."""
    found = await rows(
        url,
        f"SELECT generate_series(date_trunc('{bucket}', CAST(CAST(:first AS date) AS timestamp)),"
        f" date_trunc('{bucket}', CAST(CAST(:last AS date) AS timestamp)),"
        f" interval '1 {bucket}')::date AS start",
        first=first,
        last=last,
    )
    return [row.start.isoformat() for row in found]


def counted(timeline: Json, series: Json) -> dict[date, int]:
    """A series' counts by bucket start, without the empty buckets."""
    pairs = zip(timeline["starts"], series["counts"], strict=True)
    return {date.fromisoformat(start): count for start, count in pairs if count}


def assert_marks(
    timeline: Json, series: Json, end_day: date | None, date_from: date | None = None
) -> None:
    """The series carries the marks of timeline.marks for its counts: silent up to end_day, low
    only in the buckets wholly from date_from to end_day."""
    bucket, counts = timeline["bucket"], series["counts"]
    assert series["total"] == sum(counts)
    starts = [date.fromisoformat(start) for start in timeline["starts"]]
    low = buckets.covered(starts, bucket, date_from, end_day)
    assert series["outliers"] == [mark.model_dump() for mark in marks.outliers(counts, bucket, low)]
    end = -1 if end_day is None else buckets.position(starts, end_day)
    silent = marks.silent_from(counts, bucket, end)
    assert series["silent_from"] == (None if silent is None else starts[silent].isoformat())


async def archive_end(url: str) -> date:
    day: date = (await rows(url, ARCHIVE_END))[0].day
    return day


async def common_word(url: str) -> str:
    found = await rows(
        url,
        "SELECT w FROM (SELECT regexp_split_to_table(lower(subject), '[^a-zäöüß]+') AS w"
        ' FROM mail) t WHERE length(w) >= 6 GROUP BY w ORDER BY count(*) DESC, w COLLATE "C"'
        " LIMIT 1",
    )
    word: str = found[0].w
    return word


async def busiest(url: str, count: int = 1) -> list[int]:
    """The root persons with the most mails (person_stats), lists and automated ones included."""
    found = await rows(
        url, "SELECT person_id FROM person_stats ORDER BY mails DESC, person_id LIMIT :n", n=count
    )
    return [row.person_id for row in found]


def split_ids(*ids: int) -> Params:
    return [("split_id", str(each)) for each in ids]


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


# The total ----------------------------------------------------------------------------------


@pytest.mark.parametrize("bucket", ["month", "week"])
async def test_the_total_counts_what_sql_counts(
    client: httpx.AsyncClient, imported_database_url: str, bucket: str
) -> None:
    url = imported_database_url
    (person,) = await busiest(url)
    word = await common_word(url)
    thread = (
        await rows(
            url,
            "SELECT thread_id FROM mail WHERE thread_id IS NOT NULL"
            " GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1",
        )
    )[0].thread_id
    end = await archive_end(url)
    cases: list[tuple[Params, str, dict[str, Any]]] = [
        ([], "true", {}),
        ([("person", str(person))], takes_part(MEMBER), {"p": person}),
        ([("q", word)], FULL_TEXT, {"w": word}),
        (
            [("date_from", "2016-03-15"), ("date_to", "2018-07-20")],
            "date_utc >= '2016-03-15Z' AND date_utc < '2018-07-21Z'",
            {},
        ),
        ([("hide_duplicates", "true")], "is_duplicate_of IS NULL", {}),
        ([("thread", str(thread))], "thread_id = :t", {"t": thread}),  # D95
    ]
    for params, where, values in cases:
        timeline = await get(client, "/api/timeline", [*params, ("bucket", bucket)])
        expected = await bucketed(url, bucket, where, **values)
        assert expected, params
        total = timeline["total"]
        assert counted(timeline, total) == expected, params
        assert (total["key"], total["label"], total["person"], total["thread_id"]) == (
            "all",
            None,
            None,
            None,
        )
        undated = await rows(
            url, f"SELECT count(*) AS n FROM mail WHERE date_utc IS NULL AND ({where})", **values
        )
        assert timeline["undated"] == undated[0].n
        given = {key: date.fromisoformat(value) for key, value in params if key.startswith("date")}
        first = given.get("date_from", min(expected))
        last = given.get("date_to", max(max(expected), end))
        assert timeline["starts"] == await axis(url, bucket, first, last), params
        assert timeline["bucket"] == bucket
        assert (timeline["coarsened"], timeline["timed_out"], timeline["series"]) == (
            False,
            False,
            [],
        )
        assert timeline["archive_end"] == end.isoformat()
        assert_marks(timeline, total, min(end, given.get("date_to", end)), given.get("date_from"))


async def test_the_span_chooses_the_bucket_and_a_fine_one_is_coarsened(
    client: httpx.AsyncClient,
) -> None:
    spring = [("date_from", "2020-01-01"), ("date_to", "2020-04-29")]  # 120 days
    days = await get(client, "/api/timeline", spring)
    assert (days["bucket"], len(days["starts"]), days["coarsened"]) == ("day", 120, False)
    longer = await get(client, "/api/timeline", [spring[0], ("date_to", "2020-04-30")])
    assert (longer["bucket"], longer["starts"][0], longer["coarsened"]) == (
        "week",
        "2019-12-30",
        False,
    )
    whole = await get(client, "/api/timeline")
    assert (whole["bucket"], whole["coarsened"]) == ("month", False)
    # About 14 years by day are more than 1,500 buckets, by week fewer.
    weekly = await get(client, "/api/timeline", [("bucket", "day")])
    assert (weekly["bucket"], weekly["coarsened"]) == ("week", True)
    assert weekly["total"]["total"] == whole["total"]["total"]
    monthly = await get(client, "/api/timeline", [("bucket", "week"), ("date_from", "1980-01-01")])
    assert (monthly["bucket"], monthly["coarsened"], monthly["starts"][0]) == (
        "month",
        True,
        "1980-01-01",
    )
    # The calendar's last day as date_to: months up to it, the mails as without it.
    last = await get(client, "/api/timeline", [("date_to", "9999-12-31"), ("bucket", "day")])
    assert (last["bucket"], last["coarsened"], last["starts"][-1]) == ("month", True, "9999-12-01")
    assert last["total"]["total"] == whole["total"]["total"]


async def test_no_match_gives_an_empty_axis(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    for params, bucket in (([], "month"), ([("bucket", "day")], "day")):
        timeline = await get(client, "/api/timeline", [NOTHING, ("split", "person"), *params])
        assert timeline == {
            "bucket": bucket,
            "coarsened": False,
            "starts": [],
            "total": {
                "key": "all",
                "label": None,
                "person": None,
                "thread_id": None,
                "term": None,
                "counts": [],
                "total": 0,
                "outliers": [],
                "silent_from": None,
            },
            "series": [],
            "undated": 0,
            "archive_end": (await archive_end(imported_database_url)).isoformat(),
            "timed_out": False,
        }
    (person,) = await busiest(imported_database_url)
    named = await get(client, "/api/timeline", [NOTHING, ("split", "person"), *split_ids(person)])
    assert [(series["key"], series["counts"]) for series in named["series"]] == [
        (f"person:{person}", [])
    ]


async def test_undated_and_future_mails_and_a_person_falling_silent(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    (person,) = await busiest(url)
    # The person's mails all in 2022, one dated in 2099; three mails of others without a date.
    await rows(
        url,
        "WITH own AS (SELECT mail_id AS id, row_number() OVER (ORDER BY mail_id) AS k"
        " FROM (SELECT DISTINCT mail_id FROM participation WHERE person_id = :p) t)"
        " UPDATE mail SET date_utc = CASE WHEN own.k = 1 THEN timestamptz '2099-05-01 12:00Z'"
        " ELSE timestamptz '2022-01-10 12:00Z' + make_interval(months => (own.k % 12)::int) END"
        " FROM own WHERE mail.id = own.id",
        p=person,
    )
    await rows(
        url,
        "UPDATE mail SET date_utc = NULL WHERE id IN (SELECT id FROM mail m WHERE NOT EXISTS"
        " (SELECT 1 FROM participation WHERE mail_id = m.id AND person_id = :p)"
        " ORDER BY id LIMIT 3)",
        p=person,
    )
    end = await archive_end(url)
    assert end < date(2099, 5, 1)

    timeline = await get(mutable_client, "/api/timeline")
    assert timeline["undated"] == 3
    assert timeline["archive_end"] == end.isoformat()
    assert timeline["starts"][-1] == "2099-05-01"  # a future mail lengthens the axis only
    assert counted(timeline, timeline["total"]) == await bucketed(url, "month", "true")

    alone = await get(mutable_client, "/api/timeline", [("person", str(person))])
    assert (alone["undated"], alone["starts"][0], alone["starts"][-1]) == (
        0,
        "2022-01-01",
        "2099-05-01",
    )
    # Silent from 2023 up to the archive's end; the mail of 2099 does not end that.
    assert alone["total"]["silent_from"] == "2023-01-01"
    assert_marks(alone, alone["total"], end)


# Series --------------------------------------------------------------------------------------


async def test_person_split_takes_the_busiest_persons_without_lists(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    url = imported_database_url
    stats = await rows(
        url,
        "SELECT s.person_id, s.mails, p.kind, p.canonical_email, p.display_name"
        " FROM person_stats s JOIN person p ON p.id = s.person_id WHERE s.mails > 0"
        " ORDER BY s.mails DESC, s.person_id DESC",
    )
    humans = [row for row in stats if row.kind is None]
    params = [("split", "person"), ("bucket", "month")]
    timeline = await get(client, "/api/timeline", params)
    assert [series["key"] for series in timeline["series"]] == [
        f"person:{row.person_id}" for row in humans[:6]
    ]
    wider = await get(client, "/api/timeline", [*params, ("series", "8")])
    assert [series["person"]["person_id"] for series in wider["series"]] == [
        row.person_id for row in humans[:8]
    ]
    # A list or an automated sender with more mails than the last of them is left out.
    assert any(row.kind is not None and row.mails > humans[7].mails for row in stats)
    # Counted over the matching mails without duplicates, they are the same: person_stats
    # counts no duplicates either.
    counted_top = await get(
        client, "/api/timeline", [*params, ("series", "8"), ("hide_duplicates", "true")]
    )
    assert [series["key"] for series in counted_top["series"]] == [
        series["key"] for series in wider["series"]
    ]
    end = await archive_end(url)
    for series, row in zip(wider["series"], humans, strict=False):
        assert series["person"] == {
            "person_id": row.person_id,
            "email": row.canonical_email,
            "name": row.display_name,
            "label": None,
        }
        assert series["label"] == (row.display_name or row.canonical_email)
        expected = await bucketed(url, "month", takes_part(MEMBER), p=row.person_id)
        assert counted(wider, series) == expected
        assert_marks(wider, series, end)


async def test_person_split_counts_the_persons_with_the_most_matching_mails(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    url = imported_database_url
    word = await common_word(url)
    top = await rows(
        url,
        "SELECT coalesce(p.merged_into, p.id) AS root, count(DISTINCT mail.id) AS n FROM mail"
        " JOIN participation pa ON pa.mail_id = mail.id JOIN person p ON p.id = pa.person_id"
        " JOIN person r ON r.id = coalesce(p.merged_into, p.id)"
        f" WHERE r.kind IS NULL AND {FULL_TEXT} GROUP BY 1 ORDER BY n DESC, root DESC LIMIT 6",
        w=word,
    )
    timeline = await get(
        client, "/api/timeline", [("q", word), ("split", "person"), ("bucket", "month")]
    )
    assert [series["person"]["person_id"] for series in timeline["series"]] == [
        row.root for row in top
    ]
    for series, row in zip(timeline["series"], top, strict=True):
        expected = await bucketed(
            url, "month", f"{FULL_TEXT} AND {takes_part(MEMBER)}", w=word, p=row.root
        )
        assert counted(timeline, series) == expected
        assert series["total"] == row.n  # every match of the word is dated


async def test_person_split_by_id_keeps_the_order_and_counts_aliases_for_their_root(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    root, alias, other = await busiest(url, 3)
    response = await mutable_client.post(
        "/api/persons/merge", json={"target": root, "sources": [alias]}
    )
    assert response.status_code == 200, response.text
    params = [("split", "person"), ("bucket", "month"), *split_ids(other, alias, root, 10**12)]
    timeline = await get(mutable_client, "/api/timeline", params)
    assert [series["key"] for series in timeline["series"]] == [
        f"person:{other}",
        f"person:{root}",
    ]
    person = (
        await rows(url, "SELECT canonical_email, display_name FROM person WHERE id = :p", p=root)
    )[0]
    merged = timeline["series"][1]
    assert merged["person"] == {
        "person_id": root,
        "email": person.canonical_email,
        "name": person.display_name,
        "label": None,
    }
    for series, each in zip(timeline["series"], (other, root), strict=True):
        assert counted(timeline, series) == await bucketed(url, "month", takes_part(MEMBER), p=each)
    own = await bucketed(url, "month", takes_part("p.id = :p"), p=root)
    assert sum(own.values()) < merged["total"]  # the alias's mails count for the root


async def test_thread_split(client: httpx.AsyncClient, imported_database_url: str) -> None:
    url = imported_database_url
    top = await rows(
        url,
        "SELECT thread_id, count(*) AS n FROM mail WHERE is_duplicate_of IS NULL"
        " AND thread_id IS NOT NULL GROUP BY 1 ORDER BY n DESC, thread_id DESC LIMIT 6",
    )
    params = [("split", "thread"), ("hide_duplicates", "true"), ("bucket", "month")]
    timeline = await get(client, "/api/timeline", params)
    assert [series["thread_id"] for series in timeline["series"]] == [row.thread_id for row in top]
    for series in timeline["series"]:
        thread = series["thread_id"]
        first = await rows(url, "SELECT subject FROM mail WHERE id = :t", t=thread)
        assert (series["key"], series["label"]) == (f"thread:{thread}", first[0].subject)
        where = "is_duplicate_of IS NULL AND thread_id = :t"
        assert counted(timeline, series) == await bucketed(url, "month", where, t=thread)
    # By id, in the order given; a single mail and a later mail of a thread start no thread.
    single = await rows(url, "SELECT id FROM mail WHERE thread_id IS NULL ORDER BY id LIMIT 1")
    later = await rows(url, "SELECT id FROM mail WHERE thread_id <> id ORDER BY id LIMIT 1")
    chosen = [top[2].thread_id, single[0].id, top[0].thread_id, later[0].id, top[2].thread_id]
    timeline = await get(client, "/api/timeline", [*params, *split_ids(*chosen)])
    assert [series["thread_id"] for series in timeline["series"]] == [
        top[2].thread_id,
        top[0].thread_id,
    ]


async def test_term_split(client: httpx.AsyncClient, imported_database_url: str) -> None:
    url = imported_database_url
    word = await common_word(url)
    sender = (
        await rows(
            url,
            "SELECT p.canonical_email FROM participation pa JOIN person p ON p.id = pa.person_id"
            " WHERE pa.role = 'from' GROUP BY p.id ORDER BY count(*) DESC, p.id LIMIT 1",
        )
    )[0].canonical_email
    part = sender.split("@")[0]
    terms = [word, f"from:{part}", "has:attachment"]
    conditions: list[tuple[str, dict[str, Any]]] = [
        (FULL_TEXT, {"w": word}),
        (takes_part(NAMED, SENDER), {"part": part}),
        ("has_attachments", {}),
    ]
    params = [("split", "term"), ("hide_duplicates", "true"), ("bucket", "month")]
    timeline = await get(client, "/api/timeline", [*params, *[("term", term) for term in terms]])
    assert len(timeline["series"]) == len(terms)
    for index, (series, term, (where, values)) in enumerate(
        zip(timeline["series"], terms, conditions, strict=True)
    ):
        assert (series["key"], series["label"], series["term"]) == (f"term:{index}", term, term)
        expected = await bucketed(url, "month", f"is_duplicate_of IS NULL AND {where}", **values)
        assert expected, term
        assert counted(timeline, series) == expected


async def test_parameters_that_cannot_be_used(client: httpx.AsyncClient) -> None:
    terms = [("split", "term"), ("term", "Vertrag"), ("term", "Spende has:pdf")]
    error = await get(client, "/api/timeline", terms, 400)
    assert error["detail"]["code"] == "invalid_query"
    assert '"Spende has:pdf"' in error["detail"]["message"]
    for path in ("/api/timeline", "/api/timeline/first-mentions"):
        error = await get(client, path, [("q", "dkim:maybe")], 400)
        assert error["detail"]["code"] == "invalid_query"
        error = await get(client, path, [("person_role", "sent")], 400)
        assert error["detail"]["code"] == "invalid_filter"
    too_many = split_ids(*range(1, MAX_TIMELINE_SERIES + 2))
    for params in ([("series", "0")], [("bucket", "year")], [("split", "person"), *too_many]):
        await get(client, "/api/timeline", params, 422)
    for params in ([("limit", "501")], [("role", "cc")]):
        await get(client, "/api/timeline/first-mentions", params, 422)


# First mentions -----------------------------------------------------------------------------

FIRST_MENTIONS = """
WITH m AS (SELECT id, date_utc FROM mail WHERE {where}),
per_mail AS (
    SELECT coalesce(p.merged_into, p.id) AS root, pa.mail_id, m.date_utc,
        min(CASE pa.role WHEN 'from' THEN 0 WHEN 'to' THEN 1 WHEN 'cc' THEN 2 ELSE 3 END) AS rank
    FROM m JOIN participation pa ON pa.mail_id = m.id JOIN person p ON p.id = pa.person_id
    WHERE {role} GROUP BY 1, 2, 3
),
counts AS (SELECT root, count(*) AS mails FROM per_mail GROUP BY root),
firsts AS (
    SELECT DISTINCT ON (root) root, mail_id, date_utc, rank FROM per_mail
    WHERE date_utc IS NOT NULL ORDER BY root, date_utc, mail_id
)
SELECT f.root, f.mail_id, f.date_utc, f.rank, c.mails, r.kind, r.canonical_email,
    r.display_name, mail.subject
FROM firsts f JOIN counts c USING (root) JOIN person r ON r.id = f.root
    JOIN mail ON mail.id = f.mail_id
WHERE {kind}
ORDER BY f.date_utc, f.mail_id, f.root
"""
ROLES = ("from", "to", "cc", "bcc")


async def test_first_mentions_are_what_distinct_on_finds(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    url = imported_database_url
    word = await common_word(url)
    (person,) = await busiest(url)
    cases: list[tuple[Params, str, dict[str, Any], str, str]] = [
        ([("q", word)], FULL_TEXT, {"w": word}, "true", "r.kind IS NULL"),
        (
            [("q", word), ("role", "sent")],
            FULL_TEXT,
            {"w": word},
            "pa.role = 'from'",
            "r.kind IS NULL",
        ),
        ([("q", word), ("lists", "true")], FULL_TEXT, {"w": word}, "true", "true"),
        (
            [("person", str(person)), ("hide_duplicates", "true"), ("limit", "7")],
            f"is_duplicate_of IS NULL AND {takes_part(MEMBER)}",
            {"p": person},
            "true",
            "r.kind IS NULL",
        ),
        ([("limit", "500")], "true", {}, "true", "r.kind IS NULL"),
    ]
    for params, where, values, role, kind in cases:
        found = await rows(url, FIRST_MENTIONS.format(where=where, role=role, kind=kind), **values)
        expected = [
            {
                "person": {
                    "person_id": row.root,
                    "email": row.canonical_email,
                    "name": row.display_name,
                    "label": None,
                },
                "kind": row.kind,
                "role": ROLES[row.rank],
                "date": stamp(row.date_utc),
                "mail_id": row.mail_id,
                "subject": row.subject,
                "mails": row.mails,
            }
            for row in found
        ]
        limit = int(dict(params).get("limit", "100"))
        assert len(expected) > min(limit, 5), params
        mentions = await get(client, "/api/timeline/first-mentions", params)
        assert mentions == {"items": expected[:limit], "persons": len(expected), "timed_out": False}
    sent = await get(client, "/api/timeline/first-mentions", [("q", word), ("role", "sent")])
    assert {item["role"] for item in sent["items"]} == {"from"}
    listed = await get(client, "/api/timeline/first-mentions", [("q", word), ("lists", "true")])
    assert any(item["kind"] is not None for item in listed["items"])


# Count budget -------------------------------------------------------------------------------


async def test_parts_that_run_out_of_time_are_left_out(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    settings = api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(update={"api_count_timeout": 0.3})
    engine = create_async_engine(mutable_database_url, poolclass=pool.NullPool)
    try:
        async for client in _client(settings):
            split = [("split", "person")]
            whole = await get(client, "/api/timeline", split)
            assert whole["series"] and not whole["timed_out"]
            async with engine.connect() as other:
                # The series read participation: they wait and run out of time, the total not.
                await other.execute(text("LOCK TABLE participation IN ACCESS EXCLUSIVE MODE"))
                assert await get(client, "/api/timeline", split) == {
                    **whole,
                    "series": [],
                    "timed_out": True,
                }
                mentions = await get(client, "/api/timeline/first-mentions")
                assert mentions == {"items": [], "persons": None, "timed_out": True}
                # Now every count waits.
                await other.execute(text("LOCK TABLE mail IN ACCESS EXCLUSIVE MODE"))
                assert await get(client, "/api/timeline", split) == {
                    "bucket": "month",
                    "coarsened": False,
                    "starts": [],
                    "total": None,
                    "series": [],
                    "undated": None,
                    "archive_end": None,
                    "timed_out": True,
                }
                await other.rollback()
            assert await get(client, "/api/timeline", split) == whole
            mentions = await get(client, "/api/timeline/first-mentions")
            assert mentions["items"] and mentions["timed_out"] is False
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("options", "total"),
    [
        ([], 8),  # stems everywhere: cases 0 to 7
        ([("whole_word", "true")], 4),  # cases 0, 1, 6, 7
        ([("scope", "filename")], 1),  # case 5
    ],
)
async def test_term_series_take_the_search_options(
    search_client: httpx.AsyncClient, options: Params, total: int
) -> None:
    params = [("split", "term"), ("term", "Neger"), *options]
    timeline = await get(search_client, "/api/timeline", params)
    (series,) = timeline["series"]
    assert series["total"] == total

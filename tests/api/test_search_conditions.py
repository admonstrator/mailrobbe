"""The conditions of the search options (D171 to D175): places, whole words, placed words and
negated operators, built by api/filters.py.

The search cases (tests/api/search_cases.py) give the expected mails by case, as its docstring
tables them; every search there is read through the bounded walk (pages of two) and through the
collection of every match (one page). On the generated archive the expected mails come from SQL
written apart from api/filters.py, for each path that takes mail_conditions: the list's pages in
both orders, with the walk and with every match collected, the summary, the CSV, the timeline
and a selection by filters. A search of the whole text (body_part full, D226) without the other
options sends the SQL of before D171; the default and own weigh the mail's side only.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import ColumnElement, Text, cast, func, pool, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailrobbe.api import filters
from mailrobbe.api.fulltext import Words, full_text_search
from mailrobbe.api.query import parse_query
from mailrobbe.api.schemas import MailFilters, MailSelection
from mailrobbe.api.selection import resolve_selection
from mailrobbe.config import Settings
from mailrobbe.db.models import Mail
from tests.api.test_mails import (
    PAGE,
    SENDER,
    SORTS,
    Params,
    export,
    get,
    ids,
    listed,
    page_ids,
    pages,
    rows,
    takes_part,
)

pytestmark = pytest.mark.db

WHOLE = ("whole_word", "true")


def scope(*places: str) -> Params:
    return [("scope", place) for place in places]


@pytest.fixture
def walk_rows(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(filters, "WALK_ROWS", request.param)
    return int(request.param)


WALKS = pytest.mark.parametrize(
    "walk_rows", [filters.WALK_ROWS, 7], ids=["default", "short-walk"], indirect=True
)


async def walked_and_collected(
    client: httpx.AsyncClient, params: Params, page: int = 2
) -> list[int]:
    """The list's mails, read in small pages (the walk fills all but the last unless it runs
    out) and in pages of 200 (every match collected), which must agree."""
    walked = [mail_id for found in await pages(client, params, page) for mail_id in page_ids(found)]
    assert walked == await listed(client, params), params
    return walked


# The search cases ------------------------------------------------------------------------------

EVERYWHERE = {0, 1, 2, 3, 4, 5, 6, 7}
# (name, q, other parameters, the cases found)
SEARCHES: list[tuple[str, str, Params, set[int]]] = [
    # Places (D171): everywhere by default, as before.
    ("everywhere", "Neger", [], EVERYWHERE),
    ("all-four-places", "Neger", scope("subject", "body", "attachment", "filename"), EVERYWHERE),
    ("subject-and-text", "Neger", scope("subject", "body"), {0, 1, 2, 3, 4, 7}),
    ("subject", "Neger", scope("subject"), {0, 7}),
    ("text", "Neger", scope("body"), {0, 1, 2, 3, 4, 7}),
    ("file-names", "Neger", scope("filename"), {5}),
    ("attachment-text", "Neger", scope("attachment"), {6}),
    ("attachments", "Neger", scope("attachment", "filename"), {5, 6}),
    ("subject-and-file-names", "Neger", scope("subject", "filename"), {0, 5, 7}),
    # Whole words (D173): as written, in any case, not inside a longer word.
    ("whole", "Neger", [WHOLE], {0, 1, 6, 7}),
    ("whole-any-case", "NEGER", [WHOLE], {0, 1, 6, 7}),
    ("whole-inflected", "Negern", [WHOLE], {2}),
    ("whole-french", "negere", [WHOLE], {3, 4}),
    ("whole-accents", "négère", [WHOLE], {8}),
    ("whole-hyphenated", "Neger-Witz", [WHOLE], {0}),
    ("whole-phrase", '"Neger raus"', [WHOLE], {7}),
    ("whole-or", "Neger or negere", [WHOLE], {0, 1, 3, 4, 6, 7}),
    ("whole-in-a-file-name", "NEG", [WHOLE], {5}),
    ("whole-in-file-names", "Neger", [WHOLE, *scope("filename")], set()),
    ("whole-in-the-subject", "Neger", [WHOLE, *scope("subject")], {0, 7}),
    ("whole-in-attachment-text", "Neger", [WHOLE, *scope("attachment")], {6}),
    # The minus of a free word (D170, D175): the stem, or with whole words the word as written,
    # in the places of the mail's own text or of one document, which are separate units.
    ("minus-stem", "Neger -negere", [], set()),
    ("minus-word", "Neger -negere", [WHOLE], {0, 1, 6, 7}),
    ("minus-stem-alone", "-negere", [], {5, 6, 8, 9}),
    ("minus-word-alone", "-negere", [WHOLE], {0, 1, 2, 5, 6, 7, 8, 9}),
    ("minus-word-in-the-unit", "Neger -Stammtisch", [WHOLE], {0, 6, 7}),
    ("minus-phrase-stem", 'Neger -"Neger raus"', [], {0, 1, 2, 3, 4, 5, 6}),
    ("minus-phrase-word", 'Neger -"Neger raus"', [WHOLE], {0, 1, 6}),
    # Case 6: Protokoll_Klausur.txt and its text are one unit, the mail's own text another.
    ("minus-stem-in-a-document", "Neger -Protokoll", [], {0, 1, 2, 3, 4, 5, 7}),
    ("minus-word-in-a-document", "Neger -Protokoll", [WHOLE], {0, 1, 7}),
    ("minus-stem-beyond-the-places", "Neger -Protokoll", scope("attachment"), {6}),
    ("minus-word-beyond-the-places", "Neger -Protokoll", [WHOLE, *scope("attachment")], {6}),
    # Placed words (D172): one place each, no part of an "or", untouched by scope.
    ("in-file-names", "datei:NEG", [], {5}),
    ("in-file-names-whole", "datei:NEG", [WHOLE], {5}),
    ("stem-in-file-names", "datei:Neger", [], {5}),
    ("whole-word-in-file-names", "datei:Neger", [WHOLE], set()),
    ("in-the-subject", "betreff:Neger", [], {0, 7}),
    ("in-the-text", "text:Neger", [], {0, 1, 2, 3, 4, 7}),
    ("in-the-text-whole", "text:Neger", [WHOLE], {0, 1, 7}),
    ("in-attachment-text", "anhang:Neger", [WHOLE], {6}),
    ("placed-phrase", 'betreff:"NEGER RAUS"', [], {7}),
    ("placed-is-no-alternative", "Neger or Stammtisch datei:NEG", [], {5}),
    ("placed-beyond-the-scope", "Belege datei:NEG", scope("subject"), {5}),
    # Placed words with a minus (D175).
    ("not-in-file-names", "-datei:NEG Neger", [], {0, 1, 2, 3, 4, 6, 7}),
    ("not-in-attachments", "-anhang:Neger -datei:NEG Neger", [], {0, 1, 2, 3, 4, 7}),
    ("not-in-the-subject", "-betreff:Neger Neger", [], {1, 2, 3, 4, 5, 6}),
    ("not-in-the-text-stem", "-text:negere Neger", [], {5, 6}),
    ("not-in-the-text-whole", "-text:negere Neger", [WHOLE], {0, 1, 6, 7}),
    ("not-in-file-names-alone", "-datei:NEG", [], {0, 1, 2, 3, 4, 6, 7, 8, 9}),
    # Operators with a minus (D175).
    ("not-from", "-from:karl Neger", [], {1, 2, 3, 4, 5, 7}),
    ("not-to", "-to:info Neger", [], {0, 1, 2, 5, 6}),
    ("not-domain", "-domain:extern.example Neger", [], {0, 1, 2, 3, 4, 5, 6}),
    ("not-with-attachments", "-has:attachment Neger", [], {0, 1, 2, 3, 4, 7}),
    ("not-this-message-id", "-<case-7@verein.example> Neger", [], {0, 1, 2, 3, 4, 5, 6}),
    ("not-before", "-before:2021-03-05", [], {4, 5, 6, 7, 8, 9}),
    ("not-after", "-after:5.3.2021", [], {0, 1, 2, 3}),
    ("not-subject", "-subject:Neger", [], {1, 2, 3, 4, 5, 6, 8, 9}),
]


@pytest.mark.parametrize(
    ("q", "params", "cases"),
    [search[1:] for search in SEARCHES],
    ids=[search[0] for search in SEARCHES],
)
async def test_the_search_cases_find_their_mails(
    search_client: httpx.AsyncClient,
    search_database_url: str,
    q: str,
    params: Params,
    cases: set[int],
) -> None:
    found = await rows(search_database_url, "SELECT id, message_id FROM mail")
    case_of = {row.id: int(row.message_id.split("-")[1].split("@")[0]) for row in found}
    search = [("q", q), *params]
    listed_ids = await walked_and_collected(search_client, search)
    assert {case_of[mail_id] for mail_id in listed_ids} == cases
    summary = await get(search_client, "/api/mails/summary", search)
    assert summary["total"] == len(cases)


@pytest.mark.parametrize(
    "q",
    [
        'or a b OR "c d" -e or or f or',
        "a or or or b",
        "-a or",
        'a -"b c" or d',
        "or",
        "Neger -negere",
        "a or -b",
    ],
)
async def test_the_groups_are_what_websearch_reads(db_session: AsyncSession, q: str) -> None:
    """FullText.groups, by which whole words are decided, against PostgreSQL's own reading."""
    search = full_text_search(parse_query(q))
    assert search is not None

    def written(words: Words) -> str:
        lexemes = " <-> ".join(f"'{part.lower()}'" for part in words.text.split())
        return f"!({lexemes})" if words.negated else f"({lexemes})"

    groups = " | ".join(
        "(" + " & ".join(written(words) for words in group) + ")" for group in search.groups
    )
    websearch = func.websearch_to_tsquery("simple", search.search)
    read = func.to_tsquery("simple", groups)
    found = (await db_session.execute(select(cast(websearch, Text), cast(read, Text)))).one()
    assert found[0] == found[1]


# The SQL ----------------------------------------------------------------------------------------


def sql(condition: ColumnElement[bool]) -> str:
    """The SQL of a list's statement with the condition, as the API's driver writes it."""
    dialect = create_async_engine("postgresql+asyncpg://", poolclass=pool.NullPool).dialect
    statement = select(Mail.id).where(condition)
    compiled = statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    return " ".join(str(compiled).split())


# What "Neger" compiled to before D171: the set form and the walk form of full_text.
NEGER = "websearch_to_tsquery('german'::regconfig, 'Neger')"
BEFORE_D171 = (
    f"SELECT mail.id FROM mail WHERE (mail.tsv @@ {NEGER}) OR mail.id = ANY (array((SELECT"
    " attachment.mail_id FROM attachment JOIN document ON document.id = attachment.document_id"
    f" WHERE document.tsv @@ {NEGER})))"
)
WALK_BEFORE_D171 = (
    f"SELECT mail.id FROM mail WHERE (mail.tsv @@ {NEGER}) OR mail.has_attachments AND"
    " coalesce((SELECT true AS anon_1 FROM attachment JOIN document ON document.id ="
    f" attachment.document_id WHERE attachment.mail_id = mail.id AND (document.tsv @@ {NEGER})"
    " LIMIT 1), false)"
)


START = "SELECT mail.id FROM mail WHERE "


def weighted(query: str, weights: str) -> str:
    """The SQL of fulltext.weighted: query with its lexemes limited to weights."""
    labelled = f"'(''(?:[^'']|'''')*'')', '\\1:{weights}', 'g'"
    return f"CAST(regexp_replace(CAST({query} AS TEXT), {labelled}) AS TSQUERY)"


def recheck(query: str, weights: str, plain: str) -> str:
    """The SQL of fulltext.mail_recheck: the mail is plain (has none of the ranges that may
    give it a weight beyond weights), holds the weighted query or does not hold query."""
    either = f"tsquery_or({weighted(query, weights)}, tsquery_not({query}))"
    return f"{plain} OR (mail.tsv @@ {either})"


def kept(query: str, rechecked: str) -> str:
    """What full_text adds to a form of before D226: the mail's side rechecked, or a document,
    asked per mail as the walk form of before D171 does."""
    per_mail = WALK_BEFORE_D171.split(" OR ", 1)[1].replace(NEGER, query)
    return f"({rechecked} OR {per_mail})"


def with_recheck(before: str, query: str, rechecked: str) -> str:
    """A form of full_text as it was before D226 (before: its statement), then kept."""
    return f"{START}({before.removeprefix(START)}) AND {kept(query, rechecked)}"


NO_BLOCKS = "mail.blocks IS NULL"
NO_RANGES = "mail.history IS NULL AND mail.blocks IS NULL"


@pytest.mark.parametrize(
    ("options", "rechecked"),
    [
        (MailFilters(), recheck(NEGER, "ABC", NO_BLOCKS)),
        (
            MailFilters(scope=["subject", "body", "attachment", "filename"], whole_word=False),
            recheck(NEGER, "ABC", NO_BLOCKS),
        ),
        (MailFilters(body_part="full"), None),
    ],
    ids=["default", "every-place", "whole-text"],
)
def test_a_search_without_options_sends_the_sql_of_before(
    options: MailFilters, rechecked: str | None
) -> None:
    """The indexes are asked what they were asked before D171: the whole text is the SQL of
    before, the default that SQL and after it the weighted query for the mails with standard
    blocks (D226)."""
    condition, visible = filters.mail_conditions(options, parse_query("Neger"), [])
    assert visible is filters.VISIBLE
    for found, before in (
        (condition, BEFORE_D171),
        (filters._WALK_FORMS[condition], WALK_BEFORE_D171),
    ):
        expected = before if rechecked is None else with_recheck(before, NEGER, rechecked)
        assert sql(found) == expected


SPENDE = "websearch_to_tsquery('german'::regconfig, 'Spende')"
SPENDE_NOT_RAT = "websearch_to_tsquery('german'::regconfig, 'Spende -Rat')"


@pytest.mark.parametrize(
    ("q", "options", "mail_side", "rechecked"),
    [
        (
            "Spende",
            MailFilters(body_part="own"),
            f"(mail.tsv @@ {SPENDE})",
            recheck(SPENDE, "AB", NO_RANGES),
        ),
        (
            "Spende",
            MailFilters(scope=["subject", "body", "attachment", "filename"]),
            f"(mail.tsv @@ {SPENDE})",
            recheck(SPENDE, "ABC", NO_BLOCKS),
        ),
        # without the subject a mail without ranges carries a weight the search leaves out
        (
            "Spende",
            MailFilters(scope=["body", "attachment", "filename"]),
            f"(mail.tsv @@ {weighted(SPENDE, 'BC')})",
            None,
        ),
        (
            "Spende",
            MailFilters(scope=["subject", "attachment", "filename"], body_part="own"),
            f"(mail.tsv @@ {weighted(SPENDE, 'A')})",
            None,
        ),
        # a negated word may stand in a block only: the weighted query alone decides
        ("Spende -Rat", MailFilters(), f"(mail.tsv @@ {weighted(SPENDE_NOT_RAT, 'ABC')})", None),
        ("Spende -Rat", MailFilters(body_part="full"), f"(mail.tsv @@ {SPENDE_NOT_RAT})", None),
    ],
    ids=["own", "every-place", "text", "subject", "negated", "negated-whole-text"],
)
def test_the_parts_weigh_the_mails_side_only(
    q: str, options: MailFilters, mail_side: str, rechecked: str | None
) -> None:
    """D226: the mail's side in the weights of the subject and the parts, asked as before
    D226 where they hold all a mail without ranges carries and rechecked after it; the
    documents' side as before."""
    condition = filters.mail_conditions(options, parse_query(q), [])[0]
    query = SPENDE_NOT_RAT if "-" in q else SPENDE
    for form in (sql, lambda found: sql(filters._WALK_FORMS[found])):
        written = form(condition)
        assert f"document.tsv @@ {query}" in written
        if rechecked is None:
            assert written.startswith(f"{START}{mail_side} OR ")
        else:
            assert written.startswith(f"{START}({mail_side} OR ")
            assert written.endswith(f") AND {kept(query, rechecked)}")


def test_the_mails_side_alone_is_rechecked_in_the_same_condition() -> None:
    """Without the documents' side the weighted query follows the index's in one condition,
    which needs no walk form of its own."""
    options = MailFilters(scope=["subject", "body"])
    condition = filters.mail_conditions(options, parse_query("Spende"), [])[0]
    rechecked = recheck(SPENDE, "ABC", NO_BLOCKS)
    assert sql(condition) == f"{START}(mail.tsv @@ {SPENDE}) AND ({rechecked})"
    assert condition not in filters._WALK_FORMS


def test_whole_words_and_proximity_terms_ask_the_index_as_before() -> None:
    """The index part of whole words and of a proximity term of whole words is the query as
    before D226, rechecked for the mails with blocks; a proximity term's phrases are rechecked
    anyway and keep the weighted query alone."""
    whole = sql(filters.mail_conditions(MailFilters(whole_word=True), parse_query("Spende"), [])[0])
    assert whole.startswith(f"{START}((mail.tsv @@ {SPENDE}) AND coalesce(")
    assert f") AND ({recheck(SPENDE, 'ABC', NO_BLOCKS)} OR mail.has_attachments AND " in whole
    both = "websearch_to_tsquery('german'::regconfig, '\"Spende\" \"bar\"')"
    near = sql(
        filters.mail_conditions(MailFilters(whole_word=True), parse_query('"Spende bar"~2'), [])[0]
    )
    assert near.startswith(f"{START}((mail.tsv @@ {both}) AND coalesce(")
    assert f") AND ({recheck(both, 'ABC', NO_BLOCKS)} OR mail.has_attachments AND " in near
    phrases = sql(filters.mail_conditions(MailFilters(), parse_query('"Spende bar"~2'), [])[0])
    assert phrases.startswith(f"{START}(mail.tsv @@ CAST(regexp_replace(")
    assert NO_BLOCKS not in phrases


@pytest.mark.parametrize("distance", [1, 3])
def test_a_proximity_term_is_one_query_of_its_distances(distance: int) -> None:
    """D229: "a b"~N is a query of its own, an OR of both orders at every distance up to N + 1
    lexemes apart, on the mail's side and on the documents'."""
    q = f'"Spende bar"~{distance}'
    condition = filters.mail_conditions(MailFilters(body_part="full"), parse_query(q), [])[0]
    written = sql(condition)
    phrases = 2 * (distance + 1)
    assert written.count("tsquery_phrase(") == 2 * phrases  # the mail's side and the documents'
    for apart in range(1, distance + 2):
        assert written.count(f", {apart})") == 4
    assert "websearch_to_tsquery" not in written


@pytest.mark.parametrize(
    "q", ["-after:2021-03-05", "-before:2021-03-05", "-dkim:pass", "-dkim:unchecked"]
)
def test_negated_operators_are_neither_ranges_nor_research_filters(q: str) -> None:
    plain = filters.mail_conditions(MailFilters(), parse_query(q[1:]), [])[0]
    assert filters._ranges(plain)
    negated, visible = filters.mail_conditions(MailFilters(), parse_query(q), [])
    assert visible is filters.VISIBLE
    assert not filters._ranges(negated)
    assert filters._contents(negated) is None


# The generated archive -----------------------------------------------------------------------

# The first mail whose Message-ID q reads as one (query._MESSAGE_ID).
FIRST_MESSAGE_ID = (
    "SELECT id, message_id FROM mail WHERE message_id ~ '^<[^<>\\s@]+@[^<>\\s]+>$'"
    " ORDER BY id LIMIT 1"
)

# Whole words as D173 has them: the stem in the tsvector, then the word as written in the text,
# both without the standard blocks as the default body_part has them (D226; the same as the
# whole tsvector and text while the blocks step has marked none).
SUBJECT_OR_TEXT = (
    "ts_filter(tsv, '{a,b,c}') @@ websearch_to_tsquery('german', 'Angebot')"
    " AND (subject ~* :angebot OR mailrobbe_cut(body_text, blocks) ~* :angebot)"
)
PDF_FILE = (
    "EXISTS (SELECT 1 FROM attachment a JOIN document d ON d.id = a.document_id"
    " WHERE a.mail_id = mail.id AND d.tsv @@ to_tsquery('german', 'pdf:A') AND d.names ~* :pdf)"
)
PATTERNS = {
    "angebot": "(?<![[:alnum:]])Angebot(?![[:alnum:]])",
    "pdf": "(?<![[:alnum:]])pdf(?![[:alnum:]])",
}
# The combined case: a place, whole words, a placed word with a minus, an operator with a minus.
COMBINED: Params = [
    ("q", "Angebot -datei:pdf -dkim:pass"),
    *scope("subject", "body"),
    WHOLE,
]
COMBINED_SQL = f"{SUBJECT_OR_TEXT} AND NOT {PDF_FILE} AND dkim_status IS DISTINCT FROM 'pass'"


async def test_the_combined_case_is_not_trivial(imported_database_url: str) -> None:
    """Guards the expectations below: each part of the combined case changes what it finds."""
    url = imported_database_url
    combined = set(await ids(url, COMBINED_SQL, **PATTERNS))
    assert len(combined) > 3
    stems = set(await ids(url, "tsv @@ websearch_to_tsquery('german', 'Angebot')"))
    assert combined < set(await ids(url, SUBJECT_OR_TEXT, **PATTERNS)) < stems
    unchecked = "(dkim_status IS NULL OR dkim_status <> 'pass')"
    assert await ids(url, f"{SUBJECT_OR_TEXT} AND {PDF_FILE} AND {unchecked}", **PATTERNS)
    assert await ids(
        url, f"{SUBJECT_OR_TEXT} AND NOT {PDF_FILE} AND dkim_status = 'pass'", **PATTERNS
    )


@WALKS
@pytest.mark.parametrize("sort", SORTS)
async def test_the_options_select_what_sql_selects(
    client: httpx.AsyncClient, imported_database_url: str, walk_rows: int, sort: str
) -> None:
    expected = await ids(imported_database_url, COMBINED_SQL, sort, **PATTERNS)
    assert await walked_and_collected(client, [*COMBINED, ("sort", sort)]) == expected


async def test_summary_csv_and_timeline_count_the_same_mails(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    expected = await ids(imported_database_url, COMBINED_SQL, "date_asc", **PATTERNS)
    summary = await get(client, "/api/mails/summary", COMBINED)
    assert (summary["total"], summary["exact"]) == (len(expected), True)
    exported = await export(client, [*COMBINED, ("sort", "date_asc")])
    assert [int(row[0]) for row in exported] == expected
    timeline = await get(client, "/api/timeline", COMBINED)
    assert sum(timeline["total"]["counts"]) + timeline["undated"] == len(expected)


@pytest.fixture
async def imported_session(imported_database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(imported_database_url, poolclass=pool.NullPool)
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()


async def test_bulk_changes_and_exports_select_the_same_mails(
    imported_session: AsyncSession, imported_database_url: str
) -> None:
    settings = Settings(database_url=imported_database_url)
    chosen = MailFilters(
        q="Angebot -datei:pdf -dkim:pass", scope=["subject", "body"], whole_word=True
    )
    mails = await resolve_selection(imported_session, settings, MailSelection(filters=chosen), 600)
    expected = await ids(imported_database_url, COMBINED_SQL, "date_asc", **PATTERNS)
    assert [mail.id for mail in mails] == expected


@WALKS
@pytest.mark.parametrize("sort", SORTS)
async def test_negated_operators_select_what_sql_selects(
    client: httpx.AsyncClient, imported_database_url: str, walk_rows: int, sort: str
) -> None:
    url = imported_database_url
    sender = (
        await rows(
            url,
            "SELECT p.canonical_email FROM participation pa JOIN person p ON p.id = pa.person_id"
            " WHERE pa.role = 'from' GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1",
        )
    )[0].canonical_email
    message_id = (await rows(url, FIRST_MESSAGE_ID))[0].message_id
    named = (
        "(strpos(lower(p.canonical_email), lower(:sender)) > 0"
        " OR strpos(lower(COALESCE(p.display_name, '')), lower(:sender)) > 0)"
    )
    cases: list[tuple[Params, str]] = [
        ([("q", "-has:attachment")], "NOT has_attachments"),
        (
            [("q", "-dkim:pass -DKIM:no_key")],
            "dkim_status IS NULL OR dkim_status NOT IN ('pass', 'no_key')",
        ),
        ([("q", "-before:2016-01-01")], "date_utc IS NULL OR date_utc >= '2016-01-01Z'"),
        (
            [("q", "-after:1.1.2016 has:attachment")],
            "(date_utc IS NULL OR date_utc < '2016-01-01Z') AND has_attachments",
        ),
        ([("q", "-subject:re")], "subject IS NULL OR subject NOT ILIKE '%re%'"),
        (
            [("q", f"-from:{sender}")],
            f"NOT {takes_part(named, SENDER)}",
        ),
        ([("q", f"-{message_id}")], "message_id IS DISTINCT FROM :message_id"),
    ]
    for params, where in cases:
        expected = await ids(url, where, sort, sender=sender, message_id=message_id)
        assert expected, params
        found = await walked_and_collected(client, [*params, ("sort", sort)], PAGE)
        assert found == expected, params


async def test_negated_operators_hold_where_the_condition_cannot_be_decided(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    """An unchecked mail matches -dkim:pass, an undated one -before: and -after:, one without a
    subject -subject:, one without a Message-ID -<id>."""
    url = mutable_database_url
    chosen = (await rows(url, FIRST_MESSAGE_ID))[0]
    await rows(
        url,
        "UPDATE mail SET dkim_status = NULL, date_utc = NULL, subject = NULL, message_id = NULL"
        " WHERE id = :chosen",
        chosen=chosen.id,
    )
    for q, where in [
        ("-dkim:pass", "dkim_status IS DISTINCT FROM 'pass'"),
        ("-before:2016-01-01", "date_utc IS NULL OR date_utc >= '2016-01-01Z'"),
        ("-after:2016-01-01", "date_utc IS NULL OR date_utc < '2016-01-01Z'"),
        ("-subject:re", "subject IS NULL OR subject NOT ILIKE '%re%'"),
        (f"-{chosen.message_id}", "message_id IS DISTINCT FROM :message_id"),
    ]:
        expected = await ids(url, where, message_id=chosen.message_id)
        assert chosen.id in expected, q
        assert await walked_and_collected(mutable_client, [("q", q)], PAGE) == expected, q


def test_only_the_hidden_mails_left_out_counts_as_unfiltered() -> None:
    assert filters.mail_conditions(MailFilters(), [], []) == [filters.VISIBLE]
    assert filters.unfiltered(filters.mail_conditions(MailFilters(), [], []))
    assert filters.mail_conditions(MailFilters(include_hidden=True), [], []) == []
    assert not filters.unfiltered(filters.mail_conditions(MailFilters(), parse_query("Rat"), []))

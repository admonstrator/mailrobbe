"""How often the search words occur, by place (D174, D176): hit_count for min_hits, the hits of
the list's page and of one mail, on the search cases (tests/api/search_cases.py), whose table
of hits for "Neger" the expectations below follow."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import pool, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailrobbe.api.documents import _hit_snippets
from mailrobbe.api.fulltext import FIELDS, Words, full_text_search
from mailrobbe.api.hits import hit_count, page_hits
from mailrobbe.api.query import parse_query
from mailrobbe.api.schemas import MIN_HITS_LIMIT
from mailrobbe.db.models import Document, Mail
from tests.api.conftest import search_ids
from tests.api.search_cases import CASES, message_id
from tests.api.test_mails import Params, get, pages

# Per case: the occurrences in subject, body, attachment texts and file names; cases without
# any are left out.
Counts = dict[int, tuple[int, int, int, int]]
NEGER: Counts = {
    0: (1, 3, 0, 0),
    1: (0, 1, 0, 0),
    2: (0, 1, 0, 0),
    3: (0, 1, 0, 0),
    4: (0, 1, 0, 0),
    5: (0, 0, 0, 2),
    6: (0, 0, 1, 0),
    7: (1, 6, 0, 0),
}
NEGER_WHOLE: Counts = {0: (1, 3, 0, 0), 1: (0, 1, 0, 0), 6: (0, 0, 1, 0), 7: (1, 6, 0, 0)}
NOTHING = (0, 0, 0, 0)


@pytest.fixture
async def session(search_database_url: str) -> AsyncIterator[AsyncSession]:
    """A session on the search cases' database. Read only."""
    engine = create_async_engine(search_database_url, poolclass=pool.NullPool)
    try:
        async with AsyncSession(engine) as session:
            yield session
    finally:
        await engine.dispose()


async def counted(session: AsyncSession, q: str, **options: Any) -> Counts:
    """page_hits for every case with an occurrence, each checked against hit_count: the figure
    the list shows is the one min_hits compares (D176)."""
    search = full_text_search(parse_query(q), **options)
    assert search is not None
    rows = await session.execute(select(Mail.message_id, Mail.id, hit_count(search)))
    cases = {message: (mail_id, total) for message, mail_id, total in rows}
    hits = await page_hits(session, [mail_id for mail_id, _ in cases.values()], search)
    found: Counts = {}
    for index in range(len(CASES)):
        mail_id, total = cases[message_id(index)]
        places = tuple(getattr(hits[mail_id], field) for field in FIELDS)
        assert sum(places) == total, (index, places, total)
        if any(places):
            found[index] = (places[0], places[1], places[2], places[3])
    return found


@pytest.mark.parametrize(
    ("q", "options", "expected"),
    [
        ("Neger", {}, NEGER),
        ("Neger", {"whole_word": True}, NEGER_WHOLE),
        ("NEGER", {"whole_word": True}, NEGER_WHOLE),
        ("Neger", {"scope": ["subject"]}, {0: (1, 0, 0, 0), 7: (1, 0, 0, 0)}),
        ("Neger", {"scope": ["attachment", "filename"]}, {5: (0, 0, 0, 2), 6: (0, 0, 1, 0)}),
        ("Neger", {"scope": ["filename"], "whole_word": True}, {}),
        # negated words are not counted, also not alone
        ("Neger -Witze -datei:NEG", {}, NEGER),
        ("-Neger", {}, {}),
        # two words add up; or joins alternatives, each counted
        ("Stammtisch Neger", {}, {**NEGER, 1: (1, 2, 0, 0)}),
        ("Neger or Protokoll", {}, {**NEGER, 6: (1, 1, 1, 1)}),
        # a phrase and a hyphenated word count as their least frequent lexeme
        ('"Wort Neger"', {}, {0: (0, 1, 0, 0), 1: (0, 1, 0, 0)}),
        ('"Wort Neger"', {"whole_word": True}, {0: (0, 1, 0, 0), 1: (0, 1, 0, 0)}),
        ("Neger-Witz", {}, {0: (1, 2, 0, 0)}),
        ("Neger-Witz", {"whole_word": True}, {0: (0, 1, 0, 0)}),
        # stop words have no lexeme: nothing to count
        ("die", {}, {}),
    ],
)
async def test_counts_by_place(
    session: AsyncSession, q: str, options: dict[str, Any], expected: Counts
) -> None:
    assert await counted(session, q, **options) == expected


@pytest.mark.parametrize(
    ("q", "options", "expected"),
    [
        ("betreff:Neger", {}, {0: (1, 0, 0, 0), 7: (1, 0, 0, 0)}),
        ("text:Neger", {"whole_word": True}, {0: (0, 3, 0, 0), 1: (0, 1, 0, 0), 7: (0, 6, 0, 0)}),
        ("anhang:Neger", {}, {6: (0, 0, 1, 0)}),
        ("datei:NEG", {}, {5: (0, 0, 0, 2)}),
        ("datei:neg", {"whole_word": True}, {5: (0, 0, 0, 2)}),
        # free words in the chosen places, placed words in their own place whatever the scope
        (
            "Neger datei:NEG",
            {"scope": ["body"]},
            {
                0: (0, 3, 0, 0),
                1: (0, 1, 0, 0),
                2: (0, 1, 0, 0),
                3: (0, 1, 0, 0),
                4: (0, 1, 0, 0),
                5: (0, 0, 0, 2),
                7: (0, 6, 0, 0),
            },
        ),
    ],
)
async def test_placed_words_count_in_their_place_only(
    session: AsyncSession, q: str, options: dict[str, Any], expected: Counts
) -> None:
    assert await counted(session, q, **options) == expected


async def test_page_hits_has_every_mail_of_the_page(session: AsyncSession) -> None:
    search = full_text_search(parse_query("Neger"))
    assert search is not None
    hits = await page_hits(session, [999_999, 999_998], search)
    assert {mail_id: tuple(counts.model_dump().values()) for mail_id, counts in hits.items()} == {
        999_999: NOTHING,
        999_998: NOTHING,
    }
    assert await page_hits(session, [], search) == {}


async def case_ids(client: httpx.AsyncClient, params: Params, limit: int = 50) -> list[int]:
    """The cases the list finds, every page followed, in list order."""
    cases = {mail_id: index for index, mail_id in (await search_ids(client)).items()}
    found = await pages(client, [*params, ("sort", "date_asc")], limit=limit)
    return [cases[item["id"]] for page in found for item in page["items"]]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ([("q", "Neger"), ("min_hits", "1")], list(range(8))),
        ([("q", "Neger"), ("min_hits", "2")], [0, 5, 7]),
        ([("q", "Neger"), ("min_hits", "3")], [0, 7]),
        ([("q", "Neger"), ("min_hits", "4")], [0, 7]),
        ([("q", "Neger"), ("min_hits", "5")], [7]),
        ([("q", "Neger"), ("min_hits", "7")], [7]),
        ([("q", "Neger"), ("min_hits", "8")], []),
        ([("q", "Neger"), ("min_hits", str(MIN_HITS_LIMIT))], []),
        ([("q", "Neger"), ("whole_word", "true"), ("min_hits", "2")], [0, 7]),
        ([("q", "Neger Stammtisch"), ("min_hits", "3")], [1]),
        ([("q", "Neger Stammtisch"), ("min_hits", "4")], []),
        ([("q", "Neger"), ("min_hits", "2"), ("has_attachment", "true")], [5]),
    ],
)
async def test_min_hits_keeps_the_mails_with_enough_occurrences(
    search_client: httpx.AsyncClient, params: Params, expected: list[int]
) -> None:
    # pages of one: the bounded walk of the list (filters.first_ids), and all at once
    assert await case_ids(search_client, params, limit=1) == expected
    assert await case_ids(search_client, params) == expected
    summary = await get(search_client, "/api/mails/summary", params)
    assert (summary["total"], summary["exact"]) == (len(expected), True)


@pytest.mark.parametrize("value", ["0", str(MIN_HITS_LIMIT + 1), "zwei"])
async def test_min_hits_out_of_range_is_refused(
    search_client: httpx.AsyncClient, value: str
) -> None:
    await get(search_client, "/api/mails", [("q", "Neger"), ("min_hits", value)], status=422)


def _places(item: Any) -> tuple[int, ...]:
    return tuple(item["hits"][field] for field in FIELDS)


async def test_the_list_shows_where_the_words_occur(search_client: httpx.AsyncClient) -> None:
    cases = {mail_id: index for index, mail_id in (await search_ids(search_client)).items()}

    async def items(*params: tuple[str, str]) -> dict[int, Any]:
        page = await get(search_client, "/api/mails", [*params, ("sort", "date_asc")])
        return {cases[item["id"]]: item for item in page["items"]}

    found = await items(("q", "Neger"))
    assert {case: _places(item) for case, item in found.items()} == NEGER
    # found through an attachment alone: its text (6) or its file names (5)
    assert {case for case, item in found.items() if item["attachment_match"]} == {5, 6}
    # whole words: the stems' forms count nothing, wherever the list finds them
    whole = await items(("q", "Neger"), ("whole_word", "true"))
    assert {0, 1, 6, 7} <= set(whole)
    for case, item in whole.items():
        assert _places(item) == NEGER_WHOLE.get(case, NOTHING), case
        assert item["attachment_match"] is (case == 6), case
    # a placed word: the file names of case 5
    placed = await items(("q", "datei:NEG"))
    assert _places(placed[5]) == (0, 0, 0, 2) and placed[5]["attachment_match"] is True
    assert all(_places(item) == NOTHING for case, item in placed.items() if case != 5)
    # no full text words: no hits
    assert all(item["hits"] is None for item in (await items(("q", "has:attachment"))).values())
    assert all(item["hits"] is None for item in (await items()).values())


async def test_the_hits_of_a_mail_follow_places_and_whole_words(
    search_client: httpx.AsyncClient,
) -> None:
    ids = await search_ids(search_client)

    async def hits(case: int, *params: tuple[str, str]) -> Any:
        return await get(search_client, f"/api/mails/{ids[case]}/hits", params)

    def counts(*places: int) -> dict[str, int]:
        return dict(zip(FIELDS, places, strict=True))

    # the file names hold the stem: listed by name, no text, no snippet
    five = await hits(5, ("q", "Neger"))
    assert (five["in_mail"], five["counts"]) == (False, counts(0, 0, 0, 2))
    assert [(a["in_name"], a["in_text"], a["snippet"]) for a in five["attachments"]] == [
        (True, False, None),
        (True, False, None),
    ]
    # without the file names among the places nothing is left
    narrowed = await hits(
        5, ("q", "Neger"), ("scope", "subject"), ("scope", "body"), ("scope", "attachment")
    )
    assert (narrowed["attachments"], narrowed["counts"]) == ([], counts(0, 0, 0, 0))
    # French "negere": a hit of the stem, none as a whole word, whose stems are not marked
    assert (await hits(3, ("q", "Neger")))["in_body"] is True
    assert await hits(3, ("q", "Neger"), ("whole_word", "true")) == {
        "words": ["Neger"],
        "stems": [],
        "in_mail": False,
        "attachments": [],
        "whole_word": True,
        "in_subject": False,
        "in_body": False,
        "counts": counts(0, 0, 0, 0),
    }
    # subject and text apart, in the chosen places only
    subject = await hits(0, ("q", "Neger"), ("scope", "subject"))
    assert (subject["in_subject"], subject["in_body"], subject["in_mail"]) == (True, False, True)
    assert subject["counts"] == counts(1, 0, 0, 0)
    # an attachment's text, with the snippet of the word as written
    six = await hits(6, ("q", "neger"), ("whole_word", "true"))
    assert (six["words"], six["in_mail"], six["counts"]) == (["neger"], False, counts(0, 0, 1, 0))
    [attachment] = six["attachments"]
    assert (attachment["in_name"], attachment["in_text"]) == (False, True)
    assert "man solle die Neger zurückschicken" in attachment["snippet"]
    # placed words are words of the mail list too, looked for in their place
    placed = await hits(0, ("q", "betreff:Neger text:Witze -datei:NEG"))
    assert (placed["words"], placed["stems"]) == (["Neger", "Witze"], ["neg", "witz"])
    assert (placed["in_subject"], placed["in_body"]) == (True, True)
    assert placed["counts"] == counts(1, 2, 0, 0)
    # quoted words count as written, the others by their stems, which alone are marked (D341)
    quoted = await hits(7, ("q", '"Neger raus" Neger'))
    assert (quoted["words"], quoted["stems"]) == (["Neger raus", "Neger"], ["neg"])
    assert quoted["counts"] == counts(2, 9, 0, 0)
    assert (await hits(2, ("q", '"Negern"')))["counts"] == counts(0, 1, 0, 0)
    file_names = await hits(5, ("q", "datei:NEG"))
    assert (file_names["words"], file_names["counts"]) == (["NEG"], counts(0, 0, 0, 2))
    # a search without full text words echoes the option
    assert (await hits(0, ("q", "from:karl"), ("whole_word", "true")))["whole_word"] is True


async def test_whole_words_find_the_snippet_around_the_word_as_written(
    db_session: AsyncSession,
) -> None:
    text = "Die Negern vorne. " + "Lorem ipsum dolor sit amet. " * 30 + "Das Wort Neger allein."
    document = Document(names="x.txt", mime_type="text/plain", size_bytes=1, extracted_text=text)
    db_session.add(document)
    await db_session.flush()
    neger = Words("Neger")

    async def snippets(q: str, whole_word: bool) -> dict[int, str]:
        search = full_text_search(parse_query(q), whole_word=whole_word)
        assert search is not None
        words = [words for words, _ in search.counted]
        return await _hit_snippets(db_session, search, words, {neger: ["neg"]}, [document.id])

    assert (await snippets("Neger", True))[document.id].endswith("Das Wort Neger allein.")
    assert (await snippets("Neger", False))[document.id].startswith("Die Negern vorne.")
    # a quoted word is looked for as written (D341)
    assert (await snippets('"Neger"', False))[document.id].endswith("Das Wort Neger allein.")

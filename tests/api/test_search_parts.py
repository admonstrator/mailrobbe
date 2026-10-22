"""The parts of a mail's text in the search (D226, D228) and proximity terms (D229), on a small
archive of its own whose quotes and standard blocks are set by hand (mail.history and
mail.blocks; the trigger weighs mail.tsv by them), as the blocks step would set them.

Each mail has the Message-ID <teil-N@verein.example>, N its index in PARTS; the words placed in
its own text, quote and standard block test one rule each:

    N   own text            quote (C)           standard block (D)      note
    0   Kasse               Beleg               Rechtshinweis
    1   Kasse Beleg Rechtshinweis (no ranges, all B)
    2   Beleg               Kasse                                       subject Rechtshinweis
    3   Wochenrückblick     Kasse, a block      Rechtshinweis (in the quote)
    4   Kassen                                  Kasse Rechtshinweis     the stem only outside
    5   Kasse x2            Kasse x1            Kasse x3                counts per part
    6   Spende … bar, 2 words between
    7   Spende … bar, 20 words between
    8   Spende … bar, 21 words between
    9   bar … Spende, 2 words between
    10  -  (Spende wurde bar in an attachment's text)
    11  Notiz                                   Spende bitte bar
    12  Danke               Spende in bar
    13  Spenden kamen bar                                               Spenden: the stem only
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import pool, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailrobbe import migrate
from mailrobbe.api.fulltext import FIELDS, full_text_search
from mailrobbe.api.hits import hit_count, page_hits
from mailrobbe.api.query import parse_query
from mailrobbe.api.schemas import PROXIMITY_LIMIT
from mailrobbe.config import Settings
from mailrobbe.db.models import Mail
from mailrobbe.importer.cli import run_import
from tests.api.conftest import _client
from tests.api.search_cases import message_id, write_cases
from tests.api.test_mails import Params, get
from tests.api.test_search_conditions import walked_and_collected
from tests.conftest import _temporary_database

pytestmark = pytest.mark.db

SENDER, RECIPIENT = "lea.wagner@verein.example", "vorstand@verein.example"
NOTICE = "Rechtshinweis: Diese Nachricht ist vertraulich."
FILLER = "Füllwort " * 20


@dataclass(frozen=True, slots=True)
class Part:
    """A mail of PARTS: the quote runs from the text `quote` to the end, each block is the first
    occurrence of its text."""

    subject: str
    body: str
    quote: str | None = None
    blocks: tuple[str, ...] = ()
    attachments: tuple[tuple[str, str], ...] = ()


PARTS = [
    Part(
        "Vereinskasse",
        f"Die Kasse ist geprüft.\n\n{NOTICE}\n\nAm 2. März schrieb Lea:\n> Bitte den Beleg.\n",
        quote="Am 2. März",
        blocks=(NOTICE,),
    ),
    Part("Ohne Bereiche", f"Die Kasse und der Beleg. {NOTICE}\n"),
    Part(
        "Rechtshinweis",
        "Der Beleg liegt bei.\n\nAm 3. März schrieb Karl:\n> Die Kasse stimmt.\n",
        quote="Am 3. März",
    ),
    Part(
        "Rückblick",
        f"Der Wochenrückblick folgt.\n\nAm 4. März schrieb Lea:\n> {NOTICE}\n> Die Kasse fehlt.\n",
        quote="Am 4. März",
        blocks=(NOTICE,),
    ),
    Part(
        "Kassenprüfung",
        "Die Kassen sind geprüft.\n\nRechtshinweis: Die Kasse haftet nicht.\n",
        blocks=("Rechtshinweis: Die Kasse haftet nicht.",),
    ),
    Part(
        "Zählung",
        "Kasse und Kasse.\n\nKasse, Kasse, Kasse.\n\nAm 6. März schrieb Lea:\n> Die Kasse.\n",
        quote="Am 6. März",
        blocks=("Kasse, Kasse, Kasse.",),
    ),
    Part("Eingang", "Die Spende kam gestern bar an.\n"),
    Part("Lang", f"Spende {FILLER}bar.\n"),
    Part("Länger", f"Spende {FILLER}Füllwort bar.\n"),
    Part("Umgekehrt", "Bar bezahlt, die Spende ist da.\n"),
    Part(
        "Liste",
        "Anbei die Liste.\n",
        attachments=(("Liste.txt", "Die Spende wurde bar übergeben."),),
    ),
    Part("Hinweis", "Kurze Notiz.\n\nSpende bitte bar.\n", blocks=("Spende bitte bar.",)),
    Part(
        "Antwort",
        "Danke.\n\nAm 7. März schrieb Karl:\n> Spende in bar.\n",
        quote="Am 7. März",
    ),
    Part("Mehrzahl", "Die Spenden kamen bar.\n"),
]


def _ranges(spans: list[tuple[int, int]]) -> str | None:
    return "{" + ",".join(f"[{start},{end})" for start, end in spans) + "}" if spans else None


async def _set_ranges(url: str) -> None:
    """mail.history and mail.blocks of every mail as PARTS has them, from its stored text."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            for index, part in enumerate(PARTS):
                found = message_id(index, "teil")
                body = await connection.scalar(
                    text("SELECT body_text FROM mail WHERE message_id = :m"), {"m": found}
                )
                assert body is not None, found
                quote = [] if part.quote is None else [(body.index(part.quote), len(body))]
                blocks = [(body.index(b), body.index(b) + len(b)) for b in part.blocks]
                await connection.execute(
                    text(
                        "UPDATE mail SET history = CAST(CAST(:history AS text) AS int4multirange),"
                        " blocks = CAST(CAST(:blocks AS text) AS int4multirange)"
                        " WHERE message_id = :m"
                    ),
                    {"history": _ranges(quote), "blocks": _ranges(blocks), "m": found},
                )
            await connection.execute(text("ANALYZE mail"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def parts_archive(tmp_path_factory: pytest.TempPathFactory) -> Path:
    mbox_dir = tmp_path_factory.mktemp("parts") / "mbox"
    mbox_dir.mkdir()
    cases = [
        (SENDER, RECIPIENT, part.subject, part.body.rstrip("\n"), list(part.attachments))
        for part in PARTS
    ]
    write_cases(mbox_dir / "teile.mbox", cases, "teil")
    return mbox_dir


@pytest.fixture(scope="session")
def parts_database_url(database_server_url: str, parts_archive: Path) -> Iterator[str]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        assert asyncio.run(run_import(Settings(database_url=url), parts_archive, 1)) == 0
        asyncio.run(_set_ranges(url))
        yield url


@pytest.fixture
async def parts_client(
    parts_database_url: str, parts_archive: Path, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Client on the parts' database. Read only."""
    settings = Settings(
        database_url=parts_database_url,
        mbox_dir=parts_archive,
        frontend_dir=tmp_path / "no-frontend",
    )
    async for http in _client(settings):
        yield http


@pytest.fixture
async def parts_session(parts_database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(parts_database_url, poolclass=pool.NullPool)
    try:
        async with AsyncSession(engine) as session:
            yield session
    finally:
        await engine.dispose()


async def case_of(client: httpx.AsyncClient) -> dict[int, int]:
    """Case index by mail id."""
    page = await get(client, "/api/mails", [("sort", "date_asc"), ("include_hidden", "true")])
    found = {}
    for item in page["items"]:
        detail = await get(client, f"/api/mails/{item['id']}")
        found[item["id"]] = int(detail["message_id"].split("-")[1].split("@")[0])
    assert sorted(found.values()) == list(range(len(PARTS)))
    return found


def part(name: str) -> Params:
    return [("body_part", name)]


def scope(*places: str) -> Params:
    return [("scope", place) for place in places]


WHOLE = ("whole_word", "true")
NEAR = '"Spende bar"~2'
ALL = set(range(len(PARTS)))

# (name, q, other parameters, the cases found)
SEARCHES: list[tuple[str, str, Params, set[int]]] = [
    # The parts of the text (D226): clean (the default) leaves the standard blocks out, own
    # the quotes too, full looks at everything; a mail without ranges is all own text.
    ("clean", "Kasse", [], {0, 1, 2, 3, 4, 5}),
    ("clean-by-name", "Kasse", part("clean"), {0, 1, 2, 3, 4, 5}),
    ("own", "Kasse", part("own"), {0, 1, 4, 5}),
    ("full", "Kasse", part("full"), {0, 1, 2, 3, 4, 5}),
    ("quoted-clean", "Beleg", [], {0, 1, 2}),
    ("quoted-own", "Beleg", part("own"), {1, 2}),
    ("block-clean", "Rechtshinweis", [], {1, 2}),
    ("block-own", "Rechtshinweis", part("own"), {1, 2}),
    ("block-full", "Rechtshinweis", part("full"), {0, 1, 2, 3, 4}),
    ("own-everywhere", "Wochenrückblick", part("own"), {3}),
    # The places (D171) combine with the parts; without the text the parts do not matter.
    ("text-clean", "Rechtshinweis", scope("body"), {1}),
    ("text-full", "Rechtshinweis", [*scope("body"), *part("full")], {0, 1, 3, 4}),
    ("subject-clean", "Rechtshinweis", scope("subject"), {2}),
    ("subject-own", "Rechtshinweis", [*scope("subject"), *part("own")], {2}),
    ("subject-full", "Rechtshinweis", [*scope("subject"), *part("full")], {2}),
    # Placed words: text: is the parts of the text, betreff: the subject (D172).
    ("placed-own", "text:Kasse", part("own"), {0, 1, 4, 5}),
    ("placed-clean", "text:Rechtshinweis", [], {1}),
    ("placed-full", "text:Rechtshinweis", part("full"), {0, 1, 3, 4}),
    ("placed-subject", "betreff:Rechtshinweis", part("own"), {2}),
    ("placed-minus-own", "-text:Beleg Kasse", part("own"), {0, 4, 5}),
    ("minus-own", "Kasse -Beleg", part("own"), {0, 4, 5}),
    # Whole words (D173) decide on the text cut to the parts: case 4 holds the stem outside
    # its block and the word as written inside only.
    ("whole-clean", "Kasse", [WHOLE], {0, 1, 2, 3, 5}),
    ("whole-own", "Kasse", [WHOLE, *part("own")], {0, 1, 5}),
    ("whole-full", "Kasse", [WHOLE, *part("full")], {0, 1, 2, 3, 4, 5}),
    ("whole-block", "Rechtshinweis", [WHOLE, *scope("body"), *part("full")], {0, 1, 3, 4}),
    ("whole-placed-own", "text:Beleg", [WHOLE, *part("own")], {1, 2}),
    # Proximity (D229): both orders, the stems, at most N words between, in the places and
    # parts chosen, the attachments' texts too.
    ("near", NEAR, [], {6, 9, 10, 12, 13}),
    ("near-reversed", '"bar Spende"~2', [], {6, 9, 10, 12, 13}),
    ("near-one", '"Spende bar"~1', [], {10, 12, 13}),
    ("near-at-the-limit", f'"Spende bar"~{PROXIMITY_LIMIT}', [], {6, 7, 9, 10, 12, 13}),
    ("near-own", NEAR, part("own"), {6, 9, 10, 13}),
    ("near-full", NEAR, part("full"), {6, 9, 10, 11, 12, 13}),
    ("near-attachments", NEAR, scope("attachment"), {10}),
    ("near-subject", NEAR, scope("subject"), set()),
    ("near-and-a-word", f"Liste {NEAR}", [], {10}),
    ("near-and-an-operator", f"{NEAR} has:attachment", [], {10}),
    ("near-minus", f"Spende -{NEAR}", [], {7, 8}),
    ("near-minus-alone", f"-{NEAR}", [], ALL - {6, 9, 10, 12, 13}),
    ("near-whole", NEAR, [WHOLE], {6, 9, 10, 12}),
    ("near-whole-at-the-limit", f'"Spende bar"~{PROXIMITY_LIMIT}', [WHOLE], {6, 7, 9, 10, 12}),
    ("near-whole-own", NEAR, [WHOLE, *part("own")], {6, 9, 10}),
    ("near-whole-full", NEAR, [WHOLE, *part("full")], {6, 9, 10, 11, 12}),
    ("near-whole-minus", f"Spende -{NEAR}", [WHOLE], {7, 8}),
]


@pytest.mark.parametrize(
    ("q", "params", "cases"),
    [search[1:] for search in SEARCHES],
    ids=[search[0] for search in SEARCHES],
)
async def test_the_parts_and_proximity_find_their_mails(
    parts_client: httpx.AsyncClient, q: str, params: Params, cases: set[int]
) -> None:
    found = await case_of(parts_client)
    search = [("q", q), *params]
    listed = await walked_and_collected(parts_client, search)
    assert {found[mail_id] for mail_id in listed} == cases
    summary = await get(parts_client, "/api/mails/summary", search)
    assert summary["total"] == len(cases)


@pytest.mark.parametrize(
    "q",
    ['"Spende bar"~0', f'"Spende bar"~{PROXIMITY_LIMIT + 1}', '"Spende"~3', '"Spende bar Kasse"~3'],
)
async def test_an_unusable_proximity_term_is_refused(
    parts_client: httpx.AsyncClient, q: str
) -> None:
    error = await get(parts_client, "/api/mails", [("q", f"Kasse {q}")], status=400)
    assert error["detail"]["code"] == "invalid_query"
    assert error["detail"]["message"].endswith(q)


Counts = dict[int, tuple[int, int, int, int]]


async def counted(session: AsyncSession, q: str, **options: Any) -> Counts:
    """page_hits for every case with an occurrence, each checked against hit_count."""
    search = full_text_search(parse_query(q), **options)
    assert search is not None
    rows = await session.execute(select(Mail.message_id, Mail.id, hit_count(search)))
    cases = {message: (mail_id, total) for message, mail_id, total in rows}
    hits = await page_hits(session, [mail_id for mail_id, _ in cases.values()], search)
    found: Counts = {}
    for index in range(len(PARTS)):
        mail_id, total = cases[message_id(index, "teil")]
        places = tuple(getattr(hits[mail_id], field) for field in FIELDS)
        assert sum(places) == total, (index, places, total)
        if any(places):
            found[index] = (places[0], places[1], places[2], places[3])
    return found


@pytest.mark.parametrize(
    ("q", "options", "expected"),
    [
        # case 4's "Kassen" is the stem outside the block
        ("Kasse", {}, {i: (0, 1, 0, 0) for i in (0, 1, 2, 3, 4)} | {5: (0, 3, 0, 0)}),
        (
            "Kasse",
            {"body_part": "own"},
            {0: (0, 1, 0, 0), 1: (0, 1, 0, 0), 4: (0, 1, 0, 0)} | {5: (0, 2, 0, 0)},
        ),
        (
            "Kasse",
            {"body_part": "full"},
            {i: (0, 1, 0, 0) for i in (0, 1, 2, 3)} | {4: (0, 2, 0, 0), 5: (0, 6, 0, 0)},
        ),
        (
            "Kasse",
            {"whole_word": True},
            {i: (0, 1, 0, 0) for i in (0, 1, 2, 3)} | {5: (0, 3, 0, 0)},
        ),
        (
            "Kasse",
            {"whole_word": True, "body_part": "own"},
            {0: (0, 1, 0, 0), 1: (0, 1, 0, 0), 5: (0, 2, 0, 0)},
        ),
        (
            "Kasse",
            {"whole_word": True, "body_part": "full"},
            {i: (0, 1, 0, 0) for i in (0, 1, 2, 3, 4)} | {5: (0, 6, 0, 0)},
        ),
        # a proximity term counts as its least frequent lexeme where its words stand near
        # each other, in its places and parts
        (NEAR, {}, {i: (0, 1, 0, 0) for i in (6, 9, 12, 13)} | {10: (0, 0, 1, 0)}),
        (
            NEAR,
            {"body_part": "full"},
            {i: (0, 1, 0, 0) for i in (6, 9, 11, 12, 13)} | {10: (0, 0, 1, 0)},
        ),
        (NEAR, {"whole_word": True}, {i: (0, 1, 0, 0) for i in (6, 9, 12)} | {10: (0, 0, 1, 0)}),
        (f"-{NEAR}", {}, {}),
    ],
)
async def test_the_counts_follow_the_parts(
    parts_session: AsyncSession, q: str, options: dict[str, Any], expected: Counts
) -> None:
    assert await counted(parts_session, q, **options) == expected


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ([("q", "Kasse"), ("min_hits", "3")], {5}),
        ([("q", "Kasse"), ("min_hits", "3"), *part("own")], set()),
        ([("q", "Kasse"), ("min_hits", "2"), *part("own")], {5}),
        ([("q", "Kasse"), ("min_hits", "6"), *part("full")], {5}),
        ([("q", "Kasse"), ("min_hits", "2"), *part("full")], {4, 5}),
        ([("q", "Kasse"), ("min_hits", "3"), WHOLE], {5}),
        ([("q", "Kasse"), ("min_hits", "2"), WHOLE, *part("full")], {5}),
        ([("q", f"Kasse {NEAR}"), ("min_hits", "2")], set()),
        ([("q", f"Spende {NEAR}"), ("min_hits", "2")], {6, 9, 10, 12, 13}),
    ],
)
async def test_min_hits_counts_the_parts(
    parts_client: httpx.AsyncClient, params: Params, expected: set[int]
) -> None:
    found = await case_of(parts_client)
    listed = await walked_and_collected(parts_client, params)
    assert {found[mail_id] for mail_id in listed} == expected
    page = await get(parts_client, "/api/mails", [*params, ("limit", "200")])
    assert all(item["hits"]["body"] + item["hits"]["attachment"] >= 2 for item in page["items"])


async def test_the_list_shows_the_counts_of_the_parts(parts_client: httpx.AsyncClient) -> None:
    cases = {index: mail_id for mail_id, index in (await case_of(parts_client)).items()}

    async def body(*params: tuple[str, str]) -> int:
        page = await get(parts_client, "/api/mails", [("q", "Kasse"), *params, ("limit", "200")])
        [item] = [item for item in page["items"] if item["id"] == cases[5]]
        return int(item["hits"]["body"])

    assert (await body(), await body(*part("own")), await body(*part("full"))) == (3, 2, 6)


async def test_the_hits_of_a_mail_follow_the_parts(parts_client: httpx.AsyncClient) -> None:
    cases = {index: mail_id for mail_id, index in (await case_of(parts_client)).items()}

    async def hits(case: int, *params: tuple[str, str]) -> Any:
        return await get(parts_client, f"/api/mails/{cases[case]}/hits", params)

    # a word in the quote only: in the text by default, not among the own words
    clean = await hits(2, ("q", "Kasse"))
    assert (clean["in_body"], clean["counts"]["body"]) == (True, 1)
    own = await hits(2, ("q", "Kasse"), ("body_part", "own"))
    assert (own["in_body"], own["in_mail"], own["counts"]["body"]) == (False, False, 0)
    assert own["words"] == ["Kasse"]  # the words to mark stay the typed ones
    # a word in a standard block only: with full
    assert (await hits(0, ("q", "Rechtshinweis")))["in_body"] is False
    assert (await hits(0, ("q", "Rechtshinweis"), ("body_part", "full")))["in_body"] is True
    # a proximity term marks its two words, counted as its least frequent lexeme
    near = await hits(6, ("q", NEAR))
    assert (near["words"], near["stems"]) == (["Spende", "bar"], ["spend", "bar"])
    assert (near["in_body"], near["counts"]["body"]) == (True, 1)
    # in an attachment's text, as whole words, with the snippet around them
    attached = await hits(10, ("q", NEAR), ("whole_word", "true"))
    [attachment] = attached["attachments"]
    assert (attached["in_mail"], attachment["in_text"]) == (False, True)
    assert "Spende wurde bar übergeben" in attachment["snippet"]
    beyond = await hits(10, ("q", '"Spende übergeben"~1'), ("whole_word", "true"))
    assert beyond["attachments"] == [] and beyond["counts"]["attachment"] == 0


async def test_the_query_terms_echo_the_distance(parts_client: httpx.AsyncClient) -> None:
    page = await get(parts_client, "/api/mails", [("q", f"Kasse -{NEAR}")])
    assert [
        (t["key"], t["value"], t["raw"], t["negated"], t["distance"]) for t in page["query_terms"]
    ] == [
        ("text", "Kasse", "Kasse", False, None),
        ("near", "Spende bar", f"-{NEAR}", True, 2),
    ]

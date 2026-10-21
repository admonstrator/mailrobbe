"""The document API (D70 to D77): the document list with its filters, sorts, paging and
snippets, its summary, a document's page and text, attachment downloads, the mail list's filter
by document and its search through attachments (D73), and the import summary's figures.

Two archives. The generated one (tests/api/conftest.py), where expectations come from SQL
written apart from api/documents.py, from the stored hashes and from extracting the downloaded
bytes again. And a small one built here (Crafted), whose persons, dates, file names and texts
are chosen so that every filter has an answer known in advance.
"""

import asyncio
import base64
import hashlib
import json
import re
import shutil
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.api import documents
from mailrobbe.api.documents import (
    CONTENT_HEADERS,
    content_disposition,
    content_type,
    literal_pattern,
    search_words,
    snippet_around,
    stem_pattern,
)
from mailrobbe.api.schemas import (
    DOCUMENT_PERSONS_LIMIT,
    SNIPPET_LENGTH,
    DocumentDetail,
    DocumentListItem,
    DocumentText,
    PersonRef,
)
from mailrobbe.attachments.extract import ExtractionLimits, extract_document
from mailrobbe.config import Settings
from mailrobbe.db.models import DOCUMENT_TEXT_LIMIT
from mailrobbe.enums import DocumentKind, DocumentTextStatus
from mailrobbe.importer.cli import run_import
from mailrobbe.preview.kinds import preview_kind
from tests.api.conftest import _client
from tests.api.test_mails import Params, at, get, rows
from tests.attachments.doubles import FIRST_DAY, Attached, attachment_mail, digest
from tests.conftest import _temporary_database
from tests.importer.doubles import SEPARATOR

pytestmark = pytest.mark.db

Item = dict[str, Any]
SORTS = ["recent", "oldest", "mails", "size"]
ORDER = {
    "recent": "COALESCE(first_date, '-infinity') DESC, id DESC",
    "oldest": "COALESCE(first_date, '-infinity') ASC, id ASC",
    "mails": "mails DESC, id DESC",
    "size": "size_bytes DESC, id DESC",
}
PAGE = 37  # not a divisor of the number of documents, so the last page is short
SIGNATURES = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/gif": b"GIF8",
}


async def document_pages(client: httpx.AsyncClient, params: Params, limit: int) -> list[Any]:
    """Every page of the document list, following next_cursor from the first page."""
    found: list[Any] = []
    cursor = None
    while True:
        page = await get(client, "/api/documents", [*params, ("limit", str(limit)), *at(cursor)])
        found.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return found


async def items(client: httpx.AsyncClient, params: Params = (), limit: int = 200) -> list[Item]:
    return [item for page in await document_pages(client, params, limit) for item in page["items"]]


async def item_ids(client: httpx.AsyncClient, params: Params = ()) -> list[int]:
    return [item["id"] for item in await items(client, params)]


async def walk_back(client: httpx.AsyncClient, params: Params, forward: list[Any]) -> None:
    """From the last page back to the first, prev_cursor gives each page of forward again."""
    assert forward[0]["prev_cursor"] is None
    assert all(page["prev_cursor"] for page in forward[1:])
    limit = str(len(forward[0]["items"]))
    cursor = forward[-1]["prev_cursor"]
    for page in reversed(forward[:-1]):
        back = await get(client, "/api/documents", [*params, ("limit", limit), *at(cursor)])
        assert back["items"] == page["items"]
        assert back["next_cursor"] is not None
        cursor = back["prev_cursor"]
    assert cursor is None


def day(days: int) -> str:
    return (FIRST_DAY + timedelta(days=days)).date().isoformat()


# The crafted archive --------------------------------------------------------------------------

ANNA = "Anna Albrecht <anna@a.example>"
BERT = "Bert Berg <bert@a.example>"
CARLA = "Carla Conte <carla@c.example>"
DORA = "Dora Dietz <dora@d.example>"
INTERNAL = "a.example"
FILLER = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 25

NOTES = "Spendenliste 2023\nDie Spendenquittung für Herrn Müller liegt bei.\nBetrag 1.500,00 EUR\n"
PROTOKOLL = (
    f"{FILLER}\nProtokoll der Vorstandssitzung.\nTagesordnung:\n  HAUSHALT\n   2024, der "
    f"Tannenbaum\n{FILLER}"
)
UEBERSICHT = "Übersicht über das Weihnachtsgeld im März.\n"
ZETTEL = "Ein Zettel ohne Datum.\n"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + bytes(200)
PDF = b"%PDF-1.4\n%kein echtes PDF\n"
HTML = b"<html><script>alert(1)</script>Hallo</html>\n"
BLOB = bytes(range(256)) * 4
UMLAUT_NAME = "Übersicht März.txt"
# A From_ line without a usable date, so a mail without Date header stays undated
NO_DAY = b"From sender@example.test Fri Feb 30 00:00:00 2024"

# (index, attachments, sender, recipients, body, dated). Index 2 comes twice: same Message-ID
# and subject, so the mail at file position 3 is a duplicate, sent by Dora.
MAILS: list[tuple[int, list[Attached], str, list[str], str | None, bool]] = [
    (
        0,
        [("Spendenliste.txt", "text/plain", NOTES.encode()), ("Foto.png", "image/png", PNG)],
        ANNA,
        [BERT],
        None,
        True,
    ),
    (1, [("Spendenliste_final.txt", "text/plain", NOTES.encode())], ANNA, [CARLA], None, True),
    (2, [("Protokoll.txt", "text/plain", PROTOKOLL.encode())], CARLA, [BERT], "Tannenbaum.", True),
    (2, [("Protokoll.txt", "text/plain", PROTOKOLL.encode())], DORA, [BERT], "Tannenbaum.", True),
    (
        4,
        [
            ("Vertrag.pdf", "application/pdf", PDF),
            (UMLAUT_NAME, "text/plain", UEBERSICHT.encode()),
        ],
        BERT,
        [ANNA],
        None,
        True,
    ),
    (
        5,
        [
            ("evil.html", "text/html", HTML),
            (None, "application/octet-stream", BLOB),
            ("scan.jpg", "application/octet-stream", JPEG),
        ],
        DORA,
        [ANNA, CARLA],
        None,
        True,
    ),
    (6, [("Zettel.txt", "text/plain", ZETTEL.encode())], BERT, [CARLA], None, False),
]
CONTENTS = {
    "notes": NOTES.encode(),
    "png": PNG,
    "protokoll": PROTOKOLL.encode(),
    "pdf": PDF,
    "uebersicht": UEBERSICHT.encode(),
    "html": HTML,
    "blob": BLOB,
    "jpeg": JPEG,
    "zettel": ZETTEL.encode(),
}
# The day of the earliest original carrying each document (None: undated), its mails
FIRST_DAYS = {
    "notes": 0,
    "png": 0,
    "protokoll": 2,
    "pdf": 4,
    "uebersicht": 4,
    "html": 5,
    "blob": 5,
    "jpeg": 5,
    "zettel": None,
}
EVERY = frozenset(CONTENTS)


@dataclass(frozen=True, slots=True)
class Crafted:
    url: str
    settings: Settings  # internal domain a.example
    mbox_dir: Path
    mails: list[int]  # mail ids in file order
    documents: dict[str, int]  # document id by CONTENTS key
    persons: dict[str, int]  # person id by local part

    def ids(self, *keys: str) -> set[int]:
        return {self.documents[key] for key in keys}

    def key(self, document_id: int) -> str:
        return next(key for key, value in self.documents.items() if value == document_id)


@pytest.fixture(scope="module")
def crafted(
    database_server_url: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Crafted]:
    mbox_dir = tmp_path_factory.mktemp("crafted") / "mbox"
    mbox_dir.mkdir()
    with (mbox_dir / "crafted.mbox").open("wb") as handle:  # mboxrd; no line needs quoting
        for index, files, sender, to, body, dated in MAILS:
            message = attachment_mail(index, files, sender=sender, to=to, body=body, dated=dated)
            handle.write((SEPARATOR if dated else NO_DAY) + b"\n" + message + b"\n")
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(
            database_url=url,
            mbox_dir=mbox_dir,
            internal_domains=INTERNAL,
            frontend_dir=mbox_dir.parent / "no-frontend",
        )
        assert asyncio.run(run_import(settings, mbox_dir, 1)) == 0
        yield asyncio.run(_crafted(url, settings, mbox_dir))


async def _crafted(url: str, settings: Settings, mbox_dir: Path) -> Crafted:
    mails = [row.id for row in await rows(url, "SELECT id FROM mail ORDER BY byte_offset")]
    found = {row.sha256: row.id for row in await rows(url, "SELECT id, sha256 FROM document")}
    persons = await rows(url, "SELECT id, split_part(canonical_email, '@', 1) AS local FROM person")
    assert len(mails) == len(MAILS) and len(found) == len(CONTENTS)
    return Crafted(
        url=url,
        settings=settings,
        mbox_dir=mbox_dir,
        mails=mails,
        documents={key: found[digest(content)] for key, content in CONTENTS.items()},
        persons={row.local: row.id for row in persons},
    )


@pytest.fixture
async def crafted_client(crafted: Crafted) -> AsyncIterator[httpx.AsyncClient]:
    async for http in _client(crafted.settings):
        yield http


async def found_keys(client: httpx.AsyncClient, crafted: Crafted, params: Params) -> set[str]:
    return {crafted.key(document_id) for document_id in await item_ids(client, params)}


async def detail_of(client: httpx.AsyncClient, document_id: int) -> DocumentDetail:
    return DocumentDetail.model_validate(await get(client, f"/api/documents/{document_id}"))


# Filters (crafted) ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ([], EVERY),
        ([("q", "  ")], EVERY),
        ([("shared", "true")], {"notes"}),  # protokoll's second mail is a duplicate
        ([("name", "final")], {"notes"}),
        ([("name", "_")], {"notes"}),  # a literal underscore, not any character
        ([("name", "%")], set()),
        ([("name", " PNG ")], {"png"}),
        ([("name", "märz")], {"uebersicht"}),
        ([("date_from", day(1)), ("date_to", day(4))], {"notes", "protokoll", "pdf", "uebersicht"}),
        ([("date_to", day(0))], {"notes", "png"}),
        ([("date_from", day(5))], {"html", "blob", "jpeg"}),  # an undated mail never matches
        ([("external", "true")], {"notes", "protokoll", "html", "blob", "jpeg", "zettel"}),
        # One carrying mail must meet all: notes' internal mail is on day 0, its external one not.
        ([("external", "true"), ("date_to", day(0))], set()),
        ([("external", "true"), ("date_to", day(1))], {"notes"}),
        ([("q", "Spendenquittung")], {"notes"}),
        ([("q", "Spendenlisten")], {"notes"}),  # German stemming, as the mail search
        ([("q", "Foto")], {"png"}),  # file names are searched too
        ([("q", "tannenbaum HAUSHALT")], {"protokoll"}),
        ([("q", "Zettel OR Vertrag")], {"zettel", "pdf"}),
        ([("q", "Spendenliste -Müller")], set()),
        ([("q", "Spendenquittung"), ("name", "final")], {"notes"}),
        ([("q", "Spendenquittung"), ("date_from", day(2))], set()),
    ],
)
async def test_filters_of_the_document_list(
    crafted_client: httpx.AsyncClient, crafted: Crafted, params: Params, expected: set[str]
) -> None:
    assert await found_keys(crafted_client, crafted, params) == expected
    summary = await get(crafted_client, "/api/documents/summary", params)
    assert (summary["total"], summary["exact"]) == (len(expected), True)


@pytest.mark.parametrize(
    ("person", "role", "expected"),
    [
        ("carla", None, {"notes", "protokoll", "html", "blob", "jpeg", "zettel"}),
        ("carla", "sent", {"protokoll"}),
        ("carla", "received", {"notes", "html", "blob", "jpeg", "zettel"}),
        ("dora", "sent", {"html", "blob", "jpeg"}),  # not protokoll: Dora sent its duplicate
        ("anna", "received", {"pdf", "uebersicht", "html", "blob", "jpeg"}),
        ("bert", "received", {"notes", "png", "protokoll"}),
        ("bert", "sent", {"pdf", "uebersicht", "zettel"}),
    ],
)
async def test_the_person_filter_with_and_without_a_role(
    crafted_client: httpx.AsyncClient,
    crafted: Crafted,
    person: str,
    role: str | None,
    expected: set[str],
) -> None:
    params = [("person", str(crafted.persons[person]))]
    if role is not None:
        params.append(("person_role", role))
    assert await found_keys(crafted_client, crafted, params) == expected


async def test_person_date_and_external_together(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    anna = str(crafted.persons["anna"])
    found = await found_keys(
        crafted_client,
        crafted,
        [("person", anna), ("person_role", "sent"), ("external", "true"), ("date_to", day(3))],
    )
    assert found == {"notes"}  # mail 1, Anna to Carla; not mail 0 to Bert, which is internal


async def test_kind_and_text_status_filters(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    stored = await rows(
        crafted.url, "SELECT id, kind::text AS kind, text_status::text AS status FROM document"
    )
    for kind in DocumentKind:
        expected = {row.id for row in stored if row.kind == kind}
        assert set(await item_ids(crafted_client, [("kind", kind)])) == expected, kind
    for status in DocumentTextStatus:
        expected = {row.id for row in stored if row.status == status}
        assert set(await item_ids(crafted_client, [("text_status", status)])) == expected, status
    images = await item_ids(crafted_client, [("kind", "image")])
    assert crafted.ids("png", "jpeg") <= set(images)
    with_text = set(await item_ids(crafted_client, [("text_status", "text")]))
    assert crafted.ids("notes", "protokoll", "uebersicht", "zettel") <= with_text
    either = await item_ids(crafted_client, [("kind", "image"), ("kind", "pdf")])
    assert set(either) == {row.id for row in stored if row.kind in ("image", "pdf")}


@pytest.mark.parametrize(
    "params",
    [
        [("kind", "bogus")],
        [("text_status", "bogus")],
        [("person_role", "from")],
        [("person", "x")],
        [("date_from", "2024-13-01")],
        [("shared", "maybe")],
        [("sort", "name")],
        [("limit", "0")],
        [("limit", "201")],
    ],
)
async def test_invalid_parameters(crafted_client: httpx.AsyncClient, params: Params) -> None:
    await get(crafted_client, "/api/documents", params, status=422)


async def test_external_needs_the_internal_domains(client: httpx.AsyncClient) -> None:
    for path in ("/api/documents", "/api/documents/summary"):
        error = await get(client, path, [("external", "true")], status=400)
        assert error["detail"]["code"] == "invalid_filter"


# Sorts, items and snippets (crafted) ----------------------------------------------------------


@pytest.mark.parametrize("sort", SORTS)
async def test_each_sort_pages_both_ways(
    crafted_client: httpx.AsyncClient, crafted: Crafted, sort: str
) -> None:
    def key(name: str) -> tuple[int, int]:
        first = FIRST_DAYS[name]
        figure = {
            "recent": -1 if first is None else first,
            "oldest": -1 if first is None else first,
            "mails": 2 if name == "notes" else 1,
            "size": len(CONTENTS[name]),
        }[sort]
        return figure, crafted.documents[name]

    expected = [crafted.documents[name] for name in sorted(CONTENTS, key=key)]
    if sort != "oldest":
        expected.reverse()
    forward = await document_pages(crafted_client, [("sort", sort)], 2)
    assert [item["id"] for page in forward for item in page["items"]] == expected
    await walk_back(crafted_client, [("sort", sort)], forward)


async def test_an_item_shows_the_document(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    listed = {item["id"]: item for item in await items(crafted_client)}
    notes = DocumentListItem.model_validate(listed[crafted.documents["notes"]])
    # mode() picks the first name in the database's collation among names used equally often
    assert notes.name in ("Spendenliste.txt", "Spendenliste_final.txt")
    assert (notes.names, notes.kind, notes.mime_type) == (2, DocumentKind.TEXT, "text/plain")
    assert (notes.size, notes.sha256) == (len(NOTES.encode()), digest(NOTES.encode()))
    assert (notes.pages, notes.text_status, notes.mails) == (None, DocumentTextStatus.TEXT, 2)
    assert (notes.first_date, notes.last_date) == (FIRST_DAY, FIRST_DAY + timedelta(days=1))
    assert notes.first_sender == PersonRef(
        person_id=crafted.persons["anna"], email="anna@a.example", name="Anna Albrecht"
    )
    assert notes.snippet is None
    blob = DocumentListItem.model_validate(listed[crafted.documents["blob"]])
    assert (blob.name, blob.names) == (None, 0)
    zettel = DocumentListItem.model_validate(listed[crafted.documents["zettel"]])
    assert (zettel.first_date, zettel.last_date, zettel.mails) == (None, None, 1)
    assert zettel.first_sender and zettel.first_sender.email == "bert@a.example"


async def snippets(client: httpx.AsyncClient, crafted: Crafted, q: str) -> dict[str, str | None]:
    return {crafted.key(item["id"]): item["snippet"] for item in await items(client, [("q", q)])}


async def test_snippets_show_the_text_around_the_first_word_as_typed(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    whole = " ".join(NOTES.split())
    assert await snippets(crafted_client, crafted, "spendenquittung") == {"notes": whole}
    # The words as typed, in any case: a stem alone finds the document but shows no snippet.
    assert await snippets(crafted_client, crafted, "Spendenlisten") == {"notes": None}
    assert await snippets(crafted_client, crafted, "Foto") == {"png": None}  # no text
    found = await snippets(crafted_client, crafted, "Zettel OR Vertrag")
    assert found == {"zettel": "Ein Zettel ohne Datum.", "pdf": None}

    for q in ('"haushalt 2024"', "Tannenbaum -Spendenliste", "-Foto HAUSHALT"):
        snippet = (await snippets(crafted_client, crafted, q))["protokoll"]
        assert snippet is not None and len(snippet) <= SNIPPET_LENGTH, q
        assert "HAUSHALT 2024, der Tannenbaum" in snippet, q
        words = PROTOKOLL.split()
        assert snippet.split()[0] in words and snippet.split()[-1] in words, q
        assert snippet in " ".join(words), q


async def test_postgresql_reads_the_snippet_pattern_as_python_does(crafted: Crafted) -> None:
    typed = ["(x)+[y]{2}|z\\^$.?*", "Müller", "a  b"]
    pattern = literal_pattern(typed)
    sample = "-- (X)+[Y]{2}|Z\\^$.?* -- MÜLLER -- A\n b --"
    expected = [match.start() + 1 for match in re.finditer(pattern, sample)]
    assert len(expected) == 3
    (row,) = await rows(
        crafted.url,
        "SELECT array(SELECT regexp_instr(:sample, :pattern, 1, n) FROM generate_series(1, 3) n)"
        " AS found",
        sample=sample,
        pattern=pattern,
    )
    assert row.found == expected


def test_search_words_follow_the_query_syntax() -> None:
    assert search_words('Haushalt "finale  Fassung" -Entwurf OR Satzung') == [
        "Haushalt",
        "finale Fassung",
        "Satzung",
    ]
    assert search_words('-"nicht das" (Klammer) haushalt Haushalt haushalt') == [
        "Klammer",
        "haushalt",
        "Haushalt",
    ]
    assert search_words('"offen') == ["offen"]
    assert search_words("  or OR -x ... ") == []


def test_the_snippet_pattern_takes_the_words_literally_in_any_case() -> None:
    pattern = re.compile(literal_pattern(["Müller", "a.b", "finale Fassung"]))
    assert pattern.search("Herr MÜLLER") and pattern.search("herr müller")
    assert pattern.search("a.b") and not pattern.search("axb")
    assert pattern.search("FINALE\n  fassung") and not pattern.search("finaleFassung")
    special = "(x)+[y]{2}|z\\"
    assert re.compile(literal_pattern([special])).fullmatch(special)


def test_the_stem_pattern_finds_words_a_stem_begins_as_written() -> None:
    pattern = re.compile(stem_pattern(["spendenquitt", "ausser", "mull", "geb"]))
    found = pattern.findall("Spendenquittungen, ÄUSSERST, äußere, Herrn Müller, geben")
    assert found == ["Spendenquitt", "ÄUSSER", "äußer", "Müll"]  # "geb": too short to be safe
    assert not pattern.search("Sachspendenquittung")  # inside a word: not a form of it
    assert stem_pattern(["geb"]) == ""


async def test_postgresql_reads_the_stem_pattern_as_python_does(crafted: Crafted) -> None:
    pattern = stem_pattern(["spendenquitt", "ausser", "mull"])
    sample = "-- SPENDENQUITTUNG -- äußerst -- Sachspendenquittung -- Müllers --"
    expected = [match.start() + 1 for match in re.finditer(pattern, sample)]
    assert len(expected) == 3
    (row,) = await rows(
        crafted.url,
        "SELECT array(SELECT regexp_instr(:sample, :pattern, 1, n) FROM generate_series(1, 3) n)"
        " AS found",
        sample=sample,
        pattern=pattern,
    )
    assert row.found == expected


def test_snippets_are_cut_at_whole_words() -> None:
    sample = " ".join(f"wort{i}" for i in range(200))
    pattern = re.compile(literal_pattern(["wort100"]))
    snippet = snippet_around(sample, sample.index("wort100"), pattern)
    assert snippet is not None and "wort100" in snippet and len(snippet) <= SNIPPET_LENGTH
    assert set(snippet.split()) <= set(sample.split())
    assert snippet.index("wort100") <= SNIPPET_LENGTH // 4
    assert snippet_around("ab  \n cd", 0, re.compile("cd")) == "ab cd"
    assert snippet_around("nichts", 0, pattern) is None
    long = "a" * 1000 + "Fund" + "b" * 1000  # no spaces at all
    snippet = snippet_around(long, 1000, re.compile("Fund"))
    assert snippet is not None and "Fund" in snippet and len(snippet) == SNIPPET_LENGTH


# Summary --------------------------------------------------------------------------------------


async def test_the_summary_counts_kinds_and_statuses(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    stored = await rows(
        crafted.url, "SELECT kind::text AS kind, text_status::text AS status FROM document"
    )
    summary = await get(crafted_client, "/api/documents/summary")
    assert (summary["total"], summary["exact"]) == (len(CONTENTS), True)
    assert summary["kinds"] == {
        kind: sum(row.kind == kind for row in stored) for kind in DocumentKind
    }
    assert summary["text_status"] == {
        status: sum(row.status == status for row in stored) for status in DocumentTextStatus
    }
    carla = await get(
        crafted_client, "/api/documents/summary", [("person", str(crafted.persons["carla"]))]
    )
    assert carla["total"] == 6 and sum(carla["text_status"].values()) == 6


async def test_the_summary_falls_back_to_a_bounded_count(
    crafted_client: httpx.AsyncClient, crafted: Crafted, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def canceled(*_: object) -> None:
        return None

    monkeypatch.setattr(documents, "_all_unless_canceled", canceled)
    summary = await get(crafted_client, "/api/documents/summary")
    assert summary == {"total": len(CONTENTS), "exact": True, "kinds": None, "text_status": None}
    monkeypatch.setattr(documents, "COUNT_LIMIT", 4)
    summary = await get(crafted_client, "/api/documents/summary")
    assert summary == {"total": 4, "exact": False, "kinds": None, "text_status": None}


async def test_the_summary_runs_out_of_time(crafted: Crafted) -> None:
    settings = crafted.settings.model_copy(update={"api_count_timeout": 0.3})
    engine = create_async_engine(crafted.url, poolclass=pool.NullPool)
    try:
        async for client in _client(settings):
            async with engine.connect() as other:
                await other.execute(text("LOCK TABLE document IN ACCESS EXCLUSIVE MODE"))
                summary = await get(client, "/api/documents/summary")
                assert summary == {
                    "total": None,
                    "exact": False,
                    "kinds": None,
                    "text_status": None,
                }
                await other.rollback()
            assert (await get(client, "/api/documents/summary"))["exact"] is True
    finally:
        await engine.dispose()


# A document's page and text (crafted) ---------------------------------------------------------


async def test_the_page_of_a_document_sent_under_two_names(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    detail = await detail_of(crafted_client, crafted.documents["notes"])
    names = {(name.name, name.attachments) for name in detail.names}
    assert names == {("Spendenliste.txt", 1), ("Spendenliste_final.txt", 1)}
    assert (detail.mails, detail.attachments) == (2, 2)
    assert (detail.first_date, detail.last_date) == (FIRST_DAY, FIRST_DAY + timedelta(days=1))
    assert (detail.kind, detail.mime_type) == ("text", "text/plain")
    assert detail.size == len(NOTES.encode())
    assert (detail.text_status, detail.text_error, detail.text_truncated) == ("text", None, False)
    assert detail.extracted_at is not None and detail.sha256 == digest(NOTES.encode())
    assert detail.first_mail is not None and detail.first_mail.id == crafted.mails[0]
    assert detail.first_mail.subject == "Mail 0" and detail.first_mail.date == FIRST_DAY
    anna = PersonRef(
        person_id=crafted.persons["anna"], email="anna@a.example", name="Anna Albrecht"
    )
    assert detail.first_mail.sender == anna
    assert [(count.person, count.mails) for count in detail.senders] == [(anna, 2)]
    assert detail.sender_count == 1
    recipients = {
        (count.person.email, count.person.name, count.mails) for count in detail.recipients
    }
    assert recipients == {("bert@a.example", "Bert Berg", 1), ("carla@c.example", "Carla Conte", 1)}
    assert detail.recipient_count == 2
    (first,) = await rows(
        crafted.url,
        "SELECT id FROM attachment WHERE mail_id = :mail AND document_id = :document",
        mail=crafted.mails[0],
        document=detail.id,
    )
    assert (detail.attachment_id, detail.preview) == (first.id, None)


async def test_duplicates_count_as_attachments_but_not_as_mails(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    detail = await detail_of(crafted_client, crafted.documents["protokoll"])
    assert (detail.mails, detail.attachments) == (1, 2)
    assert detail.names[0].model_dump() == {"name": "Protokoll.txt", "attachments": 2}
    # Dora sent only the duplicate: not a sender of the document.
    assert [count.person.email for count in detail.senders] == ["carla@c.example"]
    assert [count.person.email for count in detail.recipients] == ["bert@a.example"]
    (source,) = await rows(
        crafted.url, "SELECT mail_id FROM attachment WHERE id = :id", id=detail.attachment_id
    )
    assert source.mail_id == crafted.mails[2]  # the original, not the duplicate


async def test_pages_of_undated_unnamed_and_image_documents(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    zettel = await detail_of(crafted_client, crafted.documents["zettel"])
    assert (zettel.first_date, zettel.last_date) == (None, None)
    assert zettel.first_mail and (zettel.first_mail.id, zettel.first_mail.date) == (
        crafted.mails[6],
        None,
    )
    blob = await detail_of(crafted_client, crafted.documents["blob"])
    assert (blob.name, blob.names, blob.preview) == (None, [], None)
    html = await detail_of(crafted_client, crafted.documents["html"])
    assert {count.person.email for count in html.recipients} == {
        "anna@a.example",
        "carla@c.example",
    }
    previews = {
        key: (await detail_of(crafted_client, crafted.documents[key])).preview
        for key in ("png", "jpeg", "html", "pdf", "uebersicht")
    }
    # scan.jpg was declared application/octet-stream: its name makes it a preview
    assert previews == {
        "png": "image",
        "jpeg": "image",
        "html": None,
        "pdf": "pdf",
        "uebersicht": None,
    }
    umlaut = await detail_of(crafted_client, crafted.documents["uebersicht"])
    assert umlaut.name == UMLAUT_NAME


async def test_the_text_of_a_document(crafted_client: httpx.AsyncClient, crafted: Crafted) -> None:
    notes = await get(crafted_client, f"/api/documents/{crafted.documents['notes']}/text")
    assert notes == {"text": NOTES.strip(), "truncated": False, "text_status": "text"}
    (png,) = await rows(
        crafted.url,
        "SELECT text_status::text AS status FROM document WHERE id = :id",
        id=crafted.documents["png"],
    )
    image = await get(crafted_client, f"/api/documents/{crafted.documents['png']}/text")
    assert image == {"text": "", "truncated": False, "text_status": png.status}


# Downloads (crafted) --------------------------------------------------------------------------


async def test_downloads_give_the_bytes_with_safe_headers(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    attachments = await rows(crafted.url, "SELECT id, filename, sha256 FROM attachment ORDER BY id")
    assert len(attachments) == sum(len(files) for _, files, *_ in MAILS)
    by_hash = {digest(content): content for content in CONTENTS.values()}
    for attachment in attachments:
        response = await crafted_client.get(f"/api/attachments/{attachment.id}/content")
        assert response.status_code == 200, response.text
        assert response.content == by_hash[attachment.sha256]
        for name, value in CONTENT_HEADERS.items():
            assert response.headers[name] == value
        expected_type = {PNG: "image/png", JPEG: "image/jpeg"}.get(response.content)
        assert response.headers["content-type"] == (expected_type or "application/octet-stream")
        name = attachment.filename or f"attachment-{attachment.id}"
        assert response.headers["content-disposition"] == content_disposition(name)

    umlaut = await detail_of(crafted_client, crafted.documents["uebersicht"])
    response = await crafted_client.get(f"/api/attachments/{umlaut.attachment_id}/content")
    assert response.headers["content-disposition"] == (
        'attachment; filename="_bersicht M_rz.txt"; '
        "filename*=UTF-8''%C3%9Cbersicht%20M%C3%A4rz.txt"
    )
    blob = await detail_of(crafted_client, crafted.documents["blob"])
    response = await crafted_client.get(f"/api/attachments/{blob.attachment_id}/content")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="attachment-{blob.attachment_id}"'
    )
    html = await detail_of(crafted_client, crafted.documents["html"])
    response = await crafted_client.get(f"/api/attachments/{html.attachment_id}/content")
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == 'attachment; filename="evil.html"'


def test_content_types_by_first_bytes() -> None:
    assert content_type(PNG) == "image/png"
    assert content_type(JPEG) == "image/jpeg"
    assert content_type(b"GIF87a...") == content_type(b"GIF89a...") == "image/gif"
    assert content_type(b"RIFF\x10\x00\x00\x00WEBPVP8 ") == "image/webp"
    for data in (b"RIFF\x10\x00\x00\x00WAVEfmt ", b"", b"<svg onload=alert(1)>", PDF, HTML):
        assert content_type(data) == "application/octet-stream"


def test_content_disposition_names() -> None:
    assert content_disposition("Bericht 2024.pdf") == 'attachment; filename="Bericht 2024.pdf"'
    assert content_disposition('a"b/c\\d\r\n.txt') == 'attachment; filename="a b c d  .txt"'
    assert content_disposition(" \t") == 'attachment; filename="file"'
    assert content_disposition("Maße €.txt") == (
        "attachment; filename=\"Ma_e _.txt\"; filename*=UTF-8''Ma%C3%9Fe%20%E2%82%AC.txt"
    )


@pytest.fixture
async def moved_client(crafted: Crafted, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    """Client on the crafted database whose MBOX directory is tmp_path/mbox, empty at first."""
    (tmp_path / "mbox").mkdir()
    settings = crafted.settings.model_copy(update={"mbox_dir": tmp_path / "mbox"})
    async for http in _client(settings):
        yield http


async def test_a_missing_or_changed_source(
    moved_client: httpx.AsyncClient, crafted: Crafted, tmp_path: Path
) -> None:
    document_id = crafted.documents["uebersicht"]
    detail = await detail_of(moved_client, document_id)  # the database alone answers
    assert (await moved_client.get(f"/api/documents/{document_id}/text")).status_code == 200
    path = f"/api/attachments/{detail.attachment_id}/content"
    response = await moved_client.get(path)
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "source_missing")

    (mail,) = await rows(
        crafted.url,
        "SELECT m.byte_offset, m.byte_length FROM attachment a JOIN mail m ON m.id = a.mail_id"
        " WHERE a.id = :id",
        id=detail.attachment_id,
    )
    original = (crafted.mbox_dir / "crafted.mbox").read_bytes()
    changed = bytearray(original)
    changed[mail.byte_offset + mail.byte_length // 2] ^= 0x01
    copy = tmp_path / "mbox" / "crafted.mbox"
    for data in (bytes(changed), original[: mail.byte_offset + mail.byte_length - 1]):
        copy.write_bytes(data)
        response = await moved_client.get(path)
        assert (response.status_code, response.json()["detail"]["code"]) == (409, "source_changed")
    shutil.copyfile(crafted.mbox_dir / "crafted.mbox", copy)
    assert (await moved_client.get(path)).content == UEBERSICHT.encode()


async def test_an_unhashed_attachment_is_checked_by_its_size(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    attachment_id = (await detail_of(crafted_client, crafted.documents["blob"])).attachment_id
    path = f"/api/attachments/{attachment_id}/content"

    async def stored(sha256: str | None, size: int) -> None:
        await rows(
            crafted.url,
            "UPDATE attachment SET sha256 = :sha256, size_bytes = :size WHERE id = :id",
            sha256=sha256,
            size=size,
            id=attachment_id,
        )

    try:
        await stored(None, len(BLOB))  # as above the hash limit (D18)
        assert (await crafted_client.get(path)).content == BLOB
        for sha256, size in ((None, len(BLOB) + 1), (digest(b"other"), len(BLOB))):
            await stored(sha256, size)
            response = await crafted_client.get(path)
            assert (response.status_code, response.json()["detail"]["code"]) == (
                409,
                "source_changed",
            )
    finally:
        await stored(digest(BLOB), len(BLOB))
    assert (await crafted_client.get(path)).content == BLOB


async def test_unknown_and_invalid_ids(crafted_client: httpx.AsyncClient) -> None:
    for path in ("/api/documents/0", "/api/documents/0/text", "/api/attachments/0/content"):
        error = await get(crafted_client, path, status=404)
        assert error["detail"]["code"] == "not_found"
    for path in (
        "/api/documents/x",
        f"/api/documents/{2**63}",
        f"/api/attachments/{2**63}/content",
    ):
        await get(crafted_client, path, status=422)


# The mail list: document filter and search through attachments (crafted) ----------------------


async def mail_ids(client: httpx.AsyncClient, params: Params) -> list[int]:
    page = await get(client, "/api/mails", [*params, ("limit", "200")])
    assert page["next_cursor"] is None
    return [item["id"] for item in page["items"]]


async def test_the_mails_carrying_a_document(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    m = crafted.mails
    oldest = [("sort", "date_asc")]

    def document(key: str) -> tuple[str, str]:
        return ("document", str(crafted.documents[key]))

    assert await mail_ids(crafted_client, [*oldest, document("notes")]) == [m[0], m[1]]
    protokoll = [*oldest, document("protokoll")]
    assert sorted(await mail_ids(crafted_client, protokoll)) == [m[2], m[3]]  # with the duplicate
    assert await mail_ids(crafted_client, [*protokoll, ("hide_duplicates", "true")]) == [m[2]]
    dora = ("person", str(crafted.persons["dora"]))
    assert await mail_ids(crafted_client, [*protokoll, dora]) == [m[3]]
    assert await mail_ids(crafted_client, [("document", "0")]) == []
    summary = await get(crafted_client, "/api/mails/summary", [document("notes")])
    assert (summary["total"], summary["exact"]) == (2, True)


async def test_the_mail_search_finds_words_in_attachments_and_marks_those_mails(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    m = crafted.mails

    async def search(q: str) -> dict[int, bool]:
        page = await get(crafted_client, "/api/mails", [("q", q), ("limit", "200")])
        return {item["id"]: item["attachment_match"] for item in page["items"]}

    assert await search("Weihnachtsgeld") == {m[4]: True}  # only in an attachment's text
    assert await search("Haushalt") == {m[2]: True, m[3]: True}
    assert await search("Tannenbaum") == {m[2]: False, m[3]: False}  # in the mails themselves
    assert await search("Foto") == {m[0]: True}  # an attachment's file name
    assert await search("Body") == {m[i]: False for i in (0, 1, 4, 5, 6)}
    assert await search("has:attachment Weihnachtsgeld") == {m[4]: True}
    assert set((await search("has:attachment")).values()) == {False}  # no words, no mark
    summary = await get(crafted_client, "/api/mails/summary", [("q", "Weihnachtsgeld")])
    assert summary["total"] == 1


async def test_the_hits_of_one_mail_say_where_the_words_occur(
    crafted_client: httpx.AsyncClient, crafted: Crafted
) -> None:
    m = crafted.mails

    async def hits(mail: int, q: str) -> Any:
        return await get(crafted_client, f"/api/mails/{mail}/hits", [("q", q)])

    async def attached(mail: int) -> list[int]:
        found = await rows(crafted.url, f"SELECT id FROM attachment WHERE mail_id = {mail}")
        return sorted(row.id for row in found)

    foto = (await attached(m[0]))[1]
    uebersicht = (await attached(m[4]))[1]
    (protokoll,) = await attached(m[2])
    assert await hits(m[4], "has:attachment Weihnachtsgeld") == {
        "words": ["Weihnachtsgeld"],
        "stems": ["weihnachtsgeld"],
        "in_mail": False,
        "attachments": [
            {
                "attachment_id": uebersicht,
                "in_name": False,
                "snippet": UEBERSICHT.strip(),
                "in_text": False,
            }
        ],
        "whole_word": False,
        "in_subject": False,
        "in_body": False,
        "counts": None,
    }
    tannenbaum = await hits(m[2], "Tannenbaum")
    assert tannenbaum["in_mail"] is True
    assert [hit["attachment_id"] for hit in tannenbaum["attachments"]] == [protokoll]
    assert "2024, der Tannenbaum" in tannenbaum["attachments"][0]["snippet"]
    assert await hits(m[0], "Foto") == {
        "words": ["Foto"],
        "stems": ["foto"],
        "in_mail": False,
        "attachments": [
            {"attachment_id": foto, "in_name": True, "snippet": None, "in_text": False}
        ],
        "whole_word": False,
        "in_subject": False,
        "in_body": False,
        "counts": None,
    }
    # Found as another form of the word (German stemming): the snippet around the word the stem
    # begins, which the browser marks
    stemmed = await hits(m[0], "Spendenquittungen")
    assert stemmed["stems"] == ["spendenquitt"]
    notes = " ".join(NOTES.split())
    assert [(hit["in_name"], hit["snippet"]) for hit in stemmed["attachments"]] == [(False, notes)]
    assert await hits(m[0], "has:attachment") == {
        "words": [],
        "stems": [],
        "in_mail": False,
        "attachments": [],
        "whole_word": False,
        "in_subject": False,
        "in_body": False,
        "counts": None,
    }
    invalid = await crafted_client.get(f"/api/mails/{m[0]}/hits", params={"q": "dkim:egal"})
    assert (invalid.status_code, invalid.json()["detail"]["code"]) == (400, "invalid_query")
    unknown = await crafted_client.get("/api/mails/999999/hits", params={"q": "Foto"})
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "not_found")


# The generated archive ------------------------------------------------------------------------


async def document_ids(url: str, where: str = "true", sort: str = "recent") -> list[int]:
    found = await rows(url, f"SELECT id FROM document WHERE {where} ORDER BY {ORDER[sort]}")
    return [row.id for row in found]


@pytest.mark.parametrize("sort", SORTS)
@pytest.mark.parametrize(
    ("params", "where"),
    [
        ([], "true"),
        (
            [("text_status", "text"), ("text_status", "unsupported")],
            "text_status IN ('text', 'unsupported')",
        ),
        ([("kind", "image")], "kind = 'image'"),
    ],
    ids=["all", "status", "kind"],
)
async def test_pages_visit_every_document_once_forward_and_back(
    client: httpx.AsyncClient, imported_database_url: str, params: Params, where: str, sort: str
) -> None:
    expected = await document_ids(imported_database_url, where, sort)
    assert expected
    forward = await document_pages(client, [*params, ("sort", sort)], PAGE)
    assert [item["id"] for page in forward for item in page["items"]] == expected
    await walk_back(client, [*params, ("sort", sort)], forward)


async def test_the_default_order_is_newest_first(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    page = await get(client, "/api/documents")
    assert [item["id"] for item in page["items"]] == (await document_ids(imported_database_url))[
        :50
    ]


async def test_items_against_sql(client: httpx.AsyncClient, imported_database_url: str) -> None:
    expected = {
        row.id: row
        for row in await rows(
            imported_database_url,
            """
            SELECT d.id, d.name, d.kind::text AS kind, d.mime_type, d.size_bytes, d.sha256,
                d.pages, d.text_status::text AS text_status,
                (SELECT count(DISTINCT a.filename) FROM attachment a WHERE a.document_id = d.id)
                    AS names,
                c.mails, c.first_date, c.last_date, s.person_id, s.email, s.sender_name
            FROM document d
            CROSS JOIN LATERAL (
                SELECT count(DISTINCT m.id) AS mails, min(m.date_utc) AS first_date,
                    max(m.date_utc) AS last_date
                FROM attachment a JOIN mail m ON m.id = a.mail_id
                WHERE a.document_id = d.id AND m.is_duplicate_of IS NULL
            ) c
            LEFT JOIN LATERAL (
                SELECT p.id AS person_id, p.canonical_email AS email,
                    COALESCE(pa.display_name, p.display_name) AS sender_name
                FROM participation pa JOIN person p ON p.id = pa.person_id
                WHERE pa.mail_id = d.first_mail_id AND pa.role = 'from'
                ORDER BY sender_name, email LIMIT 1
            ) s ON true
            """,
        )
    }
    listed = [DocumentListItem.model_validate(item) for item in await items(client)]
    assert sorted(item.id for item in listed) == sorted(expected)
    for item in listed:
        row = expected[item.id]
        sender = None
        if row.person_id is not None:
            sender = PersonRef(person_id=row.person_id, email=row.email, name=row.sender_name)
        assert item.model_dump() == {
            "id": row.id,
            "name": row.name,
            "names": row.names,
            "kind": row.kind,
            "mime_type": row.mime_type,
            "size": row.size_bytes,
            "sha256": row.sha256,
            "pages": row.pages,
            "text_status": row.text_status,
            "mails": row.mails,
            "first_date": row.first_date,
            "last_date": row.last_date,
            "first_sender": sender and sender.model_dump(),
            "snippet": None,
        }
    assert any(item.first_sender for item in listed)


async def test_a_document_cursor_is_bound_to_its_sort(client: httpx.AsyncClient) -> None:
    recent = (await get(client, "/api/documents", [("limit", "3")]))["next_cursor"]
    by_mails = (await get(client, "/api/documents", [("sort", "mails"), ("limit", "3")]))[
        "next_cursor"
    ]

    def forged(cursor: str) -> str:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        data["k"][0] = "x"
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

    for params in (
        [("sort", "mails"), ("cursor", recent)],
        [("sort", "size"), ("cursor", by_mails)],
        [("cursor", by_mails)],
        [("cursor", forged(recent))],
        [("sort", "mails"), ("cursor", forged(by_mails))],
        [("cursor", "bm90IGEgY3Vyc29y")],
        [("cursor", "!!")],
    ):
        error = await get(client, "/api/documents", params, status=400)
        assert error["detail"]["code"] == "invalid_cursor"


async def test_the_summary_of_the_generated_archive(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    stored = await rows(
        imported_database_url,
        "SELECT kind::text AS kind, text_status::text AS status, count(*) AS n FROM document"
        " GROUP BY 1, 2",
    )
    summary = await get(client, "/api/documents/summary")
    assert (summary["total"], summary["exact"]) == (sum(row.n for row in stored), True)
    assert summary["kinds"] == {
        kind: sum(row.n for row in stored if row.kind == kind) for kind in DocumentKind
    }
    assert summary["text_status"] == {
        status: sum(row.n for row in stored if row.status == status)
        for status in DocumentTextStatus
    }
    images = await get(client, "/api/documents/summary", [("kind", "image")])
    assert images["total"] == summary["kinds"]["image"] > 0


async def test_every_attachment_downloads_its_bytes(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    attachments = await rows(
        imported_database_url, "SELECT id, filename, size_bytes, sha256 FROM attachment"
    )
    assert attachments
    for attachment in attachments:
        response = await client.get(f"/api/attachments/{attachment.id}/content")
        assert response.status_code == 200, response.text
        data = response.content
        assert len(data) == attachment.size_bytes
        if attachment.sha256 is not None:
            assert hashlib.sha256(data).hexdigest() == attachment.sha256
        media_type = response.headers["content-type"]
        assert media_type == "application/octet-stream" or data.startswith(
            SIGNATURES.get(media_type, b"RIFF")
        )
        name = attachment.filename or f"attachment-{attachment.id}"
        assert response.headers["content-disposition"] == content_disposition(name)


async def test_every_document_page_against_sql(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    url = imported_database_url
    stored = {row.id: row for row in await rows(url, "SELECT * FROM document")}
    people = {
        row.id: PersonRef(person_id=row.id, email=row.canonical_email, name=row.display_name)
        for row in await rows(url, "SELECT id, canonical_email, display_name FROM person")
    }
    takes_part = await rows(
        url,
        "SELECT a.document_id, COALESCE(p.merged_into, p.id) AS root, pa.role = 'from' AS sent,"
        " count(DISTINCT pa.mail_id) AS mails"
        " FROM attachment a JOIN mail m ON m.id = a.mail_id AND m.is_duplicate_of IS NULL"
        " JOIN participation pa ON pa.mail_id = m.id JOIN person p ON p.id = pa.person_id"
        " GROUP BY 1, 2, 3",
    )
    names = await rows(
        url,
        "SELECT document_id, filename, count(*) AS n FROM attachment"
        " WHERE filename IS NOT NULL GROUP BY 1, 2",
    )
    occurrences = {
        row.document_id: row.id
        for row in await rows(
            url,
            "SELECT DISTINCT ON (a.document_id) a.document_id, a.id FROM attachment a"
            " JOIN mail m ON m.id = a.mail_id JOIN mbox_file f ON f.id = m.mbox_file_id"
            ' ORDER BY a.document_id, m.is_duplicate_of IS NOT NULL, f.path COLLATE "C",'
            " m.byte_offset, a.position",
        )
    }
    assert stored
    for document_id, row in stored.items():
        detail = await detail_of(client, document_id)
        assert (detail.mails, detail.attachments) == (row.mails, row.attachments)
        assert (detail.first_date, detail.last_date) == (row.first_date, row.last_date)
        assert detail.first_mail and detail.first_mail.id == row.first_mail_id
        assert detail.attachment_id == occurrences[document_id]
        own = sorted((-n.n, n.filename) for n in names if n.document_id == document_id)
        assert sorted((-n.attachments, n.name) for n in detail.names) == own
        for sent, listed, count in (
            (True, detail.senders, detail.sender_count),
            (False, detail.recipients, detail.recipient_count),
        ):
            roles = [r for r in takes_part if r.document_id == document_id and r.sent == sent]
            assert count == len(roles)
            expected = sorted(roles, key=lambda r: (-r.mails, r.root))[:DOCUMENT_PERSONS_LIMIT]
            assert [(c.person, c.mails) for c in listed] == [
                (people[r.root], r.mails) for r in expected
            ]
        kind = None if row.kind is None else DocumentKind(row.kind)
        hashed = row.sha256 is not None
        size, limit = row.size_bytes, Settings().preview_max_size
        preview = preview_kind(kind, row.name, row.mime_type, size, hashed=hashed, max_size=limit)
        assert detail.preview == preview


async def test_the_mails_carrying_each_generated_document(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    carried: dict[int, set[int]] = {}
    for row in await rows(imported_database_url, "SELECT document_id, mail_id FROM attachment"):
        carried.setdefault(row.document_id, set()).add(row.mail_id)
    assert any(len(mails) > 1 for mails in carried.values())
    for document_id, mails in carried.items():
        assert set(await mail_ids(client, [("document", str(document_id))])) == mails


async def test_the_import_summary_counts_attachments_and_documents(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    summary = await get(client, "/api/import/summary")
    (attachments,) = await rows(imported_database_url, "SELECT count(*) AS n FROM attachment")
    statuses = {
        row.status: row.n
        for row in await rows(
            imported_database_url,
            "SELECT text_status::text AS status, count(*) AS n FROM document GROUP BY 1",
        )
    }
    assert summary["attachments"] == attachments.n > 0
    assert summary["documents"] == {
        status: statuses.get(status, 0) for status in DocumentTextStatus
    }
    assert statuses.get("pending", 0) == 0  # the import's attachments phase ran


@pytest.mark.slow
async def test_every_text_is_what_extracting_the_downloaded_bytes_gives(
    client: httpx.AsyncClient, imported_database_url: str
) -> None:
    """The archive check: download each document's bytes through the API and extract them
    again; the stored text, status, pages and kind are what that gives."""
    stored = await rows(
        imported_database_url,
        "SELECT id, name, mime_type, text_status::text AS status FROM document ORDER BY id",
    )
    limits = ExtractionLimits(max_chars=DOCUMENT_TEXT_LIMIT)
    compared = 0
    for row in stored:
        assert row.status not in ("pending", "unreadable"), row
        detail = await detail_of(client, row.id)
        if row.status in ("too_large", "timeout"):  # not read, or not the same twice
            continue
        response = await client.get(f"/api/attachments/{detail.attachment_id}/content")
        assert response.status_code == 200
        extraction = await asyncio.to_thread(
            extract_document, response.content, row.name, row.mime_type, limits
        )
        shown = DocumentText.model_validate(await get(client, f"/api/documents/{row.id}/text"))
        assert (shown.text_status, shown.text, shown.truncated) == (
            extraction.status,
            extraction.text,
            extraction.truncated,
        ), row
        assert detail.pages == extraction.pages, row
        if extraction.kind is not None:
            assert detail.kind == extraction.kind, row
        compared += 1
    assert compared and any(row.status == "text" for row in stored)

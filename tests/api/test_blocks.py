"""GET /api/blocks/summary, /api/blocks, /api/blocks/{hash}, PUT /api/blocks/{hash}/override
(D225, D227) and the standard blocks in the text of a mail.

The archive is the imported one with the blocks step run again at a threshold of three mails
(BLOCKS_MIN_MAILS), so that the 600 generated mails have many blocks; one detected block is taken
back by the team. Expected senders and figures are counted in SQL written apart from
api/blocks.py.
"""

import asyncio
import itertools
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mailrobbe.api.schemas import BLOCK_SENDERS
from mailrobbe.blocks import phase
from mailrobbe.blocks.model import hash_hex, paragraph_hash, parse_hash
from mailrobbe.config import Settings
from mailrobbe.jobrun import Step
from tests.api.conftest import _client, _execute, api_settings
from tests.conftest import GeneratedArchive, _temporary_database

pytestmark = pytest.mark.db

Json = dict[str, Any]

BLOCKS_MIN_MAILS = 3
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
EDITOR = "Lena%20Vogt"  # percent-encoded, as the web UI sends it (D54)
# The detected block with most senders, taken back by the team before the step ran again.
DISMISS = """
    INSERT INTO paragraph_override (hash, standard, sample, editor)
    SELECT hash, false, sample, 'Jonas' FROM paragraph_block
    ORDER BY senders DESC, hash LIMIT 1
"""


async def _find_blocks(url: str) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        settings = Settings(database_url=url, block_min_mails=BLOCKS_MIN_MAILS)
        await phase.find_blocks(sessionmaker, settings, asyncio.Event(), Step())
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def blocks_database_url(database_server_url: str, imported_database_url: str) -> Iterator[str]:
    """A copy of the imported archive with the blocks of BLOCKS_MIN_MAILS. Read only."""
    template = make_url(imported_database_url).database
    with _temporary_database(database_server_url, template) as url:
        asyncio.run(_find_blocks(url))
        asyncio.run(_execute(url, [DISMISS]))
        asyncio.run(_find_blocks(url))
        yield url


@pytest.fixture
async def blocks_client(
    blocks_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings(blocks_database_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


@pytest.fixture
def writable_url(database_server_url: str, blocks_database_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url, make_url(blocks_database_url).database) as url:
        yield url


@pytest.fixture
async def writable_client(
    writable_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = api_settings(writable_url, generated_archive, tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


async def rows(url: str, query: str, **parameters: object) -> list[Any]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            return list(await connection.execute(text(query), parameters))
    finally:
        await engine.dispose()


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def info(row: Any, override: bool | None = None, pending: bool = False) -> Json:
    """The BlockInfo of a paragraph_block row."""
    return {
        "hash": hash_hex(row.hash),
        "sample": row.sample,
        "standard": row.standard,
        "detected": row.detected,
        "override": override,
        "pending": pending,
        "mails": row.mails,
        "senders": row.senders,
        "first_date": None if row.first_date is None else _iso(row.first_date),
        "last_date": None if row.last_date is None else _iso(row.last_date),
    }


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def test_the_summary_counts_what_the_step_applied(
    blocks_client: httpx.AsyncClient, blocks_database_url: str
) -> None:
    kinds = (
        await rows(
            blocks_database_url,
            "SELECT count(*) FILTER (WHERE standard) AS blocks,"
            " count(*) FILTER (WHERE detected AND NOT standard) AS dismissed FROM paragraph_block",
        )
    )[0]
    with_blocks = await rows(
        blocks_database_url,
        "SELECT count(*) AS n FROM mail WHERE blocks IS NOT NULL AND is_duplicate_of IS NULL",
    )
    summary = await get(blocks_client, "/api/blocks/summary")
    assert kinds.blocks > 10 and kinds.dismissed == 1
    assert summary | {"computed_at": None} == {
        "blocks": kinds.blocks,
        "detected": kinds.blocks,
        "marked": 0,
        "dismissed": 1,
        "pending": 0,
        "mails": with_blocks[0].n,
        "waiting": 0,
        "min_mails": 25,  # the setting of this server, not of the step's run
        "computed_at": None,
    }
    assert summary["computed_at"] is not None


async def test_the_list_by_state_sample_and_sort(
    blocks_client: httpx.AsyncClient, blocks_database_url: str
) -> None:
    stored = await rows(
        blocks_database_url,
        "SELECT b.*, o.standard AS override FROM paragraph_block b"
        " LEFT JOIN paragraph_override o USING (hash)",
    )
    standard = sorted(
        (row for row in stored if row.standard), key=lambda row: (-row.mails, row.hash)
    )
    page = await get(blocks_client, "/api/blocks", limit=5)
    assert page == {"items": [info(row) for row in standard[:5]], "total": len(standard)}
    second = await get(blocks_client, "/api/blocks", limit=5, offset=5)
    assert second["items"] == [info(row) for row in standard[5:10]]

    recent = sorted(
        standard,
        key=lambda row: (row.last_date is None, -(row.last_date or EPOCH).timestamp(), row.hash),
    )
    by_date = await get(blocks_client, "/api/blocks", sort="recent", limit=200)
    assert [item["hash"] for item in by_date["items"]] == [hash_hex(row.hash) for row in recent]

    (dismissed,) = [row for row in stored if not row.standard]
    assert await get(blocks_client, "/api/blocks", state="dismissed") == {
        "items": [info(dismissed, override=False)],
        "total": 1,
    }
    word = standard[0].sample.split()[0]
    found = await get(blocks_client, "/api/blocks", q=word.upper(), limit=200)
    assert found["total"] == sum(word.lower() in row.sample.lower() for row in standard) > 0
    assert await get(blocks_client, "/api/blocks", q="100%_nicht") == {"items": [], "total": 0}


async def test_a_block_page_names_its_senders_and_domains(
    blocks_client: httpx.AsyncClient, blocks_database_url: str
) -> None:
    (block,) = await rows(
        blocks_database_url,
        "SELECT * FROM paragraph_block WHERE standard ORDER BY senders DESC, hash LIMIT 1",
    )
    senders = await rows(
        blocks_database_url,
        """SELECT f.person_id, s.canonical_email, s.domain, count(DISTINCT m.id) AS mails
            FROM mail_paragraph p
            JOIN mail m ON m.id = p.mail_id AND m.is_duplicate_of IS NULL
            JOIN participation f ON f.mail_id = m.id AND f.role = 'from'
            JOIN person s ON s.id = f.person_id
            WHERE p.hash = :hash GROUP BY f.person_id, s.canonical_email, s.domain""",
        hash=block.hash,
    )
    detail = await get(blocks_client, f"/api/blocks/{hash_hex(block.hash)}")
    assert detail["block"] == info(block)
    assert len(senders) == block.senders > 1
    listed = sorted(senders, key=lambda row: (-row.mails, row.person_id))[:BLOCK_SENDERS]
    assert [
        (item["person"]["person_id"], item["person"]["email"], item["mails"])
        for item in (detail["senders"])
    ] == [(row.person_id, row.canonical_email, row.mails) for row in listed]
    assert all("label" in item["person"] for item in detail["senders"])
    domains: dict[str, int] = {}
    for row in senders:
        domains[row.domain] = domains.get(row.domain, 0) + row.mails
    assert {item["domain"]: item["mails"] for item in detail["domains"]} == domains
    counts = [item["mails"] for item in detail["domains"]]
    assert counts == sorted(counts, reverse=True)


async def test_unknown_and_malformed_hashes(blocks_client: httpx.AsyncClient) -> None:
    response = await blocks_client.get("/api/blocks/00000000000000aa")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"
    for malformed in ("00000000000000AA", "123", "zzzzzzzzzzzzzzzz"):
        assert (await blocks_client.get(f"/api/blocks/{malformed}")).status_code == 422
    response = await blocks_client.put("/api/blocks/123/override", json={"standard": True})
    assert response.status_code == 422


async def test_the_team_takes_a_block_back_and_brings_it_again(
    writable_client: httpx.AsyncClient, writable_url: str
) -> None:
    (block,) = await rows(
        writable_url,
        "SELECT * FROM paragraph_block WHERE standard ORDER BY mails DESC, hash LIMIT 1",
    )
    path = f"/api/blocks/{hash_hex(block.hash)}/override"
    response = await writable_client.put(
        path, json={"standard": False}, headers={"X-Mailrobbe-Editor": EDITOR}
    )
    assert response.status_code == 200, response.text
    assert response.json() == info(block, override=False, pending=True)
    stored = await rows(
        writable_url, "SELECT * FROM paragraph_override WHERE hash = :h", h=block.hash
    )
    assert (stored[0].standard, stored[0].sample, stored[0].editor) == (
        False,
        block.sample,
        "Lena Vogt",
    )
    assert (await get(writable_client, "/api/blocks/summary"))["pending"] == 1
    listed = await get(writable_client, "/api/blocks", limit=1)
    assert listed["items"] == [info(block, override=False, pending=True)]

    # "Wieder als Standardblock": what detection says, so the choice goes
    response = await writable_client.put(path, json={"standard": True})
    assert response.json() == info(block)
    assert (
        await rows(writable_url, "SELECT 1 FROM paragraph_override WHERE hash = :h", h=block.hash)
        == []
    )
    assert (await get(writable_client, "/api/blocks/summary"))["pending"] == 0

    # the block taken back before: brought again, pending until the next run
    (dismissed,) = await rows(writable_url, "SELECT * FROM paragraph_block WHERE NOT standard")
    response = await writable_client.put(
        f"/api/blocks/{hash_hex(dismissed.hash)}/override", json={"standard": None}
    )
    assert response.json() == info(dismissed, pending=True)
    await _find_blocks(writable_url)
    again = await get(writable_client, f"/api/blocks/{hash_hex(dismissed.hash)}")
    assert (again["block"]["standard"], again["block"]["pending"]) == (True, False)


async def test_the_team_marks_a_paragraph_not_counted_yet(
    writable_client: httpx.AsyncClient, writable_url: str
) -> None:
    # a paragraph in the middle of some mails, which detection never looks at
    (paragraph,) = await rows(
        writable_url,
        """SELECT p.hash, substr(m.body_text, lower(p.span) + 1, upper(p.span) - lower(p.span))
                AS sample, count(*) OVER (PARTITION BY p.hash) AS held
            FROM mail_paragraph p JOIN mail m ON m.id = p.mail_id
            WHERE NOT p.tail AND NOT p.quoted AND m.is_duplicate_of IS NULL
                AND p.hash NOT IN (SELECT hash FROM paragraph_block)
            ORDER BY held DESC, p.hash, p.mail_id LIMIT 1""",
    )
    value = hash_hex(paragraph.hash)
    path = f"/api/blocks/{value}/override"
    missing = await writable_client.put(path, json={"standard": True})
    assert missing.status_code == 400 and missing.json()["detail"]["code"] == "invalid_block"
    other = await writable_client.put(
        path, json={"standard": True, "sample": "Ein anderer Absatz, der nicht passt."}
    )
    assert other.status_code == 400 and other.json()["detail"]["code"] == "invalid_block"
    assert (await writable_client.get(f"/api/blocks/{value}")).status_code == 404

    # the sample as the mail detail shows it, quote markers and case do not matter
    marked = await writable_client.put(
        path, json={"standard": True, "sample": "> " + paragraph.sample.upper()}
    )
    assert marked.status_code == 200, marked.text
    held = await rows(
        writable_url,
        """SELECT count(DISTINCT m.id) AS mails, count(DISTINCT f.person_id) AS senders,
                min(m.date_utc) AS first_date, max(m.date_utc) AS last_date
            FROM mail_paragraph p
            JOIN mail m ON m.id = p.mail_id AND m.is_duplicate_of IS NULL
            LEFT JOIN participation f ON f.mail_id = m.id AND f.role = 'from'
            WHERE p.hash = :h""",
        h=paragraph.hash,
    )
    expected = {
        "hash": value,
        "sample": "> " + paragraph.sample.upper(),
        "standard": False,
        "detected": False,
        "override": True,
        "pending": True,
        "mails": held[0].mails,
        "senders": held[0].senders,
        "first_date": _iso(held[0].first_date),
        "last_date": _iso(held[0].last_date),
    }
    assert marked.json() == expected
    page = await get(writable_client, f"/api/blocks/{value}")
    assert page["block"] == expected and len(page["senders"]) == held[0].senders
    assert (await get(writable_client, "/api/blocks/summary"))["pending"] == 1

    # taken back before any run: nothing knows the paragraph any more but the answer
    undone = await writable_client.put(path, json={"standard": False})
    assert undone.json() == expected | {"override": None, "pending": False}
    assert (await writable_client.get(f"/api/blocks/{value}")).status_code == 404

    # after a run the mark is a block of its own, standard by hand
    await writable_client.put(path, json={"standard": True, "sample": paragraph.sample})
    await _find_blocks(writable_url)
    block = (await get(writable_client, f"/api/blocks/{value}"))["block"]
    assert paragraph_hash(block["sample"]) == paragraph.hash  # one occurrence as written
    assert block | {"sample": None} == expected | {
        "sample": None,
        "standard": True,
        "pending": False,
    }
    summary = await get(writable_client, "/api/blocks/summary")
    assert (summary["marked"], summary["pending"]) == (1, 0)
    assert parse_hash(value) == paragraph.hash


async def test_the_text_of_a_mail_folds_its_standard_blocks(
    blocks_client: httpx.AsyncClient, blocks_database_url: str
) -> None:
    (mail,) = await rows(
        blocks_database_url,
        """SELECT id FROM mail WHERE blocks IS NOT NULL AND history IS NOT NULL
            AND length(body_text) < 40000 ORDER BY id LIMIT 1""",
    )
    known = {
        row.hash: row
        for row in await rows(
            blocks_database_url,
            "SELECT b.hash, b.standard, b.mails, o.standard AS override FROM paragraph_block b"
            " LEFT JOIN paragraph_override o USING (hash)",
        )
    }
    body = await get(blocks_client, f"/api/mails/{mail.id}/body", format="text")
    shown, segments = body["text"], body["segments"]
    assert segments[0]["start"] == 0 and segments[-1]["end"] == len(shown)
    assert all(a["end"] == b["start"] for a, b in itertools.pairwise(segments))
    standard = [segment for segment in segments if segment["kind"] == "standard"]
    assert standard and all(segment["folded"] for segment in standard)
    for paragraph in body["paragraphs"]:
        row = known.get(parse_hash(paragraph["hash"]))
        assert paragraph["standard"] == (row is not None and row.standard)
        assert paragraph["mails"] == (0 if row is None else row.mails)
        assert paragraph["override"] == (None if row is None else row.override)
        cut = [segment for segment in standard if segment["start"] == paragraph["start"]]
        assert len(cut) == paragraph["standard"]
        if cut:
            assert cut[0]["block"] == paragraph["hash"] and cut[0]["end"] >= paragraph["end"]
            assert shown[cut[0]["start"] : cut[0]["end"]].strip() == (
                shown[paragraph["start"] : paragraph["end"]].strip()
            )
    # the other views and the text of a mail without paragraphs are as before
    plain = await rows(blocks_database_url, "SELECT id FROM mail WHERE body_text = '' LIMIT 1")
    if plain:
        empty = await get(blocks_client, f"/api/mails/{plain[0].id}/body", format="text")
        assert empty["paragraphs"] == []

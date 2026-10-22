"""Summaries stored (D301, D305) and discarded (D185), and the vocabulary of a run (D305), on a
migrated database."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.ai.model import Summary, SummaryPart, ThemeHint
from mailrobbe.ai.store import discard_result, store_summary_result
from mailrobbe.ai.summarize.prompt import load_vocabulary
from mailrobbe.enums import AiTarget
from mailrobbe.themes import load_themes

MAIL = "m" * 64
DOCUMENT = "d" * 64


def summary(body: str, tags: list[str], *, short: bool = False, **values: Any) -> Summary:
    part = SummaryPart(number=1, characters=400, summary=body, seconds=1.5, tokens_in=300)
    return Summary(
        summary=body,
        tags=tags,
        themes=values.pop("themes", []),
        parts=[part],
        parts_total=values.pop("parts_total", 1),
        short=short,
        words=values.pop("words", 80),
        **values,
    )


async def store(
    session: AsyncSession, found: Summary, *, target: AiTarget = AiTarget.MAIL, sha256: str = MAIL
) -> int:
    return await store_summary_result(
        session,
        target=target,
        sha256=sha256,
        summary=found,
        model="textmodell",
        service_url="http://127.0.0.1:1234/v1",
        remote=False,
        prompt_version=1,
        options={"context_tokens": 8192},
        seconds=1.5,
        tokens_in=300,
        tokens_out=60,
        job_id=None,
    )


async def results(session: AsyncSession) -> dict[int, Any]:
    found = await session.execute(
        text("SELECT *, state::text AS state_name FROM ai_result ORDER BY id")
    )
    return {row.id: row for row in found}


async def tags_of(session: AsyncSession, result_id: int) -> list[str]:
    found = await session.execute(
        text("""
            SELECT t.label FROM ai_tag_link l JOIN ai_tag t ON t.id = l.tag_id
            WHERE l.result_id = :id ORDER BY t.label COLLATE "C"
        """),
        {"id": result_id},
    )
    return list(found.scalars())


async def test_a_summary_is_stored_with_its_tags_and_hints(db_session: AsyncSession) -> None:
    hints = [
        ThemeHint(theme="spenden", quote="Spende über 500 Euro", position=120),
        ThemeHint(theme="spenden", quote="Förderverein", position=None),
    ]
    found = summary(
        "Anna kündigt das Sommerfest an.",
        ["Sommerfest", "Spenden-Quittung"],
        themes=hints,
        dropped_tags=1,
        dropped_themes=2,
        parts_total=3,
    )
    result_id = await store(db_session, found)

    row = (await results(db_session))[result_id]
    assert (row.kind, row.target, row.target_sha256, row.state_name) == (
        "summarize",
        "mail",
        MAIL,
        "valid",
    )
    assert (row.engine, row.model, row.remote, row.prompt_version) == (
        "text",
        "textmodell",
        False,
        1,
    )
    assert row.body == "Anna kündigt das Sommerfest an."
    assert (row.pages_total, row.tokens_in, row.tokens_out, row.seconds) == (3, 300, 60, 1.5)
    assert row.pages == [
        {
            "number": 1,
            "characters": 400,
            "summary": "Anna kündigt das Sommerfest an.",
            "error": None,
            "seconds": 1.5,
            "tokens_in": 300,
            "tokens_out": 0,
        }
    ]
    assert row.options == {
        "context_tokens": 8192,
        "short": False,
        "words": 80,
        "origin": None,
        "dropped_tags": 1,
        "dropped_themes": 2,
    }
    assert await tags_of(db_session, result_id) == ["Sommerfest", "Spenden-Quittung"]
    stored = await db_session.execute(
        text("SELECT theme, quote, position FROM ai_theme_hint WHERE result_id = :id ORDER BY id"),
        {"id": result_id},
    )
    assert [tuple(hint) for hint in stored] == [
        ("spenden", "Spende über 500 Euro", 120),
        ("spenden", "Förderverein", None),
    ]


async def test_tags_are_shared_by_their_key_and_keep_their_first_spelling(
    db_session: AsyncSession,
) -> None:
    first = await store(db_session, summary("Eins.", ["Spenden-Quittung", "Größe"]))
    second = await store(
        db_session,
        summary("Zwei.", ["spenden quittung", "Groesse", "Neu"]),
        target=AiTarget.DOCUMENT,
        sha256=DOCUMENT,
    )
    keys = await db_session.execute(text('SELECT key, label FROM ai_tag ORDER BY key COLLATE "C"'))
    assert [tuple(row) for row in keys] == [
        ("groesse", "Größe"),
        ("neu", "Neu"),
        ("spenden quittung", "Spenden-Quittung"),
    ]
    assert await tags_of(db_session, first) == ["Größe", "Spenden-Quittung"]
    assert await tags_of(db_session, second) == ["Größe", "Neu", "Spenden-Quittung"]


async def test_a_new_summary_replaces_the_old_and_discarding_brings_it_back(
    db_session: AsyncSession,
) -> None:
    ocr = await db_session.scalar(
        text("""
            INSERT INTO ai_result (kind, target, target_sha256, engine, body, pages, pages_total)
            VALUES ('ocr', 'document', :sha256, 'tesseract', 'Text', '[]', 1) RETURNING id
        """),
        {"sha256": MAIL},
    )
    short = await store(db_session, summary("", ["Dank"], short=True, words=3))
    full = await store(db_session, summary("Die neue.", ["Sommerfest"]))
    other = await store(
        db_session, summary("Ein Dokument.", []), target=AiTarget.DOCUMENT, sha256=MAIL
    )
    states = {key: row.state_name for key, row in (await results(db_session)).items()}
    assert states == {ocr: "valid", short: "replaced", full: "valid", other: "valid"}

    assert await discard_result(db_session, full, "Bea") is True
    rows = await results(db_session)
    assert (rows[full].state_name, rows[full].discarded_by) == ("discarded", "Bea")
    assert rows[short].state_name == "valid"  # a short one, without a text, comes back too
    assert rows[short].options["short"] is True and rows[short].body == ""
    assert (rows[ocr].state_name, rows[other].state_name) == ("valid", "valid")
    assert await tags_of(db_session, full) == ["Sommerfest"]  # kept with the discarded result

    assert await discard_result(db_session, short, None) is True
    rows = await results(db_session)
    assert rows[short].state_name == "discarded"
    assert (rows[ocr].state_name, rows[other].state_name) == ("valid", "valid")
    assert await discard_result(db_session, short, None) is False


async def test_the_vocabulary_offers_the_team_tags_then_the_most_used_ai_tags(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        text("INSERT INTO tag (name, color) VALUES ('zeugen', 'red'), ('Belege', 'blue')")
    )
    await store(db_session, summary("Eins.", ["Zeugen", "Kasse"]))
    await store(
        db_session,
        summary("Zwei.", ["Kasse", "Vorstand"]),
        target=AiTarget.DOCUMENT,
        sha256="e" * 64,
    )
    discarded = await store(
        db_session,
        summary("Drei.", ["Verworfen"]),
        target=AiTarget.DOCUMENT,
        sha256=DOCUMENT,
    )
    await discard_result(db_session, discarded, None)

    vocabulary = await load_vocabulary(db_session)
    assert vocabulary.tags == ("Belege", "zeugen", "Kasse", "Vorstand")
    assert vocabulary.themes == load_themes()

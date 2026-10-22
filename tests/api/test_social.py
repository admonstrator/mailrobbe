"""The social media image of one mail (D214 to D217) against the imported generated archive.

The redaction itself is tested without a database (tests/social); here the two endpoints are
checked against real mails: the PNG has the format asked for, the card's figures belong to it,
and no address of the mail's participants is left in what the card says about itself. A
transcript's picture (D298) is checked on a copy of the database with a transcript stored as a
run stores it.
"""

import io
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mailrobbe.ai.model import TranscriptSegment
from mailrobbe.ai.store import store_transcript_result
from mailrobbe.social.model import SHAPES, CardShape

pytestmark = pytest.mark.db


async def _a_mail(client: httpx.AsyncClient) -> dict[str, Any]:
    """A mail of the archive with a sender, recipients and a text."""
    response = await client.get("/api/mails", params={"limit": 20})
    assert response.status_code == 200
    for item in response.json()["items"]:
        detail = await client.get(f"/api/mails/{item['id']}")
        assert detail.status_code == 200
        if detail.json()["participants"]:
            return dict(detail.json())
    raise AssertionError("no mail with participants in the archive")


async def test_the_png_has_the_format_asked_for(client: httpx.AsyncClient) -> None:
    mail = await _a_mail(client)
    for shape in CardShape:
        response = await client.get(
            f"/api/mails/{mail['id']}/social.png", params={"shape": shape.value}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        image = Image.open(io.BytesIO(response.content))
        assert image.size == SHAPES[shape]


async def test_the_card_says_what_the_picture_blacks_out(client: httpx.AsyncClient) -> None:
    mail = await _a_mail(client)
    response = await client.get(f"/api/mails/{mail['id']}/social")
    assert response.status_code == 200
    card = response.json()
    assert (card["width"], card["height"]) == SHAPES[CardShape.PORTRAIT]
    assert card["places"] == sum(part["places"] for part in card["redactions"])
    assert card["places"] > 0  # every mail has a sender
    assert card["lines"] >= 1
    participants = [person["email"] for person in mail["participants"]]
    assert not [address for address in participants if address in response.text]


async def test_the_parameters_hold_for_the_card_and_its_picture(client: httpx.AsyncClient) -> None:
    mail = await _a_mail(client)
    params = {"shape": "wide", "participants": "false", "terms": ["Projekt Nord"]}
    card = await client.get(f"/api/mails/{mail['id']}/social", params=params)
    assert card.status_code == 200
    assert (card.json()["width"], card.json()["height"]) == SHAPES[CardShape.WIDE]
    image = await client.get(f"/api/mails/{mail['id']}/social.png", params=params)
    assert image.status_code == 200
    assert Image.open(io.BytesIO(image.content)).size == SHAPES[CardShape.WIDE]


async def test_an_unknown_mail_is_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/mails/999999999/social.png")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


async def test_too_many_own_terms_are_refused(client: httpx.AsyncClient) -> None:
    mail = await _a_mail(client)
    response = await client.get(
        f"/api/mails/{mail['id']}/social", params={"terms": [f"Begriff {n}" for n in range(21)]}
    )
    assert response.status_code == 422


# A transcribed recording (D298) ----------------------------------------------------------------

LINES = [
    TranscriptSegment(start=0.5, end=4.0, text="Hallo, hier spricht die Kasse."),
    TranscriptSegment(start=5.0, end=9.0, text="Die Spende kommt am Freitag in bar."),
    TranscriptSegment(start=10.0, end=14.0, text="Bitte nichts per Mail schreiben."),
]


@dataclass(frozen=True, slots=True)
class Recording:
    document: int
    attachment: int  # of the first mail carrying it
    other: int  # an attachment of another document


async def _recording(url: str) -> Recording:
    """A document carried by an original mail, given a transcript as a run stores it."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """SELECT d.id, d.sha256, a.id AS attachment FROM document d
                    JOIN attachment a ON a.document_id = d.id AND a.mail_id = d.first_mail_id
                    WHERE d.sha256 IS NOT NULL ORDER BY d.kind = 'media' DESC, d.id LIMIT 1"""
                )
            )
        ).one()
        other = await connection.scalar(
            text("SELECT min(id) FROM attachment WHERE document_id <> :id"), {"id": row.id}
        )
    async with AsyncSession(engine) as session:
        await store_transcript_result(
            session,
            sha256=row.sha256,
            segments=LINES,
            duration=15.0,
            transcribed=15.0,
            audio=True,
            options={},
            seconds=1.0,
            job_id=None,
        )
        await session.commit()
    await engine.dispose()
    assert other is not None
    return Recording(row.id, row.attachment, other)


async def test_a_transcript_becomes_a_picture(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    recording = await _recording(mutable_database_url)
    path = f"/api/documents/{recording.document}/social"
    card = (await mutable_client.get(path)).json()
    assert (card["width"], card["height"]) == SHAPES[CardShape.PORTRAIT]
    assert card["lines"] == len(LINES)
    assert card["places"] == sum(part["places"] for part in card["redactions"])
    assert card["places"] > 0  # the mail's sender at least
    for shape in CardShape:
        image = await mutable_client.get(f"{path}.png", params={"shape": shape.value})
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(image.content)).size == SHAPES[shape]
    asked = await mutable_client.get(path, params={"attachment": recording.attachment})
    assert asked.status_code == 200


async def test_an_excerpt_shows_the_lines_spoken_in_it(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    recording = await _recording(mutable_database_url)
    path = f"/api/documents/{recording.document}/social"
    card = (await mutable_client.get(path, params={"start": 4.5, "end": 9.5})).json()
    assert card["lines"] == 1
    assert (await mutable_client.get(path, params={"start": 9, "end": 4})).status_code == 422


async def test_a_picture_needs_a_transcript_and_a_carrying_mail(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    recording = await _recording(mutable_database_url)
    path = f"/api/documents/{recording.document}/social"
    wrong = await mutable_client.get(path, params={"attachment": recording.other})
    assert wrong.status_code == 404
    untranscribed = await mutable_client.get(f"/api/documents/{recording.document + 1}/social")
    assert untranscribed.status_code == 404
    assert untranscribed.json()["detail"]["code"] == "not_found"

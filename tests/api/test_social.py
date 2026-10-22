"""The social media image of one mail (D214 to D217) against the imported generated archive.

The redaction itself is tested without a database (tests/social); here the two endpoints are
checked against real mails: the PNG has the format asked for, the card's figures belong to it,
and no address of the mail's participants is left in what the card says about itself.
"""

import io
from typing import Any

import httpx
import pytest
from PIL import Image

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

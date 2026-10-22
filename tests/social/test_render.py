"""The picture of one mail (D214, D216): what its plan holds and what the PNG is.

The plan is what can ever be drawn, so the tests read it as text; the PNG is checked for its
format, its size and that it holds no metadata of its own.
"""

import io

import pytest
from PIL import Image

from mailrobbe.export.records import ExportMail
from mailrobbe.social.model import SHAPES, CardOptions, CardShape
from mailrobbe.social.redact import BLOCK
from mailrobbe.social.render import CUT, WATERMARK, plan, render_card
from tests.social.conftest import (
    IBAN,
    RECIPIENT,
    RECIPIENT_NAME,
    SENDER,
    SENDER_NAME,
    SUBJECT,
    export_mail,
    message,
)


def card_text(mail: ExportMail, raw: bytes, options: CardOptions) -> str:
    """Every text of the plan in one string: everything the picture can show."""
    drawn = plan(mail, raw, options)
    return "\n".join(
        [
            drawn.watermark,
            *drawn.subject,
            drawn.sender,
            drawn.address,
            drawn.recipients,
            drawn.date,
            drawn.dkim or "",
            drawn.footer,
            drawn.checksum,
            *drawn.attachments,
            *(line.text for line in drawn.body),
        ]
    )


def test_no_participant_is_left_in_the_picture(mail: ExportMail, raw: bytes) -> None:
    shown = card_text(mail, raw, CardOptions())
    for gone in (SENDER, SENDER_NAME, RECIPIENT, RECIPIENT_NAME, "Petrova", "Jürgen", IBAN):
        assert gone not in shown
    assert BLOCK in shown
    assert SUBJECT in shown  # the subject itself names no person here


def test_without_redaction_the_mail_is_shown_as_it_is(mail: ExportMail, raw: bytes) -> None:
    shown = card_text(mail, raw, CardOptions(participants=False, contacts=False, names=False))
    assert SENDER_NAME in shown and RECIPIENT in shown and IBAN in shown
    assert BLOCK not in shown


def test_every_picture_says_where_it_comes_from(mail: ExportMail, raw: bytes) -> None:
    """The watermark stands in the window's bar and in every format (D214); it names Mailrobbe
    and the project's page, never the mail."""
    assert WATERMARK == "Exportiert aus Mailrobbe (by admon.me)"
    for shape in CardShape:
        assert plan(mail, raw, CardOptions(shape=shape)).watermark == WATERMARK
    assert WATERMARK in card_text(mail, raw, CardOptions())


def test_the_card_names_the_mail_and_its_dkim(mail: ExportMail, raw: bytes) -> None:
    drawn = plan(mail, raw, CardOptions())
    assert drawn.date == "3. März 2020, 09:15 UTC"
    assert drawn.dkim == "DKIM gültig"
    assert drawn.checksum == mail.raw_sha256[:16]
    assert drawn.footer == f"{drawn.redaction.places} Stellen geschwärzt"
    assert drawn.attachments == ["Spendenquittung ████.pdf · 1,2 MB"]
    assert drawn.initial is None  # the sender's name is blacked out, so is the avatar


def test_the_seal_and_the_checksum_can_be_left_out(mail: ExportMail, raw: bytes) -> None:
    drawn = plan(mail, raw, CardOptions(dkim=False, checksum=False))
    assert drawn.dkim is None
    assert drawn.checksum == ""


def test_quoted_text_only_on_request(mail: ExportMail, raw: bytes) -> None:
    without = card_text(mail, raw, CardOptions())
    assert "vertraulich" not in without
    with_quotes = card_text(mail, raw, CardOptions(quotes=True))
    assert "vertraulich" in with_quotes


def test_a_long_text_is_cut_to_the_format() -> None:
    raw = message("Sehr geehrte Damen und Herren,\n\n" + "Wort " * 4000)
    mail = export_mail(raw)
    drawn = plan(mail, raw, CardOptions(shape=CardShape.WIDE))
    assert drawn.truncated
    assert drawn.body[-1].text == CUT
    assert all(not line.rule for line in drawn.body if line.text == CUT)
    short = plan(export_mail(message()), message(), CardOptions(shape=CardShape.PORTRAIT))
    assert not short.truncated


def test_a_mail_without_a_text_says_so() -> None:
    raw = message("")
    drawn = plan(export_mail(raw), raw, CardOptions())
    assert [line.text for line in drawn.body] == ["(kein Text)"]


@pytest.mark.parametrize("shape", list(CardShape))
def test_the_png_has_the_format_asked_for(mail: ExportMail, raw: bytes, shape: CardShape) -> None:
    card = render_card(mail, raw, CardOptions(shape=shape))
    image = Image.open(io.BytesIO(card.png))
    assert image.format == "PNG"
    assert image.size == SHAPES[shape]
    assert not {key for key in image.info if key not in ("dpi",)}  # no metadata of its own


def test_the_same_mail_gives_the_same_bytes(mail: ExportMail, raw: bytes) -> None:
    first = render_card(mail, raw, CardOptions())
    second = render_card(mail, raw, CardOptions())
    assert first.png == second.png
    other = render_card(mail, raw, CardOptions(checksum=False))
    assert other.png != first.png

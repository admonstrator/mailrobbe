"""The picture of one mail (D214, D216): what its plan holds and what the PNG is.

The plan is what can ever be drawn, so the tests read it as text; the PNG is checked for its
format, its size and that it holds no metadata of its own.
"""

import io
from typing import Any

import pytest
from PIL import Image

from mailrobbe.ai.model import TranscriptSegment
from mailrobbe.export.records import ExportMail
from mailrobbe.social.model import SHAPES, CardOptions, CardShape, RedactionKind
from mailrobbe.social.redact import BLOCK
from mailrobbe.social.render import (
    CUT,
    TRANSCRIPT_CUT,
    WATERMARK,
    CardPlan,
    draw,
    plan,
    plan_transcript,
    render_card,
)
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


# A transcribed recording (D298) ----------------------------------------------------------------

SPOKEN = [
    TranscriptSegment(start=0.4, end=3.2, text="Hallo Jürgen, hier ist Anna."),
    TranscriptSegment(start=4.0, end=12.1, text="Die Spende bringe ich am Freitag bar vorbei."),
    TranscriptSegment(start=13.0, end=19.6, text="Ruf mich an, Tel. 030 1234567.", uncertain=True),
    TranscriptSegment(start=21.0, end=25.8, text="Sag Herrn Weiß noch nichts davon."),
]


def transcript_card(excerpt: tuple[float, float] | None = None, **chosen: Any) -> CardPlan:
    mail = export_mail(message())
    options = CardOptions(**chosen)
    return plan_transcript(
        mail, "Sprachnachricht Petrova.ogg", 215_400, 31.0, SPOKEN, options, excerpt
    )


def test_a_transcript_shows_its_lines_with_their_times_blacked_out() -> None:
    drawn = transcript_card()
    assert drawn.recording is not None
    assert [line.time for line in drawn.body if line.time] == ["0:00", "0:04", "0:13", "0:21"]
    shown = "\n".join([*(line.text for line in drawn.body), *drawn.recording.note])
    for gone in ("Jürgen", "Anna", "Weiß", "Petrova", "1234567"):
        assert gone not in shown
    assert "Die Spende bringe ich am Freitag bar vorbei." in shown
    assert drawn.redaction.counts[RedactionKind.PARTICIPANT] >= 4


def test_a_transcript_says_it_is_machine_made_and_how_long_it_is() -> None:
    drawn = transcript_card()
    assert drawn.recording is not None
    assert drawn.recording.length == "0:31"
    assert drawn.recording.note == [
        "Sprachnachricht ████.ogg · 210,4 KB · maschinell transkribiert · grau: unsicher erkannt"
    ]
    assert [line.quoted for line in drawn.body] == [False, False, True, False]  # uncertain grey
    # the speech is drawn from the lines' times, as parts of the length
    assert drawn.recording.speech[0] == pytest.approx((0.4 / 31, 3.2 / 31))


def test_an_excerpt_keeps_the_lines_spoken_in_it() -> None:
    drawn = transcript_card((13.0, 21.0))
    assert [line.time for line in drawn.body if line.time] == ["0:13"]
    assert drawn.recording is not None
    assert drawn.recording.excerpt == pytest.approx((13 / 31, 21 / 31))
    assert "Ausschnitt 0:13 bis 0:21" in drawn.recording.note[0]
    empty = transcript_card((26.0, 31.0))
    assert [line.text for line in empty.body] == ["(in diesem Ausschnitt wird nichts gesagt)"]


def test_a_long_transcript_is_cut_to_the_format() -> None:
    mail = export_mail(message())
    many = [
        TranscriptSegment(start=n * 5.0, end=n * 5.0 + 4, text=f"Satz Nummer {n}.")
        for n in range(200)
    ]
    drawn = plan_transcript(mail, "a.ogg", 1, None, many, CardOptions(shape=CardShape.WIDE))
    assert drawn.truncated
    assert drawn.body[-1].text == TRANSCRIPT_CUT
    assert drawn.recording is not None and drawn.recording.length == "16:39"  # the last line's end


@pytest.mark.parametrize("shape", list(CardShape))
def test_a_transcripts_png_has_the_format_asked_for(shape: CardShape) -> None:
    image = Image.open(io.BytesIO(draw(transcript_card(shape=shape))))
    assert image.size == SHAPES[shape]

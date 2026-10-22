"""One mail drawn as a picture for social media (D214): a pseudo mail client, not a screenshot.

The card is a window of its own invention — a bar with three dots, the subject, an avatar, the
participants, the date with the DKIM seal, the text, the attachments and a footer with what was
blacked out and the mail's checksum (D61). No real client, service or organisation is imitated:
the look says "this is a mail" and nothing about where it was read.

plan() prepares what the card shows: every text through the Redactor of redact.py, wrapped to
the lines that fit the chosen format, and the places counted. draw() turns a plan into PNG
bytes. Nothing else reaches the picture, so what a published image can hold is what plan()
returns, and a test reads it as text.

The fonts are the DejaVu faces the PDF ships (export/fonts), regular and bold, so an image
looks the same on every machine; the PNG carries no metadata of its own.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from mailrobbe import quotes
from mailrobbe.api import body
from mailrobbe.enums import DkimStatus, ParticipationRole
from mailrobbe.export import records
from mailrobbe.export.records import ExportMail
from mailrobbe.social.model import SHAPES, CardOptions, Redaction
from mailrobbe.social.redact import BLOCK, Redactor, redactor

FONTS = Path(records.__file__).parent / "fonts"  # the faces of the PDF (D63)
REGULAR = FONTS / "DejaVuSans.ttf"
BOLD = FONTS / "DejaVuSans-Bold.ttf"

RGB = tuple[int, int, int]
PAGE: RGB = (237, 238, 242)  # around the window
SURFACE: RGB = (255, 255, 255)
CHROME: RGB = (246, 247, 249)  # the window's bar and footer (SPEC 7 background)
BORDER: RGB = (227, 230, 235)
INK: RGB = (22, 24, 29)
MUTED: RGB = (91, 98, 112)
DOT: RGB = (214, 217, 224)
AVATAR: RGB = (205, 210, 219)
QUOTE_RULE: RGB = (214, 217, 224)
REDACTED: RGB = (22, 24, 29)  # the bars, black wherever they stand
DKIM_COLORS: dict[DkimStatus, RGB] = {
    DkimStatus.PASS: (22, 163, 74),
    DkimStatus.CONSISTENT: (22, 163, 74),
    DkimStatus.FAIL: (220, 38, 38),
    DkimStatus.NO_KEY: (217, 119, 6),
    DkimStatus.TEMP_ERROR: (217, 119, 6),
    DkimStatus.UNSIGNED: (156, 163, 175),
}
DKIM_TEXTS: dict[DkimStatus, str] = {
    DkimStatus.PASS: "DKIM gültig",
    DkimStatus.CONSISTENT: "DKIM stimmig",
    DkimStatus.FAIL: "DKIM ungültig",
    DkimStatus.NO_KEY: "DKIM: Schlüssel fehlt",
    DkimStatus.TEMP_ERROR: "DKIM: DNS-Fehler",
    DkimStatus.UNSIGNED: "nicht signiert",
}
MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)

MARGIN = 28  # the page around the window
PAD = 36  # inside the window
BAR = 64  # the window's bar
FOOT = 58  # the window's footer
RADIUS = 22
AVATAR_SIZE = 72
SUBJECT_SIZE = 34
SUBJECT_LINES = 2
NAME_SIZE = 24
META_SIZE = 20
TEXT_SIZE = 23
LINE = 1.52  # line height of the body, as a factor of its size
CHIP_HEIGHT = 40
GAP = 14  # between the text, the attachments and the footer
CHIPS = 3  # attachments named on the card; the rest counted
RECIPIENTS = 3  # recipients named per line; the rest counted
TEXT_LIMIT = 20_000  # characters read before wrapping; no format shows more
CHECKSUM_DIGITS = 16  # the permalink's digits (D61)
CUT = "… Text gekürzt"
_RUNS = re.compile(f"({BLOCK}+)")  # a line split into its bars and the text between them


@dataclass(frozen=True, slots=True)
class Line:
    """One line of the body as it is drawn."""

    text: str
    quoted: bool = False  # grey, as a mail client shows quoted text
    rule: bool = True  # the bar beside a quoted line; a note of Mailrobbe's own has none


@dataclass(frozen=True, slots=True)
class CardPlan:
    """Everything the picture shows, redacted and already cut to the format (D216)."""

    width: int
    height: int
    subject: list[str]
    sender: str
    address: str
    recipients: str
    date: str
    dkim: str | None
    dkim_color: RGB
    initial: str | None  # the sender's initial in the avatar; None when it is blacked out
    body: list[Line] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    more_attachments: int = 0
    footer: str = ""
    checksum: str = ""
    truncated: bool = False
    redaction: Redaction = field(default_factory=Redaction)


@dataclass(frozen=True, slots=True)
class Card:
    """A rendered card: the PNG and what it says about itself."""

    png: bytes
    plan: CardPlan


@lru_cache(maxsize=16)
def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def plan(mail: ExportMail, message: bytes, options: CardOptions) -> CardPlan:
    """What the card of this mail shows under these options: every text blacked out by the one
    rule of redact.py, wrapped to the format and cut where it no longer fits."""
    width, height = SHAPES[options.shape]
    hide = redactor(mail, options)
    inner = width - 2 * MARGIN - 2 * PAD
    subject_font = _font(BOLD, SUBJECT_SIZE)
    text_font = _font(REGULAR, TEXT_SIZE)

    redaction = Redaction()
    subject, done = _redact(hide, mail.subject or "(ohne Betreff)")
    redaction += done
    sender, address, initial, done = _sender(mail, hide, options)
    redaction += done
    recipients, done = _recipients(mail, hide)
    redaction += done
    names, more, done = _attachments(mail, hide)
    redaction += done
    lines, done = _body(mail, message, hide, options, inner, text_font)
    redaction += done

    # The room the text has: the window below the header, without the attachments and the
    # footer. draw() places both the same way.
    headline = _wrap(subject, subject_font, inner, SUBJECT_LINES)
    chips = CHIP_HEIGHT + GAP if names else 0
    room = height - 2 * MARGIN - FOOT - _body_top(len(headline)) - chips - GAP
    fits = max(0, room // round(TEXT_SIZE * LINE))
    truncated = len(lines) > fits
    if truncated:
        lines = lines[: max(0, fits - 1)]
        lines.append(Line(CUT, quoted=True, rule=False))

    places = redaction.places
    blacked = f"{places} Stelle{'' if places == 1 else 'n'} geschwärzt"
    return CardPlan(
        width=width,
        height=height,
        subject=headline,
        sender=sender,
        address=address,
        recipients=recipients,
        date=_date(mail.date),
        dkim=_dkim_text(mail.dkim_status) if options.dkim else None,
        dkim_color=DKIM_COLORS.get(mail.dkim_status or DkimStatus.UNSIGNED, MUTED),
        initial=initial,
        body=lines,
        attachments=names,
        more_attachments=more,
        footer=blacked if places else "nichts geschwärzt",
        checksum=mail.raw_sha256[:CHECKSUM_DIGITS] if options.checksum else "",
        truncated=truncated,
        redaction=redaction,
    )


def render_card(mail: ExportMail, message: bytes, options: CardOptions) -> Card:
    """The PNG of one mail with its plan (what it shows and what was blacked out)."""
    prepared = plan(mail, message, options)
    return Card(draw(prepared), prepared)


def draw(card: CardPlan) -> bytes:
    """A plan as PNG bytes; nothing is read here that the plan does not hold."""
    image = Image.new("RGB", (card.width, card.height), PAGE)
    pen = ImageDraw.Draw(image)
    left, top = MARGIN, MARGIN
    right, bottom = card.width - MARGIN, card.height - MARGIN
    pen.rounded_rectangle(
        (left, top, right, bottom), radius=RADIUS, fill=SURFACE, outline=BORDER, width=1
    )

    # The window's bar: three dots and the folder a mail client would name.
    pen.rounded_rectangle(
        (left, top, right, top + BAR + RADIUS), radius=RADIUS, fill=CHROME, outline=BORDER
    )
    pen.rectangle((left + 1, top + BAR - RADIUS, right - 1, top + BAR), fill=CHROME)
    pen.line((left, top + BAR, right, top + BAR), fill=BORDER, width=1)
    for index in range(3):
        center = (left + PAD + index * 26, top + BAR // 2)
        pen.ellipse((center[0] - 7, center[1] - 7, center[0] + 7, center[1] + 7), fill=DOT)
    bar_font = _font(REGULAR, META_SIZE)
    pen.text(
        (left + PAD + 92, top + BAR // 2), "Posteingang", font=bar_font, fill=MUTED, anchor="lm"
    )

    x = left + PAD
    y = top + BAR + PAD
    subject_font = _font(BOLD, SUBJECT_SIZE)
    for headline in card.subject:
        _line(pen, x, y, headline, subject_font, INK)
        y += round(SUBJECT_SIZE * 1.3)
    y += 18

    # The sender's row: avatar, name with address, recipients, date, and the DKIM seal.
    _avatar(pen, (x, y, x + AVATAR_SIZE, y + AVATAR_SIZE), card.initial)
    text_x = x + AVATAR_SIZE + 20
    name_font = _font(BOLD, NAME_SIZE)
    meta_font = _font(REGULAR, META_SIZE)
    _line(pen, text_x, y, card.sender, name_font, INK)
    _line(pen, text_x, y + 34, card.address, meta_font, MUTED)
    _line(pen, text_x, y + 66, card.recipients, meta_font, MUTED)
    seal_bottom = y
    if card.dkim:
        seal_bottom = _seal(pen, right - PAD, y + 2, card.dkim, card.dkim_color)
    pen.text((right - PAD, seal_bottom + 10), card.date, font=meta_font, fill=MUTED, anchor="ra")
    y = top + _body_top(len(card.subject))
    pen.line((x, y - PAD // 2, right - PAD, y - PAD // 2), fill=BORDER, width=1)

    text_font = _font(REGULAR, TEXT_SIZE)
    step = round(TEXT_SIZE * LINE)
    for line in card.body:
        if line.quoted:
            if line.rule:
                pen.line((x, y + 4, x, y + step - 2), fill=QUOTE_RULE, width=3)
            _line(pen, x + 14, y, line.text, text_font, MUTED)
        else:
            _line(pen, x, y, line.text, text_font, INK)
        y += step

    chip_font = _font(REGULAR, META_SIZE)
    chips_y = min(y + GAP, bottom - FOOT - CHIP_HEIGHT - GAP)
    chip_x = x
    for name in card.attachments:
        width = round(chip_font.getlength(name)) + 28
        pen.rounded_rectangle(
            (chip_x, chips_y, chip_x + width, chips_y + CHIP_HEIGHT),
            radius=CHIP_HEIGHT // 2,
            fill=CHROME,
            outline=BORDER,
        )
        _line(pen, chip_x + 14, chips_y + 9, name, chip_font, MUTED)
        chip_x += width + 10
    if card.more_attachments:
        pen.text(
            (chip_x, chips_y + CHIP_HEIGHT // 2),
            f"+ {card.more_attachments} weitere",
            font=chip_font,
            fill=MUTED,
            anchor="lm",
        )

    # The footer: what was blacked out, and the mail's checksum as the permalink names it.
    pen.rounded_rectangle(
        (left, bottom - FOOT - RADIUS, right, bottom), radius=RADIUS, fill=CHROME, outline=BORDER
    )
    pen.rectangle((left + 1, bottom - FOOT, right - 1, bottom - FOOT + RADIUS), fill=CHROME)
    pen.line((left, bottom - FOOT, right, bottom - FOOT), fill=BORDER, width=1)
    foot_font = _font(REGULAR, META_SIZE)
    middle = bottom - FOOT // 2
    pen.text((x, middle), card.footer, font=foot_font, fill=MUTED, anchor="lm")
    if card.checksum:
        pen.text(
            (right - PAD, middle),
            f"Prüfsumme {card.checksum}",
            font=foot_font,
            fill=MUTED,
            anchor="rm",
        )

    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


# What the card says ---------------------------------------------------------------------------


def _redact(hide: Redactor, text: str) -> tuple[str, Redaction]:
    done = hide.apply(text)
    return done.text, done.redaction


def _sender(
    mail: ExportMail, hide: Redactor, options: CardOptions
) -> tuple[str, str, str | None, Redaction]:
    """The sender's name, its address and the avatar's initial, each blacked out as chosen."""
    people = mail.participants.get(ParticipationRole.FROM, [])
    if not people:
        return "(ohne Absender)", "", None, Redaction()
    person = people[0]
    name, first = _redact(hide, person.name or person.email)
    address, second = _redact(hide, f"<{person.email}>")
    initial = None if options.participants else (person.name or person.email)[:1].upper()
    return name, address, initial, first + second


def _recipients(mail: ExportMail, hide: Redactor) -> tuple[str, Redaction]:
    """The line "an …" with the first RECIPIENTS recipients of To and Cc, the rest counted."""
    people = [
        person
        for role in (ParticipationRole.TO, ParticipationRole.CC, ParticipationRole.BCC)
        for person in mail.participants.get(role, [])
    ]
    if not people:
        return "ohne Empfänger", Redaction()
    shown = [person.name or person.email for person in people[:RECIPIENTS]]
    text, done = _redact(hide, ", ".join(shown))
    rest = len(people) - len(shown)
    return f"an {text}" + (f" + {rest} weitere" if rest else ""), done


def _attachments(mail: ExportMail, hide: Redactor) -> tuple[list[str], int, Redaction]:
    """The first CHIPS attachments as "Name · 1,2 MB", their names blacked out too."""
    names: list[str] = []
    redaction = Redaction()
    for attachment in mail.attachments[:CHIPS]:
        name, done = _redact(hide, attachment.filename or "(ohne Namen)")
        redaction += done
        names.append(f"{name} · {_size(attachment.size)}")
    return names, max(0, len(mail.attachments) - CHIPS), redaction


def _body(
    mail: ExportMail,
    message: bytes,
    hide: Redactor,
    options: CardOptions,
    width: int,
    font: ImageFont.FreeTypeFont,
) -> tuple[list[Line], Redaction]:
    """The text as lines: the sender's own words, the quoted ones only on request (D151), every
    line blacked out before it is measured."""
    if len(message) > records.PARSE_LIMIT:
        text = mail.index_text or ""
    else:
        text = body.mail_text(message).text
    if not text.strip():
        return [Line("(kein Text)", quoted=True, rule=False)], Redaction()
    done = hide.apply(text[:TEXT_LIMIT])
    lines: list[Line] = []
    for segment in quotes.split_text(done.text):
        quoted = segment.kind != "text"
        if quoted and not options.quotes:
            continue
        piece = done.text[segment.start : segment.end]
        for paragraph in piece.split("\n"):
            wrapped = _wrap(paragraph.strip(), font, width - (14 if quoted else 0))
            lines.extend(Line(line, quoted) for line in wrapped or [""])
    while lines and not lines[0].text:
        lines.pop(0)
    while lines and not lines[-1].text:
        lines.pop()
    if not lines:
        return [Line("(nur zitierter Text)", quoted=True, rule=False)], done.redaction
    return lines, done.redaction


def _wrap(
    text: str, font: ImageFont.FreeTypeFont, width: int, limit: int | None = None
) -> list[str]:
    """text wrapped to width, a word too long for a line broken; at most limit lines, the last
    one ending in an ellipsis when something is left."""
    lines: list[str] = []
    for word in text.split():
        if lines and font.getlength(f"{lines[-1]} {word}") <= width:
            lines[-1] = f"{lines[-1]} {word}"
            continue
        while font.getlength(word) > width and len(word) > 1:
            cut = len(word)
            while cut > 1 and font.getlength(word[:cut]) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        lines.append(word)
    if limit is not None and len(lines) > limit:
        lines = lines[:limit]
        last = lines[-1]
        while last and font.getlength(f"{last}…") > width:
            last = last[:-1]
        lines[-1] = f"{last}…"
    return lines


def _body_top(subject_lines: int) -> int:
    """Where the body starts below the window's top edge, for the plan and the drawing alike."""
    headline = round(subject_lines * SUBJECT_SIZE * 1.3)
    return BAR + PAD + headline + 18 + max(AVATAR_SIZE, 3 * (META_SIZE + 10)) + PAD


def _date(when: datetime | None) -> str:
    if when is None:
        return "ohne Datum"
    return f"{when.day}. {MONTHS[when.month - 1]} {when.year}, {when:%H:%M} UTC"


def _dkim_text(status: DkimStatus | None) -> str:
    return DKIM_TEXTS.get(status, "DKIM nicht geprüft") if status else "DKIM nicht geprüft"


def _size(size: int) -> str:
    """A file size as the UI writes it: 1,2 MB with a comma, bytes below a kilobyte."""
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f}".replace(".", ",") + f" {unit}"
    return f"{size} B"


# Drawing the parts ----------------------------------------------------------------------------


def _line(
    pen: ImageDraw.ImageDraw,
    x: float,
    y: float,
    text: str,
    font: ImageFont.FreeTypeFont,
    color: RGB,
) -> None:
    """One line of text, the bars of a redaction black wherever the line's own colour is."""
    at = x
    for piece in _RUNS.split(text):
        if not piece:
            continue
        pen.text((at, y), piece, font=font, fill=REDACTED if piece[0] == BLOCK else color)
        at += font.getlength(piece)


def _avatar(pen: ImageDraw.ImageDraw, box: tuple[int, int, int, int], initial: str | None) -> None:
    """The round avatar: the sender's initial, or a plain figure when the name is blacked out."""
    pen.ellipse(box, fill=AVATAR)
    left, top, right, bottom = box
    if initial:
        pen.text(
            ((left + right) // 2, (top + bottom) // 2),
            initial,
            font=_font(BOLD, AVATAR_SIZE // 2),
            fill=SURFACE,
            anchor="mm",
        )
        return
    size = right - left
    head = size * 0.26
    center_x = (left + right) / 2
    head_y = top + size * 0.36
    pen.ellipse(
        (center_x - head / 2, head_y - head / 2, center_x + head / 2, head_y + head / 2),
        fill=SURFACE,
    )
    shoulders = size * 0.52
    pen.ellipse(
        (
            center_x - shoulders / 2,
            top + size * 0.58,
            center_x + shoulders / 2,
            bottom + size * 0.3,
        ),
        fill=SURFACE,
    )


def _seal(pen: ImageDraw.ImageDraw, right: int, top: int, text: str, color: RGB) -> int:
    """The DKIM pill at the row's right end; returns its bottom."""
    font = _font(BOLD, META_SIZE - 2)
    width = round(font.getlength(text)) + 34
    height = META_SIZE + 16
    pen.rounded_rectangle((right - width, top, right, top + height), radius=height // 2, fill=color)
    pen.text((right - width // 2, top + height // 2), text, font=font, fill=SURFACE, anchor="mm")
    return top + height

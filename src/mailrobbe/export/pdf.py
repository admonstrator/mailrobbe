"""One mail as PDF (D63): a reading copy for a court file, never a substitute for the EML.

A4 in DejaVu Sans from fonts/ (Latin, Greek and Cyrillic; embedded, so it looks the same on
every machine): the subject as title, the header fields as written in the mail (the date also
in UTC), source and SHA-256, DKIM per signature with its key, the attachments, the text body the
full text index is built from (api.body.mail_text; for a message above records.PARSE_LIMIT the
indexed text itself) and, on request, the research data. Every page has a footer with the mail
id, the start of the SHA-256, the page count and the note that the EML is authoritative.

The output depends on the inputs only: the creation date is a parameter, never the clock, so an
export renders the same PDF again. Characters the font has no glyph for (emoji, CJK) appear as
U+FFFD, with a note at the end. One font file only, without bold: fpdf2 parses and subsets every
font file for every document, about 50 ms per file, more than all the rest of a typical mail.
Lines are wrapped here and printed with cell(), ten times faster than multi_cell().
"""

import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF, XPos, YPos
from fpdf.fonts import TTFFont

from mailrobbe.api import body
from mailrobbe.api.schemas import MailResearch
from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus, ReviewStatus
from mailrobbe.export.records import PARSE_LIMIT, ExportMail, Signature
from mailrobbe.importer.model import BODY_TEXT_LIMIT

FONT_FILE = Path(__file__).parent / "fonts" / "DejaVuSans.ttf"
FONT = "dejavu"
TEXT_LIMIT = 100_000  # characters of the body in the PDF; mail.eml has all of it
REPLACEMENT = "\N{REPLACEMENT CHARACTER}"
MISSING = "\N{EN DASH}"  # for a field the mail does not have
PAGES = "{nb}"  # fpdf2's alias for the page count, on only while the footer is written

INK = (22, 24, 29)
MUTED = (91, 98, 112)
ACCENT = (29, 91, 214)
RULE = (227, 230, 235)
SIZE = 9.0  # pt of field values and the body
LINE = 4.4  # mm per line at SIZE
LABEL = 30.0  # mm, width of the label column

STATUS_TEXTS = {
    DkimStatus.PASS: "gültig",
    DkimStatus.CONSISTENT: "Signatur stimmig (Schlüssel nur rekonstruiert)",
    DkimStatus.FAIL: "ungültig",
    DkimStatus.NO_KEY: "Schlüssel nicht abrufbar",
    DkimStatus.UNSIGNED: "nicht signiert",
    DkimStatus.TEMP_ERROR: "DNS-Fehler",
}
REASON_TEXTS = {
    DkimReason.BODY_HASH_MISMATCH: "Body nach dem Signieren verändert",
    DkimReason.SIGNATURE_MISMATCH: "Signatur passt nicht (Header verändert oder anderer Schlüssel)",
    DkimReason.SIGNATURE_MALFORMED: "Signatur fehlerhaft aufgebaut",
    DkimReason.UNSUPPORTED_ALGORITHM: "Algorithmus nicht unterstützt",
    DkimReason.FROM_NOT_SIGNED: "From-Header nicht signiert",
    DkimReason.KEY_MALFORMED: "Schlüssel im DNS unbrauchbar",
    DkimReason.KEY_TOO_SHORT: "Schlüssel zu kurz (unter 1024 Bit)",
    DkimReason.MESSAGE_MALFORMED: "Kopfzeilen nicht lesbar",
    DkimReason.KEY_NOT_FOUND: "Schlüssel nicht im DNS (Selector gelöscht)",
    DkimReason.KEY_REVOKED: "Schlüssel widerrufen (leeres p=)",
    DkimReason.KEY_MISMATCH: "vorhandene Schlüssel passen nicht",
    DkimReason.DNS_TIMEOUT: "DNS-Zeitüberschreitung",
    DkimReason.DNS_OFFLINE: "Offline-Modus, Schlüssel nicht im Cache",
}
REVIEW_TEXTS = {
    ReviewStatus.SEEN: "Gesichtet",
    ReviewStatus.RELEVANT: "Relevant",
    ReviewStatus.IRRELEVANT: "Nicht relevant",
}
HEADER_FIELDS = (
    ("Von", "from"),
    ("An", "to"),
    ("Cc", "cc"),
    ("Bcc", "bcc"),
    ("Datum", "date"),
    ("Message-ID", "message-id"),
    ("In-Reply-To", "in-reply-to"),
)
_WORDS = re.compile(r"\S*\s*")


def render_pdf(
    mail: ExportMail,
    message: bytes,
    *,
    created_at: datetime,
    export_id: int | None = None,
    research: MailResearch | None = None,
) -> bytes:
    """The PDF of a mail whose message (verified against raw_sha256) is given."""
    pdf = _Document(mail, created_at)
    headers = _header_values(message)
    pdf.title_block(headers.get("subject") or mail.subject or "(ohne Betreff)")
    made = f"Lesefassung erstellt am {_time(created_at)}"
    pdf.note(f"Mail {mail.id} · {made}" + (f" für Export {export_id}" if export_id else ""))

    pdf.heading("Kopfzeilen")
    for label, name in HEADER_FIELDS:
        value = headers.get(name)
        if value is not None or name in ("from", "to", "date", "message-id"):
            pdf.field(label, value or MISSING)
            if name == "date":
                pdf.field("Datum (UTC)", _time(mail.date) if mail.date else MISSING)

    pdf.heading("Quelle")
    pdf.field("MBOX-Datei", mail.source.path)
    pdf.field("Offset", f"{_number(mail.source.byte_offset)} Bytes")
    pdf.field("Länge", f"{_number(mail.source.byte_length)} Bytes")
    pdf.field("SHA-256", mail.raw_sha256)
    pdf.field("Mail-ID", str(mail.id))

    pdf.heading("DKIM")
    pdf.field("Ergebnis", STATUS_TEXTS[mail.dkim_status] if mail.dkim_status else "nicht geprüft")
    for signature in mail.signatures:
        pdf.field(f"Signatur {signature.index + 1}", _signature(signature))

    pdf.heading("Anhänge")
    if not mail.attachments:
        pdf.field("", "keine")
    for number, attachment in enumerate(mail.attachments, 1):
        size = f"{_number(attachment.size)} Bytes"
        sha = f"SHA-256 {attachment.sha256}" if attachment.sha256 else "ohne SHA-256 (zu groß)"
        name = attachment.filename or "(ohne Namen)"
        pdf.field(f"{number}.", f"{name}\n{attachment.mime_type}, {size}, {sha}")

    pdf.heading("Text")
    if len(message) > PARSE_LIMIT:
        pdf.note(
            f"Die Mail ist größer als {PARSE_LIMIT // 1024**2} MiB. Hier steht der Text, den "
            f"Mailrobbe beim Import für die Volltextsuche gespeichert hat (höchstens "
            f"{_number(BODY_TEXT_LIMIT)} Zeichen); vollständig steht er in mail.eml."
        )
        pdf.text_block(mail.index_text or "(kein Text gespeichert)")
    else:
        text = body.mail_text(message)
        if text.source == "text/html":
            pdf.note("Aus dem HTML-Teil in Text umgewandelt.")
        if text.source == "none":
            pdf.note("Die Mail hat keinen Textteil.")
        shown = text.text[:TEXT_LIMIT]
        pdf.text_block(shown)
        if text.truncated or len(text.text) > len(shown):
            pdf.note(
                f"Gekürzt nach {_number(len(shown))} Zeichen; der vollständige Text steht in "
                "mail.eml."
            )

    if research is not None:
        pdf.research(research)
    if pdf.replaced:
        pdf.heading("Hinweis")
        pdf.note(
            f"{_number(pdf.replaced)} Zeichen, für die die Schrift kein Zeichen hat (etwa Emoji "
            f"oder chinesische Schrift), sind als {REPLACEMENT} dargestellt. mail.eml enthält "
            "sie unverändert."
        )
    pdf.alias_nb_pages(PAGES)  # the last footer is written by output()
    return bytes(pdf.output())


def _header_values(message: bytes) -> dict[str, str]:
    """Decoded header fields by lowercase name; repeated fields joined by commas."""
    values: dict[str, list[str]] = {}
    for header in body.mail_headers(message).headers:
        values.setdefault(header.name.lower(), []).append(header.value)
    return {name: ", ".join(found) for name, found in values.items()}


def _signature(signature: Signature) -> str:
    verdict = STATUS_TEXTS[signature.status]
    if signature.reason:
        verdict += f": {REASON_TEXTS[signature.reason]}"
    algorithm = signature.algorithm or "Algorithmus unbekannt"
    if signature.key_bits:
        algorithm += f", {signature.key_bits} Bit"
    lines = [
        verdict,
        f"Domain (d=) {signature.domain or MISSING}, "
        f"Selector (s=) {signature.selector or MISSING}, {algorithm}",
        "Passt zur Absenderdomain: "
        + {True: "ja", False: "nein", None: "unbekannt"}[signature.aligned],
        "Signiert: "
        + (_time(signature.signed_at) if signature.signed_at else "ohne Zeitangabe")
        + f" · Geprüft: {_time(signature.checked_at)}",
        _key(signature),
    ]
    return "\n".join(lines)


def _key(signature: Signature) -> str:
    fetched = f" (abgefragt {_time(signature.key_fetched_at)})" if signature.key_fetched_at else ""
    if signature.key_status is DnsStatus.FOUND:
        return f"Schlüssel im DNS{fetched}: {signature.key_record}"
    if signature.key_status is DnsStatus.NOT_FOUND:
        return f"Schlüssel im DNS nicht gefunden{fetched}"
    if signature.key_status is DnsStatus.TEMP_ERROR:
        return f"DNS-Abfrage des Schlüssels fehlgeschlagen{fetched}"
    return "Keine DNS-Antwort zum Schlüssel gespeichert"


def _time(value: datetime) -> str:
    return f"{value.astimezone(UTC):%d.%m.%Y, %H:%M:%S} UTC"


def _number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


class _Document(FPDF):
    def __init__(self, mail: ExportMail, created_at: datetime) -> None:
        super().__init__(format="A4")
        self.mail_id = mail.id
        self.sha256 = mail.raw_sha256
        self.replaced = 0  # characters shown as REPLACEMENT
        self.add_font(FONT, "", str(FONT_FILE))
        font = self.fonts[FONT]
        assert isinstance(font, TTFFont)
        self.glyphs = frozenset(font.cmap)
        self.widths = font.cw  # advance widths in 1/1000 of the font size, by code point
        self.set_margins(20, 18, 20)
        self.set_auto_page_break(True, margin=22)
        self.set_creation_date(created_at)
        self.set_creator("Mailrobbe")
        self.set_title(mail.subject or f"Mail {mail.id}")  # metadata: needs no glyphs
        self.set_lang("de")
        self.alias_nb_pages("")  # off: a mail may contain "{nb}" itself
        self.add_page()

    def footer(self) -> None:
        alias = self.str_alias_nb_pages
        self.alias_nb_pages(PAGES)
        self.set_y(-16)
        self._style(7.5, MUTED)
        self.cell(
            0,
            3.6,
            f"Mailrobbe · Mail {self.mail_id} · SHA-256 {self.sha256[:16]}… · "
            f"Seite {self.page_no()} von {PAGES}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.cell(
            0,
            3.6,
            "Lesefassung. Maßgeblich ist die Originalmail (mail.eml) mit diesem SHA-256.",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.alias_nb_pages(alias)

    def readable(self, text: str) -> str:
        """text as the font can show it: tabs as spaces, line breaks as \\n, other control and
        format characters dropped, characters without a glyph as REPLACEMENT."""
        text = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
        out = []
        for char in text:
            if char == "\n" or ord(char) in self.glyphs:
                out.append(char)
            elif unicodedata.category(char) in ("Cc", "Cf") or _variation_selector(char):
                continue
            else:
                out.append(REPLACEMENT)
                self.replaced += 1
        return "".join(out)

    def title_block(self, subject: str) -> None:
        self._style(15, INK)
        self._lines(self.wrap(self.readable(subject), self.epw), 6.6)
        self.ln(1)

    def heading(self, title: str) -> None:
        self.ln(3)
        if self.will_page_break(14):
            self.add_page()
        self._style(10, ACCENT)
        self.cell(0, 5.5, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.y, self.w - self.r_margin, self.y)
        self.ln(1.5)

    def note(self, text: str) -> None:
        self._style(8, MUTED)
        self._lines(self.wrap(self.readable(text), self.epw), 3.9)

    def field(self, label: str, value: str) -> None:
        """A label in the left column and its value, wrapped, in the right one."""
        if self.will_page_break(LINE):
            self.add_page()
        self._style(SIZE, MUTED)
        self.cell(LABEL, LINE, label)
        self._style(SIZE, INK)
        self._lines(self.wrap(self.readable(value), self.epw - LABEL), LINE, self.l_margin + LABEL)
        self.ln(0.8)

    def text_block(self, text: str) -> None:
        self._style(SIZE, INK)
        self._lines(self.wrap(self.readable(text), self.epw), LINE)

    def research(self, research: MailResearch) -> None:
        self.heading("Rechercheangaben (intern)")
        mark = research.mark
        review = REVIEW_TEXTS[mark.review] if mark.review else "Ungesichtet"
        self.field("Bewertung", review + _by(mark.review_by, mark.review_at))
        flagged = "ja" if mark.flagged else "nein"
        self.field("Markiert", flagged + _by(mark.flagged_by, mark.flagged_at))
        self.field("Schlagworte", ", ".join(tag.name for tag in research.tags) or "keine")
        self.field("Akten", ", ".join(c.name for c in research.collections) or "keine")
        if not research.notes:
            self.field("Notizen", "keine")
        for number, note in enumerate(research.notes, 1):
            written = f"{note.author or 'ohne Namen'}, {_time(note.created_at)}"
            if note.updated_at != note.created_at:
                written += f", bearbeitet {_time(note.updated_at)}"
            self.field(f"Notiz {number}", f"{written}\n{note.body}")

    def wrap(self, text: str, width: float) -> list[str]:
        """The lines of text within width in the current font: broken after spaces, a word
        longer than a line between characters; leading spaces stay, trailing ones go."""
        lines = []
        for paragraph in text.split("\n"):
            line, used = "", 0.0
            for word in _WORDS.findall(paragraph):
                visible = self._width(word.rstrip())
                if line and used + visible > width:
                    lines.append(line.rstrip())
                    line, used = "", 0.0
                while visible > width:
                    cut = self._fitting(word, width)
                    lines.append(word[:cut])
                    word = word[cut:]
                    visible = self._width(word.rstrip())
                line += word
                used += self._width(word)
            lines.append(line.rstrip())
        return lines

    def _width(self, text: str) -> float:
        """Width of text in the current font, as get_string_width() but without its overhead,
        which made wrapping take longer than everything else."""
        return sum(self.widths[ord(char)] for char in text) * self.font_size / 1000

    def _fitting(self, word: str, width: float) -> int:
        """How many characters of word fit within width; at least one."""
        used = 0.0
        for count, char in enumerate(word):
            used += self._width(char)
            if used > width:
                return max(count, 1)
        return len(word)

    def _lines(self, lines: Iterable[str], height: float, x: float | None = None) -> None:
        for line in lines:
            self.set_x(self.l_margin if x is None else x)
            self.cell(0, height, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def _style(self, size: float, color: tuple[int, int, int]) -> None:
        self.set_font(FONT, "", size)
        self.set_text_color(*color)


def _by(editor: str | None, at: datetime | None) -> str:
    if at is None:
        return ""
    return f" ({editor or 'ohne Namen'}, {_time(at)})"


def _variation_selector(char: str) -> bool:
    return 0xFE00 <= ord(char) <= 0xFE0F or 0xE0100 <= ord(char) <= 0xE01EF

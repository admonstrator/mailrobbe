"""render_pdf without a database: what a reader finds in the PDF, read back with pypdf."""

import hashlib
import io
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP

import pypdf

from mailrobbe.api.schemas import (
    AttachmentInfo,
    CollectionRef,
    MailResearch,
    MailSource,
    Mark,
    NoteInfo,
    TagRef,
)
from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus, ReviewStatus
from mailrobbe.export.pdf import REPLACEMENT, TEXT_LIMIT, render_pdf
from mailrobbe.export.records import NO_MARK, PARSE_LIMIT, ExportMail, Signature

CREATED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
FOX = "\N{FOX FACE}"  # no glyph in DejaVu Sans
SUBJECT = f"Grüße aus Zürich \N{EN DASH} Отчёт {FOX}"
KEY = "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA"


def _message(text: str, subject: str = SUBJECT) -> bytes:
    message = EmailMessage(policy=SMTP)
    message["Subject"] = subject
    message["From"] = "Jürgen Weiß <juergen@firma.example>"
    message["To"] = "Анна Петрова <anna@partner.test>"
    message["Cc"] = "buero@firma.example"
    message["Date"] = "Tue, 03 Mar 2020 10:15:00 +0100"
    message["Message-ID"] = "<abc@firma.example>"
    message["In-Reply-To"] = "<vorher@partner.test>"
    message.set_content(text)
    return message.as_bytes()


def _mail(raw: bytes, *, index_text: str | None = None) -> ExportMail:
    signature = Signature(
        index=0,
        status=DkimStatus.FAIL,
        reason=DkimReason.BODY_HASH_MISMATCH,
        domain="firma.example",
        selector="s2020",
        algorithm="rsa-sha256",
        key_bits=2048,
        aligned=True,
        signed_at=datetime(2020, 3, 3, 9, 15, tzinfo=UTC),
        checked_at=datetime(2025, 5, 6, 7, 8, 9, tzinfo=UTC),
        key_status=DnsStatus.FOUND,
        key_record=KEY,
        key_fetched_at=datetime(2025, 5, 6, 7, 8, 0, tzinfo=UTC),
    )
    attachment = AttachmentInfo(
        id=7, filename="Vertrag März.pdf", mime_type="application/pdf", size=12345, sha256="ab" * 32
    )
    return ExportMail(
        id=42,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        message_id="abc@firma.example",
        in_reply_to="vorher@partner.test",
        subject=SUBJECT,
        date=datetime(2020, 3, 3, 9, 15, tzinfo=UTC),
        source=MailSource(
            mbox_file_id=1, path="2020/archiv.mbox", byte_offset=123456, byte_length=len(raw)
        ),
        dkim_status=DkimStatus.FAIL,
        index_text=index_text,
        signatures=[signature],
        attachments=[attachment],
    )


def _pages(pdf: bytes) -> list[str]:
    """The text of each page, a line break where the PDF wraps read as a space."""
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return [" ".join(page.extract_text().split()) for page in reader.pages]


def test_the_pdf_shows_the_mail() -> None:
    raw = _message("Hallo Anna,\n\nStraße und Maß. Привет мир. " + FOX + " Ein {nb} bleibt.\n")
    mail = _mail(raw)
    pdf = render_pdf(mail, raw, created_at=CREATED, export_id=9)
    [text] = _pages(pdf)
    for expected in (
        SUBJECT.replace(FOX, REPLACEMENT),  # the title
        "Mail 42 · Lesefassung erstellt am 02.01.2026, 03:04:05 UTC für Export 9",
        "Von Jürgen Weiß <juergen@firma.example>",
        "An Анна Петрова <anna@partner.test>",
        "Cc buero@firma.example",
        "Datum Tue, 03 Mar 2020 10:15:00 +0100",
        "Datum (UTC) 03.03.2020, 09:15:00 UTC",
        "Message-ID <abc@firma.example>",
        "In-Reply-To <vorher@partner.test>",
        "MBOX-Datei 2020/archiv.mbox",
        "Offset 123.456 Bytes",
        f"SHA-256 {mail.raw_sha256}",
        "Ergebnis ungültig",
        "ungültig: Body nach dem Signieren verändert",
        "Domain (d=) firma.example, Selector (s=) s2020, rsa-sha256, 2048 Bit",
        f"Schlüssel im DNS (abgefragt 06.05.2025, 07:08:00 UTC): {KEY}",
        "Vertrag März.pdf",
        f"application/pdf, 12.345 Bytes, SHA-256 {'ab' * 32}",
        f"Straße und Maß. Привет мир. {REPLACEMENT} Ein {{nb}} bleibt.",
        "2 Zeichen, für die die Schrift kein Zeichen hat",
        f"Mailrobbe · Mail 42 · SHA-256 {mail.raw_sha256[:16]}… · Seite 1 von 1",
        "Lesefassung. Maßgeblich ist die Originalmail (mail.eml) mit diesem SHA-256.",
    ):
        assert expected in text, expected
    assert FOX not in text
    assert "Rechercheangaben" not in text
    metadata = pypdf.PdfReader(io.BytesIO(pdf)).metadata
    assert metadata is not None
    assert (metadata.title, metadata.creator) == (SUBJECT, "Mailrobbe")


def test_the_same_mail_gives_the_same_bytes() -> None:
    raw = _message("Text")
    first = render_pdf(_mail(raw), raw, created_at=CREATED)
    assert render_pdf(_mail(raw), raw, created_at=CREATED) == first
    assert render_pdf(_mail(raw), raw, created_at=datetime(2026, 1, 3, tzinfo=UTC)) != first


def test_research_appears_only_when_given() -> None:
    raw = _message("Text")
    noted = datetime(2025, 7, 1, 12, 0, tzinfo=UTC)
    research = MailResearch(
        mark=Mark(
            flagged=True,
            flagged_by="Lena Vogt",
            flagged_at=noted,
            review=ReviewStatus.RELEVANT,
            review_by="Lena Vogt",
            review_at=noted,
        ),
        tags=[TagRef(id=1, name="Kartell", color="red")],
        collections=[CollectionRef(id=2, name="Akte Hafen")],
        notes=[
            NoteInfo(
                id=3, body="Quelle B bestätigt.", author=None, created_at=noted, updated_at=noted
            )
        ],
    )
    [text] = _pages(render_pdf(_mail(raw), raw, created_at=CREATED, research=research))
    for expected in (
        "Rechercheangaben (intern)",
        "Bewertung Relevant (Lena Vogt, 01.07.2025, 12:00:00 UTC)",
        "Markiert ja (Lena Vogt, 01.07.2025, 12:00:00 UTC)",
        "Schlagworte Kartell",
        "Akten Akte Hafen",
        "Notiz 1 ohne Namen, 01.07.2025, 12:00:00 UTC",
        "Quelle B bestätigt.",
    ):
        assert expected in text, expected
    empty = MailResearch(mark=NO_MARK, tags=[], collections=[], notes=[])
    [text] = _pages(render_pdf(_mail(raw), raw, created_at=CREATED, research=empty))
    assert "Bewertung Ungesichtet" in text
    assert "Notizen keine" in text


def test_a_long_text_is_cut_and_wrapped_over_pages() -> None:
    word = "Durchsuchungsbeschluss" * 8  # longer than a line: broken between characters
    raw = _message(f"{word}\n" + "Zeile mit Text. " * (TEXT_LIMIT // 10))
    pages = _pages(render_pdf(_mail(raw), raw, created_at=CREATED))
    assert len(pages) > 2
    assert all(f"Seite {n} von {len(pages)}" in page for n, page in enumerate(pages, 1))
    text = "".join(pages)
    assert "Durchsuchungsbeschluss" * 3 in text.replace(" ", "")
    assert "Gekürzt nach 100.000 Zeichen; der vollständige Text steht in mail.eml." in text


def test_a_message_above_the_parse_limit_shows_the_indexed_text() -> None:
    raw = _message("Anhang folgt\n" + "x" * 76 + "\n") + b"y" * PARSE_LIMIT
    mail = _mail(raw, index_text="Der indexierte Text über den Hafen")
    [text] = _pages(render_pdf(mail, raw, created_at=CREATED))
    assert "Die Mail ist größer als 8 MiB." in text
    assert "Der indexierte Text über den Hafen" in text
    assert "Anhang folgt" not in text
    assert "Von Jürgen Weiß <juergen@firma.example>" in text

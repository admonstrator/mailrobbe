"""One mail for the social media image, built without a database (as tests/export/test_pdf)."""

import hashlib
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP

import pytest

from mailrobbe.api.schemas import AttachmentInfo, MailSource, PersonLabel, PersonRef
from mailrobbe.enums import DkimStatus, ParticipationRole
from mailrobbe.export.records import ExportMail

SUBJECT = "Spende für den Kreisverband Musterstadt"
SENDER = "anna.petrova@partner.test"
SENDER_NAME = "Anna Petrova"
RECIPIENT = "juergen.weiss@firma.example"
RECIPIENT_NAME = "Jürgen Weiß"
LABEL_NAME = "Jürgen Weiß (Schatzmeister)"
IBAN = "DE02120300000000202051"
TEXT = f"""Hallo Jürgen,

wie besprochen überweisen wir die Spende auf {IBAN}.
Tel. 030 1234567, sonst {RECIPIENT}.

Grüße nach Berlin
{SENDER_NAME}

Am 1.3.2020 schrieb {RECIPIENT_NAME} <{RECIPIENT}>:
> Bitte halte das vertraulich.
"""


def message(text: str = TEXT, subject: str = SUBJECT) -> bytes:
    mail = EmailMessage(policy=SMTP)
    mail["Subject"] = subject
    mail["From"] = f"{SENDER_NAME} <{SENDER}>"
    mail["To"] = f"{RECIPIENT_NAME} <{RECIPIENT}>, buero@firma.example"
    mail["Date"] = "Tue, 03 Mar 2020 10:15:00 +0100"
    mail.set_content(text)
    return mail.as_bytes()


def export_mail(raw: bytes, subject: str = SUBJECT) -> ExportMail:
    return ExportMail(
        id=42,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        message_id="abc@partner.test",
        in_reply_to=None,
        subject=subject,
        date=datetime(2020, 3, 3, 9, 15, tzinfo=UTC),
        source=MailSource(
            mbox_file_id=1, path="2020/archiv.mbox", byte_offset=0, byte_length=len(raw)
        ),
        dkim_status=DkimStatus.PASS,
        participants={
            ParticipationRole.FROM: [PersonRef(person_id=1, email=SENDER, name=SENDER_NAME)],
            ParticipationRole.TO: [
                PersonRef(person_id=2, email=RECIPIENT, name=RECIPIENT_NAME),
                PersonRef(person_id=3, email="buero@firma.example", name=None),
            ],
        },
        labels={
            2: PersonLabel(
                name=LABEL_NAME,
                role="Schatzmeister",
                email=RECIPIENT,
                note=None,
                editor="Lena Vogt",
                updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        },
        attachments=[
            AttachmentInfo(
                id=7,
                filename="Spendenquittung Petrova.pdf",
                mime_type="application/pdf",
                size=1_234_567,
                sha256="ab" * 32,
            )
        ],
    )


@pytest.fixture
def raw() -> bytes:
    return message()


@pytest.fixture
def mail(raw: bytes) -> ExportMail:
    return export_mail(raw)

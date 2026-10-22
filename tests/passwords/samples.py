"""Protected and packed attachments for the tests of milestone 19, built here (no fixtures on
disk): protected PDF, OOXML and ODF files, ZIP and 7z archives (through the 7-Zip command where
they need it), attached mails, and ARCHIVE, a few mails carrying them, which the tests of the
archives step, the passwords step and the API import into a database of their own.

ARCHIVE, by mail index (mail n is dated FIRST_DAY plus n days):

    0  Anna to Bert       Liste.pdf, protected (LISTE_PASSWORD)
    1  Bert to Anna       a reply to 0 holding LISTE_PASSWORD: tier thread
    2  Anna to Carl       Vertrag.docx, protected, with VERTRAG_PASSWORD in the same mail: tier mail
    3  Anna to Dora       Geheim.pdf, protected by a password written nowhere; Notiz.odt, encrypted
    4  Carl to Bert       Akten.zip: Bericht.txt, Ordner/Notiz.txt and inner.zip (a container in a
                          container, listed, not unpacked)
    5  Dora to Anna       Weitergeleitet.eml, an attached mail carrying Anlage.txt
    6  Anna to Bert       Paket.zip, an AES ZIP holding Plan.txt
    7  Bert to Anna       PAKET_PASSWORD after a "PIN:", no reply: tier contacts

The passwords found are LISTE_PASSWORD, VERTRAG_PASSWORD and PAKET_PASSWORD, nothing else.
"""

import asyncio
import io
import random
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from datetime import timedelta
from email import encoders
from email.message import Message
from email.mime.base import MIMEBase
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import msoffcrypto.format.ooxml
import pytest
from sqlalchemy import Row, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.config import Settings
from mailrobbe.importer.cli import run_import
from tests.attachments.doubles import FIRST_DAY
from tests.attachments.extract.samples import odf, pdf
from tests.importer.doubles import write_mbox
from tests.preview.samples import DOCX_MIME, ODT_MIME, docx, para, run

SEVEN_ZIP = shutil.which("7z")
needs_seven_zip = pytest.mark.skipif(SEVEN_ZIP is None, reason="needs the 7-Zip command")

ANNA = "Anna Adler <anna@a.example>"
BERT = "Bert Berg <bert@b.example>"
CARL = "Carl Clausen <carl@c.example>"
DORA = "Dora Dahl <dora@d.example>"
PDF_MIME = "application/pdf"
ZIP_MIME = "application/zip"

# A file attached to a mail: its name, MIME type and content, or an attached mail.
Attached = tuple[str, str, bytes] | Message


# Protected files ------------------------------------------------------------------------------


def protected_pdf(*pages: str, password: str) -> bytes:
    """A PDF of one line per page, encrypted with this user password."""
    return pdf([[line] for line in pages], password=password)


_CONTENT_TYPES = (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/></Types>'
)


def plain_docx(text: str) -> bytes:
    """A DOCX of one paragraph that msoffcrypto takes for OOXML (namespaced content types),
    above 4 KB: msoffcrypto does not decrypt again what it encrypted from a smaller package."""
    padding = random.Random(text).randbytes(6000)
    return docx(
        para(run(text)),
        parts={"[Content_Types].xml": _CONTENT_TYPES, "word/media/pad.bin": padding},
    )


def protected_docx(text: str, password: str) -> bytes:
    """plain_docx encrypted as Office does it (an OLE file holding the EncryptedPackage)."""
    out = io.BytesIO()
    msoffcrypto.format.ooxml.OOXMLFile(io.BytesIO(plain_docx(text))).encrypt(password, out)
    return out.getvalue()


def encrypted_odt() -> bytes:
    """An ODT whose content the manifest declares encrypted."""
    manifest = (
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        '<manifest:file-entry manifest:full-path="content.xml"><manifest:encryption-data/>'
        "</manifest:file-entry></manifest:manifest>"
    )
    return odf(ODT_MIME, "", manifest)


# Archives -------------------------------------------------------------------------------------


def packed(entries: Mapping[str, bytes]) -> bytes:
    """A plain ZIP of these entries, in this order (zipfile, no 7-Zip needed)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def seven_zip(entries: Mapping[str, bytes], name: str, *switches: str) -> bytes:
    """An archive the 7-Zip command makes of these entries, in this order, with its switches
    ("-tzip", "-p<password>", "-mem=AES256", "-mhe=on")."""
    assert SEVEN_ZIP is not None
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        for path, data in entries.items():
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_bytes(data)
        subprocess.run(
            [SEVEN_ZIP, "a", *switches, "--", name, *entries],
            cwd=folder,
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
        return (folder / name).read_bytes()


# Mails ----------------------------------------------------------------------------------------


def mail(
    index: int,
    sender: str,
    to: str,
    subject: str,
    body: str,
    files: Sequence[Attached] = (),
    *,
    reply_to: int | None = None,
) -> Message:
    """A mail with these attachments (base64; an attached mail as message/rfc822), its Message-ID
    <index@a.example>, dated FIRST_DAY plus index days."""
    message = MIMEMultipart()
    message["Message-ID"] = f"<{index}@a.example>"
    if reply_to is not None:
        message["In-Reply-To"] = f"<{reply_to}@a.example>"
        message["References"] = f"<{reply_to}@a.example>"
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = format_datetime(FIRST_DAY + timedelta(days=index))
    message.attach(MIMEText(body, "plain", "utf-8"))
    for item in files:
        if isinstance(item, Message):
            part: Message = MIMEMessage(item)
            part.add_header("Content-Disposition", "attachment", filename="Weitergeleitet.eml")
        else:
            name, mime_type, data = item
            part = MIMEBase(*mime_type.split("/"))
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=name)
        message.attach(part)
    return message


# The archive ----------------------------------------------------------------------------------

LISTE_PASSWORD = "Hafen-2019"
VERTRAG_PASSWORD = "Nordlicht7"
PAKET_PASSWORD = "Wellen#5"
GEHEIM_PASSWORD = "Niemand99"  # written in no mail
PASSWORDS = (LISTE_PASSWORD, VERTRAG_PASSWORD, PAKET_PASSWORD)  # in the order of their ids
LISTE_TEXT = ("Vertrauliche Spendenliste", "Seite zwei")
VERTRAG_TEXT = "Vertrag über die Lieferung"
BERICHT = b"Bericht \xc3\xbcber die Spenden\n"
INNER = {"tief.txt": b"Ganz unten\n"}
AKTEN = {"Bericht.txt": BERICHT, "Ordner/Notiz.txt": b"Notiz zum Treffen\n"}
ANLAGE = b"Anlage zum Vertrag\n"
PLAN = b"Geheimer Plan\n"
MBOX_NAME = "geschuetzt.mbox"


def forwarded() -> Message:
    """The attached mail of mail 5, carrying Anlage.txt."""
    return mail(
        100, CARL, DORA, "Lieferung", "Siehe Anlage.", [("Anlage.txt", "text/plain", ANLAGE)]
    )


def archive_mails() -> list[Message]:
    """The mails of ARCHIVE (module docstring); Paket.zip needs the 7-Zip command."""
    paket = seven_zip(
        {"Plan.txt": PLAN}, "Paket.zip", "-tzip", f"-p{PAKET_PASSWORD}", "-mem=AES256"
    )
    akten = packed({**AKTEN, "inner.zip": packed(INNER)})
    return [
        mail(
            0,
            ANNA,
            BERT,
            "Spendenliste",
            "Anbei die Liste.\n",
            [("Liste.pdf", PDF_MIME, protected_pdf(*LISTE_TEXT, password=LISTE_PASSWORD))],
        ),
        mail(
            1,
            BERT,
            ANNA,
            "Re: Spendenliste",
            f"Das Kennwort lautet: {LISTE_PASSWORD}\n",
            reply_to=0,
        ),
        mail(
            2,
            ANNA,
            CARL,
            "Vertrag",
            f"Hier der Vertrag.\nPasswort: {VERTRAG_PASSWORD}\n",
            [("Vertrag.docx", DOCX_MIME, protected_docx(VERTRAG_TEXT, VERTRAG_PASSWORD))],
        ),
        mail(
            3,
            ANNA,
            DORA,
            "Vorstand",
            "Bitte vertraulich behandeln.\n",
            [
                (
                    "Geheim.pdf",
                    PDF_MIME,
                    protected_pdf("Nur für den Vorstand", password=GEHEIM_PASSWORD),
                ),
                ("Notiz.odt", ODT_MIME, encrypted_odt()),
            ],
        ),
        mail(4, CARL, BERT, "Akten", "Die Akten im Anhang.\n", [("Akten.zip", ZIP_MIME, akten)]),
        mail(5, DORA, ANNA, "WG: Lieferung", "Zur Kenntnis.\n", [forwarded()]),
        mail(6, ANNA, BERT, "Paket", "Das Paket.\n", [("Paket.zip", ZIP_MIME, paket)]),
        mail(7, BERT, ANNA, "Zugang", f"PIN: {PAKET_PASSWORD}\n"),
    ]


def write_archive(mbox_dir: Path) -> Path:
    """ARCHIVE as an MBOX file in mbox_dir (made if needed); the directory."""
    mbox_dir.mkdir(parents=True, exist_ok=True)
    write_mbox(mbox_dir / MBOX_NAME, [message.as_bytes() for message in archive_mails()])
    return mbox_dir


def import_archive(url: str, mbox_dir: Path, *, runs: int = 1, **settings: Any) -> None:
    """`mailrobbe import` of mbox_dir into the database at url, `runs` times."""
    for _ in range(runs):
        code = asyncio.run(run_import(Settings(database_url=url, **settings), mbox_dir, 2))
        assert code == 0


async def fetch(url: str, sql: str, **params: Any) -> list[Row[Any]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            return list(await connection.execute(text(sql), params))
    finally:
        await engine.dispose()


async def execute(url: str, *statements: str, **params: Any) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement), params)
    finally:
        await engine.dispose()

"""attachments.protected (D233 to D237, D209): which documents a password can be tried on, the
tries in order and up to a deadline, the decrypted bytes, and the child process both run in,
which answers even over its time or memory limit."""

import io
import sys
import time
import zipfile

import pytest
from pypdf import PdfReader

from mailrobbe.attachments import protected
from mailrobbe.attachments.extract import Extraction, ExtractionLimits, extract_document
from mailrobbe.attachments.extract.base import Damaged, Encrypted
from mailrobbe.attachments.protected import (
    DecryptFailed,
    Tried,
    decrypt,
    decrypted,
    opens,
    trial_format,
    try_passwords,
    try_values,
)
from mailrobbe.enums import DocumentKind, DocumentTextStatus
from tests.attachments.extract.samples import pdf
from tests.passwords.samples import (
    PDF_MIME,
    ZIP_MIME,
    encrypted_odt,
    needs_seven_zip,
    packed,
    plain_docx,
    protected_docx,
    protected_pdf,
    seven_zip,
)
from tests.preview.samples import DOCX_MIME, ODT_MIME

PASSWORD = "Hafen-2019"
PDF = protected_pdf("Vertrauliche Liste", "Seite zwei", password=PASSWORD)
DOCX = protected_docx("Vertrag über die Lieferung", PASSWORD)
LIMITS = ExtractionLimits(timeout=30)
MEMORY = 1024**3
TEXT = DocumentTextStatus.TEXT
linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs Linux")


def pdf_text(data: bytes) -> str:
    return extract_document(data, "x.pdf", PDF_MIME, LIMITS).text


# Which attempt opens a document -----------------------------------------------------------------


def test_trial_format_per_format() -> None:
    assert trial_format("Liste.pdf", PDF_MIME, PDF) == "pdf"
    assert trial_format(None, "application/octet-stream", PDF) == "pdf"  # by its first bytes
    for name in ("Vertrag.docx", "Zahlen.xlsx", "Folien.pptx"):
        assert trial_format(name, "application/octet-stream", DOCX) == "ooxml"
    assert trial_format("Akten.zip", ZIP_MIME, packed({"a.txt": b"a"})) == "archive"
    assert trial_format("Akten.7z", "application/x-7z-compressed", b"7z\xbc\xaf\x27\x1c") == (
        "archive"
    )
    # detected as encrypted, not opened yet (D239); an attached mail needs no password
    assert trial_format("Notiz.odt", ODT_MIME, encrypted_odt()) is None
    assert trial_format("Weitergeleitet.eml", "message/rfc822", b"From: a@a.example\n") is None
    assert trial_format("Notiz.txt", "text/plain", b"Kennwort: x") is None


def test_opens_a_pdf_and_an_ooxml_file_with_their_password_only() -> None:
    assert opens(PDF, "Liste.pdf", PDF_MIME, PASSWORD)
    assert not opens(PDF, "Liste.pdf", PDF_MIME, "Falsch")
    assert opens(DOCX, "Vertrag.docx", DOCX_MIME, PASSWORD)
    assert not opens(DOCX, "Vertrag.docx", DOCX_MIME, "Falsch")
    # what needs no password, what no password opens, and what is broken: never an exception
    assert not opens(plain_docx("offen"), "offen.docx", DOCX_MIME, PASSWORD)
    assert not opens(encrypted_odt(), "Notiz.odt", ODT_MIME, PASSWORD)
    assert not opens(PDF[: len(PDF) // 3], "kaputt.pdf", PDF_MIME, PASSWORD)
    assert not opens(b"PK\x03\x04 kaputt", "kaputt.zip", ZIP_MIME, PASSWORD)
    assert not opens(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1kaputt", "kaputt.docx", DOCX_MIME, PASSWORD)


@needs_seven_zip
def test_opens_a_protected_zip_and_7z() -> None:
    entries = {"Plan.txt": b"Geheimer Plan\n"}
    for data, name in (
        (seven_zip(entries, "x.zip", "-tzip", f"-p{PASSWORD}", "-mem=AES256"), "x.zip"),
        (seven_zip(entries, "x.7z", "-t7z", f"-p{PASSWORD}", "-mhe=on"), "x.7z"),
    ):
        assert opens(data, name, ZIP_MIME, PASSWORD)
        assert not opens(data, name, ZIP_MIME, "Falsch")
        assert decrypted(data, name, ZIP_MIME, PASSWORD) == data  # its entries are read with it


def test_try_values_in_order_and_counted() -> None:
    assert try_values(PDF, "a.pdf", PDF_MIME, ["a", "b", PASSWORD, "c"]) == (2, 3)
    assert try_values(PDF, "a.pdf", PDF_MIME, ["a", "b"]) == (None, 2)
    assert try_values(PDF, "a.pdf", PDF_MIME, []) == (None, 0)
    assert try_values(PDF, "a.pdf", PDF_MIME, ["a", PASSWORD], deadline=time.monotonic() - 1) == (
        None,
        0,
    )


def test_try_values_stops_at_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    deadline = time.monotonic() + 0.2
    tried: list[str] = []

    def slow(data: bytes, filename: str | None, mime_type: str, password: str) -> bool:
        tried.append(password)
        while len(tried) == 2 and time.monotonic() <= deadline:  # the second one takes long
            time.sleep(0.01)
        return False

    monkeypatch.setattr(protected, "opens", slow)
    assert try_values(PDF, "a.pdf", PDF_MIME, ["a", "b", "c", PASSWORD], deadline=deadline) == (
        None,
        2,
    )
    assert tried == ["a", "b"]


def test_decrypted_pdf_and_ooxml() -> None:
    plain = decrypted(PDF, "Liste.pdf", PDF_MIME, PASSWORD)
    assert not PdfReader(io.BytesIO(plain)).is_encrypted
    assert pdf_text(plain) == "Vertrauliche Liste\n\nSeite zwei"
    package = decrypted(DOCX, "Vertrag.docx", DOCX_MIME, PASSWORD)
    assert "word/document.xml" in zipfile.ZipFile(io.BytesIO(package)).namelist()
    found = extract_document(package, "Vertrag.docx", DOCX_MIME, LIMITS)
    assert (found.status, found.text) == (TEXT, "Vertrag über die Lieferung")
    for data, name in ((PDF, "Liste.pdf"), (DOCX, "Vertrag.docx")):
        with pytest.raises(Encrypted):
            decrypted(data, name, "application/octet-stream", "Falsch")
    with pytest.raises(Damaged):
        decrypted(b"%PDF-1.4\nkaputt", "kaputt.pdf", PDF_MIME, PASSWORD)
    # what is not encrypted comes back as it is
    open_pdf = pdf([["Offen"]])
    assert decrypted(open_pdf, "offen.pdf", PDF_MIME, PASSWORD) == open_pdf
    open_docx = plain_docx("Offen")
    assert decrypted(open_docx, "offen.docx", DOCX_MIME, PASSWORD) == open_docx
    assert decrypted(b"Notiz", "Notiz.txt", "text/plain", PASSWORD) == b"Notiz"


# The child process ------------------------------------------------------------------------------


async def test_try_passwords_opens_and_extracts_the_text_in_a_child() -> None:
    tried = await try_passwords(
        PDF, "Liste.pdf", PDF_MIME, ["Falsch", PASSWORD, "später"], seconds=10, limits=LIMITS
    )
    assert tried == Tried(
        1, 2, Extraction(TEXT, "Vertrauliche Liste\n\nSeite zwei", pages=2, kind=DocumentKind.PDF)
    )
    tried = await try_passwords(
        DOCX, "Vertrag.docx", DOCX_MIME, [PASSWORD], seconds=10, limits=LIMITS
    )
    assert tried == Tried(
        0, 1, Extraction(TEXT, "Vertrag über die Lieferung", kind=DocumentKind.DOCUMENT)
    )
    none = await try_passwords(PDF, "Liste.pdf", PDF_MIME, ["a", "b"], seconds=10, limits=LIMITS)
    assert none == Tried(None, 2)


@needs_seven_zip
async def test_try_passwords_opens_an_archive_without_extracting_it() -> None:
    data = seven_zip({"Plan.txt": b"Plan\n"}, "x.zip", "-tzip", f"-p{PASSWORD}", "-mem=AES256")
    tried = await try_passwords(data, "x.zip", ZIP_MIME, ["a", PASSWORD], seconds=10, limits=LIMITS)
    assert tried == Tried(1, 2)  # the archives step unpacks it with the password (D236)


async def test_decrypt_in_a_child() -> None:
    plain = await decrypt(PDF, "Liste.pdf", PDF_MIME, PASSWORD, timeout=30, memory=MEMORY)
    assert pdf_text(plain) == "Vertrauliche Liste\n\nSeite zwei"
    package = await decrypt(DOCX, "Vertrag.docx", DOCX_MIME, PASSWORD, timeout=30, memory=MEMORY)
    assert package.startswith(b"PK\x03\x04")
    with pytest.raises(DecryptFailed, match=r"^the password does not open the document$"):
        await decrypt(PDF, "Liste.pdf", PDF_MIME, "Falsch", timeout=30, memory=MEMORY)
    with pytest.raises(DecryptFailed, match=r"^damaged document: "):
        await decrypt(
            b"%PDF-1.4\nkaputt", "kaputt.pdf", PDF_MIME, PASSWORD, timeout=30, memory=MEMORY
        )


async def test_a_child_over_its_time_limit_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A child that does not answer in time is killed; the parent answers for it."""
    monkeypatch.setattr(protected, "_GRACE", 0.0)
    started = time.monotonic()
    tried = await try_passwords(
        PDF,
        "Liste.pdf",
        PDF_MIME,
        ["a", PASSWORD],
        seconds=0,
        limits=ExtractionLimits(timeout=0.01),
    )
    assert tried == Tried(None, 2, error="stopped after the time limit of 0.01 s")
    with pytest.raises(DecryptFailed, match=r"^stopped after the time limit of 0.01 s$"):
        await decrypt(PDF, "Liste.pdf", PDF_MIME, PASSWORD, timeout=0.01, memory=MEMORY)
    assert time.monotonic() - started < 5


@linux
async def test_a_child_over_its_memory_limit_answers() -> None:
    large = PDF + b"\n%" + b"x" * 8 * 1024**2  # read whole before anything is tried
    limits = ExtractionLimits(timeout=30, memory=1024**2)
    tried = await try_passwords(
        large, "a.pdf", PDF_MIME, ["a", PASSWORD], seconds=10, limits=limits
    )
    assert tried == Tried(None, 2, error="memory limit of 1 MiB exceeded")
    with pytest.raises(DecryptFailed, match=r"^memory limit of 1 MiB exceeded$"):
        await decrypt(large, "a.pdf", PDF_MIME, PASSWORD, timeout=30, memory=1024**2)

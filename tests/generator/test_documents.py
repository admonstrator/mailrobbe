"""generator.documents and fileformats: real documents, their ground truth and circulation."""

import base64
import random
import re
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mailrobbe.attachments.extract import ExtractionLimits, extract_document
from mailrobbe.generator import documents
from mailrobbe.generator import fileformats as ff
from mailrobbe.generator.faults import inject_fault
from mailrobbe.generator.model import (
    Address,
    AttachmentSpec,
    DocumentSpec,
    Fault,
    MailKind,
    PlannedMail,
)
from mailrobbe.generator.render import render

WHEN = datetime(2021, 5, 4, 10, 0, tzinfo=UTC)
NAMES = {
    "pdf": "a.pdf", "pdf_scan": "Scan.pdf", "pdf_encrypted": "a.pdf", "pdf_damaged": "a.pdf",
    "docx": "a.docx", "odt": "a.odt", "xlsx": "a.xlsx", "pptx": "a.pptx", "csv": "a.csv",
    "txt": "a.txt", "txt_empty": "a.txt", "ics": "a.ics", "vcf": "a.vcf", "zip": "a.zip",
}  # fmt: skip
EXTRA_FORMS = (("pdf_encrypted", "invoice"), ("pdf_damaged", "offer"), ("txt_empty", "notes"))


def _forms() -> list[tuple[str, str]]:
    found = {(form, theme) for form, themes in documents.TEMPLATES.values() for theme in themes}
    return sorted(found | set(EXTRA_FORMS))


def _spec(form: str, theme: str, size: int, seed: int = 7) -> AttachmentSpec:
    document = DocumentSpec(seed, form, theme, WHEN)
    return AttachmentSpec(NAMES[form], "application/octet-stream", size, document=document)


def _bytes(built: documents.Built) -> bytes:
    return base64.decodebytes(b"".join(built.encoded))


@pytest.mark.parametrize(("form", "theme"), _forms())
def test_each_form_extracts_as_its_truth(form: str, theme: str) -> None:
    for number, size in enumerate((2_000, 60_000, 700_000)):
        spec = _spec(form, theme, size, seed=number)
        built = documents.build(spec)
        data = _bytes(built)
        truth = built.truth(spec.filename)
        assert (len(data), truth.size, truth.filename) == (built.size, built.size, spec.filename)
        result = extract_document(data, spec.filename, spec.mime_type, ExtractionLimits())
        assert (result.status.value, result.kind) == (truth.status, truth.kind), size
        if truth.marker is not None:
            assert re.fullmatch(r"Dokmarke[a-z2-9]{8}", truth.marker)
            assert truth.marker in result.text
        else:
            assert truth.status != "text"
        if truth.pages is not None:
            assert result.pages == truth.pages


def test_documents_are_pure_functions_of_spec_and_size() -> None:
    for form, theme in _forms():
        spec = DocumentSpec(11, form, theme, WHEN)
        first, pages = documents.document_bytes(spec, 50_000)
        assert documents.document_bytes(spec, 50_000) == (first, pages)
        assert documents.document_bytes(replace(spec, seed=12), 50_000)[0] != first


def test_padded_documents_come_close_to_the_planned_size() -> None:
    padded = ("pdf", "pdf_scan", "pdf_encrypted", "docx", "odt", "xlsx", "pptx", "zip")
    for form, theme in _forms():
        if form not in padded:
            continue
        for size in (80_000, 1_500_000):
            built = documents.build(_spec(form, theme, size))
            assert abs(built.size - size) < max(size // 50, 4_000), (form, theme, size)


def test_text_documents_are_as_long_as_their_content() -> None:
    for form in ("csv", "txt", "ics", "vcf"):
        theme = "export" if form == "csv" else "notes"
        built = documents.build(_spec(form, theme, 5_000_000))
        assert built.size <= 200_000


def test_ibans_have_valid_check_digits_and_no_real_bank_code() -> None:
    rng = random.Random(3)
    for _ in range(2000):
        iban = documents.iban(rng)
        assert re.fullmatch(r"DE\d{20}", iban)
        assert iban[4] == "9"  # no clearing area has 9: an invented bank code
        assert int(iban[4:] + "1314" + iban[2:4]) % 97 == 1  # ISO 13616 check
    assert int("370400440532013000" + "131489") % 97 == 1  # the well-known example passes


def test_markers_are_unique_words() -> None:
    markers = {documents.marker(seed) for seed in range(20_000)}
    assert len(markers) == 20_000
    assert all(re.fullmatch(r"Dokmarke[a-z2-9]{8}", m) for m in markers)


def test_encode_base64_is_encodebytes_in_pieces() -> None:
    rng = random.Random(5)
    for size in (0, 1, 56, 57, 58, 3_000, 58_368, 58_369, 400_000):
        for prefix in (b"", b"x", b"y" * 56, b"z" * 57):
            data = prefix + ff.filler(rng, size, b"%PDF") + b"tail" + ff.filler(rng, size)
            pieces = ff.encode_base64(data)
            assert b"".join(pieces) == base64.encodebytes(data), (size, len(prefix))
    big = documents.build(_spec("pptx", "presentation", 3_000_000))
    assert len(set(map(id, big.encoded))) < len(big.encoded)  # the noise is encoded once


def test_the_pool_reuses_renames_and_keeps_invoices_out() -> None:
    pool = documents.DocumentPool(42)
    made: list[AttachmentSpec] = []
    for n in range(3000):
        name, pattern = ("Angebot_Atlas.pdf", "Angebot_{project}.pdf")
        if n % 3 == 1:
            name, pattern = ("Protokoll_Sitzung.docx", "Protokoll_Sitzung.docx")
        spec = AttachmentSpec(name, "application/pdf", 30_000)
        made.append(pool.attach(spec, pattern, WHEN))
    invoice = AttachmentSpec("Rechnung_2021-05.pdf", "application/pdf", 30_000)
    invoices = [
        pool.attach(invoice, "Rechnung_{year}-{month2}.pdf", WHEN, circulate=False)
        for _ in range(50)
    ]
    uses = Counter(spec.document for spec in made)
    assert 3.5 < len(made) / len(uses) < 8  # about four in five are a recent document again
    assert any(spec.filename.endswith(("_Kopie.pdf", "_final.pdf", "_neu.pdf")) for spec in made)
    assert len({spec.document for spec in invoices}) == 50
    later = [pool.attach(AttachmentSpec("x.pdf", "application/pdf", 1), "Angebot_{project}.pdf",
                         WHEN) for _ in range(200)]  # fmt: skip
    assert not {spec.document for spec in later} & {spec.document for spec in invoices}
    catalog = AttachmentSpec("Katalog_2021.pdf", "application/pdf", 900_000)
    shared = {
        pool.attach(replace(catalog, size=size), "Katalog_{year}.pdf", WHEN, circulate=False,
                    shared="shop@kaufhaus.example:Katalog_2021.pdf")
        for size in (100_000, 2_000_000, 5_000)
    }  # fmt: skip
    assert len(shared) == 1  # one file, whatever size each mail planned
    image = AttachmentSpec("IMG_1.jpg", "image/jpeg", 5_000)
    assert pool.attach(image, "IMG_{n}.jpg", WHEN) is image


def test_documents_circulate_in_the_plan(gen_plan: list[PlannedMail]) -> None:
    uses: Counter[DocumentSpec] = Counter()
    names: dict[DocumentSpec, set[str]] = {}
    by_message = {mail.message_id: mail for mail in gen_plan}
    replies_again = forwarded = 0
    for mail in gen_plan:
        for spec in mail.attachments:
            if spec.document is None:
                continue
            uses[spec.document] += 1
            names.setdefault(spec.document, set()).add(spec.filename)
        parent = by_message.get(mail.in_reply_to or "")
        own = {spec.document for spec in mail.attachments if spec.document}
        if mail.kind is MailKind.REPLY and parent is not None and own:
            replies_again += own <= {spec.document for spec in parent.attachments}
        if mail.kind is MailKind.FORWARD and mail.quoted is not None and own:
            forwarded += own <= {spec.document for spec in mail.quoted.attachments}
        if mail.kind is MailKind.INVOICE:
            assert all(spec.document for spec in mail.attachments)
    occurrences = sum(uses.values())
    assert 2.2 < occurrences / len(uses) < 4.5  # the brief: about three per distinct document
    assert sum(len(found) > 1 for found in names.values()) > 5
    assert replies_again > 0 and forwarded > 0
    with_attachments = sum(bool(mail.attachments) for mail in gen_plan)
    assert 0.12 < with_attachments / len(gen_plan) < 0.2  # the configured share stays 0.15


def test_rendered_truths_follow_mime_order_and_faults() -> None:
    files = (
        AttachmentSpec("image001.png", "image/png", 3_000, inline=True),
        _spec("pdf", "invoice", 40_000),
        AttachmentSpec("IMG_9.jpg", "image/jpeg", 70_000),
        _spec("xlsx", "donations", 20_000),
    )
    mail = PlannedMail(
        index=0, seed=5, date=WHEN, sender=Address("a@x.example"), to=(Address("b@x.example"),),
        subject="Unterlagen", message_id="<1@x.example>", attachments=files, client="outlook",
    )  # fmt: skip
    rendered = render(mail)
    assert [t.filename for t in rendered.documents] == [a.filename for a in files]
    assert [t.kind for t in rendered.documents] == ["image", "pdf", "image", "spreadsheet"]
    assert [t.status for t in rendered.documents] == ["unsupported", "text", "unsupported", "text"]
    line = b"".join(documents.build(files[1]).encoded).split(b"\n")[3]
    broken = rendered.raw.replace(line, b"!#" + line[2:], 1)
    truths = documents.damaged(rendered.documents, broken)
    assert [t.sha256 is None for t in truths] == [False, True, False, False]
    assert (truths[1].status, truths[1].marker) == (None, None)
    assert inject_fault(rendered, Fault.BROKEN_ENCODING, "invalid_base64", random.Random(1))
    assert sum(t.sha256 is None for t in rendered.documents) <= 1  # the first base64 part only

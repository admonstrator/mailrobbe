"""generator.documents: scans, photos of a page and posters with set text for OCR (milestone 15)."""

import base64
import io
import re
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from PIL import Image

from mailrobbe.attachments.extract import ExtractionLimits, extract_document
from mailrobbe.generator import documents
from mailrobbe.generator.model import AttachmentSpec, DocumentSpec, PhotoGps, PlannedMail
from mailrobbe.generator.render import render

WHEN = datetime(2021, 5, 4, 10, 0, tzinfo=UTC)
FILES = {"pdf_scan": ("Scan.pdf", "application/pdf"), "jpeg": ("IMG_7.jpg", "image/jpeg"),
         "png": ("Foto.png", "image/png")}  # fmt: skip


def with_text(form: str, theme: str = "photo", start: int = 0) -> DocumentSpec:
    """The first document of this form from seed `start` on that has set text."""
    for seed in range(start, start + 500):
        spec = DocumentSpec(seed, form, theme, WHEN)
        if documents.set_text(spec) is not None:
            return spec
    raise AssertionError(f"no {form} with set text")


def test_only_a_share_of_scans_and_new_photos_have_set_text() -> None:
    def share(form: str, theme: str = "photo") -> float:
        specs = [DocumentSpec(seed, form, theme, WHEN) for seed in range(2000)]
        return sum(documents.set_text(spec) is not None for spec in specs) / len(specs)

    assert share("pdf_scan", "scan") == pytest.approx(documents.SET_TEXT_SCAN_SHARE, abs=0.05)
    assert share("jpeg") == pytest.approx(documents.SET_TEXT_PICTURE_SHARE, abs=0.03)
    assert share("png") == pytest.approx(documents.SET_TEXT_PICTURE_SHARE, abs=0.03)
    assert share("png", "inline") == share("jpeg_damaged") == share("pdf", "letter") == 0


@pytest.mark.parametrize("form", ["pdf_scan", "jpeg", "png"])
def test_a_set_text_carries_its_marker_on_the_first_page(form: str) -> None:
    spec = with_text(form)
    text = documents.set_text(spec)
    assert text is not None and text == documents.set_text(spec)  # a function of the seed
    assert re.fullmatch(r"Scanmarke[ACDEFHKLMNPRTUVWXY3479]{6}", text.marker)
    assert text.marker in "\n".join(text.pages[0])
    assert 1 <= len(text.pages) <= (2 if form == "pdf_scan" else 1)
    assert 5 <= len(text.words) <= 12
    lines = "\n".join(line for page in text.pages for line in page)
    assert all(word in lines and len(word) >= 6 for word in text.words)
    assert max(len(line) for line in lines.splitlines()) <= 54


@pytest.mark.parametrize("form", ["pdf_scan", "jpeg", "png"])
def test_documents_with_set_text_keep_their_kind_status_and_size(form: str) -> None:
    filename, mime_type = FILES[form]
    spec = AttachmentSpec(filename, mime_type, 260_000, document=with_text(form))
    built = documents.build(spec)
    truth = built.truth(filename, mime_type)
    data = base64.b64decode(b"".join(built.encoded))
    assert truth.ocr_marker == documents.set_text(with_text(form)).marker  # type: ignore[union-attr]
    assert truth.ocr_words and truth.as_json()["ocr_words"] == list(truth.ocr_words)
    assert truth.marker is None  # no text the extraction finds
    assert abs(len(data) - 260_000) < 60_000
    result = extract_document(data, filename, mime_type, ExtractionLimits())
    assert result.kind is not None
    assert (result.status.value, result.kind.value) == (truth.status, truth.kind)
    if form == "pdf_scan":
        assert result.pages == truth.pages and result.text == ""
    else:
        picture = Image.open(io.BytesIO(data))
        assert picture.format == ("JPEG" if form == "jpeg" else "PNG")
        assert truth.preview == "image"


def test_a_photo_with_set_text_keeps_its_exif() -> None:
    gps = PhotoGps(53.55, 9.99, 12.0, datetime(2021, 5, 4, 9, 0), "+02:00", "Fairphone", "4")
    spec = replace(with_text("jpeg"), gps=gps)
    built = documents.build(AttachmentSpec("IMG_1.jpg", "image/jpeg", 200_000, document=spec))
    assert built.ocr_marker is not None
    assert built.position == documents.photo_position(gps)
    data = base64.b64decode(b"".join(built.encoded))
    assert Image.open(io.BytesIO(data)).getexif()


def test_documents_without_set_text_have_no_ocr_truth() -> None:
    spec = DocumentSpec(1, "pdf", "letter", WHEN)
    truth = documents.build(AttachmentSpec("a.pdf", "application/pdf", 30_000, document=spec))
    assert (truth.ocr_marker, truth.ocr_words) == (None, None)


def test_the_plan_carries_documents_with_set_text_into_the_manifest(
    gen_plan: list[PlannedMail],
) -> None:
    carrying = [
        mail
        for mail in gen_plan
        if any(
            spec.document is not None and documents.set_text(spec.document) is not None
            for spec in mail.attachments
        )
    ]
    assert carrying, "the plan of the tests has no document with set text"
    # A few per thousand mails.
    assert len(carrying) < len(gen_plan) * 0.03
    rendered = render(carrying[0])
    found = [truth for truth in rendered.documents if truth.ocr_marker is not None]
    assert found and all(truth.ocr_words for truth in found)
    assert all(truth.as_json()["ocr_marker"] == truth.ocr_marker for truth in found)

import io
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from PIL import Image

from mailrobbe.ai.ocr import tesseract
from mailrobbe.ai.ocr.render import render
from mailrobbe.ai.ocr.tesseract import TesseractMissing, parse_tsv, read_page
from mailrobbe.ai.services import TEST_LINE, TEST_WORD, probe_picture
from mailrobbe.generator import documents
from mailrobbe.generator.model import DocumentSpec


@pytest.fixture(autouse=True)
def fresh_languages() -> Iterator[None]:
    tesseract.installed_languages.cache_clear()
    yield
    tesseract.installed_languages.cache_clear()


def read(png: bytes, uncertain: float = 60.0, languages: str = "deu+eng"):
    return read_page(png, 4, languages=languages, uncertain=uncertain, timeout=60)


def test_a_page_with_known_words_is_read() -> None:
    page = read(probe_picture())
    assert (page.number, page.engine, page.error) == (4, "tesseract", None)
    assert page.text == f"{TEST_WORD}\n\n{TEST_LINE}"
    assert page.confidence is not None and page.confidence > 80
    assert page.uncertain is False and page.seconds > 0


def test_a_page_below_the_threshold_is_uncertain() -> None:
    assert read(probe_picture(), uncertain=99.9).uncertain is True


def test_a_page_without_words_is_empty_and_not_uncertain() -> None:
    out = io.BytesIO()
    Image.new("L", (800, 600), 255).save(out, "PNG")
    page = read(out.getvalue())
    assert (page.text, page.confidence, page.uncertain, page.error) == ("", None, False, None)


def test_a_page_tesseract_fails_on_gets_an_error() -> None:
    page = read(b"\x89PNG\r\n\x1a\nbroken")
    assert page.error is not None and page.error.startswith("Tesseract failed")
    assert page.text == ""


def test_a_missing_language_names_its_package() -> None:
    with pytest.raises(TesseractMissing, match="tesseract-ocr-xyz"):
        read(probe_picture(), languages="deu+xyz")


def test_a_missing_program_names_its_package(monkeypatch) -> None:
    monkeypatch.setattr(tesseract, "PROGRAM", "tesseract-not-installed")
    with pytest.raises(TesseractMissing, match=r"\(package tesseract-ocr\)"):
        read(probe_picture())


def test_the_tsv_gives_lines_paragraphs_and_the_mean_word_confidence() -> None:
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tl\tt\tw\th\tconf\ttext"
    rows = [
        "1\t1\t0\t0\t0\t0\t0\t0\t9\t9\t-1\t",
        "5\t1\t1\t1\t1\t1\t0\t0\t9\t9\t90\tSehr",
        "5\t1\t1\t1\t1\t2\t0\t0\t9\t9\t80\tgeehrte",
        "5\t1\t1\t1\t2\t1\t0\t0\t9\t9\t70\tDamen",
        "5\t1\t2\t1\t1\t1\t0\t0\t9\t9\t60\tGruß",
        "5\t1\t2\t1\t1\t2\t0\t0\t9\t9\t95\t ",
    ]
    assert parse_tsv("\n".join([header, *rows])) == ("Sehr geehrte\nDamen\n\nGruß", 75.0)
    assert parse_tsv(header) == ("", None)


@pytest.mark.slow
def test_a_generated_scan_gives_its_marker_and_words() -> None:
    for seed in range(200):
        spec = DocumentSpec(seed, "pdf_scan", "scan", datetime(2020, 1, 1, tzinfo=UTC))
        text = documents.set_text(spec)
        if text is not None:
            break
    assert text is not None
    data, pages = documents.document_bytes(spec, 200_000)
    rendering = render(data, "pdf", purpose="tesseract", first=1, count=5, timeout=60,
                       memory=1024**3)  # fmt: skip
    assert len(rendering.pages) == pages
    read_pages = [read(page.png) for page in rendering.pages]
    found = "\n".join(page.text for page in read_pages)
    assert text.marker in found
    assert sum(word in found for word in text.words) >= 0.8 * len(text.words)
    assert all(not page.uncertain for page in read_pages)

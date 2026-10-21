"""How fast one process extracts: long PDFs and a typical mix of generated documents.

The figures are printed (pytest -s); the assertions only catch an extraction that became an
order of magnitude slower.
"""

import base64
import math
import random
import time
from datetime import UTC, datetime

import pytest

from mailrobbe.attachments.extract import ExtractionLimits, extract_document
from mailrobbe.enums import DocumentTextStatus
from mailrobbe.generator import documents
from mailrobbe.generator import fileformats as ff
from mailrobbe.generator.model import AttachmentSpec, DocumentSpec
from mailrobbe.generator.vocabulary import ATTACHMENT_TYPES

pytestmark = pytest.mark.slow
LIMITS = ExtractionLimits()
LINE = "Position {n}: Lieferung und Montage laut Angebot, 1.234,56 € netto zuzüglich Umsatzsteuer"


@pytest.mark.parametrize("pages", [50, 200])
def test_long_pdfs_are_read_page_by_page(pages: int) -> None:
    content = [
        [f"Seite {p} von {pages}"] + [LINE.format(n=n) for n in range(15)] for p in range(pages)
    ]
    data = ff.pdf(content, random.Random(pages))
    started = time.perf_counter()
    result = extract_document(data, "Bericht.pdf", "application/pdf", LIMITS)
    elapsed = time.perf_counter() - started
    assert (result.status, result.pages, result.truncated) == (
        DocumentTextStatus.TEXT,
        pages,
        False,
    )
    assert all(f"Seite {p} von {pages}" in result.text for p in range(pages))
    print(f"\nPDF of {pages} pages: {elapsed:.2f} s, {pages / elapsed:.0f} pages/s")
    assert elapsed < 30


def test_a_typical_mix_of_documents() -> None:
    rng = random.Random(1)
    templates = [t for t in (*ATTACHMENT_TYPES, *documents.PAPERS) if t[0] in documents.TEMPLATES]
    when = datetime(2021, 5, 4, tzinfo=UTC)
    mix = []
    for seed in range(150):
        name, mime, median, spread, _ = rng.choices(templates, [t[4] for t in templates])[0]
        form, themes = documents.TEMPLATES[name]
        size = min(20 * 1024**2, int(median * math.exp(spread * rng.gauss(0, 1))))
        document = DocumentSpec(seed, form, rng.choice(themes), when)
        built = documents.build(AttachmentSpec(name, mime, size, document=document))
        mix.append((name, mime, base64.decodebytes(b"".join(built.encoded)), built))
    started = time.perf_counter()
    for name, mime, data, built in mix:
        result = extract_document(data, name, mime, LIMITS)
        assert result.status is built.status, name
    elapsed = time.perf_counter() - started
    megabytes = sum(len(data) for _, _, data, _ in mix) / 1024**2
    print(
        f"\n{len(mix)} documents, {megabytes:.0f} MiB: {elapsed:.2f} s, {len(mix) / elapsed:.0f}/s"
    )
    assert len(mix) / elapsed > 5

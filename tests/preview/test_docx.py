"""DOCX to HTML (D122): structure, emphasis, tables, footnotes, links and images through mammoth,
and the safe reading of the package before mammoth sees it."""

import random
from datetime import datetime

import pytest

from mailrobbe.attachments.extract import packages
from mailrobbe.attachments.extract.base import Damaged, Encrypted
from mailrobbe.generator import fileformats as ff
from mailrobbe.preview.docx import docx_html
from mailrobbe.preview.sanitize import IMAGE_PLACEHOLDER, sanitize
from tests.attachments.extract.samples import ole
from tests.attachments.extract.test_safety import LAUGHS
from tests.preview.samples import (
    DOCX_NS,
    EMF,
    JPEG,
    SVG,
    docx,
    drawing,
    footnotes,
    para,
    png,
    run,
)


def html(data: bytes) -> str:
    return sanitize(docx_html(data))


def test_structure_and_emphasis() -> None:
    body = (
        para(run("Bericht"), style="Title")
        + para(run("Überschrift"), style="Heading1")
        + para(run("Abschnitt"), style="Heading2")
        + para(
            run("fett", "<w:b/>"),
            run(" kursiv", "<w:i/>"),
            run(" unterstrichen", '<w:u w:val="single"/>'),
            run(" gestrichen", "<w:strike/>"),
        )
        + para(
            run("Betrag:"), "<w:r><w:tab/></w:r>", run("1.500 €"), "<w:r><w:br/></w:r>", run("Ende")
        )
    )
    assert html(docx(body)) == (
        "<h1>Bericht</h1><h1>Überschrift</h1><h2>Abschnitt</h2>"
        "<p><strong>fett</strong><em> kursiv</em><u> unterstrichen</u><s> gestrichen</s></p>"
        "<p>Betrag:\t1.500 €<br>Ende</p>"
    )


def test_tables_with_spans() -> None:
    def cell(text: str, properties: str = "") -> str:
        return f"<w:tc><w:tcPr>{properties}</w:tcPr>{para(run(text))}</w:tc>"

    wide = cell("Breit", '<w:gridSpan w:val="2"/>')
    high = cell("Hoch", '<w:vMerge w:val="restart"/>')
    rows = [wide, high + cell("a"), cell("", "<w:vMerge/>") + cell("b")]
    table = "<w:tbl>" + "".join(f"<w:tr>{row}</w:tr>" for row in rows) + "</w:tbl>"
    assert html(docx(table)) == (
        '<table><tr><td colspan="2"><p>Breit</p></td></tr>'
        '<tr><td rowspan="2"><p>Hoch</p></td><td><p>a</p></td></tr>'
        "<tr><td><p>b</p></td></tr></table>"
    )


def test_footnotes_and_a_link_without_its_target() -> None:
    body = para(
        run("Siehe "),
        '<w:hyperlink r:id="rIdLink">' + run("Tracker") + "</w:hyperlink>",
        '<w:r><w:footnoteReference w:id="1"/></w:r>',
    )
    data = docx(
        body,
        related=(
            ("rIdLink", "hyperlink", "https://tracker.example/?id=7", True),
            ("rIdNotes", "footnotes", "footnotes.xml", False),
        ),
        parts={"word/footnotes.xml": footnotes("Quelle: Protokoll vom 3. März")},
    )
    assert html(data) == (
        "<p>Siehe <a>Tracker</a>"
        '<sup><a href="about:srcdoc#footnote-1" id="footnote-ref-1">[1]</a></sup></p>'
        '<ol><li id="footnote-1"><p>Quelle: Protokoll vom 3. März '
        '<a href="about:srcdoc#footnote-ref-1">↑</a></p></li></ol>'
    )


def test_raster_images_inline_and_others_as_a_placeholder() -> None:
    picture = png()
    body = para(
        drawing("rIdPng", "Firmenlogo"),
        drawing("rIdJpeg"),
        drawing("rIdEmf"),
        drawing("rIdSvg"),
        drawing("rIdMissing"),
        drawing("rIdLinked", linked=True),
    )
    data = docx(
        body,
        related=(
            ("rIdPng", "image", "media/a.png", False),
            ("rIdJpeg", "image", "media/b.png", False),  # a JPEG under a PNG name
            ("rIdEmf", "image", "media/c.emf", False),
            ("rIdSvg", "image", "media/d.png", False),  # an SVG under a PNG name
            ("rIdMissing", "image", "media/e.png", False),
            ("rIdLinked", "image", "https://tracker.example/pixel.png", True),
        ),
        parts={
            "word/media/a.png": picture,
            "word/media/b.png": JPEG,
            "word/media/c.emf": EMF,
            "word/media/d.png": SVG,
        },
    )
    result = html(data)
    png_url = "data:image/png;base64,iVBORw0KGgo"
    assert result.startswith(f'<p><img alt="Firmenlogo" src="{png_url}')
    assert '<img src="data:image/jpeg;base64,/9j/' in result
    assert result.count("<img") == 2
    assert result.count(IMAGE_PLACEHOLDER) == 4
    assert "tracker" not in result and "svg" not in result


def test_a_generated_document() -> None:
    body: list[ff.Block] = [
        ff.Para("Jahresbericht", "title"),
        ff.Para("Finanzen", "heading"),
        ff.Para("Spenden\tbetrugen 1.500,00 EUR."),
        [["Konto", "Betrag"], ["DE02 1203 0000 0000 2020 51", 1500.0]],
    ]
    data = ff.docx(
        body,
        title="Jahresbericht",
        author="Anna",
        when=datetime(2021, 3, 4),
        header="Kopf",
        footer="Fuß",
        size=4000,
        rng=random.Random(1),
    )
    result = html(data)
    assert "<h1>Finanzen</h1><p>Spenden\tbetrugen 1.500,00 EUR.</p><table>" in result
    assert "<td><p>DE02 1203 0000 0000 2020 51</p></td>" in result


def test_a_zip_bomb_stops_at_the_xml_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(packages, "XML_BUDGET", 8 * 1024**2)
    data = docx("<w:p><w:r><w:rPr><w:b/></w:rPr></w:r></w:p>" * (16 * 1024**2 // 43))
    assert len(data) < 1024**2
    with pytest.raises(Damaged, match=r"more than 8 MiB of XML in the document \(a zip bomb\?\)"):
        docx_html(data)


def test_document_type_and_entity_declarations_are_refused() -> None:
    laughs = f"{LAUGHS}<w:document {DOCX_NS}><w:body>{para(run('&lol9;'))}</w:body></w:document>"
    with pytest.raises(Damaged, match="document type declaration"):
        docx_html(docx(para(run("Text")), parts={"word/document.xml": laughs}))
    # the main part under a name that is no .xml is checked as well
    with pytest.raises(Damaged, match=r"word/body\.dat: XML with a document type declaration"):
        docx_html(docx(para(run("Text")), parts={"word/body.dat": laughs}, main="word/body.dat"))
    styles = '<?xml version="1.0"?><!DOCTYPE x SYSTEM "http://203.0.113.1/x.dtd"><x/>'
    with pytest.raises(Damaged, match=r"word/styles\.xml"):
        docx_html(docx(para(run("Text")), parts={"word/styles.xml": styles}))


def test_encrypted_legacy_and_damaged_files() -> None:
    with pytest.raises(Encrypted):
        docx_html(ole("EncryptedInfo", "EncryptedPackage"))
    with pytest.raises(Damaged, match="legacy Word file"):
        docx_html(ole("WordDocument"))
    with pytest.raises(Damaged, match="damaged ZIP container"):
        docx_html(b"PK\x03\x04 not really")

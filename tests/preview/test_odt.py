"""ODT to HTML (D122): paragraphs, headings, emphasis from styles, spaces, lists, tables, images,
notes, what is left out, and hostile packages."""

import random
from datetime import datetime

import pytest

from mailrobbe.attachments.extract import packages
from mailrobbe.attachments.extract.base import Damaged, Encrypted
from mailrobbe.generator import fileformats as ff
from mailrobbe.preview.odt import odt_html
from mailrobbe.preview.sanitize import IMAGE_PLACEHOLDER, sanitize
from tests.attachments.extract.samples import package
from tests.attachments.extract.test_safety import LAUGHS
from tests.preview.samples import EMF, JPEG, ODF_NS, SVG, odt, png, text_style


def html(data: bytes) -> str:
    return sanitize(odt_html(data))


def test_paragraphs_headings_and_spaces() -> None:
    body = (
        '<text:h text:outline-level="1">Bericht</text:h>'
        '<text:h text:outline-level="2">Teil  eins</text:h>'
        '<text:h text:outline-level="9">Tief</text:h><text:h>Ohne Ebene</text:h>'
        '<text:p>Betrag:<text:tab/>1.500 €<text:s text:c="3"/>bar<text:line-break/>Ende</text:p>'
        "<text:p>Zeile\n   mit   Umbruch im XML <text:s/>und &lt;Zeichen&gt; &amp; mehr</text:p>"
        '<text:p><text:a xlink:href="https://tracker.example/?id=7">Linktext</text:a></text:p>'
    )
    assert html(odt(body)) == (
        "<h1>Bericht</h1><h2>Teil eins</h2><h6>Tief</h6><h1>Ohne Ebene</h1>"
        "<p>Betrag:\t1.500 €   bar<br>Ende</p>"
        "<p>Zeile mit Umbruch im XML  und &lt;Zeichen&gt; &amp; mehr</p>"
        "<p>Linktext</p>"
    )


def test_emphasis_from_automatic_and_named_styles() -> None:
    styles = text_style("Strong_20_Emphasis", font_weight="bold") + text_style(
        "Wichtig", family="paragraph", font_style="italic"
    )
    automatic = (
        text_style("T1", font_weight="bold")
        + text_style("T2", font_style="italic")
        + text_style("T3", text_underline_style="solid")
        + text_style("T4", parent="Strong_20_Emphasis", font_style="oblique")
        + text_style("T5", parent="Strong_20_Emphasis", font_weight="normal")
        + text_style("T6", font_weight="700", text_underline_style="none")
        + text_style("P1", family="paragraph", parent="Wichtig")
    )
    body = (
        '<text:p>a<text:span text:style-name="T1">b</text:span>'
        '<text:span text:style-name="T2">c</text:span>'
        '<text:span text:style-name="T3">d</text:span>'
        '<text:span text:style-name="T4">e</text:span>'
        '<text:span text:style-name="T5">f</text:span>'
        '<text:span text:style-name="T6">g</text:span>'
        '<text:span text:style-name="Unbekannt">h</text:span></text:p>'
        '<text:p text:style-name="P1">Absatz</text:p>'
    )
    assert html(odt(body, automatic=automatic, styles=styles)) == (
        "<p>a<strong>b</strong><em>c</em><u>d</u><strong><em>e</em></strong>f"
        "<strong>g</strong>h</p><p><em>Absatz</em></p>"
    )


def test_lists() -> None:
    automatic = (
        '<text:list-style style:name="L1">'
        '<text:list-level-style-number text:level="1"/>'
        '<text:list-level-style-bullet text:level="2"/></text:list-style>'
    )
    body = (
        '<text:list text:style-name="L1"><text:list-item><text:p>Eins</text:p>'
        "<text:list><text:list-item><text:p>Unterpunkt</text:p></text:list-item></text:list>"
        "</text:list-item><text:list-item><text:p>Zwei</text:p></text:list-item></text:list>"
        "<text:list><text:list-header><text:p>Kopf</text:p></text:list-header></text:list>"
    )
    assert html(odt(body, automatic=automatic)) == (
        "<ol><li><p>Eins</p><ul><li><p>Unterpunkt</p></li></ul></li><li><p>Zwei</p></li></ol>"
        "<ul><li><p>Kopf</p></li></ul>"
    )


def test_tables_with_header_rows_and_spans() -> None:
    def cell(text: str, spans: str = "") -> str:
        return f"<table:table-cell{spans}><text:p>{text}</text:p></table:table-cell>"

    body = (
        '<table:table table:name="Konten"><table:table-column table:number-columns-repeated="2"/>'
        f"<table:table-header-rows><table:table-row>{cell('Name')}{cell('Betrag')}"
        "</table:table-row></table:table-header-rows>"
        f"<table:table-row>{cell('Breit', " table:number-columns-spanned='2'")}"
        "<table:covered-table-cell><text:p>verdeckt</text:p></table:covered-table-cell>"
        "</table:table-row>"
        f"<table:table-row>{cell('Hoch', " table:number-rows-spanned='2'")}{cell('a')}"
        "</table:table-row>"
        f"<table:table-row><table:covered-table-cell/>{cell('b')}</table:table-row>"
        "</table:table>"
    )
    assert html(odt(body)) == (
        "<table><thead><tr><th><p>Name</p></th><th><p>Betrag</p></th></tr></thead>"
        '<tr><td colspan="2"><p>Breit</p></td></tr>'
        '<tr><td rowspan="2"><p>Hoch</p></td><td><p>a</p></td></tr>'
        "<tr><td><p>b</p></td></tr></table>"
    )


def test_images_of_the_package() -> None:
    picture = png()
    body = (
        '<text:p>Logo: <draw:frame draw:name="Bild1"><draw:image xlink:href="Pictures/a.png"/>'
        "<svg:title>Firmen<text:span>logo</text:span></svg:title></draw:frame></text:p>"
        '<text:p><draw:frame><draw:image xlink:href="Pictures/b.svg"/>'
        '<draw:image xlink:href="./Pictures/c.jpg"/></draw:frame></text:p>'  # SVG with fallback
        '<text:p><draw:frame><draw:image xlink:href="Pictures/d.emf"/></draw:frame>'
        '<draw:frame><draw:image xlink:href="https://tracker.example/pixel.png"/></draw:frame>'
        '<draw:frame><draw:image xlink:href="Pictures/fehlt.png"/></draw:frame>'
        '<draw:frame><draw:image xlink:href="../outside.png"/></draw:frame>'
        "<draw:frame><draw:image><office:binary-data>iVBORw0KGgo=</office:binary-data>"
        "</draw:image></draw:frame></text:p>"
    )
    files = {"Pictures/a.png": picture, "Pictures/b.svg": SVG, "Pictures/c.jpg": JPEG}
    result = html(odt(body, files={**files, "Pictures/d.emf": EMF}))
    first, second, third = result.split("</p>")[:3]
    assert first.startswith('<p>Logo: <img src="data:image/png;base64,iVBORw0KGgo')
    assert first.endswith('" alt="Firmenlogo">')
    assert second.startswith('<p><img src="data:image/jpeg;base64,/9j/')
    assert third == "<p>" + IMAGE_PLACEHOLDER * 5
    assert "tracker" not in result and "iVBORw0KGgo=" not in third


def test_footnotes_and_endnotes_at_the_end() -> None:
    def note(kind: str, citation: str, text: str) -> str:
        return (
            f'<text:note text:note-class="{kind}"><text:note-citation>{citation}'
            f"</text:note-citation><text:note-body><text:p>{text}</text:p>"
            f"<text:p>zweiter Absatz</text:p></text:note-body></text:note>"
        )

    body = (
        f"<text:p>Erst{note('endnote', 'i', 'Endnote')} dann"
        f'<text:span text:style-name="T1">{note("footnote", "1", "Fußnote")}</text:span>.</text:p>'
    )
    automatic = text_style("T1", font_weight="bold")
    assert html(odt(body, automatic=automatic)) == (
        '<p>Erst<sup><a href="about:srcdoc#note-1" id="note-ref-1">i</a></sup> dann<strong>'
        '<sup><a href="about:srcdoc#note-2" id="note-ref-2">1</a></sup></strong>.</p><hr>'
        '<div id="note-2"><p><sup><a href="about:srcdoc#note-ref-2">1</a></sup> Fußnote</p>'
        "<p>zweiter Absatz</p></div>"
        '<div id="note-1"><p><sup><a href="about:srcdoc#note-ref-1">i</a></sup> Endnote</p>'
        "<p>zweiter Absatz</p></div>"
    )


def test_what_is_left_out() -> None:
    body = (
        "<text:tracked-changes><text:changed-region><text:deletion><text:p>Gelöscht</text:p>"
        "</text:deletion></text:changed-region></text:tracked-changes>"
        "<text:p>Text<office:annotation><dc:creator>Bert</dc:creator><text:p>Kommentar</text:p>"
        "</office:annotation> bleibt</text:p>"
        "<office:forms><text:p>Formular</text:p></office:forms>"
        "<text:p><draw:frame><draw:text-box><text:p>Kasten</text:p><text:p>zwei</text:p>"
        "</draw:text-box></draw:frame>nach dem Kasten</text:p>"
    )
    automatic = '<style:style style:name="x"><text:p>kein Text</text:p></style:style>'
    assert html(odt(body, automatic=automatic)) == (
        "<p>Text bleibt</p><p><br>Kasten<br>zweinach dem Kasten</p>"
    )


def test_a_generated_document() -> None:
    body: list[ff.Block] = [
        ff.Para("Jahresbericht", "title"),
        ff.Para("Finanzen", "heading"),
        ff.Para("Spenden\tbetrugen 1.500,00 EUR."),
        [["Konto", "Betrag"], ["DE02 1203 0000 0000 2020 51", 1500.0]],
    ]
    data = ff.odt(
        body, title="Jahresbericht", author="Anna", when=datetime(2021, 3, 4), size=4000,
        rng=random.Random(1),
    )  # fmt: skip
    assert html(data) == (
        "<h1>Jahresbericht</h1><h2>Finanzen</h2><p>Spenden\tbetrugen 1.500,00 EUR.</p>"
        "<table><tr><td><p>Konto</p></td><td><p>Betrag</p></td></tr>"
        "<tr><td><p>DE02 1203 0000 0000 2020 51</p></td><td><p>1.500,00</p></td></tr></table>"
    )


def test_hostile_and_broken_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = "<manifest:manifest><manifest:encryption-data/></manifest:manifest>"
    with pytest.raises(Encrypted):
        odt_html(odt("<text:p>geheim</text:p>", manifest=manifest))
    laughs = f"{LAUGHS}<office:document-content {ODF_NS}><office:body><office:text>"
    laughs += "<text:p>&lol9;</text:p></office:text></office:body></office:document-content>"
    with pytest.raises(Damaged, match=r"content\.xml: XML with a document type declaration"):
        odt_html(odt("", files={"content.xml": laughs}))
    with pytest.raises(Damaged, match="no content part"):
        odt_html(package({"mimetype": "application/vnd.oasis.opendocument.text"}))
    with pytest.raises(Damaged, match="malformed XML"):
        odt_html(odt("<text:p>offen"))
    with pytest.raises(Damaged, match="damaged ZIP container"):
        odt_html(b"PK\x03\x04 not really")
    monkeypatch.setattr(packages, "XML_BUDGET", 8 * 1024**2)
    bomb = odt("<text:p><text:s/></text:p>" * (16 * 1024**2 // 25))
    assert len(bomb) < 1024**2
    with pytest.raises(Damaged, match="more than 8 MiB of XML in the document"):
        odt_html(bomb)

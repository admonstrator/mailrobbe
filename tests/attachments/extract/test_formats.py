"""extract_document per format (D71, D72): what text each format gives, and its status."""

import base64
import json
import random

from mailrobbe.attachments.extract import ExtractionLimits
from mailrobbe.enums import DocumentKind, DocumentTextStatus
from mailrobbe.generator import fileformats as ff
from tests.attachments.extract.samples import (
    WHEN,
    W,
    docx,
    extract,
    glyphs,
    odf,
    ole,
    package,
    paragraph,
    pdf,
    rels,
    xps,
)

TEXT = DocumentTextStatus.TEXT
GERMAN = "Grüße an Jürgen: 1.234,56 € „Übersicht“ \u2013 Straße"  # en dash


# PDF


def test_pdf_text_layer_page_by_page() -> None:
    result = extract(pdf([["Rechnung Nr. 4711", GERMAN], ["Seite zwei"]]), "a.pdf")
    assert (result.status, result.pages, result.kind) == (TEXT, 2, DocumentKind.PDF)
    assert result.text.splitlines() == ["Rechnung Nr. 4711", GERMAN, "", "Seite zwei"]
    assert not result.truncated and result.error is None


def test_pdf_of_images_only_is_scanned() -> None:
    result = extract(pdf([], images=(4000, 5000, 3000)), "Scan_001.pdf")
    assert (result.status, result.pages, result.text) == (DocumentTextStatus.SCANNED, 3, "")


def test_pdf_without_text_and_images_is_empty() -> None:
    result = extract(pdf([[], []]), "leer.pdf")
    assert (result.status, result.pages) == (DocumentTextStatus.EMPTY, 2)


def test_pdf_with_a_user_password_is_encrypted() -> None:
    result = extract(pdf([["Vertraulich"]], password="geheim123"), "a.pdf")
    assert (result.status, result.text, result.error) == (DocumentTextStatus.ENCRYPTED, "", None)


def test_pdf_encrypted_with_an_empty_user_password_is_read() -> None:
    result = extract(pdf([["Nur mit Besitzerkennwort geschützt"]], password=""), "a.pdf")
    assert result.status is TEXT
    assert result.text == "Nur mit Besitzerkennwort geschützt"


def test_damaged_pdf_fails_with_its_reason() -> None:
    data = pdf([["Abgeschnitten"] * 40] * 3)
    result = extract(data[: len(data) // 2], "a.pdf")
    assert result.status is DocumentTextStatus.FAILED
    assert result.error is not None and result.error.startswith("damaged PDF")
    assert "\n" not in result.error and result.text == ""
    garbage = extract(b"%PDF-1.4\n" + random.Random(3).randbytes(5000), "kaputt.pdf")
    assert garbage.status is DocumentTextStatus.FAILED


# Office Open XML


def test_docx_body_tables_notes_comments_headers_and_footers() -> None:
    body = (
        paragraph("Protokoll", " der Sitzung")
        + "<w:p><w:r><w:t>Kasse:</w:t><w:tab/><w:t>1.234,56 €</w:t></w:r></w:p>"
        + "<w:tbl><w:tr><w:tc>" + paragraph("Name") + "</w:tc><w:tc>" + paragraph("IBAN")
        + "</w:tc></w:tr><w:tr><w:tc>" + paragraph("Max Müller") + "</w:tc><w:tc>"
        + paragraph("DE89 3704 0044 0532 0130 00") + "</w:tc></w:tr></w:tbl>"
        + "<w:p><w:del><w:r><w:delText>gestrichen</w:delText></w:r></w:del>"
        "<w:r><w:instrText> HYPERLINK x </w:instrText></w:r><w:r><w:t>Link</w:t></w:r></w:p>"
        + "<w:p><w:pPr><w:rPr><w:t>Format</w:t></w:rPr></w:pPr><w:r><w:t>Ende</w:t></w:r></w:p>"
    )  # fmt: skip
    note = f"<w:footnotes {W}><w:footnote>{paragraph('Fußnote eins')}</w:footnote></w:footnotes>"
    comment = f"<w:comments {W}><w:comment>{paragraph('Bitte prüfen')}</w:comment></w:comments>"
    header = f"<w:hdr {W}>{paragraph('Förderverein Kranich e.V.')}</w:hdr>"
    footer = f"<w:ftr {W}>{paragraph('Seite 1')}</w:ftr>"
    data = docx(
        body,
        {"footnotes.xml": note, "comments.xml": comment, "header1.xml": header,
         "header2.xml": header, "footer1.xml": footer},
        (("footnotes", "footnotes.xml"), ("comments", "comments.xml"), ("header", "header1.xml"),
         ("header", "header2.xml"), ("footer", "footer1.xml")),
    )  # fmt: skip
    result = extract(data, "Protokoll.docx")
    assert (result.status, result.kind, result.pages) == (TEXT, DocumentKind.DOCUMENT, None)
    assert result.text.split("\n") == [
        "Protokoll der Sitzung",
        "Kasse:\t1.234,56 €",
        "Name\tIBAN",
        "Max Müller\tDE89 3704 0044 0532 0130 00",
        "gestrichenLink",
        "Ende",
        "",
        "Fußnote eins",
        "",
        "Bitte prüfen",
        "",
        "Förderverein Kranich e.V.",  # the same header twice is written once
        "",
        "Seite 1",
    ]


def test_generated_docx_with_its_header_and_footer() -> None:
    blocks: list[ff.Block] = [ff.Para("Vertrag", "title"), ff.Para(GERMAN), [["A", 1.5]]]
    data = ff.docx(blocks, title="Vertrag", author="Ute", when=WHEN, header="Kopf",
                   footer="Fuß", size=50_000, rng=random.Random(2))  # fmt: skip
    result = extract(data, "Vertrag.docx")
    assert len(data) == 50_000
    assert result.text.split("\n") == ["Vertrag", GERMAN, "A\t1,50", "", "Kopf", "", "Fuß"]


def test_xlsx_sheets_rows_and_values_as_stored() -> None:
    sheets: list[tuple[str, ff.Table]] = [
        ("Spenden 2021", [["Name", "Betrag", "IBAN"], ["Jörg", 1234.5, "DE02120300000000202051"]]),
        ("Leer", []),
        ("Übersicht", [["Summe", 0.1], ["", "", "", "rechts"]]),
    ]
    data = ff.xlsx(sheets, title="t", author="a", when=WHEN, size=0, rng=random.Random(1))
    result = extract(data, "Spendenliste.xlsx")
    assert (result.status, result.pages, result.kind) == (TEXT, 3, DocumentKind.SPREADSHEET)
    assert result.text.split("\n") == [
        "Spenden 2021",
        "Name\tBetrag\tIBAN",
        "Jörg\t1234.5\tDE02120300000000202051",
        "",
        "Leer",
        "",
        "Übersicht",
        "Summe\t0.1",
        "\t\t\trechts",
    ]


def test_xlsx_inline_strings_booleans_formulas_and_gaps() -> None:
    ss = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sheet = (
        f"<worksheet {ss}><sheetData><row r='1'>"
        "<c r='A1' t='inlineStr'><is><t>Inline</t><rPh><t>phonetic</t></rPh></is></c>"
        "<c r='B1' t='b'><v>1</v></c><c r='C1'><f>A1*2</f><v>42</v></c>"
        "<c r='AZ1' t='s'><v>0</v></c></row></sheetData></worksheet>"
    )
    workbook = (
        f"<workbook {ss} xmlns:r='{ff._REL}'><sheets>"
        "<sheet name='Tabelle1' sheetId='7' r:id='rId1'/></sheets></workbook>"
    )
    data = package({
        "_rels/.rels": rels(("officeDocument", "xl/workbook.xml")),
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": rels(("worksheet", "worksheets/sheet1.xml"),
                                           ("sharedStrings", "sharedStrings.xml")),
        "xl/worksheets/sheet1.xml": sheet,
        "xl/sharedStrings.xml": f"<sst {ss}><si><r><t>Rich</t></r><r><t> Text</t></r></si></sst>",
    })  # fmt: skip
    result = extract(data, "a.xlsx")
    gap = "\t" * 17  # the empty cells before AZ are kept up to MAX_GAP
    assert result.text.split("\n") == ["Tabelle1", f"Inline\t1\t42{gap}Rich Text"]


def test_pptx_slides_in_order_with_their_notes() -> None:
    slides = [
        ("Projekt Atlas", ["Budget 12.000 €", "Start im März"], ["Sprechernotiz eins"]),
        ("Zeitplan", [], []),
        ("Kosten", ["Posten\tBetrag"], ["Notiz zwei"]),
    ]
    data = ff.pptx(slides, title="t", author="a", when=WHEN, size=0, rng=random.Random(1))
    result = extract(data, "Präsentation.pptx")
    assert (result.status, result.pages, result.kind) == (TEXT, 3, DocumentKind.PRESENTATION)
    assert result.text.split("\n") == [
        "Projekt Atlas",
        "Budget 12.000 €",
        "Start im März",
        "",
        "Sprechernotiz eins",
        "",
        "Zeitplan",
        "",
        "Kosten",
        "Posten\tBetrag",
        "",
        "Notiz zwei",
    ]


def test_password_protected_office_files_are_encrypted() -> None:
    encrypted = ole("EncryptionInfo", "EncryptedPackage")
    for name in ("a.docx", "a.xlsx", "a.pptx"):
        result = extract(encrypted, name)
        assert result.status is DocumentTextStatus.ENCRYPTED, name
    assert extract(ole("WordDocument"), "alt.docx").status is DocumentTextStatus.UNSUPPORTED
    legacy = extract(ole("WordDocument"), "alt.doc")
    assert (legacy.status, legacy.kind) == (DocumentTextStatus.UNSUPPORTED, DocumentKind.DOCUMENT)


def test_office_file_without_its_main_part_is_damaged() -> None:
    result = extract(package({"[Content_Types].xml": "<Types/>"}), "a.docx")
    assert result.status is DocumentTextStatus.FAILED
    assert result.error == "no document part (word/document.xml)"
    broken = extract(b"PK\x03\x04" + b"\x00" * 200, "a.xlsx")
    assert broken.status is DocumentTextStatus.FAILED
    assert broken.error is not None and broken.error.startswith("damaged ZIP container")


# OpenDocument


def test_odt_text_headings_tables_spaces_and_notes() -> None:
    body = (
        "<office:text><text:h>Protokoll</text:h>"
        "<text:p>Kasse<text:tab/>12,50 €<text:s text:c='3'/>bar</text:p>"
        "<text:p>Zeile<text:line-break/>zwei<text:note><text:note-citation>7</text:note-citation>"
        "<text:note-body><text:p>Anmerkung</text:p></text:note-body></text:note></text:p>"
        "<table:table><table:table-row><table:table-cell><text:p>A</text:p></table:table-cell>"
        "<table:table-cell><text:p>B</text:p></table:table-cell></table:table-row></table:table>"
        "</office:text>"
    )
    result = extract(odf("application/vnd.oasis.opendocument.text", body), "a.odt")
    assert (result.status, result.pages, result.kind) == (TEXT, None, DocumentKind.DOCUMENT)
    # a note's text comes where the note ends, before the rest of its paragraph
    assert result.text.split("\n") == [
        "Protokoll",
        "Kasse\t12,50 € bar",
        "Anmerkung",
        "Zeile",
        "zwei",
        "A\tB",
    ]


def test_generated_odt() -> None:
    blocks: list[ff.Block] = [ff.Para("Titel", "title"), ff.Para(GERMAN), [["x", 2.0]]]
    data = ff.odt(blocks, title="t", author="a", when=WHEN, size=0, rng=random.Random(1))
    assert extract(data, "a.odt").text.split("\n") == ["Titel", GERMAN, "x\t2,00"]


def test_ods_sheets_as_displayed_with_repeats() -> None:
    body = (
        "<office:spreadsheet><table:table table:name='Kasse'>"
        "<table:table-row><table:table-cell office:value='1234.5'><text:p>1.234,50 €</text:p>"
        "</table:table-cell><table:table-cell table:number-columns-repeated='2'/>"
        "<table:table-cell><text:p>bar</text:p></table:table-cell></table:table-row>"
        "<table:table-row table:number-rows-repeated='3'><table:table-cell><text:p>x</text:p>"
        "</table:table-cell></table:table-row>"
        "<table:table-row table:number-rows-repeated='1048000'><table:table-cell/>"
        "</table:table-row>"
        "</table:table><table:table table:name='Zwei'/></office:spreadsheet>"
    )
    result = extract(odf("application/vnd.oasis.opendocument.spreadsheet", body), "a.ods")
    assert (result.status, result.pages, result.kind) == (TEXT, 2, DocumentKind.SPREADSHEET)
    assert result.text.split("\n") == ["Kasse", "1.234,50 €\t\t\tbar", "x", "x", "x", "", "Zwei"]


def test_odp_pages_with_notes() -> None:
    body = (
        "<office:presentation><draw:page><draw:frame><draw:text-box><text:p>Folie eins</text:p>"
        "</draw:text-box></draw:frame><presentation:notes><draw:frame><draw:text-box>"
        "<text:p>Notiz</text:p></draw:text-box></draw:frame></presentation:notes></draw:page>"
        "<draw:page><draw:frame><draw:text-box><text:p>Folie zwei</text:p></draw:text-box>"
        "</draw:frame></draw:page></office:presentation>"
    )
    result = extract(odf("application/vnd.oasis.opendocument.presentation", body), "a.odp")
    assert (result.status, result.pages, result.kind) == (TEXT, 2, DocumentKind.PRESENTATION)
    assert result.text.split("\n") == ["Folie eins", "Notiz", "", "Folie zwei"]


def test_encrypted_odf_is_encrypted() -> None:
    manifest = (
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        '<manifest:file-entry manifest:full-path="content.xml"><manifest:encryption-data/>'
        "</manifest:file-entry></manifest:manifest>"
    )
    data = odf("application/vnd.oasis.opendocument.text", "", manifest)
    assert extract(data, "a.odt").status is DocumentTextStatus.ENCRYPTED


# XPS (D78)

XPS = "application/vnd.ms-xpsdocument"
IMAGE = (
    '<Path Data="M 0,0 L 816,0 816,1056 0,1056 Z"><Path.Fill>'
    '<ImageBrush ImageSource="/Resources/Images/1.png" Viewport="0,0,816,1056"/>'
    "</Path.Fill></Path>"
)


def test_xps_pages_in_document_order_with_runs_joined_on_their_baseline() -> None:
    first = glyphs("Spendenquittung", 100) + glyphs("Nr. 17", 100) + glyphs("{}{Betrag}: 5", 120)
    second = IMAGE + glyphs(GERMAN, 100)
    result = extract(xps([first, second], order=[2, 1]), "Quittung.xps", XPS)
    assert (result.status, result.pages, result.kind) == (TEXT, 2, DocumentKind.DOCUMENT)
    assert result.text.splitlines() == [GERMAN, "", "Spendenquittung Nr. 17", "{Betrag}: 5"]


def test_xps_without_its_document_sequence_reads_the_pages_in_name_order() -> None:
    pages = [glyphs(f"Seite {n}", 100) for n in range(1, 12)]
    result = extract(xps(pages, chain=False), "Ausdruck.oxps")
    assert result.text.split("\n\n") == [f"Seite {n}" for n in range(1, 12)]


def test_xps_of_images_only_is_scanned_and_one_without_anything_empty() -> None:
    result = extract(xps([IMAGE, IMAGE]), "Scan.xps", XPS)
    assert (result.status, result.pages, result.text) == (DocumentTextStatus.SCANNED, 2, "")
    result = extract(xps([""]), "leer.xps", XPS)
    assert (result.status, result.pages) == (DocumentTextStatus.EMPTY, 1)


# Other text formats


def test_rtf() -> None:
    rtf = (
        rb"{\rtf1\ansi\ansicpg1252{\fonttbl{\f0 Arial;}}{\colortbl;\red0\green0\blue0;}"
        rb"{\*\generator Writer}{\info{\title Geheim}}\f0 Gr\'fc\'dfe \u8364? 12{\b fett}\par "
        rb"Zeile 2\tab x{\field{\*\fldinst HYPERLINK}{\fldrslt Link}}\par}"
    )
    result = extract(rtf, "Brief.rtf")
    assert (result.status, result.kind) == (TEXT, DocumentKind.DOCUMENT)
    assert result.text.split("\n") == ["Grüße € 12fett", "Zeile 2\txLink"]


def test_plain_text_is_normalised() -> None:
    data = b"Zeile  eins\r\n\r\n\r\n\r\nZeile\x00 zwei\t\tSpalte\r\n   \r\n"
    result = extract(data, "Notizen.txt", "text/plain")
    assert (result.status, result.kind) == (TEXT, DocumentKind.TEXT)
    assert result.text == "Zeile eins\n\nZeile zwei\t\tSpalte"


def test_text_encodings_are_guessed() -> None:
    text = "Grüße, Jürgen; Straße 5 € 3"
    for data in (
        text.encode("cp1252"),
        text.encode("utf-8"),
        b"\xef\xbb\xbf" + text.encode(),
        text.encode("utf-16"),
        text.encode("utf-16-le"),
    ):
        assert extract(data, "a.txt").text == text, data[:10]
    csv = "Datum;Betrag;IBAN\r\n01.02.2021;12,50;DE02120300000000202051\r\n".encode("cp1252")
    result = extract(csv, "Export.csv", "text/csv")
    assert (result.status, result.kind) == (TEXT, DocumentKind.SPREADSHEET)
    assert result.text == "Datum;Betrag;IBAN\n01.02.2021;12,50;DE02120300000000202051"


def test_whitespace_only_text_is_empty() -> None:
    for data in (b"\r\n\r\n", b"   \t ", b"\x00\x00"):
        result = extract(data, "a.txt", "text/plain")
        assert (result.status, result.text) == (DocumentTextStatus.EMPTY, ""), data
    assert extract(b"", "a.pdf").status is DocumentTextStatus.EMPTY


def test_html_gives_the_visible_text() -> None:
    html = (
        b"<html><head><title>T</title><style>p {color: red}</style>"
        b"<script>alert('x')</script></head><body><p>Hallo J&uuml;rgen,</p>"
        b"<table><tr><td>A</td><td>B</td></tr></table></body></html>"
    )
    result = extract(html, "Seite.html", "text/html")
    assert result.status is TEXT
    assert "Hallo Jürgen," in result.text and "A" in result.text
    assert "alert" not in result.text and "color" not in result.text


def test_xml_and_json_values() -> None:
    xml = (
        '<?xml version="1.0" encoding="ISO-8859-1"?><!DOCTYPE daten>'
        "<daten><name>J\xfcrgen</name><betrag waehrung='EUR'>12.50</betrag><leer/></daten>"
    ).encode("latin-1")
    result = extract(xml, "Daten.xml", "application/xml")
    assert (result.status, result.text) == (TEXT, "Jürgen\n12.50")
    data = {"name": "Jörg", "betrag": 12.50, "liste": [1, True, None, {"iban": "DE02"}]}
    result = extract(json.dumps(data).encode(), "a.json", "application/json")
    assert result.text.split("\n") == ["Jörg", "12.5", "1", "true", "DE02"]
    broken = extract('{"name": "Jörg", '.encode(), "a.json", "application/json")
    assert broken.text == '{"name": "Jörg",'


def test_markup_declared_as_plain_text_is_read_without_its_attributes() -> None:
    xml = b'<?xml version="1.0"?><daten><betrag waehrung="EUR">12.50</betrag></daten>'
    assert extract(xml, "notiz.txt", "text/plain").text == "12.50"
    page = b'<!DOCTYPE html><html><body><p style="color: red">Hallo</p></body></html>'
    assert extract(page, "seite.txt", "text/plain").text == "Hallo"


def test_calendar_and_vcard_properties() -> None:
    ics = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:1@x.example\r\n"
        b"DTSTART:20210304T140000Z\r\nDTEND;VALUE=DATE:20210305\r\n"
        b"SUMMARY:Vorstandssitzung\\, Haushalt\r\nDESCRIPTION:Bitte Unterlagen mitbringen.\\nRaum 2"
        b"\r\n  und 3\r\nLOCATION:Am Markt 1\r\n"
        b"ORGANIZER;CN=Ute Kranz:mailto:ute@verein.example\r\n"
        b"END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    result = extract(ics, "Einladung.ics", "text/calendar")
    assert (result.status, result.kind) == (TEXT, DocumentKind.TEXT)
    assert result.text.split("\n") == [
        "2021-03-04 14:00 UTC",
        "2021-03-05",
        "Vorstandssitzung, Haushalt",
        "Bitte Unterlagen mitbringen.",
        "Raum 2 und 3",
        "Am Markt 1",
        "Ute Kranz <ute@verein.example>",
    ]
    vcf = (
        "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Müller;Max;;;\r\nFN:Max Müller\r\nORG:Kranich e.V.\r\n"
        "TEL;WORK:+49 30 23125-100\r\nNOTE;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:Gr=C3=BC=\r\n"
        "=C3=9Fe\r\nPHOTO;ENCODING=BASE64:AAAA\r\nEND:VCARD\r\n"
    ).encode()
    result = extract(vcf, "Visitenkarte.vcf", "text/vcard")
    assert result.text.split("\n") == [
        "Müller Max",
        "Max Müller",
        "Kranich e.V.",
        "+49 30 23125-100",
        "Grüße",
    ]


def test_attached_mail_is_read_like_a_mail() -> None:
    attachment = base64.encodebytes(b"%PDF-1.4 x").decode()
    eml = (
        "From: =?utf-8?q?J=C3=BCrgen_Kranz?= <juergen@verein.example>\r\n"
        "To: ute@verein.example\r\nSubject: Protokoll\r\n"
        "Date: Thu, 04 Mar 2021 10:00:00 +0100\r\nMIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="b"\r\n\r\n--b\r\n'
        "Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
        "Hallo Ute,\r\nanbei das Protokoll.\r\n--b\r\n"
        'Content-Type: application/pdf; name="Protokoll.pdf"\r\n'
        "Content-Transfer-Encoding: base64\r\n\r\n" + attachment + "--b--\r\n"
    ).encode()
    result = extract(eml, "Weitergeleitet.eml", "message/rfc822")
    assert (result.status, result.kind) == (TEXT, DocumentKind.EMAIL)
    assert result.text.split("\n") == [
        "From: Jürgen Kranz <juergen@verein.example>",
        "To: ute@verein.example",
        "Date: 2021-03-04 09:00:00 UTC",
        "Subject: Protokoll",
        "Attachments: Protokoll.pdf",
        "",
        "Hallo Ute,",
        "anbei das Protokoll.",
    ]


def test_zip_lists_member_names_without_opening_them() -> None:
    inner = package({"tief/drin.txt": "x"})
    bomb = b"\x00" * (64 * 1024**2)  # compresses to about 64 KB; never decompressed
    data = package({"Unterlagen Dokmarke2abc/": "", "Unterlagen Dokmarke2abc/Rechnung.pdf": bomb,
                    "Ablage.zip": inner})  # fmt: skip
    assert len(data) < 1024**2
    result = extract(data, "Unterlagen.zip", "application/zip")
    assert (result.status, result.kind) == (TEXT, DocumentKind.ARCHIVE)
    assert result.text.split("\n") == [
        "Unterlagen Dokmarke2abc/",
        "Unterlagen Dokmarke2abc/Rechnung.pdf",
        "Ablage.zip",
    ]


def test_formats_without_text_extraction_are_unsupported() -> None:
    for data, name, kind in (
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "Foto.png", DocumentKind.IMAGE),
        (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100, "Video.mp4", DocumentKind.MEDIA),
        (b"Rar!\x1a\x07\x00" + b"\x00" * 100, "a.rar", DocumentKind.ARCHIVE),
        (b"\x01\x02\x03\x04" * 100, "a.bin", DocumentKind.OTHER),
        # D78: markup and encoded data without text a reader would search
        (
            b'<?xml version="1.0"?>\n<svg width="10"><path d="M1 2"/></svg>',
            None,
            DocumentKind.IMAGE,
        ),
        (
            b"-----BEGIN PGP SIGNATURE-----\n\niQEzBAEBCAAdFiEE\n",
            "signature.asc",
            DocumentKind.OTHER,
        ),
        (b'body { font-family: "Arial"; }', "style.css", DocumentKind.OTHER),
        (package({"META-INF/container.xml": "<c/>"}), "Buch.epub", DocumentKind.OTHER),
    ):
        result = extract(data, name, "text/plain" if name is None else "application/octet-stream")
        assert (result.status, result.kind, result.text) == (
            DocumentTextStatus.UNSUPPORTED, kind, ""
        ), name  # fmt: skip


def test_text_beyond_max_chars_is_truncated() -> None:
    lines = [f"Zeile {n} mit etwas Text" for n in range(2000)]
    limits = ExtractionLimits(max_chars=1000)
    for data, name in (
        ("\n".join(lines).encode(), "a.txt"),
        (pdf([lines[i : i + 50] for i in range(0, 2000, 50)]), "a.pdf"),
        (ff.docx([ff.Para(line) for line in lines], title="t", author="a", when=WHEN,
                 header="", footer="", size=0, rng=random.Random(1)), "a.docx"),
    ):  # fmt: skip
        result = extract(data, name, limits=limits)
        assert (result.status, result.truncated, len(result.text)) == (TEXT, True, 1000), name
        assert result.text.startswith("Zeile 0 mit etwas Text\nZeile 1")
    short = extract(b"kurz", "a.txt", limits=limits)
    assert (short.text, short.truncated) == ("kurz", False)

"""Hostile documents: zip bombs, entity expansion, external entities, deep nesting (D72)."""

import time

import pytest

from mailrobbe.attachments.extract import packages
from mailrobbe.enums import DocumentTextStatus
from tests.attachments.extract.samples import W, docx, extract, odf, package, paragraph, rels

FAILED = DocumentTextStatus.FAILED
LAUGHS = (
    '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
    '<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">'
    '<!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">'
    '<!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">'
    '<!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">'
    '<!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">'
    '<!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">]>'
)


def test_zip_bomb_in_an_office_file_stops_at_the_xml_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(packages, "XML_BUDGET", 8 * 1024**2)  # the forked child inherits it
    # markup without text: the text limit (max_chars) does not stop it, the budget does
    data = docx("<w:p><w:r><w:rPr><w:b/></w:rPr></w:r></w:p>" * (16 * 1024**2 // 43))
    assert len(data) < 1024**2  # what the mail carries
    started = time.monotonic()
    result = extract(data, "Bombe.docx")
    assert result.status is FAILED
    assert result.error == (
        "word/document.xml: more than 8 MiB of XML in the document (a zip bomb?)"
    )
    assert time.monotonic() - started < 10
    assert packages.XML_BUDGET == 8 * 1024**2


def test_budget_counts_all_parts_of_a_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(packages, "XML_BUDGET", 4 * 1024**2)
    empty = "<w:p><w:r><w:rPr><w:b/></w:rPr></w:r></w:p>" * 30  # 1 KiB without text
    note = f"<w:footnotes {W}>{paragraph('Fußnote')}{empty * 3000}</w:footnotes>"  # 3 MiB
    data = docx(
        paragraph("Text") + empty * 3000,  # 3 MiB as well: together above the budget
        {"footnotes.xml": note},
        (("footnotes", "footnotes.xml"),),
    )
    result = extract(data, "a.docx")
    assert result.status is FAILED
    assert result.error is not None and result.error.startswith("word/footnotes.xml: more than")


def test_entity_expansion_is_refused() -> None:
    body = f"{LAUGHS}<w:document {W}><w:body>{paragraph('&lol9;')}</w:body></w:document>"
    data = package({
        "_rels/.rels": rels(("officeDocument", "word/document.xml")),
        "word/document.xml": body,
    })  # fmt: skip
    result = extract(data, "lol.docx")
    assert (result.status, result.text) == (FAILED, "")
    assert result.error == "word/document.xml: XML with a document type declaration is not read"
    xml = (LAUGHS + "<lolz>&lol9;</lolz>").encode()
    result = extract(xml, "lol.xml", "application/xml")
    assert result.status is FAILED
    assert result.error == "XML: XML with entity declarations is not read"


def test_external_entities_are_never_resolved(tmp_path: object) -> None:
    xml = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
        b"<x>&secret;</x>"
    )
    result = extract(xml, "a.xml", "application/xml")
    assert result.status is FAILED and "root:" not in result.text
    external = b'<?xml version="1.0"?><!DOCTYPE x SYSTEM "http://203.0.113.1/x.dtd"><x>Text</x>'
    assert extract(external, "a.xml", "application/xml").text == "Text"
    content = (
        '<?xml version="1.0"?><!DOCTYPE c [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        "<office:document-content><office:body><office:text><text:p>&e;</text:p>"
        "</office:text></office:body></office:document-content>"
    )
    data = package({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})
    result = extract(data, "a.odt")
    assert result.status is FAILED and "root:" not in result.text


def test_deeply_nested_documents_fail_cleanly() -> None:
    nested = "<text:span>" * 200_000 + "tief" + "</text:span>" * 200_000
    body = f"<office:text><text:p>{nested}</text:p></office:text>"
    result = extract(odf("application/vnd.oasis.opendocument.text", body), "a.odt")
    assert result.status in (DocumentTextStatus.TEXT, FAILED)
    rtf = b"{\\rtf1 " + b"{" * 100_000 + b"tief" + b"}" * 100_000 + b"}"
    assert extract(rtf, "a.rtf").text == "tief"
    json_bomb = b"[" * 100_000 + b"]" * 100_000
    result = extract(json_bomb, "a.json", "application/json")
    assert result.status in (DocumentTextStatus.EMPTY, DocumentTextStatus.TEXT, FAILED)


def test_malformed_xml_parts_are_damaged() -> None:
    result = extract(docx("<w:p><w:r><w:t>offen"), "a.docx")
    assert result.status is FAILED
    assert result.error is not None
    assert result.error.startswith("word/document.xml: malformed XML (")

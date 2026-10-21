"""Metadata of attachments (D167): what each reader finds in small handcrafted files, damage
noted without a crash, the limits on values, dates as found, and the summary."""

import io
import os
import struct
import zlib
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pypdf import PdfWriter

from mailrobbe.attachments.metadata import MetadataLimits, read_metadata
from mailrobbe.attachments.metadata.exif import read_tiff
from mailrobbe.attachments.metadata.images import read_image
from mailrobbe.attachments.metadata.model import (
    FIELD_LIMIT,
    LIST_LIMIT,
    SUMMARY_LIMIT,
    VALUE_LIMIT,
    Collector,
    Fields,
    Reading,
    clean,
    may_carry,
    summarize,
)
from mailrobbe.attachments.metadata.office import store
from mailrobbe.attachments.metadata.pdf import PDF_DATE
from mailrobbe.enums import DocumentKind, DocumentMetadataStatus
from tests.attachments.extract.samples import OLE, package
from tests.attachments.metadata import samples as s

pytestmark = pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
M = DocumentMetadataStatus
LIMITS = MetadataLimits(timeout=30)
TWO = timezone(timedelta(hours=2))


def read(data: bytes, filename: str, mime_type: str = "application/octet-stream") -> Reading:
    return read_metadata(data, filename, mime_type, LIMITS)


def collect(reader: object, data: bytes) -> Collector:
    out = Collector()
    reader(data, out)  # type: ignore[operator]
    return out


CAMERA_EXIF = {
    "make": "Canon",
    "model": "Canon EOS R6",
    "software": "Firmware 1.8.1",
    "datetime": "2024:05-06 10:00:00",  # not a date: kept as found
    "artist": "Peter Hofmann",
    "copyright": "Peter Hofmann / Redaktion",
    "xp_author": "Peter H.",
    "datetime_original": "2024-05-06T10:09:10+02:00",
    "datetime_digitized": "2024-05-06T10:09:10",  # no OffsetTimeDigitized: no zone
    "body_serial_number": "032021001234",
    "lens_model": "RF24-105mm F4 L IS USM",
    "camera_owner_name": "Redaktion Nord",
    "user_comment": "Probe am Hafen",
}
CAMERA_GPS = {
    "latitude": 52.5200833,
    "longitude": 13.41,
    "altitude": 34.5,
    "timestamp": "2024-05-06T08:09:10Z",
}


# Images


@pytest.mark.parametrize("endian", ["<", ">"])
def test_a_jpeg_gives_its_exif_gps_and_xmp(endian: str) -> None:
    data = s.jpeg(
        s.exif_segment(s.camera_tiff(endian)),
        s.segment(0xE1, s.XMP_NS + s.xmp_packet(s.XMP_DESCRIPTION)),
    )

    reading = read(data, "IMG_0001.JPG", "image/jpeg")

    assert reading.status == M.FOUND and reading.error is None
    assert reading.fields["exif"] == CAMERA_EXIF
    assert reading.fields["gps"] == CAMERA_GPS
    assert reading.fields["xmp"]["creator_tool"] == "Adobe InDesign 18.2"
    summary = summarize(reading.fields)
    assert summary.author == "Peter Hofmann"
    assert summary.program == "Firmware 1.8.1"
    assert summary.device == "Canon EOS R6"  # the make once: the model names it
    assert summary.created == datetime(2024, 5, 6, 10, 9, 10, tzinfo=TWO)
    assert summary.gps is True


def test_south_west_and_below_sea_level_are_negative() -> None:
    gps = [
        s.ascii_(1, "S"),
        s.rational(2, (33, 1), (52, 1), (0, 1)),
        s.ascii_(3, "W"),
        s.rational(4, (70, 1), (30, 1), (0, 1)),
        s.byte(5, 1),
        s.rational(6, (12, 1)),
    ]
    out = collect(read_tiff, s.tiff([s.ascii_(0x010F, "Nikon")], gps=gps))

    assert out.fields["gps"] == {"latitude": -33.8666667, "longitude": -70.5, "altitude": -12.0}


def test_damaged_offsets_keep_what_lies_inside() -> None:
    """An Exif IFD beyond the end, a value pointing outside, a GPS IFD that is IFD0 again (a
    loop) and an entry count larger than the room: noted, nothing read outside, no crash."""
    data = bytearray(
        s.tiff(
            [s.ascii_(0x010F, "Canon"), s.ascii_(0x0131, "A long software name")],
            exif=[s.ascii_(0x9003, "2024:05:06 10:09:10")],
            gps=[s.ascii_(1, "N")],
        )
    )
    entries = struct.unpack_from("<H", data, 8)[0]
    for index in range(entries):
        at = 8 + 2 + 12 * index
        tag = struct.unpack_from("<H", data, at)[0]
        if tag == 0x8769:
            struct.pack_into("<I", data, at + 8, 10_000_000)
        elif tag == 0x8825:
            struct.pack_into("<I", data, at + 8, 8)
        elif tag == 0x0131:
            struct.pack_into("<I", data, at + 8, len(data) - 4)

    reading = read(s.jpeg(s.exif_segment(bytes(data))), "kaputt.jpg", "image/jpeg")

    assert reading.status == M.FOUND
    assert reading.fields == {"exif": {"make": "Canon"}}
    assert reading.error == "EXIF: the value of tag 0x0131 lies outside the data"

    huge = bytearray(s.tiff([s.ascii_(0x010F, "Canon")]))
    struct.pack_into("<H", huge, 8, 60_000)
    out = collect(read_tiff, bytes(huge))
    assert out.fields == {"exif": {"make": "Canon"}}
    assert out.problem == "EXIF: IFD0 has 60000 entries, room for 1"


def test_a_jpeg_segment_beyond_the_end_is_damage() -> None:
    data = b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", 5000) + b"Exif\x00\x00II*\x00"

    reading = read(data, "abgeschnitten.jpg", "image/jpeg")

    assert reading.status == M.FAILED
    assert reading.error == "JPEG: the segment at byte 2 runs beyond the end"


def test_a_tiff_header_alone_or_garbage_is_no_crash() -> None:
    assert read(b"\xff\xd8\xff" + os.urandom(64), "rauschen.jpg").status in (M.EMPTY, M.FAILED)
    assert collect(read_tiff, b"II*\x00\xff\xff\xff\xff").problem is not None
    assert collect(read_tiff, b"nonsense").problem == "EXIF: no TIFF header"


def test_a_png_gives_its_text_chunks_time_and_xmp() -> None:
    itxt = b"Description\x00\x00\x00de\x00Beschreibung\x00" + "Grüße".encode()
    xmp = b"XML:com.adobe.xmp\x00\x01\x00\x00\x00" + zlib.compress(
        s.xmp_packet(
            '<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
            'xmp:CreatorTool="GIMP 2.10"/>'
        )
    )
    data = s.png(
        s.chunk(b"tEXt", b"Software\x00Screenshot-Werkzeug"),
        s.chunk(b"tEXt", b"Author\x00Anna Berg"),
        s.chunk(b"zTXt", b"Comment\x00\x00" + zlib.compress("Entwurf für März".encode("latin-1"))),
        s.chunk(b"iTXt", itxt),
        s.chunk(b"iTXt", xmp),
        s.chunk(b"tIME", struct.pack(">HBBBBB", 2023, 11, 2, 14, 5, 9)),
    )

    reading = read(data, "bildschirm.png", "image/png")

    assert reading.status == M.FOUND and reading.error is None
    assert reading.fields == {
        "png": {
            "Software": "Screenshot-Werkzeug",
            "Author": "Anna Berg",
            "Comment": "Entwurf für März",
            "Description": "Grüße",
            "tIME": "2023-11-02T14:05:09Z",
        },
        "xmp": {"creator_tool": "GIMP 2.10"},
    }
    summary = summarize(reading.fields)
    assert (summary.author, summary.program) == ("Anna Berg", "GIMP 2.10")


def test_a_png_exif_chunk_and_a_webp_are_read() -> None:
    tiff = s.tiff([s.ascii_(0x010F, "Apple"), s.ascii_(0x0110, "iPhone 13")])

    png = read(s.png(s.chunk(b"eXIf", tiff)), "foto.png", "image/png")
    webp = read(
        s.webp((b"EXIF", b"Exif\x00\x00" + tiff), (b"XMP ", s.xmp_packet(s.XMP_DESCRIPTION))),
        "foto.webp",
        "image/webp",
    )

    assert png.fields == {"exif": {"make": "Apple", "model": "iPhone 13"}}
    assert summarize(png.fields).device == "Apple iPhone 13"
    assert webp.fields["exif"] == {"make": "Apple", "model": "iPhone 13"}
    assert webp.fields["xmp"]["creator"] == ["Peter Hofmann", "Anna Berg"]


def test_an_image_without_metadata_is_empty_and_others_are_unsupported() -> None:
    assert read(s.png(), "leer.png", "image/png") == Reading(M.EMPTY)
    assert read(s.jpeg(), "leer.jpg", "image/jpeg") == Reading(M.EMPTY)
    assert read(b"GIF89a\x01\x00\x01\x00", "x.gif", "image/gif").status == M.UNSUPPORTED
    assert read(b"Hallo", "notiz.txt", "text/plain").status == M.UNSUPPORTED
    assert read(b"", "leer.pdf", "application/pdf") == Reading(M.EMPTY)


def test_xmp_reads_properties_arrays_and_history() -> None:
    out = Collector()
    read_image(s.jpeg(s.segment(0xE1, s.XMP_NS + s.xmp_packet(s.XMP_DESCRIPTION))), out)

    assert out.fields == {
        "xmp": {
            "creator_tool": "Adobe InDesign 18.2",
            "create_date": "2024-05-06T10:09:10+02:00",
            "modify_date": "2024-05-07T08:00:00Z",
            "producer": "Adobe PDF Library 17.0",
            "document_id": "xmp.did:1234",
            "instance_id": "uuid:5678",
            "creator": ["Peter Hofmann", "Anna Berg"],
            "title": ["Spendenliste"],
            "history_agents": ["Adobe InDesign 18.2", "Adobe Photoshop 25.0"],
            "history_events": 2,
        }
    }


def test_an_xmp_packet_with_a_doctype_is_refused() -> None:
    packet = b'<!DOCTYPE x [<!ENTITY a "aaaa">]><x:xmpmeta xmlns:x="adobe:ns:meta/"/>'

    reading = read(s.jpeg(s.segment(0xE1, s.XMP_NS + packet)), "boese.jpg", "image/jpeg")

    assert reading.status == M.FAILED
    assert reading.error is not None and "XMP" in reading.error


# PDF


INFO = (
    "/Title (Spendenliste 2024) /Author (Peter Hofmann) /Creator (Microsoft Word)"
    " /Producer (macOS Quartz PDFContext) /CreationDate (D:20240506100910+02'00')"
    " /ModDate (D:20240507) /Abteilung (Einkauf) /Trapped /False"
)


def test_a_pdf_gives_its_information_xmp_revisions_and_embedded_files() -> None:
    data = s.pdf(
        INFO,
        xmp=s.xmp_packet(s.XMP_DESCRIPTION),
        updates=[INFO.replace("D:20240507", "D:20240601120000Z")],
        embedded=["rechnung.xml", "anhang.txt"],
    )

    reading = read(data, "liste.pdf", "application/pdf")

    assert reading.status == M.FOUND and reading.error is None
    assert reading.fields["pdf"] == {
        "version": "1.7",
        "revisions": 2,
        "title": "Spendenliste 2024",
        "author": "Peter Hofmann",
        "creator": "Microsoft Word",
        "producer": "macOS Quartz PDFContext",
        "creation_date": "2024-05-06T10:09:10+02:00",
        "mod_date": "2024-06-01T12:00:00Z",  # the information of the last revision
        "trapped": "False",
        "embedded_files": 2,
        "embedded_file_names": ["rechnung.xml", "anhang.txt"],
    }
    assert reading.fields["pdf_custom"] == {"Abteilung": "Einkauf"}
    assert reading.fields["xmp"]["creator_tool"] == "Adobe InDesign 18.2"
    summary = summarize(reading.fields)
    assert (summary.author, summary.program) == ("Peter Hofmann", "Microsoft Word")
    assert summary.created == datetime(2024, 5, 6, 10, 9, 10, tzinfo=TWO)


def test_a_linearized_pdf_counts_one_revision_less() -> None:
    data = s.pdf("/Title (x)", linearized=True, updates=["/Title (y)"])

    assert read(data, "web.pdf", "application/pdf").fields["pdf"]["revisions"] == 1


def test_an_encrypted_pdf_keeps_what_is_readable_without_the_password() -> None:
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.add_metadata({"/Author": "Peter Hofmann"})
    writer.encrypt(user_password="geheim", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)

    reading = read(buffer.getvalue(), "geschuetzt.pdf", "application/pdf")

    assert reading.status == M.FOUND
    assert set(reading.fields) == {"pdf"} and "author" not in reading.fields["pdf"]
    assert reading.error == "encrypted: the information dictionary needs a password"


def test_a_damaged_pdf_is_a_status() -> None:
    reading = read(b"%PDF-1.4\n" + b"\x00garbage" * 50, "kaputt.pdf", "application/pdf")

    assert reading.fields == {"pdf": {"version": "1.4"}}
    assert reading.error is not None and reading.error.startswith("damaged PDF")


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("D:2024", "2024"),
        ("D:202405", "2024-05"),
        ("D:20240506100910Z", "2024-05-06T10:09:10Z"),
        ("D:20240506100910+02'00'", "2024-05-06T10:09:10+02:00"),
        ("D:20240506100910-05'30", "2024-05-06T10:09:10-05:30"),
        ("20240506100910", "2024-05-06T10:09:10"),
        ("D:20241306", None),
        ("gestern", None),
    ],
)
def test_pdf_dates(text: str, iso: str | None) -> None:
    assert PDF_DATE(text) == iso


# Office and OpenDocument


DOCX_BODY = (
    '<w:p><w:ins w:id="1" w:author="Anna Berg" w:date="2024-05-02T10:00:00Z"><w:r><w:t>neu'
    '</w:t></w:r></w:ins><w:del w:id="2" w:author="Carl Diehl"><w:r><w:delText>alt'
    "</w:delText></w:r></w:del></w:p>"
)


def test_a_docx_gives_its_properties_comments_and_tracked_changes() -> None:
    data = s.docx(DOCX_BODY, comments=["Anna Berg", "Peter Hofmann", "Anna Berg"])

    reading = read(data, "protokoll.docx")

    assert reading.status == M.FOUND and reading.error is None
    assert reading.fields == {
        "office": {
            "title": "Protokoll",
            "creator": "Peter Hofmann",
            "last_modified_by": "Anna Berg",
            "revision": 7,
            "last_printed": "2024-05-01T09:00:00Z",
            "created": "2024-04-30T08:15:00Z",
            "modified": "2024-05-02T17:45:30Z",
            "template": "Normal.dotm",
            "total_time": 95,
            "pages": 3,
            "application": "Microsoft Office Word",
            "app_version": "16.0000",
            "company": "Verein Nord e.V.",
            "comments": 3,
            "comment_authors": ["Anna Berg", "Peter Hofmann"],
            "tracked_changes": 2,
            "change_authors": ["Anna Berg", "Carl Diehl"],
        }
    }
    summary = summarize(reading.fields)
    assert (summary.author, summary.modified_by) == ("Peter Hofmann", "Anna Berg")
    assert summary.program == "Microsoft Office Word"
    assert summary.created == datetime(2024, 4, 30, 8, 15, tzinfo=UTC)


def test_a_docx_gives_its_custom_properties_under_their_own_names() -> None:
    reading = read(s.docx("<w:p/>", custom=True), "bericht.docx")

    assert reading.fields["office_custom"] == {"Abteilung": "Einkauf", "Geprüft": "true"}
    assert reading.fields["office"]["creator"] == "Peter Hofmann"


def test_a_docx_without_comments_or_changes_has_no_counts() -> None:
    office = read(s.docx("<w:p/>"), "brief.docx").fields["office"]

    assert "comments" not in office and "tracked_changes" not in office


def test_an_xlsx_finds_its_properties_by_their_usual_names() -> None:
    reading = read(s.xlsx(), "tabelle.xlsx")

    assert reading.fields["office"]["application"] == "Microsoft Excel"
    assert reading.fields["office"]["creator"] == "Peter Hofmann"


def test_office_files_without_properties_and_legacy_files_under_an_ooxml_name() -> None:
    bare = package({"word/document.xml": f"<w:document {s.W}><w:body/></w:document>"})
    legacy = read(OLE + b"\x00" * 600, "alt.docx")

    assert read(bare, "leer.docx") == Reading(M.EMPTY)
    assert legacy.status == M.FAILED
    assert legacy.error == "a legacy binary Office file under an OOXML name"


def test_an_odt_gives_its_meta() -> None:
    data = s.odt(
        "<meta:initial-creator>Peter Hofmann</meta:initial-creator>"
        "<dc:creator>Anna Berg</dc:creator>"
        "<meta:creation-date>2024-04-30T08:15:00.25</meta:creation-date>"
        "<dc:date>2024-05-02T17:45:30+01:00</dc:date>"
        "<meta:generator>LibreOffice/7.6.4.1$Linux_X86_64</meta:generator>"
        "<meta:editing-cycles>4</meta:editing-cycles>"
        "<meta:editing-duration>PT1H2M</meta:editing-duration>"
        "<meta:keyword>Hafen</meta:keyword><meta:keyword>Spende</meta:keyword>"
        '<meta:template xlink:href="../Vorlagen/Brief.ott" xlink:title="Brief"/>'
        "<dc:title>Notiz</dc:title>"
        '<meta:user-defined meta:name="Projekt">Neubau Halle 3</meta:user-defined>'
        '<meta:user-defined meta:name="Geprüft" meta:value-type="boolean">true'
        "</meta:user-defined>"
        '<meta:user-defined meta:name="">ohne Namen</meta:user-defined>'
    )

    reading = read(data, "notiz.odt")

    assert reading.status == M.FOUND
    assert reading.fields == {
        "odf": {
            "initial_creator": "Peter Hofmann",
            "creator": "Anna Berg",
            "creation_date": "2024-04-30T08:15:00.25",
            "date": "2024-05-02T17:45:30+01:00",
            "generator": "LibreOffice/7.6.4.1$Linux_X86_64",
            "editing_cycles": 4,
            "editing_duration": "PT1H2M",
            "template": "Brief",
            "template_location": "../Vorlagen/Brief.ott",
            "title": "Notiz",
            "keywords": ["Hafen", "Spende"],
        },
        "odf_custom": {"Projekt": "Neubau Halle 3", "Geprüft": "true"},
    }
    summary = summarize(reading.fields)
    assert (summary.author, summary.modified_by) == ("Peter Hofmann", "Anna Berg")
    assert summary.program == "LibreOffice/7.6.4.1$Linux_X86_64"
    assert summary.created is None  # the creation date names no zone: nothing guessed


# The model


def test_values_are_cleaned_and_capped() -> None:
    assert clean("  Peter\x00 \t Hofmann\r\n") == "Peter Hofmann"
    assert clean("x" * 2000) == "x" * (VALUE_LIMIT - 1) + "…"
    out = Collector()
    out.texts("xmp", "subject", [f"w{i % 70}" for i in range(200)])
    for index in range(FIELD_LIMIT + 50):
        out.text("pdf_custom", f"Key{index}", "v")
    out.text("pdf_custom", "", "no key")
    assert out.fields["xmp"]["subject"] == [f"w{i}" for i in range(LIST_LIMIT)]
    assert len(out.fields["pdf_custom"]) == FIELD_LIMIT - 1


def test_an_unknown_exif_date_stays_as_found() -> None:
    out = collect(read_tiff, s.tiff([s.ascii_(0x0132, "0000:00:00 00:00:00")]))

    assert out.fields == {"exif": {"datetime": "0000:00:00 00:00:00"}}


def test_the_summary_takes_the_first_field_in_order() -> None:
    fields: Fields = {
        "exif": {"make": "Canon"},
        "xmp": {"creator": ["A", "B"], "create_date": "2024-01-01T00:00:00"},
        "pdf": {"producer": "Ghostscript", "creation_date": "2023-01-01T00:00:00Z"},
    }

    summary = summarize(fields)

    assert summary.author == "A, B"
    assert summary.program == "Ghostscript"
    assert summary.device == "Canon"
    assert summary.created == datetime(2023, 1, 1, tzinfo=UTC)  # the first date with a zone
    assert summary.gps is False
    assert summarize({}) == type(summary)()
    long = summarize({"pdf": {"author": "x" * VALUE_LIMIT}}).author  # an indexed column
    assert long == "x" * (SUMMARY_LIMIT - 1) + "…"


@pytest.mark.parametrize(
    ("found", "created"),
    [
        ("2020-04-23T13:37:00+02:00", datetime(2020, 4, 23, 11, 37, tzinfo=UTC)),
        ("1900-01-01T00:00:00Z", datetime(1900, 1, 1, tzinfo=UTC)),
        ("2199-12-31T23:59:59Z", datetime(2199, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ("0001-01-01T00:00:00+01:00", None),  # before year 1 in UTC: no datetime holds it
        ("9999-12-31T23:30:00-01:00", None),  # after year 9999 in UTC
        ("0001-01-01T00:00:00Z", None),  # placeholders
        ("1601-01-01T00:00:00Z", None),
        ("1899-12-30T00:00:00Z", None),
        ("2200-01-01T00:00:00Z", None),
        ("2020-04-23T13:37:60+02:00", None),  # unreadable
    ],
)
def test_the_summary_takes_a_creation_date_in_utc_within_the_years(
    found: str, created: datetime | None
) -> None:
    summary = summarize({"pdf": {"creation_date": found}})

    assert summary.created == created
    if created is not None:
        assert summary.created is not None and summary.created.utcoffset() == timedelta(0)


def test_a_creation_date_outside_the_years_gives_way_to_the_next() -> None:
    fields: Fields = {
        "exif": {"datetime_original": "0001-01-01T00:00:00+01:00"},
        "pdf": {"creation_date": "2020-04-23T13:37:00+02:00"},
    }

    assert summarize(fields).created == datetime(2020, 4, 23, 11, 37, tzinfo=UTC)


def test_counts_are_ascii_digits_and_numbers_finite() -> None:
    out = Collector()
    for key, value in (("pages", "12"), ("words", "\u00b2"), ("slides", "9" * 19)):
        store(out, "office", key, value, frozenset())
    out.number("gps", "altitude", float("nan"))
    out.number("gps", "speed", float("inf"))

    assert out.fields == {"office": {"pages": 12, "words": "\u00b2", "slides": "9" * 19}}


def test_which_documents_may_carry_metadata() -> None:
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert may_carry(DocumentKind.IMAGE, "x.heic", "image/heic")
    assert may_carry(DocumentKind.PDF, "x.pdf", "application/pdf")
    assert may_carry(DocumentKind.DOCUMENT, None, docx)
    assert may_carry(DocumentKind.SPREADSHEET, "x.ods", "application/octet-stream")
    assert not may_carry(DocumentKind.DOCUMENT, "x.rtf", "application/rtf")
    assert not may_carry(DocumentKind.DOCUMENT, "x.doc", "application/msword")
    assert not may_carry(DocumentKind.TEXT, "x.txt", "text/plain")
    assert not may_carry(None, "x.pdf", "application/pdf")

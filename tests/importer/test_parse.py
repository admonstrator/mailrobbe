import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest

from mailrobbe.enums import ImportErrorKind
from mailrobbe.importer import parse
from mailrobbe.importer.model import BODY_TEXT_LIMIT, ParsedAddress, ParsedMail
from mailrobbe.importer.parse import parse_record
from mailrobbe.importer.split import MboxRecord, iter_records
from tests.conftest import GeneratedArchive

LIMIT = 50 * 1024**2
SEPARATOR = b"From a@b.example Mon Mar  4 09:12:33 2019"
SEPARATOR_DATE = datetime(2019, 3, 4, 9, 12, 33, tzinfo=UTC)
HEAD = (
    b"From: Eva <eva@nordwind.example>\nTo: max@elbtal.example\nMessage-ID: <1@nordwind.example>\n"
)
DATE = b"Date: Mon, 4 Mar 2019 10:12:33 +0100\n"


def _parse(
    message: bytes, separator: bytes = SEPARATOR, *, limit: int = LIMIT, truncated: bool = False
) -> ParsedMail:
    sha = hashlib.sha256(message).hexdigest()
    record = MboxRecord(0, len(message), separator, message, sha, truncated)
    return parse_record(record, attachment_hash_limit=limit)


def _mail(body: bytes = b"Hello\n", headers: bytes = b"", date: bytes = DATE) -> ParsedMail:
    return _parse(HEAD + date + headers + b"\n" + body)


def _kinds(mail: ParsedMail) -> list[ImportErrorKind]:
    return [issue.kind for issue in mail.issues]


def _expected_kinds(faults: dict[str, str]) -> set[ImportErrorKind]:
    kinds = set()
    if "missing_message_id" in faults:
        kinds.add(ImportErrorKind.MESSAGE_ID)
    if "broken_encoding" in faults:
        kinds.add(ImportErrorKind.ENCODING)
    if faults.get("bad_date", "two_digit_year") != "two_digit_year":
        kinds.add(ImportErrorKind.DATE)
    return kinds


def _subject_matches(subject: str | None, entry: dict[str, Any]) -> bool:
    expected: str = entry["subject"]
    if subject == expected:
        return True
    if subject is None:
        return False
    if entry["dkim"]["signatures"] and subject.startswith("[") and "] " in subject:
        subject = subject.partition("] ")[2]  # a list or gateway tag added after signing
    if entry["faults"].get("broken_encoding") == "broken_encoded_word":
        return expected.startswith(subject)  # base64 that lost its padding loses its last byte
    return subject == expected


@pytest.fixture(scope="module")
def parsed_archive(generated_archive: GeneratedArchive) -> list[tuple[ParsedMail, dict[str, Any]]]:
    pairs = []
    entries = iter(generated_archive.manifest)
    for path in sorted(generated_archive.mbox_dir.glob("*.mbox")):
        with path.open("rb") as handle:
            for record in iter_records(handle, max_size=256 * 1024**2):
                pairs.append((parse_record(record, attachment_hash_limit=LIMIT), next(entries)))
    return pairs


def test_every_field_matches_the_manifest(
    parsed_archive: list[tuple[ParsedMail, dict[str, Any]]],
) -> None:
    variants = {(f, v) for _, e in parsed_archive for f, v in e["faults"].items()}
    assert ("broken_encoding", "raw_8bit_header") in variants
    assert ("bad_date", "two_digit_year") in variants
    for mail, entry in parsed_archive:
        index = entry["index"]
        assert mail.message_id == entry["message_id"], index
        assert mail.in_reply_to == entry["in_reply_to"], index
        assert _subject_matches(mail.subject, entry), (index, mail.subject)
        assert mail.date_utc == datetime.fromisoformat(entry["date"]), index
        assert [a.email for a in mail.sender] == [entry["sender"]], index
        assert [a.email for a in mail.to] == entry["to"], index
        assert [a.email for a in mail.cc] == entry["cc"], index
        assert [a.email for a in mail.bcc] == entry["bcc"], index
        assert len(mail.attachments) == entry["attachments"], index
        assert set(_kinds(mail)) == _expected_kinds(entry["faults"]), (index, mail.issues)
        assert mail.body_text, index


def test_threads_carry_their_references(
    parsed_archive: list[tuple[ParsedMail, dict[str, Any]]],
) -> None:
    replies = [(m, e) for m, e in parsed_archive if e["in_reply_to"]]
    assert replies
    for mail, entry in replies:
        assert mail.reference_ids[-1] == entry["in_reply_to"]


def test_the_large_attachment_has_its_full_size(
    generated_archive: GeneratedArchive, parsed_archive: list[tuple[ParsedMail, dict[str, Any]]]
) -> None:
    size = generated_archive.config.large_attachment_size
    mails = [m for m, e in parsed_archive if "large_attachment" in e["faults"]]
    assert mails
    for mail in mails:
        large = mail.attachments[-1]
        assert large.size_bytes == size and large.sha256 is not None


def test_attachments_above_the_hash_limit_get_no_hash() -> None:
    body = (
        b"--b\nContent-Type: text/plain\n\nsee attachment\n--b\n"
        b"Content-Type: application/pdf; name=a.pdf\nContent-Transfer-Encoding: base64\n\n"
        b"JVBERi0xLjQK\n--b--\n"
    )
    headers = b'Content-Type: multipart/mixed; boundary="b"\n'
    for limit, digest in ((9, hashlib.sha256(b"%PDF-1.4\n").hexdigest()), (8, None)):
        mail = _parse(HEAD + DATE + headers + b"\n" + body, limit=limit)
        assert [(a.filename, a.size_bytes, a.sha256) for a in mail.attachments] == [
            ("a.pdf", 9, digest)
        ]


# Identifiers and subject


@pytest.mark.parametrize(
    ("header", "message_id", "issue"),
    [
        (b"Message-ID: <x@y.example> (added by postmaster)\n", "<x@y.example>", False),
        (b"Message-ID: x@y.example\n", "<x@y.example>", False),
        (b"Message-ID: no id here\n", None, True),
        (b"Message-ID: <>\n", None, True),
        (b"", None, True),
    ],
)
def test_message_id(header: bytes, message_id: str | None, issue: bool) -> None:
    mail = _parse(b"From: a@b.example\n" + DATE + header + b"\nbody\n")
    assert mail.message_id == message_id
    assert _kinds(mail) == ([ImportErrorKind.MESSAGE_ID] if issue else [])


def test_references_are_deduplicated_and_bounded() -> None:
    ids = [f"<{n}@x.example>" for n in range(60)]
    references = " ".join([ids[0], *ids]).encode()
    mail = _mail(
        headers=b"In-Reply-To: <59@x.example> <1@x.example>\nReferences: " + references + b"\n"
    )
    assert mail.in_reply_to == "<59@x.example>"
    assert mail.reference_ids == (ids[0], *ids[-49:])


@pytest.mark.parametrize(
    ("header", "subject"),
    [
        (b"Subject: =?utf-8?Q?Gr=C3=BC=C3=9Fe?= aus\n =?utf-8?B?QmVybGlu?=\n", "Grüße aus Berlin"),
        (b"Subject:   Re:  spaced   out  \n", "Re: spaced out"),
        (b"Subject: \n", None),
        (b"", None),
    ],
)
def test_subject(header: bytes, subject: str | None) -> None:
    mail = _mail(headers=header)
    assert mail.subject == subject and not mail.issues


# Decoding heuristics (the generator's broken_encoding variants and their relatives)


def test_raw_8bit_headers() -> None:
    latin = _mail(headers=b"Subject: Gr\xfc\xdfe aus K\xf6ln\n")
    assert latin.subject == "Grüße aus Köln"
    assert _kinds(latin) == [ImportErrorKind.ENCODING]
    assert "Subject header" in latin.issues[0].message
    utf8 = _mail(headers="Subject: Grüße\n".encode())
    assert utf8.subject == "Grüße" and not utf8.issues  # RFC 6532
    sender = _parse(
        b'From: "M\xfcller, Eva" <eva@x.example>\n' + DATE + b"Message-ID: <1@x>\n\nx\n"
    )
    assert sender.sender == (ParsedAddress("eva@x.example", "Müller, Eva"),)


def test_broken_encoded_words_are_decoded_as_far_as_possible() -> None:
    unterminated = _mail(headers=b"Subject: =?utf-8?Q?Gr=C3=BC=C3=9Fe_aus?=\n =?utf-8?Q?_Berlin\n")
    assert unterminated.subject == "Grüße aus Berlin"
    assert _kinds(unterminated) == [ImportErrorKind.ENCODING]
    unpadded = _mail(headers=b"Subject: =?utf-8?b?R3LDvMOfZQ?=\n")
    assert unpadded.subject == "Grüße"
    assert _kinds(unpadded) == [ImportErrorKind.ENCODING]


@pytest.mark.parametrize(
    ("charset", "body", "text", "issue"),
    [
        (b"iso-8859-1", "für".encode(), "für", "labelled iso-8859-1 but is UTF-8"),
        (b"utf-8", "für".encode("latin-1"), "für", "invalid utf-8 bytes, read as cp1252"),
        (b"x-unknown", "für".encode(), "für", "unknown charset 'x-unknown', read as utf-8"),
        (b"windows-1252", b"\x84Zitat\x93 \x80", "„Zitat“ €", None),
        (b"iso-8859-1", b"\x80 5", "€ 5", None),  # read as cp1252, as browsers do
        (b"us-ascii", b"plain", "plain", None),
    ],
)
def test_body_charsets(charset: bytes, body: bytes, text: str, issue: str | None) -> None:
    headers = (
        b"Content-Type: text/plain; charset=" + charset + b"\nContent-Transfer-Encoding: 8bit\n"
    )
    mail = _mail(body + b"\n", headers)
    assert mail.body_text == text + "\n"
    assert [i.message for i in mail.issues] == ([f"text/plain part: {issue}"] if issue else [])


def test_invalid_base64_is_decoded_leniently() -> None:
    headers = b"Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: base64\n"
    mail = _mail(b"SGFsbG8g!V2VsdA\n", headers)  # a stray character, padding lost
    assert mail.body_text == "Hallo Welt"
    assert [i.message for i in mail.issues] == ["text/plain part: invalid base64, read leniently"]
    clean = _mail(b"SGFsbG8g\n V2VsdA== \n", headers)  # whitespace is no defect (RFC 2045)
    assert clean.body_text == "Hallo Welt" and not clean.issues


# Date


@pytest.mark.parametrize(
    ("header", "problem"),
    [
        (b"", "Date header missing"),
        (b"Date: unknown\n", "Date header unparseable"),
        (b"Date: Mon, 31 Feb 2019 25:61:00 +0100\n", "Date header unparseable"),
        (b"Date: 04.03.2019 10:12:33\n", "Date header non-standard"),
        (b"Date: 2019-03-04 10:12\n", "Date header non-standard"),
        (b"Date: Mon, 4 Mar 2019 10:12:33\n", "Date header non-standard"),  # no zone
    ],
)
def test_bad_dates_fall_back_to_the_from_line(header: bytes, problem: str) -> None:
    mail = _mail(date=header)
    assert mail.date_utc == SEPARATOR_DATE
    assert _kinds(mail) == [ImportErrorKind.DATE]
    assert mail.issues[0].message.startswith(problem)
    assert mail.issues[0].message.endswith("taken from the From_ line")


@pytest.mark.parametrize(
    ("header", "instant"),
    [
        (b"Date: Mon, 4 Mar 19 10:12:33 +0100\n", datetime(2019, 3, 4, 9, 12, 33, tzinfo=UTC)),
        (b"Date: 4 Mar 2019 10:12 -0000\n", datetime(2019, 3, 4, 10, 12, tzinfo=UTC)),
        (b"Date: Mon, 4 Mar 2019 10:12:33 GMT\n", datetime(2019, 3, 4, 10, 12, 33, tzinfo=UTC)),
    ],
)
def test_rfc5322_dates(header: bytes, instant: datetime) -> None:
    mail = _mail(date=header)
    assert mail.date_utc == instant and not mail.issues


def test_without_a_from_line_the_header_is_read_loosely() -> None:
    message = HEAD + b"Date: 2019-03-04T10:12:33+01:00\n\nbody\n"
    mail = _parse(message, separator=b"")
    assert mail.date_utc == datetime(2019, 3, 4, 9, 12, 33, tzinfo=UTC)
    assert mail.issues[0].message.endswith("read as UTC")
    assert _parse(HEAD + b"\nbody\n", separator=b"").date_utc is None


def test_gmail_from_lines_carry_their_offset() -> None:
    mail = _parse(HEAD + b"\nbody\n", separator=b"From 1@xxx Mon Mar 04 10:12:33 +0100 2019")
    assert mail.date_utc == SEPARATOR_DATE


# Addresses


def test_addresses() -> None:
    mail = _parse(
        b"From: =?utf-8?Q?J=C3=A4ger=2C_Andrea?= <Andrea.Jaeger@Elbtal.example>\n"
        b'To: "Sommer, Sebastian" <s@x.example>, s@x.example, "s@x.example" <S@X.example>,\n'
        b" 'Petra Sauer' <p@y.test>, @x.example, plain@z.test\n"
        b"Cc: undisclosed-recipients:;\n"
        b"Bcc: Team: a@t.example, b@t.example;\n" + DATE + b"Message-ID: <1@x>\n\nbody\n"
    )
    assert mail.sender == (ParsedAddress("andrea.jaeger@elbtal.example", "Jäger, Andrea"),)
    assert mail.to == (
        ParsedAddress("s@x.example", "Sommer, Sebastian"),
        ParsedAddress("p@y.test", "Petra Sauer"),
        ParsedAddress("plain@z.test"),
    )
    assert mail.cc == ()
    assert [a.email for a in mail.bcc] == ["a@t.example", "b@t.example"]
    assert [i.message for i in mail.issues] == ["To header: invalid address '@x.example' left out"]


def test_display_names_equal_to_the_address_are_dropped() -> None:
    mail = _parse(b'From: "eva@x.example" <eva@x.example>\nTo: <max@y.example>\n\nx\n')
    assert mail.sender == (ParsedAddress("eva@x.example"),)
    assert mail.to == (ParsedAddress("max@y.example"),)


def test_malformed_address_lists_are_read_leniently() -> None:
    mail = _parse(b"To: a@x.example (unclosed comment, b@y.example\n" + DATE + b"\nx\n")
    assert "a@x.example" in [a.email for a in mail.to]


# Body text and attachments


def _multipart(*parts: bytes, subtype: bytes = b"mixed") -> bytes:
    body = b"".join(b"--b\n" + part for part in parts) + b"--b--\n"
    return HEAD + DATE + b"Content-Type: multipart/" + subtype + b'; boundary="b"\n\n' + body


def test_html_only_mails_get_their_text_extracted() -> None:
    html = (
        b"<html><head><title>T</title><style>p {}</style></head><body>"
        b"<p>Gr&uuml;&szlig;e &amp; mehr</p><script>x()</script><div>Zeile 1<br>Zeile 2</div>"
        b"<p></p><p></p><p>Ende\nder   Zeile</p></body></html>"
    )
    mail = _mail(html, b"Content-Type: text/html; charset=utf-8\n")
    assert mail.body_text == "Grüße & mehr\n\nZeile 1\nZeile 2\n\nEnde der Zeile"


def test_the_plain_part_wins_over_html_and_attachments() -> None:
    mail = _parse(
        _multipart(
            b"Content-Type: text/plain; name=notes.txt\n\nattached notes\n",
            b"Content-Type: text/html\n\n<p>html body</p>\n",
            b"Content-Type: text/plain\n\nplain body\n",
        )
    )
    assert mail.body_text == "plain body"
    assert [a.filename for a in mail.attachments] == ["notes.txt"]


def test_a_forwarded_message_is_searched_but_its_text_is_not_the_body() -> None:
    forwarded = (
        b"Content-Type: message/rfc822\nContent-Disposition: inline\n\n"
        b"From: x@y.example\nSubject: original\n"
        b'Content-Type: multipart/mixed; boundary="c"\n\n'
        b"--c\nContent-Type: text/plain\n\noriginal text\n"
        b"--c\nContent-Type: image/png\nContent-Disposition: attachment\n\nPNG\n--c--\n"
    )
    mail = _parse(_multipart(b"Content-Type: text/plain\n\nsee below\n", forwarded))
    assert mail.body_text == "see below"
    assert [(a.filename, a.mime_type) for a in mail.attachments] == [(None, "image/png")]
    alone = _parse(_multipart(forwarded))
    assert alone.body_text == "original text"


def test_an_attached_message_is_one_attachment() -> None:
    attached = (
        b'Content-Type: message/rfc822; name="old.eml"\n\n'
        b"From: x@y.example\nContent-Type: image/png; name=inner.png\n\nPNG\n"
    )
    mail = _parse(_multipart(b"Content-Type: text/plain\n\nsee attachment\n", attached))
    ((name, mime_type, size),) = [(a.filename, a.mime_type, a.size_bytes) for a in mail.attachments]
    assert (name, mime_type) == ("old.eml", "message/rfc822") and size > 0


@pytest.mark.parametrize(
    ("disposition", "name"),
    [
        (b"attachment; filename*=UTF-8''Gr%C3%BC%C3%9Fe%20an%20alle.pdf", "Grüße an alle.pdf"),
        (b"attachment; filename*0*=UTF-8''Gr%C3%BC; filename*1*=%C3%9Fe.pdf", "Grüße.pdf"),
        (b'attachment; filename="=?utf-8?B?R3LDvMOfZS5wZGY=?="', "Grüße.pdf"),
        (b"attachment", None),
        (b'inline; filename="logo.png"', "logo.png"),
    ],
)
def test_attachment_names(disposition: bytes, name: str | None) -> None:
    part = b"Content-Type: application/pdf\nContent-Disposition: " + disposition + b"\n\n%PDF\n"
    mail = _parse(_multipart(b"Content-Type: text/plain\n\nbody\n", part))
    assert [a.filename for a in mail.attachments] == [name] and not mail.issues
    assert mail.attachments[0].mime_type == "application/pdf"


def test_a_multipart_without_boundary_is_read_as_text() -> None:
    mail = _mail(
        b"--x\nContent-Type: text/plain\n\nhello\n--x--\n", b"Content-Type: multipart/mixed\n"
    )
    assert mail.body_text is not None and "hello" in mail.body_text
    assert _kinds(mail) == [ImportErrorKind.PARSE]


def test_nul_bytes_and_crlf_are_removed_from_the_body() -> None:
    mail = _mail(b"line one\x00\r\nline two\r\n")
    assert mail.body_text == "line one\nline two\n"


def test_the_body_is_cut() -> None:
    mail = _mail(b"x" * (BODY_TEXT_LIMIT + 10) + b"\n")
    assert mail.body_text == "x" * BODY_TEXT_LIMIT


def test_crlf_messages() -> None:
    message = (HEAD + DATE + b"Subject: crlf\n\nfirst\nsecond\n").replace(b"\n", b"\r\n")
    mail = _parse(message)
    assert (mail.subject, mail.body_text, mail.issues) == ("crlf", "first\nsecond\n", ())
    assert mail.message_id == "<1@nordwind.example>"


def test_an_empty_message() -> None:
    mail = _parse(b"")
    assert (mail.subject, mail.body_text, mail.sender, mail.attachments) == (None, None, (), ())
    assert mail.date_utc == SEPARATOR_DATE
    assert _kinds(mail) == [ImportErrorKind.MESSAGE_ID, ImportErrorKind.DATE]


def test_a_message_that_is_only_headers() -> None:
    mail = _parse(HEAD + DATE + b"Subject: nothing else")
    assert mail.subject == "nothing else" and mail.body_text is None and not mail.issues


def test_a_header_block_cut_by_a_broken_line() -> None:
    mail = _parse(HEAD + b"this is no header\n" + DATE + b"\nbody\n")
    assert ImportErrorKind.PARSE in _kinds(mail)
    assert mail.message_id == "<1@nordwind.example>"


def test_truncated_records_give_headers_only() -> None:
    message = _multipart(
        b"Content-Type: text/plain\n\nbody\n",
        b"Content-Type: application/zip; name=a.zip\nContent-Transfer-Encoding: base64\n\nUEs=\n",
    )
    mail = _parse(message[: len(message) // 2], truncated=True)
    assert mail.message_id == "<1@nordwind.example>" and mail.date_utc is not None
    assert (mail.body_text, mail.attachments, mail.issues) == (None, (), ())


def test_an_unexpected_failure_keeps_what_was_read(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object) -> None:
        raise RuntimeError("boom\nsecond line")

    monkeypatch.setattr(parse._MailParser, "_read_parts", fail)
    mail = _mail(headers=b"Subject: kept\n")
    assert (mail.subject, mail.message_id) == ("kept", "<1@nordwind.example>")
    assert _kinds(mail) == [ImportErrorKind.PARSE]
    assert mail.issues[0].message.endswith("RuntimeError: boom second line")

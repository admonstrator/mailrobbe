"""The body views of the mail detail on message bytes (api/body.py)."""

import base64

from mailrobbe.api import body
from mailrobbe.api.schemas import RAW_LIMIT, TEXT_LIMIT, HeaderField, MailText, TextSegment
from mailrobbe.blocks.model import Paragraph, hash_hex, paragraph_hash, paragraphs

HEAD = (
    b"From: Eva Berg <eva@nordwind.example>\nTo: max@elbtal.example\n"
    b"Message-ID: <1@nordwind.example>\nDate: Mon, 4 Mar 2019 10:12:33 +0100\n"
)


def _mail(content_type: bytes, payload: bytes, headers: bytes = b"") -> bytes:
    return HEAD + headers + b"Content-Type: " + content_type + b"\n\n" + payload


def _multipart(subtype: bytes, *parts: bytes) -> bytes:
    payload = b"".join(b"--b\n" + part + b"\n" for part in parts) + b"--b--\n"
    return _mail(b"multipart/" + subtype + b'; boundary="b"', payload)


PLAIN = b"Content-Type: text/plain; charset=utf-8\n\nHallo Max,\nbis morgen.\n"
HTML = (
    b"Content-Type: text/html; charset=utf-8\n\n"
    b"<html><head><title>t</title></head><body><p>Hallo <b>Max</b>,</p><p>bis morgen.</p>"
    b"</body></html>\n"
)


def test_text_is_the_plain_part_and_tells_about_html() -> None:
    text = body.mail_text(_multipart(b"alternative", PLAIN, HTML))
    assert (text.text, text.source, text.has_html, text.truncated) == (
        "Hallo Max,\nbis morgen.\n",
        "text/plain",
        True,
        False,
    )


def test_an_html_only_mail_shows_its_text() -> None:
    text = body.mail_text(_mail(b"text/html; charset=utf-8", HTML.partition(b"\n\n")[2]))
    assert (text.text, text.source, text.has_html) == (
        "Hallo Max,\n\nbis morgen.",
        "text/html",
        True,
    )


def test_a_forwarded_message_counts_only_without_text_of_its_own() -> None:
    forwarded = (
        b"Content-Type: message/rfc822\n\nFrom: a@b.example\nSubject: alt\n"
        b"Content-Type: text/plain\n\noriginal text\n"
    )
    own = body.mail_text(_multipart(b"mixed", PLAIN, forwarded))
    assert own.text == "Hallo Max,\nbis morgen.\n"
    only = body.mail_text(_multipart(b"mixed", forwarded))
    assert (only.text, only.source) == ("original text\n", "text/plain")


def test_attached_text_files_are_not_the_body() -> None:
    attached = (
        b"Content-Type: text/plain; name=notes.txt\nContent-Disposition: attachment\n\n"
        b"not the body\n"
    )
    text = body.mail_text(_multipart(b"mixed", attached, HTML))
    assert (text.text, text.source) == ("Hallo Max,\n\nbis morgen.", "text/html")


def test_a_mail_without_text_part() -> None:
    attachment = b"Content-Type: application/pdf; name=a.pdf\nContent-Transfer-Encoding: base64\n\n"
    text = body.mail_text(_multipart(b"mixed", attachment + b"JVBERi0xLjQK\n"))
    assert (text.text, text.source, text.has_html, text.truncated) == ("", "none", False, False)
    assert body.mail_html(_multipart(b"mixed", attachment + b"JVBERi0xLjQK\n")) is None


def test_charsets_line_ends_and_nul_characters() -> None:
    mislabelled = _mail(b"text/plain; charset=iso-8859-1", "Grüße\r\nbis bald\x00\n".encode())
    assert body.mail_text(mislabelled).text == "Grüße\nbis bald\n"
    latin1 = _mail(b"text/plain; charset=x-unknown", "Grüße\n".encode("latin-1"))
    assert body.mail_text(latin1).text == "Grüße\n"


def test_invalid_base64_is_read_leniently() -> None:
    payload = base64.b64encode("Grüße aus Hamburg\n".encode())
    broken = payload[:8] + b"!#%" + payload[8:]
    text = body.mail_text(
        _mail(b"text/plain; charset=utf-8", broken, b"Content-Transfer-Encoding: base64\n")
    )
    assert text.text == "Grüße aus Hamburg\n"


def test_long_texts_are_cut_at_the_limit() -> None:
    long = body.mail_text(_mail(b"text/plain", b"x" * (TEXT_LIMIT + 10) + b"\n"))
    assert (len(long.text), long.truncated) == (TEXT_LIMIT, True)
    exact = body.mail_text(_mail(b"text/plain", b"y" * (TEXT_LIMIT - 1) + b"\n"))
    assert (len(exact.text), exact.truncated) == (TEXT_LIMIT, False)


def test_the_text_comes_with_its_segments() -> None:
    reply = "Passt.\n\nAm 1.3.2019 um 10:12 schrieb Eva:\n> Treffen am Montag?\n"
    text = body.mail_text(_mail(b"text/plain; charset=utf-8", reply.encode()))
    assert text.segments == [
        TextSegment(kind="text", start=0, end=8, lines=1, folded=False),
        TextSegment(kind="quote", start=8, end=len(reply), lines=2, folded=True),
    ]
    html = b"<p>Ok.</p><p>-----Original Message-----<br>From: Eva<br>Sent: Monday</p><p>alt</p>"
    converted = body.mail_text(_mail(b"text/html; charset=utf-8", html))
    assert [(s.kind, s.folded) for s in converted.segments] == [
        ("text", False),
        ("original", True),
    ]
    assert converted.text[converted.segments[1].start :].startswith("-----Original Message")
    assert body.mail_text(_mail(b"text/plain", b"")).segments == [
        TextSegment(kind="text", start=0, end=0, lines=0, folded=False)
    ]


def test_html_is_the_first_html_part_decoded() -> None:
    latin1 = (
        "Content-Type: text/html; charset=iso-8859-1\n\n<p>Grüße</p>\n".encode("latin-1"),
        b"Content-Type: text/html\n\n<p>second</p>\n",
    )
    assert body.mail_html(_multipart(b"mixed", PLAIN, *latin1)) == "<p>Grüße</p>\n"
    assert body.mail_html(_mail(b"text/plain", b"no html\n")) is None


def test_headers_in_mail_order_unfolded_and_decoded() -> None:
    received = "by mx2.example; Mon, 4 Mar 2019 10:12:34 +0100"
    message = (
        b"Received: from mx.example\n\t" + received.encode() + b"\n"
        b"Subject: =?utf-8?q?Gr=C3=BC=C3=9Fe?= aus\n =?iso-8859-1?b?SGFtYnVyZw==?=\n"
        + "X-Ort: Lübeck\n".encode("latin-1")
        + "x-lower: Straße\n".encode()
        + b"Received: second\n\nbody\nNot: a header\n"
    )
    assert body.mail_headers(message).headers == [
        HeaderField(name="Received", value=f"from mx.example\t{received}"),
        HeaderField(name="Subject", value="Grüße aus Hamburg"),
        HeaderField(name="X-Ort", value="Lübeck"),
        HeaderField(name="x-lower", value="Straße"),
        HeaderField(name="Received", value="second"),
    ]


def test_raw_is_cut_after_a_line_end() -> None:
    line = b"y" * 99 + b"\n"
    message = line * (RAW_LIMIT // len(line) + 5)
    raw = body.mail_raw(message)
    assert raw.truncated and raw.size == len(message)
    assert raw.raw.endswith("\n") and len(raw.raw) == RAW_LIMIT // len(line) * len(line)
    invalid = b"Subject: x\n\n\xff\xfe broken\n"
    small = body.mail_raw(invalid)
    expected = "Subject: x\n\n" + "\N{REPLACEMENT CHARACTER}" * 2 + " broken\n"
    assert (small.raw, small.truncated, small.size) == (expected, False, len(invalid))


# Standard blocks in the text view (D227) ---------------------------------------------------

NOTICE = "Diese Nachricht ist vertraulich und nur für den Empfänger bestimmt."
WITH_NOTICE = (
    f"Hallo Eva,\n\npasst so, ich schicke den Vertrag morgen an alle.\n\n{NOTICE}\n\nGruß Max\n\n"
    f"Am 1.3.2019 um 10:12 schrieb Eva:\n> Treffen am Montag wegen der Spende für den Rat?\n>\n"
    f"> {NOTICE}\n>\n> Eva\n"
)


def _shown(text: str) -> tuple[MailText, list[Paragraph]]:
    shown = body.mail_text(_mail(b"text/plain; charset=utf-8", text.encode()))
    assert shown.text == text and shown.paragraphs == []
    return shown, paragraphs(text)


def test_a_standard_block_is_cut_out_of_its_segment_wherever_it_stands() -> None:
    shown, found = _shown(WITH_NOTICE)
    notice = paragraph_hash(NOTICE)
    assert notice is not None
    marked = body.with_blocks(shown, found, {notice: body.Known(True, 1234, None)})
    block = hash_hex(notice)
    assert [
        (s.kind, WITH_NOTICE[s.start : s.end], s.lines, s.folded, s.block) for s in marked.segments
    ] == [
        (
            "text",
            "Hallo Eva,\n\npasst so, ich schicke den Vertrag morgen an alle.\n\n",
            2,
            False,
            None,
        ),
        ("standard", f"{NOTICE}\n\n", 1, True, block),  # with the blank line below it
        ("text", "Gruß Max\n\n", 1, False, None),
        (
            "quote",
            "Am 1.3.2019 um 10:12 schrieb Eva:\n"
            "> Treffen am Montag wegen der Spende für den Rat?\n>\n",
            2,
            True,
            None,
        ),
        ("standard", f"> {NOTICE}\n>\n", 1, True, block),  # in the quote too
        ("quote", "> Eva\n", 1, True, None),
    ]
    assert [
        (p.start, p.end, p.hash, p.standard, p.mails, p.override) for p in marked.paragraphs
    ] == [
        (12, 61, hash_hex(found[0].hash), False, 0, None),
        (63, 130, block, True, 1234, None),
        (142, 225, hash_hex(found[2].hash), False, 0, None),
        (228, 297, block, True, 1234, None),
    ]
    assert WITH_NOTICE[228:297] == f"> {NOTICE}"


def test_paragraphs_carry_the_teams_choice_and_only_applied_blocks_are_cut() -> None:
    shown, found = _shown(WITH_NOTICE)
    first, notice = found[0].hash, found[1].hash
    known = {
        first: body.Known(standard=False, mails=0, override=True),  # marked, not applied yet
        notice: body.Known(standard=True, mails=40, override=False),  # taken back, still applied
    }
    marked = body.with_blocks(shown, found, known)
    assert [s.kind for s in marked.segments] == [
        "text",
        "standard",
        "text",
        "quote",
        "standard",
        "quote",
    ]
    assert [(p.standard, p.mails, p.override) for p in marked.paragraphs] == [
        (False, 0, True),
        (True, 40, False),
        (False, 0, None),
        (True, 40, False),
    ]
    # without blocks the segments stay those of quotes.split_text
    plain = body.with_blocks(shown, found, {})
    assert plain.segments == shown.segments
    assert [p.standard for p in plain.paragraphs] == [False] * 4


def test_a_text_that_is_one_standard_block() -> None:
    shown, found = _shown(f"{NOTICE}\n")
    marked = body.with_blocks(shown, found, {found[0].hash: body.Known(True, 3, None)})
    assert marked.segments == [
        TextSegment(
            kind="standard",
            start=0,
            end=len(NOTICE) + 1,
            lines=1,
            folded=True,
            block=hash_hex(found[0].hash),
        )
    ]
    empty, nothing = _shown("")
    assert nothing == [] and body.with_blocks(empty, nothing, {}).segments == empty.segments

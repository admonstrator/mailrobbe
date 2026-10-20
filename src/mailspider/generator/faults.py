"""Deliberate defects in generated mails (SPEC 3.6) and the byte-level edits behind them.

apply_faults runs in the workers on the rendered, still unsigned mail. Every fault is a small,
targeted edit of the bytes (one header field, one MIME part); the message is never
re-serialised. Signing runs afterwards and covers the damaged bytes, so a faulty signed mail
still verifies as pass unless a later step (sign_mail's in-transit changes) breaks it.

DuplicateInjector runs in the main process on the stream of signed mails.
"""

import base64
import binascii
import functools
import random
import re
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, timedelta
from email.message import Message
from email.parser import BytesHeaderParser
from email.utils import format_datetime

from mailspider.generator.config import GeneratorConfig
from mailspider.generator.model import Fault, RenderedMail, stage_rng

# Variant names as recorded in RenderedMail.faults and the manifest.
FAULT_VARIANTS: dict[Fault, tuple[str, ...]] = {
    Fault.MISSING_MESSAGE_ID: ("removed",),
    Fault.BROKEN_ENCODING: (
        "wrong_charset",
        "raw_8bit_header",
        "broken_encoded_word",
        "invalid_base64",
        "unknown_charset",
    ),
    Fault.BAD_DATE: ("missing", "unparseable", "nonstandard", "two_digit_year"),
    Fault.UNESCAPED_FROM: ("sentence", "separator_like"),
}
DUPLICATE_VARIANTS = ("exact", "same_message_id")

_FAULT_WEIGHTS = {
    Fault.BROKEN_ENCODING: 0.35,
    Fault.MISSING_MESSAGE_ID: 0.25,
    Fault.BAD_DATE: 0.25,
    Fault.UNESCAPED_FROM: 0.15,
}
_SECOND_FAULT_SHARE = 0.1  # faulty mails with two defects of different kinds

_DUPLICATE_BUFFER = 256  # recent mails a duplicate may copy
_DUPLICATE_MAX_SOURCE = 1024**2  # larger mails are never duplicated, which bounds the buffer
_EXACT_DUPLICATE_SHARE = 0.6

_UNKNOWN_CHARSETS = ("x-unknown", "utf-9", "iso-8859-17")
_CHARSET_SWAP = {
    "utf-8": "iso-8859-1",
    "iso-8859-1": "utf-8",
    "iso-8859-15": "utf-8",
    "windows-1252": "utf-8",
}
_FROM_SENTENCES = (
    "From my side everything is ready, we can start on Monday.",
    "From what I understand the deadline moved to the end of the month.",
    "From next week on please send the reports to the new address.",
    "From the minutes it is not clear who takes over the follow-up.",
)
_TEXT_CTES = ("7bit", "8bit", "binary", "quoted-printable")
_BASE64_GARBAGE = b"!#%*~"

_ANY_FROM_LINE = re.compile(rb"^>*From ", re.MULTILINE)
_EIGHT_BIT = re.compile(rb"[\x80-\xff]")
_QP_EIGHT_BIT = re.compile(rb"=[89A-Fa-f][0-9A-Fa-f]")
_CHARSET_PARAM = re.compile(rb'(charset[ \t]*=[ \t]*"?)[^";\s]+', re.IGNORECASE)
_ENCODED_WORD = re.compile(rb"=\?[^?\s]+\?[BbQq]\?[^?\s]*\?=")


# Header and MIME helpers on raw bytes (also used by generator.dkim)


def header_end(raw: bytes, start: int = 0, end: int | None = None) -> int:
    """Offset just past the last header line of the block starting at `start`."""
    stop = len(raw) if end is None else end
    if raw.startswith(b"\n", start):
        return start
    blank = raw.find(b"\n\n", start, stop)
    return stop if blank < 0 else blank + 1


@functools.cache
def _field_pattern(name: str) -> re.Pattern[bytes]:
    return re.compile(
        rb"^" + re.escape(name.encode()) + rb"[ \t]*:[^\n]*\n(?:[ \t][^\n]*\n)*",
        re.IGNORECASE | re.MULTILINE,
    )


def field_span(raw: bytes, name: str, start: int = 0, end: int | None = None) -> tuple[int, int]:
    """Span of the first header field `name`, continuation lines and final LF included.

    Searches the header block starting at `start`; (-1, -1) when the field is absent.
    """
    match = _field_pattern(name).search(raw, start, header_end(raw, start, end))
    return (-1, -1) if match is None else match.span()


def _parse_head(raw: bytes, start: int, end: int) -> Message:
    return BytesHeaderParser().parsebytes(raw[start:end])


@dataclass(frozen=True, slots=True)
class _Part:
    """A leaf MIME part: raw[start:head_end] is its header block, raw[body:end] its body."""

    start: int
    head_end: int
    body: int
    end: int
    content_type: str
    charset: str | None
    cte: str


def _leaf_parts(
    raw: bytes, start: int = 0, end: int | None = None, depth: int = 0
) -> Iterator[_Part]:
    """Leaf parts in document order; message/rfc822 parts count as leaves."""
    stop = len(raw) if end is None else end
    head_end = header_end(raw, start, stop)
    body = min(head_end + 1, stop)
    head = _parse_head(raw, start, head_end)
    content_type = head.get_content_type()
    boundary = head.get_boundary()
    if content_type.startswith("multipart/") and boundary and depth < 10:
        delimiter = re.compile(
            rb"^--" + re.escape(boundary.encode("utf-8", "surrogateescape")) + rb"(--)?[ \t]*$",
            re.MULTILINE,
        )
        part_start: int | None = None
        for match in delimiter.finditer(raw, body, stop):
            if part_start is not None:
                yield from _leaf_parts(
                    raw, part_start, max(part_start, match.start() - 1), depth + 1
                )
            if match.group(1):
                return
            part_start = match.end() + 1
        return
    cte = str(head.get("content-transfer-encoding", "7bit")).strip().lower()
    yield _Part(start, head_end, body, stop, content_type, head.get_content_charset(), cte)


def _replace(raw: bytes, start: int, end: int, new: bytes) -> bytes:
    return raw[:start] + new + raw[end:]


def _set_charset(raw: bytes, part: _Part, charset: str) -> bytes | None:
    start, end = field_span(raw, "Content-Type", part.start, part.head_end)
    if start < 0:
        return None
    field = raw[start:end]
    value = charset.encode()
    if _CHARSET_PARAM.search(field):
        new = _CHARSET_PARAM.sub(lambda match: match.group(1) + value, field, count=1)
    else:
        new = field.rstrip(b"\n") + b'; charset="' + value + b'"\n'
    return _replace(raw, start, end, new)


def _has_8bit_text(raw: bytes, part: _Part) -> bool:
    if part.cte == "base64":
        try:
            return _EIGHT_BIT.search(binascii.a2b_base64(raw[part.body : part.end])) is not None
        except binascii.Error:
            return False
    if part.cte == "quoted-printable":
        return _QP_EIGHT_BIT.search(raw, part.body, part.end) is not None
    return _EIGHT_BIT.search(raw, part.body, part.end) is not None


def tag_subject(raw: bytes, tag: str) -> bytes | None:
    """Insert `tag` and a space in front of the Subject value; None without a Subject."""
    start, _ = field_span(raw, "Subject")
    if start < 0:
        return None
    value = raw.index(b":", start) + 1
    while raw[value : value + 1] in (b" ", b"\t"):
        value += 1
    return raw[:value] + tag.encode() + b" " + raw[value:]


def append_footer(raw: bytes, footer: str) -> bytes | None:
    """Append a plain text footer the way list servers and gateways do, keeping MIME intact.

    Multipart mails get an extra text/plain part before the closing delimiter, text/plain mails
    the footer at the end of the body. None when neither fits (e.g. a base64 text body).
    """
    text = footer.encode("ascii")
    head_end = header_end(raw)
    head = _parse_head(raw, 0, head_end)
    boundary = head.get_boundary()
    if head.get_content_maintype() == "multipart" and boundary:
        closing = re.compile(rb"^--" + re.escape(boundary.encode()) + rb"--[ \t]*$", re.MULTILINE)
        matches = list(closing.finditer(raw, head_end))
        if not matches:
            return None
        part = (
            b"--" + boundary.encode() + b"\nContent-Type: text/plain; charset=us-ascii\n"
            b"Content-Transfer-Encoding: 7bit\nContent-Disposition: inline\n\n" + text + b"\n"
        )
        at = matches[-1].start()
        return _replace(raw, at, at, part)
    cte = str(head.get("content-transfer-encoding", "7bit")).strip().lower()
    if head.get_content_type() != "text/plain" or cte not in _TEXT_CTES or raw.endswith(b"=\n"):
        return None
    body = raw if raw.endswith(b"\n") else raw + b"\n"
    return body + b"\n" + text + b"\n"


# Fault edits: each changes the mail in place and returns False when the mail has no place
# for that defect (the mail is then unchanged).


def _remove_message_id(mail: RenderedMail, rng: random.Random) -> bool:
    start, end = field_span(mail.raw, "Message-ID")
    if start < 0:
        return False
    mail.raw = _replace(mail.raw, start, end, b"")
    mail.message_id = None
    return True


def _set_date(mail: RenderedMail, value: str | None) -> bool:
    start, end = field_span(mail.raw, "Date")
    if start < 0:
        return False
    field = b"" if value is None else b"Date: " + value.encode("ascii") + b"\n"
    mail.raw = _replace(mail.raw, start, end, field)
    return True


def _date_missing(mail: RenderedMail, rng: random.Random) -> bool:
    return _set_date(mail, None)


def _date_unparseable(mail: RenderedMail, rng: random.Random) -> bool:
    year = mail.planned.date.year
    return _set_date(mail, rng.choice(("unknown", "0", f"Mon, 31 Feb {year} 25:61:00 +0100")))


def _date_nonstandard(mail: RenderedMail, rng: random.Random) -> bool:
    date = mail.planned.date
    formats = (
        f"{date:%Y-%m-%d %H:%M}",
        date.isoformat(timespec="seconds"),
        f"{date:%d.%m.%Y %H:%M:%S}",
    )
    return _set_date(mail, rng.choice(formats))


def _date_two_digit_year(mail: RenderedMail, rng: random.Random) -> bool:
    value = format_datetime(mail.planned.date)  # "Mon, 04 Mar 2019 10:22:33 +0100"
    return _set_date(mail, re.sub(r" \d\d(\d\d) ", r" \1 ", value, count=1))


def _insert_from_line(mail: RenderedMail, line: str) -> bool:
    if _ANY_FROM_LINE.search(mail.raw):
        return False  # with escaping off, every other From line would become ambiguous too
    for part in _leaf_parts(mail.raw):
        if part.content_type == "text/plain" and part.cte in _TEXT_CTES:
            paragraph = mail.raw.find(b"\n\n", part.body, part.end)
            at = part.body if paragraph < 0 else paragraph + 2
            mail.raw = _replace(mail.raw, at, at, line.encode() + b"\n\n")
            mail.escape_from_lines = False
            return True
    return False


def _from_sentence(mail: RenderedMail, rng: random.Random) -> bool:
    return _insert_from_line(mail, rng.choice(_FROM_SENTENCES))


def _from_separator(mail: RenderedMail, rng: random.Random) -> bool:
    earlier = mail.planned.date - timedelta(days=rng.randint(1, 400), seconds=rng.randrange(86400))
    # ctime() is locale independent: "Mon Mar  4 09:12:33 2019", as in an mboxo separator
    return _insert_from_line(
        mail, f"From {mail.planned.sender.email} {earlier.astimezone(UTC).ctime()}"
    )


def _wrong_charset(mail: RenderedMail, rng: random.Random) -> bool:
    for part in _leaf_parts(mail.raw):
        swapped = _CHARSET_SWAP.get(part.charset or "")
        if part.content_type.startswith("text/") and swapped and _has_8bit_text(mail.raw, part):
            raw = _set_charset(mail.raw, part, swapped)
            if raw is not None:
                mail.raw = raw
                return True
    return False


def _unknown_charset(mail: RenderedMail, rng: random.Random) -> bool:
    for part in _leaf_parts(mail.raw):
        if part.content_type.startswith("text/"):
            raw = _set_charset(mail.raw, part, rng.choice(_UNKNOWN_CHARSETS))
            if raw is not None:
                mail.raw = raw
                return True
    return False


def _latin1(text: str) -> bytes | None:
    try:
        encoded = text.encode("latin-1")
    except UnicodeEncodeError:
        return None
    return encoded if _EIGHT_BIT.search(encoded) else None


def _raw_8bit_header(mail: RenderedMail, rng: random.Random) -> bool:
    planned = mail.planned
    subject = _latin1(planned.subject)
    name = _latin1(planned.sender.display_name or "")
    if subject is not None:
        header, field = "Subject", b"Subject: " + subject + b"\n"
    elif name is not None:
        if re.search(rb'[(),.:;<>@\[\]"\\]', name):
            name = b'"' + name.replace(b"\\", b"\\\\").replace(b'"', b'\\"') + b'"'
        header, field = "From", b"From: " + name + b" <" + planned.sender.email.encode() + b">\n"
    else:
        return False
    start, end = field_span(mail.raw, header)
    if start < 0:
        return False
    mail.raw = _replace(mail.raw, start, end, field)
    return True


def _broken_encoded_word(mail: RenderedMail, rng: random.Random) -> bool:
    start, end = field_span(mail.raw, "Subject")
    if start < 0:
        return False
    field = mail.raw[start:end]
    words = list(_ENCODED_WORD.finditer(field))
    if not words and not mail.planned.subject:
        return False
    if words and (rng.random() < 0.5 or not mail.planned.subject):
        last = words[-1]
        broken = field[: last.end() - 2] + field[last.end() :]  # closing "?=" lost
    else:
        payload = base64.b64encode(mail.planned.subject.encode())[:-1]  # padding broken
        broken = b"Subject: =?utf-8?b?" + payload + b"?=\n"
    mail.raw = _replace(mail.raw, start, end, broken)
    return True


def _invalid_base64(mail: RenderedMail, rng: random.Random) -> bool:
    raw = mail.raw
    for part in _leaf_parts(raw):
        end = part.end
        while end > part.body and raw[end - 1] in b" \t\r\n":
            end -= 1
        if part.cte != "base64" or end == part.body:
            continue
        last = max(part.body, raw.rfind(b"\n", part.body, end) + 1)  # start of the last line
        start = max(part.body, raw.rfind(b"\n", part.body, (part.body + last) // 2) + 1)
        stop = raw.find(b"\n", start, last)
        if last > part.body and rng.random() < 0.5 and raw[start:stop].strip():
            garbled = bytearray(raw[start:stop])  # garbage characters in a line mid-part
            for position in rng.sample(range(len(garbled)), min(3, len(garbled))):
                garbled[position] = rng.choice(_BASE64_GARBAGE)
            mail.raw = _replace(raw, start, stop, bytes(garbled))
        else:
            line = raw[last:end]  # padding lost, or one character short
            stripped = line.rstrip(b"=")
            mail.raw = _replace(raw, last, end, stripped if stripped != line else line[:-1])
        return True
    return False


_EDITS: dict[tuple[Fault, str], Callable[[RenderedMail, random.Random], bool]] = {
    (Fault.MISSING_MESSAGE_ID, "removed"): _remove_message_id,
    (Fault.BROKEN_ENCODING, "wrong_charset"): _wrong_charset,
    (Fault.BROKEN_ENCODING, "raw_8bit_header"): _raw_8bit_header,
    (Fault.BROKEN_ENCODING, "broken_encoded_word"): _broken_encoded_word,
    (Fault.BROKEN_ENCODING, "invalid_base64"): _invalid_base64,
    (Fault.BROKEN_ENCODING, "unknown_charset"): _unknown_charset,
    (Fault.BAD_DATE, "missing"): _date_missing,
    (Fault.BAD_DATE, "unparseable"): _date_unparseable,
    (Fault.BAD_DATE, "nonstandard"): _date_nonstandard,
    (Fault.BAD_DATE, "two_digit_year"): _date_two_digit_year,
    (Fault.UNESCAPED_FROM, "sentence"): _from_sentence,
    (Fault.UNESCAPED_FROM, "separator_like"): _from_separator,
}


def inject_fault(mail: RenderedMail, fault: Fault, variant: str, rng: random.Random) -> bool:
    """Apply one fault variant and record it; False (mail unchanged) when it does not fit."""
    if not _EDITS[fault, variant](mail, rng):
        return False
    mail.faults[fault] = variant
    return True


def apply_faults(mail: RenderedMail, config: GeneratorConfig, rng: random.Random) -> RenderedMail:
    """Byte-level defects on a rendered, unsigned mail (worker process, before sign_mail).

    About config.fault_rate of the mails get one defect, a tenth of those a second one of
    another kind. A kind with no fitting variant for the mail falls back to another kind.
    """
    if rng.random() >= config.fault_rate:
        return mail
    wanted = 2 if rng.random() < _SECOND_FAULT_SHARE else 1
    kinds = dict(_FAULT_WEIGHTS)
    applied = 0
    while kinds and applied < wanted:
        fault = rng.choices(list(kinds), weights=list(kinds.values()))[0]
        del kinds[fault]
        variants = list(FAULT_VARIANTS[fault])
        rng.shuffle(variants)
        if any(inject_fault(mail, fault, variant, rng) for variant in variants):
            applied += 1
    return mail


class DuplicateInjector:
    """Replaces some stream positions by a copy of a recent mail (main process, bounded memory).

    process() is called once per mail in stream order, after signing and before writing. It
    returns either the mail itself or a duplicate standing in for it, with duplicate_of set and
    Fault.DUPLICATE recorded. Sources come from the last 256 original mails of at most 1 MB;
    duplicates are never copied again. Variants: "exact" repeats the raw bytes, so Message-ID
    and SHA-256 match; "same_message_id" adds one header a mail client or a second delivery
    would add (Status, X-Mozilla-Status, Received), none of them covered by a DKIM signature.
    """

    def __init__(self, config: GeneratorConfig) -> None:
        self._config = config
        self._position = 0
        self._recent: deque[tuple[int, RenderedMail]] = deque(maxlen=_DUPLICATE_BUFFER)

    def process(self, mail: RenderedMail) -> RenderedMail:
        position = self._position
        self._position += 1
        rng = stage_rng(mail.planned.seed, "duplicate")
        if self._recent and rng.random() < self._config.duplicate_rate:
            source_position, source = self._recent[rng.randrange(len(self._recent))]
            return _duplicate(source, source_position, rng)
        if len(mail.raw) <= _DUPLICATE_MAX_SOURCE:
            self._recent.append((position, mail))
        return mail


def _duplicate(source: RenderedMail, source_position: int, rng: random.Random) -> RenderedMail:
    raw = source.raw
    variant = "exact"
    if source.message_id is not None and rng.random() >= _EXACT_DUPLICATE_SHARE:
        variant = "same_message_id"
        raw = _redelivered(source, rng)
    return RenderedMail(
        planned=source.planned,
        raw=raw,
        message_id=source.message_id,
        faults={**source.faults, Fault.DUPLICATE: variant},
        dkim=source.dkim,
        escape_from_lines=source.escape_from_lines,
        duplicate_of=source_position,
    )


def _redelivered(source: RenderedMail, rng: random.Random) -> bytes:
    raw = source.raw
    kind = rng.randrange(3)
    if kind == 0:  # mbox readers append a read flag to the header block
        at = header_end(raw)
        return raw[:at] + b"Status: RO\n" + raw[at:]
    if kind == 1:
        return b"X-Mozilla-Status: 0001\nX-Mozilla-Status2: 00000000\n" + raw
    planned = source.planned
    sender = planned.sender.domain
    receiver = planned.to[0].domain if planned.to else sender
    when = planned.date + timedelta(minutes=rng.randint(2, 2880))
    host = f"mx{rng.randint(1, 4)}.{sender}"
    received = (
        f"Received: from {host} ({host} [203.0.113.{rng.randint(1, 254)}])\n"
        f"\tby mail.{receiver} with ESMTPS id {rng.getrandbits(48):012x};\n"
        f"\t{format_datetime(when)}\n"
    )
    return received.encode() + raw

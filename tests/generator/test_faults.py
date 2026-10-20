import binascii
import codecs
import email.policy
import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

import pytest

from mailrobbe.enums import DkimStatus
from mailrobbe.generator.dkim import sign_mail
from mailrobbe.generator.faults import (
    FAULT_VARIANTS,
    append_footer,
    apply_faults,
    field_span,
    inject_fault,
    tag_subject,
)
from mailrobbe.generator.model import Fault, RenderedMail, stage_rng
from tests.dkim.samples import (
    CONFIG,
    INTERNAL,
    STRUCTURES,
    sample_mail,
    sample_setup,
    sample_stream,
    single_signer,
)
from tests.dkim_check import verify_mail

ALL_VARIANTS = [
    (fault, variant) for fault, variants in FAULT_VARIANTS.items() for variant in variants
]
SEPARATOR = re.compile(
    rb"^From \S+@\S+ (Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
    rb"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d\d:\d\d:\d\d \d{4}$"
)


def parse(raw: bytes) -> EmailMessage:
    """Parse and touch everything an importer reads; none of it may raise."""
    message = BytesParser(policy=email.policy.default).parsebytes(raw)
    assert isinstance(message, EmailMessage)
    for name in ("from", "to", "cc", "subject", "date", "message-id"):
        str(message.get(name, ""))
    for part in message.walk():
        if not part.is_multipart():
            part.get_payload(decode=True)
    return message


def header_value(raw: bytes, name: str) -> bytes:
    start, end = field_span(raw, name)
    assert start >= 0, name
    return raw[start:end].split(b":", 1)[1].strip()


def leaves(raw: bytes) -> list[tuple[str, str | None, object]]:
    message = parse(raw)
    return [
        (part.get_content_type(), part.get_content_charset(), part.get_payload(decode=True))
        for part in message.walk()
        if not part.is_multipart()
    ]


def lines_removed(before: bytes, after: bytes) -> list[bytes]:
    """The lines missing from `after`, provided that is the only difference."""
    old, new = before.split(b"\n"), after.split(b"\n")
    assert all(line in old for line in new)
    return [line for line in old if line not in new]


def check_removed(before: bytes, mail: RenderedMail) -> None:
    assert lines_removed(before, mail.raw) == [b"Message-ID: " + mail.planned.message_id.encode()]
    assert mail.message_id is None and parse(mail.raw)["message-id"] is None


def check_date_missing(before: bytes, mail: RenderedMail) -> None:
    assert len(lines_removed(before, mail.raw)) == 1
    assert parse(mail.raw)["date"] is None


def check_unparseable(before: bytes, mail: RenderedMail) -> None:
    with pytest.raises(ValueError):
        parsedate_to_datetime(header_value(mail.raw, "Date").decode())
    assert parse(mail.raw)["date"].datetime is None


def check_nonstandard(before: bytes, mail: RenderedMail) -> None:
    value = header_value(mail.raw, "Date").decode()
    with pytest.raises(ValueError):
        parsedate_to_datetime(value)
    try:
        recovered = datetime.fromisoformat(value)
    except ValueError:
        recovered = datetime.strptime(value, "%d.%m.%Y %H:%M:%S")
    planned = mail.planned.date
    assert recovered.replace(tzinfo=None, second=0) == planned.replace(tzinfo=None, second=0)


def check_two_digit_year(before: bytes, mail: RenderedMail) -> None:
    value = header_value(mail.raw, "Date").decode()
    assert re.search(r" \d\d \d\d:\d\d:\d\d ", value)
    assert parsedate_to_datetime(value) == mail.planned.date


def check_from_line(before: bytes, mail: RenderedMail) -> None:
    assert mail.escape_from_lines is False
    lines = mail.raw.split(b"\n")
    from_lines = [i for i, line in enumerate(lines) if re.match(rb">*From ", line)]
    assert len(from_lines) == 1 and lines[from_lines[0]].startswith(b"From ")
    assert lines[from_lines[0] - 1] == b"", "starts a paragraph"
    assert lines_removed(mail.raw, before) == [lines[from_lines[0]]]
    line = lines[from_lines[0]]
    if mail.faults[Fault.UNESCAPED_FROM] == "separator_like":
        assert SEPARATOR.match(line) and mail.planned.sender.email.encode() in line
    else:
        assert not SEPARATOR.match(line) and line.endswith(b".")


def check_wrong_charset(before: bytes, mail: RenderedMail) -> None:
    changed = [(a, b) for a, b in zip(leaves(before), leaves(mail.raw), strict=True) if a != b]
    assert len(changed) == 1
    (old_type, old_charset, old_payload), (new_type, new_charset, new_payload) = changed[0]
    assert (old_type, old_payload) == (new_type, new_payload)
    assert {old_charset, new_charset} in ({"utf-8", "iso-8859-1"},)


def check_raw_8bit_header(before: bytes, mail: RenderedMail) -> None:
    subject = header_value(mail.raw, "Subject")
    sender = header_value(mail.raw, "From")
    raw = subject if re.search(rb"[\x80-\xff]", subject) else sender
    assert re.search(rb"[\x80-\xff]", raw) and b"=?" not in raw
    expected = mail.planned.subject if raw is subject else mail.planned.sender.display_name
    assert expected and expected in raw.decode("latin-1")


def check_broken_encoded_word(before: bytes, mail: RenderedMail) -> None:
    subject = header_value(mail.raw, "Subject")
    unterminated = re.search(rb"=\?[^?]+\?[QqBb]\?[^?]*$", subject)
    padding = re.fullmatch(rb"=\?utf-8\?b\?([^?]*)\?=", subject)
    assert unterminated or (padding and len(padding.group(1)) % 4)


def check_invalid_base64(before: bytes, mail: RenderedMail) -> None:
    broken = 0
    for part in parse(mail.raw).walk():
        if part.get("content-transfer-encoding", "").lower() == "base64":
            payload = re.sub(r"\s+", "", str(part.get_payload()))
            try:
                binascii.a2b_base64(payload, strict_mode=True)
            except binascii.Error:
                broken += 1
    assert broken == 1


def check_unknown_charset(before: bytes, mail: RenderedMail) -> None:
    charsets = [charset for _, charset, _ in leaves(mail.raw) if charset]
    unknown = [charset for charset in charsets if _unknown(charset)]
    assert len(unknown) == 1


def _unknown(charset: str) -> bool:
    try:
        codecs.lookup(charset)
    except LookupError:
        return True
    return False


CHECKS: dict[tuple[Fault, str], Callable[[bytes, RenderedMail], None]] = {
    (Fault.MISSING_MESSAGE_ID, "removed"): check_removed,
    (Fault.BAD_DATE, "missing"): check_date_missing,
    (Fault.BAD_DATE, "unparseable"): check_unparseable,
    (Fault.BAD_DATE, "nonstandard"): check_nonstandard,
    (Fault.BAD_DATE, "two_digit_year"): check_two_digit_year,
    (Fault.UNESCAPED_FROM, "sentence"): check_from_line,
    (Fault.UNESCAPED_FROM, "separator_like"): check_from_line,
    (Fault.BROKEN_ENCODING, "wrong_charset"): check_wrong_charset,
    (Fault.BROKEN_ENCODING, "raw_8bit_header"): check_raw_8bit_header,
    (Fault.BROKEN_ENCODING, "broken_encoded_word"): check_broken_encoded_word,
    (Fault.BROKEN_ENCODING, "invalid_base64"): check_invalid_base64,
    (Fault.BROKEN_ENCODING, "unknown_charset"): check_unknown_charset,
}


def test_every_variant_has_a_check() -> None:
    assert set(CHECKS) == set(ALL_VARIANTS)


@pytest.mark.parametrize(("fault", "variant"), ALL_VARIANTS)
def test_variant_produces_exactly_its_defect(fault: Fault, variant: str) -> None:
    applied: set[str] = set()
    for index, structure in enumerate(STRUCTURES * 4):
        mail = sample_mail(index, structure, seed=index)
        before = mail.raw
        if not inject_fault(mail, fault, variant, random.Random(index)):
            assert mail.raw == before and not mail.faults
            continue
        assert mail.faults == {fault: variant}
        parse(mail.raw)
        CHECKS[fault, variant](before, mail)
        applied.add(structure)
    expected = {"invalid_base64": {"plain_base64", "mixed"}}.get(variant, set(STRUCTURES))
    if variant in ("sentence", "separator_like"):
        expected = set(STRUCTURES) - {"plain_base64"}
    assert applied >= expected


def test_unescaped_from_refuses_mails_with_from_lines() -> None:
    mail = sample_mail(0, "plain_8bit")
    mail.raw = mail.raw.replace(b"Viele Gr", b">From the archive\nViele Gr")
    raw = mail.raw
    assert not inject_fault(mail, Fault.UNESCAPED_FROM, "sentence", random.Random(1))
    assert mail.raw == raw and mail.escape_from_lines


def test_apply_faults_rate_and_mix() -> None:
    config = replace(CONFIG, fault_rate=0.2)
    count, faulty, double = 1500, 0, 0
    variants: Counter[tuple[Fault, str]] = Counter()
    for mail in sample_stream(count, seed=6):
        result = apply_faults(mail, config, stage_rng(mail.planned.seed, "faults"))
        faulty += bool(result.faults)
        double += len(result.faults) == 2
        variants.update(result.faults.items())
        if result.faults:
            parse(result.raw)
    assert abs(faulty / count - 0.2) < 0.03
    assert 0.03 < double / faulty < 0.2
    assert set(variants) == set(ALL_VARIANTS)


def test_apply_faults_extremes_and_determinism() -> None:
    mails = list(sample_stream(60, seed=3))
    untouched = replace(CONFIG, fault_rate=0.0)
    for mail in mails:
        raw = mail.raw
        assert apply_faults(mail, untouched, random.Random(1)).raw == raw and not mail.faults
    always = replace(CONFIG, fault_rate=1.0)
    first = [
        apply_faults(replace(m, faults={}), always, random.Random(m.planned.seed)) for m in mails
    ]
    again = [
        apply_faults(replace(m, faults={}), always, random.Random(m.planned.seed)) for m in mails
    ]
    assert all(mail.faults for mail in first)
    assert [(m.raw, m.faults) for m in first] == [(m.raw, m.faults) for m in again]


def test_faulty_mails_still_verify_after_signing() -> None:
    setup = single_signer(sample_setup().keys, INTERNAL)
    table = setup.dns_table()
    for fault, variant in ALL_VARIANTS:
        mail = next(
            mail
            for index in range(20)
            if inject_fault(
                mail := sample_mail(index, "mixed", sender=INTERNAL),
                fault,
                variant,
                random.Random(index),
            )
        )
        signed = sign_mail(mail, setup, stage_rng(mail.planned.seed, "dkim"))
        reason = signed.dkim.signatures[0].reason
        assert signed.dkim.expected is DkimStatus.PASS or reason in (
            "body_modified",
            "header_modified",
        )
        assert verify_mail(signed.raw, table)[0] is signed.dkim.expected


@pytest.mark.parametrize("structure", STRUCTURES)
def test_append_footer_keeps_mime_well_formed(structure: str) -> None:
    mail = sample_mail(2, structure)
    changed = append_footer(mail.raw, "--\nfooter line one\nfooter line two")
    if structure == "plain_base64":
        assert changed is None
        return
    assert changed is not None
    message = parse(changed)
    assert all(not part.defects for part in message.walk())
    texts = [part for part in message.walk() if part.get_content_type() == "text/plain"]
    assert texts[-1].get_content().rstrip().endswith("footer line one\nfooter line two")
    before = [payload for _, _, payload in leaves(mail.raw)]
    after = [payload for _, _, payload in leaves(changed)]
    if structure.startswith("plain"):
        assert isinstance(after[0], bytes) and isinstance(before[0], bytes)
        assert after[0].startswith(before[0])
    else:
        assert after[: len(before)] == before and len(after) == len(before) + 1


def test_tag_subject() -> None:
    mail = sample_mail(5)
    changed = tag_subject(mail.raw, "[team]")
    assert changed is not None
    assert parse(changed)["subject"] == "[team] " + mail.planned.subject
    assert tag_subject(changed, "[team]") is None  # never "[team] [team] ..."
    start, end = field_span(mail.raw, "Subject")
    assert tag_subject(mail.raw[:start] + mail.raw[end:], "[team]") is None
    encoded = b"Subject: =?utf-8?b?W1RlYW1dIEdyw7zDn2U=?=\n"  # "[Team] Grüße"
    assert tag_subject(mail.raw[:start] + encoded + mail.raw[end:], "[team]") is None

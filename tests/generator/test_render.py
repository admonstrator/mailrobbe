import email.policy
import hashlib
import re
from collections import Counter
from email.message import EmailMessage, Message
from email.parser import BytesParser

import pytest

from mailrobbe.generator.model import Fault, MailKind, PlannedMail, RenderedMail
from mailrobbe.generator.render import compose, render

_PARSER = BytesParser(policy=email.policy.default)
RESERVED = (".example", ".test")


def _parse(raw: bytes) -> EmailMessage:
    message = _PARSER.parsebytes(raw)
    assert isinstance(message, EmailMessage)
    return message


def _header_block(raw: bytes) -> bytes:
    return raw.split(b"\n\n", 1)[0] + b"\n"


@pytest.fixture(scope="module")
def parsed(gen_rendered: list[RenderedMail]) -> list[tuple[RenderedMail, EmailMessage]]:
    return [(mail, _parse(mail.raw)) for mail in gen_rendered]


def test_bytes_are_well_formed(gen_rendered: list[RenderedMail]) -> None:
    for mail in gen_rendered:
        raw = mail.raw
        assert b"\r" not in raw
        assert raw.endswith(b"\n")
        head = _header_block(raw)
        assert head.isascii()
        assert head.count(b"\nMessage-ID: ") + head.startswith(b"Message-ID: ") == 1
        assert head.count(b"\nDate: ") + head.startswith(b"Date: ") == 1
        assert max(len(line) for line in raw.split(b"\n")) <= 998
        assert mail.message_id == mail.planned.message_id
        assert mail.escape_from_lines


def test_parses_without_defects(parsed: list[tuple[RenderedMail, EmailMessage]]) -> None:
    for _mail, message in parsed:
        for part in message.walk():
            assert not part.defects, (part.get_content_type(), part.defects)
        for name in ("From", "To", "Cc", "Subject", "Date", "Message-ID"):
            header = message[name]
            if header is not None:
                assert not header.defects, (name, header.defects)
        body = message.get_body(("plain", "html"))
        assert body is not None
        assert isinstance(body, EmailMessage)
        body.get_content()


def test_headers_match_the_plan(parsed: list[tuple[RenderedMail, EmailMessage]]) -> None:
    agents: Counter[str | None] = Counter()
    for mail, message in parsed:
        planned = mail.planned
        assert message["Message-ID"] == planned.message_id
        assert message["Subject"] == planned.subject
        assert message["Date"].datetime == planned.date
        assert message["MIME-Version"] == "1.0"
        assert message.get_all("Received")
        sender = message["From"].addresses[0]
        assert sender.addr_spec == planned.sender.email
        assert (sender.display_name or None) == planned.sender.display_name
        for name, planned_addresses in (
            ("To", planned.to),
            ("Cc", planned.cc),
            ("Bcc", planned.bcc),
        ):
            header = message[name]
            if planned_addresses:
                assert [a.addr_spec for a in header.addresses] == [
                    a.email for a in planned_addresses
                ]
            elif name != "To":
                assert header is None
        if not planned.to:
            assert str(message["To"]).startswith("undisclosed-recipients")
        assert message["In-Reply-To"] == planned.in_reply_to
        if planned.references:
            assert message["References"].split() == list(planned.references)
        if planned.list_id:
            assert f"<{planned.list_id}>" in message["List-Id"]
            assert message["List-Unsubscribe"]
            assert message["Precedence"] in ("list", "bulk")
        agents[message["User-Agent"] or message["X-Mailer"]] += 1
    assert len(agents) >= 8  # varied mail programs, some writing no such header


def test_received_hosts_are_reserved(parsed: list[tuple[RenderedMail, EmailMessage]]) -> None:
    for _mail, message in parsed:
        for received in message.get_all("Received") or []:
            hosts = re.findall(r"(?:from|by) ([^\s(;]+)", str(received))
            assert hosts
            for host in hosts:
                assert host == "localhost" or host.startswith("[") or host.endswith(RESERVED), host


def test_attachments_as_planned(parsed: list[tuple[RenderedMail, EmailMessage]]) -> None:
    """Every planned attachment is in the mail, and RenderedMail.documents states each in
    document order with its decoded size and SHA-256; filler keeps its planned size."""
    with_files = with_documents = 0
    for mail, message in parsed:
        files = [part for part in message.walk() if part.get_filename()]
        planned = mail.planned.attachments
        assert sorted(part.get_filename() or "" for part in files) == sorted(
            a.filename for a in planned
        )
        assert [part.get_filename() for part in files] == [t.filename for t in mail.documents]
        for part, truth in zip(files, mail.documents, strict=True):
            payload = part.get_payload(decode=True)
            assert isinstance(payload, bytes)
            assert (len(payload), hashlib.sha256(payload).hexdigest()) == (truth.size, truth.sha256)
        by_name = {t.filename: t for t in mail.documents}
        for spec in planned:
            if spec.document is None:
                assert by_name[spec.filename].size == spec.size
        with_files += bool(files)
        with_documents += any(spec.document is not None for spec in planned)
    assert with_files > 0.08 * len(parsed)
    assert with_documents > 0.8 * with_files


def test_large_attachment(parsed: list[tuple[RenderedMail, EmailMessage]]) -> None:
    large = [(mail, message) for mail, message in parsed if mail.planned.large_attachment]
    assert large
    for mail, message in large:
        spec = mail.planned.attachments[-1]
        assert mail.faults[Fault.LARGE_ATTACHMENT] == spec.mime_type
        part = next(p for p in message.walk() if p.get_filename() == spec.filename)
        payload = part.get_payload(decode=True)
        assert isinstance(payload, bytes) and len(payload) == spec.size
    others = [mail for mail, _ in parsed if not mail.planned.large_attachment]
    assert all(Fault.LARGE_ATTACHMENT not in mail.faults for mail in others)


def test_structures_charsets_and_encodings_vary(
    parsed: list[tuple[RenderedMail, EmailMessage]],
) -> None:
    types: Counter[str] = Counter()
    encodings: Counter[str] = Counter()
    charsets: Counter[str] = Counter()
    for _mail, message in parsed:
        types[message.get_content_type()] += 1
        for part in message.walk():
            if part.is_multipart():
                continue
            encodings[str(part.get("Content-Transfer-Encoding", "7bit")).lower()] += 1
            if part.get_content_maintype() == "text":
                charsets[part.get_content_charset() or "us-ascii"] += 1
    assert {"text/plain", "multipart/alternative", "multipart/mixed"} <= set(types)
    assert {"7bit", "8bit", "quoted-printable", "base64"} <= set(encodings)
    assert charsets["utf-8"] > sum(charsets.values()) / 2
    assert charsets["iso-8859-1"] + charsets["windows-1252"] > 0


def test_old_charsets_only_in_older_years(parsed: list[tuple[RenderedMail, EmailMessage]]) -> None:
    for mail, message in parsed:
        for part in message.walk():
            if part.get_content_charset() in ("iso-8859-1", "windows-1252"):
                assert mail.planned.date.year < 2016


def test_nested_structures(
    parsed: list[tuple[RenderedMail, EmailMessage]], gen_plan: list[PlannedMail]
) -> None:
    forwards = [render(m) for m in gen_plan if m.kind is MailKind.FORWARD]
    variants: Counter[str] = Counter()
    for mail, message in [*parsed, *((m, _parse(m.raw)) for m in forwards)]:
        variant = mail.faults.get(Fault.NESTED_MIME)
        if variant is None:
            continue
        variants[variant] += 1
        if variant == "message_rfc822":
            inner = next(p for p in message.walk() if p.get_content_type() == "message/rfc822")
            forwarded = inner.get_payload(0)
            assert isinstance(forwarded, EmailMessage)
            assert forwarded["Message-ID"] == mail.planned.quoted.message_id  # type: ignore[union-attr]
            assert not any(part.defects for part in forwarded.walk())
        else:
            assert variant.startswith("depth_") and int(variant[6:]) >= 3
            assert _depth(message) == int(variant[6:])
    assert variants["message_rfc822"] and variants["depth_3"]


def _depth(message: Message) -> int:
    if not message.is_multipart():
        return 0
    parts = message.get_payload()
    assert isinstance(parts, list)
    return 1 + max(_depth(part) for part in parts if isinstance(part, Message))


def test_replies_quote_the_parent(gen_rendered: list[RenderedMail]) -> None:
    replies = [
        mail
        for mail in gen_rendered
        if mail.planned.kind is MailKind.REPLY and mail.planned.calendar is None
    ]  # an answer to an invitation quotes nothing
    assert replies
    for mail in replies:
        parent = mail.planned.quoted
        assert parent is not None
        text = mail.raw.decode("utf-8", "replace")
        markers = (
            "schrieb",
            "wrote:",
            "Von:",
            "From:",
            "-----",
            "________________________________",
        )
        assert any(marker in text for marker in markers)
    quoted = [m for m in replies if b"\n> " in m.raw]
    assert quoted  # classic "> " quoting


def test_compose_is_pure(gen_plan: list[PlannedMail]) -> None:
    for mail in gen_plan[:200]:
        assert compose(mail) == compose(mail)
        assert render(mail).raw == render(mail).raw


def test_newsletters_look_like_bulk_mail(parsed: list[tuple[RenderedMail, EmailMessage]]) -> None:
    newsletters = [(m, msg) for m, msg in parsed if m.planned.kind is MailKind.NEWSLETTER]
    assert newsletters
    for _mail, message in newsletters:
        assert message["Precedence"] == "bulk"
        assert message["List-Unsubscribe"]

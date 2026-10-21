"""Render a PlannedMail as RFC 5322 bytes (SPEC 3.6).

Headers and MIME parts are assembled by hand: several times faster than email.generator, and in
full control of what real clients do (folding, encoded words, boundaries, preambles, quoting).
Every message has LF line endings, ASCII-only headers, exactly one Message-ID and one Date line
in its header block, and parses without defects with email.policy.default.

Attachments are the parts that carry a file name; a forwarded message/rfc822 part has none.
Documents (PDF, office files, CSV, text, calendar, vCard, ZIP, pictures, recordings) are real
files built by generator.documents; the very large attachments are periodic blocks of seeded
random bytes behind a plausible magic number, base64-encoded block by block, so they cost
almost nothing. RenderedMail.documents is the ground truth of every attachment, in the order
importer.parse.mime_parts finds them.
"""

import base64
import binascii
import hashlib
import html
import random
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from functools import lru_cache

from mailrobbe.generator import documents
from mailrobbe.generator import vocabulary as vocab
from mailrobbe.generator.model import (
    Address,
    AttachmentSpec,
    DocumentTruth,
    Fault,
    MailKind,
    PlannedMail,
    RenderedMail,
    stage_rng,
)
from mailrobbe.generator.planner import format_date, subject_core
from mailrobbe.generator.population import brand, is_freemail, org_name, utc_offset

RFC822_FORWARD_SHARE = 0.3  # forwards that attach the original as message/rfc822
_AUTOMATED = (MailKind.NEWSLETTER, MailKind.NOTIFICATION, MailKind.INVOICE)


def render(planned: PlannedMail) -> RenderedMail:
    rng = stage_rng(planned.seed, "render")
    style = _STYLES.get(planned.client, _STYLES["webmail"])
    charset = _charset(planned, rng)
    root = _structure(planned, style, charset, rng)
    chunks = [_headers(planned, style, charset, rng).encode("ascii")]
    _emit(root, chunks)
    faults: dict[Fault, str] = {}
    if planned.large_attachment and planned.attachments:
        faults[Fault.LARGE_ATTACHMENT] = planned.attachments[-1].mime_type
    if _has_message(root):
        faults[Fault.NESTED_MIME] = "message_rfc822"
    elif (depth := _depth(root)) >= 3:
        faults[Fault.NESTED_MIME] = f"depth_{depth}"
    rendered = RenderedMail(planned, b"".join(chunks), planned.message_id, faults)
    # mime_parts order: inline pictures sit in the body (multipart/related), files follow it,
    # directly or inside a forwarded message/rfc822
    ordered = sorted(planned.attachments, key=lambda spec: not spec.inline)
    rendered.documents = [_truth(spec) for spec in ordered]
    return rendered


def _truth(spec: AttachmentSpec) -> DocumentTruth:
    if spec.document is not None:
        return documents.build(spec).truth(spec.filename, spec.mime_type)
    return documents.filler_truth(spec, _payload_sha256(spec))


# Mail programs ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Style:
    html_share: float  # share of mails with an HTML alternative
    words: str  # RFC 2047 encoding in headers: "B" or "Q"
    upper_charset: bool  # writes UTF-8 instead of utf-8
    eight_bit: bool  # sends non-ASCII plain text as 8bit instead of quoted-printable
    outlook_quote: bool  # quotes below a header block instead of with "> " lines
    preamble: bool  # "This is a multi-part message in MIME format."
    fold: str  # continuation of folded MIME headers
    base64_html: float  # share of HTML parts sent as base64


_STYLES = {
    "outlook": _Style(0.85, "B", False, False, True, True, "\n\t", 0.0),
    "thunderbird": _Style(0.3, "B", True, True, False, True, "\n ", 0.0),
    "apple": _Style(0.7, "Q", False, False, False, False, "\n\t", 0.0),
    "webmail": _Style(0.6, "Q", True, True, False, False, "\n ", 0.2),
    "mobile": _Style(0.4, "B", False, True, False, False, "\n ", 0.3),
    "bulk": _Style(1.0, "Q", False, False, False, False, "\n ", 0.25),
    "system": _Style(0.3, "B", True, False, False, False, "\n ", 0.1),
}


def _charset(planned: PlannedMail, rng: random.Random) -> str:
    """Mostly UTF-8; older mails from some programs still use the Western 8-bit charsets."""
    if planned.date.year < 2016:
        if planned.client == "outlook" and rng.random() < 0.5:
            return "windows-1252"
        if planned.client in ("thunderbird", "webmail", "system") and rng.random() < 0.4:
            return "iso-8859-1"
    return "utf-8"


def _label(charset: str, style: _Style) -> str:
    return charset.upper() if style.upper_charset else charset


_THUNDERBIRD = ("17.0", "31.0", "45.0", "60.0", "78.0", "102.0", "115.0", "140.0")
_PLATFORMS = (
    "Windows NT 10.0; Win64; x64; rv:{rv}",
    "Macintosh; Intel Mac OS X 10.15; rv:{rv}",
    "X11; Linux x86_64; rv:{rv}",
)
_APPLE = ("2.1499", "2.2104", "2.3445.104.11", "2.3654.120.0.1.13", "2.3774.500.171.1.1")


def _agent(planned: PlannedMail) -> tuple[str, str] | None:
    """User-Agent or X-Mailer header of the program, with a version that fits the year."""
    year = planned.date.year
    key = zlib.crc32(planned.sender.email.encode())
    match planned.client:
        case "outlook":
            if year >= 2019 and key % 2:
                return None  # Exchange Online no longer writes one
            version = "14.0" if year < 2014 else "15.0" if year < 2017 else "16.0"
            return "X-Mailer", f"Microsoft Outlook {version}"
        case "thunderbird":
            version = _THUNDERBIRD[min(len(_THUNDERBIRD) - 1, max(0, (year - 2012) // 2))]
            platform = _PLATFORMS[key % len(_PLATFORMS)].format(rv=version)
            return "User-Agent", f"Mozilla/5.0 ({platform}) Gecko/20100101 Thunderbird/{version}"
        case "apple":
            return "X-Mailer", f"Apple Mail ({_APPLE[min(4, max(0, (year - 2012) // 3))]})"
        case "mobile":
            return ("X-Mailer", "iPhone Mail (16D57)") if key % 3 == 0 else None
        case "webmail":
            if is_freemail(planned.sender.domain):
                return "X-Mailer", f"{brand(planned.sender.domain)} Webmail 3.{key % 9}"
            return "User-Agent", f"Roundcube Webmail/1.{min(6, max(0, year - 2017))}.{key % 12}"
        case "bulk":
            return "X-Mailer", f"Newsletter-System 4.{key % 10}"
        case "system":
            return ("X-Mailer", f"PHPMailer 6.{key % 9}.{key % 4}") if key % 2 else None
    return None


# Text ------------------------------------------------------------------------------------


@dataclass(slots=True)
class Text:
    """The own words of a mail, without quotes: what a reply to it quotes back."""

    greeting: str | None
    paragraphs: list[str]
    closing: list[str]
    signature: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (label, URL)

    def lines(self, delimiter: bool) -> list[str]:
        out: list[str] = []
        if self.greeting:
            out += [self.greeting, ""]
        for paragraph in self.paragraphs:
            out += [*_wrap(paragraph), ""]
        if self.links:
            out += [*(f"{label}: {url}" for label, url in self.links), ""]
        out += self.closing
        if self.signature:
            out += ["", "-- "] if delimiter else [""]
            out += self.signature
        return out


_ROLE_WORDS = frozenset({label for _, label in vocab.ROLE_MAILBOXES} | {"Team", "Alle"})
_LEGAL_WORDS = frozenset(
    word for form in (*vocab.LEGAL_FORMS_DE, *vocab.LEGAL_FORMS_EN) for word in form.split()
)
_TITLES = frozenset(vocab.ACADEMIC_TITLES) | {"Prof."}


def person_names(address: Address | None) -> tuple[str, str] | None:
    """(first name, full name) behind a display name; None for roles and bare addresses."""
    if address is None or not address.display_name:
        return None
    name = address.display_name
    if "@" in name or (" " not in name and "." in name):
        return None  # the local part shown as a name
    name = name.split(" (")[0]
    if ", " in name:
        last, _, first = name.partition(", ")
        name = f"{first} {last}"
    parts = [part for part in name.split() if part not in _TITLES]
    if not parts or parts[0] in _ROLE_WORDS or parts[-1] in _LEGAL_WORDS:
        return None
    return parts[0], " ".join(parts)


def compose(mail: PlannedMail) -> Text:
    """Own text of a mail. A pure function of the plan, so a reply can quote it exactly."""
    rng = stage_rng(mail.seed, "render-text")
    german = mail.language == "de"
    slots = _slots(mail, rng, german)
    if mail.kind in _AUTOMATED:
        return _automated_text(mail, rng, german, slots)

    recipient = mail.to[0] if len(mail.to) == 1 and not mail.list_id else None
    names = person_names(recipient)
    colleague = recipient is not None and recipient.domain == mail.sender.domain
    greeting: str | None = None
    if mail.list_id or len(mail.to) > 1:
        greeting = "Hallo zusammen," if german else "Hi all,"
    elif recipient is not None and names is None:
        if german and recipient.display_name is None and not colleague:
            greeting = "Sehr geehrte Damen und Herren,"
        else:
            greeting = "Guten Tag," if german else "Hello,"
    elif names is not None and (colleague or rng.random() < 0.5):
        greeting = f"{'Hallo' if german else 'Hi'} {names[0]},"
        colleague = True  # first names: the rest of the mail is informal too
    elif names is not None:
        greeting = f"Guten Tag {names[1]}," if german else f"Dear {names[0]},"

    topic = _topic(mail.subject, german)
    if topic is None:
        sentences = ["wie besprochen hier die Infos." if german else "as discussed, the details."]
        replies = ["danke für die Nachricht." if german else "thanks for your message."]
    else:
        sentences, replies = list(topic[0].body), list(topic[0].reply)
        slots["arg"] = topic[1]
    if mail.kind is MailKind.REPLY and len(mail.references) > 1:  # a later answer
        later = vocab.FOLLOW_UPS_DE if german else vocab.FOLLOW_UPS_EN
        chosen = [later[i] for i in sorted(rng.sample(range(len(later)), rng.randint(1, 2)))]
    elif mail.kind is MailKind.REPLY:
        picked = sorted(rng.sample(range(len(replies)), min(len(replies), rng.randint(1, 2))))
        chosen = [replies[i] for i in picked]
    elif mail.kind is MailKind.FORWARD:
        intros: tuple[str, ...] = vocab.FORWARD_INTROS_EN
        if german:
            intros = vocab.FORWARD_INTROS_DE if colleague else vocab.FORWARD_INTROS_DE_FORMAL
        chosen = [rng.choice(intros)]
    else:  # the opening sentence, then some of the others in their order
        count = rng.randint(min(1, len(sentences) - 1), len(sentences) - 1)
        chosen = [
            sentences[0],
            *(sentences[i] for i in sorted(rng.sample(range(1, len(sentences)), count))),
        ]
    files = [a.filename for a in mail.attachments if not a.inline]
    if files and mail.kind is not MailKind.FORWARD and rng.random() < 0.6:
        team = all(a.domain == mail.sender.domain for a in (*mail.to, *mail.cc))
        you = "findest du" if colleague else "finden Sie"
        if mail.list_id or len(mail.to) > 1:
            you = "findet ihr" if team else "finden Sie"
        chosen.append(f"Im Anhang {you} {files[0]}." if german else f"I have attached {files[0]}.")
    filled = [sentence.format(**slots) for sentence in chosen]
    for i, sentence in enumerate(filled):  # lower case only right after a German greeting
        if i > 0 or greeting is None or not german:
            filled[i] = sentence[:1].upper() + sentence[1:]

    sender = person_names(mail.sender)
    if german:
        word = rng.choice(vocab.CLOSINGS_DE_INFORMAL if colleague else vocab.CLOSINGS_DE_FORMAL)
    else:
        word = rng.choice(vocab.CLOSINGS_EN)
    closing = [word]
    signature = _signature(mail, sender, german)
    signed = bool(signature) and sender is not None and signature[0] == sender[1]
    if sender and (colleague or not signed):  # no full name twice above the signature
        closing.append(sender[0] if colleague or signed or rng.random() < 0.4 else sender[1])
    return Text(greeting, _paragraphs(filled, rng), closing, signature)


def _paragraphs(sentences: list[str], rng: random.Random) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        current.append(sentence)
        if len(current) >= 2 and rng.random() < 0.5:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _topic(subject: str, german: bool) -> tuple[vocab.Topic, str] | None:
    """The topic a subject was made from, and its argument."""
    core = subject_core(subject)
    for topic in vocab.TOPICS_DE if german else vocab.TOPICS_EN:
        prefix, suffix = topic.affixes
        if core.startswith(prefix) and core.endswith(suffix):
            return topic, core[len(prefix) : len(core) - len(suffix)]
    return None


def _slots(mail: PlannedMail, rng: random.Random, german: bool) -> dict[str, object]:
    later = mail.date.date() + timedelta(days=rng.randint(2, 30))
    months = vocab.MONTHS_DE if german else vocab.MONTHS_EN
    return {
        "amount": _money(rng.uniform(80, 25_000), german),
        "bill": _money(rng.lognormvariate(4.0, 0.7), german),  # around 55 EUR
        "threshold": rng.choice(("19", "29", "39", "49", "50", "69", "75")),
        "arg": "",
        "weekday": (vocab.WEEKDAYS_DE if german else vocab.WEEKDAYS_EN)[rng.randrange(5)],
        "time": f"{rng.choice((8, 9, 10, 11, 13, 14, 15, 16))}:{rng.choice(('00', '15', '30'))}",
        "date": format_date(later, german),
        "past": format_date(mail.date.date() - timedelta(days=rng.randint(1, 9)), german),
        "n": rng.randint(2, 12),
        "pct": rng.choice((3, 5, 8, 10, 12, 15, 20, 30)),
        "month": months[(mail.date.month + rng.randint(0, 2)) % 12],
        "city": rng.choice(vocab.CITIES_DE),
        "dept": rng.choice(vocab.DEPARTMENTS),
        "season": (vocab.SEASONS_DE if german else vocab.SEASONS_EN)[mail.date.month % 12 // 3],
    }


def _money(value: float, german: bool) -> str:
    text = f"{value:,.2f}"
    return text.replace(",", " ").replace(".", ",").replace(" ", ".") if german else text


def _signature(mail: PlannedMail, names: tuple[str, str] | None, german: bool) -> list[str]:
    """Signature block; the same for every mail from one address."""
    sig = random.Random(f"signature:{mail.sender.email}")
    if mail.client == "mobile":
        return ["Von meinem Smartphone gesendet" if german else "Sent from my phone"]
    organisation = org_name(mail.sender.domain)
    if organisation is None:  # private mailbox: at most the name
        return [names[1]] if names and sig.random() < 0.3 else []
    if sig.random() < 0.15:
        return []
    phone = f"{sig.choice(vocab.PHONE_PREFIXES)}-{sig.randint(100, 999)}"
    lines = [names[1], sig.choice(vocab.DEPARTMENTS)] if names else []
    lines += [organisation, f"Tel. {phone}" if german else f"Phone {phone}"]
    lines.append(f"www.{mail.sender.domain}")
    if german and sig.random() < 0.4:
        city = sig.choice(vocab.CITIES_DE)
        lines += [
            "",
            f"Sitz der Gesellschaft: {city}, Amtsgericht {city} HRB {sig.randint(1000, 99999)}",
        ]
    return lines


def _automated_text(
    mail: PlannedMail, rng: random.Random, german: bool, slots: dict[str, object]
) -> Text:
    slots["n"] = rng.randint(100_000, 9_999_999)
    names = person_names(mail.to[0]) if mail.to else None
    company = org_name(mail.sender.domain) or brand(mail.sender.domain)
    host = mail.sender.domain
    links: list[tuple[str, str]] = []
    greeting: str | None = None
    pool: tuple[str, ...]
    if mail.kind is MailKind.NEWSLETTER:
        pool = vocab.NEWSLETTER_LINES_DE if german else vocab.NEWSLETTER_LINES_EN
        if names:
            greeting = f"Hallo {names[0]}," if german else f"Hi {names[0]},"
        token = f"{rng.getrandbits(48):012x}"
        links = [
            ("Zu den Angeboten" if german else "Offers", f"https://{host}/angebote?c={token}"),
            ("Abmelden" if german else "Unsubscribe", f"https://{host}/abmelden?u={token}"),
        ]
    elif mail.kind is MailKind.INVOICE:
        pool = vocab.INVOICE_LINES_DE if german else vocab.INVOICE_LINES_EN
        greeting = "Sehr geehrte Kundin, sehr geehrter Kunde," if german else "Dear customer,"
    else:
        pool = vocab.NOTIFICATION_LINES_DE if german else vocab.NOTIFICATION_LINES_EN
        if names:
            greeting = f"Hallo {names[0]}," if german else f"Hello {names[0]},"
    count = rng.randint(min(2, len(pool)), len(pool))
    lines = [pool[i].format(**slots) for i in sorted(rng.sample(range(len(pool)), count))]
    if greeting is None:
        lines[0] = lines[0][:1].upper() + lines[0][1:]
    closing = [f"Ihr Team von {company}" if german else f"Your {company} team"]
    footer = [company, f"{rng.choice(vocab.CITIES_DE)} | https://{host}/impressum"]
    return Text(greeting, _paragraphs(lines, rng), closing, footer, links)


def _wrap(text: str, width: int = 72) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for word in text.split():
        if current and length + 1 + len(word) > width:
            lines.append(" ".join(current))
            current, length = [word], len(word)
        else:
            length += len(word) + (1 if current else 0)
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


# Quotes and forwards ---------------------------------------------------------------------

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _display(address: Address) -> str:
    return f"{address.display_name} <{address.email}>" if address.display_name else address.email


def _clock_12h(d: datetime) -> str:
    return f"{(d.hour - 1) % 12 + 1}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def _attribution(parent: PlannedMail, client: str, german: bool) -> str:
    """The line above a quote, for example 'Am 04.03.2019 um 09:12 schrieb Max Müller:'."""
    d = parent.date
    who = parent.sender.display_name or parent.sender.email
    hm = f"{d.hour:02d}:{d.minute:02d}"
    if german and client == "thunderbird":
        return f"Am {d.day:02d}.{d.month:02d}.{d.year % 100:02d} um {hm} schrieb {who}:"
    if german and client == "webmail":
        return f"Am {d.day:02d}.{d.month:02d}.{d.year} {hm}, schrieb {who}:"
    if german:
        return f"Am {d.day:02d}.{d.month:02d}.{d.year} um {hm} schrieb {_display(parent.sender)}:"
    if client == "thunderbird":
        return f"On {d.month}/{d.day}/{d.year % 100} {_clock_12h(d)}, {who} wrote:"
    day = f"{_DAYS[d.weekday()]}, {_MONTHS[d.month - 1]} {d.day}, {d.year}"
    return f"On {day} at {hm}, {_display(parent.sender)} wrote:"


def _long_date(d: datetime, german: bool) -> str:
    if german:
        day = f"{vocab.WEEKDAYS_DE[d.weekday()]}, {d.day}. {vocab.MONTHS_DE[d.month - 1]}"
        return f"{day} {d.year} {d.hour:02d}:{d.minute:02d}"
    month = vocab.MONTHS_EN[d.month - 1]
    return f"{vocab.WEEKDAYS_EN[d.weekday()]}, {month} {d.day}, {d.year} {_clock_12h(d)}"


def _outlook_block(parent: PlannedMail, mail: PlannedMail, german: bool) -> list[str]:
    """Outlook's header block above quoted or forwarded text."""
    if mail.date.year >= 2016:
        rule = "_" * 32
    else:
        rule = "-----Ursprüngliche Nachricht-----" if german else "-----Original Message-----"
    names = (
        ("Von", "Gesendet", "An", "Cc", "Betreff")
        if german
        else ("From", "Sent", "To", "Cc", "Subject")
    )
    lines = [
        rule,
        f"{names[0]}: {_display(parent.sender)}",
        f"{names[1]}: {_long_date(parent.date, german)}",
    ]
    if parent.to:
        lines.append(f"{names[2]}: {'; '.join(_display(a) for a in parent.to)}")
    if parent.cc:
        lines.append(f"{names[3]}: {'; '.join(_display(a) for a in parent.cc)}")
    return [*lines, f"{names[4]}: {parent.subject}", ""]


def _forward_block(parent: PlannedMail, mail: PlannedMail, german: bool) -> list[str]:
    if mail.client == "outlook":
        return _outlook_block(parent, mail, german)
    sender = _display(parent.sender)
    date = _long_date(parent.date, german)
    to = ", ".join(_display(a) for a in parent.to)
    if mail.client == "apple":
        head = "Anfang der weitergeleiteten Nachricht:" if german else "Begin forwarded message:"
        names = ("Von", "Betreff", "Datum", "An") if german else ("From", "Subject", "Date", "To")
        values = (sender, parent.subject, date, to)
        return [head, "", *(f"{n}: {v}" for n, v in zip(names, values, strict=True)), ""]
    dashes = "--------" if mail.client == "thunderbird" else "----------"
    head = "Weitergeleitete Nachricht" if german else "Forwarded Message"
    names = ("Betreff", "Datum", "Von", "An") if german else ("Subject", "Date", "From", "To")
    values = (parent.subject, date, sender, to)
    return [
        f"{dashes} {head} {dashes}",
        *(f"{n}: {v}" for n, v in zip(names, values, strict=True)),
        "",
    ]


def _forwards_as_message(mail: PlannedMail) -> bool:
    if mail.kind is not MailKind.FORWARD or mail.quoted is None:
        return False
    return stage_rng(mail.seed, "render-forward").random() < RFC822_FORWARD_SHARE


# MIME tree -------------------------------------------------------------------------------


@dataclass(slots=True)
class _Leaf:
    headers: str  # MIME header lines, each ending with "\n"
    body: Sequence[bytes]  # transfer-encoded, ends with "\n"


@dataclass(slots=True)
class _Multi:
    subtype: str
    boundary: str
    parts: list["_Node"]
    preamble: bool = False


@dataclass(slots=True)
class _Message:
    """A message/rfc822 part: an attached copy of another mail."""

    headers: str
    node: "_Node"


_Node = _Leaf | _Multi | _Message


def _emit(node: _Node, out: list[bytes]) -> None:
    """Append the MIME headers, the blank line and the body of `node` to `out`."""
    if isinstance(node, _Leaf):
        out += (node.headers.encode("ascii"), b"\n", *node.body)
    elif isinstance(node, _Multi):
        head = f'Content-Type: multipart/{node.subtype};\n\tboundary="{node.boundary}"\n\n'
        out.append(head.encode("ascii"))
        if node.preamble:
            out.append(b"This is a multi-part message in MIME format.\n")
        delimiter = f"--{node.boundary}\n".encode("ascii")
        for part in node.parts:
            out.append(delimiter)
            _emit(part, out)
        out.append(f"--{node.boundary}--\n".encode("ascii"))
    else:
        out.append(b"Content-Type: message/rfc822\nContent-Disposition: inline\n\n")
        out.append(node.headers.encode("ascii"))
        _emit(node.node, out)


def _depth(node: _Node) -> int:
    """Number of nested multipart levels on the deepest path."""
    if isinstance(node, _Multi):
        return 1 + max(_depth(part) for part in node.parts)
    if isinstance(node, _Message):
        return _depth(node.node)
    return 0


def _has_message(node: _Node) -> bool:
    if isinstance(node, _Multi):
        return any(_has_message(part) for part in node.parts)
    return isinstance(node, _Message)


_ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _boundary(client: str, rng: random.Random) -> str:
    bits = rng.getrandbits
    match client:
        case "outlook":
            return f"_{bits(8):03d}_EX{bits(4) + 1:02d}MB{bits(64):016X}_"
        case "thunderbird":
            return "------------" + "".join(rng.choice(_ALNUM) for _ in range(24))
        case "apple" | "mobile":
            text = f"{bits(128):032X}"
            return f"Apple-Mail={text[:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:]}"
        case "bulk":
            return f"----=_Part_{bits(20)}_{bits(30)}.{bits(40)}"
        case "system":
            return f"b1_{bits(128):032x}"
    return f"=_{bits(128):032x}"


def _text_leaf(
    text: str,
    subtype: str,
    charset: str,
    style: _Style,
    rng: random.Random,
    params: str = "",
) -> _Leaf:
    try:
        text.encode(charset)
    except UnicodeEncodeError:
        charset = "utf-8"  # the text has characters the older charset cannot hold
    label = _label(charset, style)
    data = (
        text.replace("CHARSET", label).encode(charset)
        if subtype == "html"
        else text.encode(charset)
    )
    if data.isascii() and subtype == "plain":
        encoding, body = "7bit", data
    elif rng.random() < (style.base64_html if subtype == "html" else 0.04):
        encoding, body = "base64", base64.encodebytes(data)
    elif style.eight_bit and subtype == "plain":
        encoding, body = "8bit", data
    else:
        encoding, body = "quoted-printable", binascii.b2a_qp(data)
    headers = (
        f'Content-Type: text/{subtype}; charset="{label}"{params}\n'
        f"Content-Transfer-Encoding: {encoding}\n"
    )
    return _Leaf(headers, (body,))


def _param(name: str, value: str, style: _Style) -> str:
    """A MIME parameter; a non-ASCII value in RFC 2231 form."""
    if value.isascii():
        return f'{name}="{value}"'
    encoded = "".join(
        chr(byte) if chr(byte) in _ALNUM or chr(byte) in "._-" else f"%{byte:02X}"
        for byte in value.encode()
    )
    return f"{name}*={_label('utf-8', style)}''{encoded}"


def _attachment_leaf(spec: AttachmentSpec, style: _Style, cid: str | None = None) -> _Leaf:
    lines = [
        f"Content-Type: {spec.mime_type};{style.fold}{_param('name', spec.filename, style)}",
        "Content-Transfer-Encoding: base64",
    ]
    if cid:
        lines.append(f"Content-ID: <{cid}>")
    disposition = "inline" if spec.inline else "attachment"
    lines.append(
        f"Content-Disposition: {disposition};{style.fold}{_param('filename', spec.filename, style)}"
    )
    if spec.document is not None:
        return _Leaf("\n".join(lines) + "\n", documents.build(spec).encoded)
    return _Leaf("\n".join(lines) + "\n", _encoded_payload(spec))


# Base64 turns 57 input bytes into one 76-character line, so pieces of a multiple of 57 bytes
# encode independently and their encodings can be sliced, repeated and concatenated.
_LINE = 57
_HEAD = _LINE * 16  # per-file bytes in front: magic number and a seeded random part
_BLOCK = _LINE * 1024  # repeated filler, the same for all files of one type
_MAGIC = {
    "application/pdf": b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n",
    "image/jpeg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00",
    "image/png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
    "application/zip": b"PK\x03\x04\x14\x00\x00\x00\x08\x00",
    "video/mp4": b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",
}
_TEXT_SAMPLES = {
    "text/csv": b"Datum;Artikel;Menge;Preis\n2019-03-04;Artikel 1042;12;34,50\n"
    b"2019-03-05;Artikel 2210;3;129,00\n2019-03-07;Artikel 0815;40;2,95\n",
    "text/plain": b"Notizen zum Termin\n- Angebot pruefen\n- Lieferzeit klaeren\n- Rueckruf\n",
    "text/calendar": b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Generator//Kalender//DE\n"
    b"BEGIN:VEVENT\nSUMMARY:Abstimmung\nDTSTART:20190304T090000\nEND:VEVENT\nEND:VCALENDAR\n",
    "text/vcard": b"BEGIN:VCARD\nVERSION:3.0\nFN:Kontakt\nTEL;TYPE=WORK:+49 40 66969 100\n"
    b"END:VCARD\n",
}


@lru_cache(maxsize=64)
def _filler(mime_type: str) -> tuple[bytes, bytes]:
    """Filler block of a file type and its base64 encoding (77 bytes per 57-byte line)."""
    sample = _TEXT_SAMPLES.get(mime_type)
    if sample is not None:
        block = (sample * (_BLOCK // len(sample) + 1))[:_BLOCK]
    else:
        block = random.Random(f"filler:{mime_type}").randbytes(_BLOCK)
    return block, base64.encodebytes(block)


def _payload_head(spec: AttachmentSpec) -> bytes:
    """The first bytes of a filler payload; they depend on name, type and size, so different
    files hash differently and a forwarded file keeps its hash."""
    seed = random.Random(f"{spec.filename}:{spec.mime_type}:{spec.size}")
    sample = _TEXT_SAMPLES.get(spec.mime_type)
    if sample is not None:
        own = f"{seed.getrandbits(64):016x}\n".encode() + sample * (_HEAD // len(sample) + 1)
    else:
        own = _MAGIC.get(spec.mime_type, b"") + seed.randbytes(_HEAD)
    return own[: min(_HEAD, spec.size)]


def _payload_sha256(spec: AttachmentSpec) -> str:
    """SHA-256 of the filler payload _encoded_payload writes, without building it."""
    head = _payload_head(spec)
    digest = hashlib.sha256(head)
    rest = spec.size - len(head)
    if rest:
        block, _ = _filler(spec.mime_type)
        repeats, tail = divmod(rest, _BLOCK)
        for _ in range(repeats):
            digest.update(block)
        digest.update(block[:tail])
    return digest.hexdigest()


def _encoded_payload(spec: AttachmentSpec) -> tuple[bytes, ...]:
    """Base64 lines of a deterministic payload of exactly `spec.size` bytes: its head
    (_payload_head), then the filler block of its type repeated."""
    head = _payload_head(spec)
    rest = spec.size - len(head)
    if rest == 0:
        return (base64.encodebytes(head),)
    block, encoded = _filler(spec.mime_type)
    repeats, tail = divmod(rest, _BLOCK)
    lines, partial = divmod(tail, _LINE)
    start = lines * _LINE
    return (
        base64.encodebytes(head),
        encoded * repeats,
        encoded[: lines * (_LINE // 3 * 4 + 1)],
        base64.encodebytes(block[start : start + partial]),
    )


def _body_texts(
    mail: PlannedMail, style: _Style, rng: random.Random, cids: Sequence[str]
) -> tuple[str, str | None]:
    """Plain text and, if the program writes one, HTML of the body with quote or forward."""
    german = mail.language == "de"
    delimiter = mail.client in ("thunderbird", "webmail")
    text = compose(mail)
    own = text.lines(delimiter)
    parent = mail.quoted
    quote: list[str] = []
    if parent is not None and not _forwards_as_message(mail):
        quoted = compose(parent).lines(delimiter)
        if mail.kind is MailKind.FORWARD:
            quote = _forward_block(parent, mail, german) + quoted
        elif style.outlook_quote:
            quote = _outlook_block(parent, mail, german) + quoted
        else:
            quote = [_attribution(parent, mail.client, german)]
            quote += [f"> {line}" if line else ">" for line in quoted]
    bottom = bool(quote) and mail.client == "thunderbird" and rng.random() < 0.4
    lines = ([*quote, "", *own] if bottom else [*own, "", *quote]) if quote else own
    plain = "\n".join(lines).rstrip("\n") + "\n"
    if not (cids or mail.kind is MailKind.NEWSLETTER or rng.random() < style.html_share):
        return plain, None
    return plain, _html(mail, text, quote, bottom, cids, style)


def _html(
    mail: PlannedMail,
    text: Text,
    quote: list[str],
    bottom: bool,
    cids: Sequence[str],
    style: _Style,
) -> str:
    esc = html.escape
    blocks: list[str] = []
    if text.greeting:
        blocks.append(f"<p>{esc(text.greeting)}</p>")
    blocks += [f"<p>{esc(paragraph)}</p>" for paragraph in text.paragraphs]
    blocks += [f'<p><a href="{esc(url)}">{esc(label)}</a></p>' for label, url in text.links]
    blocks.append("<p>" + "<br>\n".join(esc(line) for line in text.closing) + "</p>")
    if text.signature:
        signature = "<br>\n".join(esc(line) for line in text.signature)
        blocks.append(f'<div class="signature">{signature}</div>')
    blocks += [f'<p><img src="cid:{cid}" alt="{esc(cid.partition("@")[0])}"></p>' for cid in cids]
    if quote:
        body = "<br>\n".join(esc(line.removeprefix(">").removeprefix(" ")) for line in quote[1:])
        if style.outlook_quote or mail.kind is MailKind.FORWARD:
            cited = f"<div>\n<p>{esc(quote[0])}</p>\n<p>{body}</p>\n</div>"
        else:
            cited = f'<div>{esc(quote[0])}</div>\n<blockquote type="cite">\n{body}\n</blockquote>'
        blocks = [cited, *blocks] if bottom else [*blocks, cited]
    content = "\n".join(blocks)
    if mail.kind is MailKind.NEWSLETTER:
        image = f"https://{mail.sender.domain}/img/banner.png"
        banner = f'<img src="{image}" width="600" alt="{esc(brand(mail.sender.domain))}">'
        content = (
            f'<table width="600" align="center">\n<tr><td>{banner}</td></tr>\n'
            f"<tr><td>\n{content}\n</td></tr>\n</table>"
        )
    lang = ' lang="DE"' if mail.language == "de" else ""
    return (
        '<html>\n<head>\n<meta http-equiv="Content-Type" content="text/html; charset=CHARSET">\n'
        f"</head>\n<body{lang}>\n{content}\n</body>\n</html>\n"
    )


def _structure(planned: PlannedMail, style: _Style, charset: str, rng: random.Random) -> _Node:
    """Choose the MIME structure: plain or alternative, related for inline images, mixed."""
    inline = [a for a in planned.attachments if a.inline]
    files = [a for a in planned.attachments if not a.inline]
    stamp = f"{rng.getrandbits(32):08X}.{rng.getrandbits(32):08X}"
    cids = [f"{a.filename}@01D{stamp}" for a in inline]
    plain, html_text = _body_texts(planned, style, rng, cids)
    flowed = "; format=flowed" if planned.client == "thunderbird" else ""
    body: _Node = _text_leaf(plain, "plain", charset, style, rng, flowed)
    if html_text is not None:
        html_leaf = _text_leaf(html_text, "html", charset, style, rng)
        if planned.kind is MailKind.NEWSLETTER and rng.random() < 0.05:
            body = html_leaf  # HTML only, as some bulk senders do
        else:
            body = _Multi("alternative", _boundary(planned.client, rng), [body, html_leaf])
    if inline:
        images: list[_Node] = [
            _attachment_leaf(a, style, cid) for a, cid in zip(inline, cids, strict=True)
        ]
        body = _Multi("related", _boundary(planned.client, rng), [body, *images])
    parts: list[_Node] = [body]
    if _forwards_as_message(planned) and planned.quoted is not None:
        parts.append(_forwarded_message(planned.quoted, files, rng))
    else:
        parts += [_attachment_leaf(a, style) for a in files]
    if len(parts) == 1:
        return body
    return _Multi("mixed", _boundary(planned.client, rng), parts, style.preamble)


def _forwarded_message(
    parent: PlannedMail, files: list[AttachmentSpec], rng: random.Random
) -> _Message:
    """The forwarded original as an attached message; carried attachments travel inside it."""
    style = _STYLES.get(parent.client, _STYLES["webmail"])
    plain = "\n".join(compose(parent).lines(parent.client in ("thunderbird", "webmail"))) + "\n"
    node: _Node = _text_leaf(plain, "plain", "utf-8", style, rng)
    if files:
        parts: list[_Node] = [node, *(_attachment_leaf(a, style) for a in files)]
        node = _Multi("mixed", _boundary(parent.client, rng), parts, style.preamble)
    lines = [
        f"Date: {_date(parent.date)}",
        _address_header("From", (parent.sender,), style, "utf-8"),
        _address_header("To", parent.to, style, "utf-8")
        if parent.to
        else "To: undisclosed-recipients:;",
    ]
    if parent.cc:
        lines.append(_address_header("Cc", parent.cc, style, "utf-8"))
    lines += [
        _subject_header(parent.subject, style, "utf-8"),
        f"Message-ID: {parent.message_id}",
        "MIME-Version: 1.0",
    ]
    return _Message("\n".join(lines) + "\n", node)


# Headers ---------------------------------------------------------------------------------


def _date(d: datetime, pad: bool = False) -> str:
    """RFC 5322 date, for example 'Mon, 4 Mar 2019 09:12:33 +0100'."""
    minutes = int((d.utcoffset() or timedelta()).total_seconds()) // 60
    hours, rest = divmod(abs(minutes), 60)
    zone = f"{'+' if minutes >= 0 else '-'}{hours:02d}{rest:02d}"
    day = f"{d.day:02d}" if pad else str(d.day)
    clock = f"{d.hour:02d}:{d.minute:02d}:{d.second:02d}"
    return f"{_DAYS[d.weekday()]}, {day} {_MONTHS[d.month - 1]} {d.year} {clock} {zone}"


# Characters that may stand for themselves inside an encoded word in a phrase (RFC 2047 5.3).
_PHRASE_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!*+-/")
_SPECIALS = frozenset('()<>[]:;@\\,."')


def _q(char: str, data: bytes) -> str:
    if char == " ":
        return "_"
    return char if char in _PHRASE_SAFE else "".join(f"={byte:02X}" for byte in data)


def _encoded_words(text: str, charset: str, style: _Style) -> list[str]:
    """RFC 2047 encoded words of at most 75 characters, never splitting a character."""
    try:
        text.encode(charset)
    except UnicodeEncodeError:
        charset = "utf-8"
    prefix = f"=?{_label(charset, style)}?{style.words}?"
    room = 75 - len(prefix) - 2
    words: list[str] = []
    chunk = bytearray()
    q_text: list[str] = []
    for char in text:
        data = char.encode(charset)
        if style.words == "B":
            fits = 4 * ((len(chunk) + len(data) + 2) // 3) <= room
        else:
            piece = _q(char, data)
            fits = sum(map(len, q_text)) + len(piece) <= room
        if chunk and not fits:
            words.append(_finish_word(prefix, chunk, q_text, style.words))
            chunk, q_text = bytearray(), []
        chunk += data
        if style.words == "Q":
            q_text.append(piece)
    words.append(_finish_word(prefix, chunk, q_text, style.words))
    return words


def _finish_word(prefix: str, chunk: bytearray, q_text: list[str], method: str) -> str:
    encoded = base64.b64encode(chunk).decode() if method == "B" else "".join(q_text)
    return f"{prefix}{encoded}?="


def _phrase(name: str, style: _Style, charset: str) -> str:
    """A display name as header text: plain, quoted, or as encoded words."""
    if not name.isascii():
        return " ".join(_encoded_words(name, charset, style))
    if any(c in _SPECIALS for c in name):
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return name


def _format_address(address: Address, style: _Style, charset: str) -> str:
    if not address.display_name:
        return address.email
    return f"{_phrase(address.display_name, style, charset)} <{address.email}>"


def _address_header(name: str, addresses: Sequence[Address], style: _Style, charset: str) -> str:
    items = [_format_address(a, style, charset) for a in addresses]
    line = f"{name}: {', '.join(items)}"
    return line if len(line) <= 78 else f"{name}: " + ",\n ".join(items)


def _subject_header(subject: str, style: _Style, charset: str) -> str:
    if subject.isascii():
        return _fold(f"Subject: {subject}")
    return "Subject: " + "\n ".join(_encoded_words(subject, charset, style))


def _fold(line: str) -> str:
    """Fold an unstructured header at spaces so lines stay within 78 characters."""
    out: list[str] = []
    while len(line) > 78:
        cut = line.rfind(" ", 0, 78)
        if cut <= line.find(":") + 1:
            break
        out.append(line[:cut])
        line = line[cut:]
    out.append(line)
    return "\n".join(out)


def _fold_ids(name: str, ids: Sequence[str]) -> str:
    line = f"{name}: {' '.join(ids)}"
    return line if len(line) <= 78 else f"{name}: " + "\n ".join(ids)


def _ip(host: str) -> str:
    """Stable address of a host, from the documentation ranges (RFC 5737)."""
    value = zlib.crc32(host.encode())
    network = ("192.0.2", "198.51.100", "203.0.113")[value % 3]
    return f"{network}.{value // 3 % 250 + 2}"


def _private_ip(rng: random.Random) -> str:
    return f"10.{rng.randrange(256)}.{rng.randrange(256)}.{rng.randrange(1, 255)}"


def _host(domain: str, names: Sequence[str]) -> str:
    label = domain.partition(".")[0]  # no mail.mail.shop.example for a sending subdomain
    names = [name for name in names if name != label]
    return f"{names[zlib.crc32(domain.encode()) % len(names)]}.{domain}"


def _server_time(domain: str, sent: datetime, delay: int) -> datetime:
    """A receiving server's clock `delay` seconds after sending: UTC on some, German on most."""
    instant = (sent + timedelta(seconds=delay)).astimezone(UTC)
    if zlib.crc32(domain.encode()) % 3 == 0:
        return instant
    return instant.astimezone(timezone(utc_offset("Europe/Berlin", instant)))


def _exchange(year: int, rng: random.Random) -> str:
    """Build number of the Exchange server a mail of that year went through."""
    if year < 2016:
        return f"14.3.{rng.choice((123, 158, 174, 195, 224, 266, 319))}.{rng.randint(1, 4)}"
    if year < 2021:
        return f"15.1.{rng.choice((1415, 1713, 1979, 2044, 2176))}.{rng.randint(2, 40)}"
    return f"15.2.{rng.choice((986, 1118, 1258, 1544))}.{rng.randint(3, 40)}"


def _received(planned: PlannedMail, rng: random.Random) -> list[str]:
    """Received lines, newest first; every host is below the sender's or recipient's domain."""
    sender = planned.sender.domain
    stamp = planned.date
    relay = _host(sender, ("mail", "smtp", "mx01", "mail01", "out"))
    queue = f"{rng.getrandbits(44):011X}"
    if planned.client == "outlook":
        first = f"EX{rng.randint(1, 9):02d}MB{rng.getrandbits(16):04X}.{sender}"
        second = f"EX{rng.randint(1, 9):02d}MB{rng.getrandbits(16):04X}.{sender}"
        tls = "(TLS)"
        if stamp.year >= 2016:
            tls = "\n (version=TLS1_2, cipher=TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384)"
        hops = [
            f"from {first} ({_private_ip(rng)}) by {second}\n ({_private_ip(rng)}) with"
            f" Microsoft SMTP Server {tls} id {_exchange(stamp.year, rng)};"
            f"\n {_date(stamp + timedelta(seconds=1))}"
        ]
    elif planned.client in ("bulk", "system"):
        hops = [
            f"from localhost (localhost [127.0.0.1])\n\tby {relay} (Postfix) with ESMTP id"
            f" {queue};\n\t{_date(stamp)}"
        ]
    else:
        hops = [
            f"from [{_private_ip(rng)}]\n\tby {relay} with ESMTPSA id {queue};"
            f"\n\t{_date(stamp + timedelta(seconds=1))}"
        ]
    target = planned.to[0] if planned.to else None
    if target is not None and target.domain != sender:
        mx = _host(target.domain, ("mx1", "mx", "mail", "mx01", "in"))
        hops.append(
            f"from {relay} ({relay} [{_ip(relay)}])\n\tby {mx} (Postfix) with ESMTPS id"
            f" {rng.getrandbits(44):011X}\n\tfor <{target.email}>;"
            f" {_date(_server_time(target.domain, stamp, rng.randint(2, 40)))}"
        )
        if rng.random() < 0.5:
            store = _host(target.domain, ("mailstore", "imap", "dovecot"))
            lmtp = base64.b64encode(rng.randbytes(9)).decode()
            hops.append(
                f"from {mx} ({mx} [{_ip(mx)}])\n\tby {store} with LMTP id {lmtp};"
                f"\n\t{_date(_server_time(target.domain, stamp, rng.randint(41, 90)))}"
            )
    return [f"Received: {hop}" for hop in reversed(hops)]


def _headers(planned: PlannedMail, style: _Style, charset: str, rng: random.Random) -> str:
    lines: list[str] = []
    if rng.random() < 0.8:
        lines.append(f"Return-Path: <{planned.sender.email}>")
    lines += _received(planned, rng)
    core = [f"Date: {_date(planned.date, pad=planned.client in ('bulk', 'system'))}"]
    core.append(_address_header("From", (planned.sender,), style, charset))
    if planned.to:
        core.append(_address_header("To", planned.to, style, charset))
    else:
        core.append("To: undisclosed-recipients:;")
    if planned.cc:
        core.append(_address_header("Cc", planned.cc, style, charset))
    if planned.bcc:
        core.append(_address_header("Bcc", planned.bcc, style, charset))
    core.append(_subject_header(planned.subject, style, charset))
    if planned.client == "outlook":
        core.append(core.pop(0))  # Outlook writes the Date after the Subject
    lines += core
    list_local, _, list_domain = (planned.list_id or "").partition(".")
    hosted = planned.kind not in _AUTOMATED and list_domain.startswith("lists.")
    if hosted:
        lines.append(f"Sender: {list_local}-bounces@{list_domain}")
    lines.append(f"Message-ID: {planned.message_id}")
    if planned.in_reply_to:
        lines.append(f"In-Reply-To: {planned.in_reply_to}")
    if planned.references:
        lines.append(_fold_ids("References", planned.references))
    if planned.client == "outlook":
        lines.append(f"Thread-Index: {base64.b64encode(rng.randbytes(22)).decode()}")
        if planned.attachments:
            lines.append("X-MS-Has-Attach: yes")
        lines.append(f"Content-Language: {'de-DE' if planned.language == 'de' else 'en-US'}")
        if rng.random() < 0.03:
            lines += ["X-Priority: 1", "Importance: high"]
    agent = _agent(planned)
    if agent:
        lines.append(f"{agent[0]}: {agent[1]}")
    if planned.list_id:
        lines += _list_headers(planned, list_local, list_domain, hosted, style)
    if planned.automated and planned.kind is not MailKind.NEWSLETTER:
        lines.append("Auto-Submitted: auto-generated")
    lines.append("MIME-Version: 1.0")
    return "\n".join(lines) + "\n"


def _list_headers(
    planned: PlannedMail, local: str, domain: str, hosted: bool, style: _Style
) -> list[str]:
    list_id = planned.list_id
    if planned.kind is MailKind.NEWSLETTER:
        token = f"{zlib.crc32(str(planned.seed).encode()):08x}"
        name = _phrase(f"{brand(domain)} Newsletter", style, "utf-8")
        return [
            f"List-Id: {name} <{list_id}>",
            f"List-Unsubscribe: <https://{domain}/abmelden?u={token}>,"
            f"\n <mailto:unsubscribe@{domain}?subject=unsubscribe>",
            "List-Unsubscribe-Post: List-Unsubscribe=One-Click",
            "Precedence: bulk",
        ]
    if not hosted:
        return [
            f"List-Id: Verteiler {local} <{list_id}>",
            f"List-Unsubscribe: <mailto:{local}-leave@{domain}>",
            "Precedence: list",
        ]
    return [
        f"List-Id: {_phrase(brand(domain), style, 'utf-8')} <{list_id}>",
        f"List-Post: <mailto:{local}@{domain}>",
        f"List-Unsubscribe: <https://{domain}/mailman/options/{local}>,"
        f"\n <mailto:{local}-request@{domain}?subject=unsubscribe>",
        "Precedence: list",
    ]

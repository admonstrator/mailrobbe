"""Hand-built mails for the DKIM, fault and duplicate tests.

They stand in for generator/render.py and cover what sign_mail, apply_faults and the
DuplicateInjector rely on: LF line endings, one Message-ID and one Date header, and the shapes
the renderer produces (text in 8bit, quoted-printable and base64, ISO-8859-1 text,
multipart/alternative, multipart/mixed with a base64 attachment, RFC 2047 names and subjects).
"""

import base64
import functools
import quopri
import random
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from email.header import Header
from email.utils import format_datetime, formataddr
from pathlib import Path

from mailspider.enums import DkimStatus
from mailspider.generator.config import GeneratorConfig
from mailspider.generator.dkim import DkimSetup, Selector, Signer, build_dkim_setup
from mailspider.generator.model import (
    Address,
    Domain,
    DomainKind,
    PlannedMail,
    RenderedMail,
    derive_seed,
    stage_rng,
)

INTERNAL = Domain("nordwind.example", DomainKind.ORGANISATION, internal=True)
ORGANISATIONS = tuple(
    Domain(f"{name}.example", DomainKind.ORGANISATION)
    for name in (
        "hafenlogistik",
        "kanzlei-berg",
        "stadtwerke-lindau",
        "brauerei-alt",
        "ingenieure-ost",
        "baumarkt-sued",
        "verlag-blau",
        "praxis-sonne",
        "autohaus-west",
        "textil-nord",
        "bank-mitte",
        "spedition-roth",
        "schule-am-see",
        "klinik-tal",
        "agentur-funk",
        "druckerei-hahn",
        "museum-alt",
        "verein-sport",
        "hotel-berg",
        "steuerbuero-k",
    )
)
FREEMAIL = tuple(
    Domain(name, DomainKind.FREEMAIL)
    for name in ("webpost.example", "mailbox.test", "postfach.example", "netzmail.test")
)
SERVICES = tuple(
    Domain(name, DomainKind.SERVICE)
    for name in (
        "newsletter-haus.example",
        "lists.verband.example",
        "ticket.dienst.example",
        "shop-versand.example",
        "rechnung.portal.example",
        "kalender.dienst.test",
        "umfrage.example",
        "jobs-board.example",
    )
)
DOMAINS = (INTERNAL, *ORGANISATIONS, *FREEMAIL, *SERVICES)
CONFIG = GeneratorConfig(out_dir=Path("unused"), meta_dir=Path("unused"), seed=7)
STRUCTURES = ("plain_8bit", "plain_qp", "plain_latin1", "plain_base64", "alternative", "mixed")

_NAMES = (
    "Max Müller",
    "Anna Schäfer",
    "Jörg Weiß",
    "Lena Koch",
    "Peter Braun",
    "Sophie Wagner",
    "Jürgen Groß",
    "Claire Dubois",
    "Tom Baker",
    "Müller, Karin",
)
_SUBJECTS = (
    "Protokoll der Sitzung",
    "Rückfrage zur Rechnung 2019-03",
    "Angebot für das dritte Quartal",
    "Termin nächste Woche",
    "Re: Projektplan",
    "AW: Änderungen im Vertrag",
    "Newsletter März",
    "Ihre Bestellung ist unterwegs",
)
_TRANSLITERATION = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", " ": "."})
_LISTS = ("<vorstand.verband.example>", "<team.nordwind.example>", "<info.lists.verband.example>")


def single_signer(
    keys: Mapping[int, bytes],
    domain: Domain,
    bits: int = 2048,
    canonicalization: str = "relaxed/relaxed",
) -> DkimSetup:
    """A setup in which only `domain` signs, with one published selector "s1" for every date."""
    selector = Selector("s1", datetime(2000, 1, 1, tzinfo=UTC), bits, DkimStatus.PASS)
    order = ("from", "to", "cc", "subject", "date", "message-id", "mime-version", "content-type")
    return DkimSetup(
        keys=keys, signers={domain.name: Signer(domain.name, canonicalization, order, (selector,))}
    )


@functools.cache
def sample_setup(share: float = 0.7) -> DkimSetup:
    """DKIM setup over DOMAINS; cached, because generating the keys takes about a second."""
    config = replace(CONFIG, dkim_signed_share=share)
    return build_dkim_setup(DOMAINS, config, stage_rng(config.seed, "dkim-setup"))


def address(name: str, domain: Domain) -> Address:
    local = name.split(", ")[::-1] if ", " in name else name.split()
    return Address(".".join(local).lower().translate(_TRANSLITERATION) + "@" + domain.name, name)


def planned_mail(
    index: int,
    *,
    seed: int = 1,
    sender: Domain | None = None,
    date: datetime | None = None,
    list_id: str | None = None,
    automated: bool | None = None,
) -> PlannedMail:
    """A plausible PlannedMail; senders weighted internal 50 %, freemail and service 25 %,
    other organisations 25 %, dates spread evenly over CONFIG's range."""
    mail_seed = derive_seed(seed, index)
    rng = stage_rng(mail_seed, "sample")
    if sender is None:
        roll = rng.random()
        if roll < 0.5:
            sender = INTERNAL
        elif roll < 0.75:
            sender = rng.choice(FREEMAIL + SERVICES)
        else:
            sender = rng.choice(ORGANISATIONS)
    if date is None:
        start = datetime(CONFIG.date_from.year, CONFIG.date_from.month, CONFIG.date_from.day)
        end = datetime(CONFIG.date_to.year, CONFIG.date_to.month, CONFIG.date_to.day)
        offset = timezone(timedelta(hours=rng.choice((1, 2))))
        seconds = rng.uniform(0, (end - start).total_seconds())
        date = (start + timedelta(seconds=seconds)).replace(microsecond=0, tzinfo=offset)
    if automated is None:
        automated = sender.kind is DomainKind.SERVICE
    if list_id is None and not automated and rng.random() < 0.15:
        list_id = rng.choice(_LISTS)
    recipient = address(rng.choice(_NAMES), INTERNAL if sender is not INTERNAL else sender)
    reply = rng.random() < 0.3
    return PlannedMail(
        index=index,
        seed=mail_seed,
        date=date,
        sender=address("Info Service" if automated else rng.choice(_NAMES), sender),
        to=(recipient,),
        cc=(address(rng.choice(_NAMES), INTERNAL),) if rng.random() < 0.3 else (),
        subject=rng.choice(_SUBJECTS),
        message_id=f"<{mail_seed:x}.{index}@{sender.name}>",
        in_reply_to=f"<{index - 1}.reply@{sender.name}>" if reply else None,
        references=(f"<{index - 1}.reply@{sender.name}>",) if reply else (),
        list_id=list_id,
        automated=automated,
    )


def _text(planned: PlannedMail) -> str:
    return (
        "Hallo zusammen,\n\n"
        "anbei die Unterlagen für die nächste Sitzung. Bitte prüft die Änderungen\n"
        "bis Freitag und gebt mir kurz Bescheid.\n\n"
        f"Viele Grüße\n{(planned.sender.display_name or '').split()[0]}\n"
    )


def _body(planned: PlannedMail, structure: str, rng: random.Random) -> tuple[list[str], bytes]:
    text = _text(planned)
    if structure == "plain_8bit":
        return ['text/plain; charset="utf-8"', "8bit"], text.encode()
    if structure == "plain_qp":
        return ['text/plain; charset="utf-8"', "quoted-printable"], quopri.encodestring(
            text.encode()
        )
    if structure == "plain_latin1":
        return ['text/plain; charset="iso-8859-1"', "8bit"], text.encode("latin-1")
    if structure == "plain_base64":
        return ['text/plain; charset="utf-8"', "base64"], base64.encodebytes(text.encode())
    boundary = f"=_part_{planned.seed:016x}"
    if structure == "alternative":
        html = "<html><body><p>" + text.replace("\n\n", "</p><p>") + "</p></body></html>\n"
        parts = [
            b'Content-Type: text/plain; charset="utf-8"\nContent-Transfer-Encoding: '
            b"quoted-printable\n\n" + quopri.encodestring(text.encode()),
            b'Content-Type: text/html; charset="utf-8"\nContent-Transfer-Encoding: 8bit\n\n'
            + html.encode(),
        ]
        content_type = f'multipart/alternative; boundary="{boundary}"'
    elif structure == "mixed":
        payload = base64.encodebytes(rng.randbytes(rng.randint(600, 3000)))
        parts = [
            b'Content-Type: text/plain; charset="utf-8"\nContent-Transfer-Encoding: 8bit\n\n'
            + text.encode(),
            b'Content-Type: application/pdf; name="Rechnung_2019-03.pdf"\n'
            b'Content-Disposition: attachment; filename="Rechnung_2019-03.pdf"\n'
            b"Content-Transfer-Encoding: base64\n\n" + payload,
        ]
        content_type = f'multipart/mixed; boundary="{boundary}"'
    else:
        raise ValueError(structure)
    delimiter = b"--" + boundary.encode()
    body = b"This is a multi-part message in MIME format.\n\n"
    for part in parts:
        body += delimiter + b"\n" + part.rstrip(b"\n") + b"\n"
    return [content_type, "7bit"], body + delimiter + b"--\n"


def render(planned: PlannedMail, structure: str) -> RenderedMail:
    rng = stage_rng(planned.seed, "render")
    (content_type, cte), body = _body(planned, structure, rng)
    sender = planned.sender

    def mailbox(item: Address) -> str:
        return formataddr((item.display_name or "", item.email))

    subject = planned.subject
    if not subject.isascii():
        subject = Header(subject, "utf-8").encode()
    lines = [
        f"Received: from mail.{sender.domain} ([192.0.2.{rng.randint(1, 254)}])"
        f"\n\tby mx.{planned.to[0].domain} with ESMTPS; {format_datetime(planned.date)}",
        f"From: {mailbox(sender)}",
        f"To: {', '.join(map(mailbox, planned.to))}",
        *([f"Cc: {', '.join(map(mailbox, planned.cc))}"] if planned.cc else []),
        f"Subject: {subject}",
        f"Date: {format_datetime(planned.date)}",
        f"Message-ID: {planned.message_id}",
        *([f"In-Reply-To: {planned.in_reply_to}"] if planned.in_reply_to else []),
        *([f"References: {' '.join(planned.references)}"] if planned.references else []),
        *([f"List-Id: {planned.list_id}"] if planned.list_id else []),
        *(["Precedence: bulk"] if planned.automated else []),
        "MIME-Version: 1.0",
        f"Content-Type: {content_type}",
        f"Content-Transfer-Encoding: {cte}",
    ]
    raw = "\n".join(lines).encode() + b"\n\n" + body
    return RenderedMail(planned=planned, raw=raw, message_id=planned.message_id)


def sample_mail(
    index: int,
    structure: str | None = None,
    *,
    seed: int = 1,
    sender: Domain | None = None,
    date: datetime | None = None,
    list_id: str | None = None,
    automated: bool | None = None,
) -> RenderedMail:
    """Rendered mail number `index`; the structure cycles through STRUCTURES by default."""
    plan = planned_mail(
        index, seed=seed, sender=sender, date=date, list_id=list_id, automated=automated
    )
    return render(plan, structure or STRUCTURES[index % len(STRUCTURES)])


def sample_stream(count: int, *, seed: int = 1) -> Iterator[RenderedMail]:
    for index in range(count):
        yield sample_mail(index, seed=seed)

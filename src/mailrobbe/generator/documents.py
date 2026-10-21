"""Real documents as attachments (D77, SPEC 3.6), and their ground truth.

The planner (main process) decides which document an attachment carries: DocumentPool turns the
attachment templates of the plan into DocumentSpec values, new ones or ones that circulate. A
document is seeded, so its bytes are a pure function of its spec and size: the renderer (worker
processes) builds them with build(), cached per process, and every mail that carries the
document carries the same bytes, whatever worker renders it.

Circulation: most documents attached by people are recent documents again (passed on to
others, sometimes under another file name), a reply with attachments to a mail with documents
often attaches those again, forwards carry the forwarded mail's documents (also inside an
attached message/rfc822), and the catalogue of a sender is the same file in all its mails of a
year. Invoices and the other documents of automated mail do not circulate.

Content: minutes, donation lists, cash reports, membership lists, invoices, offers, delivery
notes, letters, contracts, presentations, notes, payment exports, invitations and contact cards
of invented associations and companies, in German, with amounts and IBANs (valid check digits,
invented bank codes, no real institutions). Every distinct document with text holds one marker
word, "Dokmarke" and a code from its seed, so a test can search for it. Forms: PDFs with a text
layer, scans (images only), PDFs encrypted with a user password, damaged (truncated) PDFs, DOCX,
XLSX (amounts as numbers, IBANs as text), PPTX, ODT, CSV, plain text (some empty), iCalendar,
vCard and ZIP archives of a few documents. Pictures, audio, video and the very large attachments
stay filler (render.py); filler_truth() states what the extraction makes of them.

DocumentTruth (model.py) is what manifest.jsonl lists for each attachment of a mail, in the
order importer.parse.mime_parts finds them: SHA-256, file name, kind, expected text status,
marker and pages.
"""

import binascii
import hashlib
import math
import random
from collections import OrderedDict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from email.message import Message
from email.parser import BytesParser
from email.policy import compat32

from mailrobbe.enums import DocumentKind, DocumentTextStatus
from mailrobbe.generator import fileformats as ff
from mailrobbe.generator import vocabulary as vocab
from mailrobbe.generator.fileformats import Block, Para, Table
from mailrobbe.generator.model import AttachmentSpec, DocumentSpec, DocumentTruth, stage_rng
from mailrobbe.generator.population import transliterate

# The importer's default MAILROBBE_ATTACHMENT_TEXT_MAX_SIZE: larger attachments are not read.
TEXT_MAX_SIZE = 50 * 1024**2
MARKER_WORD = "Dokmarke"

REUSE_SHARE = 0.8  # attachments of people that are a recent document again
RENAME_SHARE = 0.12  # of those, passed on under another file name
AGAIN_SHARE = 0.5  # replies with attachments to a mail with documents: they are those again
OCTET_SHARE = 0.06  # new documents declared as application/octet-stream
ENCRYPTED_SHARE = 0.05  # text PDFs with a user password
DAMAGED_SHARE = 0.04  # text PDFs cut short
EMPTY_TEXT_SHARE = 0.15  # notes files without any text
RECENT_DOCUMENTS = 200  # documents that may be passed on again
_TEXT_SIZE_CAP = 200_000  # text formats are written, not padded: their size is their content
_CACHE_BYTES = 96 * 1024**2  # built documents kept per process

# Template file names of the plan (vocabulary.ATTACHMENT_TYPES and the planner's own) -> the
# form of their documents and the themes their content may have.
TEMPLATES: dict[str, tuple[str, tuple[str, ...]]] = {
    "Angebot_{project}.pdf": ("pdf", ("offer",)),
    "Rechnung_{year}-{month2}.pdf": ("pdf", ("invoice",)),
    "Protokoll_Sitzung.docx": ("docx", ("minutes",)),
    "Angebot.xlsx": ("xlsx", ("offer",)),
    "Scan_{year}{month2}{day2}_{n}.pdf": ("pdf_scan", ("scan",)),
    "Präsentation_{project}.pptx": ("pptx", ("presentation",)),
    "Lieferschein_{n}.pdf": ("pdf", ("delivery",)),
    "Übersicht_{year}.xlsx": ("xlsx", ("donations", "cash_report", "members")),
    "Vertrag_{project}_v{n}.docx": ("docx", ("contract",)),
    "Export_{year}{month2}.csv": ("csv", ("export",)),
    "Notizen.txt": ("txt", ("notes",)),
    "Unterlagen.zip": ("zip", ("archive",)),
    "Bewerbung_{word}.pdf": ("pdf", ("letter",)),
    "Grundriss_{project}.pdf": ("pdf_scan", ("plan",)),
    "Einladung.ics": ("ics", ("calendar",)),
    "Visitenkarte.vcf": ("vcf", ("contact",)),
    "Katalog_{year}.pdf": ("pdf", ("catalog",)),
    "Protokoll_{year}-{month2}-{day2}.odt": ("odt", ("minutes",)),
    "Kassenbericht_{year}.pdf": ("pdf", ("cash_report",)),
    "Spendenliste_{year}.xlsx": ("xlsx", ("donations",)),
    "Mitgliederliste_{year}.csv": ("csv", ("members",)),
    "Schreiben_{word}.docx": ("docx", ("letter",)),
    "Export_{n}.csv": ("csv", ("export",)),
    "Termin.ics": ("ics", ("calendar",)),
}

_KINDS = {
    "pdf": DocumentKind.PDF,
    "pdf_scan": DocumentKind.PDF,
    "pdf_encrypted": DocumentKind.PDF,
    "pdf_damaged": DocumentKind.PDF,
    "docx": DocumentKind.DOCUMENT,
    "odt": DocumentKind.DOCUMENT,
    "xlsx": DocumentKind.SPREADSHEET,
    "csv": DocumentKind.SPREADSHEET,
    "pptx": DocumentKind.PRESENTATION,
    "txt": DocumentKind.TEXT,
    "txt_empty": DocumentKind.TEXT,
    "ics": DocumentKind.TEXT,
    "vcf": DocumentKind.TEXT,
    "zip": DocumentKind.ARCHIVE,
}
_STATUSES = {
    "pdf_scan": DocumentTextStatus.SCANNED,
    "pdf_encrypted": DocumentTextStatus.ENCRYPTED,
    "pdf_damaged": DocumentTextStatus.FAILED,
    "txt_empty": DocumentTextStatus.EMPTY,
}
_TEXT_FORMS = frozenset({"csv", "txt", "txt_empty", "ics", "vcf"})


def document_seed(seed: int, key: str) -> int:
    digest = hashlib.blake2b(f"{seed}:document:{key}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def marker(seed: int) -> str:
    """The marker word of a document: Dokmarke and eight letters and digits."""
    rng = random.Random(f"marker:{seed}")
    return MARKER_WORD + "".join(rng.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(8))


# Planner side ------------------------------------------------------------------------------


class DocumentPool:
    """Turns planned attachments into documents, new or circulating (bounded state).

    Its decisions come from a random stream of their own, so the rest of the plan is the same
    with or without documents.
    """

    def __init__(self, seed: int) -> None:
        self._seed = seed
        self._rng = stage_rng(seed, "plan-documents")
        self._recent: deque[AttachmentSpec] = deque(maxlen=RECENT_DOCUMENTS)
        self._shared: dict[str, AttachmentSpec] = {}  # bounded: senders times years
        self._count = 0

    def attach(
        self,
        spec: AttachmentSpec,
        pattern: str,
        when: datetime,
        taken: Sequence[AttachmentSpec] = (),
        *,
        circulate: bool = True,
        shared: str | None = None,
    ) -> AttachmentSpec:
        """The attachment with its document; `spec` as it is for pictures and media.

        `taken` are the mail's other attachments (no document twice), `circulate` False keeps
        the document out of reuse (invoices, automated mail), `shared` names a document many
        mails carry unchanged (a sender's catalogue of a year).
        """
        template = TEMPLATES.get(pattern)
        if template is None:
            return spec
        if shared is not None and shared in self._shared:
            return self._shared[shared]
        rng = self._rng
        if circulate and shared is None and self._recent and rng.random() < REUSE_SHARE:
            back = min(len(self._recent) - 1, int(rng.expovariate(1 / 12)))
            again = self._recent[-1 - back]
            if rng.random() < RENAME_SHARE:
                again = replace(again, filename=_renamed(again.filename, rng))
            names = {a.filename for a in taken}
            documents = {a.document for a in taken}
            if again.filename not in names and again.document not in documents:
                return again
        form, themes = template
        theme = rng.choice(themes)
        if form == "pdf":
            draw = rng.random()
            if draw < ENCRYPTED_SHARE:
                form = "pdf_encrypted"
            elif draw < ENCRYPTED_SHARE + DAMAGED_SHARE:
                form = "pdf_damaged"
        elif form == "txt" and rng.random() < EMPTY_TEXT_SHARE:
            form = "txt_empty"
        mime_type = "application/octet-stream" if rng.random() < OCTET_SHARE else spec.mime_type
        seed = document_seed(self._seed, str(self._count))
        self._count += 1
        size = min(spec.size, _TEXT_SIZE_CAP) if form in _TEXT_FORMS else spec.size
        made = replace(
            spec, mime_type=mime_type, size=size, document=DocumentSpec(seed, form, theme, when)
        )
        if shared is not None:
            self._shared[shared] = made
        elif circulate:
            self._recent.append(made)
        return made

    def again(
        self, parent: Sequence[AttachmentSpec], own: tuple[AttachmentSpec, ...]
    ) -> tuple[AttachmentSpec, ...]:
        """The attachments of a reply: its own, or the documents of the mail it answers again
        (the share of mails with attachments stays the configured one)."""
        documents = tuple(a for a in parent if a.document is not None and not a.inline)
        if documents and self._rng.random() < AGAIN_SHARE:
            return documents
        return own


_RENAMES = ("_Kopie", "_final", "_neu", "_v2", "_überarbeitet", " (1)")


def _renamed(filename: str, rng: random.Random) -> str:
    stem, dot, extension = filename.rpartition(".")
    if not dot:
        return filename + rng.choice(_RENAMES)
    return f"{stem}{rng.choice(_RENAMES)}.{extension}"


# Worker side -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Built:
    """A built document: its base64 lines in pieces (as the renderer writes them, repeated
    pieces shared) and its truth."""

    encoded: tuple[bytes, ...]
    sha256: str
    size: int
    kind: DocumentKind
    status: DocumentTextStatus
    marker: str | None
    pages: int | None

    def truth(self, filename: str) -> DocumentTruth:
        return DocumentTruth(
            self.sha256,
            filename,
            self.kind.value,
            self.status.value,
            self.marker,
            self.pages,
            self.size,
        )


class _Cache:
    """Built documents of this process, least recently used dropped beyond _CACHE_BYTES."""

    def __init__(self) -> None:
        self._items: OrderedDict[tuple[DocumentSpec, int], Built] = OrderedDict()
        self._bytes = 0

    def get(self, spec: DocumentSpec, size: int) -> Built:
        key = (spec, size)
        found = self._items.get(key)
        if found is not None:
            self._items.move_to_end(key)
            return found
        built = _build(spec, size)
        self._items[key] = built
        self._bytes += _held(built)
        while self._bytes > _CACHE_BYTES and len(self._items) > 1:
            _, dropped = self._items.popitem(last=False)
            self._bytes -= _held(dropped)
        return built


def _held(built: Built) -> int:
    return sum(len(piece) for piece in {id(piece): piece for piece in built.encoded}.values())


_CACHE = _Cache()


def build(spec: AttachmentSpec) -> Built:
    """The built document of an attachment that has one (spec.document)."""
    assert spec.document is not None
    return _CACHE.get(spec.document, spec.size)


def _build(spec: DocumentSpec, size: int) -> Built:
    data, pages = document_bytes(spec, size)
    status = _STATUSES.get(spec.form, DocumentTextStatus.TEXT)
    if spec.form in ("pdf_encrypted", "pdf_damaged"):
        pages = None  # the extraction cannot count them
    return Built(
        encoded=ff.encode_base64(data),
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        kind=_KINDS[spec.form],
        status=status,
        marker=marker(spec.seed) if status is DocumentTextStatus.TEXT else None,
        pages=pages,
    )


_FILLER_KINDS = {
    "application/pdf": DocumentKind.PDF,
    "application/zip": DocumentKind.ARCHIVE,
    "text/csv": DocumentKind.SPREADSHEET,
}


def filler_truth(spec: AttachmentSpec, sha256: str) -> DocumentTruth:
    """What the extraction makes of a filler attachment (render.py): pictures and media are
    unsupported, a PDF or ZIP of noise behind its magic number is damaged, sample text is text;
    above TEXT_MAX_SIZE nothing is read."""
    mime = spec.mime_type
    if mime.startswith("image/"):
        kind = DocumentKind.IMAGE
    elif mime.startswith(("video/", "audio/")):
        kind = DocumentKind.MEDIA
    elif mime.startswith("text/"):
        kind = _FILLER_KINDS.get(mime, DocumentKind.TEXT)
    else:
        kind = _FILLER_KINDS.get(mime, DocumentKind.OTHER)
    if spec.size > TEXT_MAX_SIZE:
        status = DocumentTextStatus.TOO_LARGE
    elif kind in (DocumentKind.PDF, DocumentKind.ARCHIVE):
        status = DocumentTextStatus.FAILED
    elif kind in (DocumentKind.TEXT, DocumentKind.SPREADSHEET):
        status = DocumentTextStatus.TEXT
    else:
        status = DocumentTextStatus.UNSUPPORTED
    return DocumentTruth(sha256, spec.filename, kind.value, status.value, None, None, spec.size)


def damaged(truths: list[DocumentTruth], raw: bytes) -> list[DocumentTruth]:
    """The truths after the invalid_base64 fault: an attachment whose base64 it broke has
    unknown bytes (sha256, status, marker and pages None)."""
    flags = damaged_attachments(raw)
    if len(flags) != len(truths):
        raise ValueError(f"{len(truths)} attachments planned, {len(flags)} found")
    return [
        replace(truth, sha256=None, status=None, marker=None, pages=None) if bad else truth
        for truth, bad in zip(truths, flags, strict=True)
    ]


def damaged_attachments(raw: bytes) -> list[bool]:
    """Per attachment (parts with a file name, in document order, as mime_parts finds them):
    whether its base64 no longer decodes cleanly, after the invalid_base64 fault."""
    message = BytesParser(policy=compat32).parsebytes(raw)
    found: list[bool] = []
    for part in message.walk():
        if part.is_multipart() or part.get_filename() is None:
            continue
        found.append(not _clean_base64(part))
    return found


def _clean_base64(part: Message) -> bool:
    if str(part.get("content-transfer-encoding", "")).strip().lower() != "base64":
        return True
    payload = part.get_payload()
    if not isinstance(payload, str):
        return True
    try:
        binascii.a2b_base64("".join(payload.split()), strict_mode=True)
    except binascii.Error:
        return False
    return True


def document_bytes(spec: DocumentSpec, size: int) -> tuple[bytes, int | None]:
    """The bytes of a document of about `size` bytes (text forms: as long as their content),
    and its pages, sheets or slides (None where it has none)."""
    rng = random.Random(f"document:{spec.seed}")
    form = spec.form
    if form == "pdf_scan":
        count = rng.randint(1, 2) if spec.theme == "plan" else rng.randint(1, 5)
        share = max(size - 1500 * count, 2000) // count
        return ff.pdf([], rng, images=[share] * count), count
    content = _Content(spec, rng, size)
    title, author, when = content.title, content.author, content.when
    if form in ("pdf", "pdf_encrypted", "pdf_damaged"):
        pages = content.pdf_pages()
        data = ff.pdf(pages, rng, size=size, password=_password(rng, form))
        if form == "pdf_damaged":
            data = data[: int(len(data) * rng.uniform(0.35, 0.9))]
        return data, len(pages)
    if form == "docx":
        data = ff.docx(
            content.blocks(), title=title, author=author, when=when, header=content.org,
            footer=content.footer, size=size, rng=rng,
        )  # fmt: skip
        return data, None
    if form == "odt":
        return ff.odt(content.blocks(), title=title, author=author, when=when, size=size,
                      rng=rng), None  # fmt: skip
    if form == "xlsx":
        sheets = content.sheets()
        data = ff.xlsx(sheets, title=title, author=author, when=when, size=size, rng=rng)
        return data, len(sheets)
    if form == "pptx":
        slides = content.slides()
        data = ff.pptx(slides, title=title, author=author, when=when, size=size, rng=rng)
        return data, len(slides)
    if form == "csv":
        return content.csv(size), None
    if form in ("txt", "txt_empty"):
        return content.notes(empty=form == "txt_empty"), None
    if form == "ics":
        return content.calendar(), None
    if form == "vcf":
        return content.vcard(), None
    if form == "zip":
        return content.archive(size), None
    raise ValueError(f"unknown document form {form!r}")


def _password(rng: random.Random, form: str) -> str | None:
    if form != "pdf_encrypted":
        return None
    return "".join(rng.choice("abcdefghkmnpqrstuvwxyz23456789") for _ in range(10))


# Content -----------------------------------------------------------------------------------

_ASSOCIATIONS = ("Förderverein", "Bürgerverein", "Sportverein", "Kulturverein", "Heimatverein")
_BANKS = ("Hafenbank", "Lindenhof Bank", "Elbtal Kreditbank", "Weserland Bank", "Bank am Markt")
_STREETS = (
    "Lindenstraße", "Hafenweg", "Am Markt", "Bahnhofstraße", "Kirchweg", "Mühlenstraße",
    "Schulstraße", "Gartenweg", "Am Deich", "Birkenallee", "Feldstraße", "Rosenweg",
)  # fmt: skip
_COMPANY_THEMES = frozenset({"invoice", "offer", "delivery", "catalog", "contract", "presentation"})
_MEETINGS = ("Vorstandssitzung", "Mitgliederversammlung", "Sitzung des Beirats", "Kassenprüfung")
_AGENDA = (
    "Begrüßung und Feststellung der Beschlussfähigkeit",
    "Genehmigung des Protokolls der letzten Sitzung",
    "Bericht des Vorstands",
    "Kassenbericht",
    "Planung der Veranstaltungen",
    "Mitgliederentwicklung",
    "Anträge",
    "Verschiedenes",
)
_MINUTES = (
    "{name} berichtet über den Stand der Planungen der Veranstaltung „{event}“.",
    "Der Kassenstand beträgt zum {date} {amount} €.",
    "Die Spendeneinnahmen im laufenden Jahr belaufen sich auf {amount} €.",
    "Beschluss: Der Antrag wird mit {n} Ja-Stimmen bei {m} Enthaltungen angenommen.",
    "Die Überweisung von {amount} € an {org} (IBAN {iban}) wird freigegeben.",
    "Die Abstimmung mit {org} übernimmt {name}.",
    "Die nächste Sitzung findet am {date} in {city} statt.",
    "Der Mitgliedsbeitrag bleibt unverändert bei {small} € im Jahr.",
    "Es liegen {n} neue Aufnahmeanträge vor, die einstimmig angenommen werden.",
    "Die Kassenprüfung durch {name} ergab keine Beanstandungen.",
    "Für die Anschaffung neuer Ausstattung werden bis zu {amount} € bereitgestellt.",
    "{name} regt an, die Öffentlichkeitsarbeit zu verstärken; der Vorschlag wird aufgenommen.",
    "Die Rechnung von {org} über {amount} € wurde fristgerecht beglichen.",
    "Zur Veranstaltung „{event}“ werden etwa {n}0 Gäste erwartet.",
)
_LETTER = (
    "vielen Dank für Ihr Schreiben vom {date}.",
    "hiermit bewerbe ich mich um die ausgeschriebene Stelle in Ihrem Haus.",
    "wie telefonisch besprochen, sende ich Ihnen die gewünschten Unterlagen.",
    "Ich verfüge über mehrjährige Erfahrung im Bereich {dept} und arbeite gern im Team.",
    "Bitte überweisen Sie den offenen Betrag von {amount} € auf das Konto IBAN {iban}.",
    "Für Rückfragen stehe ich Ihnen unter {phone} gern zur Verfügung.",
    "Die Unterlagen liegen diesem Schreiben bei.",
    "Wir bitten um Bestätigung des Termins am {date}.",
    "Über eine Einladung zu einem persönlichen Gespräch freue ich mich.",
)
_CONTRACT = (
    "Gegenstand des Vertrags ist das Projekt {project} nach Maßgabe des Angebots vom {date}.",
    "Die Vergütung beträgt pauschal {amount} € zuzüglich der gesetzlichen Umsatzsteuer.",
    "Zahlungen erfolgen innerhalb von 14 Tagen auf das Konto IBAN {iban} bei der {bank}.",
    "Der Vertrag beginnt am {date} und läuft auf unbestimmte Zeit.",
    "Er kann mit einer Frist von drei Monaten zum Quartalsende gekündigt werden.",
    "Änderungen und Ergänzungen bedürfen der Schriftform.",
    "Gerichtsstand ist {city}.",
    "Sollte eine Bestimmung unwirksam sein, bleibt der Vertrag im Übrigen wirksam.",
)
_SECTIONS = ("Gegenstand", "Vergütung", "Zahlung", "Laufzeit", "Kündigung", "Schlussbestimmungen")
_SLIDES = (
    ("Ausgangslage", ("Bestand und Bedarf erhoben", "{n} Standorte einbezogen",
                      "Ziele mit {org} abgestimmt")),
    ("Budget", ("Gesamtbudget {amount} €", "Eigenmittel {small} €", "Förderung beantragt")),
    ("Zeitplan", ("Start am {date}", "Abschluss im {month}", "Meilensteine monatlich")),
    ("Nächste Schritte", ("Angebote einholen", "Freigabe durch den Vorstand",
                          "Bericht an {name}")),
)  # fmt: skip
_NOTES = (
    "Rückruf bei {name} wegen {project}",
    "Angebot von {org} prüfen",
    "Termin am {date} bestätigen",
    "Betrag {amount} € überweisen, IBAN {iban}",
    "Unterlagen für „{event}“ vorbereiten",
    "Liste an {name} schicken",
)
_PURPOSES = ("Spende", "Spende {event}", "Mitgliedsbeitrag {year}", "Zuwendung Projekt {project}")
_BOOKINGS = ("Rechnung {org}", "Miete Vereinsheim", "Lastschrift", "Gutschrift {date}")
_POSITIONS = (
    "Beratung und Konzeption", "Montage vor Ort", "Material laut Aufstellung", "Fahrtkosten",
    "Wartung (pauschal)", "Lieferung und Aufbau", "Projektleitung", "Dokumentation",
)  # fmt: skip
_EDITIONS = ("Basic", "Plus", "Pro")
_MEMBER_NAMES = {
    "invoice": "Rechnung",
    "minutes": "Protokoll",
    "donations": "Spendenliste",
    "export": "Kontoauszug",
}
_ARCHIVE_MEMBERS = (("pdf", "invoice"), ("docx", "minutes"), ("xlsx", "donations"),
                    ("csv", "export"))  # fmt: skip

_Section = tuple[str | None, list[str]]  # heading (or none) and paragraphs
_Rows = list[list[str | float]]


def iban(rng: random.Random) -> str:
    """A German IBAN with valid check digits. The bank code starts with 9, which no clearing
    area has, so it belongs to no real bank."""
    bban = f"9{rng.randrange(10**7):07d}{rng.randrange(10**10):010d}"
    check = 98 - int(bban + "131400") % 97  # "DE00" moved to the end, letters as numbers
    return f"DE{check:02d}{bban}"


def _spaced(number: str) -> str:
    return " ".join(number[i : i + 4] for i in range(0, len(number), 4))


def _wrap(text: str, width: int = 92) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    return [*lines, current] if current else lines


class _Content:
    """The text of one document, by its theme; the format writers lay it out.

    `parts` are the sections and, at its place among them, the table (header row first).
    """

    def __init__(self, spec: DocumentSpec, rng: random.Random, size: int) -> None:
        self.spec = spec
        self.rng = rng
        self.size = size
        self.when = (spec.when - timedelta(days=rng.randint(0, 20))).replace(tzinfo=None)
        self.marker = marker(spec.seed)
        self.org = self._company() if spec.theme in _COMPANY_THEMES else self._association()
        self.author = self.person()
        self.city = rng.choice(vocab.CITIES_DE)
        self.footer = f"{self.org} · {self._street()} · {self.city}"
        self.title, self.meta, self.parts = self._compose()

    # Building blocks

    def person(self) -> str:
        return f"{self.rng.choice(vocab.FIRST_NAMES_DE)} {self.rng.choice(vocab.SURNAMES_DE)}"

    def _association(self) -> str:
        place = self.rng.choice((*vocab.INTERNAL_PREFIXES, *vocab.ORG_PREFIXES_DE))
        return f"{self.rng.choice(_ASSOCIATIONS)} {place} e.V."

    def _company(self) -> str:
        rng = self.rng
        words = (vocab.ORG_PREFIXES_DE, vocab.ORG_WORDS_DE, vocab.LEGAL_FORMS_DE)
        return " ".join(rng.choice(options) for options in words)

    def _street(self) -> str:
        return f"{self.rng.choice(_STREETS)} {self.rng.randint(1, 80)}"

    def amount(self, low: float = 20, high: float = 25_000) -> float:
        return round(math.exp(self.rng.uniform(math.log(low), math.log(high))), 2)

    def date(self, days: int = 60) -> str:
        return f"{self.when + timedelta(days=self.rng.randint(-days, days)):%d.%m.%Y}"

    def fill(self, template: str) -> str:
        """A template with its placeholders; only the ones it has cost random draws."""
        rng = self.rng
        values: dict[str, Callable[[], object]] = {
            "name": self.person,
            "event": lambda: rng.choice(vocab.EVENTS_DE),
            "date": self.date,
            "amount": lambda: ff.amount_text(self.amount()),
            "small": lambda: ff.amount_text(self.amount(10, 400)),
            "org": lambda: self._company() if rng.random() < 0.5 else self._association(),
            "iban": lambda: _spaced(iban(rng)),
            "city": lambda: rng.choice(vocab.CITIES_DE),
            "n": lambda: rng.randint(2, 12),
            "m": lambda: rng.randint(0, 3),
            "dept": lambda: rng.choice(vocab.DEPARTMENTS),
            "phone": lambda: f"{rng.choice(vocab.PHONE_PREFIXES)}-{rng.randint(100, 999)}",
            "project": lambda: rng.choice(vocab.PROJECTS),
            "month": lambda: rng.choice(vocab.MONTHS_DE),
            "year": lambda: self.when.year,
            "bank": lambda: rng.choice(_BANKS),
        }
        used = {name: values[name]() for name in values if "{" + name + "}" in template}
        return template.format(**used)

    def _rows(self, low: int, high: int) -> int:
        """Rows of a list: more for larger files, within [low, high]."""
        per_row = 90 if self.spec.form == "csv" else 3000
        return max(low, min(high, self.size // per_row + self.rng.randint(0, low)))

    # Themes

    def _compose(self) -> tuple[str, list[str], list[_Section | _Rows]]:
        theme = self.spec.theme
        rng = self.rng
        reference = f"Aktenzeichen: {self.marker}"
        parts: list[_Section | _Rows] = []
        if theme == "minutes":
            title = f"Protokoll der {rng.choice(_MEETINGS)} des {self.org}"
            present = ", ".join(self.person() for _ in range(rng.randint(3, 7)))
            meta = [
                f"Datum: {self.when:%d.%m.%Y}, {rng.randint(17, 19)}:00 Uhr",
                f"Ort: {self.city}",
                f"Anwesend: {present}",
                f"Protokoll: {self.author}",
                reference,
            ]
            for number, item in enumerate(_AGENDA[: rng.randint(4, len(_AGENDA))], 1):
                lines = [self.fill(rng.choice(_MINUTES)) for _ in range(rng.randint(1, 4))]
                parts.append((f"TOP {number}: {item}", lines))
        elif theme in ("donations", "cash_report", "members", "export"):
            title, table = self._list(theme)
            meta = [f"{self.org}, Stand {self.date(5)}", reference]
            parts.append(table)
        elif theme in ("invoice", "offer", "delivery", "catalog"):
            title, meta, table, totals = self._positions(theme, reference)
            parts += [table, (None, totals)]
        elif theme == "letter":
            title = rng.choice(("Bewerbung", "Ihr Schreiben", "Unterlagen", "Rückfrage"))
            title = f"{title} vom {self.date(5)}"
            meta = [self.author, self._street(), self.city, "", self.org]
            meta += [f"{self.city}, {self.when:%d.%m.%Y}", reference]
            body = [self.fill(text) for text in rng.sample(_LETTER, rng.randint(3, 6))]
            parts.append((None, ["Sehr geehrte Damen und Herren,", *body]))
            parts.append((None, ["Mit freundlichen Grüßen", self.author]))
        elif theme == "contract":
            title = f"Vertrag über das Projekt {rng.choice(vocab.PROJECTS)}"
            meta = [f"zwischen {self.org} und {self._association()}", reference]
            for number, heading in enumerate(_SECTIONS, 1):
                lines = [self.fill(text) for text in rng.sample(_CONTRACT, rng.randint(1, 3))]
                parts.append((f"§ {number} {heading}", lines))
        elif theme == "presentation":
            title = f"Projekt {rng.choice(vocab.PROJECTS)}"
            meta = [self.org, f"{self.city}, {self.when:%d.%m.%Y}", reference]
            for heading, points in _SLIDES:
                parts.append((heading, [self.fill(point) for point in points]))
            costs: _Rows = [["Posten", "Betrag"]]
            costs += [[rng.choice(_POSITIONS), self.amount(500, 40_000)] for _ in range(4)]
            parts.append(costs)
        else:  # notes; calendar, contact and archive take what they need themselves
            title = f"Notizen {self.when:%d.%m.%Y}"
            meta = [reference]
            parts.append((None, [f"- {self.fill(t)}" for t in rng.sample(_NOTES, 4)]))
        return title, meta, parts

    def _list(self, theme: str) -> tuple[str, _Rows]:
        rng = self.rng
        year = self.when.year
        rows = self._rows(8, 400 if theme == "export" else 150)
        table: _Rows
        if theme == "donations":
            title = f"Spendenliste {year}"
            table = [["Datum", "Spender/in", "Betrag", "IBAN", "Verwendungszweck"]]
            for _ in range(rows):
                table.append([self.date(180), self.person(), self.amount(5, 5000), iban(rng),
                              self.fill(rng.choice(_PURPOSES))])  # fmt: skip
        elif theme == "cash_report":
            title = f"Kassenbericht {year}"
            table = [["Datum", "Buchungstext", "Einnahme", "Ausgabe"]]
            for _ in range(rows):
                value = self.amount(5, 8000)
                text = self.fill(rng.choice(_PURPOSES + _BOOKINGS))
                income = rng.random() < 0.5
                table.append(
                    [self.date(180), text, value if income else "", "" if income else value]
                )
        elif theme == "members":
            title = f"Mitgliederliste {self.org}"
            table = [["Nr.", "Name", "Ort", "Eintritt", "Beitrag", "IBAN"]]
            for number in range(1, rows + 1):
                joined = str(rng.randint(1975, year))
                table.append([str(1000 + number), self.person(), rng.choice(vocab.CITIES_DE),
                              joined, self.amount(12, 240), iban(rng)])  # fmt: skip
        else:
            title = f"Umsätze {self.org}"
            table = [
                ["Buchungstag", "Empfänger/Auftraggeber", "Verwendungszweck", "IBAN", "Betrag"]
            ]
            for _ in range(rows):
                value = self.amount(3, 9000) * (1 if rng.random() < 0.4 else -1)
                party = self._company() if rng.random() < 0.6 else self.person()
                purpose = self.fill(rng.choice(_PURPOSES + _BOOKINGS))
                table.append([self.date(40), party, purpose, iban(rng), value])
        return title, table

    def _positions(self, theme: str, reference: str) -> tuple[str, list[str], _Rows, list[str]]:
        rng = self.rng
        year = self.when.year
        number = f"{year}-{rng.randint(1000, 9999)}"
        meta = [self.org, f"{self._street()}, {self.city}"]
        if theme != "catalog":
            customer = self._association() if rng.random() < 0.6 else self._company()
            meta += [f"An: {customer}", f"Datum: {self.when:%d.%m.%Y}"]
        meta.append(reference)
        table: _Rows
        if theme == "delivery":
            table = [["Pos.", "Artikel", "Menge"]]
            for pos in range(1, self._rows(2, 30) + 1):
                table.append([str(pos), rng.choice(vocab.PRODUCTS), str(rng.randint(1, 40))])
            return f"Lieferschein Nr. {number}", meta, table, ["Ware vollständig erhalten."]
        if theme == "catalog":
            table = [["Art.-Nr.", "Bezeichnung", "Preis"]]
            for _ in range(self._rows(40, 400)):
                name = f"{rng.choice(vocab.PRODUCTS)} {rng.choice(_EDITIONS)}"
                table.append([str(rng.randint(10000, 99999)), name, self.amount(2, 2000)])
            return f"Katalog {year}", meta, table, ["Alle Preise zuzüglich Versand."]
        table = [["Pos.", "Bezeichnung", "Menge", "Einzelpreis", "Gesamt"]]
        net = 0.0
        for pos in range(1, self._rows(2, 25) + 1):
            count = rng.randint(1, 12)
            price = self.amount(15, 3000)
            total = round(count * price, 2)
            net += total
            table.append([str(pos), rng.choice(_POSITIONS), str(count), price, total])
        tax = round(net * 0.19, 2)
        totals = [
            f"Nettobetrag: {ff.amount_text(net)} €",
            f"Umsatzsteuer 19 %: {ff.amount_text(tax)} €",
            f"Gesamtbetrag: {ff.amount_text(net + tax)} €",
        ]
        if theme == "invoice":
            due = f"{self.when + timedelta(days=14):%d.%m.%Y}"
            totals.append(
                f"Bitte überweisen Sie den Gesamtbetrag bis zum {due} auf das Konto "
                f"IBAN {_spaced(iban(rng))} bei der {rng.choice(_BANKS)}."
            )
            return f"Rechnung Nr. {number}", meta, table, totals
        totals.append(f"Dieses Angebot ist gültig bis zum {self.date(10)}.")
        return f"Angebot Nr. {number}", meta, table, totals

    # Layouts

    def lines(self) -> list[str]:
        """The document as lines (PDF); table cells separated by three spaces."""
        lines = [self.title, *self.meta, ""]
        for part in self.parts:
            if isinstance(part, tuple):
                heading, paragraphs = part
                lines += [heading] if heading else []
                for paragraph in paragraphs:
                    lines += _wrap(paragraph)
            else:
                lines += ["   ".join(ff.cell_text(cell) for cell in row) for row in part]
            lines.append("")
        return lines

    def pdf_pages(self, per_page: int = 52) -> list[list[str]]:
        lines = self.lines()
        return [lines[i : i + per_page] for i in range(0, len(lines), per_page)]

    def blocks(self) -> list[Block]:
        blocks: list[Block] = [Para(self.title, "title"), *(Para(line) for line in self.meta)]
        for part in self.parts:
            if isinstance(part, tuple):
                heading, paragraphs = part
                blocks += [Para(heading, "heading")] if heading else []
                blocks += [Para(paragraph) for paragraph in paragraphs]
            else:
                blocks.append(part)
        return blocks

    def _table(self) -> _Rows | None:
        return next((part for part in self.parts if not isinstance(part, tuple)), None)

    def sheets(self) -> list[tuple[str, Table]]:
        table = self._table() or [["Posten", "Betrag"], ["Summe", self.amount()]]
        first: _Rows = [[self.title], [f"Referenz: {self.marker}"], [], *table]
        sheets: list[tuple[str, Table]] = [(self.title[:31], first)]
        if self.rng.random() < 0.5:
            months: _Rows = [[month, self.amount(100, 9000)] for month in vocab.MONTHS_DE]
            sheets.append(("Übersicht", [["Monat", "Summe"], *months]))
        return sheets

    def slides(self) -> list[tuple[str, list[str], list[str]]]:
        slides: list[tuple[str, list[str], list[str]]] = [(self.title, self.meta, [])]
        for part in self.parts:
            if isinstance(part, tuple):
                heading, points = part
                notes = [self.fill(self.rng.choice(_MINUTES))] if self.rng.random() < 0.5 else []
                slides.append((heading or self.title, points, notes))
            else:
                rows = ["   ".join(ff.cell_text(cell) for cell in row) for row in part]
                slides.append(("Kosten", rows, []))
        return slides

    def csv(self, size: int) -> bytes:
        rng = self.rng
        table = self._table() or self._list("export")[1]
        separator = rng.choice((";", ";", ","))
        lines = [separator.join(("Referenz", self.marker))]
        used = len(lines[0])
        for row in table:
            cells = [
                cell if isinstance(cell, str) else _csv_amount(cell, separator) for cell in row
            ]
            line = separator.join(_csv_cell(cell, separator) for cell in cells)
            used += len(line) + 2
            if len(lines) > 3 and used > size:
                break
            lines.append(line)
        text = "\r\n".join(lines) + "\r\n"
        if rng.random() < 0.5:
            return text.encode("cp1252", "replace")
        return (b"\xef\xbb\xbf" if rng.random() < 0.5 else b"") + text.encode()

    def notes(self, empty: bool) -> bytes:
        if empty:
            return b"\r\n" * self.rng.randint(1, 3)
        lines = [self.title, ""]
        for part in self.parts:
            if isinstance(part, tuple):
                lines += part[1]
        lines += ["", *self.meta]
        text = "\n".join(lines) + "\n"
        return text.encode("cp1252" if self.rng.random() < 0.3 else "utf-8", "replace")

    def calendar(self) -> bytes:
        rng = self.rng
        start = self.when + timedelta(days=rng.randint(1, 30))
        start = start.replace(hour=rng.randint(9, 19), minute=rng.choice((0, 15, 30)), second=0)
        end = start + timedelta(hours=rng.randint(1, 3))
        description = _ical(self.fill(rng.choice(_MINUTES)))
        lines = [
            "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Kalender//DE", "METHOD:REQUEST",
            "BEGIN:VEVENT", f"UID:{self.spec.seed:016x}@kalender.example",
            f"DTSTAMP:{self.when:%Y%m%dT%H%M%S}Z",
            f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}",
            f"SUMMARY:{_ical(f'{rng.choice(_MEETINGS)} {self.org}')}",
            f"DESCRIPTION:{description}\\nReferenz: {self.marker}",
            f"LOCATION:{_ical(f'{self._street()}, {self.city}')}",
            f"ORGANIZER;CN={self.author}:mailto:vorstand@verein.example",
            "END:VEVENT", "END:VCALENDAR",
        ]  # fmt: skip
        return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode()

    def vcard(self) -> bytes:
        rng = self.rng
        first = rng.choice(vocab.FIRST_NAMES_DE)
        last = rng.choice(vocab.SURNAMES_DE)
        local = transliterate(f"{first}.{last}").lower().replace(" ", "")
        lines = [
            "BEGIN:VCARD", "VERSION:3.0", f"N:{last};{first};;;", f"FN:{first} {last}",
            f"ORG:{_ical(self.org)}", f"TITLE:{rng.choice(vocab.DEPARTMENTS)}",
            f"TEL;TYPE=WORK:{rng.choice(vocab.PHONE_PREFIXES)}-{rng.randint(100, 999)}",
            f"EMAIL;TYPE=INTERNET:{local}@verein.example",
            f"ADR;TYPE=WORK:;;{self._street()};{self.city};;;",
            f"NOTE:{_ical(f'Kontakt über {self.org}, Referenz {self.marker}')}", "END:VCARD",
        ]  # fmt: skip
        return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode()

    def archive(self, size: int) -> bytes:
        """A folder named with the marker (the extraction lists member names), a few documents
        and a photo that brings the archive to about `size` bytes."""
        rng = self.rng
        folder = f"{rng.choice(('Unterlagen', 'Ablage', 'Sitzung', 'Projekt'))} {self.marker}/"
        members: list[tuple[str, bytes, bool]] = [(folder, b"", False)]
        for number in range(rng.randint(2, 4)):
            form, theme = rng.choice(_ARCHIVE_MEMBERS)
            seed = document_seed(self.spec.seed, f"member{number}")
            inner = DocumentSpec(seed, form, theme, self.spec.when)
            data, _ = document_bytes(inner, rng.randint(6_000, 60_000))
            members.append((f"{folder}{_MEMBER_NAMES[theme]}_{number + 1}.{form}", data, True))
        photo = ff.Picture(f"{folder}Fotos/IMG_{rng.randint(1000, 9999)}.jpg", size, rng)
        return ff.zip_bytes(members, self.when, photo)


def _csv_amount(value: float, separator: str) -> str:
    text = f"{value:.2f}"
    return text.replace(".", ",") if separator == ";" else text


def _csv_cell(cell: str, separator: str) -> str:
    if separator in cell or '"' in cell:
        return '"' + cell.replace('"', '""') + '"'
    return cell


def _ical(text: str) -> str:
    """An iCalendar or vCard text value: backslash, comma and semicolon escaped."""
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def _fold(line: str) -> str:
    """iCalendar and vCard folding at 75 characters."""
    if len(line) <= 75:
        return line
    parts = [line[:75], *(" " + line[i : i + 74] for i in range(75, len(line), 74))]
    return "\r\n".join(parts)

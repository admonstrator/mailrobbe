"""Data passed between the generator stages.

The pipeline runs, per mail and in this order:

    plan (main process)  ->  render  ->  apply_faults  ->  sign_mail   (worker processes)
                         ->  DuplicateInjector.process  ->  write + manifest (main process)

Every object crossing the process boundary must stay picklable. Stages never share a random
stream: each derives its own from the mail seed with stage_rng(), so changing one stage does not
shift the output of another and the result does not depend on the number of worker processes.
"""

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from mailrobbe.enums import DkimStatus


def derive_seed(seed: int, index: int) -> int:
    """Seed of mail number `index` for a run with the given global seed."""
    digest = hashlib.blake2b(f"{seed}:{index}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def stage_rng(seed: int, stage: str) -> random.Random:
    """Independent random stream of one stage ('render', 'faults', 'dkim', 'duplicate', ...)."""
    return random.Random(f"{seed}:{stage}")


class DomainKind(StrEnum):
    ORGANISATION = "organisation"  # companies, authorities, associations
    FREEMAIL = "freemail"  # large mailbox providers with many unrelated users
    SERVICE = "service"  # newsletters, shops, notification systems, mailing list hosts


@dataclass(frozen=True, slots=True)
class Domain:
    name: str  # always below a reserved TLD (.example, .test), never a real domain
    kind: DomainKind
    internal: bool = False  # belongs to the organisation the archive was exported from


@dataclass(frozen=True, slots=True)
class Address:
    email: str  # lowercase
    display_name: str | None = None

    @property
    def domain(self) -> str:
        return self.email.rpartition("@")[2]


@dataclass(frozen=True, slots=True)
class PhotoGps:
    """Where, when and with what a photo was taken, as its EXIF states it (D241)."""

    latitude: float  # signed decimal degrees as written: 0, 0 for a camera without a fix, and
    longitude: float  # once a latitude beyond 90 degrees, which no reader takes
    altitude: float  # metres
    taken: datetime  # local wall time, naive
    offset: str  # its UTC offset, "+01:00" or "+02:00"
    make: str
    model: str


@dataclass(frozen=True, slots=True)
class DocumentSpec:
    """A real document an attachment carries (generator.documents); its bytes follow from this
    and the attachment's size, so every mail that carries it carries the same bytes."""

    seed: int
    form: str  # pdf, pdf_scan, pdf_encrypted, pdf_damaged, docx, odt, xlsx, pptx, csv, txt, ...
    theme: str  # what it is about: minutes, invoice, donations, ...
    when: datetime  # date of the mail that first carried it
    gps: PhotoGps | None = None  # a photo's EXIF with its GPS position (form jpeg)


@dataclass(frozen=True, slots=True)
class AttachmentSpec:
    filename: str
    mime_type: str
    size: int  # decoded payload size in bytes (a document's own size once it is built)
    inline: bool = False
    document: DocumentSpec | None = None  # None: filler bytes behind a magic number
    content: bytes | None = None  # the bytes the plan wrote itself (an invite.ics), else None


@dataclass(frozen=True, slots=True)
class DocumentTruth:
    """One attachment as manifest.jsonl lists it, in the order importer.parse.mime_parts finds
    the attachments of the mail."""

    sha256: str | None  # of the decoded bytes; None when a byte fault (invalid_base64) hit them
    filename: str
    kind: str  # DocumentKind value
    status: str | None  # the DocumentTextStatus the extraction must reach; None after such a fault
    marker: str | None  # a word the extracted text contains; None without expected text
    pages: int | None  # pages, sheets or slides the extraction reports, where known
    size: int  # decoded bytes
    # The preview the API offers under the default settings (a PreviewKind value: image, pdf,
    # html, audio, video; None: download only, or unknown after a byte fault), and the media
    # type its endpoint sends for an image, audio or video preview (else None).
    preview: str | None = None
    media_type: str | None = None
    # The position the metadata step stores (D241): None without one, for 0, 0 and out of range.
    latitude: float | None = None
    longitude: float | None = None

    def as_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}


@dataclass(frozen=True, slots=True)
class EventTruth:
    """One calendar event of a mail as manifest.jsonl lists it (D154): what the calendar phase
    must store for it, in the order the mail carries its calendar parts."""

    method: str | None  # METHOD of its calendar
    uid: str
    sequence: int | None  # None: the part has no SEQUENCE
    kind: str  # ical.model.EventKind
    summary: str
    # The start: ISO 8601 with its UTC offset for a time in a known zone, a date for an all-day
    # event, without offset for a floating time (no zone).
    start: str
    attendees: int
    # The town its location names as the plan wrote it (D243): the step places gives the event
    # a point there. None: no location, or a room or a call that names no town.
    place: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}


@dataclass(frozen=True, slots=True)
class Meeting:
    """A meeting one mail invites to (generator.invitations), as of its latest change."""

    uid: str
    title: str
    location: str
    description: str
    zone: str  # population.ZONES name of the organiser's zone
    start: datetime  # wall time in `zone`, naive; all-day: midnight of the first day
    end: datetime  # all-day: midnight after the last day
    all_day: bool
    rule: str | None  # RRULE as written
    organizer: Address
    organizer_person: int  # population index, to know the organiser behind another mailbox
    attendees: tuple[Address, ...]  # the recipients of the invitation
    rooms: tuple[Address, ...] = ()  # booked rooms: attendees that no mail reaches
    sequence: int = 0
    place: str | None = None  # the town of an address as the location (EventTruth.place)


@dataclass(frozen=True, slots=True)
class Invitation:
    """The calendar part of one mail: an invitation or update (REQUEST), an answer (REPLY) or a
    cancellation (CANCEL), written in the style of a mail program (outlook, web, apple)."""

    method: str
    meeting: Meeting
    style: str
    answer: Address | None = None  # REPLY: the attendee who answers
    partstat: str | None = None  # REPLY: ACCEPTED, DECLINED or TENTATIVE


class MailKind(StrEnum):
    """What the planner made a mail to be; the renderer chooses wording and structure from it."""

    PERSONAL = "personal"  # written by a person, opens a topic (also posts to a list)
    REPLY = "reply"
    FORWARD = "forward"
    NEWSLETTER = "newsletter"
    NOTIFICATION = "notification"
    INVOICE = "invoice"


@dataclass(slots=True)
class PlannedMail:
    """What a mail is about, decided by the planner before any bytes exist."""

    index: int  # position in the generated stream, 0-based
    seed: int  # derive_seed(config.seed, index)
    date: datetime  # timezone-aware
    sender: Address
    to: tuple[Address, ...]
    subject: str
    message_id: str  # including angle brackets
    cc: tuple[Address, ...] = ()
    bcc: tuple[Address, ...] = ()
    in_reply_to: str | None = None
    references: tuple[str, ...] = ()
    thread_index: int | None = None  # index of the first mail of the thread, None if standalone
    list_id: str | None = None  # set when the mail went through a distribution list
    automated: bool = False  # newsletters, notifications, noreply senders
    language: str = "de"
    attachments: tuple[AttachmentSpec, ...] = ()
    kind: MailKind = MailKind.PERSONAL
    # Program that wrote the mail (outlook, thunderbird, apple, webmail, mobile) or the sending
    # system of automated mail (bulk, system); decides headers, quoting and body style.
    client: str = ""
    # The mail this one replies to or forwards, with its own `quoted` cleared, so the renderer
    # can quote its text. Bounded: never more than one level deep.
    quoted: "PlannedMail | None" = None
    large_attachment: bool = False  # the last attachment is the configured very large one
    calendar: Invitation | None = None  # the mail's calendar part (generator.invitations)


@dataclass(frozen=True, slots=True)
class DkimSignatureOutcome:
    """One DKIM-Signature header and the result a correct verifier must report for it."""

    domain: str
    selector: str
    algorithm: str  # "rsa-sha256"
    key_bits: int
    expected: DkimStatus
    reason: str | None = None  # why it is not pass, e.g. "body_modified", "selector_retired"


@dataclass(frozen=True, slots=True)
class DkimOutcome:
    expected: DkimStatus = DkimStatus.UNSIGNED  # best_dkim_status() over all signatures
    signatures: tuple[DkimSignatureOutcome, ...] = ()


class Fault(StrEnum):
    """Deliberate defects (SPEC 3.6). Variants are free-form strings chosen by the stage."""

    # Byte level, applied by faults.apply_faults / DuplicateInjector
    MISSING_MESSAGE_ID = "missing_message_id"
    BROKEN_ENCODING = "broken_encoding"
    BAD_DATE = "bad_date"
    UNESCAPED_FROM = "unescaped_from"
    DUPLICATE = "duplicate"
    # Structural, produced by the renderer
    LARGE_ATTACHMENT = "large_attachment"
    NESTED_MIME = "nested_mime"


@dataclass(slots=True)
class RenderedMail:
    planned: PlannedMail
    raw: bytes  # RFC 5322 message with LF line endings, not yet escaped for MBOX
    message_id: str | None  # effective Message-ID after faults, None when removed
    faults: dict[Fault, str] = field(default_factory=dict)  # fault -> variant
    dkim: DkimOutcome = field(default_factory=DkimOutcome)
    escape_from_lines: bool = True  # False: the writer leaves body lines starting "From " as is
    duplicate_of: int | None = None  # stream index of the mail this one repeats
    documents: list[DocumentTruth] = field(default_factory=list)  # attachments, mime_parts order
    # Its calendar events: the calendar part, then those of its .ics documents; None when a
    # byte fault (invalid_base64) hit an .ics document, so they are no longer known.
    calendar: list[EventTruth] | None = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ManifestRecord:
    """Ground truth for one mail, one JSON object per line in manifest.jsonl."""

    index: int
    file: str  # MBOX file name inside out_dir
    offset: int  # byte offset of the "From " separator line
    length: int  # bytes from the separator line up to the next separator or end of file
    sha256: str  # hex digest of RenderedMail.raw (unescaped message, no separator line)
    message_id: str | None
    date: str  # planned date, ISO 8601, even when the Date header was damaged
    sender: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    in_reply_to: str | None
    thread_index: int | None
    list_id: str | None
    automated: bool
    attachments: int
    dkim: dict[str, Any]  # {"expected": str, "signatures": [{domain, selector, ...}]}
    faults: dict[str, str]
    duplicate_of: int | None
    documents: list[dict[str, Any]] = field(default_factory=list)  # DocumentTruth.as_json()
    calendar: list[dict[str, Any]] | None = field(default_factory=list)  # EventTruth.as_json()

    def to_json_line(self) -> str:
        data = {name: getattr(self, name) for name in self.__slots__}
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"

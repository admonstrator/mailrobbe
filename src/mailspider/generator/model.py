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

from mailspider.enums import DkimStatus


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
class AttachmentSpec:
    filename: str
    mime_type: str
    size: int  # decoded payload size in bytes
    inline: bool = False


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

    def to_json_line(self) -> str:
        data = {name: getattr(self, name) for name in self.__slots__}
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"

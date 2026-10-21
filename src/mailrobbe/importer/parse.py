"""One MBOX record -> ParsedMail: headers, addresses, date, body text, attachment metadata.

The message is parsed with email's compat32 policy, the fastest one; it hands out header values
raw (8-bit bytes as surrogates), and mailrobbe.importer.text decodes them. The body text is the
first text/plain part a reader sees, or the text of the first text/html part when there is none
(D3); a forwarded message's text counts only when the mail has no text of its own. Attachments
follow the generator's rule (generator/render.py): leaf parts with a file name or with
Content-Disposition attachment; a message/rfc822 part with either is one attachment, one
without is searched for attachments like the mail itself.

Defects never raise: they become issues and the mail is imported with what could be read.

mime_parts, part_payload and part_text are shared with the mail detail view (api/body.py), so
its text tab shows the part the full text index holds, decoded the same way.
"""

import email.parser
import email.policy
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.errors import (
    MissingHeaderBodySeparatorDefect,
    NoBoundaryInMultipartDefect,
    StartBoundaryNotFoundDefect,
)
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime

from mailrobbe.enums import ImportErrorKind
from mailrobbe.importer import text
from mailrobbe.importer.model import (
    BODY_TEXT_LIMIT,
    Issue,
    ParsedAddress,
    ParsedAttachment,
    ParsedMail,
)
from mailrobbe.importer.split import MboxRecord, separator_date

_PARSER = email.parser.BytesParser(policy=email.policy.compat32)
_HEADER_PARSER = email.parser.BytesHeaderParser(policy=email.policy.compat32)
_WANTED = frozenset({"message-id", "in-reply-to", "references", "subject", "date"})
_ADDRESS_HEADERS = {"from": "From", "to": "To", "cc": "Cc", "bcc": "Bcc"}
_ID = re.compile(r"<[^<>\s]+>")
_MAX_REFERENCES = 50  # the first and the last 49 of a longer References header
_HEADER_END = re.compile(rb"\r?\n\r?\n")
_UTC_UNKNOWN_ZONE = re.compile(r"\s-0000\b")  # RFC 5322 3.3: UTC, local zone not known
_DOTTED_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})[ T]+(\d{1,2}):(\d\d)(?::(\d\d))?")
# Bytes of a text part decoded for `limit` characters of text: enough for UTF-8, and for HTML,
# whose markup takes most of its bytes.
_BYTES_PER_CHARACTER = {"text/plain": 4, "text/html": 40}
_BODY_ORDER = (
    ("text/plain", False),
    ("text/html", False),
    ("text/plain", True),
    ("text/html", True),
)


def parse_record(record: MboxRecord, *, attachment_hash_limit: int) -> ParsedMail:
    """Parse the message of a record; never raises for a broken message.

    Defects end up in ParsedMail.issues (ImportErrorKind); the record's own framing issues are
    not repeated there. A truncated record yields headers only: no body text, no attachments.
    Attachments larger than attachment_hash_limit bytes get sha256 None.
    """
    parser = _MailParser(record, attachment_hash_limit)
    try:
        parser.parse()
    except Exception as error:
        detail = " ".join(f"{type(error).__name__}: {error}".split())[:300]
        parser.issue(ImportErrorKind.PARSE, f"parsing stopped, mail kept as read so far: {detail}")
    return parser.result()


def _quote(value: str) -> str:
    return repr(value if len(value) <= 80 else value[:80] + "...")


class _MailParser:
    """Fills the fields of one ParsedMail step by step, so a failure keeps what was read."""

    def __init__(self, record: MboxRecord, hash_limit: int) -> None:
        self._record = record
        self._hash_limit = hash_limit
        self._issues: list[Issue] = []
        self._message_id: str | None = None
        self._in_reply_to: str | None = None
        self._references: tuple[str, ...] = ()
        self._subject: str | None = None
        self._date: datetime | None = None
        self._addresses: dict[str, tuple[ParsedAddress, ...]] = {}
        self._body: str | None = None
        self._attachments: list[ParsedAttachment] = []

    def issue(self, kind: ImportErrorKind, message: str) -> None:
        self._issues.append(Issue(kind, message))

    def result(self) -> ParsedMail:
        addresses = self._addresses
        return ParsedMail(
            message_id=self._message_id,
            in_reply_to=self._in_reply_to,
            reference_ids=self._references,
            subject=self._subject,
            date_utc=self._date,
            sender=addresses.get("from", ()),
            to=addresses.get("to", ()),
            cc=addresses.get("cc", ()),
            bcc=addresses.get("bcc", ()),
            body_text=self._body,
            attachments=tuple(self._attachments),
            issues=tuple(dict.fromkeys(self._issues)),
        )

    def parse(self) -> None:
        record = self._record
        if record.truncated:
            match = _HEADER_END.search(record.message)
            head = record.message if match is None else record.message[: match.end()]
            message = _HEADER_PARSER.parsebytes(head)
        else:
            message = _PARSER.parsebytes(record.message)
        headers: dict[str, list[str]] = {}
        for name, value in message.raw_items():
            key = name.lower()
            if key in _WANTED or key in _ADDRESS_HEADERS:
                headers.setdefault(key, []).append(value)
        self._read_identifiers(headers)
        self._read_subject(headers.get("subject"))
        self._read_date(headers.get("date"))
        for key, name in _ADDRESS_HEADERS.items():
            self._addresses[key] = self._read_addresses(headers.get(key), name)
        if any(isinstance(d, MissingHeaderBodySeparatorDefect) for d in message.defects):
            self.issue(ImportErrorKind.PARSE, "header block ends at a line that is no header")
        if not record.truncated:
            self._read_parts(message)

    # Headers

    def _header(self, values: list[str] | None, name: str) -> str | None:
        """The first header of that name, decoded and unfolded; None when absent."""
        if not values:
            return None
        return text.header_text(values[0], f"{name} header", self._issues)

    def _read_identifiers(self, headers: dict[str, list[str]]) -> None:
        value = self._header(headers.get("message-id"), "Message-ID")
        if value is None:
            self.issue(ImportErrorKind.MESSAGE_ID, "Message-ID header missing")
        else:
            self._message_id = _message_id(value)
            if self._message_id is None:
                self.issue(ImportErrorKind.MESSAGE_ID, f"Message-ID malformed: {_quote(value)}")
        value = self._header(headers.get("in-reply-to"), "In-Reply-To")
        match = _ID.search(value) if value else None
        self._in_reply_to = text.clean(match.group()) if match else None
        value = self._header(headers.get("references"), "References")
        ids = list(dict.fromkeys(text.clean(token) for token in _ID.findall(value or "")))
        if len(ids) > _MAX_REFERENCES:
            ids = ids[:1] + ids[1 - _MAX_REFERENCES :]
        self._references = tuple(ids)

    def _read_subject(self, values: list[str] | None) -> None:
        value = self._header(values, "Subject")
        if value is not None:
            value = text.decode_words(value, "Subject header", self._issues)
            self._subject = " ".join(text.clean(value).split()) or None

    def _read_date(self, values: list[str] | None) -> None:
        value = (self._header(values, "Date") or "").strip()
        if value:
            self._date = _rfc5322_date(value)
            if self._date is not None:
                return
            loose = _loose_date(value)
            problem = f"{'non-standard' if loose else 'unparseable'} ({_quote(value)})"
        else:
            loose, problem = None, "missing"
        self._date = separator_date(self._record.separator)
        if self._date is not None:
            source = "taken from the From_ line"
        elif loose is not None:
            self._date, source = loose, "read as UTC"
        else:
            source = "no date known"
        self.issue(ImportErrorKind.DATE, f"Date header {problem}, {source}")

    def _read_addresses(self, values: list[str] | None, name: str) -> tuple[ParsedAddress, ...]:
        if not values:
            return ()
        where = f"{name} header"
        fields = [text.header_text(value, where, self._issues) for value in values]
        pairs = getaddresses(fields)
        if pairs == [("", "")] and any("@" in field for field in fields):
            pairs = getaddresses(fields, strict=False)  # the strict parser rejects whole lists
        found: dict[str, ParsedAddress] = {}
        for display, address in pairs:
            if not (display or address):
                continue  # an empty group, such as undisclosed-recipients:;
            email = text.clean("".join(address.split()).strip("<>").lower())
            local, _, domain = email.partition("@")
            if not local or not domain or "@" in domain:
                self.issue(
                    ImportErrorKind.ADDRESS,
                    f"{where}: invalid address {_quote(address or display)} left out",
                )
            elif email not in found:
                found[email] = ParsedAddress(email, self._display_name(display, email, where))
        return tuple(found.values())

    def _display_name(self, display: str, email: str, where: str) -> str | None:
        name = " ".join(text.clean(text.decode_words(display, where, self._issues)).split())
        if len(name) > 1 and name[0] == name[-1] and name[0] in "\"'":
            name = name[1:-1].strip()
        return name if name and name.lower() != email else None

    # Body and attachments

    def _read_parts(self, message: Message) -> None:
        """Body text from the first candidate in body order, then the attachments."""
        parts = mime_parts(message, self._issues)
        found = parts.first("text/plain", "text/html")
        if found is not None:
            body, _ = part_text(found[1], found[0], BODY_TEXT_LIMIT, self._issues)
            self._body = body if body.strip() else None
        for part, name in parts.attachments:
            self._attachments.append(self._attachment(part, name))

    def _attachment(self, part: Message, raw_name: str | None) -> ParsedAttachment:
        name = None
        if raw_name is not None:
            where = "attachment name"
            name = text.header_text(raw_name, where, self._issues)
            name = text.clean(text.decode_words(name, where, self._issues)).strip() or None
        content_type = part.get_content_type()
        if part.is_multipart():
            inner = part.get_payload(0)
            data = inner.as_bytes() if isinstance(inner, Message) else b""
        else:
            where = f"attachment {_quote(name or content_type)}"
            data = part_payload(part, where, self._issues)
        digest = hashlib.sha256(data).hexdigest() if len(data) <= self._hash_limit else None
        return ParsedAttachment(name, content_type, len(data), digest)


def _lost_boundary(defect: object) -> bool:
    return isinstance(defect, NoBoundaryInMultipartDefect | StartBoundaryNotFoundDefect)


# Parts of a message, shared with the mail detail view (api/body.py)


@dataclass(slots=True)
class MimeParts:
    """What mime_parts finds, in document order."""

    # (content type, inside a forwarded message) -> the first text/plain or text/html part
    texts: dict[tuple[str, bool], Message] = field(default_factory=dict)
    attachments: list[tuple[Message, str | None]] = field(default_factory=list)  # part, name

    def first(self, *content_types: str) -> tuple[str, Message] | None:
        """The first text part of these types in body order (D3), with its content type."""
        for key in _BODY_ORDER:
            if key[0] in content_types and key in self.texts:
                return key[0], self.texts[key]
        return None


def mime_parts(message: Message, issues: list[Issue]) -> MimeParts:
    """Walk the MIME tree in document order: text parts for the body, and the attachments.

    A part whose multipart boundary is lost counts as text/plain, with an issue.
    """
    found = MimeParts()
    stack: list[tuple[Message, bool]] = [(message, False)]
    while stack:
        part, forwarded = stack.pop()
        content_type = part.get_content_type()
        message_part = content_type.startswith("message/")
        if message_part or not part.is_multipart():
            name = part.get_filename()
            if name is not None and not name.strip():
                name = None
            if name is not None or part.get_content_disposition() == "attachment":
                found.attachments.append((part, name))
                continue
        if part.is_multipart():
            forwarded = forwarded or message_part
            children = part.get_payload()
            if isinstance(children, list):
                stack.extend(
                    (child, forwarded) for child in reversed(children) if isinstance(child, Message)
                )
            continue
        if any(_lost_boundary(defect) for defect in part.defects):
            issues.append(Issue(ImportErrorKind.PARSE, f"{content_type} part without its boundary"))
            content_type = "text/plain"  # what a mail client shows of it
        if content_type in ("text/plain", "text/html"):
            found.texts.setdefault((content_type, forwarded), part)
    return found


def part_payload(part: Message, where: str, issues: list[Issue]) -> bytes:
    """The decoded payload of a leaf part; invalid base64 decoded leniently, with an issue."""
    encoding = str(part.get("content-transfer-encoding", "")).strip().lower()
    if encoding == "base64":
        payload = part.get_payload()
        raw = text.ascii_bytes(payload) if isinstance(payload, str) else b""
        data, valid = text.decode_base64(raw)
        if not valid:
            issues.append(
                Issue(ImportErrorKind.ENCODING, f"{where}: invalid base64, read leniently")
            )
        return data
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, bytes) else b""


def part_text(
    part: Message, content_type: str, limit: int, issues: list[Issue]
) -> tuple[str, bool]:
    """At most `limit` characters of a text/plain or text/html part, and whether it has more.

    Charsets are read with the heuristics of importer.text, HTML becomes its readable text, line
    ends become LF, NUL and lone surrogates are removed.
    """
    where = f"{content_type} part"
    payload = part_payload(part, where, issues)
    data = cut_at_line(payload, _BYTES_PER_CHARACTER[content_type] * limit)
    body = text.decode_bytes(data, part.get_content_charset(), where, issues)
    if content_type == "text/html":
        body = text.html_to_text(body)
    body = text.clean(body.replace("\r\n", "\n").replace("\r", "\n"))
    return body[:limit], len(data) < len(payload) or len(body) > limit


def cut_at_line(data: bytes, limit: int) -> bytes:
    """At most `limit` bytes, cut after a line end so no character is split."""
    if len(data) <= limit:
        return data
    newline = data.rfind(b"\n", 0, limit)
    return data[: newline + 1 if newline > 0 else limit]


def _message_id(value: str) -> str | None:
    match = _ID.search(value)
    if match:
        return text.clean(match.group())
    bare = value.strip()
    if bare.count("@") == 1 and not any(c.isspace() or c in "<>" for c in bare):
        return text.clean(f"<{bare}>")
    return None


def _rfc5322_date(value: str) -> datetime | None:
    """The instant of an RFC 5322 date (two-digit years included) with a zone, else None."""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            if not _UTC_UNKNOWN_ZONE.search(value):
                return None
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _loose_date(value: str) -> datetime | None:
    """ISO 8601, `dd.mm.yyyy HH:MM[:SS]` or RFC 5322 without a zone; UTC unless it has one."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        match = _DOTTED_DATE.fullmatch(value)
        try:
            if match is None:
                parsed = parsedate_to_datetime(value)
            else:
                day, month, year, hour, minute, second = (int(n or 0) for n in match.groups())
                parsed = datetime(year, month, day, hour, minute, second)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    try:
        return parsed.astimezone(UTC)
    except OverflowError:
        return None

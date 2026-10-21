"""Status vocabularies shared by the database, the importer, DKIM checks and the generator."""

from collections.abc import Iterable
from enum import IntFlag, StrEnum


class DkimStatus(StrEnum):
    PASS = "pass"
    # Verified only with a key Mailrobbe reconstructed from signatures (D100): the signatures
    # come from one private key, but nothing binds that key to the domain. Never pass.
    CONSISTENT = "consistent"
    FAIL = "fail"
    NO_KEY = "no_key"
    UNSIGNED = "unsigned"
    TEMP_ERROR = "temp_error"


# Lower is better. A mail with several signatures takes the best one as its overall status:
# consistent holds cryptographically but its key is not bound to the domain, temp_error may
# still turn into pass on recheck, no_key cannot be verified but is not proven bad, fail is
# proven bad, unsigned has nothing to verify.
DKIM_STATUS_RANK: dict[DkimStatus, int] = {
    DkimStatus.PASS: 0,
    DkimStatus.CONSISTENT: 1,
    DkimStatus.TEMP_ERROR: 2,
    DkimStatus.NO_KEY: 3,
    DkimStatus.FAIL: 4,
    DkimStatus.UNSIGNED: 5,
}


def best_dkim_status(statuses: Iterable[DkimStatus]) -> DkimStatus:
    """Overall status of a mail from its per-signature results; unsigned when there are none."""
    return min(statuses, key=DKIM_STATUS_RANK.__getitem__, default=DkimStatus.UNSIGNED)


class DkimReason(StrEnum):
    """Why a signature did not pass (dkim_result.reason); None when it passed.

    Stable codes: the import dashboard counts them and the UI maps them to German texts.
    Grouped by the status they come with.
    """

    # fail: the signature is present but does not hold
    BODY_HASH_MISMATCH = "body_hash_mismatch"  # the body changed after signing
    SIGNATURE_MISMATCH = "signature_mismatch"  # signed headers changed, or another key signed
    SIGNATURE_MALFORMED = "signature_malformed"  # unparsable tags, missing or invalid values
    UNSUPPORTED_ALGORITHM = "unsupported_algorithm"  # a= other than rsa-sha256/rsa-sha1/ed25519
    FROM_NOT_SIGNED = "from_not_signed"  # h= does not cover From (RFC 6376 5.4)
    KEY_MALFORMED = "key_malformed"  # the TXT record is not a usable key for this signature
    KEY_TOO_SHORT = "key_too_short"  # RSA key below 1024 bits (RFC 8301)
    MESSAGE_MALFORMED = "message_malformed"  # the header section cannot be parsed
    # no_key: the key is not published (any more)
    KEY_NOT_FOUND = "key_not_found"  # NXDOMAIN or no TXT record
    KEY_REVOKED = "key_revoked"  # record with an empty p=
    # keys for the name from other sources exist (dkim_key, D100), none verifies the signature
    KEY_MISMATCH = "key_mismatch"
    # temp_error: try again later
    DNS_TIMEOUT = "dns_timeout"  # timeout, SERVFAIL or no reachable nameserver
    DNS_OFFLINE = "dns_offline"  # offline mode and the key is not in the cache


class ParticipationRole(StrEnum):
    FROM = "from"
    TO = "to"
    CC = "cc"
    BCC = "bcc"


class PersonKind(StrEnum):
    """person.kind of a root person that is no human (D39); NULL for humans and unknowns."""

    LIST = "list"  # distribution list or mailing list address
    AUTOMATED = "automated"  # newsletters, notifications, noreply senders


class MboxStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"


class DnsStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    TEMP_ERROR = "temp_error"


class ImportErrorKind(StrEnum):
    """Values of import_error.kind. The mail is still imported unless the kind says otherwise."""

    SEPARATOR = "separator"  # From_ line without empty line before it, or data without From_ line
    TOO_LARGE = "too_large"  # record above the size limit: headers only, no body, no DKIM check
    ENCODING = "encoding"  # undecodable header or body, decoded heuristically
    DATE = "date"  # Date header missing or not RFC 5322; date taken from the From_ line
    MESSAGE_ID = "message_id"  # Message-ID missing or malformed
    ADDRESS = "address"  # unparseable address in From/To/Cc/Bcc, left out
    PARSE = "parse"  # unexpected parser failure; the mail is stored with what is known
    DKIM = "dkim"  # the DKIM check failed unexpectedly; dkim_status stays NULL
    IO = "io"  # the file could not be read; the file's status becomes error
    INTERNAL = "internal"  # unexpected failure (database, bug) while importing the file; as io


class JobKind(StrEnum):
    """job.kind: the long runs the import dashboard shows and can stop (D46, D47)."""

    IMPORT = "import"  # mailrobbe import
    DKIM = "dkim"  # mailrobbe dkim
    DKIM_KEYS = "dkim_keys"  # mailrobbe dkim-keys: keys of deleted selectors (D101)


class JobStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    STOPPED = "stopped"  # stopped on request (dashboard, Ctrl-C, SIGTERM); an import resumes
    FAILED = "failed"  # ended by an error, or its process ended without recording its end


class JobOrigin(StrEnum):
    """Who started a run: a command line, or the dashboard through the API (D46)."""

    CLI = "cli"
    UI = "ui"


class ReviewStatus(StrEnum):
    """mail_mark.review: how far the team has looked at a mail (D55); NULL is unreviewed."""

    SEEN = "seen"  # gesichtet: looked at, no verdict
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"  # nicht relevant


class DocumentKind(StrEnum):
    """document.kind (D71): what a document is, for the filters and icons of the UI.

    Decided by mailrobbe.attachments.kinds from the content's first bytes, the file name's
    extension and the declared MIME type.
    """

    PDF = "pdf"
    DOCUMENT = "document"  # word processing: DOCX, ODT, RTF, legacy DOC
    SPREADSHEET = "spreadsheet"  # XLSX, ODS, CSV, legacy XLS
    PRESENTATION = "presentation"  # PPTX, ODP, legacy PPT
    TEXT = "text"  # plain text, HTML, XML, JSON, Markdown, calendar, vCard
    EMAIL = "email"  # an attached mail (message/rfc822, .eml, .msg)
    IMAGE = "image"
    ARCHIVE = "archive"  # ZIP and other containers
    MEDIA = "media"  # audio and video
    OTHER = "other"


class DocumentTextStatus(StrEnum):
    """document.text_status (D72): where the text extraction of a document stands."""

    PENDING = "pending"  # not extracted yet (or by an older extractor, EXTRACTOR_VERSION)
    TEXT = "text"  # text extracted; text_truncated says whether it was cut
    EMPTY = "empty"  # a supported format without any text
    SCANNED = "scanned"  # a PDF whose pages hold images but no text: a scan, for a later OCR
    ENCRYPTED = "encrypted"  # password protected, cannot be read without the password
    UNSUPPORTED = "unsupported"  # no text extraction for this format (images, media, ...)
    TOO_LARGE = "too_large"  # above MAILROBBE_ATTACHMENT_TEXT_MAX_SIZE, not read
    FAILED = "failed"  # the file is damaged or the extractor failed; text_error says why
    TIMEOUT = "timeout"  # stopped at the time limit; the text read until then is kept
    UNREADABLE = "unreadable"  # its MBOX file is missing or changed; tried again next import


class EntityKind(StrEnum):
    """entity.kind (milestone 10, D80, D81): what an entity found in a text is.

    Found by mailrobbe.entities in the subject and text of every mail and in the extracted text
    of every document; the key of each kind is normalised as D81 describes.
    """

    AMOUNT = "amount"  # a sum of money with its currency
    IBAN = "iban"  # an IBAN with valid check digits
    ACCOUNT = "account"  # an account number written as such (Konto, Kto.), with its bank code
    ORGANIZATION = "organization"  # a company, association or party, by its legal form or name
    PERSON = "person"  # a person's name in the text (not a sender or recipient)
    PLACE = "place"  # a town or country
    PHONE = "phone"  # a telephone or fax number
    EMAIL = "email"  # an e-mail address in the text
    URL = "url"  # a web address
    DOMAIN = "domain"  # the domain of a web or e-mail address in the text
    DATE = "date"  # a calendar day written in the text
    TERM = "term"  # a word of a research theme's word field (themes.toml, D83)


class EntityContext(IntFlag):
    """mail_entity.context and document_entity.context (D82): what an amount, IBAN or account
    number is written next to, from the word lists of themes.toml; 0 for none."""

    CASH = 1  # Bargeld, bar, Barzahlung, cash
    DONATION = 2  # Spende, Zuwendung, donation
    RECEIPT = 4  # Quittung, Spendenbescheinigung, Zuwendungsbestätigung, receipt


class KeyOrigin(StrEnum):
    """Where the key a DKIM result rests on comes from (D100): dkim_result.key_origin,
    dkim_key.origin, dkim_key_evidence.origin. Strongest first."""

    DNS = "dns"  # the domain publishes it today (dns_cache, live DNS or the override table)
    OBSERVED = "observed"  # a third party saw it in the domain's DNS (key archive live_dns)
    DOCUMENTED = "documented"  # a document holds it: a find in the archive, a manual record
    RECONSTRUCTED = "reconstructed"  # computed from signatures; binds it to no domain


KEY_ORIGIN_RANK: dict[KeyOrigin, int] = {origin: rank for rank, origin in enumerate(KeyOrigin)}


def strongest_origin(origins: Iterable[KeyOrigin]) -> KeyOrigin | None:
    """The strongest of the origins; None when there are none."""
    return min(origins, key=KEY_ORIGIN_RANK.__getitem__, default=None)


def origin_status(origin: KeyOrigin) -> DkimStatus:
    """The status of a signature whose header and body a key of this origin verifies: pass,
    or consistent for a reconstructed key (D100)."""
    return DkimStatus.CONSISTENT if origin is KeyOrigin.RECONSTRUCTED else DkimStatus.PASS


class KeyLookupSource(StrEnum):
    """dkim_key_lookup.source: where Mailrobbe looked for keys of deleted selectors (D101).

    Stored as text, so sources of a later stage (passive DNS) need no migration.
    """

    RECONSTRUCTION = "reconstruction"  # computed from two or more signatures (GCD)
    ARCHIVE_TEXT = "archive_text"  # a key record quoted in a mail or an attachment's text
    MANUAL = "manual"  # entered by a person, with a reference
    ZKEMAIL = "zkemail"  # the ZK Email DKIM archive, one request per domain
    DNS = "dns"  # today's DNS answer of another selector of the same domain


class LookupOutcome(StrEnum):
    """dkim_key_lookup.outcome."""

    FOUND = "found"  # the answer holds at least one key
    NOT_FOUND = "not_found"  # a valid answer without a key
    ERROR = "error"  # no valid answer: network, HTTP status, malformed reply


class SignalKind(StrEnum):
    """The signals of milestone 12 (D130 to D134): simple conditions on a mail's addresses,
    recipients and time, and a person falling silent, that point to mails worth reading. They
    rate nothing. A mail also has a signal "term:<theme key>" per research theme whose word
    field it mentions (D132); mailrobbe.signals.model names them all."""

    PRIVATE = "private"  # a sender or recipient uses a private mail provider
    INTERNAL_TO_PRIVATE = "internal_to_private"  # an internal sender, a private recipient
    PRIVATE_TO_INTERNAL = "private_to_internal"  # a private sender, an internal recipient
    PRIVATE_ALIAS = "private_alias"  # a private address of a person with an internal one
    BCC = "bcc"  # a recipient in Bcc
    MANY_RECIPIENTS = "many_recipients"  # at least [signals] many_recipients recipients
    FORWARD = "forward"  # a forwarded mail
    FORWARD_OUT = "forward_out"  # a forwarded mail going outside
    NIGHT = "night"  # sent at night, local time (MAILROBBE_TIMEZONE)
    WEEKEND = "weekend"  # sent on a Saturday or Sunday, local time
    SILENT = "silent"  # persons only: no mail since a month after steady activity (D134)

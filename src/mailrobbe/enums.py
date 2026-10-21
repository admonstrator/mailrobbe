"""Status vocabularies shared by the database, the importer, DKIM checks and the generator."""

from collections.abc import Iterable
from enum import StrEnum


class DkimStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NO_KEY = "no_key"
    UNSIGNED = "unsigned"
    TEMP_ERROR = "temp_error"


# Lower is better. A mail with several signatures takes the best one as its overall status:
# temp_error may still turn into pass on recheck, no_key cannot be verified but is not proven
# bad, fail is proven bad, unsigned has nothing to verify.
DKIM_STATUS_RANK: dict[DkimStatus, int] = {
    DkimStatus.PASS: 0,
    DkimStatus.TEMP_ERROR: 1,
    DkimStatus.NO_KEY: 2,
    DkimStatus.FAIL: 3,
    DkimStatus.UNSIGNED: 4,
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


class JobStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    STOPPED = "stopped"  # stopped on request (dashboard, Ctrl-C, SIGTERM); an import resumes
    FAILED = "failed"  # ended by an error, or its process ended without recording its end


class JobOrigin(StrEnum):
    """Who started a run: a command line, or the dashboard through the API (D46)."""

    CLI = "cli"
    UI = "ui"

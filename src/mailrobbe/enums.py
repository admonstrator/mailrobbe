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


class ParticipationRole(StrEnum):
    FROM = "from"
    TO = "to"
    CC = "cc"
    BCC = "bcc"


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

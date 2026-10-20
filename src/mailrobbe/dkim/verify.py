"""DKIM verification of one mail (SPEC 3.4).

verify_mail is pure: the raw message and a KeySource in, a MailVerdict out. It does no I/O of its
own (keys come only from the KeySource) and never raises, whatever the bytes are.

Contract baseline: a thin wrapper around dkim.DKIM.verify that gets the statuses right for the
generated test data and fills domain, selector, algorithm and the cache flag. The full verifier
replaces this module.
"""

import logging
import re

import dkim

from mailrobbe.dkim.model import DnsAnswer, KeySource, MailVerdict, SignatureResult
from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus

_QUIET = logging.getLogger(__name__ + ".dkimpy")
_QUIET.setLevel(logging.CRITICAL)
_SIGNATURE_LINE = re.compile(rb"^dkim-signature[ \t]*:", re.IGNORECASE | re.MULTILINE)


class _Unavailable(Exception):
    """Raised from dnsfunc to carry a temp_error answer through dkimpy."""

    def __init__(self, answer: DnsAnswer) -> None:
        super().__init__(answer.name)
        self.answer = answer


def verify_mail(raw: bytes, keys: KeySource) -> MailVerdict:
    """Verify every DKIM-Signature header field of raw (LF or CRLF line endings)."""
    try:
        verifier = dkim.DKIM(raw, logger=_QUIET)
    except Exception:
        header = re.split(rb"\r?\n\r?\n", raw, maxsplit=1)[0]
        count = len(_SIGNATURE_LINE.findall(header))
        malformed = _result(DkimStatus.FAIL, DkimReason.MESSAGE_MALFORMED, {})
        return MailVerdict((malformed,) * count)
    count = sum(1 for name, _ in verifier.headers if name.lower() == b"dkim-signature")
    return MailVerdict(tuple(_verify(verifier, index, keys) for index in range(count)))


def _verify(verifier: dkim.DKIM, index: int, keys: KeySource) -> SignatureResult:
    answers: list[DnsAnswer] = []

    def dnsfunc(name: bytes, timeout: float = 5) -> bytes | None:
        answer = keys(name.decode("ascii", errors="replace"))
        answers.append(answer)
        if answer.status is DnsStatus.TEMP_ERROR:
            raise _Unavailable(answer)
        if answer.status is DnsStatus.NOT_FOUND or answer.record is None:
            return None
        return answer.record.encode("ascii", errors="replace")

    verifier.signature_fields = {}
    try:
        valid = verifier.verify(idx=index, dnsfunc=dnsfunc)
    except _Unavailable as unavailable:
        reason = unavailable.answer.reason or DkimReason.DNS_TIMEOUT
        return _result(DkimStatus.TEMP_ERROR, reason, verifier.signature_fields, answers)
    except dkim.DKIMException as error:
        reason = (
            DkimReason.BODY_HASH_MISMATCH
            if "body hash mismatch" in str(error)
            else DkimReason.SIGNATURE_MALFORMED
        )
        return _result(DkimStatus.FAIL, reason, verifier.signature_fields, answers)
    except Exception:
        return _result(
            DkimStatus.FAIL, DkimReason.SIGNATURE_MALFORMED, verifier.signature_fields, answers
        )
    fields = verifier.signature_fields
    if valid:
        return _result(DkimStatus.PASS, None, fields, answers)
    if answers and answers[-1].status is DnsStatus.NOT_FOUND:
        return _result(DkimStatus.NO_KEY, DkimReason.KEY_NOT_FOUND, fields, answers)
    return _result(DkimStatus.FAIL, DkimReason.SIGNATURE_MISMATCH, fields, answers)


def _tag(fields: dict[bytes, bytes], name: bytes) -> str | None:
    value = fields.get(name)
    return None if value is None else value.decode("ascii", errors="replace").strip().lower()


def _result(
    status: DkimStatus,
    reason: DkimReason | None,
    fields: dict[bytes, bytes],
    answers: list[DnsAnswer] | None = None,
) -> SignatureResult:
    return SignatureResult(
        status=status,
        reason=reason,
        domain=_tag(fields, b"d"),
        selector=_tag(fields, b"s"),
        algorithm=_tag(fields, b"a"),
        key_bits=None,
        signed_headers=None,
        body_hash_ok=None,
        signed_at=None,
        aligned=None,
        dns_cached=answers[-1].from_cache if answers else False,
    )

"""Results of a DKIM check and the key answers it is based on.

Shared by the verifier (verify.py), the key sources and the cache (resolver.py, checker.py) and
the database layer (store.py). Everything here is plain data and picklable, so worker processes
can send it back to the process that writes the database.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus, KeyOrigin, best_dkim_status

# How long a source's answer may be reused (DnsAnswer.ttl). Found keys rarely change under the
# same selector name and an import takes hours; a missing key is asked for again a day later,
# and on every recheck; a timeout blocks a name for ten minutes at most.
FOUND_TTL = 7 * 24 * 3600
NOT_FOUND_TTL = 24 * 3600
TEMP_ERROR_TTL = 10 * 60


@dataclass(frozen=True, slots=True)
class DnsAnswer:
    """The answer for one DKIM key name, fresh from a source or out of the cache."""

    name: str  # '<selector>._domainkey.<domain>', normalised (override.normalise_name)
    status: DnsStatus
    record: str | None  # the TXT record, strings joined, when status is found
    fetched_at: datetime  # timezone-aware, when the source answered
    ttl: int  # seconds the answer may be reused; 0: never cache or persist it
    # For temp_error: dns_timeout or dns_offline. Not persisted; rows loaded from dns_cache
    # with status temp_error come back as dns_timeout.
    reason: DkimReason | None = None
    from_cache: bool = False  # served by the cache instead of a lookup (dkim_result.dns_cached)


class KeySource(Protocol):
    """Looks up a DKIM key name. Never raises: every failure is a temp_error answer."""

    def __call__(self, name: str) -> DnsAnswer: ...


@dataclass(frozen=True, slots=True)
class CandidateKey:
    """A key for a name from a source other than today's DNS (a dkim_key row, D100).

    It counts for a signature only when it verifies the signature's header hash.
    """

    key_id: int  # dkim_key.id
    origin: KeyOrigin  # dkim_key.origin, the strongest of its evidence
    record: str  # dkim_key.record


# Candidate keys by normalised key name (keys.store.load_candidates), strongest origin first.
KeyCandidates = Mapping[str, Sequence[CandidateKey]]
NO_CANDIDATES: KeyCandidates = {}


@dataclass(frozen=True, slots=True)
class SignatureResult:
    """Outcome of one DKIM-Signature header field; mirrors the dkim_result columns."""

    status: DkimStatus  # pass, consistent, fail, no_key or temp_error, never unsigned
    reason: DkimReason | None  # None exactly when status is pass or consistent
    domain: str | None  # d=, lowercase; None when the header field is too broken to tell
    selector: str | None  # s=
    algorithm: str | None  # a=, e.g. "rsa-sha256"
    key_bits: int | None  # size of the public key, when one was found and parsed
    signed_headers: tuple[str, ...] | None  # h= in signature order, lowercase
    body_hash_ok: bool | None  # bh= matches the body; None when it could not be computed
    signed_at: datetime | None  # t=, UTC
    aligned: bool | None  # From domain related to d= (see verify.py); None without one From
    dns_cached: bool  # the key answer came from the cache
    # The candidate key (dkim_key.id) the result rests on; None for today's DNS and without key.
    key_id: int | None = None
    # Origin of the key the result rests on (D100); None when it rests on none: no_key,
    # temp_error, or a failure found before the key was asked for.
    key_origin: KeyOrigin | None = None


@dataclass(frozen=True, slots=True)
class SignatureMaterial:
    """What one DKIM-Signature signs, for rebuilding and testing keys (verify.signature_material).

    For RSA, b= read as a number s and the header hash encoded for the key's length m satisfy
    s^e = m modulo the key's modulus (keys/reconstruct.py).
    """

    index: int  # signature_index: position among the mail's DKIM-Signature fields
    name: str  # the key name, '<selector>._domainkey.<domain>'
    key_type: str  # the k= its key must have: rsa or ed25519
    hash_name: str  # sha256 or sha1
    header_hash: bytes  # the digest b= signs
    signature: bytes  # b=
    body_hash_ok: bool
    signed_at: datetime | None  # t=, UTC


@dataclass(frozen=True, slots=True)
class MailVerdict:
    """All signatures of one mail, in header order (topmost first = signature_index 0)."""

    signatures: tuple[SignatureResult, ...] = ()

    @property
    def status(self) -> DkimStatus:
        """Overall status for mail.dkim_status: the best signature, unsigned without any."""
        return best_dkim_status(signature.status for signature in self.signatures)

    def result_rows(self, mail_id: int, checked_at: datetime) -> list[dict[str, Any]]:
        """One dict per signature, keyed by dkim_result column names (insert or COPY)."""
        return [
            {
                "mail_id": mail_id,
                "signature_index": index,
                "status": signature.status.value,
                "domain": signature.domain,
                "selector": signature.selector,
                "algorithm": signature.algorithm,
                "key_bits": signature.key_bits,
                "signed_headers": (
                    None if signature.signed_headers is None else list(signature.signed_headers)
                ),
                "body_hash_ok": signature.body_hash_ok,
                "signed_at": signature.signed_at,
                "aligned": signature.aligned,
                "reason": None if signature.reason is None else signature.reason.value,
                "checked_at": checked_at,
                "dns_cached": signature.dns_cached,
                "key_id": signature.key_id,
                "key_origin": None if signature.key_origin is None else signature.key_origin.value,
            }
            for index, signature in enumerate(self.signatures)
        ]

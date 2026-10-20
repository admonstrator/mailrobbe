"""Where DKIM keys come from: real DNS, reserved names, offline mode and the key cache (D11).

DkimChecker.from_settings (checker.py) chains them:

    KeyCache -> KeyChain(override table -> reserved names -> DnsResolver or offline_answer)

Every piece is a KeySource: a key name in, a DnsAnswer out, never an exception. The cache sits in
front because 400,000 mails have only a few thousand key names: each name reaches the chain once
per process and answer lifetime, a timeout included, never once per mail. Lifetimes are the
project's (FOUND_TTL and friends), not the record's DNS TTL, which is often a few minutes while
an import takes hours.
"""

import ipaddress
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import dns.exception
import dns.name
import dns.rdatatype
import dns.resolver
from dns.rdtypes.txtbase import TXTBase

from mailrobbe.dkim.model import FOUND_TTL, NOT_FOUND_TTL, TEMP_ERROR_TTL, DnsAnswer, KeySource
from mailrobbe.dkim.override import DnsOverrideTable, normalise_name
from mailrobbe.enums import DkimReason, DnsStatus

log = logging.getLogger(__name__)

# RFC 2606 and RFC 6761: never delegated, so a key below them cannot exist. Generated test data
# uses them; real archives do not.
RESERVED_TLDS = frozenset({"example", "test", "invalid", "localhost"})

_DKIM1 = re.compile(r"\s*v\s*=\s*dkim1", re.IGNORECASE)


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_reserved(name: str) -> bool:
    """Whether the last label of name is a reserved TLD."""
    return normalise_name(name).rpartition(".")[2] in RESERVED_TLDS


def parse_nameservers(text: str) -> tuple[str, ...]:
    """MAILROBBE_DKIM_NAMESERVERS: comma-separated IP addresses; empty means the system's."""
    addresses = []
    for entry in filter(None, (part.strip() for part in text.split(","))):
        try:
            addresses.append(str(ipaddress.ip_address(entry)))
        except ValueError:
            raise ValueError(
                f"MAILROBBE_DKIM_NAMESERVERS: {entry!r} is not an IP address"
            ) from None
    return tuple(addresses)


def _not_found(name: str) -> DnsAnswer:
    return DnsAnswer(name, DnsStatus.NOT_FOUND, None, utc_now(), NOT_FOUND_TTL)


class DnsResolver:
    """Real DNS through dnspython: one TXT query per key name, without search domains.

    timeout: seconds per name, every retry and nameserver included.
    nameservers: IP addresses; empty uses the system configuration, read on the first query, so
    a checker that never needs real DNS (generated data) never needs a configuration either.
    """

    def __init__(self, timeout: float, nameservers: Sequence[str] = ()) -> None:
        self.timeout = timeout
        self.nameservers = tuple(nameservers)
        self._resolver: dns.resolver.Resolver | None = None

    def __call__(self, name: str) -> DnsAnswer:
        key = normalise_name(name)
        try:
            qname = dns.name.from_text(key)
        except dns.exception.DNSException:
            # Empty or overlong label, bad escape: not a DNS name, so no key can be there.
            return _not_found(key)
        try:
            answer = self._dnspython().resolve(
                qname, dns.rdatatype.TXT, search=False, lifetime=self.timeout
            )
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return _not_found(key)
        # Timeout, SERVFAIL, socket errors, no usable nameserver or no system configuration.
        except Exception as error:
            log.warning("DKIM key %s: DNS lookup failed: %s", key, error)
            return DnsAnswer(
                key, DnsStatus.TEMP_ERROR, None, utc_now(), TEMP_ERROR_TTL, DkimReason.DNS_TIMEOUT
            )
        records = [
            b"".join(rdata.strings).decode("latin-1")
            for rdata in answer.rrset or ()
            if isinstance(rdata, TXTBase)
        ]
        if not records:
            return _not_found(key)
        record = next((record for record in records if _DKIM1.match(record)), records[0])
        return DnsAnswer(key, DnsStatus.FOUND, record, utc_now(), FOUND_TTL)

    def _dnspython(self) -> dns.resolver.Resolver:
        if self._resolver is None:
            resolver = dns.resolver.Resolver(configure=not self.nameservers)
            if self.nameservers:
                resolver.nameservers = list(self.nameservers)
            # EDNS0 (1232-byte payload): a 4096-bit key comes in one UDP answer, not in a
            # truncated one and a TCP retry.
            resolver.use_edns()
            self._resolver = resolver
        return self._resolver


def offline_answer(name: str) -> DnsAnswer:
    """The last source in offline mode: temp_error dns_offline, never cached or persisted."""
    return DnsAnswer(
        normalise_name(name), DnsStatus.TEMP_ERROR, None, utc_now(), 0, DkimReason.DNS_OFFLINE
    )


@dataclass(frozen=True, slots=True)
class KeyChain:
    """The sources behind the cache, in D11 order.

    The override table answers the names it lists, so a real archive placed next to generated
    data still gets real DNS for real domains; reserved names are not found without a query, in
    every mode; everything else goes to last (DnsResolver, or offline_answer).
    """

    table: DnsOverrideTable | None
    last: KeySource

    def __call__(self, name: str) -> DnsAnswer:
        key = normalise_name(name)
        if self.table is not None and self.table.lists(key):
            return self.table.answer(key)
        if is_reserved(key):
            return _not_found(key)
        return self.last(key)


class KeyCache:
    """A KeySource in front of another one, valid answers from memory; one per process.

    preload: answers from dns_cache; each serves while fetched_at + ttl lies ahead.
    refresh_negative: skip preloaded not_found and temp_error answers (recheck runs), so every
    missing or unreachable key is asked for once more; what this process fetches is cached as
    usual.
    offline: nothing can be asked instead, so answers serve whatever their age.
    clock: the current time (tests move it).

    A fresh answer with ttl > 0 is kept until it expires and queued for take_new_answers; one
    with ttl 0 is neither. Answers served from memory have from_cache=True. lookups counts the
    calls that went to the source, hits those answered from memory.
    """

    def __init__(
        self,
        source: KeySource,
        *,
        preload: Iterable[DnsAnswer] = (),
        refresh_negative: bool = False,
        offline: bool = False,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._source = source
        self._offline = offline
        self._clock = clock
        self._entries: dict[str, tuple[DnsAnswer, datetime]] = {}  # name -> answer, expiry
        self._new: dict[str, DnsAnswer] = {}
        self.lookups = 0
        self.hits = 0
        for answer in preload:
            if answer.ttl > 0 and not (refresh_negative and answer.status is not DnsStatus.FOUND):
                self._keep(normalise_name(answer.name), answer)

    def __call__(self, name: str) -> DnsAnswer:
        key = normalise_name(name)
        entry = self._entries.get(key)
        if entry is not None and (self._offline or entry[1] > self._clock()):
            self.hits += 1
            return entry[0]
        self.lookups += 1
        answer = self._source(key)
        if answer.ttl > 0:
            self._keep(key, answer)
            self._new[key] = answer
        return answer

    def take_new_answers(self) -> list[DnsAnswer]:
        """Fresh answers since the last call, the latest one per name; each is handed out once."""
        answers = list(self._new.values())
        self._new.clear()
        return answers

    def _keep(self, key: str, answer: DnsAnswer) -> None:
        expires = answer.fetched_at + timedelta(seconds=answer.ttl)
        self._entries[key] = (replace(answer, name=key, from_cache=True), expires)

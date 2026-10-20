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
import dns.message
import dns.name
import dns.rcode
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

# DnsResolver's circuit breaker: after this many failed lookups in a row, if the root zone does
# not answer either, DNS is not asked for TEMP_ERROR_TTL.
UNREACHABLE_AFTER = 5

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


def _not_found(name: str, fetched_at: datetime) -> DnsAnswer:
    return DnsAnswer(name, DnsStatus.NOT_FOUND, None, fetched_at, NOT_FOUND_TTL)


class DnsResolver:
    """Real DNS through dnspython: one TXT query per key name, without search domains.

    timeout: seconds per name, every retry and nameserver included.
    nameservers: IP addresses; empty uses the system configuration, read on the first query, so
    a checker that never needs real DNS (generated data) never needs a configuration either.
    clock: the current time (tests move it).

    Circuit breaker: when DNS is down, every new name would cost the full timeout. A failure
    counts when no nameserver answered usefully (timeout, REFUSED, socket error, no
    configuration); SERVFAIL means the resolver works and one domain is broken, so it neither
    counts nor resets the count, and every other answer resets it. After UNREACHABLE_AFTER
    failures in a row the root zone is asked for its NS records, same nameservers and timeout:
    lame delegations of dead domains time out as well, but the root answers. Only when it does
    not, the resolver stops asking for TEMP_ERROR_TTL and answers temp_error with ttl 0, which
    is neither cached nor persisted, so those names are asked for for real afterwards. The next
    name after the block asks the root again: an answer lifts the block and the name is looked
    up as usual, another failure renews the block.
    """

    def __init__(
        self,
        timeout: float,
        nameservers: Sequence[str] = (),
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.timeout = timeout
        self.nameservers = tuple(nameservers)
        self._clock = clock
        self._resolver: dns.resolver.Resolver | None = None
        self._failures = 0  # counting failures in a row
        self._blocked_until: datetime | None = None  # set while the breaker is open

    def __call__(self, name: str) -> DnsAnswer:
        key = normalise_name(name)
        try:
            qname = dns.name.from_text(key)
        except dns.exception.DNSException:
            # Empty or overlong label, bad escape: not a DNS name, so no key can be there.
            return _not_found(key, self._clock())
        if self._blocked_until is not None:
            if self._clock() < self._blocked_until:
                return self._blocked(key)
            if not self._root_answers():  # the probe after the block
                self._block()
                return self._blocked(key)
            log.info("DNS answers again, DKIM key lookups resumed")
            self._blocked_until = None
        try:
            answer = self._dnspython().resolve(
                qname, dns.rdatatype.TXT, search=False, lifetime=self.timeout
            )
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            self._failures = 0
            return _not_found(key, self._clock())
        # Timeout, SERVFAIL, REFUSED, socket errors, no usable nameserver or no configuration.
        except Exception as error:
            log.info("DKIM key %s: DNS lookup failed: %s", key, error)
            if not _servfail(error):
                self._failed()
            return DnsAnswer(
                key,
                DnsStatus.TEMP_ERROR,
                None,
                self._clock(),
                TEMP_ERROR_TTL,
                DkimReason.DNS_TIMEOUT,
            )
        self._failures = 0
        records = [
            b"".join(rdata.strings).decode("latin-1")
            for rdata in answer.rrset or ()
            if isinstance(rdata, TXTBase)
        ]
        if not records:
            return _not_found(key, self._clock())
        record = next((record for record in records if _DKIM1.match(record)), records[0])
        return DnsAnswer(key, DnsStatus.FOUND, record, self._clock(), FOUND_TTL)

    def _failed(self) -> None:
        self._failures += 1
        if self._failures < UNREACHABLE_AFTER:
            return
        self._failures = 0
        if self._root_answers():
            log.debug(
                "%d key lookups in a row failed, but the root zone answers", UNREACHABLE_AFTER
            )
            return
        log.warning(
            "DNS looks unreachable, %d key lookups in a row failed and the root zone does not "
            "answer either: keys not in the cache are temp_error without a query for the next "
            "%d minutes, then DNS is tried again",
            UNREACHABLE_AFTER,
            TEMP_ERROR_TTL // 60,
        )
        self._block()

    def _blocked(self, key: str) -> DnsAnswer:
        return DnsAnswer(key, DnsStatus.TEMP_ERROR, None, self._clock(), 0, DkimReason.DNS_TIMEOUT)

    def _block(self) -> None:
        self._blocked_until = self._clock() + timedelta(seconds=TEMP_ERROR_TTL)

    def _root_answers(self) -> bool:
        """Reachability probe: whether the nameservers answer for the root zone's NS records."""
        try:
            self._dnspython().resolve(
                dns.name.root, dns.rdatatype.NS, search=False, lifetime=self.timeout
            )
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return True  # an odd answer, but an answer
        except Exception:
            return False
        return True

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


def _servfail(error: Exception) -> bool:
    """Whether a nameserver answered SERVFAIL: the resolver works, the domain is broken."""
    errors = error.kwargs.get("errors") if isinstance(error, dns.exception.DNSException) else None
    return any(
        isinstance(response, dns.message.Message) and response.rcode() == dns.rcode.SERVFAIL
        for *_, response in errors or ()
    )


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
            return _not_found(key, utc_now())
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

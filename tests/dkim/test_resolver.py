"""Key sources and the key cache (resolver.py) against a fake DNS transport and a fake clock."""

import logging
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import dns.exception
import dns.name
import dns.rcode
import dns.resolver
import pytest

from mailrobbe.dkim.model import FOUND_TTL, NOT_FOUND_TTL, TEMP_ERROR_TTL, DnsAnswer
from mailrobbe.dkim.override import DnsOverrideTable
from mailrobbe.dkim.resolver import (
    UNREACHABLE_AFTER,
    DnsResolver,
    KeyCache,
    KeyChain,
    is_reserved,
    offline_answer,
    parse_nameservers,
)
from mailrobbe.enums import DkimReason, DnsStatus
from tests.dkim.fake_dns import FakeDns, Reply, block_network, install, txt

NAMESERVER = "192.0.2.53"
NAME = "sel._domainkey.firma.ch"
RECORD = "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC"
START = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
TTLS = {DnsStatus.FOUND: FOUND_TTL, DnsStatus.NOT_FOUND: NOT_FOUND_TTL}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDns:
    return install(monkeypatch)


def _resolve(fake: FakeDns, reply: Reply, timeout: float = 1.0) -> DnsAnswer:
    fake.zone[NAME + "."] = reply
    return DnsResolver(timeout, (NAMESERVER,))(NAME)


# --- nameservers and reserved names ---------------------------------------------------------


def test_parse_nameservers() -> None:
    assert parse_nameservers("") == ()
    assert parse_nameservers(" , ") == ()
    assert parse_nameservers(" 192.0.2.1, 2001:DB8::1 ,") == ("192.0.2.1", "2001:db8::1")


@pytest.mark.parametrize(
    "text", ["dns.google", "192.0.2.1:53", "192.0.2.300", "192.0.2.1;192.0.2.2", "192.0.2.1,x"]
)
def test_parse_nameservers_rejects_anything_but_ip_addresses(text: str) -> None:
    with pytest.raises(ValueError, match="MAILROBBE_DKIM_NAMESERVERS"):
        parse_nameservers(text)


@pytest.mark.parametrize(
    ("name", "reserved"),
    [
        ("s1._domainkey.firma.example", True),
        ("S1._DOMAINKEY.FIRMA.TEST.", True),
        ("s1._domainkey.host.invalid", True),
        ("s1._domainkey.localhost", True),
        ("s1._domainkey.example.com", False),
        ("s1._domainkey.firma.testing", False),
        (NAME, False),
    ],
)
def test_reserved_names(name: str, reserved: bool) -> None:
    assert is_reserved(name) is reserved


# --- DnsResolver ----------------------------------------------------------------------------


def test_found_record(fake: FakeDns) -> None:
    fake.zone[NAME + "."] = [(RECORD.encode(),)]
    answer = DnsResolver(0.5, (NAMESERVER,))("Sel._DomainKey.Firma.CH.")
    assert answer == DnsAnswer(NAME, DnsStatus.FOUND, RECORD, answer.fetched_at, FOUND_TTL)
    assert answer.fetched_at.tzinfo is not None
    (query,) = fake.queries
    assert (query.name, query.rdtype, query.where) == (NAME + ".", "TXT", NAMESERVER)
    assert query.timeout is not None and query.timeout <= 0.5
    assert (query.edns, query.payload) == (0, 1232)


def test_character_strings_are_joined_and_decoded_one_to_one(fake: FakeDns) -> None:
    answer = _resolve(fake, [(b"v=DKIM1; k=rsa; ", b"p=AB", b"CD; n=caf\xe9")])
    assert answer.record == "v=DKIM1; k=rsa; p=ABCD; n=café"


@pytest.mark.parametrize(
    ("records", "chosen"),
    [
        ([(b"v=spf1 -all",), (b"V=dkim1; p=A",), (b"v=DKIM1; p=B",)], "V=dkim1; p=A"),
        ([(b"k=rsa; p=A",), (b" v = DKIM1; ", b"p=B")], " v = DKIM1; p=B"),
        ([(b"k=rsa; p=A",), (b"k=rsa; p=B",)], "k=rsa; p=A"),
    ],
)
def test_several_records_prefer_the_first_dkim1(
    fake: FakeDns, records: list[tuple[bytes, ...]], chosen: str
) -> None:
    assert _resolve(fake, records).record == chosen


@pytest.mark.parametrize("reply", [dns.rcode.NXDOMAIN, dns.rcode.NOERROR])
def test_missing_record_is_not_found(fake: FakeDns, reply: dns.rcode.Rcode) -> None:
    answer = _resolve(fake, reply)
    assert (answer.status, answer.record, answer.ttl, answer.reason) == (
        DnsStatus.NOT_FOUND,
        None,
        NOT_FOUND_TTL,
        None,
    )
    assert answer.name == NAME and len(fake.queries) == 1


@pytest.mark.parametrize(
    "reply",
    [
        dns.rcode.SERVFAIL,
        dns.rcode.REFUSED,
        ConnectionRefusedError(111, "Connection refused"),
        OSError(101, "Network is unreachable"),
        dns.exception.Timeout,
    ],
    ids=["servfail", "refused", "connection-refused", "unreachable", "timeout"],
)
def test_failures_are_temp_errors(fake: FakeDns, reply: Reply) -> None:
    answer = _resolve(fake, reply, timeout=0.2)
    assert (answer.status, answer.record, answer.ttl, answer.reason) == (
        DnsStatus.TEMP_ERROR,
        None,
        TEMP_ERROR_TTL,
        DkimReason.DNS_TIMEOUT,
    )


def test_timeout_covers_every_retry_and_nameserver(fake: FakeDns) -> None:
    fake.zone[NAME + "."] = dns.exception.Timeout
    source = DnsResolver(0.3, ("192.0.2.1", "192.0.2.2"))
    started = time.monotonic()
    answer = source(NAME)
    elapsed = time.monotonic() - started
    assert answer.status is DnsStatus.TEMP_ERROR
    assert elapsed < 1.5  # dnspython would keep trying for 5 seconds by default
    assert {query.where for query in fake.queries} == {"192.0.2.1", "192.0.2.2"}
    assert all(query.timeout is not None and query.timeout <= 0.3 for query in fake.queries)


@pytest.mark.parametrize(
    "name",
    ["a" * 64 + "._domainkey.firma.ch", "s1._domainkey..firma.ch", "s\\1._domainkey.firma.ch"],
    ids=["label-too-long", "empty-label", "bad-escape"],
)
def test_names_dns_cannot_express_are_not_found_without_a_query(fake: FakeDns, name: str) -> None:
    answer = DnsResolver(1.0, (NAMESERVER,))(name)
    assert answer.status is DnsStatus.NOT_FOUND
    assert fake.queries == []


def test_empty_nameservers_use_the_system_configuration_without_search(
    fake: FakeDns, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[object] = []

    def read_resolv_conf(self: dns.resolver.Resolver, f: object) -> None:
        reads.append(f)
        self.nameservers = ["192.0.2.7"]
        self.search = [dns.name.from_text("corp.example")]
        self.use_search_by_default = True

    monkeypatch.setattr(dns.resolver.Resolver, "read_resolv_conf", read_resolv_conf)
    source = DnsResolver(1.0)
    assert reads == []  # read on the first query, not when the source is built
    assert source("s1._domainkey.firma").status is DnsStatus.NOT_FOUND
    assert source("s2._domainkey.firma").status is DnsStatus.NOT_FOUND
    assert len(reads) == 1
    # One query per name, for the name itself: no search domain is tried.
    assert [(query.name, query.where) for query in fake.queries] == [
        ("s1._domainkey.firma.", "192.0.2.7"),
        ("s2._domainkey.firma.", "192.0.2.7"),
    ]


def test_missing_system_configuration_is_a_temp_error(
    fake: FakeDns, monkeypatch: pytest.MonkeyPatch
) -> None:
    def read_resolv_conf(self: dns.resolver.Resolver, f: object) -> None:
        raise dns.resolver.NoResolverConfiguration

    monkeypatch.setattr(dns.resolver.Resolver, "read_resolv_conf", read_resolv_conf)
    answer = DnsResolver(1.0)(NAME)
    assert (answer.status, answer.reason) == (DnsStatus.TEMP_ERROR, DkimReason.DNS_TIMEOUT)
    assert fake.queries == []


# --- KeyChain and offline mode ---------------------------------------------------------------


@dataclass
class Recorder:
    """The last source of a chain: records the names it is asked for."""

    names: list[str] = field(default_factory=list)

    def __call__(self, name: str) -> DnsAnswer:
        self.names.append(name)
        return DnsAnswer(name, DnsStatus.FOUND, "v=DKIM1; p=dns", START, FOUND_TTL)


TABLE = DnsOverrideTable(
    records={NAME: RECORD, "s1._domainkey.alt.example": RECORD},
    temp_error=frozenset({"slow._domainkey.firma.ch"}),
)


def test_chain_asks_the_override_table_first_then_reserved_names_then_dns() -> None:
    last = Recorder()
    chain = KeyChain(TABLE, last)
    assert (chain("Sel._DomainKey.Firma.CH.").status, chain(NAME).record) == (
        DnsStatus.FOUND,
        RECORD,
    )
    assert chain("s1._domainkey.alt.example").record == RECORD  # listed wins over reserved
    slow = chain("slow._domainkey.firma.ch")
    assert (slow.status, slow.reason) == (DnsStatus.TEMP_ERROR, DkimReason.DNS_TIMEOUT)
    retired = chain("old._domainkey.alt.example")
    assert (retired.status, retired.ttl) == (DnsStatus.NOT_FOUND, NOT_FOUND_TTL)
    assert last.names == []
    assert chain("S2._domainkey.Firma.CH").record == "v=DKIM1; p=dns"
    assert last.names == ["s2._domainkey.firma.ch"]


def test_chain_without_table_still_keeps_reserved_names_local() -> None:
    last = Recorder()
    assert KeyChain(None, last)("s1._domainkey.alt.example").status is DnsStatus.NOT_FOUND
    assert KeyChain(None, last)(NAME).status is DnsStatus.FOUND
    assert last.names == [NAME]


def test_offline_chain() -> None:
    chain = KeyChain(TABLE, offline_answer)
    assert chain(NAME).record == RECORD
    reserved = chain("old._domainkey.alt.example")
    assert (reserved.status, reserved.reason) == (DnsStatus.NOT_FOUND, None)
    offline = chain("S2._domainkey.Firma.CH.")
    assert (offline.name, offline.status, offline.reason, offline.ttl) == (
        "s2._domainkey.firma.ch",
        DnsStatus.TEMP_ERROR,
        DkimReason.DNS_OFFLINE,
        0,
    )


# --- KeyCache --------------------------------------------------------------------------------


@dataclass
class Clock:
    now: datetime = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass
class Source:
    """A KeySource stamped with the fake clock: found unless statuses says otherwise."""

    clock: Clock
    statuses: dict[str, DnsStatus] = field(default_factory=dict)
    ttl: int | None = None  # overrides the status's lifetime
    calls: list[str] = field(default_factory=list)

    def __call__(self, name: str) -> DnsAnswer:
        self.calls.append(name)
        return _answer(name, self.statuses.get(name, DnsStatus.FOUND), self.clock.now, self.ttl)


def _answer(
    name: str,
    status: DnsStatus = DnsStatus.FOUND,
    at: datetime = START,
    ttl: int | None = None,
    **changes: Any,
) -> DnsAnswer:
    found = status is DnsStatus.FOUND
    temp = status is DnsStatus.TEMP_ERROR
    return DnsAnswer(
        name=name,
        status=status,
        record=RECORD if found else None,
        fetched_at=at,
        ttl=ttl if ttl is not None else TTLS.get(status, TEMP_ERROR_TTL),
        reason=DkimReason.DNS_TIMEOUT if temp else None,
        **changes,
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


def test_cache_answers_a_name_once_while_valid(clock: Clock) -> None:
    source = Source(clock)
    cache = KeyCache(source, clock=clock)
    first = cache(NAME)
    assert not first.from_cache
    again = [cache("SEL._domainkey.firma.CH."), cache(NAME)]
    assert again == [replace(first, from_cache=True)] * 2
    assert source.calls == [NAME]
    assert (cache.lookups, cache.hits) == (1, 2)


@pytest.mark.parametrize("status", list(DnsStatus))
def test_answers_expire_after_their_ttl(clock: Clock, status: DnsStatus) -> None:
    source = Source(clock, {NAME: status})
    cache = KeyCache(source, clock=clock)
    ttl = cache(NAME).ttl
    for _ in range(50):  # a temp_error too costs one lookup per name and lifetime, not per mail
        cache(NAME)
    clock.advance(ttl - 1)
    assert cache(NAME).from_cache
    assert source.calls == [NAME]
    clock.advance(1)  # fetched_at + ttl is now: expired
    assert not cache(NAME).from_cache
    assert source.calls == [NAME, NAME]
    assert (cache.lookups, cache.hits) == (2, 51)


def test_ttl_zero_answers_are_neither_kept_nor_queued(clock: Clock) -> None:
    source = Source(clock, ttl=0)
    cache = KeyCache(source, clock=clock)
    assert [cache(NAME).from_cache for _ in range(3)] == [False] * 3
    assert source.calls == [NAME] * 3
    assert cache.take_new_answers() == []
    assert (cache.lookups, cache.hits) == (3, 0)


def test_take_new_answers_hands_out_each_answer_once(clock: Clock) -> None:
    other = "s2._domainkey.firma.ch"
    source = Source(clock, {other: DnsStatus.NOT_FOUND})
    cache = KeyCache(source, clock=clock)
    first, second = cache(NAME), cache(other)
    cache(NAME)
    assert cache.take_new_answers() == [first, second]
    assert cache.take_new_answers() == []
    clock.advance(NOT_FOUND_TTL)
    cache(other)  # expired: fetched again
    clock.advance(NOT_FOUND_TTL)
    latest = cache(other)  # and once more
    # Fetched twice since the last call: one answer per name, the latest.
    assert cache.take_new_answers() == [latest]
    assert not latest.from_cache and latest.fetched_at == clock.now


def test_preloaded_answers_serve_while_valid(clock: Clock) -> None:
    valid = _answer(NAME, at=START - timedelta(days=6), from_cache=True)
    expired = _answer("s2._domainkey.firma.ch", DnsStatus.NOT_FOUND, START - timedelta(days=1))
    unusable = _answer("s3._domainkey.firma.ch", ttl=0, from_cache=True)
    source = Source(clock)
    cache = KeyCache(source, preload=[valid, expired, unusable], clock=clock)
    assert cache(NAME) == valid
    assert not cache(expired.name).from_cache
    assert not cache(unusable.name).from_cache
    assert source.calls == [expired.name, unusable.name]
    # Preloaded answers came from dns_cache and are not handed back for persisting.
    assert [answer.name for answer in cache.take_new_answers()] == [
        expired.name,
        unusable.name,
    ]


def test_preloaded_answers_are_normalised_and_marked_as_cached(clock: Clock) -> None:
    cache = KeyCache(Source(clock), preload=[_answer("SEL._DomainKey.Firma.CH.")], clock=clock)
    assert cache(NAME) == _answer(NAME, from_cache=True)
    assert cache.lookups == 0


def test_offline_cache_serves_answers_whatever_their_age(clock: Clock) -> None:
    old = START - timedelta(days=400)
    preload = [
        _answer(NAME, at=old, from_cache=True),
        _answer("slow._domainkey.firma.ch", DnsStatus.TEMP_ERROR, old, from_cache=True),
    ]
    source = Source(clock)
    cache = KeyCache(source, preload=preload, offline=True, clock=clock)
    assert cache(NAME).status is DnsStatus.FOUND
    assert cache("slow._domainkey.firma.ch").status is DnsStatus.TEMP_ERROR
    fresh = "s2._domainkey.firma.ch"
    cache(fresh)
    clock.advance(30 * 24 * 3600)
    assert cache(fresh).from_cache
    assert source.calls == [fresh]
    assert (cache.lookups, cache.hits) == (1, 3)


def test_refresh_negative_asks_again_for_missing_and_unreachable_keys(clock: Clock) -> None:
    missing, slow = "old._domainkey.firma.ch", "slow._domainkey.firma.ch"
    preload = [
        _answer(NAME, from_cache=True),
        _answer(missing, DnsStatus.NOT_FOUND, from_cache=True),
        _answer(slow, DnsStatus.TEMP_ERROR, from_cache=True),
    ]
    source = Source(clock, {missing: DnsStatus.NOT_FOUND})
    cache = KeyCache(source, preload=preload, refresh_negative=True, clock=clock)
    assert cache(NAME).from_cache
    assert (cache(missing).from_cache, cache(slow).status) == (False, DnsStatus.FOUND)
    # What this process fetched is cached as usual.
    assert cache(missing).from_cache and cache(slow).from_cache
    assert source.calls == [missing, slow]
    assert (cache.lookups, cache.hits) == (2, 3)


# --- DnsResolver's circuit breaker -----------------------------------------------------------


def _names(count: int, prefix: str = "down") -> list[str]:
    return [f"{prefix}{index}._domainkey.firma.ch" for index in range(count)]


def _logged(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno == level]


def _open_breaker(fake: FakeDns, clock: Clock) -> DnsResolver:
    fake.default = dns.rcode.SERVFAIL
    source = DnsResolver(0.2, (NAMESERVER,), clock=clock)
    for name in _names(UNREACHABLE_AFTER):
        source(name)
    return source


def _blocked(answer: DnsAnswer) -> bool:
    return (answer.status, answer.reason, answer.ttl) == (
        DnsStatus.TEMP_ERROR,
        DkimReason.DNS_TIMEOUT,
        0,
    )


def test_breaker_opens_after_five_failures_in_a_row(
    fake: FakeDns, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe.dkim.resolver")
    fake.default = dns.rcode.SERVFAIL
    fake.zone["down1._domainkey.firma.ch."] = ConnectionRefusedError(111, "Connection refused")
    fake.zone["down2._domainkey.firma.ch."] = dns.exception.Timeout
    source = DnsResolver(0.2, (NAMESERVER,), clock=clock)
    failed = [source(name) for name in _names(UNREACHABLE_AFTER)]
    # The failures themselves were real answers from the network: cached like any temp_error.
    assert {(answer.status, answer.ttl) for answer in failed} == {
        (DnsStatus.TEMP_ERROR, TEMP_ERROR_TTL)
    }
    assert {query.name for query in fake.queries} == {
        name + "." for name in _names(UNREACHABLE_AFTER)
    }
    (warning,) = _logged(caplog, logging.WARNING)
    assert warning.startswith("DNS looks unreachable")

    fake.zone[NAME + "."] = txt(RECORD)  # DNS would even answer now: nobody asks
    queries = len(fake.queries)
    blocked = [source(NAME), source("other._domainkey.firma.ch"), source(NAME)]
    assert all(map(_blocked, blocked))
    assert blocked[0].fetched_at == clock.now
    assert len(fake.queries) == queries
    assert len(_logged(caplog, logging.WARNING)) == 1


def test_any_answer_resets_the_failure_count(fake: FakeDns, clock: Clock) -> None:
    fake.default = dns.rcode.SERVFAIL
    fake.zone.update(
        {
            "nx._domainkey.firma.ch.": dns.rcode.NXDOMAIN,
            "empty._domainkey.firma.ch.": dns.rcode.NOERROR,
            NAME + ".": txt(RECORD),
        }
    )
    source = DnsResolver(0.2, (NAMESERVER,), clock=clock)
    for answered in ("nx._domainkey.firma.ch", "empty._domainkey.firma.ch", NAME):
        for name in _names(UNREACHABLE_AFTER - 1):
            assert source(name).ttl == TEMP_ERROR_TTL
        assert source(answered).status is not DnsStatus.TEMP_ERROR
    for name in _names(UNREACHABLE_AFTER - 1):
        source(name)
    queries = len(fake.queries)
    assert source("fifth._domainkey.firma.ch").ttl == TEMP_ERROR_TTL  # still asked for real
    assert len(fake.queries) == queries + 1
    assert _blocked(source(NAME))


def test_a_failed_probe_renews_the_block(
    fake: FakeDns, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe.dkim.resolver")
    source = _open_breaker(fake, clock)
    for _ in range(2):
        clock.advance(TEMP_ERROR_TTL - 1)
        queries = len(fake.queries)
        assert _blocked(source(NAME))
        clock.advance(1)
        probe = source("probe._domainkey.firma.ch")
        assert (probe.status, probe.ttl) == (DnsStatus.TEMP_ERROR, TEMP_ERROR_TTL)
        assert len(fake.queries) == queries + 1  # exactly one probe
        assert _blocked(source(NAME)) and _blocked(source("next._domainkey.firma.ch"))
        assert len(fake.queries) == queries + 1
    assert len(_logged(caplog, logging.WARNING)) == 1
    assert not [message for message in _logged(caplog, logging.INFO) if "again" in message]


def test_a_successful_probe_closes_the_breaker(
    fake: FakeDns, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe.dkim.resolver")
    source = _open_breaker(fake, clock)
    clock.advance(TEMP_ERROR_TTL)
    fake.default = dns.rcode.NXDOMAIN
    fake.zone[NAME + "."] = txt(RECORD)
    probe = source(NAME)
    assert (probe.status, probe.record, probe.ttl) == (DnsStatus.FOUND, RECORD, FOUND_TTL)
    assert probe.fetched_at == clock.now
    resumed = [message for message in _logged(caplog, logging.INFO) if "again" in message]
    assert resumed == ["DNS answers again, DKIM key lookups resumed"]
    queries = len(fake.queries)
    assert source("gone._domainkey.firma.ch").status is DnsStatus.NOT_FOUND
    # Closed for good: a single failure afterwards does not block anything.
    fake.default = dns.rcode.SERVFAIL
    assert source("down._domainkey.firma.ch").ttl == TEMP_ERROR_TTL
    assert source("down._domainkey.firma.ch").ttl == TEMP_ERROR_TTL
    assert len(fake.queries) == queries + 3


def test_blocked_answers_are_neither_cached_nor_persisted(fake: FakeDns, clock: Clock) -> None:
    fake.default = dns.rcode.SERVFAIL
    cache = KeyCache(DnsResolver(0.2, (NAMESERVER,), clock=clock), clock=clock)
    for name in _names(UNREACHABLE_AFTER):
        cache(name)
    assert len(cache.take_new_answers()) == UNREACHABLE_AFTER
    assert _blocked(cache(NAME)) and _blocked(cache(NAME))
    assert (cache.lookups, cache.take_new_answers()) == (UNREACHABLE_AFTER + 2, [])
    clock.advance(TEMP_ERROR_TTL)
    fake.zone[NAME + "."] = txt(RECORD)
    assert cache(NAME).status is DnsStatus.FOUND  # asked for real once the block ended

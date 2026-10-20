"""DkimChecker.from_settings: the key sources chosen from the settings, end to end over the corpus.

No test reaches the network: dnspython's transports fail the test (fake_dns.block_network), and
the tests that need real DNS answer it from a fake zone.
"""

import base64
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import dkim
import dns.resolver
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from mailrobbe.config import Settings
from mailrobbe.dkim.checker import DkimChecker
from mailrobbe.dkim.model import FOUND_TTL, NOT_FOUND_TTL, DnsAnswer, MailVerdict
from mailrobbe.dkim.override import key_name
from mailrobbe.dkim.resolver import KeyChain, offline_answer
from mailrobbe.enums import DkimReason, DkimStatus, DnsStatus
from tests.dkim.conftest import Corpus
from tests.dkim.fake_dns import FakeDns, block_network, install, txt

NAMESERVER = "192.0.2.53"
REAL_NAME = "sel._domainkey.firma.ch"  # not under a reserved TLD: only real DNS can answer it
MESSAGE = (
    b"From: Erika Muster <erika.muster@firma.ch>\nTo: max@kunde.ch\nSubject: Offerte\n"
    b"Date: Tue, 05 Mar 2019 09:12:00 +0100\nMessage-ID: <42@firma.ch>\n\n"
    b"Guten Tag\n\nanbei die Offerte.\n"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture(scope="module")
def real_mail() -> tuple[bytes, str]:
    """A mail signed by firma.ch, and the TXT record of its key."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signature: bytes = dkim.sign(MESSAGE, b"sel", b"firma.ch", pem, linesep=b"\n")
    return signature + MESSAGE, "v=DKIM1; k=rsa; p=" + base64.b64encode(der).decode()


def _statuses(verdict: MailVerdict) -> list[str]:
    return [signature.status.value for signature in verdict.signatures]


def _expected(record: dict[str, Any]) -> list[str]:
    return [signature["expected"] for signature in record["dkim"]["signatures"]]


def _key_names(corpus: Corpus) -> set[str]:
    return {
        key_name(signature["selector"], signature["domain"])
        for record in corpus.records
        for signature in record["dkim"]["signatures"]
    }


def _check_corpus(checker: DkimChecker, corpus: Corpus) -> list[MailVerdict]:
    verdicts = []
    for record in corpus.records:
        verdict = checker.check(corpus.message(record))
        assert _statuses(verdict) == _expected(record), record["index"]
        assert verdict.status.value == record["dkim"]["expected"], record["index"]
        verdicts.append(verdict)
    return verdicts


@pytest.mark.parametrize(
    "changes",
    [
        {"dkim_nameservers": "192.0.2.1,dns.google"},
        {"dkim_nameservers": "192.0.2.1:53", "dkim_offline": True},
        {"dkim_dns_timeout": 0},
    ],
)
def test_invalid_dns_settings_fail_at_start(tmp_path: Path, changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="MAILROBBE_DKIM_"):
        DkimChecker.from_settings(Settings(mbox_dir=tmp_path, **changes))


@pytest.mark.parametrize("offline", [False, True], ids=["online", "offline"])
def test_corpus_through_from_settings(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch, offline: bool
) -> None:
    """Generated data needs neither DNS nor a resolver configuration, online or offline."""

    def no_resolver(*args: object, **kwargs: object) -> None:
        pytest.fail("generated data must not need a DNS resolver")

    monkeypatch.setattr(dns.resolver.Resolver, "__init__", no_resolver)
    asked: Counter[str] = Counter()
    chain = KeyChain.__call__

    def counting(self: KeyChain, name: str) -> DnsAnswer:
        asked[name] += 1
        return chain(self, name)

    monkeypatch.setattr(KeyChain, "__call__", counting)
    checker = DkimChecker.from_settings(Settings(mbox_dir=corpus.mbox_dir, dkim_offline=offline))
    signatures = sum(len(record["dkim"]["signatures"]) for record in corpus.records)
    names = _key_names(corpus)

    first = _check_corpus(checker, corpus)
    assert set(asked) == names and set(asked.values()) == {1}
    assert (checker.lookups, checker.hits) == (len(names), signatures - len(names))
    fresh = [s for verdict in first for s in verdict.signatures if not s.dns_cached]
    assert len(fresh) == len(names)
    assert not any(s.reason is DkimReason.DNS_OFFLINE for v in first for s in v.signatures)
    answers = checker.take_new_answers()
    assert sorted(answer.name for answer in answers) == sorted(names)
    assert all(answer.ttl > 0 and not answer.from_cache for answer in answers)
    assert checker.take_new_answers() == []

    second = _check_corpus(checker, corpus)
    assert all(s.dns_cached for verdict in second for s in verdict.signatures)
    assert (checker.lookups, checker.hits) == (len(names), 2 * signatures - len(names))
    assert set(asked.values()) == {1}
    assert checker.take_new_answers() == []


def test_offline_with_the_corpus_answers_preloaded(corpus: Corpus, tmp_path: Path) -> None:
    """What an import of the corpus leaves in dns_cache, a year old, with no table around."""
    chain = KeyChain(corpus.table, offline_answer)
    preload = [
        replace(answer, fetched_at=answer.fetched_at - timedelta(days=365), from_cache=True)
        for answer in map(chain, sorted(_key_names(corpus)))
    ]
    checker = DkimChecker.from_settings(
        Settings(mbox_dir=tmp_path, dkim_offline=True), preload=preload
    )
    verdicts = _check_corpus(checker, corpus)
    assert checker.lookups == 0
    assert all(s.dns_cached for verdict in verdicts for s in verdict.signatures)
    assert checker.take_new_answers() == []


def test_offline_without_cache_real_names_are_dns_offline(
    tmp_path: Path, real_mail: tuple[bytes, str]
) -> None:
    raw, _ = real_mail
    checker = DkimChecker.from_settings(Settings(mbox_dir=tmp_path, dkim_offline=True))
    for _ in range(2):
        (signature,) = checker.check(raw).signatures
        assert (signature.status, signature.reason) == (
            DkimStatus.TEMP_ERROR,
            DkimReason.DNS_OFFLINE,
        )
    # Offline answers have ttl 0: asked again each time, never cached or persisted.
    assert (checker.lookups, checker.hits) == (2, 0)
    assert checker.take_new_answers() == []


def _real_dns(monkeypatch: pytest.MonkeyPatch, record: str) -> FakeDns:
    return install(monkeypatch, {REAL_NAME + ".": txt(record)})


def test_names_outside_the_table_go_to_real_dns(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch, real_mail: tuple[bytes, str]
) -> None:
    """A real archive next to generated data: the table answers its names, DNS the others."""
    raw, record = real_mail
    fake = _real_dns(monkeypatch, record)
    settings = Settings(mbox_dir=corpus.mbox_dir, dkim_nameservers=NAMESERVER, dkim_dns_timeout=0.5)
    checker = DkimChecker.from_settings(settings)
    assert fake.queries == []  # building the checker sends nothing
    assert checker.check(raw).status is DkimStatus.PASS
    assert checker.check(raw).signatures[0].dns_cached
    (query,) = fake.queries
    assert (query.name, query.rdtype, query.where) == (REAL_NAME + ".", "TXT", NAMESERVER)
    assert query.timeout is not None and query.timeout <= 0.5
    for generated in corpus.records[:40]:
        assert (
            checker.check(corpus.message(generated)).status.value == generated["dkim"]["expected"]
        )
    assert len(fake.queries) == 1
    (answer,) = [answer for answer in checker.take_new_answers() if answer.name == REAL_NAME]
    assert (answer.status, answer.record) == (DnsStatus.FOUND, record)


def test_the_table_wins_over_preloaded_answers(
    corpus: Corpus, real_mail: tuple[bytes, str]
) -> None:
    """dns_cache rows from earlier test data (other keys) must not shadow the table's names."""
    _, other_key = real_mail
    now = datetime.now(UTC)
    preload = [
        DnsAnswer(name, DnsStatus.FOUND, other_key, now, FOUND_TTL, from_cache=True)
        for name in corpus.table.records
    ] + [
        DnsAnswer(name, DnsStatus.NOT_FOUND, None, now, NOT_FOUND_TTL, from_cache=True)
        for name in corpus.table.temp_error
    ]
    checker = DkimChecker.from_settings(Settings(mbox_dir=corpus.mbox_dir), preload=preload)
    _check_corpus(checker, corpus)


def test_refresh_negative_asks_dns_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_mail: tuple[bytes, str]
) -> None:
    raw, record = real_mail
    fake = _real_dns(monkeypatch, record)
    settings = Settings(mbox_dir=tmp_path, dkim_nameservers=NAMESERVER, dkim_dns_timeout=0.5)
    missing = DnsAnswer(
        REAL_NAME, DnsStatus.NOT_FOUND, None, datetime.now(UTC), NOT_FOUND_TTL, from_cache=True
    )

    cached = DkimChecker.from_settings(settings, preload=[missing])
    assert cached.check(raw).status is DkimStatus.NO_KEY
    assert (cached.lookups, fake.queries) == (0, [])

    recheck = DkimChecker.from_settings(settings, preload=[missing], refresh_negative=True)
    assert recheck.check(raw).status is DkimStatus.PASS
    assert recheck.lookups == 1 and len(fake.queries) == 1
    assert [answer.status for answer in recheck.take_new_answers()] == [DnsStatus.FOUND]


def test_any_key_source_gets_a_cache(corpus: Corpus) -> None:
    checker = DkimChecker(corpus.table.answer)
    signed = next(record for record in corpus.records if record["dkim"]["signatures"])
    for _ in range(3):
        checker.check(corpus.message(signed))
    signatures = len(signed["dkim"]["signatures"])
    assert (checker.lookups, checker.hits) == (signatures, 2 * signatures)
    assert len(checker.take_new_answers()) == signatures

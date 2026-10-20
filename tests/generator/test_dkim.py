import email.policy
import pickle
import random
import re
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from email.parser import BytesParser
from pathlib import Path
from unittest import mock

import dkim
import pytest
from cryptography.hazmat.primitives import serialization
from dkim.util import parse_tag_value

from mailspider.dkim.override import DnsOverrideTable, key_name
from mailspider.enums import DkimStatus
from mailspider.generator import dkim as generator_dkim
from mailspider.generator.config import DKIM_KEY_DIR, DNS_OVERRIDE_NAME
from mailspider.generator.dkim import (
    DkimSetup,
    build_dkim_setup,
    generate_test_key,
    sign_mail,
    write_dkim_artifacts,
)
from mailspider.generator.model import DomainKind, RenderedMail, stage_rng
from tests.dkim.samples import (
    CONFIG,
    DOMAINS,
    INTERNAL,
    ORGANISATIONS,
    STRUCTURES,
    sample_mail,
    sample_setup,
    sample_stream,
    single_signer,
)
from tests.dkim_check import verify_mail

SELECTOR_NAME = re.compile(r"^(mail\d{4}|k\d{4}|dkim\d{4}|\d{6}|s\d+|selector\d+|dkim)$")
START = datetime(2012, 1, 1, tzinfo=UTC)
RECENT = datetime(2025, 3, 3, 9, tzinfo=UTC)  # every sample domain signs by then


@pytest.fixture(scope="module")
def setup() -> DkimSetup:
    return sample_setup()


@pytest.fixture(scope="module")
def table(setup: DkimSetup) -> DnsOverrideTable:
    return setup.dns_table()


def sign(mail: RenderedMail, setup: DkimSetup) -> RenderedMail:
    return sign_mail(mail, setup, stage_rng(mail.planned.seed, "dkim"))


def signature_tags(raw: bytes) -> list[dict[bytes, bytes]]:
    headers, _ = dkim.rfc822_parse(raw)
    return [parse_tag_value(value) for name, value in headers if name.lower() == b"dkim-signature"]


def test_generate_test_key_is_deterministic() -> None:
    key = generate_test_key(1024, random.Random(3))
    assert key == generate_test_key(1024, random.Random(3))
    assert key != generate_test_key(1024, random.Random(4))
    assert key.startswith(b"-----BEGIN RSA PRIVATE KEY-----")
    loaded = serialization.load_pem_private_key(key, password=None)
    assert loaded.key_size == 1024  # type: ignore[union-attr]


def test_setup_keys_and_pickling(setup: DkimSetup) -> None:
    sizes = {
        bits: serialization.load_pem_private_key(pem, password=None).key_size  # type: ignore[union-attr]
        for bits, pem in setup.keys.items()
    }
    assert sizes == {2048: 2048, 1024: 1024}
    assert pickle.loads(pickle.dumps(setup)) == setup


def test_selector_plan(setup: DkimSetup) -> None:
    names = {domain.name for domain in DOMAINS}
    assert set(setup.signers) <= names
    assert INTERNAL.name in setup.signers
    for domain in DOMAINS:
        if domain.kind is not DomainKind.ORGANISATION:
            assert domain.name in setup.signers, "freemail and service domains sign"
    assert sum(domain.name not in setup.signers for domain in ORGANISATIONS) == 3
    assert setup.relays and all(name in setup.signers for name in setup.relays)
    bits: Counter[int] = Counter()
    for signer in setup.signers.values():
        selectors = signer.selectors
        assert len({selector.name for selector in selectors}) == len(selectors)
        assert all(SELECTOR_NAME.match(selector.name) for selector in selectors)
        assert [s.valid_from for s in selectors] == sorted({s.valid_from for s in selectors})
        assert selectors[-1].status is not DkimStatus.NO_KEY, "the current selector is published"
        bits.update(selector.key_bits for selector in selectors)
        assert signer.selector_at(selectors[0].valid_from - timedelta(seconds=1)) is None
        assert signer.selector_at(selectors[-1].valid_from) is selectors[-1]
    assert bits[1024] and bits[2048] > bits[1024]
    # the internal domain signs the last 70 % of the volume, which grows like the planner's clock
    first = datetime.combine(CONFIG.date_from, time(), UTC)
    span = datetime.combine(CONFIG.date_to, time(), UTC) + timedelta(days=1) - first
    since = (setup.signers[INTERNAL.name].selectors[0].valid_from - first) / span
    assert 0.55 * since + 0.45 * since**2 == pytest.approx(0.3)


def test_dns_table_follows_the_selector_states(setup: DkimSetup, table: DnsOverrideTable) -> None:
    states: Counter[DkimStatus] = Counter()
    for signer in setup.signers.values():
        for selector in signer.selectors:
            name = key_name(selector.name, signer.domain)
            states[selector.status] += 1
            assert (name in table.records) is (selector.status is DkimStatus.PASS)
            assert (name in table.temp_error) is (selector.status is DkimStatus.TEMP_ERROR)
            if selector.status is DkimStatus.TEMP_ERROR:
                assert signer.domain != INTERNAL.name
    assert set(states) == {DkimStatus.PASS, DkimStatus.NO_KEY, DkimStatus.TEMP_ERROR}
    assert all(record.startswith("v=DKIM1; k=rsa; p=") for record in table.records.values())


def test_write_dkim_artifacts(setup: DkimSetup, table: DnsOverrideTable, tmp_path: Path) -> None:
    write_dkim_artifacts(setup, tmp_path / "meta")
    assert DnsOverrideTable.load(tmp_path / "meta" / DNS_OVERRIDE_NAME) == table
    key_dir = tmp_path / "meta" / DKIM_KEY_DIR
    assert sorted(path.name for path in key_dir.iterdir()) == [
        "README.txt",
        "rsa-1024.pem",
        "rsa-2048.pem",
    ]
    assert (key_dir / "rsa-2048.pem").read_bytes() == setup.keys[2048]
    assert "never use them for real mail" in (key_dir / "README.txt").read_text()


def test_signed_share_extremes(setup: DkimSetup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generator_dkim, "generate_test_key", lambda bits, rng: setup.keys[bits])
    rng = random.Random(1)
    nobody = build_dkim_setup(DOMAINS, replace(CONFIG, dkim_signed_share=0.0), rng)
    assert nobody.signers == {}
    everybody = build_dkim_setup(DOMAINS, replace(CONFIG, dkim_signed_share=1.0), rng)
    assert set(everybody.signers) == {domain.name for domain in DOMAINS}
    assert all(signer.selectors[0].valid_from < START for signer in everybody.signers.values())


@pytest.mark.parametrize(
    ("bits", "canonicalization"), [(2048, "relaxed/relaxed"), (1024, "relaxed/simple")]
)
def test_signature_is_the_one_dkimpy_builds(
    setup: DkimSetup, bits: int, canonicalization: str
) -> None:
    compared: set[str] = set()
    for index, structure in enumerate(STRUCTURES * 3):
        original = sample_mail(index, structure, sender=INTERNAL)
        signed = sign(
            replace(original, raw=original.raw),
            single_signer(setup.keys, INTERNAL, bits, canonicalization),
        )
        if signed.dkim.signatures[0].reason is not None:
            continue  # changed after signing
        header = signed.raw[: len(signed.raw) - len(original.raw)]
        tags = signature_tags(signed.raw)[0]
        with mock.patch("time.time", return_value=int(original.planned.date.timestamp())):
            expected = dkim.DKIM(original.raw, linesep=b"\n").sign(
                b"s1",
                INTERNAL.name.encode(),
                setup.keys[bits],
                canonicalize=tuple(canonicalization.encode().split(b"/")),
                include_headers=[name.strip() for name in tags[b"h"].split(b":")],
            )
        assert header == expected
        compared.add(structure)
    assert compared == set(STRUCTURES)


@pytest.mark.parametrize("canonicalization", ["relaxed/relaxed", "relaxed/simple"])
@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"\n",
        b"text\n\n\n",
        b"tab\tinside\n",
        b"two  spaces\n",
        b"trailing \nwhitespace\t\nend",
        b"stray\r\ncarriage\rreturns\n",
        b"QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=\nYWJj\n\n",
    ],
)
def test_body_canonicalisation_is_dkimpys(
    setup: DkimSetup, canonicalization: str, body: bytes
) -> None:
    """The fast path for bodies must give exactly the signature dkimpy computes."""
    message = sample_mail(0, "plain_8bit").raw.split(b"\n\n")[0] + b"\n\n" + body
    signer = single_signer(setup.keys, INTERNAL, 2048, canonicalization).signers[INTERNAL.name]
    header = generator_dkim._signature(
        message, signer, signer.selectors[0], setup.keys[2048], 1234567890, False
    )
    include = [name.strip() for name in signature_tags(header + message)[0][b"h"].split(b":")]
    with mock.patch("time.time", return_value=1234567890):
        expected = dkim.DKIM(message, linesep=b"\n").sign(
            b"s1",
            INTERNAL.name.encode(),
            setup.keys[2048],
            canonicalize=tuple(canonicalization.encode().split(b"/")),
            include_headers=include,
        )
    assert header == expected


def test_signatures_carry_the_mail_date_and_keep_lf(setup: DkimSetup) -> None:
    for mail in sample_stream(200, seed=5):
        signed = sign(mail, setup)
        assert b"\r" not in signed.raw
        tags = signature_tags(signed.raw)
        assert len(tags) == len(signed.dkim.signatures)
        for tag, outcome in zip(tags, signed.dkim.signatures, strict=True):
            assert int(tag[b"t"]) == int(mail.planned.date.timestamp())
            assert tag[b"d"].decode() == outcome.domain
            assert tag[b"s"].decode() == outcome.selector
            assert tag[b"c"] in (b"relaxed/relaxed", b"relaxed/simple")
            headers = {name.strip() for name in tag[b"h"].split(b":")}
            assert {b"from", b"subject", b"date", b"message-id"} <= headers


def test_signing_is_deterministic(setup: DkimSetup) -> None:
    first = [sign(mail, setup).raw for mail in sample_stream(30, seed=8)]
    assert first == [sign(mail, setup).raw for mail in sample_stream(30, seed=8)]


def test_every_signed_mail_verifies_as_expected(setup: DkimSetup, table: DnsOverrideTable) -> None:
    statuses: Counter[DkimStatus] = Counter()
    reasons: Counter[str | None] = Counter()
    mixed_pairs = 0
    for mail in sample_stream(600, seed=2):
        signed = sign(mail, setup)
        overall, per_signature = verify_mail(signed.raw, table)
        assert per_signature == [outcome.expected for outcome in signed.dkim.signatures]
        assert overall is signed.dkim.expected
        statuses[overall] += 1
        reasons.update(outcome.reason for outcome in signed.dkim.signatures)
        if len(set(per_signature)) == 2:
            mixed_pairs += 1
            outer = signed.dkim.signatures[0].domain
            assert outer in setup.relays or outer in (mail.planned.list_id or "")
            assert outer != mail.planned.sender.domain
    assert set(statuses) == set(DkimStatus)
    assert {"selector_retired", "body_modified", "header_modified", "dns_timeout"} <= set(reasons)
    assert mixed_pairs


@pytest.mark.parametrize("status", [DkimStatus.NO_KEY, DkimStatus.TEMP_ERROR])
def test_unpublished_selectors(
    setup: DkimSetup, table: DnsOverrideTable, status: DkimStatus
) -> None:
    signer, selector = next(
        (signer, selector)
        for signer in setup.signers.values()
        for selector in signer.selectors
        if selector.status is status
    )
    domain = next(domain for domain in DOMAINS if domain.name == signer.domain)
    date = max(selector.valid_from, START) + timedelta(hours=1)
    signed = sign(sample_mail(1, sender=domain, date=date, automated=False), setup)
    author = signed.dkim.signatures[-1]
    assert (author.selector, author.expected) == (selector.name, status)
    assert author.reason == {DkimStatus.NO_KEY: "selector_retired"}.get(status, "dns_timeout")
    assert verify_mail(signed.raw, table)[1][-1] is status


def test_both_key_sizes_verify(setup: DkimSetup) -> None:
    for bits in (1024, 2048):
        custom = single_signer(setup.keys, INTERNAL, bits)
        signed = sign(sample_mail(3, "mixed", sender=INTERNAL), custom)
        assert signed.dkim.signatures[0].key_bits == bits
        overall, _ = verify_mail(signed.raw, custom.dns_table())
        assert overall is signed.dkim.expected


def test_unknown_domains_stay_unsigned(setup: DkimSetup, table: DnsOverrideTable) -> None:
    mail = sample_mail(4)
    mail.planned.sender = replace(mail.planned.sender, email="max@elsewhere.example")
    raw = mail.raw
    signed = sign(mail, setup)
    assert signed.raw == raw
    assert signed.dkim.expected is DkimStatus.UNSIGNED and signed.dkim.signatures == ()
    assert verify_mail(signed.raw, table) == (DkimStatus.UNSIGNED, [])


def test_changed_mails_stay_well_formed(setup: DkimSetup) -> None:
    changed: Counter[str] = Counter()
    for index in range(300):
        date = RECENT + timedelta(hours=7 * index)
        mail = sample_mail(
            index, seed=4, sender=INTERNAL, date=date, list_id="<team.nordwind.example>"
        )
        signed = sign(mail, setup)
        reason = signed.dkim.signatures[-1].reason
        if reason not in ("body_modified", "header_modified"):
            continue
        changed[reason] += 1
        message = BytesParser(policy=email.policy.default).parsebytes(signed.raw)
        assert all(not part.defects for part in message.walk())
        if reason == "header_modified":
            assert str(message["subject"]).startswith("[team] ")
        else:
            texts = [
                part.get_content()
                for part in message.walk()
                if part.get_content_type() == "text/plain"
            ]
            assert "team mailing list" in texts[-1]
    assert changed["body_modified"] and changed["header_modified"]


@pytest.mark.slow
@pytest.mark.parametrize("share", [0.7, 0.4])
def test_shares(setup: DkimSetup, share: float, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generator_dkim, "generate_test_key", lambda bits, rng: setup.keys[bits])
    config = replace(CONFIG, dkim_signed_share=share)
    custom = build_dkim_setup(DOMAINS, config, stage_rng(config.seed, "dkim-setup"))
    table = custom.dns_table()
    count = 4000
    statuses: Counter[DkimStatus] = Counter()
    two = 0
    for mail in sample_stream(count, seed=9):
        signed = sign(mail, custom)
        assert verify_mail(signed.raw, table)[0] is signed.dkim.expected
        statuses[signed.dkim.expected] += 1
        two += len(signed.dkim.signatures) == 2
    signed_count = count - statuses[DkimStatus.UNSIGNED]
    assert abs(signed_count / count - share) < 0.05
    assert 0.005 < statuses[DkimStatus.FAIL] / signed_count < 0.08
    assert 0.03 < two / signed_count < 0.3
    assert statuses[DkimStatus.NO_KEY] and statuses[DkimStatus.TEMP_ERROR]

import bisect
import hashlib
import random
from collections import Counter
from dataclasses import replace

from mailspider.generator.config import GeneratorConfig
from mailspider.generator.dkim import sign_mail
from mailspider.generator.faults import DuplicateInjector, inject_fault
from mailspider.generator.model import Fault, RenderedMail, stage_rng
from tests.dkim.samples import CONFIG, sample_setup, sample_stream
from tests.dkim_check import verify_mail

MOZILLA = b"X-Mozilla-Status: 0001\nX-Mozilla-Status2: 00000000\n"


def run(mails: list[RenderedMail], config: GeneratorConfig) -> list[RenderedMail]:
    injector = DuplicateInjector(config)
    return [injector.process(mail) for mail in mails]


def redelivered_from(duplicate: bytes, source: bytes) -> bool:
    """The duplicate is the source plus one header a client or a second delivery adds."""
    received = duplicate.startswith(b"Received: ") and duplicate.endswith(source)
    lines_added = duplicate.count(b"\n") - source.count(b"\n")
    return (
        duplicate.replace(b"Status: RO\n", b"", 1) == source
        or duplicate.removeprefix(MOZILLA) == source
        or (received and lines_added == 3)
    )


def test_duplicates_rate_variants_and_sources() -> None:
    mails = list(sample_stream(3000, seed=12))
    out = run(mails, replace(CONFIG, duplicate_rate=0.05))
    originals = {position for position, mail in enumerate(out) if mail.duplicate_of is None}
    duplicates = [
        (position, mail) for position, mail in enumerate(out) if mail.duplicate_of is not None
    ]
    assert abs(len(duplicates) / len(out) - 0.05) < 0.012
    ordered = sorted(originals)
    variants: Counter[str] = Counter()
    for position, duplicate in duplicates:
        assert duplicate.duplicate_of is not None
        source_position = duplicate.duplicate_of
        source = out[source_position]
        assert duplicate.duplicate_of in originals, "never a duplicate of a duplicate"
        # the buffer holds the last 256 originals; duplicates in between do not count
        newer = bisect.bisect_left(ordered, position) - bisect.bisect_left(ordered, source_position)
        assert 0 < newer <= 256
        variant = duplicate.faults[Fault.DUPLICATE]
        variants[variant] += 1
        assert duplicate.faults == {**source.faults, Fault.DUPLICATE: variant}
        assert duplicate.planned is source.planned and duplicate.dkim == source.dkim
        assert duplicate.message_id == source.message_id
        assert duplicate.escape_from_lines == source.escape_from_lines
        if variant == "exact":
            assert hashlib.sha256(duplicate.raw).digest() == hashlib.sha256(source.raw).digest()
        else:
            assert duplicate.raw != source.raw and redelivered_from(duplicate.raw, source.raw)
    assert set(variants) == {"exact", "same_message_id"}
    assert all(out[position] is mails[position] for position in originals)


def test_duplicates_are_deterministic() -> None:
    config = replace(CONFIG, duplicate_rate=0.1)
    first = run(list(sample_stream(500, seed=13)), config)
    second = run(list(sample_stream(500, seed=13)), config)
    assert [(m.raw, m.duplicate_of) for m in first] == [(m.raw, m.duplicate_of) for m in second]


def test_duplicate_rate_extremes() -> None:
    mails = list(sample_stream(50, seed=14))
    assert all(mail.duplicate_of is None for mail in run(mails, replace(CONFIG, duplicate_rate=0)))
    out = run(mails, replace(CONFIG, duplicate_rate=1))
    assert out[0] is mails[0] and all(mail.duplicate_of == 0 for mail in out[1:])


def test_large_mails_and_mails_without_message_id() -> None:
    mails = list(sample_stream(400, seed=15))
    for index, mail in enumerate(mails):
        if index % 2:
            mail.raw += b"x" * (1024**2)  # too large to be copied
        else:
            assert inject_fault(mail, Fault.MISSING_MESSAGE_ID, "removed", random.Random(index))
    out = run(mails, replace(CONFIG, duplicate_rate=0.3))
    duplicates = [mail for mail in out if mail.duplicate_of is not None]
    assert duplicates
    assert all(mail.duplicate_of is not None and mail.duplicate_of % 2 == 0 for mail in duplicates)
    assert {mail.faults[Fault.DUPLICATE] for mail in duplicates} == {"exact"}


def test_redelivered_duplicates_keep_their_dkim_result() -> None:
    setup = sample_setup()
    table = setup.dns_table()
    signed = [
        sign_mail(mail, setup, stage_rng(mail.planned.seed, "dkim"))
        for mail in sample_stream(300, seed=16)
    ]
    out = run(signed, replace(CONFIG, duplicate_rate=0.3))
    checked = 0
    for duplicate in out:
        if duplicate.faults.get(Fault.DUPLICATE) == "same_message_id":
            overall, per_signature = verify_mail(duplicate.raw, table)
            assert overall is duplicate.dkim.expected
            assert per_signature == [outcome.expected for outcome in duplicate.dkim.signatures]
            checked += 1
    assert checked > 10

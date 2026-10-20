"""Acceptance: verify_mail and DkimChecker against the generator's ground truth."""

from collections import Counter

from mailrobbe.config import Settings
from mailrobbe.dkim.checker import DkimChecker, dns_override_path
from mailrobbe.dkim.verify import verify_mail
from mailrobbe.enums import DkimStatus
from tests.dkim.conftest import Corpus


def test_every_signature_matches_the_manifest(corpus: Corpus) -> None:
    seen: Counter[str] = Counter()
    for record in corpus.records:
        verdict = verify_mail(corpus.message(record), corpus.table.answer)
        expected = record["dkim"]["signatures"]
        got = [(s.status.value, s.domain, s.selector) for s in verdict.signatures]
        assert got == [(e["expected"], e["domain"], e["selector"]) for e in expected], record
        assert verdict.status.value == record["dkim"]["expected"], record["index"]
        seen[verdict.status.value] += 1
    assert set(seen) == {status.value for status in DkimStatus}


def test_checker_finds_the_generators_override_table(corpus: Corpus) -> None:
    settings = Settings(mbox_dir=corpus.mbox_dir)
    assert dns_override_path(settings) == corpus.config.meta_dir / "dns_override.json"
    checker = DkimChecker.from_settings(settings)
    for record in corpus.records[:80]:
        verdict = checker.check(corpus.message(record))
        assert verdict.status.value == record["dkim"]["expected"], record["index"]

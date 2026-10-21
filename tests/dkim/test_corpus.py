"""Acceptance: verify_mail and DkimChecker against the generator's ground truth."""

import base64
import hashlib
from collections import Counter
from datetime import datetime

import dkim
from dkim.canonicalization import CanonicalizationPolicy
from dkim.util import parse_tag_value

from mailrobbe.config import Settings
from mailrobbe.dkim.checker import DkimChecker, dns_override_path
from mailrobbe.dkim.verify import verify_mail
from mailrobbe.enums import DkimReason, DkimStatus
from tests import dkim_check
from tests.dkim.conftest import Corpus

# manifest reason -> dkim_result.reason
REASONS = {
    None: None,
    "body_modified": DkimReason.BODY_HASH_MISMATCH,
    "header_modified": DkimReason.SIGNATURE_MISMATCH,
    "selector_retired": DkimReason.KEY_NOT_FOUND,
    "dns_timeout": DkimReason.DNS_TIMEOUT,
}


def dkimpy_body_hashes_ok(raw: bytes) -> list[bool]:
    """Per signature, whether bh= matches the body as dkimpy canonicalises and hashes it."""
    headers, body = dkim.rfc822_parse(raw)
    results = []
    for name, value in headers:
        if name.lower() == b"dkim-signature":
            tags = parse_tag_value(value)
            policy = CanonicalizationPolicy.from_c_value(tags[b"c"])
            digest = hashlib.sha256(policy.canonicalize_body(body)).digest()
            results.append(digest == base64.b64decode(tags[b"bh"]))
    return results


def test_every_signature_matches_the_manifest(corpus: Corpus) -> None:
    seen: Counter[str] = Counter()
    reasons: Counter[str | None] = Counter()
    for record in corpus.records:
        raw = corpus.message(record)
        verdict = verify_mail(raw, corpus.table.answer)
        expected = record["dkim"]["signatures"]
        got = [(s.status.value, s.domain, s.selector, s.algorithm) for s in verdict.signatures]
        want = [(e["expected"], e["domain"], e["selector"], e["algorithm"]) for e in expected]
        assert got == want, record["index"]
        assert verdict.status.value == record["dkim"]["expected"], record["index"]
        date = datetime.fromisoformat(record["date"])
        body_hashes = dkimpy_body_hashes_ok(raw) if expected else []
        for position, (result, outcome) in enumerate(
            zip(verdict.signatures, expected, strict=True)
        ):
            context = (record["index"], position)
            assert result.reason is REASONS[outcome["reason"]], context
            has_key = result.status in (DkimStatus.PASS, DkimStatus.FAIL)
            assert result.key_bits == (outcome["key_bits"] if has_key else None), context
            assert result.body_hash_ok is body_hashes[position], context
            if outcome["reason"] == "body_modified":
                assert result.body_hash_ok is False, context
            elif has_key:
                assert result.body_hash_ok is True, context
            assert result.signed_at == date, context
            assert result.signed_headers is not None and "from" in result.signed_headers
            assert result.dns_cached is False
            if position == len(expected) - 1:  # the author's signature
                assert result.aligned is True, context
            reasons[outcome["reason"]] += 1
        seen[verdict.status.value] += 1
    # consistent needs a reconstructed key, which the corpus never has (D100)
    assert set(seen) == {status.value for status in DkimStatus} - {"consistent"}
    assert set(reasons) == set(REASONS)


def test_dkimpy_agrees_on_every_corpus_mail(corpus: Corpus) -> None:
    for record in corpus.records:
        raw = corpus.message(record)
        ours = [result.status for result in verify_mail(raw, corpus.table.answer).signatures]
        assert dkim_check.verify_mail(raw, corpus.table)[1] == ours, record["index"]


def test_checker_finds_the_generators_override_table(corpus: Corpus) -> None:
    settings = Settings(mbox_dir=corpus.mbox_dir)
    assert dns_override_path(settings) == corpus.config.meta_dir / "dns_override.json"
    checker = DkimChecker.from_settings(settings)
    for record in corpus.records[:80]:
        verdict = checker.check(corpus.message(record))
        assert verdict.status.value == record["dkim"]["expected"], record["index"]

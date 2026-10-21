"""`mailrobbe dkim-keys` on the generated corpus, checked once without candidate keys.

The generator signs with two keys (_generator/dkim_keys/rsa-2048.pem and rsa-1024.pem) under
every selector, and its manifest says which key size signed each signature: the ground truth for
the keys a task finds. Some mails were changed in transit after signing; what the true key says
about each signature of a retired selector (Signed) is what the check must say once a key of
the name is known. The key archive is a local HTTP server on 127.0.0.1, never the real one.
"""

import asyncio
import base64
import json
import logging
import random
import threading
import time
import urllib.parse
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import gmpy2
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import aggregates, jobrun, jobs, migrate
from mailrobbe.api.schemas import SelectorSummary
from mailrobbe.cli import main
from mailrobbe.config import Settings
from mailrobbe.dkim.keys import zkemail
from mailrobbe.dkim.keys.identity import key_identity, rsa_record, split_key_name
from mailrobbe.dkim.keys.model import DkimKeysOptions, DkimKeysProgress, DkimKeysTask
from mailrobbe.dkim.keys.run import KeysRun, run_keys
from mailrobbe.dkim.keys.store import Evidence, save_evidence, save_lookup
from mailrobbe.dkim.override import key_name
from mailrobbe.dkim.recheck import recheck
from mailrobbe.dkim.verify import key_verifies, signature_material
from mailrobbe.enums import JobKind, KeyLookupSource, KeyOrigin, LookupOutcome, origin_status
from mailrobbe.generator.config import DKIM_KEY_DIR
from mailrobbe.jobrun import RunRefused
from tests.dkim.conftest import Corpus
from tests.dkim.test_recheck import Archive, _load

pytestmark = pytest.mark.db

Outcome = tuple[str, str | None]  # dkim_result status and reason


@pytest.fixture
def checked(empty_database_url: str, corpus: Corpus) -> Archive:
    """The corpus imported as rows and checked once: retired selectors are no_key."""
    migrate.upgrade("head", empty_database_url)
    archive = Archive(
        empty_database_url, corpus.mbox_dir, asyncio.run(_load(empty_database_url, corpus))
    )
    recheck(archive.settings, statuses=None)
    return archive


# Ground truth ---------------------------------------------------------------------------------


def _private(corpus: Corpus, bits: int) -> rsa.RSAPrivateKey:
    pem = (corpus.config.meta_dir / DKIM_KEY_DIR / f"rsa-{bits}.pem").read_bytes()
    key = serialization.load_pem_private_key(pem, password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    return key


def _record(corpus: Corpus, bits: int) -> str:
    numbers = _private(corpus, bits).public_key().public_numbers()
    return rsa_record(numbers.n, numbers.e)


def _bits(corpus: Corpus) -> dict[str, int]:
    """The key size of every no_key key name."""
    return {
        key_name(signature["selector"], signature["domain"]): signature["key_bits"]
        for record in corpus.records
        for signature in record["dkim"]["signatures"]
        if signature["expected"] == "no_key"
    }


def _retired(corpus: Corpus, bits: int, mails: int = 1) -> list[str]:
    """The no_key key names of the key of `bits`, with at least `mails` mails that are no
    duplicates."""
    found: defaultdict[str, set[int]] = defaultdict(set)
    for record in corpus.records:
        for signature in record["dkim"]["signatures"]:
            name = key_name(signature["selector"], signature["domain"])
            if _bits(corpus).get(name) == bits and record["duplicate_of"] is None:
                found[name].add(record["index"])
    return sorted(name for name, indexes in found.items() if len(indexes) >= mails)


@dataclass(frozen=True, slots=True)
class Signed:
    """A signature of a retired selector, and what its true key says about it."""

    mail_id: int
    index: int
    verifies: bool  # the signed header fields are as signed
    body_ok: bool

    def after(self, origin: KeyOrigin) -> Outcome:
        """Its outcome once the key of its name is known with this origin."""
        if not self.verifies:
            return "no_key", "key_mismatch"  # the key known does not fit
        if not self.body_ok:
            return "fail", "body_hash_mismatch"
        return origin_status(origin).value, None


def _signed(corpus: Corpus, archive: Archive) -> dict[str, list[Signed]]:
    """The signatures of every no_key key name, duplicates included."""
    bits = _bits(corpus)
    truth = {size: _record(corpus, size) for size in set(bits.values())}
    found: defaultdict[str, list[Signed]] = defaultdict(list)
    for record in corpus.records:
        for material in signature_material(corpus.message(record)):
            if material.name in bits:
                verifies = key_verifies(truth[bits[material.name]], material)
                mail_id = archive.mail_ids[record["index"]]
                found[material.name].append(
                    Signed(mail_id, material.index, verifies, material.body_hash_ok)
                )
    return dict(found)


def _clean(corpus: Corpus, signed: dict[str, list[Signed]], bits: int, mails: int = 1) -> list[str]:
    """Names whose every signature verifies with an intact body."""
    return [
        name
        for name in _retired(corpus, bits, mails)
        if all(s.verifies and s.body_ok for s in signed[name])
    ]


def _expected(signed: dict[str, list[Signed]], name: str, origin: KeyOrigin) -> dict[Any, Outcome]:
    return {(s.mail_id, s.index): s.after(origin) for s in signed[name]}


def _domain(name: str) -> str:
    parts = split_key_name(name)
    assert parts is not None
    return parts[1]


def _origin_after_compare(corpus: Corpus, name: str, record: str) -> KeyOrigin:
    """Observed when today's DNS publishes the key under another selector of the domain."""
    identity = key_identity(record)
    assert identity is not None
    for other, published in corpus.table.records.items():
        same = key_identity(published)
        elsewhere = other != name and other.endswith("._domainkey." + _domain(name))
        if elsewhere and same is not None and same.key_sha256 == identity.key_sha256:
            return KeyOrigin.OBSERVED
    return KeyOrigin.RECONSTRUCTED


# Database -------------------------------------------------------------------------------------


async def _rows(url: str, sql: str, **params: Any) -> list[dict[str, Any]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            return [dict(row._mapping) for row in await connection.execute(text(sql), params)]
    finally:
        await engine.dispose()


async def _write(url: str, sql: str, **params: Any) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(sql), params)
    finally:
        await engine.dispose()


def _results(archive: Archive, name: str) -> list[dict[str, Any]]:
    """The dkim_result rows of a key name."""
    selector, _, domain = name.partition("._domainkey.")
    return asyncio.run(
        _rows(
            archive.url,
            "SELECT mail_id, signature_index, status, reason, key_id, key_origin, key_bits"
            " FROM dkim_result WHERE selector = :selector AND domain = :domain"
            " ORDER BY mail_id, signature_index",
            selector=selector,
            domain=domain,
        )
    )


def _outcomes(archive: Archive, name: str) -> dict[Any, Outcome]:
    return {
        (row["mail_id"], row["signature_index"]): (row["status"], row["reason"])
        for row in _results(archive, name)
    }


async def _store_key(url: str, name: str, record: str, origin: KeyOrigin) -> int:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as db:
            lookup = await save_lookup(
                db, KeyLookupSource.RECONSTRUCTION, name, LookupOutcome.FOUND, name=name
            )
            key_id = await save_evidence(db, lookup, name, record, Evidence(origin))
            assert key_id is not None
            return key_id
    finally:
        await engine.dispose()


def _job(archive: Archive) -> dict[str, Any]:
    sql = "SELECT * FROM job WHERE kind = 'dkim_keys' ORDER BY id DESC LIMIT 1"
    [job] = asyncio.run(_rows(archive.url, sql))
    return job


def _steps(job: dict[str, Any]) -> dict[str, tuple[str, str | None, int, int | None]]:
    progress = DkimKeysProgress.model_validate(job["progress"])
    return {step.key: (step.status, step.unit, step.done, step.total) for step in progress.steps}


def _count(archive: Archive, sql: str) -> int:
    [(count,)] = asyncio.run(archive.query(sql))
    return int(count)


def _run(
    archive: Archive, task: DkimKeysTask, settings: Settings | None = None, **options: Any
) -> KeysRun:
    chosen = DkimKeysOptions(task=task, **options)
    return asyncio.run(run_keys(settings or archive.settings, chosen))


# reconstruct ----------------------------------------------------------------------------------


def test_reconstruct_rebuilds_the_keys_of_retired_selectors(
    checked: Archive, corpus: Corpus
) -> None:
    signed = _signed(corpus, checked)
    # 1024 bits, so that a GCD takes seconds, not a minute: one name has only intact
    # signatures, the other one whose signed header changed on the way
    rebuilt, broken = names = _retired(corpus, 1024, mails=2)
    assert rebuilt in _clean(corpus, signed, 1024) and broken not in _clean(corpus, signed, 1024)
    truth = _private(corpus, 1024).public_key().public_numbers()
    unchanged = _outcomes(checked, broken)

    result = _run(checked, "reconstruct", names=names, workers=2)

    assert not result.stopped
    summary = result.summary
    assert (summary.names, summary.keys_found, summary.factorable) == (2, 1, 0)
    [key] = asyncio.run(_rows(checked.url, "SELECT id, name, origin, record FROM dkim_key"))
    identity = key_identity(key["record"])
    assert identity is not None
    assert (key["name"], identity.modulus, identity.exponent) == (rebuilt, truth.n, truth.e)
    origin = _origin_after_compare(corpus, rebuilt, key["record"])
    assert key["origin"] == origin
    assert _outcomes(checked, rebuilt) == _expected(signed, rebuilt, origin)
    assert {(row["key_id"], row["key_bits"]) for row in _results(checked, rebuilt)} == {
        (key["id"], 1024)
    }
    assert _outcomes(checked, broken) == unchanged
    mails = len({s.mail_id for s in signed[rebuilt]})
    assert summary.mails_checked == summary.mails_changed == mails

    lookups = asyncio.run(
        _rows(
            checked.url,
            "SELECT query, name, outcome, raw, raw_type, message FROM dkim_key_lookup"
            " WHERE source = 'reconstruction' ORDER BY query COLLATE \"C\"",
        )
    )
    assert [(row["query"], row["name"], row["outcome"]) for row in lookups] == [
        (rebuilt, rebuilt, "found"),
        (broken, broken, "not_found"),
    ]
    found, failed = (json.loads(row["raw"]) for row in lookups)
    assert {row["raw_type"] for row in lookups} == {"application/json"}
    assert [int(rebuilt_key["modulus"], 16) for rebuilt_key in found["keys"]] == [truth.n]
    assert len(found["read"]) >= len(found["signatures"]) >= 2 and found["unreadable"] == 0
    assert lookups[0]["message"].startswith("1 key (1024 bits) from ")
    assert (failed["keys"], len(failed["signatures"])) == ([], 2)
    assert lookups[1]["message"].startswith("no pair of the 2 signatures gives a key")
    [evidence] = asyncio.run(
        _rows(
            checked.url,
            "SELECT details, observed_from, observed_to FROM dkim_key_evidence"
            " WHERE origin = 'reconstructed'",
        )
    )
    details = evidence["details"]
    assert (details["exponent"], details["hash"]) == (65537, "sha256")
    sha256 = {record["sha256"] for record in corpus.records}
    assert {signature["mail_sha256"] for signature in details["signatures"]} <= sha256
    assert len(details["signatures"]) >= 2
    assert evidence["observed_from"] < evidence["observed_to"]  # the signatures' t=

    job = _job(checked)
    assert (job["status"], job["phase"], job["origin"]) == ("done", "aggregates", "cli")
    steps = _steps(job)
    assert list(steps) == ["select", "reconstruct", "compare", "check", *aggregates.STEPS]
    assert steps["select"] == ("done", "names", 2, None)
    assert steps["reconstruct"] == ("done", "names", 2, 2)
    assert steps["compare"][:2] == ("done", "names")
    assert steps["check"] == ("done", "mails", mails, mails)
    assert all(steps[key][0] == "done" for key in aggregates.STEPS)
    assert job["message"] == (
        f"reconstruct: 2 key names, 1 key found, 0 factorable; {mails} mails checked, "
        f"{mails} changed"
    )


def test_a_key_another_source_holds_under_another_name_lends_its_evidence(
    checked: Archive, corpus: Corpus
) -> None:
    signed = _signed(corpus, checked)
    [rebuilt, *_] = _clean(corpus, signed, 1024, mails=2)
    other = "elsewhere._domainkey." + _domain(rebuilt)
    asyncio.run(_store_key(checked.url, other, _record(corpus, 1024), KeyOrigin.DOCUMENTED))

    result = _run(checked, "reconstruct", names=[rebuilt])

    assert result.summary.keys_found == 1
    [key] = asyncio.run(
        _rows(checked.url, "SELECT id, origin FROM dkim_key WHERE name = :name", name=rebuilt)
    )
    evidence = asyncio.run(
        _rows(
            checked.url,
            "SELECT origin, details ->> 'name' AS name FROM dkim_key_evidence"
            " WHERE key_id = :key ORDER BY id",
            key=key["id"],
        )
    )
    assert {"origin": "documented", "name": other} in evidence
    assert key["origin"] in {KeyOrigin.DOCUMENTED, KeyOrigin.OBSERVED}  # observed: today's DNS
    assert _outcomes(checked, rebuilt) == _expected(signed, rebuilt, key["origin"])


def test_a_name_is_tried_again_only_with_other_signatures(checked: Archive, corpus: Corpus) -> None:
    [name, *_] = [n for n in _retired(corpus, 1024) if n not in _retired(corpus, 1024, mails=2)]
    selector, _, domain = name.partition("._domainkey.")
    asyncio.run(  # no other name is concerned any more
        _write(
            checked.url,
            "UPDATE dkim_result SET status = 'pass', reason = NULL WHERE status IN"
            " ('no_key', 'fail') AND (selector, domain) <> (:selector, :domain)",
            selector=selector,
            domain=domain,
        )
    )

    first = _run(checked, "reconstruct")
    assert (first.summary.names, first.summary.keys_found, first.summary.mails_checked) == (1, 0, 0)
    sql = "SELECT query, outcome, message FROM dkim_key_lookup"
    [lookup] = asyncio.run(_rows(checked.url, sql))
    assert (lookup["query"], lookup["outcome"]) == (name, "not_found")
    assert lookup["message"] == "1 distinct RSA signatures, two are needed"
    steps = _steps(_job(checked))
    assert steps["reconstruct"] == ("done", "names", 1, 1)
    assert all(steps[key][0] == "skipped" for key in ("check", *aggregates.STEPS))

    again = _run(checked, "reconstruct")  # the same signatures: nothing to do
    assert again.summary.names == 0
    assert _steps(_job(checked))["reconstruct"][0] == "skipped"
    given = _run(checked, "reconstruct", names=[name.upper()])  # a name given is always tried
    assert given.summary.names == 1
    assert _count(checked, "SELECT count(*) FROM dkim_key_lookup") == 2


def test_only_failures_from_before_today_s_key_are_read(checked: Archive) -> None:
    """A signature that fails with today's key is one of a replaced key only when signed
    before the first one today's key verifies; a later one is a mail changed on the way."""
    signatures = asyncio.run(
        _rows(
            checked.url,
            "WITH name AS (SELECT r.domain, r.selector FROM dkim_result r"
            " JOIN mail m ON m.id = r.mail_id"
            " WHERE r.status = 'pass' AND r.key_id IS NULL AND r.signed_at IS NOT NULL"
            " AND m.is_duplicate_of IS NULL GROUP BY r.domain, r.selector"
            " HAVING count(DISTINCT r.signed_at) >= 3"
            ' ORDER BY r.domain COLLATE "C", r.selector COLLATE "C" LIMIT 1)'
            " SELECT r.domain, r.selector, r.mail_id, r.signature_index FROM dkim_result r"
            " JOIN name USING (domain, selector) JOIN mail m ON m.id = r.mail_id"
            " WHERE r.status = 'pass' AND m.is_duplicate_of IS NULL"
            " ORDER BY r.signed_at, r.mail_id, r.signature_index",
        )
    )
    first, last = signatures[0], signatures[-1]
    name = key_name(first["selector"], first["domain"])
    asyncio.run(  # no other signature is concerned
        _write(
            checked.url,
            "UPDATE dkim_result SET status = 'pass', reason = NULL WHERE status IN"
            " ('no_key', 'fail')",
        )
    )
    for signature in (first, last):
        asyncio.run(
            _write(
                checked.url,
                "UPDATE dkim_result SET status = 'fail', reason = 'signature_mismatch',"
                " body_hash_ok = true WHERE mail_id = :mail AND signature_index = :index",
                mail=signature["mail_id"],
                index=signature["signature_index"],
            )
        )

    result = _run(checked, "reconstruct")

    assert result.summary.names == 1
    [lookup] = asyncio.run(_rows(checked.url, "SELECT query, raw FROM dkim_key_lookup"))
    assert lookup["query"] == name
    assert json.loads(lookup["raw"])["read"] == [[first["mail_id"], first["signature_index"]]]


# search ---------------------------------------------------------------------------------------


def test_search_finds_records_quoted_in_a_mail_and_in_a_document(
    checked: Archive, corpus: Corpus
) -> None:
    signed = _signed(corpus, checked)
    [mail] = asyncio.run(_rows(checked.url, "SELECT id, raw_sha256 FROM mail ORDER BY id LIMIT 1"))
    p_1024 = _record(corpus, 1024).partition("p=")[2]
    quoted = " ".join(f'"{p_1024[i : i + 60]}"' for i in range(0, len(p_1024), 60))
    body = (
        "Guten Tag,\n\nbitte tragen Sie folgenden Eintrag ein:\n\n"
        f'k2016._domainkey IN TXT ( "v=DKIM1; k=rsa; p=" {quoted} )\n\nViele Grüße\n'
    )
    der = (
        _private(corpus, 2048)
        .public_key()
        .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.PKCS1)
    )
    bare = base64.b64encode(der).decode()
    asyncio.run(
        _write(
            checked.url,
            "UPDATE mail SET body_text = :body, date_utc = :date WHERE id = :id",
            body=body,
            date=datetime(2016, 5, 4, 10, tzinfo=UTC),
            id=mail["id"],
        )
    )
    asyncio.run(
        _write(
            checked.url,
            "INSERT INTO document (sha256, mime_type, size_bytes, extracted_text, first_date)"
            " VALUES (:sha256, 'text/plain', 100, :text, :date)",
            sha256="d" * 64,
            text=f"Zonendatei\n\nselector1 TXT p={bare}\n",
            date=datetime(2019, 1, 2, tzinfo=UTC),
        )
    )
    [document] = asyncio.run(_rows(checked.url, "SELECT id FROM document"))
    bits = _bits(corpus)
    # A key counts for a name when it verifies one of its oldest signatures; in this corpus
    # that is every name with a signature whose header did not change.
    fitting = sorted(name for name in bits if any(s.verifies for s in signed[name]))
    assert len(bits) > len(fitting) > 0

    result = _run(checked, "search")

    assert result.summary.keys_found == len(fitting)
    keys = asyncio.run(
        _rows(
            checked.url,
            "SELECT k.name, k.origin, k.bits, e.reference, e.details, e.observed_from, l.source,"
            " l.query, l.raw FROM dkim_key k JOIN dkim_key_evidence e ON e.key_id = k.id"
            ' JOIN dkim_key_lookup l ON l.id = e.lookup_id ORDER BY k.name COLLATE "C"',
        )
    )
    assert [key["name"] for key in keys] == fitting
    for key in keys:
        assert (key["origin"], key["source"]) == ("documented", "archive_text")
        assert key["bits"] == bits[key["name"]]
        if key["bits"] == 1024:
            sha256 = mail["raw_sha256"]
            assert (key["reference"], key["details"]) == (f"/m/{sha256}", {"mail_sha256": sha256})
            assert key["observed_from"] == datetime(2016, 5, 4, 10, tzinfo=UTC)
            assert key["raw"].decode().startswith('v=DKIM1; k=rsa; p=" "MI')
        else:
            assert key["reference"] == f"/anhaenge/{document['id']}"
            assert key["details"] == {"document_sha256": "d" * 64}
            assert key["raw"] == f"p={bare}".encode()
        assert key["query"] == key["reference"]
        expected = _expected(signed, key["name"], KeyOrigin.DOCUMENTED)
        assert _outcomes(checked, key["name"]) == expected, key["name"]
    assert _count(checked, "SELECT count(*) FROM dkim_key_lookup") == 2  # one per text
    assert result.summary.mails_changed > 0
    assert _steps(_job(checked))["search"] == ("done", None, 2, 2)


# fetch ----------------------------------------------------------------------------------------


@contextmanager
def key_archive(
    answers: dict[str, tuple[int, Any]], *, delay: float = 0.0, slow: frozenset[str] = frozenset()
) -> Iterator[tuple[str, list[dict[str, str]]]]:
    """A ZK Email archive on 127.0.0.1: domain -> (status, JSON body), [] for other domains;
    each answer after `delay` seconds, those for `slow` domains after two."""
    requests: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            domain = query["domain"][0]
            requests.append({"domain": domain, "user_agent": self.headers["User-Agent"]})
            status, body = answers.get(domain, (200, []))
            time.sleep(2.0 if domain in slow else delay)
            data = json.dumps(body).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:  # the client gave up waiting
                pass

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", requests
    finally:
        server.shutdown()
        server.server_close()


def _entry(name: str, record: str, *sources: str) -> dict[str, Any]:
    selector, _, domain = name.partition("._domainkey.")
    seen = {"firstSeenAt": "2016-01-01T00:00:00Z", "lastSeenAt": "2016-12-31T00:00:00Z"}
    return {
        "domain": domain,
        "selector": selector,
        "value": record,
        "id": len(name),
        "firstSeenAt": "2015-01-01T00:00:00Z",
        "lastSeenAt": "2017-01-01T00:00:00Z",
        "observations": [{"source": source, **seen} for source in sources],
    }


def _concerned_domains(archive: Archive) -> list[str]:
    async def plan() -> list[str]:
        engine = create_async_engine(archive.url, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                found = await zkemail.fetch_plan(connection, "http://127.0.0.1:1")
                return [domain.domain for domain in found.domains]
        finally:
            await engine.dispose()

    return asyncio.run(plan())


def test_fetch_asks_the_archive_once_per_domain(checked: Archive, corpus: Corpus) -> None:
    signed = _signed(corpus, checked)
    observed = _clean(corpus, signed, 1024, mails=2)[0]
    recovered = next(
        n for n in _clean(corpus, signed, 2048, mails=2) if _domain(n) != _domain(observed)
    )
    domains = _concerned_domains(checked)
    failing, slow = [d for d in domains if d not in (_domain(observed), _domain(recovered))][:2]
    answers = {
        _domain(observed): (
            200,
            [
                _entry(observed, _record(corpus, 1024), "gcd_recovered", "live_dns"),
                _entry(f"revoked._domainkey.{_domain(observed)}", "v=DKIM1; p=", "live_dns"),
            ],
        ),
        _domain(recovered): (200, [_entry(recovered, _record(corpus, 2048), "gcd_recovered")]),
        failing: (500, {"error": "internal"}),
    }

    with key_archive(answers, slow=frozenset({slow})) as (url, requests):
        settings = checked.settings.model_copy(
            update={"dkim_key_archive_url": url + "/", "dkim_key_archive_timeout": 0.5}
        )
        result = _run(checked, "fetch", settings)

    assert not result.stopped and result.summary.skipped_domains == []
    assert sorted(request["domain"] for request in requests) == sorted(domains)
    assert {request["user_agent"] for request in requests} == {zkemail.USER_AGENT}
    sql = (
        "SELECT domain, query, outcome, http_status, message, raw FROM dkim_key_lookup"
        " WHERE source = 'zkemail'"
    )
    lookups = {row["domain"]: row for row in asyncio.run(_rows(checked.url, sql))}
    assert sorted(lookups) == sorted(domains)
    outcomes = {domain: (row["outcome"], row["http_status"]) for domain, row in lookups.items()}
    assert outcomes.pop(_domain(observed)) == outcomes.pop(_domain(recovered)) == ("found", 200)
    assert outcomes.pop(failing) == ("error", 500)
    assert outcomes.pop(slow) == ("error", None)
    assert set(outcomes.values()) == {("not_found", 200)}
    assert lookups[slow]["message"] == "no answer within 0.5 s"
    assert lookups[failing]["raw"] == b'{"error": "internal"}'  # stored as it came
    assert lookups[_domain(observed)]["query"] == f"{url}/api/key?domain={_domain(observed)}"

    keys = asyncio.run(_rows(checked.url, "SELECT name, origin FROM dkim_key"))
    expected = _origin_after_compare(corpus, recovered, _record(corpus, 2048))
    assert {key["name"]: key["origin"] for key in keys} == {
        observed: "observed",
        recovered: expected,
    }
    [live] = asyncio.run(
        _rows(
            checked.url,
            "SELECT e.details, e.observed_from, e.observed_to FROM dkim_key_evidence e"
            " JOIN dkim_key k ON k.id = e.key_id WHERE k.name = :name",
            name=observed,
        )
    )
    assert live["details"]["sources"] == ["gcd_recovered", "live_dns"]
    assert live["observed_from"].year == live["observed_to"].year == 2016  # live_dns times
    assert _outcomes(checked, observed) == _expected(signed, observed, KeyOrigin.OBSERVED)
    assert _outcomes(checked, recovered) == _expected(signed, recovered, expected)

    # Elsewhere than on this machine, domains under reserved TLDs are never sent.
    lookups_before = _count(checked, "SELECT count(*) FROM dkim_key_lookup")
    remote = checked.settings.model_copy(update={"dkim_key_archive_url": "http://192.0.2.1:9"})
    elsewhere = _run(checked, "fetch", remote)
    assert elsewhere.summary.skipped_domains == sorted(_concerned_domains(checked))
    assert _count(checked, "SELECT count(*) FROM dkim_key_lookup") == lookups_before
    job = _job(checked)
    assert job["message"].endswith(
        f"; {len(elsewhere.summary.skipped_domains)} domains under reserved TLDs skipped"
    )
    assert _steps(job)["fetch"][0] == "skipped"

    off = checked.settings.model_copy(update={"dkim_key_archive_url": "off"})
    with pytest.raises(RunRefused, match="switched off"):
        _run(checked, "fetch", off)


def test_a_stop_ends_the_fetch_but_checks_what_it_found(
    checked: Archive, corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobrun, "REPORT_SECONDS", 0.05)
    signed = _signed(corpus, checked)
    by_domain: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, bits in _bits(corpus).items():
        by_domain[_domain(name)].append(_entry(name, _record(corpus, bits), "live_dns"))
    answers = {domain: (200, entries) for domain, entries in by_domain.items()}
    domains = _concerned_domains(checked)
    before = {name: _outcomes(checked, name) for name in signed}

    async def stopped_run(url: str) -> KeysRun:
        settings = checked.settings.model_copy(update={"dkim_key_archive_url": url})
        run = asyncio.create_task(run_keys(settings, DkimKeysOptions(task="fetch")))
        engine = create_async_engine(checked.url, poolclass=pool.NullPool)
        try:
            async with asyncio.timeout(30):
                while not await checked.query("SELECT 1 FROM dkim_key_lookup"):
                    await asyncio.sleep(0.02)
            async with engine.begin() as connection:
                assert await jobs.request_stop(connection, JobKind.DKIM_KEYS) is not None
            return await asyncio.wait_for(run, 30)
        finally:
            run.cancel()
            await engine.dispose()

    with key_archive(answers, delay=0.3) as (url, _):
        result = asyncio.run(stopped_run(url))

    assert result.stopped
    asked = {row[0] for row in asyncio.run(checked.query("SELECT domain FROM dkim_key_lookup"))}
    assert 1 <= len(asked) < len(domains)
    assert result.summary.mails_changed > 0
    for name in signed:  # the keys found are checked all the same
        if _domain(name) in asked:
            assert _outcomes(checked, name) == _expected(signed, name, KeyOrigin.OBSERVED), name
        else:
            assert _outcomes(checked, name) == before[name], name
    job = _job(checked)
    assert job["status"] == "stopped"
    steps = _steps(job)
    assert steps["fetch"][:3] == ("stopped", "domains", len(asked))
    assert steps["check"][0] == "done"


# check ----------------------------------------------------------------------------------------


def test_check_follows_a_key_that_turns_factorable(checked: Archive, corpus: Corpus) -> None:
    signed = _signed(corpus, checked)
    name = _clean(corpus, signed, 1024, mails=2)[0]
    other = next(n for n in _retired(corpus, 1024) if _domain(n) != _domain(name))
    before = _results(checked, name)
    statuses = dict(asyncio.run(checked.query("SELECT id, dkim_status FROM mail")))
    record = _record(corpus, 1024)
    key_id = asyncio.run(_store_key(checked.url, name, record, KeyOrigin.RECONSTRUCTED))

    found = _run(checked, "check", names=[name])

    mails = sorted({row["mail_id"] for row in before})
    assert found.summary.transitions == dict(
        Counter(f"{statuses[mail]} -> consistent" for mail in mails)
    )
    assert _outcomes(checked, name) == _expected(signed, name, KeyOrigin.RECONSTRUCTED)
    assert {(row["key_id"], row["key_origin"]) for row in _results(checked, name)} == {
        (key_id, "reconstructed")
    }
    steps = _steps(_job(checked))
    assert list(steps) == ["select", "check", *aggregates.STEPS]
    assert steps["select"] == ("done", "names", 1, None)

    # A key of another domain shares a prime with it: both keys are factorable, never used.
    prime = _private(corpus, 1024).private_numbers().p
    cofactor = int(gmpy2.next_prime(random.Random(1).getrandbits(512) | (1 << 511)))
    shared = rsa_record(prime * cofactor, 65537)
    asyncio.run(_store_key(checked.url, other, shared, KeyOrigin.RECONSTRUCTED))
    flagged = _run(checked, "search")  # no text quotes a key; compare runs all the same
    assert flagged.summary.factorable == 2
    sql = 'SELECT name, factorable FROM dkim_key ORDER BY name COLLATE "C"'
    assert asyncio.run(checked.query(sql)) == sorted([(name, True), (other, True)])
    assert _results(checked, name) == before
    assert flagged.summary.transitions == dict(
        Counter(f"consistent -> {statuses[mail]}" for mail in mails)
    )


# The commands ---------------------------------------------------------------------------------


def test_the_commands(
    checked: Archive,
    corpus: Corpus,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MAILROBBE_DATABASE_URL", checked.url)
    monkeypatch.setenv("MAILROBBE_MBOX_DIR", str(checked.mbox_dir))
    signed = _signed(corpus, checked)
    rebuilt, documented, *_ = _clean(corpus, signed, 1024)
    record = _record(corpus, 1024)

    # `mailrobbe dkim` checks with the keys found
    asyncio.run(_store_key(checked.url, rebuilt, record, KeyOrigin.RECONSTRUCTED))
    assert main(["dkim", "--status", "no_key", "temp_error"]) == 0
    capsys.readouterr()
    assert _outcomes(checked, rebuilt) == _expected(signed, rebuilt, KeyOrigin.RECONSTRUCTED)

    # add: the record from a zone file, the file kept as the source's answer
    selector = documented.partition(".")[0]
    zone = tmp_path / "zone.txt"
    zone.write_text(f'{selector}._domainkey IN TXT ( "{record}" )\n')
    argv = ["dkim-keys", "add", "--name", documented.upper(), "--record-file", str(zone)]
    argv += ["--reference", "Zonendatei vom Provider, Ticket 4711", "--note", "per Post"]
    argv += ["--evidence-file", str(zone), "--editor", "Anna", "--observed-from", "2016-01-01"]
    assert main(argv) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["task"] == "check" and summary["mails_changed"] > 0
    assert _outcomes(checked, documented) == _expected(signed, documented, KeyOrigin.DOCUMENTED)
    [row] = asyncio.run(
        _rows(
            checked.url,
            "SELECT l.query, l.raw, l.raw_type, l.raw_name, l.editor, e.origin, e.reference,"
            " e.note, e.observed_from FROM dkim_key_lookup l"
            " JOIN dkim_key_evidence e ON e.lookup_id = l.id WHERE l.source = 'manual'",
        )
    )
    assert row["raw"] == zone.read_bytes()
    assert (row["query"], row["raw_type"], row["raw_name"], row["editor"]) == (
        documented,
        "text/plain",
        "zone.txt",
        "Anna",
    )
    assert (row["origin"], row["note"], row["observed_from"]) == (
        "documented",
        "per Post",
        datetime(2016, 1, 1, tzinfo=UTC),
    )
    assert row["reference"] == "Zonendatei vom Provider, Ticket 4711"

    base = ["dkim-keys", "add", "--reference", "r", "--name"]
    assert main([*base, "kein.name", "--record", record]) == 2
    assert main([*base, documented, "--record", "v=DKIM1; k=rsa; p="]) == 2
    assert main([*base, documented, "--record-file", str(tmp_path / "missing.txt")]) == 2
    assert "not a DKIM key name" in caplog.text and "no usable DKIM key" in caplog.text

    # status: the figures of the dashboard card
    capsys.readouterr()
    assert main(["dkim-keys", "status"]) == 0
    figures = SelectorSummary.model_validate_json(capsys.readouterr().out)
    sql = "SELECT count(*) FROM mail WHERE dkim_status = 'no_key'"
    assert figures.mails_missing == _count(checked, sql)
    assert (figures.names_missing, figures.names_resolved) == (len(_bits(corpus)) - 2, 2)
    assert figures.keys[KeyOrigin.RECONSTRUCTED] == figures.keys[KeyOrigin.DOCUMENTED] == 1
    assert figures.signatures[KeyOrigin.RECONSTRUCTED] == len(signed[rebuilt])
    assert figures.lookups[KeyLookupSource.MANUAL] == 1
    assert figures.last_lookup_at is not None

    # the dashboard's arguments; a fetch while the archive is switched off
    assert main(["dkim-keys", "--origin", "ui", "check", f"--name={rebuilt}", "--jobs=1"]) == 0
    assert _job(checked)["origin"] == "ui"
    monkeypatch.setenv("MAILROBBE_DKIM_KEY_ARCHIVE_URL", "off")
    with caplog.at_level(logging.ERROR):
        assert main(["dkim-keys", "fetch", "--domain", "netzpost.example"]) == 1
    assert "the key archive is switched off" in caplog.text

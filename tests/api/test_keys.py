"""The keys API (D100 to D104), and what the mail detail and the export show of a key from
another source than today's DNS (D105).

The imported archive has no such keys, so the tests add them the way `mailrobbe dkim-keys`
stores them (dkim.keys.store): the key of a retired selector, reconstructed from two of its
signatures (the generator's own key), with the mails it verifies set to consistent as the check
after a reconstruction sets them. Expected figures come from direct SQL; runs are
tests/api/fake_run.py, as in test_imports.py.
"""

import base64
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api import keys
from mailrobbe.api.schemas import (
    DkimKeyInfo,
    KeyEvidenceInfo,
    SelectorItem,
    SelectorSummary,
    UsedSignature,
)
from mailrobbe.config import Settings
from mailrobbe.dkim.keys.identity import key_identity
from mailrobbe.dkim.keys.store import Evidence, save_evidence, save_lookup
from mailrobbe.dkim.model import DnsAnswer, KeySource
from mailrobbe.dkim.override import key_name
from mailrobbe.dkim.resolver import is_reserved
from mailrobbe.dkim.verify import verify_mail
from mailrobbe.enums import (
    DkimStatus,
    DnsStatus,
    KeyLookupSource,
    KeyOrigin,
    LookupOutcome,
    best_dkim_status,
)
from mailrobbe.export.keys import CHECK_SCRIPT
from mailrobbe.export.pdf import CONSISTENT_TEXT
from mailrobbe.generator.config import DKIM_KEY_DIR
from mailrobbe.mbox import read_message
from tests.api.conftest import _client, api_settings
from tests.api.test_exports import Zip
from tests.api.test_imports import Dashboard, error_code, fake, post, serve, until
from tests.api.test_mails import get, rows
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

EDITOR = {"X-Mailrobbe-Editor": "Lena%20Vogt"}
LOCAL_ARCHIVE = "http://127.0.0.1:8765/"


@dataclass(frozen=True, slots=True)
class Retired:
    """A retired key name whose key was reconstructed, as this test's database now holds it."""

    name: str
    domain: str
    selector: str
    record: str
    bits: int
    key_id: int
    key_sha256: str
    lookup_id: int
    evidence_id: int
    answer: bytes  # the reconstruction lookup's stored answer
    used: list[Any]  # the two signatures the key was computed from
    verified: list[Any]  # every signature the key verifies now, duplicates included


def _generator_records(archive: GeneratedArchive) -> list[str]:
    """The key records of the generator's test keys, which sign every selector."""
    records = []
    for pem in sorted((archive.config.meta_dir / DKIM_KEY_DIR).glob("rsa-*.pem")):
        key = serialization.load_pem_private_key(pem.read_bytes(), password=None)
        der = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        records.append("v=DKIM1; k=rsa; p=" + base64.b64encode(der).decode())
    return records


def _publishing(record: str) -> KeySource:
    def lookup(name: str) -> DnsAnswer:
        return DnsAnswer(name, DnsStatus.FOUND, record, datetime.now(UTC), 0)

    return lookup


@pytest.fixture
def settings(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> Settings:
    return api_settings(mutable_database_url, generated_archive, tmp_path / "no-frontend")


@pytest.fixture
async def retired(settings: Settings, generated_archive: GeneratedArchive) -> Retired:
    """The retired name with the most intact signatures gets its key back, reconstructed."""
    url = settings.database_url
    found = await rows(
        url,
        "SELECT r.mail_id, r.signature_index, r.domain, r.selector, m.raw_sha256, "
        "m.is_duplicate_of IS NOT NULL AS duplicate, f.path, m.byte_offset, m.byte_length "
        "FROM dkim_result r JOIN mail m ON m.id = r.mail_id "
        "JOIN mbox_file f ON f.id = m.mbox_file_id "
        "WHERE r.status = 'no_key' AND r.reason = 'key_not_found' "
        "ORDER BY r.mail_id, r.signature_index",
    )
    by_name: dict[str, list[Any]] = defaultdict(list)
    for row in found:
        by_name[key_name(row.selector, row.domain)].append(row)
    records = _generator_records(generated_archive)
    for name, signatures in sorted(by_name.items(), key=lambda item: (-len(item[1]), item[0])):
        raw = {
            row.mail_id: read_message(
                generated_archive.mbox_dir / row.path, row.byte_offset, row.byte_length
            )
            for row in signatures
        }
        for record in records:
            verified = [
                row
                for row in signatures
                if verify_mail(raw[row.mail_id], _publishing(record))
                .signatures[row.signature_index]
                .status
                is DkimStatus.PASS
            ]
            if sum(not row.duplicate for row in verified) >= 3:
                return await _reconstructed(url, name, record, verified)
    raise AssertionError("no retired name with three intact signatures")


async def _reconstructed(url: str, name: str, record: str, verified: list[Any]) -> Retired:
    used = [row for row in verified if not row.duplicate][:2]
    details = {
        "exponent": 65537,
        "hash": "sha256",
        "signatures": [
            {
                "mail_id": r.mail_id,
                "signature_index": r.signature_index,
                "mail_sha256": r.raw_sha256,
            }
            for r in used
        ],
    }
    answer = json.dumps(details).encode()
    domain = verified[0].domain
    identity = key_identity(record)
    assert identity is not None
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            lookup_id = await save_lookup(
                connection,
                KeyLookupSource.RECONSTRUCTION,
                name,
                LookupOutcome.FOUND,
                domain=domain,
                name=name,
                raw=answer,
                raw_type="application/json",
            )
            key_id = await save_evidence(
                connection,
                lookup_id,
                name,
                record,
                Evidence(KeyOrigin.RECONSTRUCTED, details=details),
            )
            assert key_id is not None
            for row in verified:
                await connection.execute(
                    text(
                        "UPDATE dkim_result SET status = 'consistent', reason = NULL, "
                        "key_id = :key_id, key_origin = 'reconstructed', key_bits = :bits "
                        "WHERE mail_id = :mail_id AND signature_index = :index"
                    ),
                    {
                        "key_id": key_id,
                        "bits": identity.bits,
                        "mail_id": row.mail_id,
                        "index": row.signature_index,
                    },
                )
            statuses = await connection.execute(
                text("SELECT mail_id, status FROM dkim_result WHERE mail_id = ANY(:ids)"),
                {"ids": sorted({row.mail_id for row in verified})},
            )
            by_mail: dict[int, list[DkimStatus]] = defaultdict(list)
            for mail_id, status in statuses:
                by_mail[mail_id].append(DkimStatus(status))
            for mail_id, found in by_mail.items():
                await connection.execute(
                    text("UPDATE mail SET dkim_status = :status WHERE id = :id"),
                    {"status": best_dkim_status(found).value, "id": mail_id},
                )
            evidence_id = await connection.scalar(
                text("SELECT id FROM dkim_key_evidence WHERE key_id = :key_id"), {"key_id": key_id}
            )
    finally:
        await engine.dispose()
    assert evidence_id is not None
    return Retired(
        name=name,
        domain=domain,
        selector=verified[0].selector,
        record=record,
        bits=identity.bits,
        key_id=key_id,
        key_sha256=identity.key_sha256,
        lookup_id=lookup_id,
        evidence_id=evidence_id,
        answer=answer,
        used=used,
        verified=verified,
    )


@pytest.fixture
async def dashboard(settings: Settings, retired: Retired) -> AsyncIterator[Dashboard]:
    """The app on this test's database with the reconstructed key, without any job rows."""
    await rows(settings.database_url, "DELETE FROM job")
    async with serve(settings) as dashboard:
        yield dashboard


async def _reaped(dashboard: Dashboard) -> None:
    async def none_left() -> bool:
        return not dashboard.runs.children

    await until(none_left)


# Expected figures from direct SQL -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Expected:
    items: list[SelectorItem]  # every name with a signature on a mail that is no duplicate
    open: set[str]
    resolved: set[str]
    signatures: list[Any]  # those signatures


async def _expected(url: str) -> Expected:
    signatures = await rows(
        url,
        "SELECT r.* FROM dkim_result r JOIN mail m ON m.id = r.mail_id "
        "WHERE m.is_duplicate_of IS NULL AND r.domain IS NOT NULL AND r.selector IS NOT NULL",
    )
    stored = await rows(url, "SELECT name, origin, factorable FROM dkim_key")
    dns = {row.name: row.status for row in await rows(url, "SELECT name, status FROM dns_cache")}
    named: dict[str, list[Any]] = defaultdict(list)
    for row in signatures:
        named[key_name(row.selector, row.domain)].append(row)
    items, opened, resolved = [], set(), set()
    for name, found in named.items():
        own = [key for key in stored if key.name == name]
        origins = [KeyOrigin(key.origin) for key in own if not key.factorable]
        signed = [row.signed_at for row in found if row.signed_at]
        items.append(
            SelectorItem(
                name=name,
                domain=found[0].domain,
                selector=found[0].selector,
                signatures=len(found),
                mails=len({row.mail_id for row in found}),
                statuses=Counter(DkimStatus(row.status) for row in found),
                rsa_signatures=sum((row.algorithm or "").startswith("rsa-") for row in found),
                first_signed=min(signed, default=None),
                last_signed=max(signed, default=None),
                keys=len(own),
                best_origin=min(origins, key=list(KeyOrigin).index, default=None),
                dns_status=dns.get(name),
            )
        )
        if any(_open(row) for row in found):
            opened.add(name)
        if any(row.key_id is not None for row in found):
            resolved.add(name)
    items.sort(key=lambda item: (-item.mails, item.name.encode()))
    return Expected(items, opened, resolved, signatures)


def _open(row: Any) -> bool:
    return bool(
        row.status == "no_key"
        or (row.status == "fail" and row.reason == "signature_mismatch" and row.body_hash_ok)
    )


async def _listed(client: httpx.AsyncClient, params: list[tuple[str, str]]) -> list[SelectorItem]:
    """Every page of the selector list, seven names at a time."""
    found: list[SelectorItem] = []
    total = None
    while True:
        page = await get(
            client, "/api/dkim/selectors", [*params, ("limit", "7"), ("offset", str(len(found)))]
        )
        assert total in (None, page["total"])
        total = page["total"]
        found += map(SelectorItem.model_validate, page["items"])
        if len(page["items"]) < 7:
            assert len(found) == total
            return found


# Selector list, summary and page --------------------------------------------------------------


async def test_the_selector_list_by_filter_and_search(
    dashboard: Dashboard, retired: Retired
) -> None:
    expected = await _expected(dashboard.url)
    assert retired.name in expected.resolved
    assert expected.open - expected.resolved and expected.resolved
    shown = {
        "open": [item for item in expected.items if item.name in expected.open],
        "resolved": [item for item in expected.items if item.name in expected.resolved],
        "all": expected.items,
    }
    client = dashboard.client
    assert await _listed(client, []) == shown["open"]  # open by default
    for show, items in shown.items():
        assert await _listed(client, [("show", show)]) == items, show
    item = next(item for item in shown["resolved"] if item.name == retired.name)
    assert (item.keys, item.best_origin) == (1, KeyOrigin.RECONSTRUCTED)
    assert item.statuses[DkimStatus.CONSISTENT] == sum(not r.duplicate for r in retired.verified)

    part = retired.domain.split(".")[0].upper()
    assert await _listed(client, [("show", "all"), ("q", f"  {part} ")]) == [
        item for item in expected.items if part.lower() in item.name
    ]
    assert await _listed(client, [("show", "all"), ("q", "%_")]) == []  # LIKE signs are literal
    empty = await get(client, "/api/dkim/selectors", [("show", "all"), ("offset", "100000")])
    assert empty == {"items": [], "total": len(expected.items)}
    await get(client, "/api/dkim/selectors", [("show", "some")], status=422)
    await get(client, "/api/dkim/selectors", [("limit", "0")], status=422)


async def test_the_summary(dashboard: Dashboard, retired: Retired) -> None:
    expected = await _expected(dashboard.url)
    by_name: dict[str, list[Any]] = defaultdict(list)
    for row in expected.signatures:
        by_name[key_name(row.selector, row.domain)].append(row)
    missing = {name for name, found in by_name.items() if any(r.status == "no_key" for r in found)}
    mails = dict(
        await rows(
            dashboard.url,
            "SELECT dkim_status::text, count(*) FROM mail WHERE is_duplicate_of IS NULL "
            "GROUP BY dkim_status",
        )
    )
    asked = await rows(dashboard.url, "SELECT max(asked_at) FROM dkim_key_lookup")
    summary = SelectorSummary.model_validate(
        await get(dashboard.client, "/api/dkim/selectors/summary")
    )
    assert summary == SelectorSummary(
        names_missing=len(missing),
        mails_missing=mails.get("no_key", 0),
        reconstructable=sum(
            item.rsa_signatures >= 2 for item in expected.items if item.name in missing
        ),
        names_resolved=len(expected.resolved),
        mails_consistent=mails["consistent"],
        keys={origin: int(origin is KeyOrigin.RECONSTRUCTED) for origin in KeyOrigin},
        factorable=0,
        signatures={
            origin: sum(r.key_origin == origin for r in expected.signatures) for origin in KeyOrigin
        },
        lookups={
            source: int(source is KeyLookupSource.RECONSTRUCTION) for source in KeyLookupSource
        },
        last_lookup_at=asked[0][0],
    )
    assert summary.names_missing > 0 and summary.reconstructable > 0
    assert summary.mails_consistent == len({r.mail_id for r in retired.verified if not r.duplicate})


async def test_the_page_of_a_name_with_a_reconstructed_key(
    dashboard: Dashboard, retired: Retired
) -> None:
    expected = await _expected(dashboard.url)
    item = next(item for item in expected.items if item.name == retired.name)
    page = await get(dashboard.client, f"/api/dkim/selectors/{retired.name.upper()}.")
    assert {name: page[name] for name in ("name", "domain", "selector", "dns_status")} == {
        "name": retired.name,
        "domain": retired.domain,
        "selector": retired.selector,
        "dns_status": "not_found",  # retired: the override table no longer publishes it
    }
    assert (
        SelectorItem.model_validate(
            page | {"keys": 1, "best_origin": "reconstructed", "dns_status": item.dns_status}
        )
        == item
    )
    verifies = sum(not row.duplicate for row in retired.verified)
    assert [DkimKeyInfo.model_validate(key) for key in page["keys"]] == [
        DkimKeyInfo(
            id=retired.key_id,
            name=retired.name,
            key_type="rsa",
            bits=retired.bits,
            key_sha256=retired.key_sha256,
            record=retired.record,
            origin=KeyOrigin.RECONSTRUCTED,
            factorable=False,
            signatures=verifies,
            evidence=[
                KeyEvidenceInfo(
                    id=retired.evidence_id,
                    origin=KeyOrigin.RECONSTRUCTED,
                    source=KeyLookupSource.RECONSTRUCTION,
                    lookup_id=retired.lookup_id,
                    asked_at=page["keys"][0]["evidence"][0]["asked_at"],
                    observed_from=None,
                    observed_to=None,
                    reference=None,
                    note=None,
                    editor=None,
                    raw_sha256=hashlib.sha256(retired.answer).hexdigest(),
                    raw_size=len(retired.answer),
                    signatures=[
                        UsedSignature(
                            mail_id=row.mail_id,
                            mail_sha256=row.raw_sha256,
                            signature_index=row.signature_index,
                        )
                        for row in retired.used
                    ],
                )
            ],
        )
    ]
    [lookup] = page["lookups"]
    assert (lookup["id"], lookup["source"], lookup["keys"]) == (
        retired.lookup_id,
        "reconstruction",
        1,
    )
    assert (lookup["raw_type"], lookup["raw_size"]) == ("application/json", len(retired.answer))

    own = [row for row in expected.signatures if key_name(row.selector, row.domain) == retired.name]
    own.sort(
        key=lambda row: (
            row.signed_at is None,
            -row.signed_at.timestamp() if row.signed_at else 0,
            -row.mail_id,
            row.signature_index,
        )
    )
    recent = page["recent_mails"]
    assert [(m["id"], m["signature_index"]) for m in recent] == [
        (row.mail_id, row.signature_index) for row in own
    ]
    verified = {(row.mail_id, row.signature_index) for row in retired.verified}
    for mail in recent:
        rests = (mail["id"], mail["signature_index"]) in verified
        assert (mail["status"], mail["key_id"], mail["key_origin"]) == (
            ("consistent", retired.key_id, "reconstructed") if rests else ("no_key", None, None)
        )


async def test_unknown_names(dashboard: Dashboard) -> None:
    client = dashboard.client
    response = await client.get("/api/dkim/selectors/nothing._domainkey.nowhere.example")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "not_found")
    for name in ("nothing", "._domainkey.firma.example", "a._domainkey."):
        response = await client.get(f"/api/dkim/selectors/{name}")
        assert (response.status_code, response.json()["detail"]["code"]) == (400, "invalid_key")


# Manual keys and raw answers ------------------------------------------------------------------


async def _open_name(url: str, retired: Retired) -> str:
    """The name with the most open signatures besides the reconstructed one."""
    expected = await _expected(url)
    return next(
        item.name
        for item in expected.items
        if item.name in expected.open and item.name != retired.name
    )


async def test_a_manual_key_with_an_evidence_file(
    dashboard: Dashboard,
    retired: Retired,
    generated_archive: GeneratedArchive,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake(monkeypatch, "done")
    client = dashboard.client
    name = await _open_name(dashboard.url, retired)
    record = _generator_records(generated_archive)[-1]
    p = record.partition("p=")[2]
    evidence = b'; zone file of 2019\nsel._domainkey IN TXT "v=DKIM1; p=..."\n\xff\x00'
    body = {
        "record": f'"v=DKIM1; k=rsa; " "p={p[:40]}" "{p[40:]}"',
        "reference": "  Zonendatei vom Provider, Mail vom 3. März 2020  ",
        "note": "",
        "observed_from": "2019-01-01T00:00:00Z",
        "observed_to": "2020-06-30T00:00:00+02:00",
        "file_name": "zone 2019.txt",
        "file_base64": base64.b64encode(evidence).decode(),
    }
    response = await client.post(
        f"/api/dkim/selectors/{name.upper()}/keys", json=body, headers=EDITOR
    )
    assert response.status_code == 201, response.text
    page = response.json()
    assert page["name"] == name
    [key] = page["keys"]
    identity = key_identity(record)
    assert identity is not None
    assert (key["origin"], key["key_sha256"], key["bits"], key["signatures"]) == (
        "documented",
        identity.key_sha256,
        identity.bits,
        0,  # the check run verifies its signatures
    )
    assert key["record"] == f"v=DKIM1; k=rsa; p={p}"
    [item] = key["evidence"]
    assert {
        field: item[field] for field in ("origin", "source", "reference", "note", "editor")
    } == {
        "origin": "documented",
        "source": "manual",
        "reference": "Zonendatei vom Provider, Mail vom 3. März 2020",
        "note": None,
        "editor": "Lena Vogt",
    }
    assert (item["observed_from"], item["observed_to"]) == (
        "2019-01-01T00:00:00Z",
        "2020-06-29T22:00:00Z",
    )
    assert (item["raw_sha256"], item["raw_size"]) == (
        hashlib.sha256(evidence).hexdigest(),
        len(evidence),
    )
    [lookup] = [lookup for lookup in page["lookups"] if lookup["id"] == item["lookup_id"]]
    assert (lookup["source"], lookup["query"], lookup["raw_name"], lookup["raw_type"]) == (
        "manual",
        name,
        "zone 2019.txt",
        "text/plain",
    )

    raw = await client.get(f"/api/dkim/lookups/{item['lookup_id']}/raw")
    assert raw.status_code == 200
    assert raw.content == evidence
    assert raw.headers["content-type"].startswith("text/plain")
    assert raw.headers["x-mailrobbe-sha256"] == hashlib.sha256(evidence).hexdigest()
    assert 'filename="zone 2019.txt"' in raw.headers["content-disposition"]

    await _reaped(dashboard)
    [job] = await rows(dashboard.url, "SELECT kind::text, origin::text, options FROM job")
    assert (job.kind, job.origin) == ("dkim_keys", "ui")
    assert (job.options["task"], job.options["names"]) == ("check", [name])


async def test_a_manual_key_while_a_run_is_alive(
    dashboard: Dashboard,
    retired: Retired,
    generated_archive: GeneratedArchive,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake(monkeypatch, "wait")
    client = dashboard.client
    started = await post(client, "/api/dkim/keys/run", {"task": "reconstruct"}, 202)
    name = await _open_name(dashboard.url, retired)
    p = _generator_records(generated_archive)[0].partition("p=")[2]
    response = await client.post(
        f"/api/dkim/selectors/{name}/keys", json={"record": p, "reference": "Screenshot"}
    )
    assert response.status_code == 201, response.text
    [key] = response.json()["keys"]
    assert (key["origin"], key["evidence"][0]["editor"], key["evidence"][0]["raw_size"]) == (
        "documented",
        None,
        None,
    )
    jobs = await rows(dashboard.url, "SELECT id FROM job")
    assert [job.id for job in jobs] == [started["id"]]  # the key waits for the next check
    stopped = await post(client, "/api/dkim/keys/run/stop", {})
    assert stopped["stop_requested"] is True
    await _reaped(dashboard)


async def test_manual_keys_that_are_refused(
    dashboard: Dashboard, retired: Retired, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "done")
    client = dashboard.client
    path = f"/api/dkim/selectors/{retired.name}/keys"
    good = {"record": retired.record, "reference": "Akte 7"}

    response = await client.post(path, content=json.dumps(good).encode())  # no content type
    assert response.status_code == 415
    response = await client.post(
        path, content=json.dumps(good), headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 415
    await post(client, path, {"record": retired.record}, 422)  # no reference
    await post(client, path, good | {"reference": ""}, 422)
    for record in ("v=DKIM1; k=rsa; p=", "v=DKIM1; k=rsa; p=QUJD", "hello, world"):
        assert await error_code(client, path, good | {"record": record}, 400) == "invalid_key"
    for file in ("not base64!", "QUJ", "data:text/plain;base64,@@"):
        body = good | {"file_name": "x.txt", "file_base64": file}
        assert await error_code(client, path, body, 400) == "invalid_option"
    monkeypatch.setattr(keys, "EVIDENCE_FILE_LIMIT", 16)
    body = good | {"file_base64": base64.b64encode(b"x" * 17).decode()}
    assert await error_code(client, path, body, 400) == "invalid_option"
    body = good | {"observed_from": "2021-01-01T00:00:00Z", "observed_to": "2020-01-01T00:00:00Z"}
    assert await error_code(client, path, body, 400) == "invalid_option"
    unknown = "/api/dkim/selectors/nothing._domainkey.nowhere.example/keys"
    assert await error_code(client, unknown, good, 404) == "not_found"
    assert await error_code(client, "/api/dkim/selectors/nothing/keys", good, 400) == "invalid_key"
    assert await rows(dashboard.url, "SELECT id FROM dkim_key_lookup WHERE source = 'manual'") == []

    # 16 bytes as a data: URL are fine, and the same key again is more evidence for it
    body = good | {
        "file_base64": "data:image/png;base64," + base64.b64encode(b"\x89PNG" * 4).decode()
    }
    response = await client.post(path, json=body)
    assert response.status_code == 201, response.text
    [key] = response.json()["keys"]
    assert key["id"] == retired.key_id
    assert key["origin"] == "documented"  # stronger than reconstructed
    assert [item["origin"] for item in key["evidence"]] == ["documented", "reconstructed"]
    lookup_id = key["evidence"][0]["lookup_id"]
    raw = await client.get(f"/api/dkim/lookups/{lookup_id}/raw")
    assert (raw.content, raw.headers["content-type"]) == (b"\x89PNG" * 4, "image/png")
    assert 'filename="beleg"' in raw.headers["content-disposition"]
    await _reaped(dashboard)


async def test_raw_answers(dashboard: Dashboard, retired: Retired) -> None:
    client = dashboard.client
    response = await client.get(f"/api/dkim/lookups/{retired.lookup_id}/raw")
    assert response.status_code == 200
    assert response.content == retired.answer
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-mailrobbe-sha256"] == hashlib.sha256(retired.answer).hexdigest()
    assert response.headers["content-disposition"] == (
        f'attachment; filename="lookup-{retired.lookup_id}-reconstruction.json"'
    )
    assert response.headers["x-content-type-options"] == "nosniff"

    engine = create_async_engine(dashboard.url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            empty = await save_lookup(
                connection,
                KeyLookupSource.ZKEMAIL,
                f"{LOCAL_ARCHIVE}api/key?domain={retired.domain}",
                LookupOutcome.NOT_FOUND,
                domain=retired.domain,
                http_status=404,
            )
    finally:
        await engine.dispose()
    for lookup_id in (empty, retired.lookup_id + 1000, 2**63 - 1):
        response = await client.get(f"/api/dkim/lookups/{lookup_id}/raw")
        assert (response.status_code, response.json()["detail"]["code"]) == (404, "not_found")
    assert (await client.get("/api/dkim/lookups/x/raw")).status_code == 422
    # the domain's lookup without a name shows on the pages of its names
    page = await get(client, f"/api/dkim/selectors/{retired.name}")
    assert [lookup["id"] for lookup in page["lookups"]] == [empty, retired.lookup_id]


# The key archive's preview --------------------------------------------------------------------


async def test_the_archive_preview(
    settings: Settings, retired: Retired, generated_archive: GeneratedArchive
) -> None:
    expected = await _expected(settings.database_url)
    concerned: dict[str, tuple[set[str], set[int]]] = defaultdict(lambda: (set(), set()))
    for row in expected.signatures:
        if _open(row) or row.key_id is not None:
            concerned[row.domain][0].add(row.selector)
            concerned[row.domain][1].add(row.mail_id)
    assert all(map(is_reserved, concerned))  # generated domains only
    asked_at = datetime(2026, 3, 1, 12, tzinfo=UTC)
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            for outcome, at in (
                (LookupOutcome.ERROR, datetime(2025, 1, 1, tzinfo=UTC)),
                (LookupOutcome.NOT_FOUND, asked_at),
            ):
                await save_lookup(
                    connection,
                    KeyLookupSource.ZKEMAIL,
                    f"{LOCAL_ARCHIVE}api/key?domain={retired.domain}",
                    outcome,
                    domain=retired.domain,
                    asked_at=at,
                )
    finally:
        await engine.dispose()
    order = sorted(concerned, key=lambda domain: (-len(concerned[domain][1]), domain.encode()))

    for url, shown in (
        ("https://archive.zk.email/", "https://archive.zk.email"),
        ("off", None),
        (LOCAL_ARCHIVE, LOCAL_ARCHIVE.rstrip("/")),
    ):
        changed = settings.model_copy(update={"dkim_key_archive_url": url})
        async for client in _client(changed):
            preview = await get(client, "/api/dkim/archive/preview")
        assert preview["url"] == shown
        if url == LOCAL_ARCHIVE:  # an archive on this machine is asked for every domain
            assert preview["skipped"] == []
            assert [item["domain"] for item in preview["domains"]] == order
            for item in preview["domains"]:
                selectors, mails = concerned[item["domain"]]
                assert (item["names"], item["mails"]) == (len(selectors), len(mails))
                last = asked_at if item["domain"] == retired.domain else None
                assert (
                    datetime.fromisoformat(item["last_asked_at"]) if item["last_asked_at"] else None
                ) == last
        else:
            assert preview["domains"] == []
            assert preview["skipped"] == sorted(concerned, key=str.encode)


# Runs -----------------------------------------------------------------------------------------


async def test_a_key_run_from_start_to_stop(
    dashboard: Dashboard, retired: Retired, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    client = dashboard.client
    run = {"task": "reconstruct", "names": [retired.name.upper(), retired.name], "workers": 2}
    job = await post(client, "/api/dkim/keys/run", run, 202)
    assert (job["kind"], job["origin"], job["status"], job["alive"]) == (
        "dkim_keys",
        "ui",
        "running",
        True,
    )
    assert job["options"] == {
        "task": "reconstruct",
        "names": [retired.name],
        "domains": [],
        "workers": 2,
        "archive_url": None,
    }
    assert job["progress"]["names"] == 0 and job["phase"] is None
    assert await error_code(client, "/api/dkim/keys/run", {"task": "check"}, 409) == "job_running"
    stopped = await post(client, "/api/dkim/keys/run/stop", {})
    assert (stopped["id"], stopped["stop_requested"]) == (job["id"], True)
    await _reaped(dashboard)
    [row] = await rows(dashboard.url, "SELECT status::text, message FROM job")
    assert (row.status, row.message) == ("stopped", "stop requested")
    assert await error_code(client, "/api/dkim/keys/run/stop", {}, 409) == "no_job"

    fake(monkeypatch, "done")
    run = {"task": "fetch", "domains": [f" {retired.domain.upper()}. ", retired.domain]}
    job = await post(client, "/api/dkim/keys/run", run, 202)
    assert (job["options"]["task"], job["options"]["domains"]) == ("fetch", [retired.domain])
    await _reaped(dashboard)


async def test_key_runs_that_are_refused(
    settings: Settings, dashboard: Dashboard, retired: Retired, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "done")
    client = dashboard.client
    path = "/api/dkim/keys/run"
    response = await client.post(path, content=b'{"task": "reconstruct"}')
    assert response.status_code == 415
    await post(client, path, {"task": "dance"}, 422)
    await post(client, path, {"task": "reconstruct", "workers": 0}, 422)
    refused = [
        ({"task": "fetch", "names": [retired.name]}, "invalid_option"),
        ({"task": "search", "names": [retired.name]}, "invalid_option"),
        ({"task": "reconstruct", "domains": [retired.domain]}, "invalid_option"),
        ({"task": "fetch", "domains": ["not a domain"]}, "invalid_option"),
        ({"task": "fetch", "domains": ["localhost"]}, "invalid_option"),
        ({"task": "check", "names": ["nothing"]}, "invalid_key"),
    ]
    for body, code in refused:
        assert await error_code(client, path, body, 400) == code, body
    response = await client.post("/api/dkim/keys/run/stop", content=b"{}")
    assert response.status_code == 415
    async with serve(settings.model_copy(update={"dkim_key_archive_url": "off"})) as off:
        assert await error_code(off.client, path, {"task": "fetch"}, 409) == "archive_off"
        await post(off.client, path, {"task": "search"}, 202)
        await _reaped(off)
    assert [row.kind for row in await rows(dashboard.url, "SELECT kind::text FROM job")] == [
        "dkim_keys"
    ]


# The mail detail and the export -----------------------------------------------------------------


async def test_the_detail_of_a_mail_with_a_reconstructed_key(
    dashboard: Dashboard, retired: Retired
) -> None:
    row = retired.verified[-1]
    detail = await get(dashboard.client, f"/api/mails/{row.mail_id}")
    assert detail["dkim"]["status"] == "consistent"
    signature = detail["dkim"]["signatures"][row.signature_index]
    assert (signature["status"], signature["reason"], signature["key_origin"]) == (
        "consistent",
        None,
        "reconstructed",
    )
    page = await get(dashboard.client, f"/api/dkim/selectors/{retired.name}")
    assert signature["key"] == page["keys"][0]
    assert [used["mail_id"] for used in signature["key"]["evidence"][0]["signatures"]] == [
        used.mail_id for used in retired.used
    ]
    for other in detail["dkim"]["signatures"]:
        if other is not signature:
            assert other["key"] is None


async def test_the_export_of_a_mail_with_a_reconstructed_key(
    dashboard: Dashboard, retired: Retired, tmp_path: Path
) -> None:
    client = dashboard.client
    third = next(row for row in retired.verified if not row.duplicate and row not in retired.used)
    first = retired.used[0]
    response = await client.post(
        "/api/exports", json={"ids": [third.mail_id, first.mail_id]}, headers=EDITOR
    )
    assert response.status_code == 201, response.text
    info = response.json()
    download = await client.get(info["download_url"])
    assert download.status_code == 200
    archive = Zip(download.content, info["id"])

    folder = f"schluessel/{retired.name}/{retired.key_sha256}"
    answer = f"{folder}/beleg-{retired.evidence_id}-antwort.json"
    files = [
        f"{folder}/record.txt",
        answer,
        f"{folder}/beleg-{retired.evidence_id}.json",
        f"{folder}/signaturen.json",
        f"{folder}/{CHECK_SCRIPT}",
    ]
    assert [path for path in archive.paths if path.startswith("schluessel/")] == files
    assert set(files) < set(archive.check_sums())
    assert archive.read(f"{folder}/record.txt") == retired.record.encode() + b"\n"
    assert archive.read(answer) == retired.answer
    evidence = json.loads(archive.read(f"{folder}/beleg-{retired.evidence_id}.json"))
    assert {name: evidence[name] for name in ("evidence_id", "origin", "source", "query")} == {
        "evidence_id": retired.evidence_id,
        "origin": "reconstructed",
        "source": "reconstruction",
        "query": retired.name,
    }
    assert evidence["answer_file"] == answer.rpartition("/")[2]
    assert evidence["answer_sha256"] == hashlib.sha256(retired.answer).hexdigest()
    assert evidence["details"] == json.loads(retired.answer)

    listed = json.loads(archive.read(f"{folder}/signaturen.json"))
    assert [
        (s["mail_sha256"], s["signature_index"], s["reconstruction"], s["exported"])
        for s in listed["signatures"]
    ] == [
        (first.raw_sha256, first.signature_index, True, True),
        (retired.used[1].raw_sha256, retired.used[1].signature_index, True, False),
        (third.raw_sha256, third.signature_index, False, True),
    ]
    assert listed["missing"] == []

    manifest = archive.manifest()
    entry = next(mail for mail in manifest["mails"] if mail["mail_id"] == third.mail_id)
    signature = next(s for s in entry["dkim"]["signatures"] if s["index"] == third.signature_index)
    assert (signature["key_origin"], signature["key_sha256"], signature["evidence"]) == (
        "reconstructed",
        retired.key_sha256,
        [retired.evidence_id],
    )
    table = archive.csv()[8:]
    column = table[0].index("Mail-ID")
    csv_row = next(row for row in table[1:] if row[column] == str(third.mail_id))
    assert any("Herkunft des Schlüssels: rekonstruiert" in cell for cell in csv_row)
    pdf = archive.pdf_text(entry["files"]["pdf"]["path"])
    assert "Herkunft des Schlüssels: rekonstruiert" in pdf
    assert CONSISTENT_TEXT in pdf
    readme = archive.read("LIESMICH.txt").decode()
    assert "SCHLÜSSEL AUS ANDEREN QUELLEN" in readme and "(1 Ordner;" in readme

    # The check script on its own, with nothing but Python
    target = tmp_path / "key"
    with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:
        for path in files:
            (target / path).parent.mkdir(parents=True, exist_ok=True)
            (target / path).write_bytes(bundle.read(f"{archive.folder}/{path}"))
    script = target / folder / CHECK_SCRIPT
    checked = subprocess.run(
        [sys.executable, "-I", str(script)], capture_output=True, text=True, check=False
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "Ergebnis: alle 3 Signaturen passen zum Schlüssel in record.txt." in checked.stdout
    for value in ("m", "s"):
        changed = json.loads(json.dumps(listed))
        number = changed["signatures"][1][value]
        changed["signatures"][1][value] = number[:-2] + ("00" if number[-2:] != "00" else "01")
        (target / folder / "signaturen.json").write_text(json.dumps(changed), encoding="utf-8")
        checked = subprocess.run(
            [sys.executable, "-I", str(script)], capture_output=True, text=True, check=False
        )
        assert checked.returncode == 1, value
        assert "2. Mail" in checked.stdout and "STIMMT NICHT" in checked.stdout
        assert "Ergebnis: 1 von 3 Signaturen passen NICHT zum Schlüssel." in checked.stdout

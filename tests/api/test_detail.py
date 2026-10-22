"""The single-mail API against the imported generated archive (tests/api/conftest.py).

Expectations come from the generator manifest where it knows them (participants, attachments,
DKIM, duplicates, replies), otherwise from direct SQL (ids, threads, names, the order within a
role, which follows the database's collation). Body views are compared with the body text the
importer indexed. client stays read only: writes go through mutable_client, broken sources
through copies of MBOX files in tmp_path.
"""

import asyncio
import email
import email.policy
import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api import body
from mailrobbe.api.detail import HTML_HEADERS
from mailrobbe.api.schemas import (
    RAW_LIMIT,
    THREAD_LIMIT,
    MailDetail,
    MailDkim,
    MailHeaders,
    MailRaw,
    MailResearch,
    MailText,
    Mark,
    Participant,
)
from mailrobbe.config import Settings
from mailrobbe.dkim.override import key_name
from mailrobbe.enums import DocumentKind
from mailrobbe.importer.model import BODY_TEXT_LIMIT
from mailrobbe.mbox import read_message
from mailrobbe.preview.kinds import preview_kind
from tests.api.conftest import _client
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

EMPTY_MARK = Mark(
    flagged=False, flagged_by=None, flagged_at=None, review=None, review_by=None, review_at=None
)
EMPTY_RESEARCH = MailResearch(mark=EMPTY_MARK, tags=[], collections=[], notes=[])

Record = dict[str, Any]  # one manifest entry
Row = dict[str, Any]  # one mail row, with its file's path


@dataclass(frozen=True, slots=True)
class Archive:
    """The imported archive as direct SQL sees it, next to the manifest (same order)."""

    mbox_dir: Path
    manifest: list[Record]
    mails: list[Row]
    attachments: dict[int, list[Row]]  # mail id -> attachment rows by id, with their document
    participants: dict[int, list[tuple[str, str, str | None]]]  # mail id -> (role, email, name)
    dkim: dict[int, list[Row]]  # mail id -> dkim_result rows by signature_index
    dns: dict[str, Row]  # dns_cache rows by name
    override: dict[str, str]  # the generator's DNS override records
    roots: dict[str, int]  # address -> its root person (D28)
    figures: dict[int, tuple[int, int]]  # person_stats: person -> (mails, contacts)
    edges: dict[tuple[int, int], int]  # (person_a, person_b) -> mails_total

    @property
    def entries(self) -> list[tuple[Record, Row]]:
        return list(zip(self.manifest, self.mails, strict=True))

    def message(self, mail: Row) -> bytes:
        return read_message(self.mbox_dir / mail["path"], mail["byte_offset"], mail["byte_length"])


@pytest.fixture(scope="module")
def archive(imported_database_url: str, generated_archive: GeneratedArchive) -> Archive:
    return asyncio.run(_load(imported_database_url, generated_archive))


async def _load(url: str, generated: GeneratedArchive) -> Archive:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:

            async def rows(sql: str) -> list[Row]:
                return [row._asdict() for row in await connection.execute(text(sql))]

            mails = {
                (row["path"], row["byte_offset"]): row
                for row in await rows(
                    "SELECT m.*, f.path FROM mail m JOIN mbox_file f ON f.id = m.mbox_file_id"
                )
            }
            attachments: dict[int, list[Row]] = defaultdict(list)
            for row in await rows(
                "SELECT a.*, d.kind::text AS kind, d.text_status::text AS text_status, d.pages, "
                "d.mails AS document_mails, d.metadata_status::text AS metadata_status, "
                "d.metadata_author, d.metadata_modified_by, d.metadata_program, "
                "d.metadata_device, d.metadata_created, d.metadata_gps, d.metadata_latitude, "
                "d.metadata_longitude, d.protection::text AS protection, "
                "d.members_status::text AS members_status FROM attachment a "
                "LEFT JOIN document d ON d.id = a.document_id ORDER BY a.id"
            ):
                attachments[row["mail_id"]].append(row)
            participants: dict[int, list[tuple[str, str, str | None]]] = defaultdict(list)
            for row in await rows(
                "SELECT p.mail_id, p.role::text AS role, e.canonical_email AS email, "
                "COALESCE(p.display_name, e.display_name) AS name "
                "FROM participation p JOIN person e ON e.id = p.person_id "
                "ORDER BY p.mail_id, p.role, name, email"
            ):
                participants[row["mail_id"]].append((row["role"], row["email"], row["name"]))
            dkim: dict[int, list[Row]] = defaultdict(list)
            for row in await rows("SELECT * FROM dkim_result ORDER BY mail_id, signature_index"):
                dkim[row["mail_id"]].append(row)
            dns = {row["name"]: row for row in await rows("SELECT * FROM dns_cache")}
            roots = {
                row["canonical_email"]: row["root"]
                for row in await rows(
                    "SELECT canonical_email, COALESCE(merged_into, id) AS root FROM person"
                )
            }
            figures = {
                row["person_id"]: (row["mails"], row["contacts"])
                for row in await rows("SELECT person_id, mails, contacts FROM person_stats")
            }
            edges = {
                (row["person_a"], row["person_b"]): row["mails_total"]
                for row in await rows("SELECT person_a, person_b, mails_total FROM edge")
            }
    finally:
        await engine.dispose()
    override = json.loads(generated.dns_override.read_text(encoding="utf-8"))["records"]
    return Archive(
        mbox_dir=generated.mbox_dir,
        manifest=generated.manifest,
        mails=[mails[record["file"], record["offset"]] for record in generated.manifest],
        attachments=attachments,
        participants=participants,
        dkim=dkim,
        dns=dns,
        override=override,
        roots=roots,
        figures=figures,
        edges=edges,
    )


async def _detail(client: httpx.AsyncClient, mail_id: int) -> MailDetail:
    response = await client.get(f"/api/mails/{mail_id}")
    assert response.status_code == 200, response.text
    return MailDetail.model_validate(response.json())


def _signatures(dkim: MailDkim) -> Counter[tuple[str | None, str | None, str]]:
    return Counter((s.domain, s.selector, s.status.value) for s in dkim.signatures)


def _expected_signatures(record: Record) -> Counter[tuple[str | None, str | None, str]]:
    return Counter(
        (s["domain"], s["selector"], s["expected"]) for s in record["dkim"]["signatures"]
    )


def _expected_figures(
    archive: Archive, participants: list[Participant]
) -> list[tuple[int | None, int | None, int | None]]:
    """mails, contacts and mails_with_sender of each participant, from its root's rows."""
    roots = [archive.roots[p.email] for p in participants]
    sender = next((archive.roots[p.email] for p in participants if p.role == "from"), None)
    expected = []
    for root in roots:
        mails, contacts = archive.figures.get(root, (None, None))
        pair = (min(root, sender), max(root, sender)) if sender is not None else None
        together = None if pair is None or root == sender else archive.edges.get(pair)
        expected.append((mails, contacts, together))
    return expected


def _shown_attachment(row: Row, rows: list[Row]) -> dict[str, Any]:
    """An attachment as the detail shows it, a container's members under it (D231)."""
    locked = row["protection"] == "locked"
    return {
        "id": row["id"],
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "size": row["size_bytes"],
        "sha256": row["sha256"],
        "document_id": row["document_id"],
        "kind": row["kind"],
        "text_status": row["text_status"],
        "pages": row["pages"],
        "document_mails": row["document_mails"],
        "preview": None
        if locked
        else preview_kind(
            None if row["kind"] is None else DocumentKind(row["kind"]),
            row["filename"],
            row["mime_type"],
            row["size_bytes"],
            hashed=row["sha256"] is not None,
            max_size=Settings().preview_max_size,
        ),
        "metadata": _metadata_summary(row),
        "protection": row["protection"],
        "path": row["path"],
        "members_status": row["members_status"],
        "members": [
            _shown_attachment(member, rows)
            for member in sorted(rows, key=lambda each: each["position"])
            if member["container_id"] == row["id"]
        ],
    }


def _metadata_summary(row: Row) -> dict[str, Any] | None:
    """AttachmentInfo.metadata as the document row has it (D167): None unless its metadata was
    found and the summary names something."""
    summary = {
        "author": row["metadata_author"],
        "modified_by": row["metadata_modified_by"],
        "software": row["metadata_program"],
        "device": row["metadata_device"],
        "created": row["metadata_created"],
        "gps": bool(row["metadata_gps"]),
        "latitude": row["metadata_latitude"],  # D249
        "longitude": row["metadata_longitude"],
    }
    return summary if row["metadata_status"] == "found" and any(summary.values()) else None


def _together(manifest: list[Record]) -> Counter[frozenset[str]]:
    """Mails between two addresses, either one the sender, as edge.mails_total counts them."""
    together: Counter[frozenset[str]] = Counter()
    for record in manifest:
        if record["duplicate_of"] is None:
            sender = record["sender"].lower()
            recipients = {a.lower() for role in ("to", "cc", "bcc") for a in record[role]}
            together.update(frozenset((sender, recipient)) for recipient in recipients - {sender})
    return together


def _sort_key(mail: Row) -> tuple[bool, datetime, int]:
    """MAIL_SORT_KEY then id: mails without a date first."""
    date = mail["date_utc"]
    return (date is not None, date or datetime.min.replace(tzinfo=UTC), mail["id"])


# The detail ----------------------------------------------------------------------------------


async def test_the_detail_of_every_mail(client: httpx.AsyncClient, archive: Archive) -> None:
    ids = [mail["id"] for mail in archive.mails]
    by_message_id: dict[str, list[Record]] = defaultdict(list)
    for record in archive.manifest:
        if record["message_id"]:
            by_message_id[record["message_id"]].append(record)
    threads: dict[int, list[Row]] = defaultdict(list)
    for mail in sorted(archive.mails, key=_sort_key):
        if mail["thread_id"] is not None:
            threads[mail["thread_id"]].append(mail)
    together = _together(archive.manifest)
    assert together

    for record, mail in archive.entries:
        index, mail_id = record["index"], mail["id"]
        detail = await _detail(client, mail_id)
        assert (detail.source.path, detail.source.byte_offset, detail.source.byte_length) == (
            record["file"],
            record["offset"],
            record["length"],
        )
        assert detail.source.mbox_file_id == mail["mbox_file_id"]
        assert detail.raw_sha256 == record["sha256"]
        assert (detail.subject, detail.date, detail.message_id, detail.in_reply_to) == (
            mail["subject"],
            mail["date_utc"],
            record["message_id"],
            record["in_reply_to"],
        )
        assert detail.reference_ids == (mail["reference_ids"] or [])

        expected = {("from", record["sender"])}
        expected |= {(role, address) for role in ("to", "cc", "bcc") for address in record[role]}
        assert {(p.role.value, p.email) for p in detail.participants} == expected, index
        shown = [(p.role.value, p.email, p.name) for p in detail.participants]
        assert shown == archive.participants[mail_id], index
        # The figures of each address's root (D26, D28); person_stats is filled since milestone 5,
        # so every participant has its mails. The mails with the sender match the manifest (D36).
        shown_figures = [(p.mails, p.contacts, p.mails_with_sender) for p in detail.participants]
        assert shown_figures == _expected_figures(archive, detail.participants), index
        assert all(p.mails is not None for p in detail.participants), index
        sender = record["sender"].lower()
        assert {(p.email, p.mails_with_sender) for p in detail.participants} == {
            (p.email, None if p.email == sender else together.get(frozenset((sender, p.email))))
            for p in detail.participants
        }, index

        own = archive.attachments[mail_id]
        assert [a.model_dump() for a in detail.attachments] == [
            _shown_attachment(row, own) for row in own if row["container_id"] is None
        ]
        # finalize gave every attachment its document, the attachments phase every text status
        assert all(a.document_id and a.document_mails for a in detail.attachments), index
        assert all(a.text_status != "pending" for a in detail.attachments), index
        assert len(detail.attachments) == record["attachments"], index
        assert detail.has_attachments == (record["attachments"] > 0)

        assert detail.dkim.status == record["dkim"]["expected"], index
        assert _signatures(detail.dkim) == _expected_signatures(record), index
        assert [s.index for s in detail.dkim.signatures] == list(
            range(len(record["dkim"]["signatures"]))
        )
        for signature in detail.dkim.signatures:
            assert signature.domain and signature.selector
            key = archive.dns.get(key_name(signature.selector, signature.domain), {})
            assert (signature.dns_record, signature.dns_fetched_at, signature.dns_ttl) == (
                key.get("record"),
                key.get("fetched_at"),
                key.get("ttl"),
            )

        original = record["duplicate_of"]
        assert detail.duplicate_of == (None if original is None else ids[original]), index
        copies = [ids[r["index"]] for r in archive.manifest if r["duplicate_of"] == index]
        assert detail.duplicates == sorted(copies), index

        replied = [r for r in by_message_id.get(record["in_reply_to"] or "", []) if r is not record]
        best = min(
            replied, key=lambda r: (r["duplicate_of"] is not None, ids[r["index"]]), default=None
        )
        assert detail.in_reply_to_id == (None if best is None else ids[best["index"]]), index

        members = threads.get(mail["thread_id"], [])
        assert len(members) < THREAD_LIMIT  # the window is tested on its own below
        assert [m.id for m in detail.thread] == [m["id"] for m in members], index
        assert detail.thread_size == len(members)
        assert detail.research == EMPTY_RESEARCH


async def test_dns_records_of_pass_fail_and_no_key_signatures(
    client: httpx.AsyncClient, archive: Archive
) -> None:
    for status, reason in (
        ("pass", None),
        ("fail", "body_modified"),
        ("no_key", "selector_retired"),
    ):
        mail = next(
            m
            for r, m in archive.entries
            if [(s["expected"], s["reason"]) for s in r["dkim"]["signatures"]] == [(status, reason)]
        )
        (signature,) = (await _detail(client, mail["id"])).dkim.signatures
        assert signature.status == status
        assert signature.selector and signature.domain
        published = archive.override.get(key_name(signature.selector, signature.domain))
        assert signature.dns_record == published
        assert (published is None) == (status == "no_key")
        assert signature.dns_ttl and signature.dns_fetched_at
        if status == "pass":
            assert signature.reason is None and signature.body_hash_ok and signature.key_bits
        elif status == "fail":
            assert signature.reason == "body_hash_mismatch" and signature.body_hash_ok is False
        else:
            assert signature.reason == "key_not_found" and signature.key_bits is None


async def test_threads_and_single_mails(client: httpx.AsyncClient, archive: Archive) -> None:
    threads = Counter(mail["thread_id"] for mail in archive.mails if mail["thread_id"])
    largest = max(threads, key=threads.__getitem__)
    members = sorted((m for m in archive.mails if m["thread_id"] == largest), key=_sort_key)
    detail = await _detail(client, members[-1]["id"])
    assert [t.id for t in detail.thread] == [m["id"] for m in members]
    assert [t.subject for t in detail.thread] == [m["subject"] for m in members]
    assert detail.thread_size == len(members) >= 3
    senders = {(t.id, t.sender.email if t.sender else None) for t in detail.thread}
    assert senders == {(m["id"], archive.participants[m["id"]][0][1]) for m in members}

    single = next(m for m in archive.mails if m["thread_id"] is None)
    detail = await _detail(client, single["id"])
    assert (detail.thread_id, detail.thread, detail.thread_size) == (None, [], 0)


async def test_a_long_thread_shows_a_window_around_the_mail(
    mutable_client: httpx.AsyncClient, mutable_database_url: str, archive: Archive
) -> None:
    # Pull mails into one thread on this test's own copy; order by date then id.
    members = sorted(archive.mails, key=_sort_key)[: THREAD_LIMIT + 150]
    thread_id = members[0]["id"]
    await _execute(
        mutable_database_url,
        "UPDATE mail SET thread_id = :thread_id WHERE id = ANY(:ids)",
        thread_id=thread_id,
        ids=[m["id"] for m in members],
    )
    ids = [m["id"] for m in members]
    first = await _detail(mutable_client, ids[0])
    assert [t.id for t in first.thread] == ids[:THREAD_LIMIT]
    assert first.thread_size == len(ids)
    middle = await _detail(mutable_client, ids[150])
    assert [t.id for t in middle.thread] == ids[150 - THREAD_LIMIT // 2 :][:THREAD_LIMIT]
    last = await _detail(mutable_client, ids[-1])
    assert [t.id for t in last.thread] == ids[-THREAD_LIMIT:]


async def test_an_attachment_above_the_hash_limit_has_no_hash(
    mutable_client: httpx.AsyncClient, mutable_database_url: str, archive: Archive
) -> None:
    mail = next(m for r, m in archive.entries if "large_attachment" in r["faults"])
    large = archive.attachments[mail["id"]][-1]
    assert large["size_bytes"] == 2 * 1024**2  # the fixture's large_attachment_size
    # The fixture imports with the default limit; what a lower one stores is a NULL hash.
    await _execute(
        mutable_database_url, "UPDATE attachment SET sha256 = NULL WHERE id = :id", id=large["id"]
    )
    attachments = (await _detail(mutable_client, mail["id"])).attachments
    assert [(a.id, a.size, a.sha256) for a in attachments][-1] == (
        large["id"],
        large["size_bytes"],
        None,
    )
    assert all(a.sha256 for a in attachments[:-1])


async def test_participants_show_the_figures_of_their_roots(
    mutable_client: httpx.AsyncClient, mutable_database_url: str, archive: Archive
) -> None:
    # A mail from s to at least two other addresses b and c. Two persons outside the mail become
    # roots: r of s and c, a of b. The aliases' own person_stats rows are stale ones.
    for mail in archive.mails:
        people = archive.participants[mail["id"]]
        addresses = list(dict.fromkeys(email for _, email, _ in people))  # the sender first
        if people[0][0] == "from" and len(addresses) >= 4:
            break
    mail_id, (sender, b, c) = mail["id"], addresses[:3]
    r, a = [root for email, root in archive.roots.items() if email not in addresses][:2]
    aliases = {archive.roots[sender]: r, archive.roots[b]: a, archive.roots[c]: r}
    url = mutable_database_url
    for alias, root in aliases.items():
        await _execute(url, "UPDATE person SET merged_into = :r WHERE id = :a", r=root, a=alias)
    await _execute(url, "DELETE FROM person_stats")
    await _execute(url, "DELETE FROM edge")
    await _execute(
        url,
        "INSERT INTO person_stats (person_id, sent, received, contacts)"
        " SELECT unnest(CAST(:ids AS bigint[])), 99, 99, 99",
        ids=list(aliases),
    )
    await _execute(
        url,
        "INSERT INTO person_stats (person_id, sent, received, contacts)"
        " VALUES (:a, 7, 5, 3), (:r, 20, 2, 9)",
        a=a,
        r=r,
    )
    await _execute(
        url,
        "INSERT INTO edge (person_a, person_b, mails_a_to_b, mails_b_to_a, mails_cc)"
        " VALUES (:first, :second, 4, 1, 1)",
        first=min(a, r),
        second=max(a, r),
    )
    expected = {sender: (22, 9, None), b: (12, 3, 6), c: (22, 9, None)}
    participants = (await _detail(mutable_client, mail_id)).participants
    assert {p.email for p in participants} >= set(expected)
    for p in participants:
        assert p.person_id == archive.roots[p.email]  # the address's own person
        shown = (p.mails, p.contacts, p.mails_with_sender)
        assert shown == expected.get(p.email, (None, None, None)), p.email


async def test_unknown_and_invalid_ids(client: httpx.AsyncClient) -> None:
    for path in (
        "/api/mails/0",
        "/api/mails/987654321",
        "/api/mails/987654321/body",
        "/api/mails/987654321/eml",
    ):
        response = await client.get(path)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"
    response = await client.post("/api/mails/987654321/dkim/recheck")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "not_found")
    for path in ("/api/mails/abc", f"/api/mails/{2**63}", "/api/mails/1/body?format=pdf"):
        assert (await client.get(path)).status_code == 422


# Bodies ----------------------------------------------------------------------------------------


def test_the_text_tab_shows_what_the_index_holds(archive: Archive) -> None:
    sources: Counter[str] = Counter()
    for record, mail in archive.entries:
        shown = body.mail_text(archive.message(mail))
        indexed = shown.text[:BODY_TEXT_LIMIT]
        assert (indexed if indexed.strip() else None) == mail["body_text"], record["index"]
        assert "\r" not in shown.text and not shown.truncated
        sources[shown.source] += 1
    assert sources["text/plain"] and sources["text/html"]


async def test_text_and_html_of_a_multipart_mail(
    client: httpx.AsyncClient, archive: Archive
) -> None:
    mail = next(m for m in archive.mails if _content_type(archive, m) == "multipart/alternative")
    response = await client.get(f"/api/mails/{mail['id']}/body")
    shown = MailText.model_validate(response.json())
    assert (shown.source, shown.has_html, shown.truncated) == ("text/plain", True, False)
    assert shown.text.startswith(mail["body_text"])
    html = await client.get(f"/api/mails/{mail['id']}/body", params={"format": "html"})
    assert html.status_code == 200 and "<body" in html.text


async def test_an_html_only_mail(client: httpx.AsyncClient, archive: Archive) -> None:
    mail = next(m for m in archive.mails if _content_type(archive, m) == "text/html")
    shown = MailText.model_validate((await client.get(f"/api/mails/{mail['id']}/body")).json())
    assert (shown.source, shown.has_html) == ("text/html", True)
    assert shown.text == mail["body_text"] and "<" not in shown.text
    html = await client.get(f"/api/mails/{mail['id']}/body?format=html")
    assert html.status_code == 200
    assert html.headers["content-type"] == "text/html; charset=utf-8"
    assert {name: html.headers[name] for name in HTML_HEADERS} == HTML_HEADERS
    assert "sandbox" in html.headers["content-security-policy"]
    assert html.text.lstrip().startswith("<html")


async def test_a_plain_mail_has_no_html(client: httpx.AsyncClient, archive: Archive) -> None:
    mail = next(m for m in archive.mails if _content_type(archive, m) == "text/plain")
    shown = MailText.model_validate((await client.get(f"/api/mails/{mail['id']}/body")).json())
    assert (shown.source, shown.has_html) == ("text/plain", False)
    response = await client.get(f"/api/mails/{mail['id']}/body?format=html")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "no_html")


async def test_bodies_of_faulty_mails(client: httpx.AsyncClient, archive: Archive) -> None:
    faults = ["wrong_charset", "unknown_charset", "invalid_base64", "message_rfc822"]
    for fault in faults:
        mail = next(m for r, m in archive.entries if fault in r["faults"].values())
        shown = MailText.model_validate((await client.get(f"/api/mails/{mail['id']}/body")).json())
        assert shown.text.startswith(mail["body_text"]), fault
        assert "\N{REPLACEMENT CHARACTER}" not in shown.text, fault


async def test_headers_view(client: httpx.AsyncClient, archive: Archive) -> None:
    mail = next(m for r, m in archive.entries if len(r["dkim"]["signatures"]) == 2)
    message = archive.message(mail)
    response = await client.get(f"/api/mails/{mail['id']}/body", params={"format": "headers"})
    headers = MailHeaders.model_validate(response.json()).headers
    head = message.split(b"\n\n", 1)[0] + b"\n"
    names = [n.decode() for n in re.findall(rb"^([!-9;-~]+)[ \t]*:", head, re.MULTILINE)]
    assert [h.name for h in headers] == names
    assert all("\n" not in h.value for h in headers)
    # The n-th DKIM-Signature field is signature_index n.
    fields = [h.value for h in headers if h.name.lower() == "dkim-signature"]
    signatures = (await _detail(client, mail["id"])).dkim.signatures
    assert [_tag(f, "d") for f in fields] == [s.domain for s in signatures]
    assert [_tag(f, "s") for f in fields] == [s.selector for s in signatures]
    subject = next(h.value for h in headers if h.name.lower() == "subject")
    assert " ".join(subject.split()) == mail["subject"]


async def test_headers_with_encoded_words_and_raw_8bit_bytes(
    client: httpx.AsyncClient, archive: Archive
) -> None:
    mail = next(
        m for r, m in archive.entries if not r["faults"] and b"Subject: =?" in archive.message(m)
    )
    headers = await _headers(client, mail["id"])
    assert " ".join(headers["Subject"].split()) == mail["subject"]
    assert "=?" not in headers["Subject"]

    mail = next(
        m for r, m in archive.entries if r["faults"].get("broken_encoding") == "raw_8bit_header"
    )
    head = archive.message(mail).split(b"\n\n", 1)[0]
    name, value = next(
        line.split(b": ", 1) for line in head.split(b"\n") if re.search(rb"[\x80-\xff]", line)
    )
    headers = await _headers(client, mail["id"])
    assert headers[name.decode()] == value.decode("cp1252")


async def test_raw_view_of_a_large_and_a_small_mail(
    client: httpx.AsyncClient, archive: Archive
) -> None:
    mail = next(m for m in archive.mails if m["byte_length"] > RAW_LIMIT + 1024)
    message = archive.message(mail)
    response = await client.get(f"/api/mails/{mail['id']}/body", params={"format": "raw"})
    raw = MailRaw.model_validate(response.json())
    assert (raw.truncated, raw.size) == (True, len(message))
    shown = raw.raw.encode()
    assert len(shown) <= RAW_LIMIT and shown.endswith(b"\n") and message.startswith(shown)

    mail = next(m for m in archive.mails if m["byte_length"] < 10_000)
    message = archive.message(mail)
    response = await client.get(f"/api/mails/{mail['id']}/body", params={"format": "raw"})
    assert MailRaw.model_validate(response.json()) == MailRaw(
        raw=message.decode("utf-8", "replace"), truncated=False, size=len(message)
    )


async def test_eml_download(client: httpx.AsyncClient, archive: Archive) -> None:
    record, mail = next((r, m) for r, m in archive.entries if r["attachments"] > 0)
    response = await client.get(f"/api/mails/{mail['id']}/eml")
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == record["sha256"]
    assert response.headers["content-type"] == "message/rfc822"
    assert (
        response.headers["content-disposition"] == f'attachment; filename="mail-{mail["id"]}.eml"'
    )


# A missing or changed source -----------------------------------------------------------------


@pytest.fixture
async def copy_client(
    imported_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Read-only client on the shared database whose MBOX directory is tmp_path/mbox."""
    settings = Settings(
        database_url=imported_database_url,
        mbox_dir=tmp_path / "mbox",
        dkim_dns_override=generated_archive.dns_override,
        frontend_dir=tmp_path / "no-frontend",
    )
    (tmp_path / "mbox").mkdir()
    async for http in _client(settings):
        yield http


async def test_a_missing_source(copy_client: httpx.AsyncClient, archive: Archive) -> None:
    mail_id = archive.mails[0]["id"]
    for method, path in (
        ("GET", "body"),
        ("GET", "body?format=raw"),
        ("GET", "eml"),
        ("POST", "dkim/recheck"),
    ):
        response = await copy_client.request(method, f"/api/mails/{mail_id}/{path}")
        assert (response.status_code, response.json()["detail"]["code"]) == (409, "source_missing")
    assert (await copy_client.get(f"/api/mails/{mail_id}")).status_code == 200  # database only


async def test_a_changed_source(
    copy_client: httpx.AsyncClient, archive: Archive, tmp_path: Path
) -> None:
    record, mail = archive.entries[1]
    original = (archive.mbox_dir / record["file"]).read_bytes()
    copy = tmp_path / "mbox" / record["file"]
    middle = record["offset"] + record["length"] // 2
    changed = bytearray(original)
    changed[middle] ^= 0x01
    end = record["offset"] + record["length"]
    for data in (bytes(changed), original[: end - 1]):
        copy.write_bytes(data)
        for method, path in (
            ("GET", "body?format=headers"),
            ("GET", "eml"),
            ("POST", "dkim/recheck"),
        ):
            response = await copy_client.request(method, f"/api/mails/{mail['id']}/{path}")
            assert (response.status_code, response.json()["detail"]["code"]) == (
                409,
                "source_changed",
            )
    copy.write_bytes(original)
    assert (await copy_client.get(f"/api/mails/{mail['id']}/eml")).content == archive.message(mail)


# Writes: DKIM recheck and note ---------------------------------------------------------------


async def test_recheck_gives_the_expected_results(
    mutable_client: httpx.AsyncClient, archive: Archive
) -> None:
    for status in ("pass", "fail", "no_key", "temp_error", "unsigned"):
        # a mail of that status, else one with a signature of it (a key that times out beside a
        # valid signature gives the mail pass): every signature status is rechecked
        record, mail = next(
            (r, m)
            for r, m in archive.entries
            if r["dkim"]["expected"] == status
            or any(s["expected"] == status for s in r["dkim"]["signatures"])
        )
        before = archive.dkim[mail["id"]]
        response = await mutable_client.post(f"/api/mails/{mail['id']}/dkim/recheck")
        assert response.status_code == 200, response.text
        dkim = MailDkim.model_validate(response.json())
        assert dkim.status == record["dkim"]["expected"]
        assert _signatures(dkim) == _expected_signatures(record)
        for signature, row in zip(dkim.signatures, before, strict=True):
            assert signature.checked_at > row["checked_at"]
            assert signature.status == row["status"]
        for signature in dkim.signatures:
            # a missing key is asked for again, and the new answer replaces the cached one
            if signature.status == "no_key":
                assert signature.selector and signature.domain
                cached = archive.dns[key_name(signature.selector, signature.domain)]
                assert signature.dns_fetched_at and signature.dns_fetched_at > cached["fetched_at"]
        assert (await _detail(mutable_client, mail["id"])).dkim == dkim


async def test_recheck_with_wrong_dns_settings(
    mutable_database_url: str,
    generated_archive: GeneratedArchive,
    archive: Archive,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(
        database_url=mutable_database_url,
        mbox_dir=generated_archive.mbox_dir,
        dkim_dns_timeout=0,
        frontend_dir=tmp_path / "no-frontend",
    )
    mail = next(m for r, m in archive.entries if r["dkim"]["expected"] == "pass")
    with caplog.at_level(logging.ERROR):
        async for http in _client(settings):
            response = await http.post(f"/api/mails/{mail['id']}/dkim/recheck")
            assert response.status_code == 500
            detail = await _detail(http, mail["id"])
    assert "MAILROBBE_DKIM_DNS_TIMEOUT must be positive" in caplog.text
    assert [s.checked_at for s in detail.dkim.signatures] == [
        row["checked_at"] for row in archive.dkim[mail["id"]]
    ]


# Helpers -------------------------------------------------------------------------------------


def _content_type(archive: Archive, mail: Row) -> str:
    message = email.message_from_bytes(archive.message(mail), policy=email.policy.compat32)
    return message.get_content_type()


def _tag(field: str, name: str) -> str | None:
    match = re.search(rf"(?:^|;)\s*{name}=([^;\s]+)", field)
    return match.group(1) if match else None


async def _headers(client: httpx.AsyncClient, mail_id: int) -> dict[str, str]:
    response = await client.get(f"/api/mails/{mail_id}/body", params={"format": "headers"})
    return {h.name: h.value for h in MailHeaders.model_validate(response.json()).headers}


async def _execute(url: str, sql: str, **params: object) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(sql), params)
    finally:
        await engine.dispose()

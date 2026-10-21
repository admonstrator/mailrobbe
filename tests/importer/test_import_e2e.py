"""The real chain (split, parse, store, finalize) on a copy of the generated archive.

The database must match the generator manifest mail by mail. Where the two may differ, it is
said precisely next to the assertion:

- Subjects: a list host or gateway may tag the subject in transit ("[name] " in front, see
  generator.dkim._tamper); broken_encoding variants that damage the Subject header itself
  (raw_8bit_header, broken_encoded_word) are decoded heuristically.
- Threads: every reply references its thread's root, so a thread stays together through the
  root's Message-ID even when that mail lost it; only the root itself (missing_message_id)
  drops out, and a thread left with one mail is no thread.

DKIM is checked against the generator's DNS override table, so nothing queries real DNS: the
copy holds only the MBOX files, and the settings point at the table explicitly.
"""

import asyncio
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.config import Settings
from mailrobbe.enums import DocumentKind
from mailrobbe.importer import cli
from mailrobbe.importer.cli import run_import
from mailrobbe.importer.model import BODY_TEXT_LIMIT
from mailrobbe.jobs import ImportProgress
from mailrobbe.preview.kinds import preview_kind
from tests.conftest import GeneratedArchive, _temporary_database
from tests.importer.doubles import copy_archive

pytestmark = [pytest.mark.db, pytest.mark.slow]

_TRANSIT_TAG = re.compile(r"\[[^\]]+\] ")
_DAMAGED_SUBJECT = {"raw_8bit_header", "broken_encoded_word"}


@dataclass(frozen=True, slots=True)
class Imported:
    exit_code: int
    files: dict[str, str]  # path -> status
    manifest: list[dict[str, Any]] = field(repr=False)
    mails: dict[tuple[str, int], dict[str, Any]] = field(repr=False)  # (file, offset) -> row
    participants: dict[int, dict[str, set[str]]] = field(repr=False)  # mail id -> role -> emails
    errors: dict[tuple[str, int], set[str]] = field(repr=False)  # (file, offset) -> kinds
    signatures: dict[int, list[str]] = field(repr=False)  # mail id -> dkim_result statuses
    job: dict[str, Any] = field(repr=False)  # the run's job row
    # mail id -> its attachments by position, with their document's kind and text status
    attachments: dict[int, list[dict[str, Any]]] = field(repr=False)

    def mail(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.mails[record["file"], record["offset"]]


@pytest.fixture(scope="module")
def imported(
    database_server_url: str,
    generated_archive: GeneratedArchive,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Imported]:
    mbox_dir = copy_archive(generated_archive.mbox_dir, tmp_path_factory.mktemp("e2e") / "mbox")
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(database_url=url, dkim_dns_override=generated_archive.dns_override)
        exit_code = asyncio.run(run_import(settings, mbox_dir, 2))
        yield asyncio.run(_load(url, exit_code, generated_archive.manifest))


async def _load(url: str, exit_code: int, manifest: list[dict[str, Any]]) -> Imported:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:

        async def rows(sql: str) -> list[Any]:
            return list(await connection.execute(text(sql)))

        mails = {
            (row.path, row.byte_offset): row._asdict()
            for row in await rows(
                "SELECT m.*, f.path, (SELECT count(*) FROM attachment a WHERE a.mail_id = m.id) "
                "AS attachments FROM mail m JOIN mbox_file f ON f.id = m.mbox_file_id"
            )
        }
        participants: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for mail_id, role, email in await rows(
            "SELECT p.mail_id, p.role::text, e.email FROM participation p "
            "JOIN person_email e ON e.person_id = p.person_id"
        ):
            participants[mail_id][role].add(email)
        errors: dict[tuple[str, int], set[str]] = defaultdict(set)
        for path, offset, kind in await rows(
            "SELECT f.path, e.byte_offset, e.kind FROM import_error e "
            "JOIN mbox_file f ON f.id = e.mbox_file_id"
        ):
            errors[path, offset].add(kind)
        signatures: dict[int, list[str]] = defaultdict(list)
        for mail_id, status in await rows("SELECT mail_id, status::text FROM dkim_result"):
            signatures[mail_id].append(status)
        files = {path: status for path, status in await rows("SELECT path, status FROM mbox_file")}
        attachments: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in await rows(
            "SELECT a.*, d.kind::text AS kind, d.text_status::text AS status FROM attachment a "
            "JOIN document d ON d.id = a.document_id ORDER BY a.mail_id, a.position"
        ):
            attachments[row.mail_id].append(row._asdict())
        [job] = [row._asdict() for row in await rows("SELECT * FROM job")]
    await engine.dispose()
    return Imported(
        exit_code, files, manifest, mails, participants, errors, signatures, job, attachments
    )


def test_every_file_is_done(imported: Imported) -> None:
    assert imported.exit_code == 0
    assert set(imported.files.values()) == {"done"}
    assert set(imported.files) == {record["file"] for record in imported.manifest}


def test_the_run_is_recorded_with_its_dkim_checks(imported: Imported) -> None:
    # A run that was not stopped ends with the signals (D135).
    assert (imported.job["status"], imported.job["phase"]) == ("done", "signals")
    progress = ImportProgress.model_validate(imported.job["progress"])
    assert progress.mails_imported == len(imported.manifest)
    steps = {step.key: step for step in progress.steps}
    assert list(steps) == list(cli.STEPS)
    assert {step.status for step in steps.values()} == {"done", "skipped"}  # headers skipped
    assert steps["attachments"].done == steps["attachments"].total
    assert steps["attachments"].done > 0
    assert steps["entities"].done == steps["entities"].total
    assert steps["entities"].done > 0
    assert steps["import"].done == steps["import"].total == progress.bytes_imported
    # Every mail got a verdict (D13: the importer checks inline), so both rates are the same.
    assert progress.dkim_per_second == progress.mails_per_second > 0


def test_every_manifest_mail_exists_once_with_its_framing(imported: Imported) -> None:
    assert len(imported.mails) == len(imported.manifest)
    for record in imported.manifest:
        mail = imported.mail(record)
        assert (mail["byte_length"], mail["raw_sha256"]) == (record["length"], record["sha256"])


def test_headers_match_the_manifest(imported: Imported) -> None:
    for record in imported.manifest:
        mail = imported.mail(record)
        index = record["index"]
        assert mail["message_id"] == record["message_id"], index
        assert mail["date_utc"] == datetime.fromisoformat(record["date"]), index
        assert mail["in_reply_to"] == record["in_reply_to"], index
        subject = mail["subject"] or ""
        planned = record["subject"] or ""
        if record["faults"].get("broken_encoding") in _DAMAGED_SUBJECT:
            assert subject or not planned, index
        else:
            assert _TRANSIT_TAG.sub("", subject, count=1) == planned or subject == planned, index


def test_participants_match_the_manifest(imported: Imported) -> None:
    for record in imported.manifest:
        roles = imported.participants[imported.mail(record)["id"]]
        expected = {
            "from": {record["sender"]},
            "to": set(record["to"]),
            "cc": set(record["cc"]),
            "bcc": set(record["bcc"]),
        }
        assert {role: roles.get(role, set()) for role in expected} == expected, record["index"]


def test_attachments_and_body(imported: Imported) -> None:
    for record in imported.manifest:
        mail = imported.mail(record)
        assert mail["attachments"] == record["attachments"], record["index"]
        assert mail["has_attachments"] == (record["attachments"] > 0), record["index"]
        assert len(mail["body_text"] or "") <= BODY_TEXT_LIMIT
        assert mail["tsv"] is not None


def test_documents_match_the_manifest(imported: Imported) -> None:
    """Each attachment is the manifest's file (D77): its SHA-256, size, kind and text status
    after the attachments phase, and the preview the API offers for what the database holds
    (D125)."""
    max_size = Settings().preview_max_size
    kinds: Counter[str] = Counter()
    for record in imported.manifest:
        attachments = imported.attachments.get(imported.mail(record)["id"], [])
        assert [a["filename"] for a in attachments] == [t["filename"] for t in record["documents"]]
        for truth, attachment in zip(record["documents"], attachments, strict=True):
            if truth["sha256"] is None:  # the invalid_base64 fault: bytes unknown
                continue
            where = (record["index"], truth["filename"])
            found = [attachment[key] for key in ("sha256", "size_bytes", "kind", "status")]
            assert found == [truth[key] for key in ("sha256", "size", "kind", "status")], where
            hint = preview_kind(
                DocumentKind(attachment["kind"]), attachment["filename"], attachment["mime_type"],
                attachment["size_bytes"], hashed=attachment["sha256"] is not None,
                max_size=max_size,
            )  # fmt: skip
            assert hint == truth["preview"], where
            kinds[truth["kind"]] += 1
    assert {"pdf", "document", "spreadsheet", "image"} <= set(kinds), kinds


def test_dkim_matches_the_manifest(imported: Imported) -> None:
    for record in imported.manifest:
        mail = imported.mail(record)
        expected = record["dkim"]
        assert mail["dkim_status"] == expected["expected"], record["index"]
        # One dkim_result row per signature; the manifest lists them in signing order.
        statuses = Counter(imported.signatures.get(mail["id"], []))
        assert statuses == Counter(s["expected"] for s in expected["signatures"]), record["index"]


def test_duplicates_point_at_their_original(imported: Imported) -> None:
    manifest = imported.manifest
    ids = [imported.mail(record)["id"] for record in manifest]
    for record in manifest:
        original = record["duplicate_of"]
        expected = None if original is None else ids[original]
        assert imported.mail(record)["is_duplicate_of"] == expected, record["index"]
    assert any(record["duplicate_of"] is not None for record in manifest)


def test_threads_match_the_manifest(imported: Imported) -> None:
    manifest = imported.manifest
    by_index = {record["index"]: record for record in manifest}
    actual: dict[int, set[int]] = defaultdict(set)
    for record in manifest:
        thread_id = imported.mail(record)["thread_id"]
        if thread_id is not None:
            actual[thread_id].add(record["index"])

    threads: dict[int, set[int]] = defaultdict(set)
    for record in manifest:
        if record["thread_index"] is not None and record["duplicate_of"] is None:
            threads[record["thread_index"]].add(record["index"])
    expected: list[set[int]] = []
    for root, members in threads.items():
        if "missing_message_id" in by_index[root]["faults"]:
            members = members - {root}  # the root left the thread with its Message-ID
        if len(members) >= 2:
            duplicates = {r["index"] for r in manifest if r["duplicate_of"] in members}
            expected.append(members | duplicates)
    assert sorted(map(sorted, actual.values())) == sorted(map(sorted, expected))
    assert len(expected) > 10


# Import error kinds a fault variant must produce, and those it may produce.
_REQUIRED = {
    ("missing_message_id", "removed"): {"message_id"},
    ("bad_date", "missing"): {"date"},
    ("bad_date", "unparseable"): {"date"},
    ("bad_date", "nonstandard"): {"date"},
    ("broken_encoding", "raw_8bit_header"): {"encoding"},
    ("broken_encoding", "unknown_charset"): {"encoding"},
}
_ALLOWED = {
    ("bad_date", "two_digit_year"): {"date"},
    ("broken_encoding", "wrong_charset"): {"encoding"},
    ("broken_encoding", "invalid_base64"): {"encoding"},
    ("broken_encoding", "broken_encoded_word"): {"encoding"},
}


def test_import_errors_follow_the_faults(imported: Imported) -> None:
    for record in imported.manifest:
        kinds = imported.errors.get((record["file"], record["offset"]), set())
        faults = record["faults"].items()
        required = set().union(*(_REQUIRED.get(fault, set()) for fault in faults))
        allowed = required.union(*(_ALLOWED.get(fault, set()) for fault in faults))
        assert required <= kinds <= allowed, (record["index"], record["faults"], kinds)
    located = {key for key in imported.errors}
    assert located <= set(imported.mails)  # every error names the offset of its mail


def test_list_and_automation_headers_match_the_manifest(imported: Imported) -> None:
    for record in imported.manifest:
        mail = imported.mail(record)
        expected = (record["list_id"], record["automated"])
        assert (mail["list_id"], mail["automated"]) == expected, record["index"]

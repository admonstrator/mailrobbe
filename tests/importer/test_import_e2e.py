"""The real chain (split, parse, store, finalize) on a copy of the generated archive.

The database must match the generator manifest mail by mail. Where the two may differ, it is
said precisely next to the assertion:

- Subjects: a list host or gateway may tag the subject in transit ("[name] " in front, see
  generator.dkim._tamper); broken_encoding variants that damage the Subject header itself
  (raw_8bit_header, broken_encoded_word) are decoded heuristically.
- Threads: every reply references its thread's root, so a thread stays together through the
  root's Message-ID even when that mail lost it; only the root itself (missing_message_id)
  drops out, and a thread left with one mail is no thread.
"""

import asyncio
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.config import Settings
from mailrobbe.importer import dkim_hook
from mailrobbe.importer.cli import run_import
from mailrobbe.importer.model import BODY_TEXT_LIMIT
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
        exit_code = asyncio.run(run_import(Settings(database_url=url), mbox_dir, 2))
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
        files = {path: status for path, status in await rows("SELECT path, status FROM mbox_file")}
    await engine.dispose()
    return Imported(exit_code, files, manifest, mails, participants, errors)


def test_every_file_is_done(imported: Imported) -> None:
    assert imported.exit_code == 0
    assert set(imported.files.values()) == {"done"}
    assert set(imported.files) == {record["file"] for record in imported.manifest}


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
    if dkim_hook.create_checker(Settings(), None) is None:
        assert {mail["dkim_status"] for mail in imported.mails.values()} == {None}


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

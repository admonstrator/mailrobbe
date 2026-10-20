"""`mailrobbe dkim` end to end: the generated corpus imported as rows, checked from its files.

The archive fixture stands in for the importer: one mbox_file row per generated file and one mail
row per manifest record (offset, length, sha256, Message-ID, subject), dkim_status still NULL.
"""

import asyncio
import hashlib
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, pool, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.cli import main
from mailrobbe.config import Settings
from mailrobbe.db.models import DkimResult, DnsCache, Mail, MboxFile
from mailrobbe.dkim.override import key_name
from mailrobbe.dkim.recheck import DEFAULT_STATUSES, recheck
from mailrobbe.enums import DkimStatus, DnsStatus
from mailrobbe.mbox import read_message
from tests.dkim.conftest import Corpus

# read_message ---------------------------------------------------------------------------------


def test_read_message_gives_the_imported_bytes(corpus: Corpus) -> None:
    for record in corpus.records:
        raw = read_message(corpus.mbox_dir / record["file"], record["offset"], record["length"])
        assert hashlib.sha256(raw).hexdigest() == record["sha256"], record["index"]
        assert raw == corpus.message(record)


def test_read_message_accepts_crlf_records(tmp_path: Path) -> None:
    quoted = b"From: a@nordwind.example\r\nSubject: x\r\n\r\n>From here on\r\n>>From there\r\n"
    first = b"From a@nordwind.example Mon Mar  4 09:12:33 2019\r\n" + quoted + b"\r\n"
    second = b"From b@nordwind.example Mon Mar  4 09:12:34 2019\nBody\n\n"
    path = tmp_path / "crlf.mbox"
    path.write_bytes(first + second)
    assert read_message(path, 0, len(first)) == quoted.replace(b"\n>", b"\n")
    assert read_message(path, len(first), len(second)) == b"Body\n"


def test_read_message_rejects_a_range_without_a_record(corpus: Corpus) -> None:
    record = corpus.records[1]
    path = corpus.mbox_dir / record["file"]
    with pytest.raises(ValueError):
        read_message(path, record["offset"] + 1, record["length"])
    with pytest.raises(ValueError):  # beyond the end of the file
        read_message(path, record["offset"], path.stat().st_size)


# The recheck ----------------------------------------------------------------------------------


@dataclass
class Archive:
    url: str
    mbox_dir: Path
    mail_ids: dict[int, int]  # manifest index -> mail.id

    @property
    def settings(self) -> Settings:
        return Settings(database_url=self.url, mbox_dir=self.mbox_dir)

    def state(self) -> dict[int, tuple[DkimStatus | None, list[dict[str, Any]]]]:
        """mail.id -> (dkim_status, dkim_result rows in signature order)."""
        return asyncio.run(_state(self.url))

    def set_status(self, mail_ids: list[int], status: DkimStatus) -> None:
        asyncio.run(_set_status(self.url, mail_ids, status))

    def dns_cache(self) -> dict[str, DnsStatus]:
        """dns_cache: name -> status."""
        return asyncio.run(_dns_cache(self.url))


async def _load(url: str, corpus: Corpus) -> dict[int, int]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            file_ids: dict[str, int] = {}
            for name in sorted({record["file"] for record in corpus.records}):
                size = (corpus.mbox_dir / name).stat().st_size
                statement = insert(MboxFile).values(path=name, size_bytes=size)
                result = await connection.execute(statement.returning(MboxFile.id))
                file_ids[name] = result.scalar_one()
            rows = [
                {
                    "mbox_file_id": file_ids[record["file"]],
                    "byte_offset": record["offset"],
                    "byte_length": record["length"],
                    "raw_sha256": record["sha256"],
                    "message_id": record["message_id"],
                    "subject": record["subject"],
                }
                for record in corpus.records
            ]
            await connection.execute(insert(Mail), rows)
            ids = await connection.execute(select(Mail.mbox_file_id, Mail.byte_offset, Mail.id))
            by_position = {(file_id, offset): mail_id for file_id, offset, mail_id in ids}
    finally:
        await engine.dispose()
    return {
        record["index"]: by_position[file_ids[record["file"]], record["offset"]]
        for record in corpus.records
    }


async def _state(url: str) -> dict[int, tuple[DkimStatus | None, list[dict[str, Any]]]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            mails = await connection.execute(select(Mail.id, Mail.dkim_status))
            state: dict[int, tuple[DkimStatus | None, list[dict[str, Any]]]] = {
                mail_id: (status, []) for mail_id, status in mails
            }
            results = await connection.execute(
                select(*DkimResult.__table__.columns).order_by(
                    DkimResult.mail_id, DkimResult.signature_index
                )
            )
            for row in results:
                state[row.mail_id][1].append(dict(row._mapping))
    finally:
        await engine.dispose()
    return state


async def _dns_cache(url: str) -> dict[str, DnsStatus]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(select(DnsCache.name, DnsCache.status))
            return {name: status for name, status in rows}
    finally:
        await engine.dispose()


async def _set_status(url: str, mail_ids: list[int], status: DkimStatus) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                update(Mail).where(Mail.id.in_(mail_ids)).values(dkim_status=status)
            )
    finally:
        await engine.dispose()


@pytest.fixture
def archive(empty_database_url: str, corpus: Corpus) -> Archive:
    migrate.upgrade("head", empty_database_url)
    return Archive(
        empty_database_url, corpus.mbox_dir, asyncio.run(_load(empty_database_url, corpus))
    )


def _expected(record: dict[str, Any]) -> list[tuple[int, str, str, str]]:
    signatures = record["dkim"]["signatures"]
    return [(i, s["expected"], s["domain"], s["selector"]) for i, s in enumerate(signatures)]


def _got(rows: list[dict[str, Any]]) -> list[tuple[int, str, str, str]]:
    return [(r["signature_index"], r["status"], r["domain"], r["selector"]) for r in rows]


def _ids(archive: Archive, corpus: Corpus, *statuses: str) -> list[int]:
    """Mail ids of the records whose expected DKIM status is one of statuses."""
    return [
        archive.mail_ids[record["index"]]
        for record in corpus.records
        if record["dkim"]["expected"] in statuses
    ]


@pytest.mark.db
@pytest.mark.parametrize("jobs", [1, 2])
def test_recheck_matches_the_manifest(archive: Archive, corpus: Corpus, jobs: int) -> None:
    expected = Counter(record["dkim"]["expected"] for record in corpus.records)
    summary = recheck(archive.settings, statuses=None, jobs=jobs)
    total = len(corpus.records)
    assert (summary.selected, summary.checked, summary.skipped) == (total, total, {})
    assert summary.statuses == dict(sorted(expected.items()))
    assert summary.transitions == {f"unchecked -> {s}": n for s, n in sorted(expected.items())}

    state = archive.state()
    for record in corpus.records:
        status, rows = state[archive.mail_ids[record["index"]]]
        assert status == record["dkim"]["expected"], record["index"]
        assert _got(rows) == _expected(record), record["index"]  # none for unsigned mails

    # Every key name of the corpus reached dns_cache with the answer the override table gives.
    names = {
        key_name(signature["selector"], signature["domain"]): signature["expected"]
        for record in corpus.records
        for signature in record["dkim"]["signatures"]
    }
    cache = archive.dns_cache()
    assert summary.dns_answers_saved >= len(cache) == len(names)
    dns_status = {"no_key": DnsStatus.NOT_FOUND, "temp_error": DnsStatus.TEMP_ERROR}
    assert cache == {
        name: dns_status.get(status, DnsStatus.FOUND) for name, status in names.items()
    }
    # One key lookup per signature: the first one per name and worker reaches the override table,
    # the others are cache hits and say so in dns_cached.
    rows = [row for _, rows in state.values() for row in rows]
    assert summary.dns_lookups + summary.dns_hits == len(rows)
    assert summary.dns_lookups == sum(not row["dns_cached"] for row in rows)
    assert len(names) <= summary.dns_lookups <= len(names) * jobs

    # The default selection: only the keys that were missing or did not answer are asked again.
    again = recheck(archive.settings, jobs=jobs)
    retried = expected["no_key"] + expected["temp_error"]
    assert (again.selected, again.checked, again.transitions) == (retried, retried, {})
    assert again.statuses == {"no_key": expected["no_key"], "temp_error": expected["temp_error"]}


@pytest.mark.db
def test_status_selection_touches_only_the_selected_mails(archive: Archive, corpus: Corpus) -> None:
    failed = _ids(archive, corpus, "fail")
    archive.set_status(failed, DkimStatus.FAIL)  # as if checked before, without results

    summary = recheck(archive.settings, statuses=DEFAULT_STATUSES)
    assert summary.selected == len(corpus.records) - len(failed)
    state = archive.state()
    assert all(state[mail_id] == (DkimStatus.FAIL, []) for mail_id in failed)

    no_key = set(_ids(archive, corpus, "no_key"))
    summary = recheck(archive.settings, statuses={DkimStatus.NO_KEY})
    assert (summary.selected, summary.statuses, summary.transitions) == (
        len(no_key),
        {"no_key": len(no_key)},
        {},
    )
    after = archive.state()
    for mail_id, (status, rows) in after.items():
        before = state[mail_id][1]
        touched = [r["checked_at"] for r in rows] != [r["checked_at"] for r in before]
        assert touched == (mail_id in no_key), mail_id
        assert status == state[mail_id][0] and _got(rows) == _got(before)


@pytest.mark.db
def test_unreadable_and_changed_mails_are_skipped(
    archive: Archive, corpus: Corpus, tmp_path: Path
) -> None:
    mbox_dir = tmp_path / "mbox"
    shutil.copytree(corpus.mbox_dir, mbox_dir)
    files = sorted({record["file"] for record in corpus.records})
    first = [record for record in corpus.records if record["file"] == files[0]]
    fine, changed, broken = first[3], first[4], first[5]
    gone = next(record for record in corpus.records if record["file"] == files[-1])
    with (mbox_dir / files[0]).open("r+b") as handle:
        handle.seek(changed["offset"] + changed["length"] // 2)
        byte = handle.read(1)
        handle.seek(-1, 1)
        handle.write(b"x" if byte != b"x" else b"y")
        handle.seek(broken["offset"])
        handle.write(b"X")  # no From separator any more
    (mbox_dir / files[-1]).unlink()

    selected = [archive.mail_ids[record["index"]] for record in (fine, changed, broken, gone)]
    settings = Settings(database_url=archive.url, mbox_dir=mbox_dir)
    summary = recheck(settings, mail_ids=selected)
    assert (summary.selected, summary.checked) == (4, 1)
    assert summary.skipped == {"hash_mismatch": 1, "missing_file": 1, "unreadable": 1}
    state = archive.state()
    assert state[selected[0]][0] == fine["dkim"]["expected"]
    assert all(state[mail_id] == (None, []) for mail_id in selected[1:])


@pytest.mark.db
def test_cli_checks_the_given_mails(
    archive: Archive,
    corpus: Corpus,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MAILROBBE_DATABASE_URL", archive.url)
    monkeypatch.setenv("MAILROBBE_MBOX_DIR", str(archive.mbox_dir))
    signed = [record for record in corpus.records if record["dkim"]["signatures"]][:2]
    selected = [archive.mail_ids[record["index"]] for record in signed]
    override = corpus.config.meta_dir / "dns_override.json"
    argv = ["dkim", "--status", "pass", "--dns-override", str(override), "--offline", "--quiet"]
    argv += [option for mail_id in selected for option in ("--mail", str(mail_id))]

    assert main(argv) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["selected"], summary["checked"], summary["skipped"]) == (2, 2, {})
    state = archive.state()
    for record, mail_id in zip(signed, selected, strict=True):
        assert state[mail_id][0] == record["dkim"]["expected"]
        assert _got(state[mail_id][1]) == _expected(record)
    assert sum(1 for status, _ in state.values() if status is not None) == 2


@pytest.mark.db
def test_a_worker_that_cannot_start_stops_the_run(archive: Archive, tmp_path: Path) -> None:
    broken = tmp_path / "dns_override.json"
    broken.write_text("{", encoding="utf-8")
    settings = archive.settings.model_copy(update={"dkim_dns_override": broken})
    with pytest.raises(ValueError):  # instead of the pool starting new workers forever
        recheck(settings, statuses=None, jobs=2)
    assert all(status is None for status, _ in archive.state().values())


def test_cli_reports_an_unreachable_database(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("MAILROBBE_DATABASE_URL", "postgresql+asyncpg://m:m@127.0.0.1:1/m")
    assert main(["dkim", "--quiet"]) == 1
    assert "database error" in caplog.text


@pytest.mark.parametrize(
    "argv",
    [["--all", "--status", "pass"], ["--status", "checked"], ["--jobs", "0"], ["--mail", "x"]],
)
def test_cli_rejects_bad_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["dkim", *argv])
    assert exit_info.value.code == 2


def test_cli_rejects_a_missing_override_table(tmp_path: Path) -> None:
    assert main(["dkim", "--dns-override", str(tmp_path / "missing.json")]) == 2

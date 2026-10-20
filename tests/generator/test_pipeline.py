import email.policy
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import pytest

from mailspider.dkim.override import DnsOverrideTable
from mailspider.generator.config import (
    DNS_OVERRIDE_NAME,
    MANIFEST_NAME,
    SUMMARY_NAME,
    GeneratorConfig,
)
from mailspider.generator.pipeline import CHUNK, WINDOW_PER_JOB, GenerationSummary, generate
from mailspider.generator.writer import unescape_from_lines
from tests.dkim_check import verify_mail
from tests.generator.conftest import small_config

MAILS = 300


def _config(tmp: Path, **changes: object) -> GeneratorConfig:
    values: dict[str, object] = {
        "mails": MAILS,
        "persons": 300,
        "domains": 30,
        "file_size": 2 * 1024**2,
        "large_attachments": 1,
        "large_attachment_size": 1024**2,
        "fault_rate": 0.05,
        "duplicate_rate": 0.03,
    }
    values.update(changes)
    return small_config(tmp, **values)


def _manifest(config: GeneratorConfig) -> list[dict[str, Any]]:
    lines = (config.meta_dir / MANIFEST_NAME).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _output(config: GeneratorConfig) -> dict[str, bytes]:
    files = {path.name: path.read_bytes() for path in sorted(config.out_dir.glob("*.mbox"))}
    for name in (MANIFEST_NAME, DNS_OVERRIDE_NAME):
        files[name] = (config.meta_dir / name).read_bytes()
    return files


def _message(files: dict[str, bytes], record: dict[str, Any]) -> bytes:
    """The message bytes of a record as RenderedMail.raw had them (separator and quoting off)."""
    piece = files[record["file"]][record["offset"] : record["offset"] + record["length"]]
    assert piece.startswith(b"From ") and piece.endswith(b"\n\n")
    message = piece.partition(b"\n")[2][:-1]
    return message if "unescaped_from" in record["faults"] else unescape_from_lines(message)


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> tuple[GeneratorConfig, GenerationSummary]:
    config = _config(tmp_path_factory.mktemp("run"))
    return config, generate(config)


def test_manifest_matches_the_mbox_files(run: tuple[GeneratorConfig, GenerationSummary]) -> None:
    config, summary = run
    records = _manifest(config)
    assert len(records) == summary.mails == MAILS
    assert [record["index"] for record in records] == list(range(MAILS))
    files = {name: (config.out_dir / name).read_bytes() for name in summary.files}
    assert {name: len(data) for name, data in files.items()} == summary.files
    assert len(files) > 1
    covered: Counter[str] = Counter()
    for record in records:
        assert hashlib.sha256(_message(files, record)).hexdigest() == record["sha256"]
        covered[record["file"]] += record["length"]
    assert dict(covered) == summary.files  # the records tile every file without gaps


def test_summary_counts_come_from_the_manifest(
    run: tuple[GeneratorConfig, GenerationSummary],
) -> None:
    config, summary = run
    records = _manifest(config)
    assert summary.dkim_expected == dict(Counter(r["dkim"]["expected"] for r in records))
    faults = Counter(fault for r in records for fault in r["faults"])
    assert summary.faults == dict(faults)
    assert summary.duplicates == sum(r["duplicate_of"] is not None for r in records)
    assert summary.faults["large_attachment"] == 1
    assert summary.bytes_total == sum(summary.files.values())
    stored = json.loads((config.meta_dir / SUMMARY_NAME).read_text(encoding="utf-8"))
    assert stored == json.loads(json.dumps(asdict(summary)))
    assert stored["config"]["mails"] == MAILS
    assert stored["config"]["out_dir"] == str(config.out_dir)


def test_records_describe_the_mails(run: tuple[GeneratorConfig, GenerationSummary]) -> None:
    config, summary = run
    files = {name: (config.out_dir / name).read_bytes() for name in summary.files}
    parser = BytesParser(policy=email.policy.default)
    for record in _manifest(config)[:60]:
        piece = files[record["file"]][record["offset"] : record["offset"] + record["length"]]
        message = parser.parsebytes(_message(files, record))
        if record["message_id"] is not None:
            assert message["Message-ID"] == record["message_id"]
        assert message["From"].addresses[0].addr_spec == record["sender"]
        assert piece.startswith(f"From {record['sender']} ".encode())
        if record["duplicate_of"] is not None:
            assert record["duplicate_of"] < record["index"]


def test_dkim_expectations_hold(run: tuple[GeneratorConfig, GenerationSummary]) -> None:
    config, summary = run
    table = DnsOverrideTable.load(config.meta_dir / DNS_OVERRIDE_NAME)
    files = {name: (config.out_dir / name).read_bytes() for name in summary.files}
    statuses: Counter[str] = Counter()
    for record in _manifest(config):
        overall, _ = verify_mail(_message(files, record), table)
        assert overall.value == record["dkim"]["expected"], record["index"]
        statuses[overall.value] += 1
    assert statuses["pass"] > 0 and statuses["unsigned"] > 0


def test_output_does_not_depend_on_jobs(
    tmp_path: Path, run: tuple[GeneratorConfig, GenerationSummary]
) -> None:
    config, _ = run
    parallel = _config(tmp_path, jobs=2)
    generate(parallel)
    assert _output(parallel) == _output(config)


def test_existing_output_is_protected(tmp_path: Path) -> None:
    config = _config(tmp_path, mails=40, large_attachments=0)
    first = generate(config)
    before = _output(config)
    with pytest.raises(FileExistsError):
        generate(config)
    again = generate(_config(tmp_path, mails=40, large_attachments=0, overwrite=True))
    assert _output(config) == before
    assert again.files == first.files


def test_small_file_size_gives_several_files(tmp_path: Path) -> None:
    config = _config(tmp_path, mails=120, large_attachments=0, file_size=256 * 1024)
    summary = generate(config)
    assert len(summary.files) >= 4
    oversized = [size for size in summary.files.values() if size > config.file_size]
    for name, size in summary.files.items():
        records = [r for r in _manifest(config) if r["file"] == name]
        assert size <= config.file_size or len(records) == 1
    assert len(oversized) < len(summary.files)


@pytest.mark.slow
def test_bigger_run_with_four_jobs_matches_one_job(tmp_path: Path) -> None:
    # more chunks than the look-ahead window holds, so chunks are dealt out repeatedly
    mails = 2 * CHUNK * WINDOW_PER_JOB * 4
    single = _config(tmp_path / "one", mails=mails, file_size=8 * 1024**2, large_attachments=2)
    parallel = _config(
        tmp_path / "four", mails=mails, file_size=8 * 1024**2, large_attachments=2, jobs=4
    )
    generate(single)
    generate(parallel)
    assert _output(single) == _output(parallel)

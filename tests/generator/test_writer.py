import hashlib
import json
import mailbox
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mailrobbe.enums import DkimStatus
from mailrobbe.generator.config import MANIFEST_NAME
from mailrobbe.generator.model import (
    Address,
    DkimOutcome,
    DkimSignatureOutcome,
    Fault,
    PlannedMail,
    RenderedMail,
)
from mailrobbe.generator.writer import (
    ManifestWriter,
    MboxWriter,
    escape_from_lines,
    manifest_record,
    prepare_output,
    separator_line,
    unescape_from_lines,
)
from tests.generator.conftest import small_config

_SEPARATOR = re.compile(
    rb"From \S+@\S+ (Mon|Tue|Wed|Thu|Fri|Sat|Sun) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    rb" [ \d]\d \d\d:\d\d:\d\d \d{4}\n"
)


def _mail(index: int, body: bytes = b"Hello\n", **changes: object) -> RenderedMail:
    planned = PlannedMail(
        index=index,
        seed=index,
        date=datetime(2019, 3, 4, 10, 12, 33, tzinfo=timezone(timedelta(hours=1))),
        sender=Address("max.mueller@nordwind.example", "Max Müller"),
        to=(Address("eva@elbtal.example"),),
        subject=f"Mail {index}",
        message_id=f"<{index}@nordwind.example>",
    )
    raw = b"From: max.mueller@nordwind.example\nMessage-ID: <%d@nordwind.example>\n\n" % index
    mail = RenderedMail(planned=planned, raw=raw + body, message_id=planned.message_id)
    return replace(mail, **changes)  # type: ignore[arg-type]


def test_escape_round_trip() -> None:
    raw = (
        b"From: a@b.example\nSubject: From here\n\nFrom the start\n>From quoted\n>>From deeper\n"
        b"Fromage\n From indented\nnot From here\nFrom"
    )
    escaped = escape_from_lines(raw)
    assert escaped.split(b"\n")[3:7] == [
        b">From the start",
        b">>From quoted",
        b">>>From deeper",
        b"Fromage",
    ]
    assert escaped.startswith(b"From: a@b.example\n")  # a header is no From_ line
    assert b"\n From indented\nnot From here\nFrom" in escaped
    assert unescape_from_lines(escaped) == raw
    assert escape_from_lines(b"no separator here") == b"no separator here"


def test_separator_is_the_envelope_sender_and_utc_asctime() -> None:
    line = separator_line(_mail(1))
    assert line == b"From max.mueller@nordwind.example Mon Mar  4 09:12:33 2019\n"
    assert _SEPARATOR.fullmatch(line)


def test_offsets_and_lengths_match_the_file(tmp_path: Path) -> None:
    mails = [
        _mail(0),
        _mail(1, b"From the start of a line\nand >From again\n"),
        _mail(2, b"no final newline"),
        _mail(3, b"From unescaped\n", escape_from_lines=False),
    ]
    with MboxWriter(tmp_path, 1024**2) as writer:
        places = [writer.write(mail) for mail in mails]
    data = (tmp_path / "mbox-0001.mbox").read_bytes()
    assert writer.files == {"mbox-0001.mbox": len(data)}
    assert sum(length for _, _, length in places) == len(data)
    for mail, (file, offset, length) in zip(mails, places, strict=True):
        assert file == "mbox-0001.mbox"
        record = data[offset : offset + length]
        separator, _, rest = record.partition(b"\n")
        assert _SEPARATOR.fullmatch(separator + b"\n")
        assert record.endswith(b"\n\n")
        message = rest[:-1]  # the empty line after the message
        expected = mail.raw if mail.raw.endswith(b"\n") else mail.raw + b"\n"
        if mail.escape_from_lines:
            assert unescape_from_lines(message) == expected
        else:
            assert message == expected
    assert b"\n>From the start of a line\nand >From again\n" in data
    assert b"\nFrom unescaped\n" in data
    assert len(mailbox.mbox(str(tmp_path / "mbox-0001.mbox"))) == len(mails) + 1  # the fault


def test_rotation_at_the_target_size(tmp_path: Path) -> None:
    mails = [_mail(i, b"x" * 300 + b"\n") for i in range(10)]
    with MboxWriter(tmp_path, 1000) as writer:
        places = [writer.write(mail) for mail in mails]
    length = places[0][2]
    per_file = 1000 // length
    assert [file for file, _, _ in places] == [
        f"mbox-{i // per_file + 1:04d}.mbox" for i in range(len(mails))
    ]
    for name, size in writer.files.items():
        assert (tmp_path / name).stat().st_size == size <= 1000
        assert (tmp_path / name).read_bytes().startswith(b"From ")


def test_oversized_record_gets_a_file_of_its_own(tmp_path: Path) -> None:
    mails = [_mail(0), _mail(1, b"y" * 5000 + b"\n"), _mail(2), _mail(3)]
    with MboxWriter(tmp_path, 1000) as writer:
        places = [writer.write(mail) for mail in mails]
    assert [file for file, _, _ in places] == [
        "mbox-0001.mbox",
        "mbox-0002.mbox",
        "mbox-0003.mbox",
        "mbox-0003.mbox",
    ]
    assert places[1][1] == 0 and writer.files["mbox-0002.mbox"] == places[1][2] > 1000


def test_first_record_larger_than_the_target(tmp_path: Path) -> None:
    with MboxWriter(tmp_path, 100) as writer:
        assert writer.write(_mail(0, b"z" * 500 + b"\n"))[:2] == ("mbox-0001.mbox", 0)
        assert writer.write(_mail(1))[:2] == ("mbox-0002.mbox", 0)


def test_manifest_record_takes_values_from_the_written_mail(tmp_path: Path) -> None:
    signature = DkimSignatureOutcome(
        "nordwind.example", "s1", "rsa-sha256", 2048, DkimStatus.NO_KEY, "selector_retired"
    )
    mail = _mail(
        7,
        message_id=None,
        faults={Fault.NESTED_MIME: "depth_3", Fault.BAD_DATE: "garbage"},
        dkim=DkimOutcome(DkimStatus.NO_KEY, (signature,)),
        duplicate_of=3,
    )
    record = manifest_record(12, mail, "mbox-0001.mbox", 100, 200)
    assert record.index == 12 and record.duplicate_of == 3
    assert record.message_id is None
    assert record.sha256 == hashlib.sha256(mail.raw).hexdigest()
    assert record.date == "2019-03-04T10:12:33+01:00"
    assert record.to == ["eva@elbtal.example"] and record.cc == [] and record.bcc == []
    assert record.faults == {"bad_date": "garbage", "nested_mime": "depth_3"}
    assert record.dkim == {
        "expected": "no_key",
        "signatures": [
            {
                "domain": "nordwind.example",
                "selector": "s1",
                "algorithm": "rsa-sha256",
                "key_bits": 2048,
                "expected": "no_key",
                "reason": "selector_retired",
            }
        ],
    }
    with ManifestWriter(tmp_path) as manifest:
        manifest.write(record)
    line = (tmp_path / MANIFEST_NAME).read_text(encoding="utf-8")
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line)["dkim"]["signatures"][0]["expected"] == "no_key"


def test_prepare_output_refuses_existing_output(tmp_path: Path) -> None:
    config = small_config(tmp_path)
    prepare_output(config)
    assert config.out_dir.is_dir() and config.meta_dir.is_dir()
    prepare_output(config)  # empty directories are fine

    (config.out_dir / "archive.mbox").write_bytes(b"From x\n")
    with pytest.raises(FileExistsError, match="MBOX"):
        prepare_output(config)
    (config.out_dir / "archive.mbox").unlink()

    (config.meta_dir / "manifest.jsonl").write_text("{}\n")
    with pytest.raises(FileExistsError, match="--overwrite"):
        prepare_output(config)


def test_prepare_output_overwrite_deletes_only_generator_files(tmp_path: Path) -> None:
    config = small_config(tmp_path, overwrite=True)
    config.meta_dir.mkdir(parents=True)
    (config.out_dir / "mbox-0001.mbox").write_bytes(b"old")
    (config.out_dir / "mbox-0002.mbox").write_bytes(b"old")
    (config.out_dir / "archive.mbox").write_bytes(b"keep")
    (config.out_dir / "notes.txt").write_text("keep")
    (config.meta_dir / "manifest.jsonl").write_text("old")
    (config.meta_dir / "dkim_keys").mkdir()
    (config.meta_dir / "dkim_keys" / "rsa-2048.pem").write_text("old")
    prepare_output(config)
    assert sorted(p.name for p in config.out_dir.iterdir()) == [
        "_generator",
        "archive.mbox",
        "notes.txt",
    ]
    assert list(config.meta_dir.iterdir()) == []


def test_prepare_output_rejects_meta_dir_containing_out_dir(tmp_path: Path) -> None:
    for meta_dir in (tmp_path / "mbox", tmp_path):
        config = replace(small_config(tmp_path, overwrite=True), meta_dir=meta_dir)
        with pytest.raises(ValueError, match="meta_dir"):
            prepare_output(config)

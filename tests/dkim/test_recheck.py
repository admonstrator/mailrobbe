"""Reading imported mails back from their MBOX files (mbox.read_message)."""

import hashlib
from pathlib import Path

import pytest

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

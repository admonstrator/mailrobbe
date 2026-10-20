import hashlib

import pytest

from mailrobbe.mbox import message_from_record, read_message, unescape_from_lines
from tests.conftest import GeneratedArchive


def test_read_message_matches_the_manifest(generated_archive: GeneratedArchive) -> None:
    records = generated_archive.manifest
    assert any("unescaped_from" in record["faults"] for record in records)
    for record in records:
        path = generated_archive.mbox_dir / record["file"]
        message = read_message(path, record["offset"], record["length"])
        assert hashlib.sha256(message).hexdigest() == record["sha256"], record["index"]


def test_read_message_rejects_a_record_beyond_the_end(generated_archive: GeneratedArchive) -> None:
    last = generated_archive.manifest[-1]
    with pytest.raises(ValueError, match="bytes"):
        read_message(generated_archive.mbox_dir / last["file"], last["offset"], last["length"] + 1)


SEPARATOR = b"From a@b.example Mon Mar  4 09:12:33 2019\n"


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (SEPARATOR + b"S: x\n\nbody\n\n", b"S: x\n\nbody\n"),
        # not ended by an empty line: the next separator followed directly
        (SEPARATOR + b"S: x\n\nbody\n", b"S: x\n\nbody\n"),
        # a message ending with an empty line of its own keeps it
        (SEPARATOR + b"S: x\n\nbody\n\n\n", b"S: x\n\nbody\n\n"),
        # data without a separator keeps its first line
        (b"S: x\n\nbody\n\n", b"S: x\n\nbody\n"),
        (SEPARATOR + b"S: x\n\n>From here\n>>From x\n\n", b"S: x\n\nFrom here\n>From x\n"),
    ],
)
def test_message_from_record(record: bytes, message: bytes) -> None:
    assert message_from_record(record) == message


def test_unescape_from_lines_only_touches_quoted_from_lines() -> None:
    data = b">From a\n>>From b\n> From c\nx >From d\n>Fromage\n"
    assert unescape_from_lines(data) == b"From a\n>From b\n> From c\nx >From d\n>Fromage\n"

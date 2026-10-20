import hashlib
import io
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mailrobbe.enums import ImportErrorKind
from mailrobbe.importer.model import TRUNCATED_HEAD_SIZE
from mailrobbe.importer.split import MboxRecord, iter_records, separator_date
from mailrobbe.mbox import message_from_record
from tests.conftest import GeneratedArchive

MAX_SIZE = 256 * 1024**2
SEPARATOR = b"From a@b.example Mon Mar  4 09:12:33 2019\n"


def _records(data: bytes, start: int = 0, **options: int) -> list[MboxRecord]:
    options.setdefault("max_size", MAX_SIZE)
    return list(iter_records(io.BytesIO(data), start, **options))


def _kinds(record: MboxRecord) -> list[ImportErrorKind]:
    return [issue.kind for issue in record.issues]


def _by_file(archive: GeneratedArchive) -> dict[str, list[dict[str, Any]]]:
    files: dict[str, list[dict[str, Any]]] = {}
    for entry in archive.manifest:
        files.setdefault(entry["file"], []).append(entry)
    return files


def _sample(archive: GeneratedArchive, tmp_path: Path, wanted: set[int]) -> tuple[bytes, list[str]]:
    """The records of the given manifest indexes copied into one MBOX; returns it and hashes."""
    chunks, hashes = [], []
    for entry in archive.manifest:
        if entry["index"] in wanted:
            path = archive.mbox_dir / entry["file"]
            with path.open("rb") as handle:
                handle.seek(entry["offset"])
                chunks.append(handle.read(entry["length"]))
            hashes.append(entry["sha256"])
    return b"".join(chunks), hashes


@pytest.fixture(scope="module")
def faulty_sample(generated_archive: GeneratedArchive, tmp_path_factory: pytest.TempPathFactory):
    """Every record with an unescaped From line, each with its neighbours."""
    faulty = [e["index"] for e in generated_archive.manifest if "unescaped_from" in e["faults"]]
    variants = {e["faults"].get("unescaped_from") for e in generated_archive.manifest}
    assert {"sentence", "separator_like"} <= variants
    wanted = {index + step for index in faulty for step in (-1, 0, 1)}
    return _sample(generated_archive, tmp_path_factory.mktemp("sample"), wanted)


def test_records_match_the_manifest(generated_archive: GeneratedArchive) -> None:
    for name, entries in _by_file(generated_archive).items():
        path = generated_archive.mbox_dir / name
        data = path.read_bytes()
        with path.open("rb") as handle:
            records = list(iter_records(handle, max_size=MAX_SIZE))
        assert len(records) == len(entries), name
        for record, entry in zip(records, entries, strict=True):
            assert (record.byte_offset, record.byte_length) == (entry["offset"], entry["length"])
            assert record.raw_sha256 == entry["sha256"], entry["index"]
            raw = data[record.byte_offset : record.byte_offset + record.byte_length]
            assert record.message == message_from_record(raw)
            assert record.separator == raw.partition(b"\n")[0]
            assert not record.truncated
            assert not record.issues, entry["index"]
        assert sum(record.byte_length for record in records) == len(data)


@pytest.mark.parametrize("block_size", [1, 7, 64, 4096])
def test_tiny_blocks_give_the_same_records(
    faulty_sample: tuple[bytes, list[str]], block_size: int
) -> None:
    data, hashes = faulty_sample
    expected = _records(data)
    assert [record.raw_sha256 for record in expected] == hashes
    assert _records(data, block_size=block_size) == expected


@pytest.mark.parametrize("block_size", [64, 1000, 1024**2])
def test_large_records_are_truncated_but_hashed_whole(
    generated_archive: GeneratedArchive, tmp_path: Path, block_size: int
) -> None:
    large = next(e for e in generated_archive.manifest if "large_attachment" in e["faults"])
    data, hashes = _sample(generated_archive, tmp_path, {large["index"] - 1, large["index"]})
    assert large["length"] > TRUNCATED_HEAD_SIZE
    max_size = large["length"] - 1
    records = _records(data, max_size=max_size, block_size=block_size)
    assert [record.raw_sha256 for record in records] == hashes
    small, big = records
    assert not small.truncated and not small.issues
    assert big.truncated
    assert _kinds(big) == [ImportErrorKind.TOO_LARGE]
    raw = data[big.byte_offset :]
    assert big.message == message_from_record(raw)[:TRUNCATED_HEAD_SIZE]
    assert big.byte_length == large["length"]


def test_every_record_above_max_size_keeps_its_hash(
    faulty_sample: tuple[bytes, list[str]],
) -> None:
    data, hashes = faulty_sample
    for block_size in (7, 4096):
        records = _records(data, max_size=2000, block_size=block_size)
        assert [record.raw_sha256 for record in records] == hashes
        assert all(record.truncated == (record.byte_length > 2000) for record in records)
        assert any(record.truncated for record in records)
        for record in records:
            raw = data[record.byte_offset : record.byte_offset + record.byte_length]
            assert record.message == message_from_record(raw)[:TRUNCATED_HEAD_SIZE]


# mboxrd quoting, line starts that straddle chunks, records ending with and without LF LF
_QUOTED = (
    SEPARATOR + b"Subject: q\n\n>From a\n>>From b\n>Fro\n>>>>\n>From\n> From c\n>",
    SEPARATOR + b"Subject: q\n\nx\n>>From the end\n\n",
    SEPARATOR + b"Subject: q\n\nno final newline",
)


@pytest.mark.parametrize("block_size", [1, 2, 3, 5, 64])
@pytest.mark.parametrize("max_size", [0, 40, MAX_SIZE])
def test_quoted_from_lines_are_unescaped_in_every_chunking(block_size: int, max_size: int) -> None:
    data = b"\n\n".join(_QUOTED)
    records = _records(data, max_size=max_size, block_size=block_size)
    assert len(records) == len(_QUOTED)
    for record in records:
        raw = data[record.byte_offset : record.byte_offset + record.byte_length]
        message = message_from_record(raw)
        assert record.raw_sha256 == hashlib.sha256(message).hexdigest()
        assert record.message == message
    assert records[0].message.split(b"\n")[2:6] == [b"From a", b">From b", b">Fro", b">>>>"]


def test_resuming_at_a_record_boundary_yields_the_tail(generated_archive: GeneratedArchive) -> None:
    name, entries = max(_by_file(generated_archive).items(), key=lambda item: len(item[1]))
    data = (generated_archive.mbox_dir / name).read_bytes()
    full = _records(data)
    middle = len(entries) // 2
    tail = _records(data, entries[middle]["offset"])
    assert tail == full[middle:]
    assert sum(record.byte_length for record in tail) == len(data) - entries[middle]["offset"]
    assert _records(data, len(data)) == []


def test_resuming_keeps_the_issue_of_a_separator_without_empty_line() -> None:
    first = SEPARATOR + b"Subject: 1\n\nbody\n"
    data = first + SEPARATOR + b"Subject: 2\n\nbody\n\n"
    full = _records(data)
    assert _kinds(full[1]) == [ImportErrorKind.SEPARATOR]
    assert full[0].message == b"Subject: 1\n\nbody\n"  # no byte lost at the end
    assert _records(data, len(first)) == full[1:]


def test_data_without_separator_at_start_is_one_record() -> None:
    headless = b"Subject: lost\n\nbody\n\n"
    data = headless + SEPARATOR + b"Subject: next\n\nbody\n\n"
    first, second = _records(data)
    assert (first.byte_offset, first.byte_length, first.separator) == (0, len(headless), b"")
    assert first.message == message_from_record(headless)
    assert _kinds(first) == [ImportErrorKind.SEPARATOR]
    assert second.byte_offset == len(headless) and not second.issues


def test_a_malformed_from_line_at_start_is_still_a_boundary() -> None:
    first, second = _records(b"From nowhere\nSubject: x\n\nbody\n\n" + SEPARATOR + b"S: y\n\n")
    assert first.separator == b"From nowhere"
    assert first.message == b"Subject: x\n\nbody\n"
    assert _kinds(first) == [ImportErrorKind.SEPARATOR]
    assert not second.issues


@pytest.mark.parametrize(
    "line",
    [
        b"From my side everything is ready, we can start on Monday.",
        b"From a@b.example Mon Mar  4 09:12:33",  # no year
        b"From  Mon Mar  4 09:12:33 2019",  # no envelope sender
        b"From a@b.example Mon Mar 4 9:12 2019\n",  # a separator followed by an empty line
        b"From a b@c.example Mon Mar  4 09:12:33 2019",  # sender with a space
    ],
)
def test_body_lines_that_are_no_separator(line: bytes) -> None:
    data = SEPARATOR + b"Subject: x\n\n" + line + b"\nSubject: looks like a header\n\n"
    (record,) = _records(data)
    assert record.byte_length == len(data)


@pytest.mark.parametrize(
    ("line", "instant"),
    [
        (b"From a@b.example Mon Mar  4 09:12:33 2019", datetime(2019, 3, 4, 9, 12, 33, tzinfo=UTC)),
        (b"From 1234567890@xxx Mon Jan 01 00:00:00 +0000 2018", datetime(2018, 1, 1, tzinfo=UTC)),
        (b"From 1@xxx Mon Jan 01 00:30:00 +0100 2018", datetime(2017, 12, 31, 23, 30, tzinfo=UTC)),
        (
            b"From MAILER-DAEMON Fri Jul  8 12:08:34 2011",
            datetime(2011, 7, 8, 12, 8, 34, tzinfo=UTC),
        ),
        (b"From - Thu Feb 29 23:59 2024", datetime(2024, 2, 29, 23, 59, tzinfo=UTC)),
    ],
)
def test_separator_forms(line: bytes, instant: datetime) -> None:
    data = SEPARATOR + b"Subject: 1\n\n" + b"\n" + line + b"\nX-Header: 2\n\nbody\n\n"
    second = _records(data)[1]
    assert second.separator == line and not second.issues
    assert separator_date(line) == instant


def test_separator_date_rejects_impossible_dates() -> None:
    assert separator_date(b"From a@b Mon Feb 30 09:12:33 2019") is None
    assert separator_date(b"") is None


@pytest.mark.parametrize("max_size", [0, 30, MAX_SIZE])
@pytest.mark.parametrize("block_size", [1, 3, 4096])
def test_crlf_files_follow_message_from_record(block_size: int, max_size: int) -> None:
    separator = SEPARATOR.replace(b"\n", b"\r\n")
    messages = [b"Subject: %d\r\nFrom: a@b.example\r\n\r\n>From here\r\n" % n for n in range(3)]
    last = separator + b"Subject: last\r\n\r\nno empty line at the end\r\n"
    data = b"".join(separator + message + b"\r\n" for message in messages) + last
    records = _records(data, block_size=block_size, max_size=max_size)
    assert len(records) == 4
    for record in records:
        raw = data[record.byte_offset : record.byte_offset + record.byte_length]
        assert record.message == message_from_record(raw)
        assert record.raw_sha256 == hashlib.sha256(record.message).hexdigest()
        assert record.separator == SEPARATOR.rstrip()
        assert _kinds(record) == ([ImportErrorKind.TOO_LARGE] if record.truncated else [])
    assert records[0].message == b"Subject: 0\r\nFrom: a@b.example\r\n\r\nFrom here\r\n"
    assert records[3].message.endswith(b"at the end\r\n")


def test_empty_input_has_no_records() -> None:
    assert _records(b"") == []


class _Endless(io.RawIOBase):
    """`size` bytes of `line` repeated, generated while read."""

    def __init__(self, line: bytes, size: int) -> None:
        self._line, self._size, self._at = line, size, 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self._at = offset
        return offset

    def readinto(self, buffer: Any) -> int:
        count = max(0, min(len(buffer), self._size - self._at))
        start = self._at % len(self._line)
        chunk = (self._line * (count // len(self._line) + 2))[start : start + count]
        buffer[:count] = chunk
        self._at += count
        return count


@pytest.mark.parametrize(
    ("line", "size"),
    [(b"From nobody, a line that is no separator\n", 8 * 1024**2), (b"x" * 4096, 64 * 1024**2)],
    ids=["rejected-candidates", "no-newline"],
)
def test_memory_stays_bounded_without_any_separator(line: bytes, size: int) -> None:
    handle = io.BufferedReader(_Endless(line, size))
    tracemalloc.start()
    try:
        (record,) = iter_records(handle, max_size=1024**2, block_size=256 * 1024)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert record.byte_length == size and record.truncated
    assert peak < 4 * 1024**2

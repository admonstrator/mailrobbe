"""mboxrd writer with file rotation, and the manifest of what was written where.

Record layout (start.md): a separator line `From <envelope sender> <asctime in UTC>`, the message
with every line matching `^>*From ` prefixed by one more `>` (unless the mail asks to stay
unescaped), a final LF, then one empty line. A manifest offset points at the `F` of the
separator; its length covers separator, message and the empty line.
"""

import hashlib
import re
import shutil
from dataclasses import asdict
from datetime import UTC
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from mailspider.generator.config import MANIFEST_NAME, MBOX_NAME_TEMPLATE, GeneratorConfig
from mailspider.generator.model import ManifestRecord, RenderedMail

_FROM_LINE = re.compile(rb"^(>*From )", re.MULTILINE)
_ESCAPED_FROM_LINE = re.compile(rb"^>(>*From )", re.MULTILINE)
_BUFFER = 1024 * 1024


def escape_from_lines(raw: bytes) -> bytes:
    """mboxrd quoting: one more `>` in front of every line that matches `^>*From `."""
    if b"From " not in raw:
        return raw
    return _FROM_LINE.sub(rb">\1", raw)


def unescape_from_lines(data: bytes) -> bytes:
    """Inverse of escape_from_lines, as an mboxrd reader applies it."""
    if b"From " not in data:
        return data
    return _ESCAPED_FROM_LINE.sub(rb"\1", data)


def separator_line(mail: RenderedMail) -> bytes:
    """`From <envelope sender> <asctime in UTC>`, for example `From a@b.example Mon Mar  4 ...`."""
    planned = mail.planned
    stamp = planned.date.astimezone(UTC).ctime()
    return f"From {planned.sender.email} {stamp}\n".encode("ascii")


def prepare_output(config: GeneratorConfig) -> None:
    """Create out_dir and meta_dir; refuse to mix runs unless config.overwrite.

    Raises FileExistsError when out_dir already holds `*.mbox` files or meta_dir is not empty.
    With overwrite only `mbox-*.mbox` in out_dir and the contents of meta_dir are deleted.
    """
    out_dir = config.out_dir
    meta_dir = config.meta_dir
    out_resolved = out_dir.resolve()
    meta_resolved = meta_dir.resolve()
    if meta_resolved == out_resolved or out_resolved.is_relative_to(meta_resolved):
        raise ValueError(f"meta_dir {meta_dir} must not be out_dir or contain it")
    out_dir.mkdir(parents=True, exist_ok=True)
    mbox_files = sorted(out_dir.glob("*.mbox"))
    meta_entries = sorted(meta_dir.iterdir()) if meta_dir.is_dir() else []
    if (mbox_files or meta_entries) and not config.overwrite:
        found = f"{len(mbox_files)} MBOX file(s) in {out_dir}" if mbox_files else ""
        if meta_entries:
            found += f"{' and ' if found else ''}{len(meta_entries)} entries in {meta_dir}"
        raise FileExistsError(f"refusing to overwrite: {found} (use --overwrite)")
    if config.overwrite:
        for path in sorted(out_dir.glob("mbox-*.mbox")):
            path.unlink()
        for entry in meta_entries:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    meta_dir.mkdir(parents=True, exist_ok=True)


class MboxWriter:
    """Appends records to mbox-0001.mbox, mbox-0002.mbox, ... in out_dir.

    A new file starts when the current one is not empty and the next record would push it past
    file_size, so a record larger than file_size gets a file of its own.
    """

    def __init__(self, out_dir: Path, file_size: int) -> None:
        self._out_dir = out_dir
        self._file_size = file_size
        self._handle: IO[bytes] | None = None
        self._name = ""
        self._size = 0
        self.files: dict[str, int] = {}  # file name -> bytes written, in order

    def write(self, mail: RenderedMail) -> tuple[str, int, int]:
        """Append one record; returns (file name, offset of the separator, record length)."""
        separator = separator_line(mail)
        body = escape_from_lines(mail.raw) if mail.escape_from_lines else mail.raw
        ending = b"\n" if body.endswith(b"\n") else b"\n\n"
        length = len(separator) + len(body) + len(ending)
        if self._handle is None or (self._size and self._size + length > self._file_size):
            self._open_next()
        assert self._handle is not None
        offset = self._size
        self._handle.write(separator)
        self._handle.write(body)
        self._handle.write(ending)
        self._size += length
        self.files[self._name] = self._size
        return self._name, offset, length

    def _open_next(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._name = MBOX_NAME_TEMPLATE.format(number=len(self.files) + 1)
        self._handle = open(self._out_dir / self._name, "wb", buffering=_BUFFER)  # noqa: SIM115
        self._size = 0
        self.files[self._name] = 0

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()


def manifest_record(
    index: int, mail: RenderedMail, file: str, offset: int, length: int, sha256: str | None = None
) -> ManifestRecord:
    """Ground truth of one written mail; values come from the RenderedMail as written.

    `sha256` is the digest of mail.raw when the caller already has it.
    """
    planned = mail.planned
    signatures = []
    for outcome in mail.dkim.signatures:
        item = asdict(outcome)
        item["expected"] = outcome.expected.value
        signatures.append(item)
    return ManifestRecord(
        index=index,
        file=file,
        offset=offset,
        length=length,
        sha256=sha256 or hashlib.sha256(mail.raw).hexdigest(),
        message_id=mail.message_id,
        date=planned.date.isoformat(),
        sender=planned.sender.email,
        to=[a.email for a in planned.to],
        cc=[a.email for a in planned.cc],
        bcc=[a.email for a in planned.bcc],
        subject=planned.subject,
        in_reply_to=planned.in_reply_to,
        thread_index=planned.thread_index,
        list_id=planned.list_id,
        automated=planned.automated,
        attachments=len(planned.attachments),
        dkim={"expected": mail.dkim.expected.value, "signatures": signatures},
        faults={fault.value: variant for fault, variant in sorted(mail.faults.items())},
        duplicate_of=mail.duplicate_of,
    )


class ManifestWriter:
    """manifest.jsonl in meta_dir: one ManifestRecord per line, in stream order."""

    def __init__(self, meta_dir: Path) -> None:
        self._handle = open(meta_dir / MANIFEST_NAME, "w", encoding="utf-8", buffering=_BUFFER)  # noqa: SIM115

    def write(self, record: ManifestRecord) -> None:
        self._handle.write(record.to_json_line())

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()

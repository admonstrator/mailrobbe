"""A small generated corpus for the DKIM tests, built once per test session.

400 mails with seed 42 cover every DKIM outcome: pass, fail (body and header changed after
signing), no_key, temp_error, unsigned, and mails with two signatures. The manifest is the
ground truth (_generator/manifest.jsonl); Corpus.message returns the bytes whose SHA-256 the
manifest records, which is what the importer stores as mail.raw_sha256.
"""

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import pytest

from mailrobbe.dkim.override import DnsOverrideTable
from mailrobbe.generator.config import DNS_OVERRIDE_NAME, MANIFEST_NAME, GeneratorConfig
from mailrobbe.generator.pipeline import generate
from mailrobbe.generator.writer import unescape_from_lines
from tests.generator.conftest import small_config

CORPUS_MAILS = 400


@dataclass
class Corpus:
    config: GeneratorConfig

    @property
    def mbox_dir(self) -> Path:
        return self.config.out_dir

    @cached_property
    def records(self) -> list[dict[str, Any]]:
        text = (self.config.meta_dir / MANIFEST_NAME).read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    @cached_property
    def table(self) -> DnsOverrideTable:
        return DnsOverrideTable.load(self.config.meta_dir / DNS_OVERRIDE_NAME)

    @cached_property
    def _files(self) -> dict[str, bytes]:
        return {path.name: path.read_bytes() for path in sorted(self.mbox_dir.glob("*.mbox"))}

    def record_bytes(self, record: dict[str, Any]) -> bytes:
        """The whole MBOX record: separator line, quoted message, empty line."""
        start = record["offset"]
        return self._files[record["file"]][start : start + record["length"]]

    def message(self, record: dict[str, Any]) -> bytes:
        """The message as the generator rendered it: no separator line, mboxrd quoting undone."""
        message = self.record_bytes(record).partition(b"\n")[2][:-1]
        return message if "unescaped_from" in record["faults"] else unescape_from_lines(message)


@pytest.fixture(scope="session")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Corpus:
    config = small_config(
        tmp_path_factory.mktemp("dkim-corpus"),
        mails=CORPUS_MAILS,
        persons=300,
        domains=30,
        file_size=4 * 1024**2,
        large_attachment_size=1024**2,
        fault_rate=0.05,
        duplicate_rate=0.03,
        seed=42,
        jobs=1,
    )
    generate(config)
    return Corpus(config)

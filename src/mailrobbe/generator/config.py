import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# File names inside GeneratorConfig.meta_dir.
MANIFEST_NAME = "manifest.jsonl"
DNS_OVERRIDE_NAME = "dns_override.json"
SUMMARY_NAME = "summary.json"
DKIM_KEY_DIR = "dkim_keys"

# MBOX files are named mbox-0001.mbox, mbox-0002.mbox, ... inside GeneratorConfig.out_dir.
MBOX_NAME_TEMPLATE = "mbox-{number:04d}.mbox"

_SIZE_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
_SIZE_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)(?:i?b)?\s*$", re.IGNORECASE)


def parse_size(value: str) -> int:
    """Parse '128MB', '4GB', '512KiB' or a plain byte count. Units are binary (1 MB = 2**20)."""
    match = _SIZE_PATTERN.match(value)
    if match is None:
        raise ValueError(f"invalid size: {value!r}")
    number, unit = match.groups()
    size = int(float(number) * _SIZE_UNITS[unit.lower()])
    if size <= 0:
        raise ValueError(f"size must be positive: {value!r}")
    return size


@dataclass(frozen=True, slots=True)
class GeneratorConfig:
    """All knobs of the test data generator (SPEC 3.6). The CLI maps 1:1 onto these fields."""

    out_dir: Path
    meta_dir: Path
    mails: int = 10_000
    persons: int = 1_500
    domains: int = 120
    date_from: date = date(2012, 1, 1)
    date_to: date = date(2026, 6, 30)
    attachment_share: float = 0.15
    file_size: int = 128 * 1024**2
    dkim_signed_share: float = 0.7
    fault_rate: float = 0.02
    duplicate_rate: float = 0.01
    large_attachments: int = 2
    large_attachment_size: int = 55 * 1024**2
    seed: int = 42
    jobs: int = 1
    overwrite: bool = False

    def __post_init__(self) -> None:
        if self.mails < 1:
            raise ValueError("mails must be at least 1")
        if self.persons < 2:
            raise ValueError("persons must be at least 2")
        if not 1 <= self.domains <= self.persons:
            raise ValueError("domains must be between 1 and the number of persons")
        if self.date_from >= self.date_to:
            raise ValueError("date_from must be before date_to")
        if self.date_to > date.today():
            # DKIM verifiers reject signatures with t= in the future (t= is the mail date).
            raise ValueError("date_to must not lie in the future")
        for name in ("attachment_share", "dkim_signed_share", "fault_rate", "duplicate_rate"):
            share = getattr(self, name)
            if not 0.0 <= share <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.large_attachments < 0:
            raise ValueError("large_attachments must not be negative")
        if self.large_attachments > self.mails:
            raise ValueError("large_attachments must not exceed mails")
        if self.file_size < 1 or self.large_attachment_size < 1:
            raise ValueError("sizes must be positive")
        if self.jobs < 1:
            raise ValueError("jobs must be at least 1")

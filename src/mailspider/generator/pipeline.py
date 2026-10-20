"""Generator orchestration: population, planning, worker pool, writer, manifest, summary.

CONTRACT STUB: generate() is implemented by the generator core.
"""

from dataclasses import dataclass, field
from typing import Any

from mailspider.generator.config import GeneratorConfig


@dataclass(slots=True)
class GenerationSummary:
    """Written to summary.json and printed by the CLI."""

    mails: int
    files: dict[str, int]  # MBOX file name -> size in bytes
    bytes_total: int
    dkim_expected: dict[str, int]  # DkimStatus value -> number of mails
    faults: dict[str, int]  # Fault value -> number of mails
    duplicates: int
    elapsed_seconds: float
    config: dict[str, Any] = field(default_factory=dict)


def generate(config: GeneratorConfig) -> GenerationSummary:
    raise NotImplementedError("generator core pending")

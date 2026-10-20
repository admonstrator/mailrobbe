"""DKIM keys, selectors and signing for generated mails.

CONTRACT STUB: the signatures below are fixed; the bodies are placeholders that leave every mail
unsigned and write an empty DNS override table, so the pipeline runs end to end.
"""

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mailspider.generator.config import DNS_OVERRIDE_NAME, GeneratorConfig
from mailspider.generator.model import Domain, RenderedMail


@dataclass(frozen=True, slots=True)
class DkimSetup:
    """Keys and selector plan, built once in the main process and shipped to the workers."""


def build_dkim_setup(
    domains: Sequence[Domain], config: GeneratorConfig, rng: random.Random
) -> DkimSetup:
    return DkimSetup()


def write_dkim_artifacts(setup: DkimSetup, meta_dir: Path) -> None:
    """Write dns_override.json (and the test keys) into meta_dir."""
    table = {"version": 1, "records": {}, "temp_error": []}
    (meta_dir / DNS_OVERRIDE_NAME).write_text(json.dumps(table, indent=2) + "\n")


def sign_mail(mail: RenderedMail, setup: DkimSetup, rng: random.Random) -> RenderedMail:
    """Sign (or deliberately mis-sign) the mail and record the expected outcome in mail.dkim."""
    return mail

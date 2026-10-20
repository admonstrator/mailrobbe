"""Deliberate defects in generated mails (SPEC 3.6).

CONTRACT STUB: the signatures below are fixed; the bodies are placeholders that change nothing.
"""

import random

from mailspider.generator.config import GeneratorConfig
from mailspider.generator.model import RenderedMail


def apply_faults(mail: RenderedMail, config: GeneratorConfig, rng: random.Random) -> RenderedMail:
    """Byte-level defects on a rendered, unsigned mail (worker process, before sign_mail)."""
    return mail


class DuplicateInjector:
    """Replaces some stream positions by a copy of a recent mail (main process, bounded memory).

    process() is called once per mail in stream order, after signing and before writing. It
    returns either the mail itself or a duplicate standing in for it, with duplicate_of set and
    Fault.DUPLICATE recorded.
    """

    def __init__(self, config: GeneratorConfig) -> None:
        self._config = config

    def process(self, mail: RenderedMail) -> RenderedMail:
        return mail

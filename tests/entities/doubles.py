"""An extraction for the entities phase that spawned workers can import (they do not see
monkeypatching): a text with KILL in it ends its worker process, one with RAISE makes it raise,
any other text goes to the real extract_entities."""

import os

from mailrobbe.entities.extract import extract_entities
from mailrobbe.entities.model import Found

KILL = "KILL-THE-WORKER"
RAISE = "RAISE-AN-ERROR"


def breaking_extract(text: str) -> list[Found]:
    if KILL in text:
        os._exit(3)
    if RAISE in text:
        raise ValueError("a broken pattern")
    return extract_entities(text)

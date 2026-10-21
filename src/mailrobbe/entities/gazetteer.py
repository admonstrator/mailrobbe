"""The gazetteers of the extraction (D80): plain UTF-8 lists shipped in data/.

One entry per line, written as it appears in texts; blank lines and lines starting with # are
left out, runs of spaces count as one. In the lists of places and organisations, "Name = Entity"
finds Name and counts it as Entity (Alternative für Deutschland = AfD). The lists are read once
per process (each worker process of the scan reads them once) and are part of the scan version
(model.scan_version), so an edited list scans every text again at the next import.

    first_names.txt             first names, German and frequent international ones (persons)
    common_words.txt            capitalised words that are no names: sentence starters, frequent
                                nouns, months, weekdays (persons, organisations, places)
    cities.txt                  towns: Germany, Austria, Switzerland, the world's capitals
    countries.txt               countries, in German and English
    ambiguous_places.txt        towns and countries whose name is a common word too; found only
                                after a postcode or after in, aus, nach, bei
    organizations.txt           parties, authorities, courts and media, matched as written
    organization_prefixes.txt   words that start an organisation's name before a capitalised
                                word (Stiftung X, Kreisverband X, Staatsanwaltschaft X)
"""

from functools import cache
from pathlib import Path

DATA_DIR = Path(__file__).with_name("data")


def data_files() -> tuple[Path, ...]:
    """Every list, in name order (for the scan version)."""
    return tuple(sorted(DATA_DIR.glob("*.txt")))


@cache
def entries(name: str) -> tuple[str, ...]:
    """The entries of one list in file order, each once."""
    lines = (DATA_DIR / name).read_text(encoding="utf-8").splitlines()
    kept = (" ".join(line.split()) for line in lines if not line.lstrip().startswith("#"))
    return tuple(dict.fromkeys(entry for entry in kept if entry))

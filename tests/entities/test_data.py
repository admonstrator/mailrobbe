"""The gazetteers of data/ (D80): they ship and load, agree with each other, find the names the
generator writes, and take part in the scan version."""

import shutil
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

from mailrobbe.db.models import ENTITY_VERSION
from mailrobbe.entities import model
from mailrobbe.entities.extract import extract_entities
from mailrobbe.entities.gazetteer import DATA_DIR, data_files, entries
from mailrobbe.entities.names import gazetteers
from mailrobbe.enums import EntityContext, EntityKind
from mailrobbe.generator import vocabulary as vocab
from mailrobbe.themes import load_entity_context

LISTS = (
    "ambiguous_places.txt",
    "cities.txt",
    "common_words.txt",
    "countries.txt",
    "first_names.txt",
    "organization_prefixes.txt",
    "organizations.txt",
)


def written(name: str) -> set[str]:
    """The names of a list as they stand in texts (the left side of "Name = Entity")."""
    return {entry.partition(" = ")[0] for entry in entries(name)}


def test_every_list_ships_and_loads() -> None:
    assert tuple(path.name for path in data_files()) == LISTS
    assert all(entries(name) for name in LISTS)
    assert all(path.read_bytes().decode("utf-8") for path in data_files())


@pytest.mark.parametrize("name", LISTS)
def test_no_list_names_an_entry_twice(name: str) -> None:
    lines = (DATA_DIR / name).read_text(encoding="utf-8").splitlines()
    kept = [" ".join(line.split()) for line in lines if line.strip() and line.lstrip()[0] != "#"]
    twice = [entry for entry, count in Counter(kept).items() if count > 1]
    assert twice == []


def test_ambiguous_places_are_places() -> None:
    assert written("ambiguous_places.txt") <= written("cities.txt") | written("countries.txt")


def test_no_first_name_is_a_common_word() -> None:
    assert written("first_names.txt") & written("common_words.txt") == set()


def test_every_short_form_of_an_organization_is_listed_itself() -> None:
    aliases = {entry.partition(" = ")[2] for entry in entries("organizations.txt")} - {""}
    assert aliases <= written("organizations.txt")


def generated_names() -> Iterator[tuple[str, str]]:
    """Every first name of the generator with a surname, each surname at least once."""
    first_names = vocab.FIRST_NAMES_DE + vocab.FIRST_NAMES_INTL
    surnames = vocab.SURNAMES_DE + vocab.SURNAMES_INTL
    for index in range(max(len(first_names), len(surnames))):
        yield first_names[index % len(first_names)], surnames[index % len(surnames)]


@pytest.mark.parametrize(("first", "surname"), list(generated_names()))
def test_the_generated_names_are_persons(first: str, surname: str) -> None:
    found = extract_entities(f"Gestern hat {first} {surname} angerufen.")
    persons = [(item.kind, item.label) for item in found if item.kind is EntityKind.PERSON]
    assert persons == [(EntityKind.PERSON, f"{first} {surname}")]


def test_the_generated_first_names_are_listed() -> None:
    names = gazetteers()
    for first in vocab.FIRST_NAMES_DE + vocab.FIRST_NAMES_INTL:
        assert all(part in names.first_names for part in first.split("-")), first


# The scan version ------------------------------------------------------------------------------


@pytest.fixture
def fresh_version() -> Iterator[None]:
    """scan_version computed anew in the test and again after it."""
    model.scan_version.cache_clear()
    yield
    model.scan_version.cache_clear()


@pytest.mark.usefixtures("fresh_version")
def test_the_scan_version_is_a_positive_31_bit_number_and_stable() -> None:
    version = model.scan_version()
    model.scan_version.cache_clear()
    assert model.scan_version() == version
    assert 0 < version < 2**31


@pytest.mark.usefixtures("fresh_version")
def test_the_scan_version_changes_with_a_context_word_list(monkeypatch: pytest.MonkeyPatch) -> None:
    before = model.scan_version()
    lists = dict(load_entity_context())
    lists[EntityContext.CASH] = (*lists[EntityContext.CASH], "Barscheck")
    monkeypatch.setattr(model, "load_entity_context", lambda: lists)
    model.scan_version.cache_clear()
    assert model.scan_version() != before


@pytest.mark.usefixtures("fresh_version")
def test_the_scan_version_changes_with_a_gazetteer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before = model.scan_version()
    copies = []
    for path in data_files():
        copies.append(Path(shutil.copy(path, tmp_path / path.name)))
    monkeypatch.setattr(model, "data_files", lambda: tuple(copies))
    model.scan_version.cache_clear()
    assert model.scan_version() == before  # the same lists elsewhere
    with (tmp_path / "first_names.txt").open("a", encoding="utf-8") as names:
        names.write("Quirin\n")
    model.scan_version.cache_clear()
    assert model.scan_version() != before


@pytest.mark.usefixtures("fresh_version")
def test_the_scan_version_changes_with_the_entity_version(monkeypatch: pytest.MonkeyPatch) -> None:
    before = model.scan_version()
    monkeypatch.setattr(model, "ENTITY_VERSION", ENTITY_VERSION + 1)
    model.scan_version.cache_clear()
    assert model.scan_version() != before

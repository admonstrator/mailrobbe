"""The keys alias suggestions compare (D30, D161) and the signs of their tiers (D160):
normalize_name, person_name, normalize_local_part, role_address, main_name, shared_mailbox,
made_from_name, registered_domain and reason."""

import pytest

from mailrobbe.enums import AliasTier
from mailrobbe.persons.suggestions import (
    ROLE_LOCAL_PARTS,
    ROLE_STEMS,
    address_keys,
    fold,
    made_from_name,
    main_name,
    normalize_local_part,
    normalize_name,
    person_name,
    reason,
    registered_domain,
    role_address,
    shared_mailbox,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Anna Schmidt", "anna schmidt"),
        ("ANNA SCHMIDT", "anna schmidt"),
        ("Schmidt, Anna", "anna schmidt"),  # Nachname, Vorname turned around
        ("Schmidt,Anna", "anna schmidt"),
        ("Müller-Lüdenscheidt, Hans-Jürgen", "hans-jürgen müller-lüdenscheidt"),
        ("  Anna \t  Schmidt  ", "anna schmidt"),  # surplus whitespace
        ("Anna\u00a0Schmidt", "anna schmidt"),  # a no-break space is whitespace too
        ('"Anna Schmidt"', "anna schmidt"),
        ("'Anna Schmidt'", "anna schmidt"),
        ("„Anna Schmidt“", "anna schmidt"),
        ("«Anna Schmidt»", "anna schmidt"),
        ("Dr. Anna Schmidt", "anna schmidt"),  # academic titles left out
        ("Schmidt, Dr. Anna", "anna schmidt"),
        ("Prof. Dr.-Ing. Anna Schmidt", "anna schmidt"),
        ("Anna Schmidt (Bergmann Bau)", "anna schmidt"),  # an addition in brackets left out
        ("Anna Schmidt [extern]", "anna schmidt"),
        ("Schmidt, Anna, Vertrieb", "schmidt, anna, vertrieb"),  # two commas: left as is
        ("Dr. Schmidt", None),  # one word without the title
        ("Anna", None),  # one word
        ("anna.schmidt", None),  # the local part as a name: one word
        ("Schmidt,", None),  # turned around, one word is left
        (",", None),
        ("", None),
        ("   ", None),
        ("anna@a.example", None),
        ("Anna Schmidt <anna@a.example>", None),
        ("Anna Schmidt via anna@a.example", None),
    ],
)
def test_normalize_name(name: str, expected: str | None) -> None:
    assert normalize_name(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Anna Schmidt", "anna schmidt"),
        ("Dr. Anna Schmidt", "anna schmidt"),
        ("Jo Li", "jo li"),  # two letters are enough
        ("Ö Schmidt", None),  # one word of one letter
        ("A. Schmidt", None),
        ("Anna Schmidt 2", None),  # digits
        ("Kandidat 17 Nord", None),
        ("Anna Schmidt via Verteiler", None),  # someone acting for someone else
        ("Anna Schmidt (via Doodle)", None),
        ("Anna Schmidt im Auftrag", None),
        ("i.A. Anna Schmidt", None),
        ("Zentralpostfach", None),  # one word
        ("Zentralpostfach Partei", None),  # functions and organisations
        ("Vorstand KV Nord", None),
        ("Geschäftsstelle Musterstadt", None),
        ("Kreisverband Musterstadt", None),
        ("Mitgliederservice Nord", None),
        ("Bergmann Bau GmbH", None),
        ("Freunde des Waldes e.V.", None),
        ("SPD Musterstadt", None),
        ("Redaktion Abendblatt", None),
        ("Bündnis Sportverein", None),
    ],
)
def test_person_name(name: str, expected: str | None) -> None:
    assert person_name(name) == expected


@pytest.mark.parametrize(
    ("local_part", "expected"),
    [
        ("anna.schmidt", "anna.schmidt"),
        ("Anna.Schmidt", "anna.schmidt"),
        ("anna.schmidt+newsletter", "anna.schmidt"),  # +suffix removed
        ("anna+a+b", "anna"),
        ("a.schmidt", "a.schmidt"),
        ("info", None),  # role addresses
        ("INFO", None),
        ("info+shop", None),
        ("noreply", None),
        ("no-reply", None),
        ("do-not-reply", None),
        ("mailer-daemon", None),
        ("Buchhaltung", None),
        ("zentralpostfach", None),  # German offices
        ("geschaeftsstelle", None),
        ("vorstand", None),
        ("kv.musterstadt", None),  # between separators
        ("kv-nord", None),
        ("musterstadt_ov", None),
        ("vorstand.nord", None),
        ("landesgeschaeftsstelle", None),  # inside a compound
        ("fraktionsbuero", None),
        ("mitgliederservice", None),
        ("zentralpostfach2", None),
        ("+newsletter", None),  # nothing left
        ("", None),
    ],
)
def test_normalize_local_part(local_part: str, expected: str | None) -> None:
    assert normalize_local_part(local_part) == expected
    assert role_address(local_part) is (expected is None and local_part.partition("+")[0] != "")


def test_role_words_are_folded() -> None:
    for word in (*ROLE_LOCAL_PARTS, *ROLE_STEMS):
        assert word == fold(word) and "+" not in word, word
    # Plain names are no functions, whatever words they contain.
    for word in ("kevin", "silvia", "amtmann", "vitali", "anja", "kai", "ute"):
        assert not role_address(f"{word}.schmidt"), word


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ({"Anna Schmidt": 3}, "anna schmidt"),
        ({"Anna Schmidt": 1, "Schmidt, Anna": 2}, "anna schmidt"),  # the same key
        ({"Anna Schmidt": 2, "Anna Maria Schmidt": 2}, "anna maria schmidt"),  # tie: smaller
        ({"Anna Schmidt": 2, "Info": 2}, "anna schmidt"),  # half is enough
        ({"Anna Schmidt": 2, "Info": 3}, None),
        # The parts of a name count as its use.
        ({"Felix Schmid": 2, "Felix": 3, "felix.schmid": 1, "Dr. Felix Schmid": 1}, "felix schmid"),
        ({"Zentralpostfach": 40, "Max Mustermann": 2}, None),
        ({"Anna": 3}, None),
        ({}, None),
    ],
)
def test_main_name(names: dict[str, int], expected: str | None) -> None:
    assert main_name(names) == expected


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ({"Anna Meier": 10, "Bert Meier": 8}, True),
        ({"Anna Meier": 40, "Bert Meier": 12, "Familie Meier": 4}, True),
        ({"Anna Meier": 40, "Bert Meier": 1}, False),  # once is no real share
        ({"Anna Meier": 40, "Bert Meier": 5}, False),  # under a fifth
        ({"Anna Meier": 10, "Anna Maria Meier": 8}, False),  # one person, with a middle name
        ({"Anna Meier": 10, "Info": 30}, False),
        ({"Zentralpostfach": 40, "Max Mustermann": 2}, False),
    ],
)
def test_shared_mailbox(names: dict[str, int], expected: bool) -> None:
    assert shared_mailbox(names) is expected


def test_the_keys_of_an_address() -> None:
    keys = address_keys
    assert keys("anna.schmidt@a.example", (("Anna Schmidt", 3),)) == (
        "anna.schmidt",
        "anna schmidt",
    )
    assert keys("as@a.example", (("Info", 3),)) == ("as", None)
    assert keys("zentralpostfach@partei.example", (("Max Mustermann", 2),)) is None
    assert keys("meier@a.example", (("Anna Meier", 10), ("Bert Meier", 8))) is None


@pytest.mark.parametrize(
    ("local_part", "name", "expected"),
    [
        ("max.mustermann", "max mustermann", True),
        ("maxmustermann", "max mustermann", True),
        ("mustermann.max", "max mustermann", True),
        ("mustermann_max", "max mustermann", True),
        ("m.mustermann", "max mustermann", True),
        ("mmustermann", "max mustermann", True),
        ("mustermann-m", "max mustermann", True),
        ("hans-juergen.mueller", "hans-jürgen müller", True),  # umlauts as mail systems write them
        ("hans-jurgen.muller", "hans-jürgen müller", True),
        ("hj.mueller", "hans-jürgen müller", True),
        ("hans.mueller", "hans-jürgen müller", True),
        ("anna.maria.schmidt", "anna maria schmidt", True),
        ("anna.schmidt", "anna maria schmidt", True),
        ("am.schmidt", "anna maria schmidt", True),
        ("mustermann", "max mustermann", False),  # the surname alone
        ("max", "max mustermann", False),
        ("max.mustermann2", "max mustermann", False),
        ("m.muster", "max mustermann", False),
        ("erika.mustermann", "max mustermann", False),
        ("max.mustermann", "max", False),
    ],
)
def test_made_from_name(local_part: str, name: str, expected: bool) -> None:
    assert made_from_name(local_part, name) is expected


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("partei.example", "partei.example"),
        ("kv-nord.partei.example", "partei.example"),
        ("mail.lv.partei.example", "partei.example"),
        ("Partei.Example.", "partei.example"),
        ("partei.co.uk", "partei.co.uk"),  # two-label public suffixes
        ("nord.partei.co.uk", "partei.co.uk"),
        ("verein.or.at", "verein.or.at"),
        ("localhost", "localhost"),
    ],
)
def test_registered_domain(domain: str, expected: str) -> None:
    assert registered_domain(domain) == expected


def test_reason() -> None:
    certain, uncertain = AliasTier.CERTAIN, AliasTier.UNCERTAIN
    assert reason("anna schmidt", "anna", certain) == "name_and_local_part"
    assert reason("anna schmidt", None, certain) == "name_fits_addresses"
    assert reason("anna schmidt", None, uncertain) == "name"
    assert reason(None, "anna", uncertain) == "local_part"

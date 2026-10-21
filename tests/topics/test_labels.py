"""The spellings of the terms (D141): the words of a text, and the spelling written most."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.topics import labels
from mailrobbe.topics.labels import Spellings, words


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rückmeldung bis Freitag, bitte!", ["Rückmeldung", "bis", "Freitag", "bitte"]),
        ("Spenden-Quittung", ["Spenden", "Quittung"]),  # the parts, as mail.tsv has them
        ("Bewerbung_Schäfer.pdf", ["Bewerbung", "Schäfer", "pdf"]),
        ("abc123 4711 Grüße3 x2y", []),  # numbers to the parser of mail.tsv
        ("Ab zu", []),  # too short
        ("a" * 41 + " " + "b" * 40, ["b" * 40]),  # a longer run is no word at all
        ("an kassenwart@verein.example schreiben", ["schreiben"]),
        ("(kassenwart@verein.example) <info@verein.example>, mailto:anna@x.example", []),
        ("siehe https://verein.example/spenden/quittung?jahr=2023 dort", ["siehe", "dort"]),
        ("<HTTP://Verein.example/Spenden> und www.spenden.example/liste", ["und"]),
        ("Grüße@all", []),  # a token with an @ goes as a whole
    ],
)
def test_words(text: str, expected: list[str]) -> None:
    assert words(text) == expected


def test_a_long_token_is_read_in_linear_time() -> None:
    # Without an @ or a link, the address pattern must not try every start inside a token.
    assert words("x" * 200_000 + " Spende") == ["Spende"]


TEXTS = [
    "Wir warten auf Ihre Rückmeldung. Danke für die Rückmeldung!",
    "Alle Rückmeldungen liegen vor.",
    "Spenden, Spenden, Spende und spenden.",
    "Die Kasse stimmt, die kasse nicht.",
    "kassenwart@verein.example und kassenwart@verein.example: Kassenwart",
    "Der Verein und die Vereine",  # verein is no term here
]
TERMS = {"ruckmeld", "spend", "kass", "kassenwart", "unbekannt"}


@pytest.mark.db
async def test_the_spelling_written_most_labels_a_term(db_session: AsyncSession) -> None:
    spellings = Spellings(TERMS)
    for text in TEXTS:
        spellings.add(text)
    assert spellings.pending > 0
    await spellings.stem(db_session)
    assert spellings.pending == 0
    assert spellings.labels() == {
        "ruckmeld": "Rückmeldung",  # the umlaut back; written twice, "Rückmeldungen" once
        "spend": "Spenden",  # twice, "Spende" and "spenden" once
        "kass": "Kasse",  # as often as "kasse": the first in Python string order
        "kassenwart": "Kassenwart",  # the addresses do not count
    }  # "unbekannt" was never written: the phase keeps its lexeme
    # Spellings of terms only: Rückmeldung, Rückmeldungen, Spenden, Spende, spenden, Kasse,
    # kasse, Kassenwart.
    assert spellings.spellings == 8


@pytest.mark.db
async def test_stemming_between_batches_counts_the_same(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    whole = Spellings(TERMS)
    for text in TEXTS:
        whole.add(text)
    await whole.stem(db_session)

    monkeypatch.setattr(labels, "STEM_BATCH", 3)
    stepwise = Spellings(TERMS)
    for text in TEXTS * 3:
        stepwise.add(text)
        await stepwise.stem(db_session)  # as when PENDING_SPELLINGS is reached after each mail
    assert stepwise.labels() == whole.labels()
    stepwise.add("Kasse Kasse")  # one more "Kasse" makes it the first by count alone
    stepwise.add("kasse")
    await stepwise.stem(db_session)
    assert stepwise.labels()["kass"] == "Kasse"
    tie = Spellings({"kass"})
    tie.add("kasse KASSE")
    await tie.stem(db_session)
    assert tie.labels() == {"kass": "KASSE"}  # capitals first, even all of them

"""The extraction of one text (D80 to D83): every kind, its normalisation, the precedence between
kinds, the contexts, determinism, limits and hostile input."""

import time
from decimal import Decimal

import pytest

from mailrobbe.entities.extract import extract_entities
from mailrobbe.entities.model import ENTITIES_PER_TEXT, KEY_LIMIT, NO_CONTEXT, Found
from mailrobbe.entities.money import parse_number
from mailrobbe.enums import EntityContext, EntityKind

K = EntityKind
CASH, DONATION, RECEIPT = EntityContext.CASH, EntityContext.DONATION, EntityContext.RECEIPT
IBAN = "DE89 3704 0044 0532 0130 00"
IBAN_KEY = "DE89370400440532013000"


def of_kind(text: str, kind: EntityKind) -> list[Found]:
    return [found for found in extract_entities(text) if found.kind is kind]


def keys(text: str, kind: EntityKind) -> list[str]:
    return [found.key for found in of_kind(text, kind)]


def one(text: str, kind: EntityKind) -> Found:
    found = of_kind(text, kind)
    assert len(found) == 1, found
    return found[0]


def kinds(text: str) -> set[EntityKind]:
    return {found.kind for found in extract_entities(text)}


# Amounts ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "key", "label"),
    [
        ("Betrag: 5.000,00 EUR", "EUR 5000.00", "5.000,00 EUR"),
        ("€ 1.234,56", "EUR 1234.56", "1.234,56 EUR"),
        ("1,234.56 USD", "USD 1234.56", "1.234,56 USD"),
        ("$1.5 million für die Kampagne", "USD 1500000.00", "1.500.000,00 USD"),
        ("2,5 Mio. Euro", "EUR 2500000.00", "2.500.000,00 EUR"),
        ("12 Mrd. EUR Schulden", "EUR 12000000000.00", "12.000.000.000,00 EUR"),
        ("300 T€ Umsatz", "EUR 300000.00", "300.000,00 EUR"),
        ("5000,- DM", "DEM 5000.00", "5.000,00 DEM"),
        ("100 D-Mark", "DEM 100.00", "100,00 DEM"),
        ("CHF 1'250.50", "CHF 1250.50", "1.250,50 CHF"),
        ("Fr. 50.–", "CHF 50.00", "50,00 CHF"),  # noqa: RUF001  (the Swiss dash)
        ("£20", "GBP 20.00", "20,00 GBP"),
        ("20 Pfund Sterling", "GBP 20.00", "20,00 GBP"),
        ("10.000 €", "EUR 10000.00", "10.000,00 EUR"),
        ("10.5 €", "EUR 10.50", "10,50 EUR"),
        ("1.000.000 EUR", "EUR 1000000.00", "1.000.000,00 EUR"),
        ("ab 49\nEUR im Monat", "EUR 49.00", "49,00 EUR"),
        ("USD5", "USD 5.00", "5,00 USD"),
        ("5 EURO", "EUR 5.00", "5,00 EUR"),
        ("12,345 Euro", "EUR 12345.00", "12.345,00 EUR"),
    ],
)
def test_amounts_in_german_and_english_notation(text: str, key: str, label: str) -> None:
    amount = one(text, K.AMOUNT)
    assert (amount.key, amount.label) == (key, label)
    assert amount.value == Decimal(key.split()[1])
    assert amount.currency == key.split()[0]


@pytest.mark.parametrize(
    "text",
    [
        "Die Euro-Zone und der Euro, Europa",
        "EUR 12.34.56",
        "3 Pfund Mehl",
        "Fr. 12.03.2021 Treffen",  # Friday, not francs
        "Seite 5 von 10",
        "EURO2024 und Eurovision 2024",
    ],
)
def test_no_amount_without_a_currency_and_a_number(text: str) -> None:
    assert of_kind(text, K.AMOUNT) == []


def test_a_currency_between_two_numbers_binds_the_one_that_looks_like_money() -> None:
    assert keys("Haushalt 2019 EUR 500,00", K.AMOUNT) == ["EUR 500.00"]
    assert keys("Zahlung am 12.03.2021 EUR 500", K.AMOUNT) == ["EUR 500.00"]
    assert keys("Zahlung am 12.03.2021 EUR 500", K.DATE) == ["2021-03-12"]


@pytest.mark.parametrize(
    ("number", "value"),
    [
        ("5.000", "5000"),
        ("5,000", "5000"),
        ("5.000,50", "5000.50"),
        ("5,000.50", "5000.50"),
        ("1.234.567", "1234567"),
        ("10,5", "10.5"),
        ("10.5", "10.5"),
        ("1'250.50", "1250.50"),
        ("12.34.56", None),
        ("1.23.456", None),
        ("1.000,00,00", None),
    ],
)
def test_parse_number_reads_both_notations(number: str, value: str | None) -> None:
    assert parse_number(number) == (None if value is None else Decimal(value))


# IBANs and accounts ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "key", "country"),
    [
        (f"IBAN {IBAN}", IBAN_KEY, "DE"),
        (f"IBAN: {IBAN_KEY}.", IBAN_KEY, "DE"),
        ("CH93 0076 2011 6238 5295 7", "CH9300762011623852957", "CH"),
        ("GB82 WEST 1234 5698 7654 32", "GB82WEST12345698765432", "GB"),
        ("AT61 1904 3002 3457 3201", "AT611904300234573201", "AT"),
    ],
)
def test_ibans_with_valid_check_digits(text: str, key: str, country: str) -> None:
    iban = one(text, K.IBAN)
    assert (iban.key, iban.detail) == (key, country)
    assert iban.label == " ".join(key[i : i + 4] for i in range(0, len(key), 4))


def test_a_wrong_check_digit_is_no_iban_and_nothing_else_either() -> None:
    assert extract_entities("IBAN DE88 3704 0044 0532 0130 00 falsch") == []
    assert extract_entities("XDE89370400440532013000") == []


@pytest.mark.parametrize(
    ("text", "key", "label"),
    [
        (
            "Konto 1234567 bei der Sparkasse, BLZ 100 200 30",
            "10020030/1234567",
            "Kto. 1234567 (BLZ 100 200 30)",
        ),
        (
            "Kto.-Nr. 987654321 BLZ 10020030",
            "10020030/987654321",
            "Kto. 987654321 (BLZ 100 200 30)",
        ),
        ("Kontonummer: 12345678", "12345678", "Kto. 12345678"),
    ],
)
def test_account_numbers_with_their_bank_code(text: str, key: str, label: str) -> None:
    account = one(text, K.ACCOUNT)
    assert (account.key, account.label) == (key, label)


def test_no_account_without_the_word_or_with_too_few_digits() -> None:
    assert of_kind("Konto 123 und Kontoauszug 123456 und 12345678", K.ACCOUNT) == []


# Names -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "key", "label"),
    [
        ("Sehr geehrter Herr Dr. Müller,", "herr müller", "Herr Müller"),
        ("Thomas Schmidt schrieb gestern.", "thomas schmidt", "Thomas Schmidt"),
        ("Frau Prof. Dr. Anna Weber kommt.", "anna weber", "Anna Weber"),
        ("Hans-Peter von der Leyen", "hans-peter von der leyen", "Hans-Peter von der Leyen"),
        ("Mit freundlichen Grüßen\nAnna Schmidt\nVorstand", "anna schmidt", "Anna Schmidt"),
        ("Herr Thomas sagt es.", "herr thomas", "Herr Thomas"),
        ("Mr John Smith", "john smith", "John Smith"),
        ("Mrs. Jane Doe", "jane doe", "Jane Doe"),
    ],
)
def test_persons(text: str, key: str, label: str) -> None:
    person = one(text, K.PERSON)
    assert (person.key, person.label) == (key, label)


@pytest.mark.parametrize(
    "text",
    [
        "Thomas allein",
        "Sehr geehrte Damen und Herren",
        "SCHMIDT, Thomas",
        "Schmidt, Thomas",
        "Herr der Ringe",
        "Treffen mit Thomas Bremen",  # a first name and a town: no person
    ],
)
def test_no_person(text: str) -> None:
    assert of_kind(text, K.PERSON) == []


@pytest.mark.parametrize(
    ("text", "key", "label"),
    [
        ("Die Muster GmbH liefert.", "muster gmbh", "Muster GmbH"),
        (
            "Verband der Automobilindustrie e. V.",
            "verband der automobilindustrie e.v.",
            "Verband der Automobilindustrie e. V.",
        ),
        (
            "Heidekraut Verlag GmbH & Co. KG",
            "heidekraut verlag gmbh & co. kg",
            "Heidekraut Verlag GmbH & Co. KG",
        ),
        (
            "Deutscher Fußball-Bund e.V.",
            "deutscher fussball-bund e.v.",
            "Deutscher Fußball-Bund e.V.",
        ),
        ("Acme Inc. in London", "acme inc.", "Acme Inc."),
        ("Die Alternative für Deutschland", "afd", "AfD"),
        ("der AfD-Kreisverband", "afd", "AfD"),
        ("Stiftung Warentest", "stiftung warentest", "Stiftung Warentest"),
        (
            "Amtsgericht Frankfurt am Main",
            "amtsgericht frankfurt am main",
            "Amtsgericht Frankfurt am Main",
        ),
        ("laut taz", "taz", "taz"),
        ("24.04.2013;Brunnenhof Bau KG;Zuwendung", "brunnenhof bau kg", "Brunnenhof Bau KG"),
        (
            "Dirk Beck;Rechnung Fuchsbau Textil GmbH;",
            "fuchsbau textil gmbh",
            "Fuchsbau Textil GmbH",
        ),
        ("Freie Wähler e.V.", "freie wähler e.v.", "Freie Wähler e.V."),
        (
            "Mitgliederliste Förderverein Sandkamp e.V.",
            "förderverein sandkamp e.v.",
            "Förderverein Sandkamp e.V.",
        ),
    ],
)
def test_organizations(text: str, key: str, label: str) -> None:
    organization = one(text, K.ORGANIZATION)
    assert (organization.key, organization.label) == (key, label)


def test_organizations_in_a_list_end_at_the_one_before() -> None:
    text = "Verband der Automobilindustrie e. V. und Gesellschaft für Informatik e.V."
    assert keys(text, K.ORGANIZATION) == [
        "verband der automobilindustrie e.v.",
        "gesellschaft für informatik e.v.",
    ]


def test_a_legal_form_alone_is_no_organization() -> None:
    assert of_kind("die AG und eine GmbH", K.ORGANIZATION) == []


@pytest.mark.parametrize(
    ("text", "key", "detail"),
    [
        ("in Berlin", "berlin", "city"),
        ("Frankfurt am Main", "frankfurt am main", "city"),
        ("Deutschland", "deutschland", "country"),
        ("Berlin-Mitte", "berlin", "city"),
        ("Wir fahren nach Essen.", "essen", "city"),
        ("45127 Essen", "essen", "city"),
        ("Musterweg 1\n12345 Kleinkleckersdorf", "kleinkleckersdorf", "city"),
    ],
)
def test_places(text: str, key: str, detail: str) -> None:
    place = one(text, K.PLACE)
    assert (place.key, place.detail) == (key, detail)


@pytest.mark.parametrize(
    "text",
    [
        "Das Essen war gut.",  # an ambiguous town only after a cue
        "55894 Schutzhandschuhe Plus 21,73",  # an article number, not a postcode
    ],
)
def test_no_place(text: str) -> None:
    assert of_kind(text, K.PLACE) == []


def test_an_organization_named_after_a_place_is_no_place() -> None:
    assert kinds("Stiftung Berlin") == {K.ORGANIZATION}


# Contact data ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "key", "label", "country"),
    [
        ("Tel. 030 1234567", "+49301234567", "+49 30 1234567", "DE"),
        ("Tel.: +49 (0)30 123456-78", "+493012345678", "+49 30 123456-78", "DE"),
        ("Fax: +41 44 668 18 00", "+41446681800", "+41 44 668 18 00", "CH"),
        ("Mobil 0171 1234567", "+491711234567", "+49 171 1234567", "DE"),
        ("Tel. +39 06 1234 5678", "+390612345678", "+39 06 1234 5678", "IT"),
        ("Call +44 20 7946 0958.", "+442079460958", "+44 20 7946 0958", "GB"),
    ],
)
def test_phone_numbers_in_e164(text: str, key: str, label: str, country: str) -> None:
    phone = one(text, K.PHONE)
    assert (phone.key, phone.label, phone.detail) == (key, label, country)


def test_no_phone_number_too_short_or_without_a_cue() -> None:
    assert of_kind("Tel. 12 und Bestellnummer +12 und 030 1234567", K.PHONE) == []


def test_email_addresses_lowercase_without_mailto_and_trailing_dot() -> None:
    text = "Info@Muster.DE oder mailto:a.b@c.de. Schreiben Sie an a@b.de."
    assert keys(text, K.EMAIL) == ["info@muster.de", "a.b@c.de", "a@b.de"]
    assert keys("a@b und user@localhost", K.EMAIL) == []


def test_urls_normalised_and_trimmed() -> None:
    first, second = of_kind("https://www.Muster.de/Kontakt/#top und www.muster.de", K.URL)
    assert (first.key, first.label, first.detail) == (
        "https://www.muster.de/Kontakt",
        "https://www.Muster.de/Kontakt/#top",
        "www.muster.de",
    )
    assert (second.key, second.label) == ("https://www.muster.de", "www.muster.de")
    text = "(https://example.org/x) und https://example.org/a_(b)"
    assert keys(text, K.URL) == ["https://example.org/x", "https://example.org/a_(b)"]


def test_domains_of_urls_and_addresses() -> None:
    domain = one("https://www.muster.de/a, info@muster.de", K.DOMAIN)
    assert (domain.key, domain.occurrences) == ("muster.de", 2)
    assert keys("a@mail.muster.co.uk", K.DOMAIN) == ["muster.co.uk"]
    assert keys("http://192.168.1.1/admin", K.DOMAIN) == []


def test_a_url_longer_than_the_key_limit_is_no_entity_and_hides_its_digits() -> None:
    url = "https://example.org/" + "a" * KEY_LIMIT + "/+49301234567"
    assert kinds(url) == {K.DOMAIN}


# Dates -----------------------------------------------------------------------------------------


def test_dates_in_every_notation_are_one_day() -> None:
    text = (
        "15.03.2019, 15.3.19, 15. März 2019, 15. Mär. 2019, 15 March 2019, "
        "March 15, 2019 and 2019-03-15"
    )
    date = one(text, K.DATE)
    assert (date.key, date.label, date.occurrences) == ("2019-03-15", "15.03.2019", 7)


@pytest.mark.parametrize(
    "text", ["1.2.3", "10.0.19041", "31.02.2020", "1.2.33", "15.03.1850", "15.03.2019.1"]
)
def test_no_date(text: str) -> None:
    assert of_kind(text, K.DATE) == []


def test_two_digit_years() -> None:
    assert keys("01.02.39 und 01.02.40", K.DATE) == ["2039-02-01", "1940-02-01"]


# Theme terms -----------------------------------------------------------------------------------


def test_theme_terms_whole_words_with_endings_and_phrases() -> None:
    text = "Umvolkung, „Großer Austausch“, der große Austausch, Tag X, Spenden in bar, NSU, nsu"
    terms = {found.key: found.detail for found in of_kind(text, K.TERM)}
    assert terms == {
        "rassismus:umvolkung": "rassismus",
        "rassismus:grosser austausch": "rassismus",  # case-folded
        "verfassungsfeindlichkeit:tag x": "verfassungsfeindlichkeit",
        "spenden:spende": "spenden",
        "spenden:in bar": "spenden",
        "extremismus:nsu": "extremismus",
    }


def test_a_term_inside_an_address_is_none() -> None:
    assert of_kind("spende@verein.example", K.TERM) == []


# Contexts --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "context"),
    [
        ("Die Spende von 5.000 EUR wurde bar übergeben.", CASH | DONATION),
        ("Dr. Müller hat 500 EUR gespendet.", DONATION),
        ("Am 3. Oktober kamen 200 EUR als Spende.", DONATION),
        ("Quittung über 50 EUR", RECEIPT),
        ("Wir haben 400 EUR in bar erhalten", CASH),
        ("Die Zuwendung (500 EUR) ist da.", DONATION),
        ("Donation of USD 300 in cash, receipt attached.", CASH | DONATION | RECEIPT),
        ("Die Spendeneinnahmen betragen 900 EUR.", DONATION),
        ("Die Spende kam an. Die Rechnung über 300 EUR ist offen.", NO_CONTEXT),
        ("Mitgliedsbeitrag 60 EUR", NO_CONTEXT),
        ("Spende: " + "x" * 300 + " 700 EUR", NO_CONTEXT),  # beyond the window
    ],
)
def test_contexts_of_amounts_in_their_sentence(text: str, context: EntityContext) -> None:
    assert one(text, K.AMOUNT).context == context


def test_contexts_of_ibans_and_accounts() -> None:
    assert one("Barzahlung auf das Konto 1234567", K.ACCOUNT).context == CASH
    assert one(f"Spenden bitte an IBAN {IBAN}", K.IBAN).context == DONATION


def test_a_mention_keeps_the_contexts_of_all_its_occurrences() -> None:
    text = "Spende: 100 EUR. Das ist viel.\n\nDie Quittung über 100 EUR folgt."
    amount = one(text, K.AMOUNT)
    assert (amount.context, amount.occurrences) == (DONATION | RECEIPT, 2)


def test_in_a_table_the_line_is_the_sentence() -> None:
    amounts = of_kind("Spende\t500 EUR\nMiete\t300 EUR", K.AMOUNT)
    assert [(found.key, found.context) for found in amounts] == [
        ("EUR 500.00", DONATION),
        ("EUR 300.00", NO_CONTEXT),
    ]
    csv = (
        "Datum,Zweck,IBAN\n01.01.2020,Spende,DE89370400440532013000\n"
        "02.01.2020,Miete,DE02120300000000202051"
    )
    assert [(found.key, found.context) for found in of_kind(csv, K.IBAN)] == [
        (IBAN_KEY, DONATION),
        ("DE02120300000000202051", NO_CONTEXT),
    ]


# Precedence, order, determinism ----------------------------------------------------------------


def test_one_span_gives_one_entity_of_the_most_specific_kind() -> None:
    assert kinds(f"IBAN {IBAN}") == {K.IBAN}
    assert kinds("Tel. +49 30 12345678") == {K.PHONE}
    assert kinds("https://example.org/2019-03-15/5000-EUR") == {K.URL, K.DOMAIN}
    assert kinds("5.000,00 EUR") == {K.AMOUNT}


def test_entities_come_by_first_position_and_count_their_occurrences() -> None:
    text = "Berlin, 15.03.2019. Thomas Schmidt aus Berlin zahlte 50 EUR. In Berlin."
    found = extract_entities(text)
    assert [(entity.kind, entity.key) for entity in found] == [
        (K.PLACE, "berlin"),
        (K.DATE, "2019-03-15"),
        (K.PERSON, "thomas schmidt"),
        (K.AMOUNT, "EUR 50.00"),
    ]
    assert found[0].occurrences == 3
    assert [entity.position for entity in found] == [0, 8, 20, 53]


def test_the_label_is_the_first_occurrence_as_written() -> None:
    assert one("www.muster.de und WWW.MUSTER.DE", K.URL).label == "www.muster.de"


def test_the_same_text_gives_the_same_entities() -> None:
    text = (
        "Herr Dr. Müller von der Muster GmbH aus 10115 Berlin überwies am 15.03.2019 eine "
        f"Spende von 5.000,00 EUR in bar (IBAN {IBAN}). Tel. +49 30 1234567, "
        "www.muster.de, info@muster.de. Umvolkung."
    )
    first = extract_entities(text)
    assert first == extract_entities(text)
    assert {found.kind for found in first} == set(EntityKind) - {K.ACCOUNT}


def test_empty_and_blank_texts() -> None:
    assert extract_entities("") == []
    assert extract_entities("\n") == []
    assert extract_entities(" \t\n ") == []


def test_at_most_entities_per_text() -> None:
    text = " ".join(f"user{index}@example.org" for index in range(ENTITIES_PER_TEXT + 500))
    found = extract_entities(text)
    assert len(found) == ENTITIES_PER_TEXT
    assert found[0].key == "user0@example.org"
    assert {found.kind for found in found} == {K.EMAIL, K.DOMAIN}


def test_an_english_text() -> None:
    text = (
        "Please transfer USD 1,500.00 to John Smith at Acme Inc. in London by March 15, 2019. "
        "Call +44 20 7946 0958."
    )
    assert [(found.kind, found.key) for found in extract_entities(text)] == [
        (K.AMOUNT, "USD 1500.00"),
        (K.PERSON, "john smith"),
        (K.ORGANIZATION, "acme inc."),
        (K.PLACE, "london"),
        (K.DATE, "2019-03-15"),
        (K.PHONE, "+442079460958"),
    ]


# Hostile input ---------------------------------------------------------------------------------

LENGTH = 200_000
HOSTILE = {
    "digits": "1" * LENGTH,
    "digit dots": "1." * (LENGTH // 2),
    "digit spaces": "1 " * (LENGTH // 2),
    "at signs": "a@" * (LENGTH // 2),
    "local parts": ("a" * 63 + "@") * (LENGTH // 64),
    "url": "http://" + "a" * LENGTH,
    "honorifics": "Herr " * (LENGTH // 5),
    "capitals": "A " * (LENGTH // 2),
    "first names": "Thomas " * (LENGTH // 7),
    "legal forms": "GmbH " * (LENGTH // 5),
    "currencies": "€1" * (LENGTH // 2),
    "separators": "\t;" * (LENGTH // 2),
    "csv": ",a" * (LENGTH // 2),
    "iban starts": "DE89 " * (LENGTH // 5),
    "phone cues": "Tel. " * (LENGTH // 5),
    "brackets": "(" * LENGTH,
    "hyphens": "Müller-" * (LENGTH // 7),
    "blank lines": "x.\n\n" * (LENGTH // 4),
    "months": "März " * (LENGTH // 5),
    "postcode towns": "\n12345 Abc" * (LENGTH // 10),
    "context words": "Spende " * (LENGTH // 7),
}


@pytest.mark.parametrize("text", HOSTILE.values(), ids=HOSTILE.keys())
def test_hostile_texts_take_linear_time(text: str) -> None:
    started = time.monotonic()
    extract_entities(text)
    assert time.monotonic() - started < 10  # about 2 s at most on a laptop

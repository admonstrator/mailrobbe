# ruff: noqa: RUF001  (typographic quotes, apostrophes and dashes in texts are meant)
"""Money: IBANs, account numbers and amounts (D81, D82).

Per kind, what is found and how it is normalised:

    iban      a country code, two check digits and the rest, compact or in groups of four, with
              the length of its country and ISO 7064 mod-97 check digits; key compact, label in
              groups of four, detail the country code. A string of the right shape that fails
              the check is claimed but no entity: no account, phone or date either.
    account   5 to 12 digits after Konto, Kontonummer, Kto. and the like, with the 8 digits after
              BLZ in the same line; key "blz/number" or the number, label "Kto. 1234567 (BLZ 100
              200 30)".
    amount    a number with a currency before or after it, in German or English notation, with
              Tsd., Mio., Mrd. and their words; key "EUR 5000.00", label "5.000,00 EUR", value
              and currency (D-Mark is DEM). A currency between two numbers binds the number that
              looks more like money ("2019 EUR 500,00" is 500 euros), or the one that is a
              number at all ("am 12.03.2021 EUR 500" is 500 euros).
"""

import re
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal

from mailrobbe.entities.occurrences import Occurrences
from mailrobbe.enums import EntityKind

# IBAN lengths by country (SWIFT IBAN registry).
IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22,
    "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "DO": 28,
    "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23,
    "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IQ": 23, "IS": 26,
    "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20,
    "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18,
    "NO": 15, "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24,
    "SC": 31, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "ST": 25, "SV": 28, "TL": 23, "TN": 24,
    "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}  # fmt: skip

_IBAN_START = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2})(\d{2})(?=[ ]?[A-Z0-9])")
_IBAN_CHAR = re.compile(r"[A-Z0-9]")


def find_ibans(found: Occurrences) -> None:
    text = found.text
    for match in _IBAN_START.finditer(text):
        country = match.group(1)
        length = IBAN_LENGTHS.get(country)
        if length is None or not found.free(match.start(), match.end()):
            continue
        end = _iban_end(text, match.end(), length - 4)
        if end is None:
            continue
        compact = text[match.start() : end].replace(" ", "")
        if _mod97(compact) == 1:
            label = " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))
            found.add(EntityKind.IBAN, compact, label, match.start(), end, detail=country)
        else:
            found.claim(match.start(), end)


def _iban_end(text: str, position: int, count: int) -> int | None:
    """The end of `count` IBAN characters from position, in groups of four separated by single
    spaces (or none); None when they are not there or more follow."""
    taken = 4  # the characters before position: country and check digits
    while count:
        if taken % 4 == 0 and text.startswith(" ", position):
            position += 1
        if position >= len(text) or not _IBAN_CHAR.match(text, position):
            return None
        position += 1
        taken += 1
        count -= 1
    if position < len(text) and (text[position].isalnum()):
        return None
    return position


def _mod97(iban: str) -> int:
    """ISO 7064 mod 97-10 of an IBAN: 1 when its check digits are right."""
    moved = iban[4:] + iban[:4]
    digits = "".join(str(int(char, 36)) for char in moved)
    return int(digits) % 97


_ACCOUNT = re.compile(
    r"(?=K)(?<![\w-])(?:Kontonummer|Kontonr\.|Konto-Nr\.|Kto\.-Nr\.|Kto\.?[ ]?Nr\.|Konto|Kto\.)"
    r"[ \t]*:?[ \t]*(?P<number>\d{5,12})(?![\d.,]?\d)"
)
_BLZ = re.compile(r"(?<![\w-])BLZ\.?[ \t]*:?[ \t]*(?P<code>\d(?: ?\d){7})(?! ?\d)")


def find_accounts(found: Occurrences) -> None:
    text = found.text
    for match in _ACCOUNT.finditer(text):
        start, end = match.span("number")
        if not found.free(start, end):
            continue
        number = match.group("number")
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", end)
        line_end = len(text) if line_end < 0 else line_end
        code = _BLZ.search(text, line_start, line_end)
        if code and found.free(*code.span("code")):
            digits = code.group("code").replace(" ", "")
            found.claim(*code.span("code"))
            key = f"{digits}/{number}"
            label = f"Kto. {number} (BLZ {digits[:3]} {digits[3:6]} {digits[6:]})"
        else:
            key, label = number, f"Kto. {number}"
        found.add(EntityKind.ACCOUNT, key, label, match.start(), end)


# Amounts ---------------------------------------------------------------------------------------

_SPACE = r"[ \t\u00a0]{0,2}\n?[ \t\u00a0]{0,2}"  # between number and currency: one line break
_NUMBER = r"\d(?:[\d.,'’\u00a0\u202f]{0,24}\d)?"
_DASH = r"[.,](?:--?|–)"  # 5000,- and 5.000,--
_MULTIPLIERS = {
    "Tsd.": 10**3, "Tsd": 10**3, "Tausend": 10**3, "thousand": 10**3,
    "Mio.": 10**6, "Mio": 10**6, "Mill.": 10**6, "Million": 10**6, "Millionen": 10**6,
    "million": 10**6,
    "Mrd.": 10**9, "Mrd": 10**9, "Milliarde": 10**9, "Milliarden": 10**9, "billion": 10**9,
    "bn": 10**9,
}  # fmt: skip
_MULTIPLIER = "|".join(re.escape(word) for word in sorted(_MULTIPLIERS, key=len, reverse=True))
# The currency signs, codes and words: currency, factor, and whether they may stand before and
# after the number.
_CURRENCIES: dict[str, tuple[str, int, bool, bool]] = {
    "T€": ("EUR", 1000, False, True),
    "TEUR": ("EUR", 1000, False, True),
    "€": ("EUR", 1, True, True),
    "EUR": ("EUR", 1, True, True),
    "Eur.": ("EUR", 1, False, True),
    "Euro": ("EUR", 1, True, True),
    "Euros": ("EUR", 1, False, True),
    "EURO": ("EUR", 1, True, True),
    "$": ("USD", 1, True, True),
    "US$": ("USD", 1, True, True),
    "USD": ("USD", 1, True, True),
    "US-Dollar": ("USD", 1, False, True),
    "Dollar": ("USD", 1, False, True),
    "Dollars": ("USD", 1, False, True),
    "dollars": ("USD", 1, False, True),
    "CHF": ("CHF", 1, True, True),
    "SFr.": ("CHF", 1, True, True),
    "sFr.": ("CHF", 1, True, True),
    "Fr.": ("CHF", 1, True, False),  # Frau and Freitag too: only directly before a number
    "Franken": ("CHF", 1, False, True),
    "£": ("GBP", 1, True, True),
    "GBP": ("GBP", 1, True, True),
    "Pfund Sterling": ("GBP", 1, False, True),  # Pfund alone is a weight more often
    "DM": ("DEM", 1, True, True),
    "D-Mark": ("DEM", 1, True, True),
}
_LETTER_AFTER = r"(?![^\W\d_])"
# A sign ending with a letter does not run on into a word (the lookahead), and one starting with
# a letter does not continue one: _currencies checks that, since a lookbehind at the start of the
# pattern would make the scan several times slower.
_CURRENCY = re.compile(
    "|".join(
        re.escape(sign) + (_LETTER_AFTER if sign[-1].isalpha() else "")
        for sign in sorted(_CURRENCIES, key=len, reverse=True)
    )
)
_BEFORE = re.compile(
    rf"(?<![\d.,'’])(?P<number>{_NUMBER})(?P<dash>{_DASH})?{_SPACE}"
    rf"(?:(?P<multiplier>{_MULTIPLIER}){_LETTER_AFTER}{_SPACE})?\Z"
)
_AFTER = re.compile(
    rf"[ \t\u00a0]{{0,2}}(?P<number>{_NUMBER})(?![\d])(?P<dash>{_DASH})?"
    rf"(?:{_SPACE}(?P<multiplier>{_MULTIPLIER}){_LETTER_AFTER})?"
)
_LOOK_BEFORE = 48  # characters searched before a currency for its number
_LARGEST = Decimal(10) ** 15
_CENT = Decimal("0.01")
_GERMAN = str.maketrans(",.", ".,")


def find_amounts(found: Occurrences) -> None:
    text = found.text
    for currency_match in _currencies(text):
        start, end = currency_match.span()
        if not found.free(start, end):
            continue
        currency, factor, before, after = _CURRENCIES[currency_match.group()]
        candidates: list[tuple[re.Match[str], int, int]] = []  # a number, the amount's span
        if after:  # the currency may follow its number
            number = _BEFORE.search(text, max(0, start - _LOOK_BEFORE), start)
            if number and found.free(number.start(), start) and not _named(number, start):
                candidates.append((number, number.start(), end))
        if before:
            number = _AFTER.match(text, end)
            if number and found.free(end, number.end()) and not _named(number, end):
                candidates.append((number, start, number.end()))
        valued = [
            (value, number, span)
            for number, *span in candidates
            if (value := _value(number, factor)) is not None
        ]
        if not valued:
            continue
        # The number that looks more like money; on a tie the one before the currency.
        value, _, span = max(valued, key=lambda item: _money_like(item[1]))
        label = f"{value:,.2f}".translate(_GERMAN) + f" {currency}"
        found.add(
            EntityKind.AMOUNT, f"{currency} {value:.2f}", label, *span,
            value=value, currency=currency,
        )  # fmt: skip


def _currencies(text: str) -> Iterator[re.Match[str]]:
    position = 0
    while (match := _CURRENCY.search(text, position)) is not None:
        start = match.start()
        if start and match.group()[0].isalpha() and text[start - 1].isalpha():
            position = start + 1  # inside a word: a shorter sign may start after it
            continue
        yield match
        position = match.end()


_CENTS = re.compile(r"[.,]\d\d\Z")


def _named(number: re.Match[str], currency_edge: int) -> bool:
    """A year written against the currency names something (EURO2024), it is no amount."""
    digits = number.group("number")
    touching = currency_edge in (number.start("number"), number.end("number"))
    return touching and len(digits) == 4 and digits.isdigit() and 1900 <= int(digits) <= 2099


def _money_like(match: re.Match[str]) -> int:
    """How much a number looks like an amount: cents or a dash 2, grouped 1, a year -1."""
    number = match.group("number")
    if match.group("dash") or _CENTS.search(number):
        return 2
    if not number.isdigit():
        return 1
    return -1 if len(number) == 4 and 1900 <= int(number) <= 2099 else 0


def _value(match: re.Match[str], factor: int) -> Decimal | None:
    number = parse_number(match.group("number"))
    if number is None:
        return None
    multiplier = match.group("multiplier")
    if multiplier:
        factor *= _MULTIPLIERS[multiplier]
    value = (number * factor).quantize(_CENT, ROUND_HALF_UP)
    return value if value < _LARGEST else None


_GROUPED = re.compile(r"\d{1,3}(?:[.,'’\u00a0\u202f]\d{3})+")


def parse_number(number: str) -> Decimal | None:
    """A number in German or English notation (D81): with both separators, the last one is the
    decimal separator; a single separator followed by exactly three digits groups thousands,
    otherwise it is the decimal separator; apostrophes and narrow spaces only group thousands.
    None for a number that fits none of these (12.34.56)."""
    marks = [char for char in number if char in ".,"]
    decimal_mark = None
    if len(set(marks)) == 2:
        decimal_mark = marks[-1]
        if marks.count(decimal_mark) > 1:
            return None
    elif len(marks) == 1:
        tail = number.rpartition(marks[0])[2]
        if not (len(tail) == 3 and tail.isdigit()):
            decimal_mark = marks[0]
    whole, fraction = number, ""
    if decimal_mark is not None:
        whole, _, fraction = number.rpartition(decimal_mark)
        if not (whole and fraction.isdigit()):
            return None
    if not whole.isdigit() and not _GROUPED.fullmatch(whole):
        return None
    digits = "".join(char for char in whole if char.isdigit())
    return Decimal(f"{digits}.{fraction or 0}")

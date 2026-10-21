"""What the generator writes into the archive is found (SPEC 3.6): its IBANs (valid check
digits, bank codes starting with 9) and amounts in the documents, the amounts and signature
phone numbers in the mails, each as a mention of the text it stands in."""

import re
from collections import defaultdict
from decimal import Decimal

import pytest

from tests.entities.conftest import rows

pytestmark = [pytest.mark.db, pytest.mark.slow]

IBAN = re.compile(r"(?<![\w])DE\d{2}(?: ?\d{4}){4} ?\d{2}(?!\d)")
GERMAN_AMOUNT = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})*,\d{2}) (?:€|EUR)")
ENGLISH_AMOUNT = re.compile(r"EUR (\d{1,3}(?:,\d{3})*\.\d{2})(?![\d])")
PHONE = re.compile(r"^(?:Tel\.|Phone) (\+49 \d+ \d+-\d{3})$", re.MULTILINE)


async def mentioned(url: str, source: str, kind: str) -> dict[int, set[str]]:
    """The keys of one kind each mail or document mentions."""
    column = "mail_id" if source == "mail" else "document_id"
    keys: dict[int, set[str]] = defaultdict(set)
    for owner, key in await rows(
        url,
        f"""SELECT m.{column}, e.key FROM {source}_entity m JOIN entity e ON e.id = m.entity_id
            WHERE e.kind = CAST(:kind AS entity_kind)""",
        kind=kind,
    ):
        keys[owner].add(key)
    return keys


async def document_texts(url: str) -> list[tuple[int, str]]:
    return [
        (document, text)
        for document, text in await rows(
            url, "SELECT id, extracted_text FROM document WHERE extracted_text IS NOT NULL"
        )
    ]


async def mail_texts(url: str) -> list[tuple[int, str]]:
    return [
        (mail, f"{subject or ''}\n{body or ''}")
        for mail, subject, body in await rows(url, "SELECT id, subject, body_text FROM mail")
    ]


def amount_key(written: str, german: bool) -> str:
    plain = written.replace(".", "").replace(",", ".") if german else written.replace(",", "")
    return f"EUR {Decimal(plain):.2f}"


async def test_every_generated_iban_is_found(scanned_database_url: str) -> None:
    found = await mentioned(scanned_database_url, "document", "iban")
    missing, checked = [], 0
    for document, text in await document_texts(scanned_database_url):
        for match in IBAN.finditer(text):
            iban = match.group().replace(" ", "")
            if iban[4] != "9":  # not one of the generator's
                continue
            checked += 1
            if iban not in found[document]:
                missing.append((document, iban))
    assert checked > 50
    assert missing == []


async def test_every_generated_amount_is_found(scanned_database_url: str) -> None:
    url = scanned_database_url
    checked, missing = 0, []
    for source, texts in (("document", await document_texts(url)), ("mail", await mail_texts(url))):
        found = await mentioned(url, source, "amount")
        for owner, text in texts:
            written = [(match, True) for match in GERMAN_AMOUNT.finditer(text)]
            written += [(match, False) for match in ENGLISH_AMOUNT.finditer(text)]
            for match, german in written:
                checked += 1
                key = amount_key(match.group(1), german)
                if key not in found[owner]:
                    missing.append((source, owner, match.group()))
    assert checked > 30
    assert missing == []


async def test_every_signature_phone_number_is_found(scanned_database_url: str) -> None:
    found = await mentioned(scanned_database_url, "mail", "phone")
    checked, missing = 0, []
    for mail, text in await mail_texts(scanned_database_url):
        for match in PHONE.finditer(text):
            checked += 1
            key = re.sub(r"[ -]", "", match.group(1))
            if key not in found[mail]:
                missing.append((mail, match.group(1)))
    assert checked > 50
    assert missing == []

"""Key records quoted in the archive's own texts (D103): the task search of `mailrobbe dkim-keys`.

Mails from a hoster ("Ihr DKIM-Eintrag"), zone files and configurations in attachments often
hold a key record. texts() finds the candidates through the full text indexes (mail.tsv,
document.tsv): the token dkim1 of v=DKIM1, or a token starting like the base64 of an RSA key
(MII..., MIGf... for 1024 bits, MIGJ... for a bare RSAPublicKey). find_records reads the records
out of a text: a v=DKIM1 record with p=, also split over several quoted strings and lines as
zone files write it, or a bare p=MI... . The length of an RSA key comes from its DER header, so
text after the key never sticks to it.

A key found counts only when it verifies a signature: signatures_to_test reads one signature of
each concerned name (every mail once), and the run stores a key that verifies one of them as
documented, referenced by the mail's permalink or the document page and dated by the mail
(store_find). The passage found is the lookup's answer.
"""

import asyncio
import base64
import binascii
import hashlib
import re
from collections import defaultdict
from collections.abc import AsyncIterator, Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from mailrobbe.db.models import TEXT_SEARCH_CONFIG, DkimResult, Document, Mail, MboxFile
from mailrobbe.dkim.keys.store import (
    CONCERNED,
    Evidence,
    find_lookup,
    of_key_names,
    save_evidence,
    save_lookup,
)
from mailrobbe.dkim.model import SignatureMaterial
from mailrobbe.dkim.verify import key_verifies, signature_material
from mailrobbe.enums import KeyLookupSource, KeyOrigin, LookupOutcome
from mailrobbe.mbox import read_message

# Tokens of the german configuration (mail.tsv, document.tsv): dkim1 from v=DKIM1, and the
# lowercase start of an RSA key's base64 (SubjectPublicKeyInfo MII.. or MIGf.., RSAPublicKey
# MII.. or MIGJ..)
TEXT_QUERY = "dkim1 | mii:* | migf:* | migj:*"
BATCH = 100  # texts per query and commit
RECORD_REACH = 300  # characters between the v=DKIM1 of a record and its p=
MAX_KEY_CHARS = 1500  # base64 of an RSA key of 8192 bits, with room for line breaks
ED25519_CHARS = 43  # 32 bytes in base64, without padding

_P_TAG = re.compile(r"(?<![A-Za-z0-9])p\s*=\s*")
_V_TAG = re.compile(r"v\s*=\s*DKIM1(?![A-Za-z0-9])", re.IGNORECASE)
_TAG = re.compile(r"(?<![A-Za-z0-9])([khs])\s*=\s*([A-Za-z0-9*:\s-]*?)\s*(?=[;\"]|$)")
# base64 of a key, with what may stand between its parts: whitespace and line breaks, and the
# quotes between the strings of a TXT record ("..." "...")
_BASE64 = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
_JOINS = frozenset(' \t\r\n"')


@dataclass(frozen=True, slots=True)
class FoundRecord:
    record: str  # v=DKIM1; k=...; p=..., with the h= and s= the text gives
    passage: str  # the record as it stands in the text, from v=DKIM1 or p= to the key's end


def find_records(text: str) -> list[FoundRecord]:
    """The DKIM key records quoted in a text, each once, in order."""
    found: dict[str, FoundRecord] = {}
    for match in _P_TAG.finditer(text):
        record = _record_at(text, match.start(), match.end())
        if record is not None and record.record not in found:
            found[record.record] = record
    return list(found.values())


def _record_at(text: str, tag: int, value: int) -> FoundRecord | None:
    """The record whose p= starts at `tag` and its value at `value`."""
    head = text[max(0, tag - RECORD_REACH) : tag]
    versions = list(_V_TAG.finditer(head))
    start = tag - len(head) + versions[-1].start() if versions else tag
    tags = {name.lower(): value.strip() for name, value in _TAG.findall(text[start:tag])}
    key_type = tags.pop("k", "rsa").lower()
    if not versions and not text.startswith("MI", value):
        return None  # a bare p= must look like the DER of an RSA key
    characters, positions = [], []
    for position in range(value, min(len(text), value + MAX_KEY_CHARS)):
        character = text[position]
        if character in _BASE64:
            characters.append(character)
            positions.append(position)
        elif character not in _JOINS:
            break
    length = _key_length(key_type, "".join(characters[:8]))
    if length is None or length > len(characters):
        return None
    key = "".join(characters[:length])
    key += "=" * (-len(key) % 4)
    end = positions[length - 1] + 1
    while text.startswith("=", end):
        end += 1
    extra = "".join(f"; {name}={tags[name]}" for name in ("h", "s") if tags.get(name))
    return FoundRecord(f"v=DKIM1; k={key_type}{extra}; p={key}", text[start:end])


def _key_length(key_type: str, start: str) -> int | None:
    """Base64 characters (without padding) of the key that starts with these 8 characters."""
    if key_type == "ed25519":
        return ED25519_CHARS
    if key_type != "rsa" or len(start) < 8:
        return None
    try:
        header = base64.b64decode(start)
    except binascii.Error:
        return None
    if header[0] != 0x30:  # an ASN.1 SEQUENCE: SubjectPublicKeyInfo or RSAPublicKey
        return None
    if header[1] < 0x80:
        size = 2 + header[1]
    elif 0x81 <= header[1] <= 0x83:
        octets = header[1] & 0x7F
        size = 2 + octets + int.from_bytes(header[2 : 2 + octets])
    else:
        return None
    return -(-size * 4 // 3)


# Reading the archive -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Text:
    """A mail text or an attachment text that may quote a key record."""

    reference: str  # /m/<mail sha256> or /anhaenge/<document id>
    details: dict[str, str]  # {"mail_sha256": ...} or {"document_sha256": ...}
    date: datetime | None  # the mail's date, a document's first mail
    text: str


async def count_texts(db: AsyncConnection) -> int:
    """How many texts texts() goes through."""
    query = func.to_tsquery(TEXT_SEARCH_CONFIG, TEXT_QUERY)
    mails = select(func.count()).where(Mail.tsv.op("@@")(query), Mail.is_duplicate_of.is_(None))
    documents = select(func.count()).where(Document.tsv.op("@@")(query))
    return (await db.scalar(mails) or 0) + (await db.scalar(documents) or 0)


async def texts(db: AsyncConnection) -> AsyncIterator[list[Text]]:
    """The mail texts (no duplicates) and attachment texts that may quote a key record, BATCH
    at a time; one query per batch, so the caller may write and commit between them."""
    query = func.to_tsquery(TEXT_SEARCH_CONFIG, TEXT_QUERY)
    last = 0
    while True:
        rows = (
            await db.execute(
                select(Mail.id, Mail.raw_sha256, Mail.date_utc, Mail.body_text)
                .where(Mail.tsv.op("@@")(query), Mail.is_duplicate_of.is_(None), Mail.id > last)
                .order_by(Mail.id)
                .limit(BATCH)
            )
        ).all()
        if rows:
            last = rows[-1].id
            yield [
                Text(f"/m/{sha256}", {"mail_sha256": sha256}, date, body or "")
                for _, sha256, date, body in rows
            ]
        if len(rows) < BATCH:
            break
    last = 0
    while True:
        documents = (
            await db.execute(
                select(Document.id, Document.sha256, Document.first_date, Document.extracted_text)
                .where(Document.tsv.op("@@")(query), Document.id > last)
                .order_by(Document.id)
                .limit(BATCH)
            )
        ).all()
        if documents:
            last = documents[-1].id
            yield [
                Text(
                    f"/anhaenge/{document_id}",
                    {"document_sha256": sha256} if sha256 else {},
                    date,
                    text or "",
                )
                for document_id, sha256, date, text in documents
            ]
        if len(documents) < BATCH:
            break


async def signatures_to_test(
    db: AsyncConnection, mbox_dir: Path, names: Collection[str] = ()
) -> list[SignatureMaterial]:
    """One signature of each concerned key name (or of these names), from mails that are no
    duplicates, the oldest first; every mail is read once."""
    where = [CONCERNED, Mail.is_duplicate_of.is_(None)]
    if names:
        where.append(of_key_names(names))
    rows = await db.execute(
        select(
            DkimResult.domain,
            DkimResult.selector,
            DkimResult.signature_index,
            Mail.id,
            MboxFile.path,
            Mail.byte_offset,
            Mail.byte_length,
            Mail.raw_sha256,
        )
        .join(Mail, Mail.id == DkimResult.mail_id)
        .join(MboxFile, MboxFile.id == Mail.mbox_file_id)
        .where(*where)
        .distinct(DkimResult.domain, DkimResult.selector)
        .order_by(
            DkimResult.domain,
            DkimResult.selector,
            DkimResult.signed_at.asc().nulls_last(),
            Mail.id,
        )
    )
    wanted: defaultdict[tuple[str, int, int, str], set[int]] = defaultdict(set)
    for _, _, index, _, path, offset, length, sha256 in rows:
        wanted[path, offset, length, sha256].add(index)
    return await asyncio.to_thread(_read_signatures, mbox_dir, wanted)


def _read_signatures(
    mbox_dir: Path, wanted: dict[tuple[str, int, int, str], set[int]]
) -> list[SignatureMaterial]:
    found = []
    for (path, offset, length, sha256), indexes in sorted(wanted.items()):
        try:
            raw = read_message(mbox_dir / path, offset, length)
        except (OSError, ValueError):
            continue
        if hashlib.sha256(raw).hexdigest() != sha256:
            continue
        found += [material for material in signature_material(raw) if material.index in indexes]
    return found


def fitting_names(record: str, signatures: Collection[SignatureMaterial]) -> list[str]:
    """The key names whose signature the key of `record` verifies, in name order."""
    return sorted({s.name for s in signatures if key_verifies(record, s)})


async def store_find(
    db: AsyncConnection, text: Text, found: FoundRecord, names: list[str]
) -> dict[int, str]:
    """Store a key found in a text for the names it verifies a signature of; the keys stored
    (id and name, one per name). The same passage of the same text found again adds no
    lookup."""
    raw = found.passage.encode("utf-8")
    domains = {key_name.partition("._domainkey.")[2] for key_name in names}
    lookup_id = await find_lookup(db, KeyLookupSource.ARCHIVE_TEXT, text.reference, raw)
    if lookup_id is None:
        lookup_id = await save_lookup(
            db,
            KeyLookupSource.ARCHIVE_TEXT,
            text.reference,
            LookupOutcome.FOUND,
            domain=domains.pop() if len(domains) == 1 else None,
            name=names[0] if len(names) == 1 else None,
            raw=raw,
            raw_type="text/plain; charset=utf-8",
            message=f"a key record quoted in {text.reference}",
        )
    evidence = Evidence(
        KeyOrigin.DOCUMENTED,
        observed_from=text.date,
        reference=text.reference,
        details=text.details,
    )
    stored = {}
    for name in names:
        key_id = await save_evidence(db, lookup_id, name, found.record, evidence)
        if key_id is not None:
            stored[key_id] = name
    return stored

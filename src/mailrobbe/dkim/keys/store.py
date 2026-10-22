"""dkim_key, dkim_key_lookup and dkim_key_evidence (D100, D101): the one place that writes them.

Every source goes the same way: save_lookup records the question and the answer unchanged (also
when nothing was found or the source failed), save_evidence stores a key found in that answer
and what the answer says about it. A key is one row per name and content (key_sha256), so the
same key from two sources is one row with two pieces of evidence, and its origin is the
strongest of them. keep_dns_keys keeps every key today's DNS gives (D106), so it still verifies
once the domain drops or replaces it; load_candidates hands the keys to the checker;
add_manual_key stores a key a person entered (D103). CONCERNED and of_key_names select
dkim_result rows; selector_summary counts what the dashboard card shows.

The functions take an AsyncSession or AsyncConnection, run in the caller's transaction and never
commit.
"""

import hashlib
import mimetypes
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import version
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    exists,
    false,
    func,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.api.schemas import SelectorSummary
from mailrobbe.db.models import DkimKey, DkimKeyEvidence, DkimKeyLookup, DkimResult, DnsCache
from mailrobbe.dkim.keys.identity import key_identity, split_key_name
from mailrobbe.dkim.model import FOUND_TTL, CandidateKey, DnsAnswer
from mailrobbe.enums import (
    KEY_ORIGIN_RANK,
    DkimReason,
    DkimStatus,
    DnsStatus,
    KeyLookupSource,
    KeyOrigin,
    LookupOutcome,
)

Executor = AsyncSession | AsyncConnection

TOOL_VERSION = version("mailrobbe")
DNS_RECORD_TYPE = "text/plain; charset=utf-8"  # raw_type of a DNS answer: the TXT record

# The dkim_result rows a key search works for, whose key name is "concerned": no key (no_key),
# or a failing signature with an intact body, as after a new key under the old name.
CONCERNED = or_(
    DkimResult.status == DkimStatus.NO_KEY,
    and_(
        DkimResult.status == DkimStatus.FAIL,
        DkimResult.reason == DkimReason.SIGNATURE_MISMATCH.value,
        DkimResult.body_hash_ok.is_(True),
    ),
)


# SQL conditions on dkim_result r for figures per key name (the API's selector pages too): a
# signature with a key name, on a mail that is no duplicate (an anti join with the few
# duplicates through ix_mail_is_duplicate_of reads no other mail row).
NAMED = "r.domain IS NOT NULL AND r.selector IS NOT NULL"
NOT_DUPLICATE = (
    "NOT EXISTS (SELECT FROM mail d WHERE d.id = r.mail_id AND d.is_duplicate_of IS NOT NULL)"
)


def of_key_names(names: Collection[str]) -> ColumnElement[bool]:
    """The dkim_result rows of these key names (through ix_dkim_result_domain_selector)."""
    pairs = []
    for name in sorted(set(names)):
        parts = split_key_name(name)
        if parts is not None:
            selector, domain = parts
            # d= is stored as written, so with a trailing dot when it had one
            pairs += [(selector, domain), (selector, domain + ".")]
    if not pairs:
        return false()
    return tuple_(DkimResult.selector, DkimResult.domain).in_(pairs)


_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')  # the strings of a TXT record in a zone file


async def save_lookup(
    db: Executor,
    source: KeyLookupSource,
    query: str,
    outcome: LookupOutcome,
    *,
    domain: str | None = None,
    name: str | None = None,
    raw: bytes | None = None,
    raw_type: str | None = None,
    raw_name: str | None = None,
    http_status: int | None = None,
    message: str | None = None,
    editor: str | None = None,
    asked_at: datetime | None = None,
) -> int:
    """Record one question to a source; its id. query never holds credentials.

    asked_at defaults to the database's current time; raw_sha256 is computed here.
    """
    values: dict[str, Any] = {
        "source": source.value,
        "query": query,
        "outcome": outcome.value,
        "domain": domain,
        "name": name,
        "raw": raw,
        "raw_sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
        "raw_type": raw_type,
        "raw_name": raw_name,
        "http_status": http_status,
        "message": message,
        "tool_version": TOOL_VERSION,
        "editor": editor,
    }
    if asked_at is not None:
        values["asked_at"] = asked_at
    lookup_id = await db.scalar(
        postgresql.insert(DkimKeyLookup).values(values).returning(DkimKeyLookup.id)
    )
    assert lookup_id is not None
    return int(lookup_id)


@dataclass(frozen=True, slots=True)
class Evidence:
    """What a lookup says about a key."""

    origin: KeyOrigin
    observed_from: datetime | None = None  # the source's own times, not when it was asked
    observed_to: datetime | None = None
    reference: str | None = None  # URL, permalink /m/<hash>, /anhaenge/<id>, file name
    note: str | None = None
    # Per source: reconstruction {"exponent", "hash", "signatures": [{"mail_id",
    # "signature_index", "mail_sha256"}]}; zkemail {"entry_id", "sources"}; archive_text
    # {"mail_sha256" or "document_sha256"}; dns {"name"}
    details: Mapping[str, Any] = field(default_factory=dict)
    editor: str | None = None


async def save_evidence(
    db: Executor, lookup_id: int, name: str, record: str, evidence: Evidence
) -> int | None:
    """Store the key of `record` for `name` with this evidence; the key's id.

    None when the record holds no usable key (malformed, revoked) or name is no DKIM key name.
    The key row is created on first sight and keeps its first record; its origin becomes the
    stronger of the stored one and this evidence's. Evidence from the same lookup for the same
    key is stored once.
    """
    parts = split_key_name(name)
    identity = key_identity(record)
    if parts is None or identity is None:
        return None
    selector, domain = parts
    key_name = f"{selector}._domainkey.{domain}"
    inserted = postgresql.insert(DkimKey).values(
        name=key_name,
        domain=domain,
        selector=selector,
        key_type=identity.key_type,
        bits=identity.bits,
        key_sha256=identity.key_sha256,
        record=record.strip(),
        origin=evidence.origin,
    )
    key_id = await db.scalar(
        inserted.on_conflict_do_nothing(index_elements=["name", "key_sha256"]).returning(DkimKey.id)
    )
    if key_id is None:
        key_id = await db.scalar(
            select(DkimKey.id).where(
                DkimKey.name == key_name, DkimKey.key_sha256 == identity.key_sha256
            )
        )
        assert key_id is not None
        # key_origin lists its values strongest first, so PostgreSQL orders them by strength.
        await db.execute(
            update(DkimKey)
            .where(DkimKey.id == key_id, DkimKey.origin > evidence.origin)
            .values(origin=evidence.origin)
        )
    await db.execute(
        postgresql.insert(DkimKeyEvidence)
        .values(
            key_id=key_id,
            lookup_id=lookup_id,
            origin=evidence.origin,
            observed_from=evidence.observed_from,
            observed_to=evidence.observed_to,
            reference=evidence.reference,
            note=evidence.note,
            details=dict(evidence.details),
            editor=evidence.editor,
        )
        .on_conflict_do_nothing(index_elements=["key_id", "lookup_id"])
    )
    return int(key_id)


async def keep_dns_keys(db: Executor, answers: Iterable[DnsAnswer]) -> None:
    """Keep the key of every found answer (D106): a key of origin dns, its lookup the record
    unchanged (source dns, asked when DNS answered), its evidence the first and the last time
    Mailrobbe saw it there. A key once kept stays when DNS later answers not found, an error or
    another key, so the mails it verified still verify (the checker tries it after DNS). The
    same answer again only moves the last time on. Answers without a usable key are left out.
    """
    for answer in answers:
        if answer.status is not DnsStatus.FOUND or answer.record is None:
            continue
        parts = split_key_name(answer.name)
        if parts is None or key_identity(answer.record) is None:
            continue
        raw = answer.record.encode("utf-8")
        lookup_id = await find_lookup(db, KeyLookupSource.DNS, answer.name, raw)
        if lookup_id is None:
            lookup_id = await save_lookup(
                db,
                KeyLookupSource.DNS,
                answer.name,
                LookupOutcome.FOUND,
                domain=parts[1],
                name=answer.name,
                raw=raw,
                raw_type=DNS_RECORD_TYPE,
                message="the DNS answer of the name, kept",
                asked_at=answer.fetched_at,
            )
        seen = Evidence(
            KeyOrigin.DNS,
            observed_from=answer.fetched_at,
            observed_to=answer.fetched_at,
            details={"name": answer.name},
        )
        key_id = await save_evidence(db, lookup_id, answer.name, answer.record, seen)
        assert key_id is not None  # name and record were checked above
        await db.execute(
            update(DkimKeyEvidence)
            .where(
                DkimKeyEvidence.key_id == key_id,
                DkimKeyEvidence.lookup_id == lookup_id,
                DkimKeyEvidence.origin == KeyOrigin.DNS,
            )
            .values(
                observed_from=func.least(DkimKeyEvidence.observed_from, answer.fetched_at),
                observed_to=func.greatest(DkimKeyEvidence.observed_to, answer.fetched_at),
            )
        )


async def keep_cached_keys(db: Executor) -> None:
    """keep_dns_keys for the found dns_cache rows not kept yet, as those of runs before D106;
    one anti join finds them, so a run start costs nothing once every key is kept."""
    kept = (
        select(DkimKeyLookup.id)
        .join(DkimKeyEvidence, DkimKeyEvidence.lookup_id == DkimKeyLookup.id)
        .where(
            DkimKeyLookup.source == KeyLookupSource.DNS.value,
            DkimKeyLookup.query == DnsCache.name,
            DkimKeyLookup.raw_sha256
            == func.encode(func.sha256(func.convert_to(DnsCache.record, "UTF8")), "hex"),
            DkimKeyEvidence.origin == KeyOrigin.DNS,
        )
    )
    rows = await db.execute(
        select(DnsCache.name, DnsCache.record, DnsCache.fetched_at)
        .where(
            DnsCache.status == DnsStatus.FOUND,
            DnsCache.record.is_not(None),
            ~exists(kept),
        )
        .order_by(DnsCache.name)
    )
    await keep_dns_keys(
        db,
        [
            DnsAnswer(name, DnsStatus.FOUND, record, fetched_at, FOUND_TTL)
            for name, record, fetched_at in rows
        ],
    )


async def load_candidates(db: Executor) -> dict[str, tuple[CandidateKey, ...]]:
    """Every key that may verify signatures (not factorable), by name, strongest origin first,
    then oldest first. Read once per run, like the DNS cache (D11)."""
    rows = await db.execute(
        select(DkimKey.id, DkimKey.name, DkimKey.origin, DkimKey.record)
        .where(DkimKey.factorable.is_(False))
        .order_by(DkimKey.name, DkimKey.id)
    )
    found: dict[str, list[CandidateKey]] = {}
    for key_id, name, origin, record in rows:
        found.setdefault(name, []).append(CandidateKey(key_id, KeyOrigin(origin), record))
    return {
        name: tuple(sorted(keys, key=lambda key: KEY_ORIGIN_RANK[key.origin]))
        for name, keys in found.items()
    }


async def find_lookup(db: Executor, source: KeyLookupSource, query: str, raw: bytes) -> int | None:
    """An earlier lookup with the same source, query and answer, so a run that finds the same
    answer again (a quoted record, today's DNS) adds evidence to it instead of a new lookup."""
    lookup_id = await db.scalar(
        select(func.min(DkimKeyLookup.id)).where(
            DkimKeyLookup.source == source.value,
            DkimKeyLookup.query == query,
            DkimKeyLookup.raw_sha256 == hashlib.sha256(raw).hexdigest(),
        )
    )
    return None if lookup_id is None else int(lookup_id)


class KeyRejected(ValueError):
    """A manual key without a DKIM key name or without a usable key (the API's invalid_key)."""


def manual_record(text: str) -> str | None:
    """The key record in what a person entered; None when it holds no usable key.

    Accepted: the TXT record, also as the quoted strings a zone file splits it into (joined
    without a separator, as DNS does), or only the p= value of an RSA or Ed25519 key.
    """
    strings = _QUOTED.findall(text)
    record = "".join(strings) if strings else text.strip()
    bare = re.sub(r"\s+", "", record)  # a p= value copied over several lines
    for form in (record, f"v=DKIM1; k=rsa; p={bare}", f"v=DKIM1; k=ed25519; p={bare}"):
        if key_identity(form) is not None:
            return form
    return None


async def add_manual_key(
    db: Executor,
    name: str,
    record: str,
    *,
    reference: str,
    note: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    file_name: str | None = None,
    file_bytes: bytes | None = None,
    file_type: str | None = None,
    editor: str | None = None,
) -> int:
    """Store a key a person found elsewhere (D103); its key id. Raises KeyRejected.

    The lookup (source manual, query the key name) keeps the evidence file unchanged as its
    answer, or the text entered when there is no file; the evidence is documented. The check of
    the name's mails is the caller's (the task check of `mailrobbe dkim-keys`).
    """
    parts = split_key_name(name)
    if parts is None:
        raise KeyRejected(f"not a DKIM key name ('<selector>._domainkey.<domain>'): {name!r}")
    usable = manual_record(record)
    if usable is None:
        raise KeyRejected("the record holds no usable DKIM key")
    selector, domain = parts
    key_name = f"{selector}._domainkey.{domain}"
    if file_bytes is None:
        raw, raw_type = record.encode("utf-8"), "text/plain; charset=utf-8"
    else:
        guessed, _ = mimetypes.guess_type(file_name or "")
        raw, raw_type = file_bytes, file_type or guessed or "application/octet-stream"
    lookup_id = await save_lookup(
        db,
        KeyLookupSource.MANUAL,
        key_name,
        LookupOutcome.FOUND,
        domain=domain,
        name=key_name,
        raw=raw,
        raw_type=raw_type,
        raw_name=file_name if file_bytes is not None else None,
        message="entered with a reference",
        editor=editor,
    )
    evidence = Evidence(
        KeyOrigin.DOCUMENTED,
        observed_from=observed_from,
        observed_to=observed_to,
        reference=reference,
        note=note or None,
        editor=editor,
    )
    key_id = await save_evidence(db, lookup_id, key_name, usable, evidence)
    assert key_id is not None  # name and record were checked above
    return key_id


_ORIGIN_COUNTS = "".join(
    f", count(*) FILTER (WHERE r.key_origin = '{origin}') AS origin_{origin}"
    for origin in KeyOrigin
)
_ORIGIN_SUMS = "".join(f", COALESCE(sum(origin_{o}), 0) AS origin_{o}" for o in KeyOrigin)
_SUMMARY_NAMES = text(f"""
    WITH names AS (
        SELECT count(*) FILTER (WHERE r.status = 'no_key') AS no_key,
               count(*) FILTER (WHERE r.algorithm LIKE 'rsa-%') AS rsa_signatures,
               count(*) FILTER (WHERE r.key_id IS NOT NULL) AS resolved
               {_ORIGIN_COUNTS}
        FROM dkim_result r
        WHERE {NAMED} AND {NOT_DUPLICATE}
        GROUP BY r.domain, r.selector
    )
    SELECT count(*) FILTER (WHERE no_key > 0) AS names_missing,
           count(*) FILTER (WHERE no_key > 0 AND rsa_signatures >= 2) AS reconstructable,
           count(*) FILTER (WHERE resolved > 0) AS names_resolved
           {_ORIGIN_SUMS}
    FROM names
""")
# Mails by status through ix_mail_dkim_sort, less the duplicates through ix_mail_is_duplicate_of.
_SUMMARY_MAILS = text("""
    SELECT (SELECT count(*) FROM mail WHERE dkim_status = 'no_key')
           - (SELECT count(*) FROM mail
              WHERE is_duplicate_of IS NOT NULL AND dkim_status = 'no_key') AS no_key,
           (SELECT count(*) FROM mail WHERE dkim_status = 'consistent')
           - (SELECT count(*) FROM mail
              WHERE is_duplicate_of IS NOT NULL AND dkim_status = 'consistent') AS consistent
""")


async def selector_summary(db: Executor) -> SelectorSummary:
    """The figures of the dashboard card "Gelöschte Selektoren" (and `mailrobbe dkim-keys
    status`), live, over the mails that are no duplicates: one scan of dkim_result grouped by
    key name, the mails through the indexes on mail.dkim_status and is_duplicate_of."""
    names = (await db.execute(_SUMMARY_NAMES)).one()
    mails = (await db.execute(_SUMMARY_MAILS)).one()
    keys = await _counts(db, select(DkimKey.origin, func.count()).group_by(DkimKey.origin))
    factorable = await db.scalar(select(func.count()).where(DkimKey.factorable.is_(True)))
    lookups = await _counts(
        db, select(DkimKeyLookup.source, func.count()).group_by(DkimKeyLookup.source)
    )
    return SelectorSummary(
        names_missing=names.names_missing,
        mails_missing=mails.no_key,
        reconstructable=names.reconstructable,
        names_resolved=names.names_resolved,
        mails_consistent=mails.consistent,
        keys={origin: keys.get(origin, 0) for origin in KeyOrigin},
        factorable=factorable or 0,
        signatures={origin: getattr(names, f"origin_{origin}") for origin in KeyOrigin},
        lookups={source: lookups.get(source.value, 0) for source in KeyLookupSource},
        # a search's, not when DNS gave a key that was kept (D106)
        last_lookup_at=await db.scalar(
            select(func.max(DkimKeyLookup.asked_at)).where(
                DkimKeyLookup.source != KeyLookupSource.DNS.value
            )
        ),
    )


async def _counts(db: Executor, statement: Select[Any, int]) -> dict[Any, int]:
    """A grouped count as {group: count}."""
    return {group: count for group, count in await db.execute(statement)}

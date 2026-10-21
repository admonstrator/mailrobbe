"""Small hand-built archives for the persons tests, and the person tables read back by address.

Tests name persons by their address: ids depend on the order in which the store creates them.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.enums import DkimStatus
from mailrobbe.importer.model import ParsedAddress, ParsedMail
from mailrobbe.importer.store import Batch, Store
from tests.importer.doubles import (
    FakeVerdict,
    add_mbox_file,
    fetch,
    make_mail,
    make_record,
    message,
)

Entry = tuple[ParsedMail, DkimStatus | None]


def mail(
    sender: str,
    *,
    to: Sequence[str] = (),
    cc: Sequence[str] = (),
    bcc: Sequence[str] = (),
    date: datetime | None = None,
    dkim: str | None = None,
    message_id: str | None = None,
) -> Entry:
    """A mail and its DKIM status; addresses are "anna@a.example" or "Anna <anna@a.example>"."""
    parsed = make_mail(
        message_id=message_id,
        subject="Mail",
        date_utc=date,
        sender=(_address(sender),),
        to=tuple(map(_address, to)),
        cc=tuple(map(_address, cc)),
        bcc=tuple(map(_address, bcc)),
    )
    return parsed, None if dkim is None else DkimStatus(dkim)


async def store(session: AsyncSession, entries: Sequence[Entry]) -> list[int]:
    """Store the mails in a new MBOX file, in this order; returns their ids."""
    (files,) = await fetch(session, "SELECT count(*) FROM mbox_file")
    file_id = await add_mbox_file(session, f"{files[0]}.mbox")
    batch = Batch()
    offset = 0
    for index, (parsed, status) in enumerate(entries):
        record = make_record(offset, message(index))
        batch.add(record, parsed, None if status is None else FakeVerdict(status))
        offset += record.byte_length
    await Store().write(session, file_id, batch)
    rows = await fetch(
        session, "SELECT id FROM mail WHERE mbox_file_id = :id ORDER BY byte_offset", id=file_id
    )
    return [mail_id for (mail_id,) in rows]


async def ids(session: AsyncSession) -> dict[str, int]:
    """Person id by address."""
    return dict(await fetch(session, "SELECT canonical_email, id FROM person"))


async def stats(session: AsyncSession) -> dict[str, tuple[Any, ...]]:
    """person_stats by root address: sent, received, cc_only, contacts, first and last date,
    DKIM share."""
    rows = await fetch(
        session,
        "SELECT p.canonical_email, s.sent, s.received, s.cc_only, s.contacts, s.first_date, "
        "s.last_date, s.dkim_pass_ratio FROM person_stats s JOIN person p ON p.id = s.person_id",
    )
    return {row[0]: row[1:] for row in rows}


async def years(session: AsyncSession) -> dict[tuple[str, int], tuple[int, int]]:
    """person_year by root address and year: sent, received."""
    rows = await fetch(
        session,
        "SELECT p.canonical_email, y.year, y.sent, y.received "
        "FROM person_year y JOIN person p ON p.id = y.person_id",
    )
    return {(email, year): (sent, received) for email, year, sent, received in rows}


async def suggestions(session: AsyncSession) -> dict[tuple[str, str], tuple[str | None, ...]]:
    """alias_suggestion by the addresses of both roots, in alphabetical order: name, local part."""
    rows = await fetch(
        session,
        "SELECT a.canonical_email, b.canonical_email, s.same_name, s.same_local_part "
        "FROM alias_suggestion s JOIN person a ON a.id = s.person_a "
        "JOIN person b ON b.id = s.person_b",
    )
    return {(min(a, b), max(a, b)): (name, local_part) for a, b, name, local_part in rows}


async def tiers(session: AsyncSession) -> dict[tuple[str, str], str]:
    """The tier of each alias_suggestion (D160), by the addresses of both roots as above."""
    rows = await fetch(
        session,
        "SELECT a.canonical_email, b.canonical_email, s.tier::text "
        "FROM alias_suggestion s JOIN person a ON a.id = s.person_a "
        "JOIN person b ON b.id = s.person_b",
    )
    return {(min(a, b), max(a, b)): tier for a, b, tier in rows}


async def snapshot(session: AsyncSession) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of the tables a merge refreshes, sorted: the edges and the persons tables."""
    return {
        table: sorted(await fetch(session, f"SELECT * FROM {table}"))
        for table in ("edge", "edge_year", "person_stats", "person_year", "alias_suggestion")
    }


async def row_versions(session: AsyncSession) -> dict[str, list[tuple[str, str]]]:
    """Where each row of those tables is stored and which transaction wrote it."""
    return {
        table: sorted(await fetch(session, f"SELECT ctid::text, xmin::text FROM {table}"))
        for table in ("person_stats", "person_year", "alias_suggestion")
    }


def _address(value: str) -> ParsedAddress:
    if "<" not in value:
        return ParsedAddress(value)
    name, _, email = value.partition("<")
    return ParsedAddress(email.rstrip(">"), name.strip())

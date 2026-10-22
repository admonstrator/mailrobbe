"""A small hand-made archive for the hide rules: senders with aliases, domains with subdomains,
a mailing list, an automated sender, and subjects holding LIKE wildcards. Each mail's raw_sha256
is its name, so matches read back as names."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class M:
    sender: str  # address
    subject: str | None
    day: int  # of March 2024
    list_id: str | None = None
    automated: bool = False
    dkim: str | None = "pass"


# address -> the address of the person it is merged into, or None for a root
PERSONS = {
    "news@newsletter.example": None,
    "info@mail.newsletter.example": None,
    "info@xnewsletter.example": None,
    "anna@a.example": None,
    "anna.alt@b.example": "anna@a.example",
    "bert@a_b.example": None,
    "bert@mail.axb.example": None,
    "noreply@system.test": None,
}
# a second address of the news sender's person row (person_email), as an import may store it
EXTRA_ADDRESS = ("n@newsletter.example", "news@newsletter.example")

ARCHIVE = {
    "news1": M("news@newsletter.example", "Wochenrückblick 12", 1, "news.newsletter.example"),
    "news2": M("news@newsletter.example", "Re: WOCHENRÜCKBLICK 13", 2, "news.newsletter.example"),
    "sub": M("info@mail.newsletter.example", "Angebot", 3, dkim="no_key"),
    "other": M("info@xnewsletter.example", "Angebot 100%", 4, dkim=None),
    "anna": M("anna@a.example", "Rat_Sitzung am Montag", 5),
    "alias": M("anna.alt@b.example", "Spende 10% bar", 6, dkim="fail"),
    "council": M("anna@a.example", "Ratssitzung", 7),
    "bert": M("bert@a_b.example", "Termin", 8),
    "bert2": M("bert@mail.axb.example", "Termin", 9),
    "bot": M("noreply@system.test", "Rechtshinweis", 10, automated=True, dkim="unsigned"),
}


async def insert_archive(
    session: AsyncSession, mails: dict[str, M] = ARCHIVE, offset: int = 0
) -> dict[str, int]:
    """The persons (once) and the mails into a new file; the mails' ids by name."""
    if offset == 0:
        for address in PERSONS:
            await session.execute(
                text("INSERT INTO person (canonical_email, domain) VALUES (:email, :domain)"),
                {"email": address, "domain": address.partition("@")[2]},
            )
        await session.execute(
            text("""INSERT INTO person_email (email, person_id)
                SELECT canonical_email, id FROM person""")
        )
        extra, owner = EXTRA_ADDRESS
        await session.execute(
            text("""INSERT INTO person_email (email, person_id)
                SELECT :extra, id FROM person WHERE canonical_email = :owner"""),
            {"extra": extra, "owner": owner},
        )
        for address, root in PERSONS.items():
            if root is not None:
                await merge(session, address, root)
    file_id = await session.scalar(
        text("INSERT INTO mbox_file (path, size_bytes) VALUES (:path, 0) RETURNING id"),
        {"path": f"file-{offset}.mbox"},
    )
    ids = {}
    for index, (name, mail) in enumerate(mails.items()):
        ids[name] = await session.scalar(
            text("""
                INSERT INTO mail (mbox_file_id, byte_offset, byte_length, raw_sha256, subject,
                    date_utc, list_id, automated, dkim_status)
                VALUES (:file, :offset, 100, :name, :subject, :date, :list_id, :automated,
                    CAST(:dkim AS dkim_status))
                RETURNING id
            """),
            {
                "file": file_id,
                "offset": index * 100,
                "name": name,
                "subject": mail.subject,
                "date": datetime(2024, 3, mail.day, 12, tzinfo=UTC),
                "list_id": mail.list_id,
                "automated": mail.automated,
                "dkim": mail.dkim,
            },
        )
        await session.execute(
            text("""
                INSERT INTO participation (mail_id, person_id, role)
                SELECT :mail, id, 'from' FROM person WHERE canonical_email = :sender
            """),
            {"mail": ids[name], "sender": mail.sender},
        )
    return ids


async def merge(session: AsyncSession, address: str, root: str) -> None:
    """The person of address merged into the person of root, as persons.merge leaves them."""
    await session.execute(
        text("""
            UPDATE person SET merged_into = (SELECT id FROM person WHERE canonical_email = :root)
            WHERE canonical_email = :address
        """),
        {"address": address, "root": root},
    )


async def person_id(session: AsyncSession, address: str) -> int:
    found = await session.scalar(
        text("SELECT id FROM person WHERE canonical_email = :email"), {"email": address}
    )
    assert isinstance(found, int)
    return found

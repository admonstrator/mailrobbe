"""passwords.order (D235): the passwords offered to a locked document, nearest tier first, each in
its nearest tier only, with the finding of that tier, those with a finding after the tried-until
id, capped; on rows written in SQL."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.passwords import order
from mailrobbe.passwords.order import OrderedCandidate, ordered_candidates

pytestmark = pytest.mark.db

DAY0 = datetime(2024, 3, 1, 10, tzinfo=UTC)
DOCUMENT = 1  # the locked document: carried by mail 10, beside document 2
PERSONS = {1: "anna@a.example", 2: "bert@b.example", 3: "carl@c.example", 4: "dora@d.example"}
# id: sender, recipient, days after DAY0, thread
MAILS = {
    10: (1, 2, 0, 10),  # carries the document
    11: (3, 4, 100, 10),  # the same thread, other persons, much later
    12: (2, 3, 29, None),  # shares Bert, 29 days later
    13: (4, 1, -30, None),  # shares Anna, 30 days before
    14: (1, 2, 31, None),  # the same persons, 31 days later: beyond
    15: (3, 4, 0, None),  # the same day, nobody in common
    16: (3, 4, 0, None),  # carries document 3, opened before
}
# id, value
PASSWORDS = {
    1: "manuell",
    2: "imMail",
    3: "imThread",
    4: "kontakt29",
    5: "kontakt30",
    6: "zuSpaet",
    7: "fremd",
    8: "anhang",
    9: "geoeffnet",
    10: "ohneFund",
    11: "ohneEditor",
}
# id: password, mail, document, editor
FINDINGS = {
    1: (1, None, None, "Aaron"),  # typed in by hand ...
    2: (1, 15, None, None),  # ... and found far away too
    3: (2, 11, None, None),  # in the thread, before ...
    4: (2, 10, None, None),  # ... the carrying mail
    5: (2, 12, None, None),
    6: (3, 11, None, None),
    7: (4, 12, None, None),
    8: (5, 13, None, None),
    9: (6, 14, None, None),
    10: (7, 15, None, None),
    11: (8, None, 2, None),  # in the text of a document beside it
    12: (11, None, None, None),  # typed in without an editor name (D54)
}
EXPECTED = [
    OrderedCandidate(1, "manuell", "manual", 1),
    OrderedCandidate(11, "ohneEditor", "manual", 12),
    OrderedCandidate(2, "imMail", "mail", 4),
    OrderedCandidate(3, "imThread", "thread", 6),
    OrderedCandidate(4, "kontakt29", "contacts", 7),
    OrderedCandidate(5, "kontakt30", "contacts", 8),
    OrderedCandidate(8, "anhang", "attachments", 11),
    OrderedCandidate(9, "geoeffnet", "opened", None),
    OrderedCandidate(6, "zuSpaet", "archive", 9),
    OrderedCandidate(7, "fremd", "archive", 10),
    OrderedCandidate(10, "ohneFund", "archive", None),
]


async def _write(session: AsyncSession) -> None:
    async def run(sql: str, **params: object) -> None:
        await session.execute(text(sql), params)

    await run("INSERT INTO mbox_file (id, path, size_bytes) VALUES (1, 'a.mbox', 100000)")
    for person_id, address in PERSONS.items():
        await run(
            "INSERT INTO person (id, canonical_email, domain) OVERRIDING SYSTEM VALUE "
            "VALUES (:id, :address, :domain)",
            id=person_id,
            address=address,
            domain=address.partition("@")[2],
        )
    for mail_id, (sender, recipient, days, thread) in MAILS.items():
        await run(
            "INSERT INTO mail (id, mbox_file_id, byte_offset, byte_length, raw_sha256, date_utc, "
            "thread_id) OVERRIDING SYSTEM VALUE VALUES (:id, 1, :offset, 100, :sha, :date, "
            ":thread)",
            id=mail_id,
            offset=mail_id * 100,
            sha=f"sha-{mail_id}",
            date=DAY0 + timedelta(days=days),
            thread=thread,
        )
        for person, role in ((sender, "from"), (recipient, "to")):
            await run(
                "INSERT INTO participation (mail_id, person_id, role) "
                "VALUES (:mail, :person, CAST(:role AS participation_role))",
                mail=mail_id,
                person=person,
                role=role,
            )
    await run(
        "INSERT INTO document (id, sha256, mime_type, size_bytes, text_status) "
        "OVERRIDING SYSTEM VALUE VALUES (1, 'gesperrt', 'application/pdf', 100, 'encrypted'), "
        "(2, 'daneben', 'text/plain', 100, 'text'), "
        "(3, 'geoeffnet', 'application/pdf', 100, 'text')"
    )
    for mail_id, position, document in ((10, 0, 1), (10, 1, 2), (16, 0, 3)):
        await attach(session, mail_id, position, document)
    for password_id, value in PASSWORDS.items():
        await run(
            "INSERT INTO password (id, value) OVERRIDING SYSTEM VALUE VALUES (:id, :value)",
            id=password_id,
            value=value,
        )
    for finding_id, (password, place, document_id, editor) in FINDINGS.items():
        await run(
            "INSERT INTO password_finding (id, password_id, mail_id, document_id, editor) "
            "OVERRIDING SYSTEM VALUE VALUES (:id, :password, :mail, :document, :editor)",
            id=finding_id,
            password=password,
            mail=place,
            document=document_id,
            editor=editor,
        )
    await run(
        "INSERT INTO document_password (document_id, password_id, tier) VALUES (3, 9, 'archive')"
    )


async def attach(session: AsyncSession, mail_id: int, position: int, document: int) -> None:
    await session.execute(
        text(
            "INSERT INTO attachment (mail_id, mime_type, size_bytes, position, document_id) "
            "VALUES (:mail, 'application/pdf', 100, :position, :document)"
        ),
        {"mail": mail_id, "position": position, "document": document},
    )


@pytest.fixture
async def session(db_session: AsyncSession) -> AsyncSession:
    await _write(db_session)
    return db_session


async def test_nearest_tier_first_each_password_once(session: AsyncSession) -> None:
    found = await ordered_candidates(session, DOCUMENT, after_id=0)
    assert found == EXPECTED
    assert order.values(found) == [candidate.value for candidate in EXPECTED]


async def test_only_passwords_with_a_finding_after_the_tried_until_id(
    session: AsyncSession,
) -> None:
    found = await ordered_candidates(session, DOCUMENT, after_id=5)
    assert found == [c for c in EXPECTED if c.password_id in {3, 4, 5, 6, 7, 8, 11}]
    assert await ordered_candidates(session, DOCUMENT, after_id=12) == []


async def test_a_tried_password_found_at_a_new_place_comes_again(session: AsyncSession) -> None:
    """ "fremd" was offered from the archive; written now in the carrying mail, it is near."""
    await session.execute(
        text(
            "INSERT INTO password_finding (id, password_id, mail_id) OVERRIDING SYSTEM VALUE "
            "VALUES (13, 7, 10)"
        )
    )
    found = await ordered_candidates(session, DOCUMENT, after_id=12)
    assert found == [OrderedCandidate(7, "fremd", "mail", 13)]


async def test_contacts_within_30_days_of_any_carrying_mail(session: AsyncSession) -> None:
    """A second carrier 60 days later widens the window: 31 days after the first is inside."""
    await session.execute(
        text(
            "INSERT INTO mail (id, mbox_file_id, byte_offset, byte_length, raw_sha256, date_utc) "
            "OVERRIDING SYSTEM VALUE VALUES (17, 1, 1700, 100, 'sha-17', :date)"
        ),
        {"date": DAY0 + timedelta(days=60)},
    )
    await session.execute(
        text("INSERT INTO participation (mail_id, person_id, role) VALUES (17, 3, 'from')")
    )
    await attach(session, 17, 0, DOCUMENT)
    tiers = {c.value: c.tier for c in await ordered_candidates(session, DOCUMENT, after_id=0)}
    assert tiers["zuSpaet"] == "contacts"
    assert tiers["fremd"] == "contacts"  # mail 17 is from Carl, who wrote mail 15
    assert tiers["kontakt30"] == "contacts"


async def test_attachments_of_every_near_mail(session: AsyncSession) -> None:
    """A document attached to mail 12 (Bert, 29 days later) holds "fremd": tier attachments."""
    await session.execute(
        text(
            "INSERT INTO document (id, sha256, mime_type, size_bytes, text_status) "
            "OVERRIDING SYSTEM VALUE VALUES (4, 'kontaktanhang', 'text/plain', 100, 'text')"
        )
    )
    await attach(session, 12, 0, 4)
    await session.execute(
        text(
            "INSERT INTO password_finding (id, password_id, document_id) OVERRIDING SYSTEM VALUE "
            "VALUES (13, 7, 4)"
        )
    )
    found = {c.value: c for c in await ordered_candidates(session, DOCUMENT, after_id=0)}
    assert found["fremd"] == OrderedCandidate(7, "fremd", "attachments", 13)


async def test_the_tiers_are_those_of_the_document(session: AsyncSession) -> None:
    """Document 3, carried by mail 16 alone (Carl to Dora, no thread): Carl and Dora wrote mails
    12, 13 and 15 within 30 days, mail 11 too late; the password that opened it is tier opened."""
    found = await ordered_candidates(session, 3, after_id=0)
    assert [(c.password_id, c.tier) for c in found] == [
        (1, "manual"),
        (11, "manual"),
        (2, "contacts"),
        (4, "contacts"),
        (5, "contacts"),
        (7, "contacts"),
        (9, "opened"),
        (3, "archive"),
        (6, "archive"),
        (8, "archive"),
        (10, "archive"),
    ]


async def test_the_list_is_capped(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(order, "MAX_CANDIDATES", 3)
    assert await ordered_candidates(session, DOCUMENT, after_id=0) == EXPECTED[:3]

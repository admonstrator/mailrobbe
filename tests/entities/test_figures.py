"""The figures of the entities (D85), computed again in Python from the mention rows of the
scanned archive: mails that are no duplicates, a document counting for every mail carrying it,
documents, first and last date."""

from collections import defaultdict
from datetime import datetime

import pytest

from mailrobbe.entities.figures import FiguresRefresh, refresh_entity_figures
from tests.entities.conftest import execute, rows, sessions, value

pytestmark = [pytest.mark.db, pytest.mark.slow]

Figures = tuple[int, int, datetime | None, datetime | None]


async def expected_figures(url: str) -> tuple[dict[int, Figures], dict[str, bool]]:
    """The figures of every entity from the mention rows, and which special cases the archive
    has (so that the comparison means something)."""
    mails = {mail: (duplicate, date) for mail, duplicate, date in await rows(
        url, "SELECT id, is_duplicate_of, date_utc FROM mail"
    )}  # fmt: skip
    carried: dict[int, set[int]] = defaultdict(set)
    for mail, document in await rows(
        url, "SELECT mail_id, document_id FROM attachment WHERE document_id IS NOT NULL"
    ):
        carried[document].add(mail)
    own: dict[int, set[int]] = defaultdict(set)
    attached: dict[int, set[int]] = defaultdict(set)
    documents: dict[int, set[int]] = defaultdict(set)
    for entity, mail in await rows(url, "SELECT entity_id, mail_id FROM mail_entity"):
        own[entity].add(mail)
    for entity, document in await rows(url, "SELECT entity_id, document_id FROM document_entity"):
        documents[entity].add(document)
        attached[entity] |= carried[document]
    figures: dict[int, Figures] = {}
    for (entity,) in await rows(url, "SELECT id FROM entity"):
        dates = [
            mails[mail][1] for mail in own[entity] | attached[entity] if mails[mail][0] is None
        ]
        figures[entity] = (len(dates), len(documents[entity]), min(dates, default=None),
                           max(dates, default=None))  # fmt: skip
    cases = {
        "a document in several mails": any(len(mails) > 1 for mails in carried.values()),
        "an entity in a mail's text and its attachment": any(
            own[entity] & attached[entity] for entity in figures
        ),
        "an entity mentioned by a duplicate": any(
            mails[mail][0] is not None for entity in figures for mail in own[entity]
        ),
        "an entity only in documents": any(
            documents[entity] and not own[entity] for entity in figures
        ),
    }
    return figures, cases


async def stored_figures(url: str) -> dict[int, Figures]:
    return {
        entity: (mails, documents, first, last)
        for entity, mails, documents, first, last in await rows(
            url, "SELECT id, mails, documents, first_date, last_date FROM entity"
        )
    }


async def test_the_figures_are_those_of_the_mentions(scanned_database_url: str) -> None:
    expected, cases = await expected_figures(scanned_database_url)
    assert cases == dict.fromkeys(cases, True)
    assert await stored_figures(scanned_database_url) == expected
    assert await value(scanned_database_url, "SELECT count(*) FROM entity WHERE mails = 0") == sum(
        1 for figures in expected.values() if figures[0] == 0
    )


async def test_a_second_refresh_changes_nothing(scanned_database_url: str) -> None:
    async with sessions(scanned_database_url) as sessionmaker, sessionmaker() as session:
        refreshed = await refresh_entity_figures(session)
        await session.rollback()
    assert refreshed == FiguresRefresh(updated=0, deleted=0)


async def test_a_mail_marked_as_duplicate_no_longer_counts(scanned_url: str) -> None:
    url = scanned_url
    [(entity, mail, other)] = await rows(
        url,
        """SELECT m.entity_id, m.mail_id, (SELECT min(id) FROM mail WHERE id <> m.mail_id)
           FROM mail_entity m JOIN entity e ON e.id = m.entity_id
           JOIN mail ON mail.id = m.mail_id
           WHERE e.mails = 2 AND mail.is_duplicate_of IS NULL
             AND NOT EXISTS (SELECT 1 FROM mail d WHERE d.is_duplicate_of = m.mail_id)
           ORDER BY m.entity_id, m.mail_id LIMIT 1""",
    )
    await execute(
        url, "UPDATE mail SET is_duplicate_of = :other WHERE id = :id", other=other, id=mail
    )
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        refreshed = await refresh_entity_figures(session)
    assert refreshed.deleted == 0 and refreshed.updated >= 1
    assert await value(url, "SELECT mails FROM entity WHERE id = :id", id=entity) == 1
    expected, _ = await expected_figures(url)
    assert await stored_figures(url) == expected

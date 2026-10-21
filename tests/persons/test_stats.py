"""person_stats and person_year (D29) on small hand-built archives."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import aggregates
from mailrobbe.importer.finalize import finalize
from mailrobbe.persons.merge import merge_persons
from mailrobbe.persons.stats import refresh_person_stats
from tests.importer.doubles import fetch
from tests.persons.helpers import ids, mail, row_versions, snapshot, stats, store, years

pytestmark = pytest.mark.db

ANNA, ANNE, BERT = "anna@a.example", "anne@a.example", "bert@b.example"
CARL, DORA, ERIK = "carl@c.example", "dora@d.example", "erik@e.example"


def _day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, tzinfo=UTC)


async def test_sent_received_and_only_cc_follow_the_roles(db_session: AsyncSession) -> None:
    await store(
        db_session,
        [
            mail(ANNA, to=[BERT], cc=[CARL], bcc=[DORA], date=_day(2020, 1, 1)),
            mail(ANNA, to=[ANNA], date=_day(2020, 2, 1)),  # to herself: sent, not received
            mail(CARL, to=[BERT], cc=[BERT, DORA], date=_day(2020, 3, 1)),  # Bert: To and Cc
            mail(BERT, cc=[CARL], bcc=[CARL], date=_day(2020, 4, 1)),  # Carl: Cc and Bcc
        ],
    )
    await finalize(db_session)

    figures = {email: row[:3] for email, row in (await stats(db_session)).items()}
    assert figures == {  # sent, received, only Cc
        ANNA: (2, 0, 0),
        BERT: (1, 2, 0),
        CARL: (1, 2, 1),
        DORA: (0, 2, 1),
    }
    # contacts: the edges to Bert, Carl and Dora (D36)
    assert (await stats(db_session))[ANNA][3:6] == (3, _day(2020, 1, 1), _day(2020, 2, 1))
    assert await years(db_session) == {
        (ANNA, 2020): (2, 0),
        (BERT, 2020): (1, 2),
        (CARL, 2020): (1, 2),
        (DORA, 2020): (0, 2),
    }


async def test_duplicates_count_nowhere(db_session: AsyncSession) -> None:
    await store(
        db_session,
        [
            mail(ANNA, to=[BERT], date=_day(2021, 5, 1), message_id="<1@a>", dkim="pass"),
            # the same Message-ID and subject: a duplicate (D16), here with one more recipient
            mail(ANNA, to=[BERT, ERIK], date=_day(2021, 5, 1), message_id="<1@a>", dkim="fail"),
        ],
    )
    await finalize(db_session)

    assert await stats(db_session) == {
        ANNA: (1, 0, 0, 1, _day(2021, 5, 1), _day(2021, 5, 1), 1.0),
        BERT: (0, 1, 0, 1, _day(2021, 5, 1), _day(2021, 5, 1), None),
        ERIK: (0, 0, 0, 0, None, None, None),  # a root whose mails are all duplicates
    }
    assert await years(db_session) == {(ANNA, 2021): (1, 0), (BERT, 2021): (0, 1)}


async def test_mails_without_a_date_count_in_the_totals_only(db_session: AsyncSession) -> None:
    await store(db_session, [mail(ANNA, to=[BERT], date=_day(2019, 5, 1)), mail(BERT, to=[ANNA])])
    await finalize(db_session)

    figures = await stats(db_session)
    assert figures[ANNA][:2] == (1, 1)
    assert figures[ANNA][4:6] == (_day(2019, 5, 1), _day(2019, 5, 1))
    assert await years(db_session) == {(ANNA, 2019): (1, 0), (BERT, 2019): (0, 1)}


async def test_years_are_utc_years_whatever_the_session_time_zone(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(text("SET LOCAL TimeZone = 'Pacific/Kiritimati'"))  # UTC+14
    east = timezone(timedelta(hours=2))
    await store(
        db_session,
        [
            mail(ANNA, to=[BERT], date=datetime(2020, 12, 31, 23, 30, tzinfo=UTC)),
            mail(ANNA, to=[BERT], date=datetime(2021, 1, 1, 0, 30, tzinfo=east)),  # 2020 in UTC
            mail(ANNA, to=[BERT], date=datetime(2021, 1, 1, 0, 30, tzinfo=UTC)),
        ],
    )
    await refresh_person_stats(db_session)

    assert await years(db_session) == {
        (ANNA, 2020): (2, 0),
        (ANNA, 2021): (1, 0),
        (BERT, 2020): (0, 2),
        (BERT, 2021): (0, 1),
    }


async def test_dkim_share_is_pass_among_the_checked_sent_mails(db_session: AsyncSession) -> None:
    await store(
        db_session,
        [
            mail(ANNA, to=[BERT], dkim="pass"),
            mail(ANNA, to=[BERT], dkim="pass"),
            mail(ANNA, to=[BERT], dkim="fail"),
            mail(ANNA, to=[BERT], dkim="unsigned"),  # checked: counts against the share
            mail(ANNA, to=[BERT]),  # not checked yet: left out
            mail(BERT, to=[ANNA]),
            mail(CARL, to=[ANNA], dkim="pass"),
        ],
    )
    await refresh_person_stats(db_session)

    shares = {email: row[6] for email, row in (await stats(db_session)).items()}
    assert shares == {ANNA: 0.5, BERT: None, CARL: 1.0}


async def test_a_mail_counts_once_per_root(db_session: AsyncSession) -> None:
    await store(
        db_session,
        [
            mail(ANNA, to=[ANNE], date=_day(2022, 1, 1)),  # from one address to another of hers
            mail(BERT, to=[ANNA], cc=[ANNE], date=_day(2022, 2, 1)),  # in To with one: not only Cc
            mail(BERT, cc=[ANNA, ANNE], date=_day(2022, 3, 1)),  # in Cc with both: only Cc
            mail(BERT, to=[ANNE], date=_day(2022, 4, 1)),
        ],
    )
    person = await ids(db_session)
    await refresh_person_stats(db_session)
    await merge_persons(db_session, person[ANNA], [person[ANNE]])

    merged = await snapshot(db_session)
    assert (await stats(db_session))[ANNA][:3] == (1, 3, 1)
    assert ANNE not in await stats(db_session)  # an alias has no figures of its own
    assert await years(db_session) == {(ANNA, 2022): (1, 3), (BERT, 2022): (3, 0)}
    await refresh_person_stats(db_session)
    assert await snapshot(db_session) == merged


async def test_contacts_are_the_edges_of_the_person(db_session: AsyncSession) -> None:
    await store(db_session, [mail(ANNA, to=[BERT, CARL]), mail(DORA, to=[ERIK])])
    person = await ids(db_session)
    edges = [(ANNA, BERT), (ANNA, CARL), (BERT, CARL)]
    await db_session.execute(
        text("INSERT INTO edge (person_a, person_b) VALUES (:a, :b)"),
        [{"a": min(person[x], person[y]), "b": max(person[x], person[y])} for x, y in edges],
    )
    await refresh_person_stats(db_session)

    contacts = {email: row[3] for email, row in (await stats(db_session)).items()}
    assert contacts == {ANNA: 2, BERT: 2, CARL: 2, DORA: 0, ERIK: 0}


async def test_rows_that_no_longer_hold_are_deleted(db_session: AsyncSession) -> None:
    mail_ids = await store(
        db_session, [mail(ANNA, to=[BERT], date=_day(2018, 1, 1)), mail(ANNA, to=[BERT])]
    )
    person = await ids(db_session)
    await refresh_person_stats(db_session)

    # merged outside merge_persons, and the dated mail turned out to be a duplicate
    await db_session.execute(
        text("UPDATE person SET merged_into = :a WHERE id = :b"),
        {"a": person[ANNA], "b": person[BERT]},
    )
    await db_session.execute(
        text("UPDATE mail SET is_duplicate_of = :undated WHERE id = :dated"),
        {"undated": mail_ids[1], "dated": mail_ids[0]},
    )
    await refresh_person_stats(db_session)

    assert await stats(db_session) == {ANNA: (1, 0, 0, 0, None, None, None)}
    assert await years(db_session) == {}


async def test_a_second_refresh_writes_nothing(db_session: AsyncSession) -> None:
    await store(
        db_session,
        [
            mail(
                f"Anna Schmidt <{ANNA}>", to=[BERT], cc=[CARL], date=_day(2020, 1, 1), dkim="pass"
            ),
            mail(BERT, to=["Anna Schmidt <anna@b.example>"], date=_day(2021, 1, 1)),
        ],
    )
    await finalize(db_session)
    before = await row_versions(db_session)
    assert all(before.values())  # every table has rows

    await aggregates.refresh_aggregates(db_session)
    assert await row_versions(db_session) == before
    await finalize(db_session)
    assert await row_versions(db_session) == before


async def test_a_refresh_for_no_persons_does_nothing(db_session: AsyncSession) -> None:
    await store(db_session, [mail(ANNA, to=[BERT])])
    await refresh_person_stats(db_session, [])
    assert await fetch(db_session, "SELECT count(*) FROM person_stats") == [(0,)]

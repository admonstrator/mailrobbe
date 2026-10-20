"""finalize: duplicates (D16), threads (D17), display names, and that a rerun changes nothing."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.importer.finalize import ThreadForest, finalize
from mailrobbe.importer.model import ParsedMail
from mailrobbe.importer.store import Batch, Store
from tests.importer.doubles import (
    add_mbox_file,
    address,
    fetch,
    make_mail,
    make_record,
    message,
)


async def _store(
    session: AsyncSession, file_id: int, mails: list[tuple[int, ParsedMail]], raw: bytes = b""
) -> dict[int, int]:
    """Store mails at the given offsets; returns offset -> mail id. `raw` fixes the message."""
    batch = Batch()
    for offset, mail in mails:
        batch.add(make_record(offset, raw or message(offset)), mail)
    await Store().write(session, file_id, batch)
    rows = await fetch(
        session, "SELECT byte_offset, id FROM mail WHERE mbox_file_id = :id", id=file_id
    )
    return dict(rows)


async def _column(session: AsyncSession, column: str) -> dict[int, Any]:
    return dict(await fetch(session, f"SELECT id, {column} FROM mail"))


@pytest.mark.db
async def test_duplicates_point_at_the_earliest_mail(db_session: AsyncSession) -> None:
    # b.mbox is stored first, so its mails get the smaller ids; a.mbox still comes first
    later = await add_mbox_file(db_session, "b.mbox")
    earlier = await add_mbox_file(db_session, "a.mbox")
    same = make_mail(message_id="<x@a.example>", subject="Hallo")
    b = await _store(
        db_session,
        later,
        [
            (0, same),
            (100, make_mail(message_id="<x@a.example>", subject="Other subject")),
            (200, make_mail(message_id="<y@a.example>")),
        ],
    )
    a = await _store(db_session, earlier, [(500, same), (50, same), (900, make_mail())])
    no_id = await _store(db_session, earlier, [(1000, make_mail()), (2000, make_mail())], b"S: 1\n")
    other = await _store(db_session, later, [(5000, make_mail(message_id="<y@a.example>"))])

    result = await finalize(db_session)
    duplicates = await _column(db_session, "is_duplicate_of")
    assert duplicates == {
        a[50]: None,
        a[500]: a[50],
        b[0]: a[50],
        b[100]: None,  # same Message-ID, other subject
        b[200]: None,
        other[5000]: b[200],  # subject NULL on both sides
        a[900]: None,  # no Message-ID, its own message
        no_id[1000]: None,
        no_id[2000]: no_id[1000],  # no Message-ID, same message
    }
    assert result.duplicates == 4

    await db_session.execute(
        text("UPDATE mail SET subject = 'Changed' WHERE id = :id"), {"id": b[0]}
    )
    await db_session.commit()
    result = await finalize(db_session)
    assert result.duplicates == 1
    assert (await _column(db_session, "is_duplicate_of"))[b[0]] is None


@pytest.mark.db
async def test_threads_follow_message_ids(db_session: AsyncSession) -> None:
    file_id = await add_mbox_file(db_session)
    root = make_mail(message_id="<a@x>", subject="Start")
    ids = await _store(
        db_session,
        file_id,
        [
            (0, root),
            (100, make_mail(message_id="<b@x>", in_reply_to="<a@x>", reference_ids=("<a@x>",))),
            (200, make_mail(message_id="<c@x>", reference_ids=("<a@x>", "<b@x>"))),
            # two replies to a parent that is not in the archive
            (300, make_mail(message_id="<d@x>", in_reply_to="<missing@x>")),
            (400, make_mail(message_id="<e@x>", reference_ids=("<missing@x>",))),
            (500, make_mail(message_id="<single@x>")),
            (600, make_mail()),
            (700, root),  # duplicate of the root: in its thread, but not a node
            (800, make_mail(message_id="<lonely@x>")),
            (900, make_mail(message_id="<lonely@x>")),  # duplicate of a single mail
        ],
    )
    result = await finalize(db_session)
    threads = await _column(db_session, "thread_id")
    assert threads == {
        ids[0]: ids[0],
        ids[100]: ids[0],
        ids[200]: ids[0],
        ids[300]: ids[300],
        ids[400]: ids[300],
        ids[500]: None,
        ids[600]: None,
        ids[700]: ids[0],
        ids[800]: None,
        ids[900]: None,
    }
    assert result.threads == 6


@pytest.mark.db
async def test_display_names_are_counted(db_session: AsyncSession) -> None:
    file_id = await add_mbox_file(db_session)
    anna, bert, carl = "anna@a.example", "bert@b.example", "carl@c.example"
    mails = [
        make_mail(sender=(address(anna, "Anna"),), to=(address(bert, "Bert"),)),
        make_mail(sender=(address(anna, "Anna B."),), cc=(address(bert, "Bert"),)),
        make_mail(sender=(address(anna, "Anna B."),), to=(address(bert, "Bert"),)),
        make_mail(sender=(address(anna, "Anna"),), to=(address(carl),)),
        make_mail(to=(address(bert, "B."),), bcc=(address(carl),)),
    ]
    await _store(db_session, file_id, [(index * 100, mail) for index, mail in enumerate(mails)])
    await finalize(db_session)
    names = await fetch(
        db_session,
        "SELECT p.canonical_email, p.display_name, e.display_names FROM person p "
        "JOIN person_email e ON e.person_id = p.id ORDER BY 1",
    )
    assert names == [
        (anna, "Anna", {"Anna": 2, "Anna B.": 2}),  # a tie: alphabetically first
        (bert, "Bert", {"Bert": 3, "B.": 1}),
        (carl, None, {}),
    ]


@pytest.mark.db
async def test_a_second_finalize_changes_nothing(db_session: AsyncSession) -> None:
    file_id = await add_mbox_file(db_session)
    mail = make_mail(message_id="<a@x>", sender=(address("anna@a.example", "Anna"),))
    reply = make_mail(message_id="<b@x>", in_reply_to="<a@x>", to=(address("anna@a.example"),))
    await _store(db_session, file_id, [(0, mail), (100, mail), (200, reply)])
    first = await finalize(db_session)
    assert (first.duplicates, first.threads, first.display_names) == (1, 3, 2)
    second = await finalize(db_session)
    assert (second.duplicates, second.threads, second.display_names) == (0, 0, 0)


def test_thread_forest_joins_through_references() -> None:
    forest = ThreadForest()
    forest.add(5, "<a>", None, None)
    forest.add(3, "<c>", "<b>", None)  # parent <b> arrives later
    forest.add(9, "<b>", "<a>", ["<a>"])
    forest.add(7, None, None, None)
    forest.add(8, None, "<z>", None)
    forest.add(4, "<y>", None, ["<z>", "<y>"])
    forest.add(6, "<solo>", None, [])
    assert forest.thread_ids() == {5: 3, 3: 3, 9: 3, 8: 4, 4: 4}

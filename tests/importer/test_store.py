"""Batches written by store.Store, built by hand from MboxRecord and ParsedMail objects."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.enums import DkimStatus, ImportErrorKind
from mailrobbe.importer.model import Issue
from mailrobbe.importer.store import BATCH_RECORDS, Batch, Store
from tests.importer.doubles import (
    FakeVerdict,
    add_mbox_file,
    address,
    attachment,
    fetch,
    make_mail,
    make_record,
    message,
)

pytestmark = pytest.mark.db

DATE = datetime(2024, 1, 1, 10, tzinfo=UTC)


def _batch(*entries: tuple[int, Any], verdict: Any = None) -> Batch:
    batch = Batch()
    for offset, mail in entries:
        batch.add(make_record(offset, message(offset)), mail, verdict)
    return batch


async def test_a_batch_stores_mails_and_their_rows(db_session: AsyncSession) -> None:
    file_id = await add_mbox_file(db_session)
    first = make_record(0, message(1), issues=(Issue(ImportErrorKind.SEPARATOR, "no blank"),))
    second = make_record(first.byte_length, message(2))
    batch = Batch()
    batch.add(
        first,
        make_mail(
            message_id="<1@a.example>",
            reference_ids=("<0@a.example>", "<9@a.example>"),
            in_reply_to="<9@a.example>",
            subject="Hallo",
            date_utc=DATE,
            sender=(address("anna@a.example", "Anna"),),
            to=(address("bert@b.example"),),
            cc=(address("carl@sub.c.example", "Carl"),),
            body_text="Grüße",
            attachments=(attachment("x.pdf", 10, "ff"), attachment(None, 2, None)),
            issues=(Issue(ImportErrorKind.DATE, "Date header missing"),),
        ),
        FakeVerdict(DkimStatus.PASS),
        (Issue(ImportErrorKind.DKIM, "checker failed"),),
    )
    batch.add(second, make_mail(sender=(address("anna@a.example", "A. Nna"),)))
    await Store().write(db_session, file_id, batch)

    mails = await fetch(
        db_session,
        "SELECT byte_offset, byte_length, message_id, in_reply_to, reference_ids, subject, "
        "date_utc, raw_sha256, has_attachments, body_text, dkim_status::text, thread_id, "
        "is_duplicate_of, tsv IS NOT NULL FROM mail ORDER BY byte_offset",
    )
    assert mails == [
        (
            0,
            first.byte_length,
            "<1@a.example>",
            "<9@a.example>",
            ["<0@a.example>", "<9@a.example>"],
            "Hallo",
            DATE,
            first.raw_sha256,
            True,
            "Grüße",
            "pass",
            None,
            None,
            True,
        ),
        (
            first.byte_length,
            second.byte_length,
            *(None, None, None, None, None),
            second.raw_sha256,
            False,
            None,
            None,
            None,
            None,
            True,
        ),
    ]
    participations = await fetch(
        db_session,
        "SELECT m.byte_offset, e.email, p.role::text, p.display_name FROM participation p "
        "JOIN mail m ON m.id = p.mail_id JOIN person_email e ON e.person_id = p.person_id "
        "ORDER BY 1, 3, 2",
    )
    assert participations == [
        (0, "carl@sub.c.example", "cc", "Carl"),
        (0, "anna@a.example", "from", "Anna"),
        (0, "bert@b.example", "to", None),
        (first.byte_length, "anna@a.example", "from", "A. Nna"),
    ]
    persons = await fetch(
        db_session, "SELECT canonical_email, domain, display_name FROM person ORDER BY 1"
    )
    assert persons == [
        ("anna@a.example", "a.example", None),
        ("bert@b.example", "b.example", None),
        ("carl@sub.c.example", "sub.c.example", None),
    ]
    attachments = await fetch(
        db_session,
        "SELECT filename, mime_type, size_bytes, sha256 FROM attachment ORDER BY size_bytes DESC",
    )
    assert attachments == [
        ("x.pdf", "application/pdf", 10, "ff"),
        (None, "application/pdf", 2, None),
    ]
    dkim = await fetch(db_session, "SELECT signature_index, status::text, domain FROM dkim_result")
    assert dkim == [(0, "pass", "a.example")]
    errors = await fetch(
        db_session, "SELECT mbox_file_id, byte_offset, kind, message FROM import_error ORDER BY id"
    )
    assert errors == [
        (file_id, 0, "separator", "no blank"),
        (file_id, 0, "date", "Date header missing"),
        (file_id, 0, "dkim", "checker failed"),
    ]
    progress = await fetch(
        db_session, "SELECT bytes_done, mails_parsed, error_count FROM mbox_file"
    )
    assert progress == [(batch.end, 2, 3)]
    assert batch.end == first.byte_length + second.byte_length


async def test_persons_are_reused_across_batches_and_workers(db_session: AsyncSession) -> None:
    file_id = await add_mbox_file(db_session)
    anna = address("anna@a.example", "Anna")
    store = Store()
    await store.write(db_session, file_id, _batch((0, make_mail(sender=(anna,)))))
    await store.write(db_session, file_id, _batch((100, make_mail(to=(anna,)))))
    other_worker = Store()
    await other_worker.write(
        db_session, file_id, _batch((200, make_mail(cc=(anna, address("bert@b.example")))))
    )
    assert await fetch(db_session, "SELECT count(*) FROM person") == [(2,)]
    assert await fetch(db_session, "SELECT count(*) FROM person_email") == [(2,)]
    rows = await fetch(
        db_session,
        "SELECT count(DISTINCT p.person_id) FROM participation p "
        "JOIN person_email e ON e.person_id = p.person_id WHERE e.email = 'anna@a.example'",
    )
    assert rows == [(1,)]


async def test_an_alias_maps_to_its_person(db_session: AsyncSession) -> None:
    file_id = await add_mbox_file(db_session)
    person_id = await db_session.scalar(
        text(
            "INSERT INTO person (canonical_email, domain) VALUES ('anna@a.example', 'a.example') "
            "RETURNING id"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO person_email (email, person_id) VALUES "
            "('anna@a.example', :id), ('anna.alt@b.example', :id)"
        ),
        {"id": person_id},
    )
    await db_session.commit()
    mail = make_mail(to=(address("anna.alt@b.example"), address("anna@a.example", "Anna")))
    await Store().write(db_session, file_id, _batch((0, mail)))
    rows = await fetch(db_session, "SELECT person_id, role::text, display_name FROM participation")
    assert rows == [(person_id, "to", "Anna")]
    assert await fetch(db_session, "SELECT count(*) FROM person") == [(1,)]


async def test_participation_is_deduplicated_per_person_and_role(db_session: AsyncSession) -> None:
    file_id = await add_mbox_file(db_session)
    bert = "bert@b.example"
    mail = make_mail(
        sender=(address(bert),),
        to=(address(bert), address(bert, "Bert"), address(bert, "Other")),
        cc=(address(bert, "Cc Bert"),),
        bcc=(address(bert),),
    )
    await Store().write(db_session, file_id, _batch((0, mail)))
    rows = await fetch(db_session, "SELECT role::text, display_name FROM participation ORDER BY 1")
    assert rows == [("bcc", None), ("cc", "Cc Bert"), ("from", None), ("to", "Bert")]


async def test_nothing_of_a_failing_batch_is_committed(db_session: AsyncSession) -> None:
    file_id = await add_mbox_file(db_session)
    store = Store()
    failing = make_mail(issues=(Issue(ImportErrorKind.ENCODING, "bad charset"),))
    first = _batch((0, failing))
    await store.write(db_session, file_id, first)
    before = await fetch(db_session, "SELECT bytes_done, mails_parsed, error_count FROM mbox_file")

    # offset 0 is stored already: the COPY of the second batch violates the unique constraint
    second = _batch((500, make_mail(sender=(address("new@n.example"),))), (0, failing))
    with pytest.raises(Exception, match="duplicate key"):
        await store.write(db_session, file_id, second)

    assert await fetch(db_session, "SELECT byte_offset FROM mail") == [(0,)]
    assert await fetch(db_session, "SELECT count(*) FROM import_error") == [(1,)]
    assert await fetch(db_session, "SELECT count(*) FROM participation") == [(0,)]
    after = await fetch(db_session, "SELECT bytes_done, mails_parsed, error_count FROM mbox_file")
    assert after == before == [(first.end, 1, 1)]


async def test_unsigned_and_unchecked_mails(db_session: AsyncSession) -> None:
    file_id = await add_mbox_file(db_session)
    batch = _batch((0, make_mail()), verdict=FakeVerdict(DkimStatus.UNSIGNED))
    batch.add(make_record(1000, message(7), truncated=True), make_mail(), None)
    await Store().write(db_session, file_id, batch)
    rows = await fetch(db_session, "SELECT dkim_status::text FROM mail ORDER BY byte_offset")
    assert rows == [("unsigned",), (None,)]
    assert await fetch(db_session, "SELECT count(*) FROM dkim_result") == [(0,)]


def test_a_batch_is_full_at_its_record_limit() -> None:
    batch = Batch()
    for index in range(BATCH_RECORDS):
        assert not batch.is_full()
        batch.add(make_record(index * 100, b"S: x\n\nb\n"), make_mail())
    assert batch.is_full()
    assert len(batch) == BATCH_RECORDS

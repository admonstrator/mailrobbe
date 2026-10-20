"""Constraints and behaviour of the migrated schema, written through the ORM models."""

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.db.models import (
    TEXT_SEARCH_CONFIG,
    Attachment,
    DkimResult,
    Edge,
    ImportErrorRecord,
    Mail,
    MailHeader,
    MboxFile,
    Participation,
    Person,
)
from mailrobbe.enums import DkimStatus, ParticipationRole

pytestmark = pytest.mark.db

SHA256 = "0" * 64


def _violation(error: pytest.ExceptionInfo[IntegrityError]) -> tuple[str, str]:
    """SQLSTATE and constraint name, from the asyncpg exception behind SQLAlchemy's DBAPI error."""
    cause = error.value.orig.__cause__ if error.value.orig is not None else None
    return getattr(cause, "sqlstate", ""), getattr(cause, "constraint_name", "")


async def _mbox_file(session: AsyncSession, path: str = "/data/mbox/mbox-0001.mbox") -> MboxFile:
    mbox_file = MboxFile(path=path, size_bytes=4096)
    session.add(mbox_file)
    await session.flush()
    return mbox_file


async def _mail(
    session: AsyncSession, mbox_file: MboxFile, byte_offset: int, **values: object
) -> Mail:
    mail = Mail(
        mbox_file_id=mbox_file.id,
        byte_offset=byte_offset,
        byte_length=100,
        raw_sha256=SHA256,
        **values,
    )
    session.add(mail)
    await session.flush()
    return mail


async def _persons(session: AsyncSession, *emails: str) -> list[Person]:
    persons = [Person(canonical_email=email, domain=email.rpartition("@")[2]) for email in emails]
    session.add_all(persons)
    await session.flush()
    return persons


async def _ordered_person_ids(session: AsyncSession) -> tuple[int, int]:
    first, second = await _persons(
        session, "max.mueller@nordwind.example", "erika.muster@bergmann.test"
    )
    low, high = sorted((first.id, second.id))
    return low, high


async def test_edge_rejects_unordered_pair(db_session: AsyncSession) -> None:
    low, high = await _ordered_person_ids(db_session)
    for person_a, person_b in ((high, low), (low, low)):
        with pytest.raises(IntegrityError) as error:
            async with db_session.begin_nested():
                db_session.add(Edge(person_a=person_a, person_b=person_b))
        # check_violation; the constraint's name is covered by test_constraint_names_match_models
        assert _violation(error)[0] == "23514"

    db_session.add(Edge(person_a=low, person_b=high))
    await db_session.flush()


async def test_edge_mails_total_is_computed(db_session: AsyncSession) -> None:
    low, high = await _ordered_person_ids(db_session)
    db_session.add(Edge(person_a=low, person_b=high, mails_a_to_b=3, mails_b_to_a=2, mails_cc=1))
    await db_session.flush()
    total = select(Edge.mails_total).where(Edge.person_a == low, Edge.person_b == high)
    assert await db_session.scalar(total) == 6

    await db_session.execute(update(Edge).values(mails_cc=Edge.mails_cc + 10))
    assert await db_session.scalar(total) == 16


async def test_mail_offset_is_unique_per_file(db_session: AsyncSession) -> None:
    first = await _mbox_file(db_session)
    second = await _mbox_file(db_session, "/data/mbox/mbox-0002.mbox")
    await _mail(db_session, first, 0)
    await _mail(db_session, second, 0)

    with pytest.raises(IntegrityError) as error:
        async with db_session.begin_nested():
            await _mail(db_session, first, 0)
    assert _violation(error) == ("23505", "uq_mail_mbox_file_id_byte_offset")


async def test_deleting_mbox_file_cascades(db_session: AsyncSession) -> None:
    mbox_file = await _mbox_file(db_session)
    mail = await _mail(db_session, mbox_file, 0)
    (person,) = await _persons(db_session, "max.mueller@nordwind.example")
    db_session.add_all(
        [
            MailHeader(mail_id=mail.id, position=0, name="Subject", value="Angebot"),
            Participation(mail_id=mail.id, person_id=person.id, role=ParticipationRole.FROM),
            Attachment(mail_id=mail.id, mime_type="application/pdf", size_bytes=1024),
            DkimResult(mail_id=mail.id, signature_index=0, status=DkimStatus.PASS),
            ImportErrorRecord(mbox_file_id=mbox_file.id, kind="encoding", message="bad charset"),
        ]
    )
    await db_session.flush()

    await db_session.execute(delete(MboxFile).where(MboxFile.id == mbox_file.id))

    for model in (Mail, MailHeader, Participation, Attachment, DkimResult, ImportErrorRecord):
        count = await db_session.scalar(select(func.count()).select_from(model))
        assert count == 0, model.__tablename__
    assert await db_session.scalar(select(func.count()).select_from(Person)) == 1


async def test_participation_accepts_every_role_including_bcc(db_session: AsyncSession) -> None:
    mail = await _mail(db_session, await _mbox_file(db_session), 0)
    (person,) = await _persons(db_session, "max.mueller@nordwind.example")
    db_session.add_all(
        Participation(mail_id=mail.id, person_id=person.id, role=role) for role in ParticipationRole
    )
    await db_session.flush()

    roles = await db_session.scalars(
        select(Participation.role).where(Participation.mail_id == mail.id)
    )
    assert set(roles) == {"from", "to", "cc", "bcc"}


async def test_mail_dkim_status_is_null_until_checked(db_session: AsyncSession) -> None:
    mail = await _mail(db_session, await _mbox_file(db_session), 0)
    status = select(Mail.dkim_status).where(Mail.id == mail.id)
    assert await db_session.scalar(status) is None

    mail.dkim_status = DkimStatus.TEMP_ERROR
    await db_session.flush()
    assert await db_session.scalar(status) is DkimStatus.TEMP_ERROR


async def test_full_text_search_uses_gin_index(db_session: AsyncSession) -> None:
    mbox_file = await _mbox_file(db_session)
    invoice = await _mail(db_session, mbox_file, 0, body_text="Anbei die Rechnung für März.")
    await _mail(db_session, mbox_file, 100, body_text="Termin am Montag um neun.")

    search = f"SELECT id FROM mail WHERE tsv @@ to_tsquery('{TEXT_SEARCH_CONFIG}', 'rechnung')"
    assert list(await db_session.scalars(text(search))) == [invoice.id]
    # The tables are tiny, so forbid sequential scans to see whether the index can serve the query.
    await db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(await db_session.scalars(text(f"EXPLAIN {search}")))
    assert "Index Scan on ix_mail_tsv" in plan


# No plan check here: on a handful of rows the planner prefers a full scan of the unique btree
# index, even with sequential scans off. The trigram operator class is checked in test_migrations.
async def test_substring_search_on_canonical_email(db_session: AsyncSession) -> None:
    await _persons(
        db_session,
        "max.mueller@nordwind.example",
        "anna.mueller-lang@bergmann.test",
        "erika.muster@bergmann.test",
    )

    search = "SELECT canonical_email FROM person WHERE canonical_email ILIKE '%mueller%'"
    assert set(await db_session.scalars(text(search))) == {
        "max.mueller@nordwind.example",
        "anna.mueller-lang@bergmann.test",
    }


async def test_mail_tsv_is_generated_from_subject_and_body(db_session: AsyncSession) -> None:
    mbox_file = await _mbox_file(db_session)
    mail = await _mail(
        db_session, mbox_file, 0, subject="Rechnungen für März", body_text="Die Verträge anbei."
    )
    await db_session.refresh(mail, ["tsv"])
    matches = select(
        Mail.tsv.bool_op("@@")(func.to_tsquery(TEXT_SEARCH_CONFIG, "rechnung & vertrag"))
    ).where(Mail.id == mail.id)
    assert await db_session.scalar(matches) is True
    weights = select(
        func.ts_rank(Mail.tsv, func.to_tsquery(TEXT_SEARCH_CONFIG, "rechnung"))
        > func.ts_rank(Mail.tsv, func.to_tsquery(TEXT_SEARCH_CONFIG, "vertrag"))
    ).where(Mail.id == mail.id)
    assert await db_session.scalar(weights) is True  # subject weighs more than body
    await db_session.execute(update(Mail).where(Mail.id == mail.id).values(subject=None))
    await db_session.refresh(mail, ["tsv"])
    assert await db_session.scalar(matches) is False

"""The entities phase of an import (D84) on the generated archive: every text scanned once, the
same entities whatever the workers and batches, stop and resume, texts that change or go, and
texts that break the extraction."""

import asyncio
import logging

import pytest

from mailrobbe.entities import phase
from mailrobbe.entities.extract import extract_entities
from mailrobbe.entities.figures import FiguresRefresh
from mailrobbe.entities.model import scan_version
from mailrobbe.entities.phase import Waiting, waiting
from mailrobbe.enums import EntityContext
from tests.entities.conftest import (
    Step,
    entities_now,
    execute,
    rows,
    scan,
    sessions,
    value,
)
from tests.entities.doubles import KILL, RAISE, breaking_extract

pytestmark = [pytest.mark.db, pytest.mark.slow]

WITH_TEXT = "text_status IN ('text', 'timeout') AND extracted_text IS NOT NULL"


async def waiting_now(url: str) -> Waiting:
    async with sessions(url) as sessionmaker, sessionmaker() as session:
        return await waiting(session)


async def test_a_phase_scans_every_text_once(unscanned_url: str) -> None:
    url = unscanned_url
    mails = await value(url, "SELECT count(*) FROM mail")
    documents = await value(url, f"SELECT count(*) FROM document WHERE {WITH_TEXT}")
    before = await waiting_now(url)
    assert (before.mails, before.documents, before.gone) == (mails, documents, 0)
    assert documents > 0 and before.bytes > 0

    step = Step()
    result = await scan(url, step=step)
    assert (result.mails, result.documents) == (mails, documents)
    assert (result.failed, result.gone, result.stopped) == (0, 0, False)
    assert step.done == result.bytes == before.bytes
    assert result.entities == await value(url, "SELECT count(*) FROM entity")
    assert result.figures is not None and 0 < result.figures.updated <= result.entities
    version = scan_version()
    scans = "SELECT count(*) FROM {} WHERE version = :version"
    assert await value(url, scans.format("mail_entity_scan"), version=version) == mails
    assert await value(url, scans.format("document_entity_scan"), version=version) == documents
    assert await value(url, "SELECT count(*) FROM document_entity") > 0
    kinds = {kind for (kind,) in await rows(url, "SELECT DISTINCT kind::text FROM entity")}
    assert kinds >= {
        "amount", "iban", "organization", "person", "place", "phone", "email", "url", "domain",
        "date", "term",
    }  # fmt: skip
    assert not await waiting_now(url)

    stored = await entities_now(url)
    idle_step = Step()
    idle = await scan(url, step=idle_step)
    assert (idle.mails_waiting, idle.documents_waiting, idle_step.calls) == (0, 0, 0)
    assert idle.figures == FiguresRefresh(updated=0, deleted=0)
    assert await entities_now(url) == stored


async def test_the_same_entities_whatever_the_workers_and_batches(
    unscanned_url: str, scanned_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(phase, "BATCH_TEXTS", 7)  # the batches are cut in the main process
    result = await scan(unscanned_url, workers=3)
    assert result.failed == 0
    assert await entities_now(unscanned_url) == await entities_now(scanned_database_url)


async def test_a_stop_keeps_the_stored_batches_and_the_next_phase_does_the_rest(
    unscanned_url: str, scanned_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = unscanned_url
    monkeypatch.setattr(phase, "BATCH_TEXTS", 40)
    before = await waiting_now(url)
    stop = asyncio.Event()
    step = Step(stop)  # sets stop when the first batch is stored
    stopped = await scan(url, step=step, stop=stop)
    assert stopped.stopped and stopped.figures is None
    first = stopped.documents + stopped.mails
    assert step.calls == 1 and 0 < first <= 40
    rest = await waiting_now(url)
    assert rest.documents + rest.mails == before.documents + before.mails - first
    assert rest.bytes == before.bytes - step.done
    assert await value(url, "SELECT count(*) FROM entity WHERE mails > 0") == 0  # no figures yet

    finished = await scan(url)
    assert not finished.stopped and not await waiting_now(url)
    assert finished.documents + finished.mails == rest.documents + rest.mails
    assert await entities_now(url) == await entities_now(scanned_database_url)


async def test_a_stop_before_the_phase_scans_nothing(unscanned_url: str) -> None:
    stop = asyncio.Event()
    stop.set()
    result = await scan(unscanned_url, stop=stop)
    assert result.stopped and (result.mails, result.documents) == (0, 0)
    assert await value(unscanned_url, "SELECT count(*) FROM mail_entity_scan") == 0


async def document_mentions(url: str, document_id: int) -> list[tuple[object, ...]]:
    return await rows(
        url,
        """SELECT e.kind::text, e.key, m.occurrences, m.context, m.position
           FROM document_entity m JOIN entity e ON e.id = m.entity_id
           WHERE m.document_id = :id ORDER BY m.position, e.kind""",
        id=document_id,
    )


async def test_a_text_extracted_again_is_scanned_again(scanned_url: str) -> None:
    url = scanned_url
    document = await value(url, "SELECT min(document_id) FROM document_entity")
    before = await document_mentions(url, document)
    later = "extracted_at = extracted_at + interval '1 day'"
    await execute(url, f"UPDATE document SET {later} WHERE id = :id", id=document)
    left = await waiting_now(url)
    assert (left.mails, left.documents, left.gone) == (0, 1, 0)
    result = await scan(url)
    assert (result.mails, result.documents) == (0, 1)
    assert await document_mentions(url, document) == before
    recorded = """SELECT s.extracted_at = d.extracted_at FROM document_entity_scan s
                  JOIN document d ON d.id = s.document_id WHERE d.id = :id"""
    assert await value(url, recorded, id=document) is True
    assert not await waiting_now(url)


async def test_a_new_text_of_a_document_replaces_its_mentions(scanned_url: str) -> None:
    url = scanned_url
    document = await value(url, "SELECT min(document_id) FROM document_entity")
    new_text = "Barspende von 1.234,56 EUR an den Förderverein Nordwind e.V., Quittung folgt."
    await execute(
        url,
        """UPDATE document SET extracted_text = :text,
               extracted_at = extracted_at + interval '1 day' WHERE id = :id""",
        text=new_text,
        id=document,
    )
    left = await waiting_now(url)
    assert (left.mails, left.documents, left.bytes) == (0, 1, len(new_text.encode()))
    result = await scan(url)
    assert (result.mails, result.documents) == (0, 1)
    expected = [
        (found.kind.value, found.key, found.occurrences, int(found.context), found.position)
        for found in extract_entities(new_text)
    ]
    assert await document_mentions(url, document) == sorted(expected, key=lambda row: row[4])
    contexts = [row[3] for row in expected if row[0] == "amount"]
    assert contexts == [EntityContext.CASH | EntityContext.DONATION | EntityContext.RECEIPT]
    assert not await waiting_now(url)


async def test_a_document_whose_text_is_gone_loses_its_mentions(scanned_url: str) -> None:
    url = scanned_url
    document = await value(url, "SELECT min(document_id) FROM document_entity")
    await execute(
        url,
        """UPDATE document SET text_status = 'unreadable', extracted_text = NULL
           WHERE id = :id""",
        id=document,
    )
    assert await waiting_now(url) == Waiting(mails=0, documents=0, bytes=0, gone=1)
    result = await scan(url)
    assert result.gone == 1
    assert await document_mentions(url, document) == []
    scans = "SELECT count(*) FROM document_entity_scan WHERE document_id = :id"
    assert await value(url, scans, id=document) == 0
    assert not await waiting_now(url)


async def test_a_deleted_mail_takes_its_mentions_and_the_next_phase_its_orphans(
    scanned_url: str,
) -> None:
    url = scanned_url
    [(entity, mail)] = await rows(
        url,
        """SELECT m.entity_id, m.mail_id FROM mail_entity m
           WHERE NOT EXISTS (SELECT 1 FROM mail_entity o
                             WHERE o.entity_id = m.entity_id AND o.mail_id <> m.mail_id)
             AND NOT EXISTS (SELECT 1 FROM document_entity d WHERE d.entity_id = m.entity_id)
             AND NOT EXISTS (SELECT 1 FROM attachment a WHERE a.mail_id = m.mail_id)
           ORDER BY m.entity_id LIMIT 1""",
    )
    await execute(url, "DELETE FROM mail WHERE id = :id", id=mail)
    assert await value(url, "SELECT count(*) FROM mail_entity WHERE mail_id = :id", id=mail) == 0
    assert not await waiting_now(url)  # its scan went with it
    result = await scan(url)
    assert result.figures is not None and result.figures.deleted >= 1
    assert await value(url, "SELECT count(*) FROM entity WHERE id = :id", id=entity) == 0


async def test_a_new_scan_version_scans_every_text_again(
    scanned_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = scanned_url
    before = await entities_now(url)
    monkeypatch.setattr(phase, "scan_version", lambda: 7)
    again = await waiting_now(url)
    assert again.mails == await value(url, "SELECT count(*) FROM mail")
    assert again.documents == await value(url, f"SELECT count(*) FROM document WHERE {WITH_TEXT}")
    result = await scan(url)
    assert (result.mails, result.documents) == (again.mails, again.documents)
    assert result.entities == 0  # all known
    assert await entities_now(url) == before
    assert await value(url, "SELECT count(*) FROM mail_entity_scan WHERE version <> 7") == 0
    assert not await waiting_now(url)


async def test_a_text_that_breaks_the_extraction_is_recorded_without_entities(
    scanned_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    url = scanned_url
    [(killer,), (raiser,), (plain,)] = await rows(url, "SELECT id FROM mail ORDER BY id LIMIT 3")
    bodies = {
        killer: f"Dieser Text {KILL} beendet den Prozess. Spende 10 EUR",
        raiser: f"Dieser Text {RAISE} wirft. Spende 20 EUR",
        plain: "Eine Spende von 30 EUR in bar.",
    }
    for mail, body in bodies.items():
        await execute(url, "UPDATE mail SET body_text = :body WHERE id = :id", body=body, id=mail)
        await execute(url, "DELETE FROM mail_entity_scan WHERE mail_id = :id", id=mail)
    caplog.set_level(logging.WARNING, logger=phase.__name__)
    result = await scan(url, workers=2, extract=breaking_extract)
    assert (result.mails, result.failed) == (3, 2)
    mentioned = """SELECT e.key FROM mail_entity m JOIN entity e ON e.id = m.entity_id
                   WHERE m.mail_id = :id AND e.kind = 'amount'"""
    assert await rows(url, mentioned, id=killer) == []
    assert await rows(url, mentioned, id=raiser) == []
    assert await rows(url, mentioned, id=plain) == [("EUR 30.00",)]
    assert not await waiting_now(url)
    warnings = [record.getMessage() for record in caplog.records]
    assert any("a worker process died" in message for message in warnings)
    assert any(
        f"mail {killer} recorded without entities: the worker process died" in message
        for message in warnings
    )
    assert any(
        f"mail {raiser} recorded without entities" in message and "a broken pattern" in message
        for message in warnings
    )

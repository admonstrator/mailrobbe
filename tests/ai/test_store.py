"""ai.store and ai.queue on a migrated database (D185, D186)."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.ai.model import LOGO_MAILS, PAGE_SEPARATOR, PRIORITY_SINGLE, OcrPage
from mailrobbe.ai.queue import cancel_tasks, enqueue_ocr, retry_tasks, task_counts, work_list_ids
from mailrobbe.ai.store import (
    discard_job_results,
    discard_result,
    reapply_results,
    store_ocr_result,
)
from mailrobbe.enums import AiTaskKind, AiTaskStatus

_DOCUMENT = text("""
    INSERT INTO document (sha256, name, mime_type, size_bytes, kind, text_status, extracted_text,
        mails, extracted_at)
    VALUES (:sha256, :name, :mime, :size, CAST(:kind AS document_kind),
        CAST(:status AS document_text_status), :text, :mails, NULL)
    RETURNING id
""")


async def document(
    session: AsyncSession,
    sha256: str | None,
    *,
    kind: str = "pdf",
    status: str = "scanned",
    body: str | None = None,
    size: int = 200_000,
    mails: int = 1,
) -> int:
    mime = "application/pdf" if kind == "pdf" else "image/jpeg"
    parameters = {
        "sha256": sha256,
        "name": f"{sha256}.{kind}",
        "mime": mime,
        "size": size,
        "kind": kind,
        "status": status,
        "text": body,
        "mails": mails,
    }
    document_id = await session.scalar(_DOCUMENT, parameters)
    assert document_id is not None
    return int(document_id)


async def row(session: AsyncSession, document_id: int) -> Any:
    return (
        await session.execute(
            text(
                "SELECT text_status::text AS status, text_origin::text AS origin, "
                "extracted_text, ai_result_id, extracted_at, text_truncated, pages "
                "FROM document WHERE id = :id"
            ),
            {"id": document_id},
        )
    ).one()


def pages(*texts: str, engine: Any = "tesseract") -> list[OcrPage]:
    return [OcrPage(number=n, engine=engine, text=t) for n, t in enumerate(texts, start=1)]


async def store(session: AsyncSession, sha256: str, found: list[OcrPage], **extra: Any) -> int:
    stored = await store_ocr_result(
        session,
        sha256=sha256,
        pages=found,
        pages_total=extra.get("pages_total", len(found)),
        model=extra.get("model"),
        service_url=None,
        remote=False,
        prompt_version=None,
        options={},
        seconds=1.0,
        job_id=None,
    )
    return stored.result_id


async def test_an_ocr_text_fills_a_scan_and_an_image(db_session: AsyncSession) -> None:
    scan = await document(db_session, "a" * 64)
    image = await document(db_session, "b" * 64, kind="image", status="unsupported")
    result = await store(db_session, "a" * 64, pages("Seite eins", "Seite zwei"), pages_total=3)
    await store(db_session, "b" * 64, pages("Schild"))
    filled = await row(db_session, scan)
    assert (filled.status, filled.origin, filled.ai_result_id) == ("text", "ocr", result)
    assert filled.extracted_text == PAGE_SEPARATOR.join(["Seite eins", "Seite zwei"])
    assert filled.extracted_at is not None and filled.pages == 3
    assert (await row(db_session, image)).extracted_text == "Schild"
    searched = await db_session.scalar(
        text("SELECT count(*) FROM document WHERE tsv @@ websearch_to_tsquery('german', 'Schild')")
    )
    assert searched == 1


async def test_an_ocr_text_never_replaces_an_extracted_one(db_session: AsyncSession) -> None:
    own = await document(db_session, "c" * 64, status="text", body="eigener Text")
    await store(db_session, "c" * 64, pages("erkannt"))
    kept = await row(db_session, own)
    assert (kept.status, kept.origin, kept.extracted_text) == ("text", "extracted", "eigener Text")


async def test_no_text_is_recorded_but_changes_nothing(db_session: AsyncSession) -> None:
    scan = await document(db_session, "d" * 64)
    first = await store(db_session, "d" * 64, pages("alt"))
    second = await store(db_session, "d" * 64, pages(""))
    kept = await row(db_session, scan)
    assert (kept.extracted_text, kept.ai_result_id) == ("alt", first)
    found = await db_session.execute(text("SELECT id, state::text AS state FROM ai_result"))
    states = {row.id: row.state for row in found}
    assert states[first] == "replaced" and states[second] == "valid"


async def test_discarding_brings_back_the_predecessor_or_the_scan(db_session: AsyncSession) -> None:
    scan = await document(db_session, "e" * 64)
    first = await store(db_session, "e" * 64, pages("tesseract"))
    second = await store(db_session, "e" * 64, pages("vision", engine="vision"))
    assert (await row(db_session, scan)).extracted_text == "vision"
    assert await discard_result(db_session, second, "Anna")
    back = await row(db_session, scan)
    assert (back.extracted_text, back.ai_result_id, back.origin) == ("tesseract", first, "ocr")
    assert not await discard_result(db_session, second, "Anna")
    assert await discard_result(db_session, first, "Anna")
    gone = await row(db_session, scan)
    assert (gone.status, gone.origin, gone.extracted_text, gone.ai_result_id) == (
        "scanned",
        "extracted",
        None,
        None,
    )
    by = await db_session.scalar(
        text("SELECT discarded_by FROM ai_result WHERE id = :id"), {"id": first}
    )
    assert by == "Anna"


async def test_discarding_a_run_and_reapplying_to_a_new_document(db_session: AsyncSession) -> None:
    job_id = await db_session.scalar(
        text("INSERT INTO job (kind, origin) VALUES ('ai', 'cli') RETURNING id")
    )
    image = await document(db_session, "f" * 64, kind="image", status="unsupported")
    result = await store_ocr_result(
        db_session,
        sha256="f" * 64,
        pages=pages("Plakat"),
        pages_total=1,
        model="m",
        service_url="http://127.0.0.1:1234/v1",
        remote=False,
        prompt_version=1,
        options={},
        seconds=2.0,
        job_id=job_id,
    )
    assert result.documents == 1
    # an import removed the document and made it again: the result goes back in
    await db_session.execute(text("DELETE FROM document WHERE id = :id"), {"id": image})
    again = await document(db_session, "f" * 64, kind="image", status="unsupported")
    assert await reapply_results(db_session) == 1
    assert (await row(db_session, again)).extracted_text == "Plakat"
    assert await discard_job_results(db_session, job_id, None) == 1
    assert (await row(db_session, again)).status == "unsupported"


async def test_enqueue_takes_readable_documents_once(db_session: AsyncSession) -> None:
    scan = await document(db_session, "1" * 64, mails=3)
    image = await document(db_session, "2" * 64, kind="image", status="unsupported")
    logo = await document(
        db_session, "3" * 64, kind="image", status="unsupported", mails=LOGO_MAILS + 1
    )
    own = await document(db_session, "4" * 64, status="text", body="Text")
    unhashed = await document(db_session, None)
    queued = await enqueue_ocr(
        db_session, [scan, image, logo, own, unhashed, 999_999], editor="Ben"
    )
    assert (queued.queued, queued.raised, queued.unreadable, queued.logos) == (2, 0, 3, 1)
    again = await enqueue_ocr(db_session, [scan, logo], engine="vision", single=True)
    assert (again.queued, again.raised) == (1, 1)
    tasks = (
        await db_session.execute(
            text("SELECT target_sha256, engine, priority, queued_by FROM ai_task ORDER BY id")
        )
    ).all()
    assert [(t.target_sha256[0], t.engine, t.priority) for t in tasks] == [
        ("1", "vision", PRIORITY_SINGLE),
        ("2", "auto", 0),
        ("3", "vision", PRIORITY_SINGLE),
    ]
    assert tasks[1].queued_by == "Ben"
    counts = await task_counts(db_session)
    assert counts[AiTaskKind.OCR][AiTaskStatus.WAITING] == 3


async def test_cancel_and_retry(db_session: AsyncSession) -> None:
    scan = await document(db_session, "5" * 64)
    other = await document(db_session, "6" * 64)
    await enqueue_ocr(db_session, [scan, other])
    assert await cancel_tasks(db_session) == 2
    assert await retry_tasks(db_session, kind=AiTaskKind.OCR, editor="Cem") == 2
    ids = list((await db_session.execute(text("SELECT id FROM ai_task ORDER BY id"))).scalars())
    assert await cancel_tasks(db_session, ids[:1]) == 1
    await enqueue_ocr(db_session, [scan])  # a new open task for the same content
    assert await retry_tasks(db_session, ids[:1]) == 0  # stays cancelled beside the open one


async def test_work_lists(db_session: AsyncSession) -> None:
    scan = await document(db_session, "7" * 64, mails=1)
    busy_scan = await document(db_session, "8" * 64, mails=5)
    photo = await document(db_session, "9" * 64, kind="image", status="unsupported")
    await document(db_session, "a1" * 32, kind="image", status="unsupported", size=1000)
    await document(db_session, "a2" * 32, kind="image", status="unsupported", mails=LOGO_MAILS + 1)
    assert await work_list_ids(db_session, "scanned") == [busy_scan, scan]
    assert await work_list_ids(db_session, "images") == [photo]
    await store(db_session, "7" * 64, pages(""))
    assert await work_list_ids(db_session, "scanned") == [busy_scan]

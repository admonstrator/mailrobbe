"""ai.store and ai.queue on a migrated database (D185, D186, D294, D295)."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.ai.model import (
    LOGO_MAILS,
    PAGE_SEPARATOR,
    PRIORITY_SINGLE,
    TRANSCRIBE_MODEL,
    OcrPage,
    TranscriptSegment,
)
from mailrobbe.ai.queue import cancel_tasks, enqueue, retry_tasks, task_counts, work_list_ids
from mailrobbe.ai.store import (
    discard_job_results,
    discard_result,
    reapply_results,
    store_ocr_result,
    store_transcript_result,
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
    mime = {"pdf": "application/pdf", "image": "image/jpeg", "media": "audio/ogg"}[kind]
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
                "extracted_text, ai_result_id, extracted_at, text_truncated, pages, duration "
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
    queued = await enqueue(db_session, [scan, image, logo, own, unhashed, 999_999], editor="Ben")
    assert (queued.queued, queued.raised, queued.unreadable, queued.logos) == (2, 0, 3, 1)
    again = await enqueue(db_session, [scan, logo], engine="vision", single=True)
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
    await enqueue(db_session, [scan, other])
    assert await cancel_tasks(db_session) == 2
    assert await retry_tasks(db_session, kind=AiTaskKind.OCR, editor="Cem") == 2
    ids = list((await db_session.execute(text("SELECT id FROM ai_task ORDER BY id"))).scalars())
    assert await cancel_tasks(db_session, ids[:1]) == 1
    await enqueue(db_session, [scan])  # a new open task for the same content
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


# Transcripts (D294, D295) ------------------------------------------------------------------------


def line(start: float, end: float, said: str, uncertain: bool = False) -> TranscriptSegment:
    return TranscriptSegment(start=start, end=end, text=said, confidence=0.8, uncertain=uncertain)


async def transcribe(
    session: AsyncSession,
    sha256: str,
    lines: list[TranscriptSegment],
    *,
    duration: float | None = 60.0,
    audio: bool = True,
    job_id: int | None = None,
) -> int:
    stored = await store_transcript_result(
        session,
        sha256=sha256,
        segments=lines,
        duration=duration,
        transcribed=duration or 0.0,
        audio=audio,
        options={"max_minutes": 180, "threads": 4, "uncertain": 0.5},
        seconds=3.0,
        job_id=job_id,
    )
    return stored.result_id


async def result(session: AsyncSession, result_id: int) -> Any:
    return (
        await session.execute(
            text(
                "SELECT kind::text AS kind, engine, model, body, pages, pages_total, duration, "
                "transcribed, options, state::text AS state FROM ai_result WHERE id = :id"
            ),
            {"id": result_id},
        )
    ).one()


async def test_a_transcript_fills_a_recording(db_session: AsyncSession) -> None:
    voice = await document(db_session, "ab" * 32, kind="media", status="unsupported")
    found = [line(9.5, 20.0, "Der Kassenbericht liegt im Büro.", True), line(1.0, 8.0, "Hallo")]
    stored = await transcribe(db_session, "ab" * 32, found, duration=42.0)
    filled = await row(db_session, voice)
    assert (filled.status, filled.origin, filled.ai_result_id) == ("text", "transcript", stored)
    assert filled.extracted_text == "Hallo\nDer Kassenbericht liegt im Büro."
    assert (filled.duration, filled.text_truncated) == (42.0, False)
    assert filled.extracted_at is not None
    kept = await result(db_session, stored)
    assert (kept.kind, kept.engine, kept.model, kept.state) == (
        "transcribe",
        "parakeet",
        TRANSCRIBE_MODEL,
        "valid",
    )
    assert (kept.duration, kept.transcribed, kept.pages_total) == (42.0, 42.0, None)
    assert [segment["start"] for segment in kept.pages] == [1.0, 9.5]  # in time order
    assert kept.pages[1]["uncertain"] is True
    assert kept.options == {"max_minutes": 180, "threads": 4, "uncertain": 0.5, "audio": True}
    searched = await db_session.scalar(
        text(
            "SELECT count(*) FROM document "
            "WHERE tsv @@ websearch_to_tsquery('german', 'Kassenbericht')"
        )
    )
    assert searched == 1


async def test_a_transcript_fills_neither_a_scan_nor_a_text_of_its_own(
    db_session: AsyncSession,
) -> None:
    scan = await document(db_session, "ac" * 32)
    own = await document(db_session, "ad" * 32, kind="media", status="text", body="Untertitel")
    await transcribe(db_session, "ac" * 32, [line(0, 2, "gesprochen")])
    await transcribe(db_session, "ad" * 32, [line(0, 2, "gesprochen")], duration=12.0)
    assert (await row(db_session, scan)).status == "scanned"
    kept = await row(db_session, own)
    assert (kept.origin, kept.extracted_text, kept.ai_result_id) == (
        "extracted",
        "Untertitel",
        None,
    )
    assert kept.duration == 12.0  # the length goes to every document of the content


async def test_an_empty_transcript_keeps_the_text_and_gives_the_length(
    db_session: AsyncSession,
) -> None:
    voice = await document(db_session, "ae" * 32, kind="media", status="unsupported")
    first = await transcribe(db_session, "ae" * 32, [line(0, 3, "Hallo")], duration=None)
    assert (await row(db_session, voice)).duration is None  # not known: nothing set
    second = await transcribe(db_session, "ae" * 32, [], duration=30.0, audio=False)
    kept = await row(db_session, voice)
    assert (kept.extracted_text, kept.ai_result_id, kept.duration) == ("Hallo", first, 30.0)
    empty = await result(db_session, second)
    assert (empty.body, empty.pages, empty.options["audio"]) == ("", [], False)
    assert (await result(db_session, first)).state == "replaced"


async def test_discarding_a_transcript_brings_back_the_earlier_one_or_the_recording(
    db_session: AsyncSession,
) -> None:
    voice = await document(db_session, "af" * 32, kind="media", status="unsupported")
    first = await transcribe(db_session, "af" * 32, [line(0, 3, "erste Fassung")])
    second = await transcribe(db_session, "af" * 32, [line(0, 3, "zweite Fassung")])
    assert await discard_result(db_session, second, "Anna")
    back = await row(db_session, voice)
    assert (back.extracted_text, back.ai_result_id, back.origin) == (
        "erste Fassung",
        first,
        "transcript",
    )
    assert await discard_result(db_session, first, "Anna")
    gone = await row(db_session, voice)
    assert (gone.status, gone.origin, gone.extracted_text, gone.ai_result_id) == (
        "unsupported",
        "extracted",
        None,
        None,
    )
    assert gone.duration == 60.0  # the recording's length stays known


async def test_reapplying_transcripts_to_recordings_made_again(db_session: AsyncSession) -> None:
    job_id = await db_session.scalar(
        text("INSERT INTO job (kind, origin) VALUES ('ai', 'cli') RETURNING id")
    )
    voice = await document(db_session, "b1" * 32, kind="media", status="unsupported")
    tone = await document(db_session, "b2" * 32, kind="media", status="unsupported")
    await transcribe(db_session, "b1" * 32, [line(0, 3, "Ansage")], job_id=job_id)
    await transcribe(db_session, "b2" * 32, [], duration=7.0, job_id=job_id)
    # an import removed the documents and made them again: text and lengths go back in
    await db_session.execute(
        text("DELETE FROM document WHERE id = ANY(:ids)"), {"ids": [voice, tone]}
    )
    voice = await document(db_session, "b1" * 32, kind="media", status="unsupported")
    tone = await document(db_session, "b2" * 32, kind="media", status="unsupported")
    assert await reapply_results(db_session) == 1
    again = await row(db_session, voice)
    assert (again.extracted_text, again.origin, again.duration) == ("Ansage", "transcript", 60.0)
    assert (await row(db_session, tone)).duration == 7.0
    assert await reapply_results(db_session) == 0
    assert await discard_job_results(db_session, job_id, None) == 2
    assert (await row(db_session, voice)).status == "unsupported"


async def test_enqueue_gives_each_document_what_fits_it(db_session: AsyncSession) -> None:
    scan = await document(db_session, "c1" * 32)
    voice = await document(db_session, "c2" * 32, kind="media", status="unsupported", mails=2)
    video = await document(db_session, "c3" * 32, kind="media", status="empty")
    logo = await document(
        db_session, "c4" * 32, kind="image", status="unsupported", mails=LOGO_MAILS + 1
    )
    own = await document(db_session, "c5" * 32, kind="media", status="text", body="Text")
    every = [scan, voice, video, logo, own]
    queued = await enqueue(db_session, every, engine="vision", editor="Ben")
    assert (queued.queued, queued.raised, queued.unreadable, queued.logos) == (3, 0, 1, 1)
    only = await enqueue(db_session, every, kind=AiTaskKind.TRANSCRIBE, single=True)
    assert (only.queued, only.raised, only.unreadable, only.logos) == (0, 2, 3, 0)
    ocr = await enqueue(db_session, [voice, logo], kind=AiTaskKind.OCR, include_logos=True)
    assert (ocr.queued, ocr.raised, ocr.unreadable, ocr.logos) == (1, 0, 1, 0)
    tasks = (
        await db_session.execute(
            text(
                "SELECT kind::text AS kind, target_sha256, engine, priority, queued_by "
                "FROM ai_task ORDER BY id"
            )
        )
    ).all()
    assert [(t.kind, t.target_sha256[:2], t.engine, t.priority) for t in tasks] == [
        ("ocr", "c1", "vision", 0),
        ("transcribe", "c2", "auto", PRIORITY_SINGLE),  # always auto: one transcriber
        ("transcribe", "c3", "auto", PRIORITY_SINGLE),
        ("ocr", "c4", "auto", 0),
    ]
    assert {t.queued_by for t in tasks[:3]} == {"Ben"}
    counts = await task_counts(db_session)
    waiting = AiTaskStatus.WAITING
    assert (counts[AiTaskKind.OCR][waiting], counts[AiTaskKind.TRANSCRIBE][waiting]) == (2, 2)
    assert await cancel_tasks(db_session, kind=AiTaskKind.TRANSCRIBE) == 2


async def test_the_media_work_list(db_session: AsyncSession) -> None:
    voice = await document(db_session, "d1" * 32, kind="media", status="unsupported", mails=1)
    busy = await document(db_session, "d2" * 32, kind="media", status="unsupported", mails=4)
    heard = await document(db_session, "d3" * 32, kind="media", status="empty", mails=2)
    await document(db_session, "d4" * 32, kind="media", status="text", body="eigener Text")
    await document(db_session, "d5" * 32, kind="image", status="unsupported")
    assert await work_list_ids(db_session, "media") == [busy, heard, voice]
    await transcribe(db_session, "d3" * 32, [])  # a valid transcript, even without speech
    await transcribe(db_session, "d1" * 32, [line(0, 1, "Hallo")])
    assert await work_list_ids(db_session, "media") == [busy]

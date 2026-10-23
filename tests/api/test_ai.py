"""The AI API (D180 to D189): the status with its services, work lists and estimates, the check
of a service, the queue, the results and discarding them, the send log, the run started and
stopped as a child process, and what documents and hit lines say about machine made texts.

Each test works on its own copy of the imported archive, prepared as a known set of work: three
PDFs made scans (2 pages, 3 pages, pages unknown), the other scans and every other image put out
of the work lists' way, three images of 200 KB, one of them in more than LOGO_MAILS mails, and
three recordings (90 s, 30 s, length unknown), the other recordings put out of the way too.
Results are stored through ai.store, as a run stores them; the run is tests/api/fake_run.py in
place of `mailrobbe ai` (processes.CLI), as in test_imports.py. The service check is replaced
(api.ai.check_service), or asks the fake service of tests/ai/fakes.py, so nothing asks a real
service; the transcriber's files are those of the FakeAudio of tests/ai/fakes.py (D291).

Summaries (milestone 17, D300 to D311) are queued for mails and documents of the archive as it
was imported, with a local text service configured (the fixture texts); their results are rows
inserted as a run would write them (summarized), with AI tags and theme hints.
"""

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mailrobbe.ai.audio import parakeet
from mailrobbe.ai.model import (
    CHARS_PER_TOKEN,
    LOGO_MAILS,
    PRIORITY_FILED,
    PRIORITY_SINGLE,
    SUMMARY_MIN_WORDS,
    SUMMARY_RULE_SECONDS_PER_KTOKEN,
    SUMMARY_RULE_SECONDS_PER_TASK,
    TRANSCRIBE_MODEL,
    OcrPage,
    Service,
    ServiceCheck,
    TranscriptSegment,
    tag_key,
    transcribe_threads,
)
from mailrobbe.ai.store import store_ocr_result, store_transcript_result
from mailrobbe.api import ai as ai_api
from mailrobbe.api.schemas import AI_RULE_SECONDS, AI_RULE_SECONDS_PER_MINUTE
from mailrobbe.config import Settings
from mailrobbe.enums import JobKind
from tests.ai.fakes import MODEL_TOTAL, FakeAudio, fake_service
from tests.api.conftest import api_settings
from tests.api.test_imports import Dashboard, error_code, fake, holding, post, reaped, serve, until
from tests.api.test_mails import Params, get, rows
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

WORD = "Zauberwortocr"  # a word no generated text holds
PREPARE = [
    "UPDATE document SET size_bytes = 1000 WHERE kind = 'image'",
    "UPDATE document SET text_status = 'failed' WHERE text_status = 'scanned'",
    # PDFs with a text, each carried by an original mail of its own
    """CREATE TEMP TABLE scans AS
        SELECT id, row_number() OVER (ORDER BY id) AS n FROM (
            SELECT d.id FROM document d
            WHERE d.kind = 'pdf' AND d.text_status = 'text' AND d.sha256 IS NOT NULL
              AND EXISTS (SELECT 1 FROM attachment a JOIN mail m ON m.id = a.mail_id
                          WHERE a.document_id = d.id AND m.is_duplicate_of IS NULL)
            ORDER BY d.id LIMIT 3) chosen""",
    """UPDATE document d SET text_status = 'scanned', extracted_text = NULL,
        pages = CASE s.n WHEN 1 THEN 2 WHEN 2 THEN 3 END, mails = 4 - s.n
        FROM scans s WHERE s.id = d.id""",
    """CREATE TEMP TABLE images AS
        SELECT id, row_number() OVER (ORDER BY id) AS n FROM (
            SELECT id FROM document
            WHERE kind = 'image' AND sha256 IS NOT NULL AND text_status = 'unsupported'
            ORDER BY id LIMIT 3) chosen""",
    f"""UPDATE document d SET size_bytes = 200000,
        mails = CASE i.n WHEN 3 THEN {LOGO_MAILS + 10} ELSE 1 END
        FROM images i WHERE i.id = d.id""",
    # recordings, each carried by an original mail: the archive's few, made up to three from
    # other files; the other recordings out of the media list's way
    """CREATE TEMP TABLE recordings AS
        SELECT id, row_number() OVER (ORDER BY media DESC, id) AS n FROM (
            SELECT d.id, d.kind = 'media' AS media FROM document d
            WHERE d.kind NOT IN ('pdf', 'image') AND d.sha256 IS NOT NULL
              AND EXISTS (SELECT 1 FROM attachment a JOIN mail m ON m.id = a.mail_id
                          WHERE a.document_id = d.id AND m.is_duplicate_of IS NULL)
            ORDER BY d.kind = 'media' DESC, d.id LIMIT 3) chosen""",
    """UPDATE document d SET text_status = 'failed'
        WHERE d.kind = 'media' AND d.id NOT IN (SELECT id FROM recordings)""",
    """UPDATE document d SET kind = 'media', text_status = 'unsupported', extracted_text = NULL,
        text_origin = 'extracted', mails = 4 - r.n,
        duration = CASE r.n WHEN 1 THEN 90 WHEN 2 THEN 30 END
        FROM recordings r WHERE r.id = d.id""",
]


@dataclass(frozen=True, slots=True)
class Work:
    scans: list[int]  # document ids: 2 pages, 3 pages, pages unknown
    images: list[int]  # the last one a logo
    text: int  # a PDF with a text read from its file
    recordings: list[int]  # 90 s, 30 s, length unknown; in 3, 2 and 1 mails


@pytest.fixture
async def work(mutable_database_url: str) -> Work:
    url = mutable_database_url
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        for statement in PREPARE:
            await connection.execute(text(statement))
        scans = list((await connection.execute(text("SELECT id FROM scans ORDER BY n"))).scalars())
        images = list(
            (await connection.execute(text("SELECT id FROM images ORDER BY n"))).scalars()
        )
        recordings = list(
            (await connection.execute(text("SELECT id FROM recordings ORDER BY n"))).scalars()
        )
        own = await connection.scalar(
            text(
                "SELECT min(id) FROM document WHERE kind = 'pdf' AND text_status = 'text' "
                "AND sha256 IS NOT NULL"
            )
        )
        await connection.commit()
    await engine.dispose()
    assert len(scans) == 3 and len(images) == 3 and own is not None
    assert len(recordings) == 3
    return Work(scans, images, own, recordings)


@pytest.fixture(autouse=True)
def model_files(monkeypatch: pytest.MonkeyPatch) -> FakeAudio:
    """The transcriber's files: 1000 bytes still missing."""
    audio = FakeAudio({}, missing=1000)
    monkeypatch.setattr(parakeet, "model_state", audio.model_state)
    return audio


def ai_settings(url: str, archive: GeneratedArchive, tmp_path: Path, **extra: Any) -> Settings:
    return api_settings(url, archive, tmp_path / "no-frontend").model_copy(update=extra)


@pytest.fixture
async def dashboard(
    work: Work, mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[Dashboard]:
    """The API on the prepared copy, with a local vision service configured."""
    await rows(mutable_database_url, "DELETE FROM job")
    settings = ai_settings(
        mutable_database_url,
        generated_archive,
        tmp_path,
        ai_vision_url="http://host.docker.internal:11434",
        ai_vision_model="vision-test",
    )
    async with serve(settings) as served:
        yield served


@asynccontextmanager
async def session_on(url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
            await session.commit()
    finally:
        await engine.dispose()


async def sha256(url: str, document_id: int) -> str:
    found = await rows(url, "SELECT sha256 FROM document WHERE id = :id", id=document_id)
    return str(found[0].sha256)


async def store(url: str, document_id: int, pages: list[OcrPage], **extra: Any) -> int:
    """An OCR result for the document's content, stored as a run stores it."""
    async with session_on(url) as session:
        stored = await store_ocr_result(
            session,
            sha256=await sha256(url, document_id),
            pages=pages,
            pages_total=extra.get("pages_total"),
            model=extra.get("model"),
            service_url=None,
            remote=False,
            prompt_version=1,
            options={},
            seconds=2.5,
            job_id=extra.get("job_id"),
        )
    return stored.result_id


def recognised(*texts: str) -> list[OcrPage]:
    return [OcrPage(number=n, engine="tesseract", text=t) for n, t in enumerate(texts, start=1)]


async def status(dashboard: Dashboard) -> Any:
    return await get(dashboard.client, "/api/ai/status")


def work_list(found: Any, key: str) -> Any:
    return next(entry for entry in found["work_lists"] if entry["key"] == key)


# Status ----------------------------------------------------------------------------------------


async def test_status_shows_the_service_the_work_lists_and_their_estimates(
    dashboard: Dashboard,
) -> None:
    found = await status(dashboard)
    assert found["enabled"] and found["vision"]
    assert found["services"] == [
        {
            "capability": "vision",
            "url": "http://host.docker.internal:11434",
            "model": "vision-test",
            "protocol": "auto",
            "locality": "local",
            "refused": None,
            "key": False,
        }
    ]
    assert found["queue"]["ocr"] == dict.fromkeys(
        ("waiting", "running", "done", "failed", "cancelled"), 0
    )
    scanned = work_list(found, "scanned")
    # 2 + 3 known pages; the third scan counts as one page in the estimate
    assert (scanned["documents"], scanned["pages"], scanned["without_pages"]) == (3, 5, 1)
    assert scanned["engine"] == "tesseract"
    estimates = {estimate["engine"]: estimate for estimate in scanned["estimates"]}
    assert estimates["tesseract"] == {
        "engine": "tesseract",
        "model": "",
        "seconds": 6 * AI_RULE_SECONDS["tesseract"],
        "estimated": True,
        "seconds_per_page": AI_RULE_SECONDS["tesseract"],
        "seconds_per_minute": None,
    }
    assert estimates["vision"]["seconds"] == 6 * AI_RULE_SECONDS["vision"]
    images = work_list(found, "images")  # the logo is left out (D186)
    assert (images["documents"], images["pages"], images["bytes"]) == (2, 2, 400_000)
    assert images["engine"] == "vision"
    assert found["job"] is None and found["remote_used"] is False
    assert found["defaults"]["vision_model"] == "vision-test"


async def test_a_measured_speed_replaces_the_rule_of_thumb(dashboard: Dashboard) -> None:
    await rows(
        dashboard.url,
        """INSERT INTO ai_calibration (kind, engine, model, unit, seconds_per_unit, samples)
           VALUES ('ocr', 'tesseract', '', 'page', 2.5, 40)""",
    )
    estimates = work_list(await status(dashboard), "scanned")["estimates"]
    tesseract = next(estimate for estimate in estimates if estimate["engine"] == "tesseract")
    assert (tesseract["seconds"], tesseract["estimated"]) == (15.0, False)
    vision = next(estimate for estimate in estimates if estimate["engine"] == "vision")
    assert vision["estimated"] is True


async def test_a_remote_service_is_refused_without_the_permission(
    work: Work, mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    remote = "https://203.0.113.5/v1"  # TEST-NET-3: public, never looked up
    settings = ai_settings(mutable_database_url, generated_archive, tmp_path, ai_vision_url=remote)
    async with serve(settings) as served:
        found = await status(served)
        assert found["vision"] is False and found["remote_used"] is True
        [service] = found["services"]
        assert service["locality"] == "remote"
        assert "MAILROBBE_AI_ALLOW_REMOTE" in service["refused"]
        # without a usable vision model, everything goes to Tesseract (D182)
        assert work_list(found, "images")["engine"] == "tesseract"
        assert [e["engine"] for e in work_list(found, "images")["estimates"]] == ["tesseract"]
        body = {"work_list": "images", "engine": "vision"}
        assert await error_code(served.client, "/api/ai/tasks", body, 400) == "invalid_option"
    allowed = settings.model_copy(update={"ai_allow_remote": True})
    async with serve(allowed) as served:
        [service] = (await status(served))["services"]
        assert service["refused"] is None


async def test_without_a_service_only_tesseract_reads(
    work: Work, mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    async with serve(ai_settings(mutable_database_url, generated_archive, tmp_path)) as served:
        found = await status(served)
        assert (found["enabled"], found["vision"], found["services"]) == (True, False, [])
        assert found["defaults"]["vision_url"] == ""
        assert (found["text"], found["defaults"]["text_url"]) == (False, "")
        assert await error_code(served.client, "/api/ai/services/vision/check", {}, 404) == (
            "not_found"
        )


async def test_the_check_asks_the_service(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[Service] = []

    def check(service: Service, settings: Settings) -> ServiceCheck:
        asked.append(service)
        return ServiceCheck(
            capability="vision",
            url=service.display_url,
            locality="local",
            reachable=True,
            protocol="ollama",
            model=service.model,
            model_found=True,
            test="passed",
            test_detail="MAILROBBE",
            seconds=1.5,
        )

    monkeypatch.setattr(ai_api, "check_service", check)
    found = await post(dashboard.client, "/api/ai/services/vision/check", {})
    assert (found["test"], found["protocol"], found["seconds"]) == ("passed", "ollama", 1.5)
    assert [service.model for service in asked] == ["vision-test"]


async def test_the_check_runs_the_real_test_against_a_service(
    work: Work, mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    answer = "robbe\u20107342\nPrüfung der Texterkennung"
    with fake_service("ollama", models={"vision-test": True}, answer=answer) as fake:
        settings = ai_settings(
            mutable_database_url,
            generated_archive,
            tmp_path,
            ai_vision_url=fake.url,
            ai_vision_model="vision-test",
        )
        async with serve(settings) as served:
            found = await post(served.client, "/api/ai/services/vision/check", {})
        assert len(fake.chats) == 1
    assert (found["reachable"], found["protocol"], found["model_found"]) == (True, "ollama", True)
    assert (found["test"], found["error"], found["locality"]) == ("passed", None, "local")
    assert [model["name"] for model in found["models"]] == ["vision-test"]


# Queue -----------------------------------------------------------------------------------------


async def queue(dashboard: Dashboard, body: dict[str, Any], status: int = 200) -> Any:
    return await post(dashboard.client, "/api/ai/tasks", body, status)


async def tasks(dashboard: Dashboard, params: Params = ()) -> list[Any]:
    found = await get(dashboard.client, "/api/ai/tasks", params)
    items: list[Any] = found["items"]
    return items


async def test_a_work_list_is_queued_once_and_raised_after(
    dashboard: Dashboard, work: Work
) -> None:
    body = {"work_list": "scanned"}
    assert await queue(dashboard, body) == {
        "queued": 3,
        "raised": 0,
        "unreadable": 0,
        "logos": 0,
        "run": None,
        "short": 0,
        "estimate": None,
    }
    assert await queue(dashboard, body) == {
        "queued": 0,
        "raised": 3,
        "unreadable": 0,
        "logos": 0,
        "run": None,
        "short": 0,
        "estimate": None,
    }
    listed = await tasks(dashboard)
    # Newest first; a work list is queued by its mails, so the scans' order is the archive's.
    assert [task["id"] for task in listed] == sorted((task["id"] for task in listed), reverse=True)
    assert sorted(task["document"]["id"] for task in listed) == sorted(work.scans)
    assert {task["status"] for task in listed} == {"waiting"}
    pages = {task["document"]["id"]: task["document"]["pages"] for task in listed}
    assert [pages[scan] for scan in work.scans] == [2, 3, None]
    images = await queue(dashboard, {"work_list": "images", "engine": "vision"})
    assert images["queued"] == 2  # the logo is not on the list at all
    assert (await status(dashboard))["queue"]["ocr"]["waiting"] == 5


async def test_ids_leave_out_logos_and_what_ocr_cannot_read(
    dashboard: Dashboard, work: Work
) -> None:
    body = {"document_ids": [*work.images, work.text, 2**40], "include_logos": False}
    assert await queue(dashboard, body) == {
        "queued": 2,
        "raised": 0,
        "unreadable": 2,
        "logos": 1,
        "run": None,
        "short": 0,
        "estimate": None,
    }
    with_logos = await queue(dashboard, {"document_ids": work.images, "include_logos": True})
    assert (with_logos["queued"], with_logos["raised"]) == (1, 2)


async def test_one_document_from_its_page_goes_first(dashboard: Dashboard, work: Work) -> None:
    await queue(dashboard, {"work_list": "scanned"})
    single = {"document_ids": [work.scans[2]], "single": True, "engine": "vision"}
    assert (await queue(dashboard, single))["raised"] == 1
    by_document = {task["document"]["id"]: task for task in await tasks(dashboard)}
    assert by_document[work.scans[2]]["priority"] == PRIORITY_SINGLE
    assert by_document[work.scans[2]]["engine"] == "vision"
    assert by_document[work.scans[0]]["priority"] == 0


async def test_the_document_list_filters_are_queued_by_its_own_conditions(
    dashboard: Dashboard, work: Work
) -> None:
    filters = {"kind": ["pdf"], "text_status": ["scanned", "text"]}
    queued = await queue(dashboard, {"filters": filters})
    assert queued == {
        "queued": 3,
        "raised": 0,
        "unreadable": 0,
        "logos": 0,
        "run": None,
        "short": 0,
        "estimate": None,
    }
    summary = await get(
        dashboard.client, "/api/documents/summary", [("kind", "pdf"), ("text_status", "scanned")]
    )
    assert summary["ocr_readable"] == 3
    images = await get(dashboard.client, "/api/documents/summary", [("kind", "image")])
    unhashed = await rows(
        dashboard.url, "SELECT count(*) FROM document WHERE kind = 'image' AND sha256 IS NULL"
    )
    assert images["ocr_readable"] == images["total"] - unhashed[0][0]


async def test_a_selection_is_one_thing_and_bounded(
    dashboard: Dashboard, work: Work, monkeypatch: pytest.MonkeyPatch
) -> None:
    both = {"work_list": "scanned", "document_ids": [1]}
    assert await error_code(dashboard.client, "/api/ai/tasks", both, 400) == "invalid_selection"
    assert await error_code(dashboard.client, "/api/ai/tasks", {}, 400) == "invalid_selection"
    monkeypatch.setattr(ai_api, "AI_QUEUE_LIMIT", 2)
    body = {"filters": {"kind": ["pdf"]}}
    assert await error_code(dashboard.client, "/api/ai/tasks", body, 400) == "too_many_documents"


async def test_tasks_page_newest_first_and_filter_by_status(
    dashboard: Dashboard, work: Work
) -> None:
    await queue(dashboard, {"work_list": "scanned"})
    first = await get(dashboard.client, "/api/ai/tasks", [("limit", "2")])
    assert len(first["items"]) == 2 and first["next_cursor"] is not None
    rest = await get(
        dashboard.client, "/api/ai/tasks", [("limit", "2"), ("cursor", first["next_cursor"])]
    )
    ids = [task["id"] for task in first["items"] + rest["items"]]
    assert ids == sorted(ids, reverse=True) and len(ids) == 3 and rest["next_cursor"] is None
    assert await tasks(dashboard, [("status", "failed")]) == []
    await get(dashboard.client, "/api/ai/tasks", [("cursor", "result:1")], status=400)


async def test_waiting_tasks_are_cancelled_and_queued_again(
    dashboard: Dashboard, work: Work
) -> None:
    await queue(dashboard, {"work_list": "scanned"})
    one = (await tasks(dashboard))[0]["id"]
    assert await post(dashboard.client, "/api/ai/tasks/cancel", {"ids": [one]}) == {"changed": 1}
    assert await post(dashboard.client, "/api/ai/tasks/cancel", {"all": True}) == {"changed": 2}
    await rows(
        dashboard.url, "UPDATE ai_task SET status = 'failed', error = 'x' WHERE id = :id", id=one
    )
    retried = await post(dashboard.client, "/api/ai/tasks/retry", {"ids": [one]})
    assert retried == {"changed": 1}
    by_id = {task["id"]: task for task in await tasks(dashboard)}
    assert (by_id[one]["status"], by_id[one]["error"], by_id[one]["attempts"]) == (
        "waiting",
        None,
        0,
    )
    assert await post(dashboard.client, "/api/ai/tasks/retry", {"all": True}) == {"changed": 2}
    for body in ({}, {"ids": [one], "all": True}):
        code = await error_code(dashboard.client, "/api/ai/tasks/retry", body, 400)
        assert code == "invalid_selection"


async def test_a_task_shows_the_pages_read_so_far(dashboard: Dashboard, work: Work) -> None:
    await queue(dashboard, {"document_ids": [work.scans[1]]})
    partial = '{"pages": [{"number": 1, "engine": "tesseract", "text": "a"}], "pages_total": 3}'
    await rows(
        dashboard.url,
        "UPDATE ai_task SET status = 'running', partial = CAST(:p AS jsonb)",
        p=partial,
    )
    [task] = await tasks(dashboard)
    assert (task["status"], task["pages_read"], task["pages_total"]) == ("running", 1, 3)
    detail = await get(dashboard.client, f"/api/documents/{work.scans[1]}")
    assert detail["ai"] == {
        "result": None,
        "task": {"id": task["id"], "status": "running", "engine": "auto", "pages_read": 1},
    }


# Results ---------------------------------------------------------------------------------------


async def test_results_say_what_their_pages_hold(dashboard: Dashboard, work: Work) -> None:
    pages = [
        OcrPage(number=1, engine="tesseract", text="Erste Seite", confidence=90),
        OcrPage(number=2, engine="vision", text="Notiz", uncertain=True),
        OcrPage(number=3, engine="tesseract", error="timed out"),
    ]
    result = await store(dashboard.url, work.scans[1], pages, pages_total=3, model="vision-test")
    [item] = (await get(dashboard.client, "/api/ai/results"))["items"]
    assert item["id"] == result and item["document"]["id"] == work.scans[1]
    assert (item["engine"], item["model"], item["state"]) == ("mixed", "vision-test", "valid")
    assert (item["pages_read"], item["pages_text"], item["pages_total"]) == (3, 2, 3)
    assert (item["uncertain"], item["failed"]) == ([2], [3])
    assert item["characters"] == len("Erste Seite\n\f\nNotiz")
    detail = await get(dashboard.client, f"/api/documents/{work.scans[1]}")
    assert detail["text_origin"] == "ocr" and detail["text_status"] == "text"
    assert detail["ocr_readable"] is True and detail["ai"]["task"] is None
    assert detail["ai"]["result"] == {
        "id": result,
        "engine": "mixed",
        "model": "vision-test",
        "remote": False,
        "created_at": item["created_at"],
        "pages_total": 3,
        "pages_read": 3,
        "pages_text": 2,
        "uncertain": [2],
        "failed": [3],
        "characters": item["characters"],
    }
    own = await get(dashboard.client, f"/api/documents/{work.text}")
    assert (own["text_origin"], own["ai"], own["ocr_readable"]) == ("extracted", None, False)


async def test_discarding_brings_back_what_the_import_found(
    dashboard: Dashboard, work: Work
) -> None:
    result = await store(dashboard.url, work.scans[0], recognised("Text"))
    path = f"/api/ai/results/{result}/discard"
    response = await dashboard.client.post(path, json={}, headers={"X-Mailrobbe-Editor": "Aaron"})
    assert response.status_code == 200 and response.json() == {"changed": 1}
    detail = await get(dashboard.client, f"/api/documents/{work.scans[0]}")
    assert (detail["text_status"], detail["text_origin"]) == ("scanned", "extracted")
    assert detail["ai"] is None  # the discarded result is no longer the document's
    [item] = (await get(dashboard.client, "/api/ai/results", [("state", "discarded")]))["items"]
    assert item["discarded_by"] == "Aaron"
    assert await error_code(dashboard.client, path, {}, 404) == "not_found"
    # back on the work list
    assert work_list(await status(dashboard), "scanned")["documents"] == 3


async def test_a_runs_results_are_discarded_together(dashboard: Dashboard, work: Work) -> None:
    [job] = await rows(
        dashboard.url,
        "INSERT INTO job (kind, origin, status) VALUES ('ai', 'cli', 'done') RETURNING id",
    )
    for document_id in work.scans[:2]:
        await store(dashboard.url, document_id, recognised("Text"), job_id=job.id)
    other = await store(dashboard.url, work.scans[2], recognised("Text"))
    found = await get(dashboard.client, "/api/ai/results", [("job_id", str(job.id))])
    assert len(found["items"]) == 2
    assert await post(dashboard.client, f"/api/ai/jobs/{job.id}/discard", {}) == {"changed": 2}
    valid = (await get(dashboard.client, "/api/ai/results", [("state", "valid")]))["items"]
    assert [item["id"] for item in valid] == [other]


async def test_the_send_log_lists_what_went_out(dashboard: Dashboard, work: Work) -> None:
    content = await sha256(dashboard.url, work.images[0])
    await rows(
        dashboard.url,
        """INSERT INTO ai_send_log (service_url, kind, target_sha256, bytes)
           VALUES ('https://203.0.113.5/v1', 'ocr', :sha, 1234)""",
        sha=content,
    )
    found = await get(dashboard.client, "/api/ai/send-log")
    assert found["total"] == 1 and found["next_cursor"] is None
    [item] = found["items"]
    assert (item["bytes"], item["document"]["id"]) == (1234, work.images[0])
    assert (await status(dashboard))["remote_used"] is True


# Documents and hit lines -----------------------------------------------------------------------


async def carrier(url: str, document_id: int) -> int:
    found = await rows(
        url,
        """SELECT min(m.id) FROM attachment a JOIN mail m ON m.id = a.mail_id
           WHERE a.document_id = :id AND m.is_duplicate_of IS NULL""",
        id=document_id,
    )
    return int(found[0][0])


async def test_the_document_list_filters_and_marks_machine_texts(
    dashboard: Dashboard, work: Work
) -> None:
    await store(dashboard.url, work.scans[0], recognised(f"{WORD} im Scan"))
    found = await get(dashboard.client, "/api/documents", [("text_origin", "ocr")])
    assert [(item["id"], item["text_origin"]) for item in found["items"]] == [
        (work.scans[0], "ocr")
    ]
    extracted = await get(dashboard.client, "/api/documents", [("text_origin", "extracted")])
    assert work.scans[0] not in {item["id"] for item in extracted["items"]}
    assert {item["text_origin"] for item in extracted["items"]} == {"extracted"}
    searched = await get(dashboard.client, "/api/documents", [("q", WORD)])
    assert [item["id"] for item in searched["items"]] == [work.scans[0]]


async def test_hit_lines_say_when_the_text_is_machine_made(
    dashboard: Dashboard, work: Work
) -> None:
    await store(dashboard.url, work.scans[0], recognised(f"{WORD} im Scan"))
    mail = await carrier(dashboard.url, work.scans[0])
    listed = await get(dashboard.client, "/api/mails", [("q", WORD)])
    item = next(item for item in listed["items"] if item["id"] == mail)
    assert (item["attachment_match"], item["attachment_machine"]) == (True, True)
    assert item["attachment_transcript"] is False  # recognised, not transcribed
    hits = await get(dashboard.client, f"/api/mails/{mail}/hits", [("q", WORD)])
    [hit] = hits["attachments"]
    assert (hit["in_text"], hit["machine"]) == (True, True)
    # the mail's attachment list says so too (D280)
    detail = await get(dashboard.client, f"/api/mails/{mail}")
    ocr = {item["document_id"]: item["ocr"] for item in detail["attachments"]}
    assert ocr[work.scans[0]] == "recognised"
    # a word of a text read from the file is no machine hit
    word = await rows(
        dashboard.url,
        """SELECT w FROM regexp_split_to_table((SELECT extracted_text FROM document
           WHERE id = :id), '\\W+') w WHERE length(w) > 8 LIMIT 1""",
        id=work.text,
    )
    own = await carrier(dashboard.url, work.text)
    plain = await get(dashboard.client, f"/api/mails/{own}/hits", [("q", word[0][0])])
    assert plain["attachments"] and not any(hit["machine"] for hit in plain["attachments"])


# The run ---------------------------------------------------------------------------------------


async def test_a_run_starts_with_the_defaults_and_stops(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    body = {"engine": "tesseract", "max_pages": 7, "max_minutes": 30}
    job = await post(dashboard.client, "/api/ai/run", body, 202)
    assert (job["kind"], job["origin"], job["alive"]) == ("ai", "ui", True)
    assert (job["options"]["ocr_engine"], job["options"]["max_pages"]) == ("tesseract", 7)
    assert job["options"]["max_minutes"] == 30
    assert job["options"]["vision_model"] == "vision-test"
    # an import waits for it, and the dashboard shows it
    start = await error_code(dashboard.client, "/api/import/start", {}, 409)
    assert start == "job_running"
    assert (await get(dashboard.client, "/api/import/status"))["ai_job"]["id"] == job["id"]
    stopped = await post(dashboard.client, "/api/ai/run/stop", {})
    assert stopped["stop_requested"] is True
    await reaped(dashboard)

    async def ended() -> bool:
        return bool((await status(dashboard))["job"]["status"] == "stopped")

    await until(ended)
    # the next start takes the settings again, not the latest run's choice (D315)
    defaults = (await status(dashboard))["defaults"]
    assert (defaults["max_pages"], defaults["max_minutes"]) == (50, 180)
    assert await error_code(dashboard.client, "/api/ai/run/stop", {}, 409) == "no_job"


async def test_a_document_starts_a_run_of_its_own(
    dashboard: Dashboard, work: Work, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    await queue(dashboard, {"work_list": "scanned"})
    body = {"document_ids": [work.scans[1]], "single": True, "start": True}
    assert (await queue(dashboard, body))["run"] == "started"
    job = (await status(dashboard))["job"]
    assert job["alive"] and job["options"]["documents"] == [work.scans[1]]
    detail = await get(
        dashboard.client, f"/api/mails/{await carrier(dashboard.url, work.scans[1])}"
    )
    ocr = {item["document_id"]: item["ocr"] for item in detail["attachments"]}
    assert ocr[work.scans[1]] == "queued"
    # while it lives, another document is queued first and taken next
    again = {"document_ids": [work.scans[0]], "single": True, "start": True}
    assert (await queue(dashboard, again))["run"] == "running"
    await post(dashboard.client, "/api/ai/run/stop", {})
    await reaped(dashboard)
    # an import keeps it from starting; the document waits in the queue
    async with holding(dashboard.url, JobKind.IMPORT):
        assert (await queue(dashboard, again))["run"] == "busy"
    unreadable = {"document_ids": [work.text], "start": True}
    assert (await queue(dashboard, unreadable))["run"] is None
    selection = {"work_list": "scanned", "start": True}
    assert (
        await error_code(dashboard.client, "/api/ai/tasks", selection, 400) == "invalid_selection"
    )


async def test_a_run_waits_for_an_import(
    dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "done")
    async with holding(dashboard.url, JobKind.IMPORT):
        assert await error_code(dashboard.client, "/api/ai/run", {}, 409) == "job_running"
    control = {"engine": "vision", "vision_model": "a\x00b"}
    assert await error_code(dashboard.client, "/api/ai/run", control, 400) == "invalid_option"
    assert (await status(dashboard))["job"] is None


# Summaries (milestone 17, D300 to D311) --------------------------------------------------------

TEXT_SERVICE: dict[str, Any] = {
    "ai_text_url": "http://host.docker.internal:1234/v1",
    "ai_text_model": "text-test",
}
SUMMARY_OPTIONS: dict[str, Any] = {
    "short": False,
    "words": 180,
    "origin": None,
    "dropped_tags": 0,
    "dropped_themes": 0,
    "context_tokens": 8192,
}
# Mails whose text has at least SUMMARY_MIN_WORDS words (\s+ doubled for the SQL string).
WORDS = (
    "COALESCE(array_length(regexp_split_to_array(btrim(COALESCE(body_text, '')), '\\s+'), 1), 0)"
)


@pytest.fixture
async def texts(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[Dashboard]:
    """The API on a copy of the imported archive, with a local text service configured."""
    await rows(mutable_database_url, "DELETE FROM job")
    settings = ai_settings(mutable_database_url, generated_archive, tmp_path, **TEXT_SERVICE)
    async with serve(settings) as served:
        yield served


async def summarized(
    url: str,
    target: str,
    content: str,
    body: str = "Der Vorstand bespricht die Spendenquittungen des Vereins.",
    *,
    tags: Sequence[str] = (),
    themes: Sequence[tuple[str, str, int | None]] = (),
    parts: Sequence[dict[str, Any]] = ({"number": 1, "characters": 900, "summary": "Teil"},),
    parts_total: int | None = None,
    options: dict[str, Any] | None = None,
    state: str = "valid",
    thread_id: int | None = None,
) -> int:
    """A summary of a mail's, a document's or a thread's content with its AI tags and theme
    hints, as a run stores it (ai_result of kind summarize, D300, D316)."""
    async with session_on(url) as session:
        result_id = await session.scalar(
            text("""
                INSERT INTO ai_result (kind, target, target_sha256, thread_id, engine, model,
                    remote, prompt_version, options, body, pages, pages_total, seconds, state)
                VALUES ('summarize', :target, :content, :thread, 'text', 'text-test', false, 1,
                    CAST(:options AS jsonb), :body, CAST(:pages AS jsonb), :total, 4.5,
                    CAST(:state AS ai_result_state))
                RETURNING id
            """),
            {
                "target": target,
                "content": content,
                "thread": thread_id,
                "options": json.dumps(SUMMARY_OPTIONS if options is None else options),
                "body": body,
                "pages": json.dumps(list(parts)),
                "total": len(parts) if parts_total is None else parts_total,
                "state": state,
            },
        )
        for label in tags:
            tag_id = await session.scalar(
                text("""
                    INSERT INTO ai_tag (key, label) VALUES (:key, :label)
                    ON CONFLICT (key) DO UPDATE SET key = EXCLUDED.key RETURNING id
                """),
                {"key": tag_key(label), "label": label},
            )
            await session.execute(
                text("INSERT INTO ai_tag_link (result_id, tag_id) VALUES (:result, :tag)"),
                {"result": result_id, "tag": tag_id},
            )
        for theme, quote, position in themes:
            await session.execute(
                text("""
                    INSERT INTO ai_theme_hint (result_id, theme, quote, position)
                    VALUES (:result, :theme, :quote, :position)
                """),
                {"result": result_id, "theme": theme, "quote": quote, "position": position},
            )
    assert result_id is not None
    return int(result_id)


async def original_mails(url: str, count: int) -> list[Any]:
    """Mails with a content of their own (no duplicates), a text of at least SUMMARY_MIN_WORDS
    words and no attachment, by id: summarising one from its page queues its attachments too
    (D317), and which mail gets an id depends on the import's workers."""
    return await rows(
        url,
        f"""SELECT id, raw_sha256, subject, date_utc,
               length(COALESCE(subject, '')) + length(COALESCE(body_text, '')) AS characters
           FROM mail m
           WHERE NOT EXISTS (SELECT 1 FROM mail o WHERE o.raw_sha256 = m.raw_sha256
                             AND o.id <> m.id)
             AND {WORDS} >= {SUMMARY_MIN_WORDS}
             AND NOT EXISTS (SELECT 1 FROM attachment a WHERE a.mail_id = m.id)
           ORDER BY id LIMIT :count""",
        count=count,
    )


async def text_document(url: str) -> int:
    """A document with a SHA-256 and a text: one that can be summarised (D302)."""
    found = await rows(
        url,
        """SELECT min(id) FROM document
           WHERE sha256 IS NOT NULL AND COALESCE(extracted_text, '') <> ''""",
    )
    return int(found[0][0])


async def summary_tasks(dashboard: Dashboard) -> list[Any]:
    return [task for task in await tasks(dashboard) if task["kind"] == "summarize"]


async def test_status_says_whether_a_text_service_is_usable(
    texts: Dashboard, mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    found = await status(texts)
    assert found["text"] is True and found["vision"] is False
    assert found["services"] == [
        {
            "capability": "text",
            "url": "http://host.docker.internal:1234/v1",
            "model": "text-test",
            "protocol": "auto",
            "locality": "local",
            "refused": None,
            "key": False,
        }
    ]
    assert (found["defaults"]["text_model"], found["defaults"]["text_url"]) == (
        "text-test",
        "http://host.docker.internal:1234/v1",
    )
    assert found["queue"]["summarize"]["waiting"] == 0
    remote = ai_settings(
        mutable_database_url,
        generated_archive,
        tmp_path,
        ai_text_url="https://203.0.113.5/v1",  # TEST-NET-3: public, never looked up
        ai_text_model="text-test",
    )
    async with serve(remote) as served:
        refused = await status(served)
        assert refused["text"] is False and refused["remote_used"] is True
        body = {"kind": "summarize", "mail_ids": [1], "preview": True}
        assert await error_code(served.client, "/api/ai/tasks", body, 400) == "invalid_option"


async def test_mails_and_documents_are_queued_for_summaries(texts: Dashboard) -> None:
    [first, second] = await original_mails(texts.url, 2)
    [duplicate] = await rows(
        texts.url,
        """SELECT m.id, o.id AS original FROM mail m
           JOIN mail o ON o.raw_sha256 = m.raw_sha256 AND o.id < m.id
           WHERE COALESCE(m.body_text, '') <> ''
           ORDER BY m.id LIMIT 1""",
    )
    body = {
        "kind": "summarize",
        "mail_ids": [first.id, second.id, duplicate.id, duplicate.original, 2**40],
    }
    queued = await queue(texts, body)
    # byte-identical copies share one task (D301); an unknown id cannot be summarised
    assert (queued["queued"], queued["raised"], queued["unreadable"], queued["logos"]) == (
        3,
        0,
        1,
        0,
    )
    assert queued["run"] is None and queued["estimate"]["tasks"] == 3
    listed = {task["mail"]["id"]: task for task in await summary_tasks(texts)}
    # a content is shown by its earliest mail
    assert sorted(listed) == sorted([first.id, second.id, duplicate.original])
    task = listed[first.id]
    assert (task["target"], task["document"], task["status"], task["priority"]) == (
        "mail",
        None,
        "waiting",
        0,
    )
    assert task["mail"]["subject"] == first.subject and task["mail"]["date"] is not None
    again = await queue(texts, {"kind": "summarize", "mail_ids": [first.id], "single": True})
    assert (again["queued"], again["raised"]) == (0, 1)
    raised = {task["mail"]["id"]: task for task in await summary_tasks(texts)}[first.id]
    assert raised["priority"] == PRIORITY_SINGLE
    document = await text_document(texts.url)
    [empty] = await rows(
        texts.url,
        "SELECT id FROM document WHERE COALESCE(extracted_text, '') = '' ORDER BY id LIMIT 1",
    )
    queued = await queue(texts, {"kind": "summarize", "document_ids": [document, empty.id]})
    assert (queued["queued"], queued["unreadable"]) == (1, 1)
    [task] = [task for task in await summary_tasks(texts) if task["target"] == "document"]
    assert (task["document"]["id"], task["mail"]) == (document, None)
    assert (await status(texts))["queue"]["summarize"]["waiting"] == 4


async def test_a_preview_counts_and_estimates_without_writing(texts: Dashboard) -> None:
    mails = await original_mails(texts.url, 3)
    [short] = await rows(
        texts.url,
        f"""SELECT id, length(COALESCE(subject, '')) + length(COALESCE(body_text, ''))
               AS characters
           FROM mail m
           WHERE COALESCE(subject, '') <> '' AND {WORDS} < {SUMMARY_MIN_WORDS}
             AND NOT EXISTS (SELECT 1 FROM mail o WHERE o.raw_sha256 = m.raw_sha256
                             AND o.id <> m.id)
           ORDER BY id LIMIT 1""",
    )
    body = {"kind": "summarize", "mail_ids": [*(mail.id for mail in mails), short.id]}
    preview = await queue(texts, {**body, "preview": True})
    characters = sum(mail.characters for mail in mails) + short.characters
    tokens = round(characters / CHARS_PER_TOKEN) + 100 * 4
    assert (preview["queued"], preview["raised"], preview["short"]) == (4, 0, 1)
    assert preview["estimate"] == {
        "model": "text-test",
        "tasks": 4,
        "tokens": tokens,
        "seconds": pytest.approx(
            4 * SUMMARY_RULE_SECONDS_PER_TASK + tokens / 1000 * SUMMARY_RULE_SECONDS_PER_KTOKEN
        ),
        "estimated": True,
    }
    assert await summary_tasks(texts) == []
    await rows(
        texts.url,
        """INSERT INTO ai_calibration (kind, engine, model, unit, seconds_per_unit, samples)
           VALUES ('summarize', 'text', 'text-test', 'ktoken', 2.0, 30)""",
    )
    measured = (await queue(texts, {**body, "preview": True}))["estimate"]
    assert (measured["seconds"], measured["estimated"]) == (pytest.approx(tokens / 500), False)
    # queued for real, the estimate is the queued tasks'
    queued = await queue(texts, body)
    assert (queued["queued"], queued["short"], queued["estimate"]["tokens"]) == (4, 1, tokens)
    assert len(await summary_tasks(texts)) == 4


async def test_an_akte_or_a_filter_of_the_mail_list_is_queued(
    texts: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    mails = await original_mails(texts.url, 3)
    [akte] = await rows(
        texts.url, "INSERT INTO collection (name) VALUES ('Spenden 2019') RETURNING id"
    )
    for mail in mails:
        await rows(
            texts.url,
            "INSERT INTO collection_mail (collection_id, mail_sha256) VALUES (:c, :sha)",
            c=akte.id,
            sha=mail.raw_sha256,
        )
    body = {"kind": "summarize", "mail_filters": {"collection": [akte.id]}}
    queued = await queue(texts, body)
    assert (queued["queued"], queued["unreadable"]) == (3, 0)
    # what an Akte holds comes after one element from its page and before the rest (D308)
    assert {task["priority"] for task in await summary_tasks(texts)} == {PRIORITY_FILED}
    monkeypatch.setattr(ai_api, "AI_QUEUE_LIMIT", 2)
    assert await error_code(texts.client, "/api/ai/tasks", body, 400) == "too_many_mails"
    unusable = {"kind": "summarize", "mail_filters": {"q": "before:gestern"}}
    assert await error_code(texts.client, "/api/ai/tasks", unusable, 400) == "invalid_query"


async def test_the_document_list_filters_queue_documents_with_a_text(
    texts: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    [figures] = await rows(
        texts.url,
        """SELECT count(*) FILTER (WHERE sha256 IS NOT NULL
                                  AND COALESCE(extracted_text, '') <> '') AS summarizable,
               count(*) AS documents
           FROM document WHERE kind = 'pdf'""",
    )
    assert 2 < figures.summarizable < figures.documents
    body = {"kind": "summarize", "filters": {"kind": ["pdf"]}}
    queued = await queue(texts, body)
    assert (queued["queued"], queued["unreadable"]) == (figures.summarizable, 0)
    assert {task["target"] for task in await summary_tasks(texts)} == {"document"}
    monkeypatch.setattr(ai_api, "AI_QUEUE_LIMIT", 2)
    assert await error_code(texts.client, "/api/ai/tasks", body, 400) == "too_many_documents"


async def test_a_summary_selection_is_one_thing(texts: Dashboard, dashboard: Dashboard) -> None:
    selections: list[dict[str, Any]] = [
        {"kind": "summarize"},
        {"kind": "summarize", "mail_ids": [1], "document_ids": [1]},
        {"kind": "summarize", "mail_filters": {}, "filters": {}},
        {"mail_ids": [1]},  # mails are summarised only
        {"document_ids": [1], "mail_filters": {}},
        {"kind": "summarize", "everything": True, "mail_ids": [1]},
        {"kind": "summarize", "thread_ids": [1], "document_ids": [1]},
    ]
    for body in selections:
        assert await error_code(texts.client, "/api/ai/tasks", body, 400) == "invalid_selection"
    options: list[dict[str, Any]] = [
        {"kind": "summarize", "work_list": "scanned"},
        {"document_ids": [1], "preview": True},  # a preview is made for summaries only
    ]
    for body in options:
        assert await error_code(texts.client, "/api/ai/tasks", body, 400) == "invalid_option"
    # without a text service there is nothing to summarise with, not even for a preview
    for preview in (False, True):
        body = {"kind": "summarize", "mail_ids": [1], "preview": preview}
        assert await error_code(dashboard.client, "/api/ai/tasks", body, 400) == "invalid_option"
    assert (await status(dashboard))["text"] is False


async def test_an_element_starts_a_run_of_its_own(
    texts: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    [mail] = await original_mails(texts.url, 1)
    body = {"kind": "summarize", "mail_ids": [mail.id], "single": True, "start": True}
    assert (await queue(texts, body))["run"] == "started"
    job = (await status(texts))["job"]
    # the mail takes its attachments along (D317)
    attached = sorted(
        task["document"]["id"] for task in await summary_tasks(texts) if task["document"]
    )
    assert job["alive"] and (job["options"]["mails"], job["options"]["documents"]) == (
        [mail.id],
        attached,
    )
    assert job["options"]["text_model"] == "text-test"
    # the card follows the live run's steps (D318)
    found = await get(texts.client, "/api/ai/summary", [("mail", str(mail.id))])
    assert found["task"] is not None and found["run"]["id"] == job["id"]
    # while it lives, the next element is queued first and taken next
    document = await text_document(texts.url)
    other = {"kind": "summarize", "document_ids": [document], "single": True, "start": True}
    assert (await queue(texts, other))["run"] == "running"
    await post(texts.client, "/api/ai/run/stop", {})
    await reaped(texts)
    async with holding(texts.url, JobKind.IMPORT):
        assert (await queue(texts, other))["run"] == "busy"
    # a filter starts a run of the whole queue
    filtered = {"kind": "summarize", "filters": {"kind": ["pdf"]}, "start": True}
    assert (await queue(texts, filtered))["run"] == "started"
    job = (await status(texts))["job"]
    assert job["alive"] and (job["options"]["mails"], job["options"]["documents"]) == ([], [])
    await post(texts.client, "/api/ai/run/stop", {})
    await reaped(texts)
    # nothing to summarise starts nothing; a preview never starts a run
    [empty] = await rows(
        texts.url,
        "SELECT id FROM document WHERE COALESCE(extracted_text, '') = '' ORDER BY id LIMIT 1",
    )
    nothing = {"kind": "summarize", "document_ids": [empty.id], "start": True}
    assert (await queue(texts, nothing))["run"] is None
    assert (await queue(texts, {**body, "preview": True}))["run"] is None
    assert not (await status(texts))["job"]["alive"]


async def test_a_mail_takes_its_attachments_along_their_text_recognised_first(
    texts: Dashboard, work: Work
) -> None:
    [carrier] = await rows(
        texts.url,
        """SELECT a.mail_id AS id FROM attachment a JOIN mail m ON m.id = a.mail_id
           WHERE a.document_id = :scan AND a.container_id IS NULL AND m.is_duplicate_of IS NULL
           ORDER BY a.mail_id LIMIT 1""",
        scan=work.scans[0],
    )
    body = {"kind": "summarize", "mail_ids": [carrier.id], "single": True}
    # a preview counts the mail alone
    assert (await queue(texts, {**body, "preview": True}))["queued"] == 1
    assert await tasks(texts) == []
    queued = await queue(texts, body)
    found = await tasks(texts)
    # the scan and whatever else of its attachments a work list takes, first in the queue
    ocr = {task["document"]["id"]: task["priority"] for task in found if task["kind"] == "ocr"}
    assert ocr[work.scans[0]] == PRIORITY_SINGLE and set(ocr.values()) == {PRIORITY_SINGLE}
    summaries = {task["target"]: task for task in found if task["kind"] == "summarize"}
    assert summaries["mail"]["mail"]["id"] == carrier.id
    documents = [task["document"]["id"] for task in found if task["target"] == "document"]
    assert work.scans[0] in documents
    assert queued["queued"] == len(found)
    view = await get(texts.client, "/api/ai/summary", [("mail", str(carrier.id))])
    assert view["preparing"] >= 2  # the scan's OCR and its summary


async def test_everything_without_a_summary_is_queued_for_the_whole_queue(
    texts: Dashboard,
) -> None:
    body = {"kind": "summarize", "everything": True}
    before = await queue(texts, {**body, "preview": True})
    [mail] = await original_mails(texts.url, 1)
    await summarized(texts.url, "mail", mail.raw_sha256)
    document = await text_document(texts.url)
    [sha] = await rows(texts.url, "SELECT sha256 FROM document WHERE id = :id", id=document)
    await summarized(texts.url, "document", sha.sha256)
    # what has a summary is left out, and so is a mail a hide rule hides (D222)
    [hidden] = await rows(
        texts.url,
        """SELECT m.id, m.raw_sha256 FROM mail m WHERE m.is_duplicate_of IS NULL
             AND m.raw_sha256 <> :sha AND COALESCE(m.body_text, '') <> ''
             AND NOT EXISTS (SELECT 1 FROM mail o WHERE o.raw_sha256 = m.raw_sha256
                             AND o.id <> m.id)
           ORDER BY m.id LIMIT 1""",
        sha=mail.raw_sha256,
    )
    await rows(
        texts.url,
        "INSERT INTO hide_rule (id, domain) OVERRIDING SYSTEM VALUE VALUES (1, 'x.example')",
    )
    await rows(
        texts.url, "INSERT INTO mail_hidden (rule_id, mail_id) VALUES (1, :id)", id=hidden.id
    )
    after = await queue(texts, {**body, "preview": True})
    assert before["queued"] > 3 and after["queued"] == before["queued"] - 3
    assert await summary_tasks(texts) == []
    queued = await queue(texts, body)
    assert queued["queued"] == after["queued"]
    listed = await summary_tasks(texts)
    assert {task["target"] for task in listed} == {"mail", "document"}
    assert hidden.id not in {task["mail"]["id"] for task in listed if task["mail"]}


async def test_a_run_takes_the_text_model_for_itself(
    texts: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "done")
    control = {"text_model": "a\x00b"}
    assert await error_code(texts.client, "/api/ai/run", control, 400) == "invalid_option"
    job = await post(texts.client, "/api/ai/run", {"text_model": "text-large"}, 202)
    assert job["options"]["text_model"] == "text-large"
    await reaped(texts)
    # the next start takes the settings' model again (D315)
    assert (await status(texts))["defaults"]["text_model"] == "text-test"


async def test_results_tasks_and_sends_name_a_mail(texts: Dashboard) -> None:
    [mail] = await original_mails(texts.url, 1)
    parts = [
        {"number": 1, "characters": 9000, "summary": "Erster Teil"},
        {"number": 2, "characters": 9000, "summary": "", "error": "answer cut at its length"},
    ]
    body = "Der Kassenwart bittet um Spendenquittungen ohne Namen."
    result = await summarized(
        texts.url,
        "mail",
        mail.raw_sha256,
        body,
        tags=["Spendenquittung", "Kassenwart"],
        themes=[("spenden", "Spendenquittungen", 40)],
        parts=parts,
        parts_total=3,
    )
    [item] = (await get(texts.client, "/api/ai/results"))["items"]
    assert (item["id"], item["kind"], item["target"], item["document"]) == (
        result,
        "summarize",
        "mail",
        None,
    )
    assert (item["mail"]["id"], item["mail"]["subject"]) == (mail.id, mail.subject)
    assert (item["engine"], item["model"], item["characters"]) == ("text", "text-test", len(body))
    # a summary's parts are its pages
    assert (item["pages_read"], item["pages_total"], item["failed"]) == (2, 3, [2])
    assert (item["tags"], item["themes"], item["uncertain"]) == (2, 1, [])
    await rows(
        texts.url,
        """INSERT INTO ai_send_log (service_url, kind, target, target_sha256, bytes)
           VALUES ('https://203.0.113.5/v1', 'summarize', 'mail', :sha, 2048)""",
        sha=mail.raw_sha256,
    )
    [sent] = (await get(texts.client, "/api/ai/send-log"))["items"]
    assert (sent["target"], sent["document"], sent["mail"]["id"]) == ("mail", None, mail.id)
    await queue(texts, {"kind": "summarize", "mail_ids": [mail.id]})
    partial = json.dumps({"parts": parts[:1], "parts_total": 3})
    await rows(
        texts.url,
        "UPDATE ai_task SET status = 'running', partial = CAST(:p AS jsonb)",
        p=partial,
    )
    [task] = await summary_tasks(texts)
    assert (task["pages_read"], task["pages_total"], task["mail"]["id"]) == (1, 3, mail.id)


async def test_the_alias_check_starts_with_a_text_service_on_this_machine(
    texts: Dashboard, dashboard: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    # a vision service alone checks no pair
    assert await error_code(dashboard.client, "/api/ai/run/aliases", {}, 400) == "invalid_option"
    assert await post(texts.client, "/api/ai/run/aliases", {}) == {"run": "started"}
    job = (await status(texts))["job"]
    assert job["alive"] and job["options"]["aliases"] is True
    assert await post(texts.client, "/api/ai/run/aliases", {}) == {"run": "running"}
    page = await get(texts.client, "/api/persons/suggestions", [("ai", "true")])
    check = {"available": True, "running": True, "checked": 0, "same": 0, "sure": 0}
    assert page["check"] == check
    await post(texts.client, "/api/ai/run/stop", {})
    await reaped(texts)


async def test_one_pair_is_asked_about_on_its_own(
    texts: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    body = {"persons": [7]}
    assert await error_code(texts.client, "/api/ai/run/aliases", body, 400) == "invalid_option"
    body = {"persons": [9, 4, 9]}
    assert await post(texts.client, "/api/ai/run/aliases", body) == {"run": "started"}
    job = (await status(texts))["job"]
    assert (job["options"]["aliases"], job["options"]["persons"]) == (True, [4, 9])
    await post(texts.client, "/api/ai/run/stop", {})
    await reaped(texts)


# Transcripts (D290 to D296) ---------------------------------------------------------------------

SPOKEN = "Zauberworttranskript"  # a word no generated text holds


def said(start: float, end: float, words: str, uncertain: bool = False) -> TranscriptSegment:
    return TranscriptSegment(start=start, end=end, text=words, confidence=0.7, uncertain=uncertain)


async def transcribe(
    url: str,
    document_id: int,
    segments: list[TranscriptSegment],
    *,
    duration: float | None = 90.0,
    audio: bool = True,
) -> int:
    """A transcript of the document's content, stored as a run stores it."""
    async with session_on(url) as session:
        stored = await store_transcript_result(
            session,
            sha256=await sha256(url, document_id),
            segments=segments,
            duration=duration,
            transcribed=duration or 0.0,
            audio=audio,
            options={"max_minutes": 180, "threads": 4, "uncertain": 0.5},
            seconds=12.0,
            job_id=None,
        )
    return stored.result_id


async def test_status_shows_the_transcriber_and_the_recordings(
    dashboard: Dashboard, work: Work
) -> None:
    found = await status(dashboard)
    assert found["transcription"] == {
        "available": found["transcription"]["available"],  # the libraries installed here
        "model": TRANSCRIBE_MODEL,
        "ready": False,
        "missing_bytes": 1000,
        "total_bytes": MODEL_TOTAL,
        "threads": transcribe_threads(Settings()),
        "max_minutes": 180,
    }
    media = work_list(found, "media")
    sizes = await rows(
        dashboard.url,
        "SELECT sum(size_bytes) FROM document WHERE id = ANY(:ids)",
        ids=work.recordings,
    )
    assert (media["documents"], media["bytes"], media["engine"]) == (3, sizes[0][0], "parakeet")
    # 90 s and 30 s known, the third counts AI_RULE_MINUTES
    assert (media["minutes"], media["without_minutes"], media["pages"]) == (2.0, 1, 0)
    assert media["estimates"] == [
        {
            "engine": "parakeet",
            "model": TRANSCRIBE_MODEL,
            "seconds": 3 * AI_RULE_SECONDS_PER_MINUTE,
            "estimated": True,
            "seconds_per_page": 0.0,
            "seconds_per_minute": AI_RULE_SECONDS_PER_MINUTE,
        }
    ]
    assert found["queue"]["transcribe"]["waiting"] == 0


async def test_a_measured_speed_estimates_the_recordings(dashboard: Dashboard, work: Work) -> None:
    await rows(
        dashboard.url,
        """INSERT INTO ai_calibration (kind, engine, model, unit, seconds_per_unit, samples)
           VALUES ('transcribe', 'parakeet', :model, 'minute', 4.0, 600)""",
        model=TRANSCRIBE_MODEL,
    )
    [estimate] = work_list(await status(dashboard), "media")["estimates"]
    # still estimated: one length is not known
    assert (estimate["seconds"], estimate["estimated"]) == (12.0, True)
    assert estimate["seconds_per_minute"] == 4.0
    # a recording longer than max_minutes counts with max_minutes only
    await rows(
        dashboard.url, "UPDATE document SET duration = 12000 WHERE id = :id", id=work.recordings[2]
    )
    media = work_list(await status(dashboard), "media")
    assert (media["minutes"], media["without_minutes"]) == (202.0, 0)
    [estimate] = media["estimates"]
    assert (estimate["seconds"], estimate["estimated"]) == ((120 + 180 * 60) / 60 * 4.0, False)


async def test_recordings_are_queued_for_the_transcriber(dashboard: Dashboard, work: Work) -> None:
    queued = await queue(dashboard, {"work_list": "media", "engine": "vision"})
    assert queued == {
        "queued": 3,
        "raised": 0,
        "unreadable": 0,
        "logos": 0,
        "run": None,
        "short": 0,
        "estimate": None,
    }
    listed = await tasks(dashboard)
    assert {(task["kind"], task["engine"], task["status"]) for task in listed} == {
        ("transcribe", "auto", "waiting")  # the engine is OCR's
    }
    durations = {task["document"]["id"]: task["document"]["duration"] for task in listed}
    assert durations == dict(zip(work.recordings, [90.0, 30.0, None], strict=True))
    assert {task["seconds_read"] for task in listed} == {0.0}
    assert {task["pages_read"] for task in listed} == {0}
    assert (await status(dashboard))["queue"]["transcribe"]["waiting"] == 3

    # each document gets what fits it, unless kind names one
    mixed = {"document_ids": [work.recordings[0], work.scans[0]], "single": True}
    assert (await queue(dashboard, mixed))["queued"] == 1  # the scan; the recording is raised
    only = {"document_ids": [work.recordings[1], work.scans[1]], "kind": "transcribe"}
    assert (await queue(dashboard, only))["unreadable"] == 1
    ocr = {"document_ids": [work.recordings[2], work.scans[2]], "kind": "ocr"}
    assert (await queue(dashboard, ocr))["queued"] == 1
    by_kind = {(task["kind"], task["document"]["id"]) for task in await tasks(dashboard)}
    assert by_kind == {
        *(("transcribe", recording) for recording in work.recordings),
        ("ocr", work.scans[0]),
        ("ocr", work.scans[2]),
    }


async def test_the_document_list_queues_recordings_too(dashboard: Dashboard, work: Work) -> None:
    summary = await get(dashboard.client, "/api/documents/summary", [("kind", "media")])
    assert summary["ocr_readable"] == 3  # what "Für KI vormerken" queues: the recordings
    queued = await queue(dashboard, {"filters": {"kind": ["media", "pdf"]}, "kind": "transcribe"})
    assert (queued["queued"], queued["unreadable"]) == (3, 0)
    both = await queue(dashboard, {"filters": {"kind": ["media", "pdf"]}})
    assert (both["queued"], both["raised"]) == (3, 3)  # the scans for OCR


async def test_a_recording_starts_a_run_of_its_own(
    dashboard: Dashboard, work: Work, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    body = {"document_ids": [work.recordings[0]], "single": True, "start": True}
    assert (await queue(dashboard, body))["run"] == "started"
    job = (await status(dashboard))["job"]
    assert job["options"]["documents"] == [work.recordings[0]]
    assert job["options"]["max_minutes"] == 180  # the defaults'
    detail = await get(
        dashboard.client, f"/api/mails/{await carrier(dashboard.url, work.recordings[0])}"
    )
    states = {item["document_id"]: item["transcript"] for item in detail["attachments"]}
    assert states[work.recordings[0]] == "queued"
    await post(dashboard.client, "/api/ai/run/stop", {})
    await reaped(dashboard)


async def test_a_task_shows_the_seconds_read_so_far(dashboard: Dashboard, work: Work) -> None:
    await queue(dashboard, {"document_ids": [work.recordings[0]]})
    partial = (
        '{"segments": [{"start": 1.0, "end": 8.0, "text": "Hallo"}], "until": 42.5, '
        '"duration": 90.0}'
    )
    await rows(
        dashboard.url,
        "UPDATE ai_task SET status = 'running', partial = CAST(:p AS jsonb)",
        p=partial,
    )
    [task] = await tasks(dashboard)
    assert (task["status"], task["seconds_read"], task["pages_read"]) == ("running", 42.5, 0)
    detail = await get(dashboard.client, f"/api/documents/{work.recordings[0]}")
    assert detail["ai"] is None  # no OCR
    assert detail["transcript"] == {
        "result": None,
        "task": {"id": task["id"], "status": "running", "seconds_read": 42.5},
    }
    assert (detail["transcribable"], detail["ocr_readable"], detail["duration"]) == (
        True,
        False,
        90.0,
    )


async def test_a_transcript_on_the_document_page_and_in_the_results(
    dashboard: Dashboard, work: Work
) -> None:
    lines = [said(12.0, 20.5, f"Der {SPOKEN} liegt bereit.", True), said(1.0, 8.0, "Guten Tag")]
    result = await transcribe(dashboard.url, work.recordings[0], lines)
    text_of = f"Guten Tag\nDer {SPOKEN} liegt bereit."
    [item] = (await get(dashboard.client, "/api/ai/results"))["items"]
    assert (item["id"], item["kind"], item["engine"], item["model"]) == (
        result,
        "transcribe",
        "parakeet",
        TRANSCRIBE_MODEL,
    )
    assert (item["pages_read"], item["pages_text"], item["uncertain"], item["failed"]) == (
        0,
        0,
        [],
        [],
    )
    assert (item["segments"], item["uncertain_segments"]) == (2, 1)
    assert (item["duration"], item["transcribed"], item["characters"]) == (
        90.0,
        90.0,
        len(text_of),
    )
    assert item["document"]["duration"] == 90.0

    detail = await get(dashboard.client, f"/api/documents/{work.recordings[0]}")
    assert (detail["text_origin"], detail["text_status"], detail["duration"]) == (
        "transcript",
        "text",
        90.0,
    )
    assert (detail["transcribable"], detail["ai"]) == (True, None)
    expected = {
        "id": result,
        "model": TRANSCRIBE_MODEL,
        "created_at": item["created_at"],
        "duration": 90.0,
        "transcribed": 90.0,
        "segments": 2,
        "uncertain": 1,
        "characters": len(text_of),
        "audio": True,
    }
    assert detail["transcript"] == {"result": expected, "task": None}
    view = await get(dashboard.client, f"/api/documents/{work.recordings[0]}/transcript")
    assert view["result"] == expected
    assert [(line["start"], line["text"], line["uncertain"]) for line in view["segments"]] == [
        (1.0, "Guten Tag", False),
        (12.0, f"Der {SPOKEN} liegt bereit.", True),
    ]
    text_view = await get(dashboard.client, f"/api/documents/{work.recordings[0]}/text")
    assert SPOKEN in str(text_view)

    # without a transcript: 404, also for a scan
    for document_id in (work.recordings[1], work.scans[0], 2**40):
        path = f"/api/documents/{document_id}/transcript"
        await get(dashboard.client, path, status=404)
    response = await dashboard.client.get(f"/api/documents/{work.recordings[1]}/transcript")
    assert response.json()["detail"]["code"] == "not_found"


async def test_a_recording_without_sound_is_read_without_a_text(
    dashboard: Dashboard, work: Work
) -> None:
    await transcribe(dashboard.url, work.recordings[2], [], duration=4.0, audio=False)
    detail = await get(dashboard.client, f"/api/documents/{work.recordings[2]}")
    assert (detail["text_origin"], detail["text_status"], detail["duration"]) == (
        "extracted",
        "unsupported",
        4.0,
    )
    result = detail["transcript"]["result"]
    assert (result["audio"], result["characters"], result["segments"]) == (False, 0, 0)
    # off the work list
    assert work_list(await status(dashboard), "media")["documents"] == 2


async def test_the_mail_says_where_the_transcription_of_its_recordings_stands(
    dashboard: Dashboard, work: Work
) -> None:
    await transcribe(dashboard.url, work.recordings[0], [said(0.0, 2.0, "Hallo")])
    await transcribe(dashboard.url, work.recordings[1], [], duration=30.0)
    expected = {
        work.recordings[0]: ("transcribed", 90.0),
        work.recordings[1]: ("no_text", 30.0),
        work.recordings[2]: ("transcribable", None),
    }
    for recording, state in expected.items():
        detail = await get(
            dashboard.client, f"/api/mails/{await carrier(dashboard.url, recording)}"
        )
        found = {
            item["document_id"]: (item["transcript"], item["duration"])
            for item in detail["attachments"]
        }
        assert found[recording] == state
        # an attachment the transcriber does not read has no state
        others = [item for item in detail["attachments"] if item["document_id"] != recording]
        for item in others:
            if item["document_id"] not in expected:
                assert item["transcript"] is None


async def test_hit_lines_say_a_transcript_is_machine_made(dashboard: Dashboard, work: Work) -> None:
    await transcribe(dashboard.url, work.recordings[0], [said(1.0, 4.0, f"{SPOKEN} gesagt")])
    mail = await carrier(dashboard.url, work.recordings[0])
    listed = await get(dashboard.client, "/api/mails", [("q", SPOKEN)])
    item = next(item for item in listed["items"] if item["id"] == mail)
    assert (item["attachment_match"], item["attachment_machine"]) == (True, True)
    assert item["attachment_transcript"] is True  # "maschinell transkribiert"
    hits = await get(dashboard.client, f"/api/mails/{mail}/hits", [("q", SPOKEN)])
    [hit] = hits["attachments"]
    assert (hit["in_text"], hit["machine"]) == (True, True)
    searched = await get(dashboard.client, "/api/documents", [("q", SPOKEN)])
    assert [(row["id"], row["text_origin"]) for row in searched["items"]] == [
        (work.recordings[0], "transcript")
    ]
    filtered = await get(dashboard.client, "/api/documents", [("text_origin", "transcript")])
    assert [row["id"] for row in filtered["items"]] == [work.recordings[0]]


async def test_a_transcription_without_a_vision_service(
    work: Work, mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    async with serve(ai_settings(mutable_database_url, generated_archive, tmp_path)) as served:
        media = {"work_list": "media"}  # as the AI page queues the list: no engine
        assert (await post(served.client, "/api/ai/tasks", media))["queued"] == 3
        body = {"work_list": "media", "engine": "vision", "kind": "transcribe"}
        assert (await post(served.client, "/api/ai/tasks", body))["raised"] == 3
        scans = {"work_list": "scanned", "engine": "vision"}
        assert await error_code(served.client, "/api/ai/tasks", scans, 400) == "invalid_option"

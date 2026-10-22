"""The AI API (D180 to D189): the status with its services, work lists and estimates, the check
of a service, the queue, the results and discarding them, the send log, the run started and
stopped as a child process, and what documents and hit lines say about machine made texts.

Each test works on its own copy of the imported archive, prepared as a known set of work: three
PDFs made scans (2 pages, 3 pages, pages unknown), the other scans and every other image put out
of the work lists' way, and three images of 200 KB, one of them in more than LOGO_MAILS mails.
Results are stored through ai.store, as a run stores them; the run is tests/api/fake_run.py in
place of `mailrobbe ai` (processes.CLI), as in test_imports.py. The service check is replaced
(api.ai.check_service), or asks the fake service of tests/ai/fakes.py, so nothing asks a real
service.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mailrobbe.ai.model import LOGO_MAILS, PRIORITY_SINGLE, OcrPage, Service, ServiceCheck
from mailrobbe.ai.store import store_ocr_result
from mailrobbe.api import ai as ai_api
from mailrobbe.api.schemas import AI_RULE_SECONDS
from mailrobbe.config import Settings
from mailrobbe.enums import JobKind
from tests.ai.fakes import fake_service
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
]


@dataclass(frozen=True, slots=True)
class Work:
    scans: list[int]  # document ids: 2 pages, 3 pages, pages unknown
    images: list[int]  # the last one a logo
    text: int  # a PDF with a text read from its file


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
        own = await connection.scalar(
            text(
                "SELECT min(id) FROM document WHERE kind = 'pdf' AND text_status = 'text' "
                "AND sha256 IS NOT NULL"
            )
        )
        await connection.commit()
    await engine.dispose()
    assert len(scans) == 3 and len(images) == 3 and own is not None
    return Work(scans, images, own)


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
    }
    assert await queue(dashboard, body) == {
        "queued": 0,
        "raised": 3,
        "unreadable": 0,
        "logos": 0,
        "run": None,
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
    assert queued == {"queued": 3, "raised": 0, "unreadable": 0, "logos": 0, "run": None}
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
    body = {"engine": "tesseract", "max_pages": 7}
    job = await post(dashboard.client, "/api/ai/run", body, 202)
    assert (job["kind"], job["origin"], job["alive"]) == ("ai", "ui", True)
    assert (job["options"]["ocr_engine"], job["options"]["max_pages"]) == ("tesseract", 7)
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
    # the next start takes the latest run's choice (D49)
    assert (await status(dashboard))["defaults"]["max_pages"] == 7
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

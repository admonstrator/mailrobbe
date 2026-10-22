"""`mailrobbe ai`: the options, check, queue, status, the transcriber's model and a run started
like the dashboard does."""

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import cli as main_cli
from mailrobbe import jobrun, jobs, migrate
from mailrobbe.ai import cli as ai_cli
from mailrobbe.ai import run as ai_run
from mailrobbe.ai.audio import parakeet
from mailrobbe.ai.model import TRANSCRIBE_MODEL, AiOptions
from mailrobbe.config import Settings
from mailrobbe.enums import JobOrigin
from tests.ai.fakes import MODEL_TOTAL, FakeAudio, ModelMissing
from tests.ai.test_run import VISION_URL, Fake, rows
from tests.conftest import _temporary_database


@pytest.fixture(autouse=True)
def quiet_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AI_VISION_URL", "AI_VISION_MODEL", "AI_OCR_ENGINE", "AI_CONCURRENCY"):
        monkeypatch.delenv(f"MAILROBBE_{name}", raising=False)
    for name in ("AI_MODEL_DIR", "AI_TRANSCRIBE_MAX_MINUTES", "AI_TRANSCRIBE_THREADS"):
        monkeypatch.delenv(f"MAILROBBE_{name}", raising=False)
    monkeypatch.setattr(jobrun, "REPORT_SECONDS", 0.05)


@pytest.fixture(autouse=True)
def model_files(monkeypatch: pytest.MonkeyPatch) -> FakeAudio:
    """The transcriber's files, none there yet; downloading fetches them in 100 MB steps."""
    audio = FakeAudio({}, missing=MODEL_TOTAL)
    monkeypatch.setattr(parakeet, "model_state", audio.model_state)
    monkeypatch.setattr(parakeet, "download_model", audio.download_model)
    return audio


def test_the_help_names_the_tasks(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ended:
        main_cli.main(["ai", "--help"])
    assert ended.value.code == 0
    shown = capsys.readouterr().out
    for task in ("run", "check", "queue", "status", "model"):
        assert f"    {task} " in shown
    with pytest.raises(SystemExit):
        main_cli.main(["ai", "run", "--help"])
    shown = capsys.readouterr().out
    for option in ("--engine", "--vision-model", "--max-pages", "--max-minutes", "--concurrency"):
        assert option in shown
    with pytest.raises(SystemExit):
        main_cli.main(["ai", "queue", "--help"])
    assert "--media" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main_cli.main(["ai", "model", "--help"])
    assert "--download" in capsys.readouterr().out


def test_the_command_line_overrides_the_settings() -> None:
    args = main_cli.build_parser().parse_args(
        [
            "ai",
            "--origin",
            "ui",
            "run",
            "--engine",
            "vision",
            "--vision-model",
            " anderes ",
            "--max-pages",
            "5",
            "--max-minutes",
            "30",
            "--concurrency",
            "2",
            "--document",
            "9",
            "--document",
            "4",
        ]
    )
    assert args.origin is JobOrigin.UI
    settings = Settings(
        ai_vision_url=VISION_URL, ai_vision_model="lesemodell", ai_vision_key=SecretStr("geheim-9")
    )
    found = ai_cli.options(settings, args)
    assert found == AiOptions.from_settings(settings).model_copy(
        update={
            "ocr_engine": "vision",
            "vision_model": "anderes",
            "max_pages": 5,
            "max_minutes": 30,
            "concurrency": 2,
            "documents": [4, 9],
        }
    )
    assert found.vision_url == VISION_URL and "geheim" not in found.model_dump_json()
    defaults = ai_cli.options(settings, main_cli.build_parser().parse_args(["ai", "run"]))
    assert defaults == AiOptions.from_settings(settings)


def test_pages_and_requests_must_be_positive(capsys: pytest.CaptureFixture[str]) -> None:
    for option in ("--max-pages", "--max-minutes", "--concurrency"):
        with pytest.raises(SystemExit) as ended:
            main_cli.build_parser().parse_args(["ai", "run", option, "0"])
        assert ended.value.code == 2
    assert "must be at least 1" in capsys.readouterr().err


def test_check_prints_each_service_and_fails_with_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main_cli.main(["ai", "check"]) == 0  # nothing configured
    assert json.loads(capsys.readouterr().out) == []

    monkeypatch.setenv("MAILROBBE_AI_VISION_URL", VISION_URL)
    monkeypatch.setenv("MAILROBBE_AI_VISION_MODEL", "lesemodell")
    monkeypatch.setenv("MAILROBBE_AI_VISION_KEY", "geheim-123")
    fake = Fake(check_result={"test": "passed"})
    monkeypatch.setattr(ai_cli, "default_engines", fake.engines)
    assert main_cli.main(["ai", "check"]) == 0
    shown = capsys.readouterr().out
    (found,) = json.loads(shown)
    assert (found["url"], found["model"], found["test"]) == (VISION_URL, "lesemodell", "passed")
    assert "geheim" not in shown

    fake.check_result = {"model_found": False}
    assert main_cli.main(["ai", "check"]) == 1


# On a database --------------------------------------------------------------------------------

_DOCUMENT = text("""
    INSERT INTO document (sha256, name, mime_type, size_bytes, kind, text_status, mails)
    VALUES (:sha256, :name, :mime, :size, CAST(:kind AS document_kind),
        CAST(:status AS document_text_status), :mails)
""")


async def _documents(url: str) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.begin() as connection:
        for values in (
            ("a", "Scan.pdf", "application/pdf", 1_000, "pdf", "scanned", 1),
            ("b", "Bild.jpg", "image/jpeg", 200_000, "image", "unsupported", 2),
            ("c", "Logo.png", "image/png", 200_000, "image", "unsupported", 80),
            ("d", "Text.pdf", "application/pdf", 1_000, "pdf", "text", 1),
            ("e", "Ansage.ogg", "audio/ogg", 50_000, "media", "unsupported", 3),
        ):
            sha256, name, mime, size, kind, status, mails = values
            parameters = {"sha256": sha256 * 64, "name": name, "mime": mime, "size": size}
            await connection.execute(
                _DOCUMENT, {**parameters, "kind": kind, "status": status, "mails": mails}
            )
    await engine.dispose()


@pytest.fixture
def database(database_server_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        asyncio.run(_documents(url))
        monkeypatch.setenv("MAILROBBE_DATABASE_URL", url)
        yield url


@pytest.mark.db
def test_queue_and_status(database: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main_cli.main(["ai", "queue"]) == 2  # nothing named

    assert main_cli.main(["ai", "queue", "--scanned", "--images"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "queued": 2,
        "raised": 0,
        "unreadable": 0,
        "logos": 0,
    }
    (logo,) = asyncio.run(rows(database, "SELECT id FROM document WHERE name = 'Logo.png'"))
    (own,) = asyncio.run(rows(database, "SELECT id FROM document WHERE name = 'Text.pdf'"))
    arguments = ["ai", "queue", "--document", str(logo.id), "--document", str(own.id)]
    assert main_cli.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["logos"] == 1
    assert main_cli.main([*arguments, "--include-logos", "--engine", "vision"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "queued": 1,
        "raised": 0,
        "unreadable": 1,
        "logos": 0,
    }
    queued = asyncio.run(rows(database, "SELECT engine FROM ai_task ORDER BY id"))
    assert [row.engine for row in queued] == ["auto", "auto", "vision"]

    assert main_cli.main(["ai", "status"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["tasks"]["ocr"] == {
        "waiting": 3,
        "running": 0,
        "done": 0,
        "failed": 0,
        "cancelled": 0,
    }
    assert found["latest_run"] is None


@pytest.mark.db
def test_a_run_started_like_the_dashboard_does(
    database: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ai_run, "default_engines", Fake().engines)
    assert main_cli.main(["ai", "--origin", "ui", "run", "--engine", "tesseract"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["status"], summary["queued"]) == ("done", 0)
    (job,) = asyncio.run(rows(database, "SELECT * FROM job WHERE kind = 'ai'"))
    assert (job.origin, job.status, job.options["ocr_engine"]) == ("ui", "done", "tesseract")

    assert main_cli.main(["ai", "status"]) == 0
    latest: dict[str, Any] = json.loads(capsys.readouterr().out)["latest_run"]
    assert (latest["id"], latest["status"], latest["origin"]) == (job.id, "done", "ui")
    assert [step["key"] for step in latest["progress"]["steps"]] == list(ai_run.RUN_STEPS)


@pytest.mark.db
def test_a_run_refused_exits_with_one(
    database: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def hold_and_run() -> int:
        engine = create_async_engine(database, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                await connection.execute(
                    text("SELECT pg_advisory_lock(:key)"), {"key": jobs.AI_LOCK_KEY}
                )
                await connection.commit()
                return await asyncio.to_thread(main_cli.main, ["ai", "run"])
        finally:
            await engine.dispose()

    monkeypatch.setattr(ai_run, "default_engines", Fake().engines)
    assert asyncio.run(hold_and_run()) == 1
    assert capsys.readouterr().out == ""


# The transcriber (D290, D291) -------------------------------------------------------------------


def test_model_prints_the_state_of_the_files(
    model_files: FakeAudio, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAILROBBE_AI_MODEL_DIR", "/data/models")
    monkeypatch.setenv("MAILROBBE_AI_TRANSCRIBE_THREADS", "3")
    assert main_cli.main(["ai", "model"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found == {
        "model": TRANSCRIBE_MODEL,
        "available": found["available"],  # whether the libraries are installed here
        "model_dir": "/data/models",
        "ready": False,
        "missing_bytes": MODEL_TOTAL,
        "total_bytes": MODEL_TOTAL,
        "threads": 3,
        "max_minutes": 180,
    }
    assert isinstance(found["available"], bool)
    assert model_files.downloads == []  # only looked at


@pytest.mark.db
def test_queue_media_and_the_transcriber_in_status(
    database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main_cli.main(["ai", "queue", "--media", "--engine", "vision"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "queued": 1,
        "raised": 0,
        "unreadable": 0,
        "logos": 0,
    }
    (task,) = asyncio.run(rows(database, "SELECT kind::text AS kind, engine FROM ai_task"))
    assert (task.kind, task.engine) == ("transcribe", "auto")  # the engine is OCR's
    (voice,) = asyncio.run(rows(database, "SELECT id FROM document WHERE name = 'Ansage.ogg'"))
    assert main_cli.main(["ai", "queue", "--document", str(voice.id)]) == 0
    assert json.loads(capsys.readouterr().out)["raised"] == 1

    assert main_cli.main(["ai", "status"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["tasks"]["transcribe"]["waiting"] == 1
    assert found["tasks"]["ocr"]["waiting"] == 0
    assert (found["transcriber"]["ready"], found["transcriber"]["missing_bytes"]) == (
        False,
        MODEL_TOTAL,
    )


@pytest.mark.db
def test_model_download_fetches_what_is_missing(
    database: str, model_files: FakeAudio, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main_cli.main(["ai", "model", "--download"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert (found["ready"], found["missing_bytes"]) == (True, 0)
    assert model_files.downloads == [MODEL_TOTAL]
    assert main_cli.main(["ai", "model", "--download"]) == 0  # nothing left to fetch
    assert model_files.downloads == [MODEL_TOTAL]


@pytest.mark.db
def test_model_download_is_refused_while_a_run_holds_the_lock(
    database: str, model_files: FakeAudio, capsys: pytest.CaptureFixture[str]
) -> None:
    async def hold_and_download() -> int:
        engine = create_async_engine(database, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                await connection.execute(
                    text("SELECT pg_advisory_lock(:key)"), {"key": jobs.AI_LOCK_KEY}
                )
                await connection.commit()
                return await asyncio.to_thread(main_cli.main, ["ai", "model", "--download"])
        finally:
            await engine.dispose()

    assert asyncio.run(hold_and_download()) == 1
    assert json.loads(capsys.readouterr().out)["ready"] is False
    assert model_files.downloads == []


@pytest.mark.db
def test_a_model_that_cannot_be_downloaded_exits_with_one(
    database: str,
    model_files: FakeAudio,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(parakeet, "ModelMissing", ModelMissing)
    model_files.unavailable = "huggingface.co: Name or service not known"
    assert main_cli.main(["ai", "model", "--download"]) == 1
    assert "ModelMissing: huggingface.co: Name or service not known" in caplog.text
    assert json.loads(capsys.readouterr().out)["missing_bytes"] == MODEL_TOTAL

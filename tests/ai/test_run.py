"""The AI run (D181, D182, D184 to D188) on a small imported archive: scanned PDFs and a photo,
read through engine doubles, and once through the real Tesseract."""

import asyncio
import io
import logging
import shutil
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import jobrun, jobs, migrate
from mailrobbe.ai import run as ai_run
from mailrobbe.ai.model import (
    PAGE_SEPARATOR,
    AiOptions,
    AiProgress,
    OcrPage,
    Service,
    ServiceCheck,
    locality,
)
from mailrobbe.ai.prompts import load_prompts
from mailrobbe.ai.queue import enqueue_ocr
from mailrobbe.ai.run import EngineErrors, Engines, run_ai
from mailrobbe.config import Settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.enums import JobKind
from mailrobbe.importer.cli import run_import
from tests.ai.fakes import fake_service
from tests.attachments.doubles import attachment_mail, digest
from tests.conftest import _temporary_database
from tests.importer.doubles import SEPARATOR

pytestmark = pytest.mark.db

FONT = Path(__file__).parents[2] / "src/mailrobbe/export/fonts/DejaVuSans.ttf"
VISION_URL = "http://127.0.0.1:9/v1"
REMOTE_URL = "http://203.0.113.7:1234/v1"  # TEST-NET-3: remote, and never asked here
WORD = "Spendenquittung"


def page_image(label: str, size: tuple[int, int] = (400, 200), font_size: int = 24) -> Image.Image:
    image = Image.new("RGB", size, "white")
    font = ImageFont.truetype(str(FONT), font_size)
    ImageDraw.Draw(image).text((20, 20), label, fill="black", font=font)
    return image


def scan(*labels: str) -> bytes:
    """A PDF of page images without a text layer: what the import calls scanned."""
    pages = [page_image(label) for label in labels]
    buffer = io.BytesIO()
    pages[0].save(buffer, "PDF", save_all=True, append_images=pages[1:], resolution=100)
    return buffer.getvalue()


def photo() -> bytes:
    buffer = io.BytesIO()
    page_image("Foto").save(buffer, "JPEG")
    return buffer.getvalue()


def letter() -> bytes:
    """One page with a word in large type at 200 dpi, for the real Tesseract."""
    image = page_image(f"{WORD} Bergmann", size=(1700, 400), font_size=80)
    buffer = io.BytesIO()
    image.save(buffer, "PDF", resolution=200)
    return buffer.getvalue()


FILES = {
    "Scan.pdf": scan("Seite eins", "Seite zwei", "Seite drei"),
    "Flyer.pdf": scan("Flyer"),
    "Foto.jpg": photo(),
    "Brief.pdf": letter(),
}
MIMES = {".pdf": "application/pdf", ".jpg": "image/jpeg"}
MAILS = [["Scan.pdf"], ["Flyer.pdf"], ["Flyer.pdf", "Foto.jpg"], ["Brief.pdf"]]
NAMES = {digest(data): name for name, data in FILES.items()}


@dataclass(frozen=True, slots=True)
class Archive:
    server: str
    template: str  # the imported database, copied for each test
    mbox_dir: Path


@pytest.fixture(scope="module")
def archive(
    database_server_url: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Archive]:
    mbox_dir = tmp_path_factory.mktemp("ai") / "mbox"
    mbox_dir.mkdir()
    with (mbox_dir / "ai.mbox").open("wb") as handle:
        for index, names in enumerate(MAILS):
            files = [(name, MIMES[Path(name).suffix], FILES[name]) for name in names]
            handle.write(SEPARATOR + b"\n" + attachment_mail(index, files) + b"\n")
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(database_url=url, mbox_dir=mbox_dir)
        assert asyncio.run(run_import(settings, mbox_dir, 1)) == 0
        name = make_url(url).database
        assert name is not None
        yield Archive(database_server_url, name, mbox_dir)


@pytest.fixture
def database(archive: Archive) -> Iterator[str]:
    with _temporary_database(archive.server, template=archive.template) as url:
        yield url


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobrun, "REPORT_SECONDS", 0.05)
    monkeypatch.setattr(ai_run, "WAIT_FIRST", 0.01)
    monkeypatch.setattr(ai_run, "WAIT_MAX", 0.02)


def settings_for(url: str, archive: Archive, **values: Any) -> Settings:
    return Settings(database_url=url, mbox_dir=archive.mbox_dir, import_workers=1, **values)


def options_for(settings: Settings, **values: Any) -> AiOptions:
    return AiOptions.from_settings(settings).model_copy(update={"tesseract_workers": 1, **values})


async def rows(url: str, statement: str, parameters: dict[str, Any] | None = None) -> list[Any]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(statement), parameters or {})
            return list(result.all()) if result.returns_rows else []
    finally:
        await engine.dispose()


async def queue(url: str, *names: str, engine: Any = "auto", single: bool = False) -> None:
    ids = [
        row.id
        for row in await rows(url, "SELECT id FROM document WHERE name = ANY(:n)", {"n": names})
    ]
    assert len(ids) == len(names)
    database = create_engine(url)
    try:
        async with create_sessionmaker(database).begin() as session:
            queued = await enqueue_ocr(session, ids, engine=engine, single=single)
    finally:
        await database.dispose()
    assert queued.queued == len(names)


async def tasks(url: str) -> dict[str, Any]:
    found = await rows(
        url,
        "SELECT d.name, t.* FROM ai_task t JOIN document d ON d.sha256 = t.target_sha256",
    )
    return {row.name: row for row in found}


async def document(url: str, name: str) -> Any:
    (found,) = await rows(
        url,
        "SELECT d.*, d.text_origin::text AS origin, d.text_status::text AS status, "
        "r.engine AS result_engine, r.model, r.service_url, r.prompt_version, r.pages AS read, "
        "r.pages_total AS result_pages_total, r.options AS result_options, r.remote "
        "FROM document d LEFT JOIN ai_result r ON r.id = d.ai_result_id WHERE d.name = :name",
        {"name": name},
    )
    return found


async def latest(url: str) -> Any:
    (job,) = await rows(url, "SELECT * FROM job WHERE kind = 'ai' ORDER BY id DESC LIMIT 1")
    return job


def steps(job: Any) -> dict[str, str]:
    return {step.key: step.status for step in AiProgress.model_validate(job.progress).steps}


# Engine doubles -------------------------------------------------------------------------------


class Unreachable(Exception):
    pass


class ModelMissing(Exception):
    pass


class AnswerError(Exception):
    pass


class RenderError(Exception):
    pass


class TesseractMissing(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Page:
    number: int
    png: bytes


@dataclass(frozen=True, slots=True)
class Rendered:
    pages_total: int
    pages: list[Page]


@dataclass(frozen=True, slots=True)
class Prompts:
    version: int = 3


Reader = Callable[[str, int], OcrPage]  # file name, page number


@dataclass
class Fake:
    """Render, Tesseract, the vision model and the service check: each call recorded."""

    tesseract_reader: Reader | None = None
    vision_reader: Reader | None = None
    render_error: set[str] = field(default_factory=set)  # file names that cannot be rendered
    tesseract_missing: bool = False
    check_result: dict[str, Any] = field(default_factory=dict)
    renders: list[tuple[str, str, int, int]] = field(default_factory=list)
    reads: list[tuple[str, str, int]] = field(default_factory=list)  # engine, name, number

    def engines(self) -> Engines:
        return Engines(
            render=self.render,
            tesseract=self.tesseract,
            languages=self.languages,
            vision=self.vision,
            check=self.check,
            prompts=Prompts,
            errors=EngineErrors(
                Unreachable, ModelMissing, AnswerError, RenderError, TesseractMissing
            ),
        )

    def render(
        self, data: bytes, kind: str, *, purpose: str, first: int, count: int, **_: Any
    ) -> Rendered:
        name = NAMES[digest(data)]
        self.renders.append((name, purpose, first, count))
        if name in self.render_error:
            raise RenderError("pdftoppm ended with status 1")
        total = 1 if kind == "image" else len(PdfReader(io.BytesIO(data)).pages)
        numbers = range(first, min(total, first + count - 1) + 1)
        return Rendered(total, [Page(n, f"{name}|{n}|{purpose}".encode()) for n in numbers])

    def languages(self, languages: str) -> None:
        if self.tesseract_missing:
            raise TesseractMissing(f"Tesseract has no language data for {languages}")

    def tesseract(self, png: bytes, number: int, **_: Any) -> OcrPage:
        name = png.decode().split("|")[0]
        self.reads.append(("tesseract", name, number))
        if self.tesseract_reader is not None:
            return self.tesseract_reader(name, number)
        return OcrPage(number=number, engine="tesseract", text=f"{name} {number}", confidence=90)

    def vision(self, service: Service, png: bytes, number: int, **extra: Any) -> OcrPage:
        assert isinstance(extra["prompts"], Prompts) and extra["protocol"] == "openai"
        name = png.decode().split("|")[0]
        self.reads.append(("vision", name, number))
        if self.vision_reader is not None:
            return self.vision_reader(name, number)
        return OcrPage(
            number=number,
            engine="vision",
            text=f"Vision {name} {number}",
            tokens_in=5,
            tokens_out=5,
        )

    def check(self, service: Service, settings: Settings, *, test: bool) -> ServiceCheck:
        values = {
            "capability": "vision",
            "url": service.display_url,
            "locality": locality(service.url),
            "reachable": True,
            "protocol": "openai",
            "model": service.model,
            "model_found": True,
            **self.check_result,
        }
        return ServiceCheck.model_validate(values)


def tesseract_page(name: str, number: int, **values: Any) -> OcrPage:
    return OcrPage(number=number, engine="tesseract", text=f"{name} {number}", **values)


# The run ----------------------------------------------------------------------------------------


async def test_a_run_reads_the_queue_in_order_and_stores_the_texts(
    archive: Archive, database: str
) -> None:
    await queue(database, "Scan.pdf", "Flyer.pdf")
    await queue(database, "Foto.jpg", single=True)
    fake = Fake(tesseract_reader=lambda name, number: tesseract_page(name, number, seconds=2.0))
    settings = settings_for(database, archive)
    result = await run_ai(settings, options_for(settings), engines=fake.engines())

    assert result.exit_code == 0
    # One document from its page first, then the one in most mails, then the oldest task.
    assert [read[1] for read in fake.reads] == ["Foto.jpg", "Flyer.pdf", *["Scan.pdf"] * 3]
    assert {read[0] for read in fake.reads} == {"tesseract"}  # no vision service is set
    assert fake.renders[-1] == ("Scan.pdf", "tesseract", 1, 4)
    summary = result.summary
    assert (summary.status, summary.queued, summary.done, summary.no_text) == ("done", 3, 3, 0)
    assert (summary.pages, summary.documents, summary.failed) == (5, 3, 0)

    scanned = await document(database, "Scan.pdf")
    assert (scanned.origin, scanned.status, scanned.result_engine) == ("ocr", "text", "tesseract")
    assert scanned.extracted_text == PAGE_SEPARATOR.join(f"Scan.pdf {n}" for n in (1, 2, 3))
    assert (scanned.result_pages_total, scanned.model, scanned.service_url) == (3, None, None)
    assert scanned.result_options == {
        "engine": "auto",
        "languages": "deu+eng",
        "uncertain": 60.0,
        "max_pages": 50,
    }
    found = await rows(
        database, "SELECT name FROM document WHERE tsv @@ to_tsquery('simple', 'flyer')"
    )
    assert [row.name for row in found] == ["Flyer.pdf"]
    queued = await tasks(database)
    assert {row.status for row in queued.values()} == {"done"}
    assert all(row.result_id is not None and row.partial == {} for row in queued.values())
    (calibration,) = await rows(database, "SELECT * FROM ai_calibration")
    assert (calibration.engine, calibration.model, calibration.unit) == ("tesseract", "", "page")
    assert (calibration.samples, calibration.seconds_per_unit) == (5, 2.0)

    job = await latest(database)
    assert (job.status, job.origin, job.phase) == ("done", "cli", "signals")
    assert job.message.startswith("3 documents read (0 without text), 0 failed, 5 pages")
    assert steps(job) == {
        "check": "done",
        "ocr": "done",
        "transcribe": "skipped",
        "entities": "done",
        "signals": "done",
    }
    progress = AiProgress.model_validate(job.progress)
    assert (progress.queued, progress.done, progress.failed, progress.current) == (3, 3, 0, None)
    ocr = next(step for step in progress.steps if step.key == "ocr")
    assert (ocr.unit, ocr.done, ocr.total) == ("pages", 5, 5)


async def test_a_run_for_one_document_leaves_the_queue_waiting(
    archive: Archive, database: str
) -> None:
    await queue(database, "Scan.pdf", "Flyer.pdf", "Foto.jpg")
    flyer = await document(database, "Flyer.pdf")
    fake = Fake(tesseract_reader=lambda name, number: tesseract_page(name, number))
    settings = settings_for(database, archive)
    options = options_for(settings, documents=[flyer.id])
    result = await run_ai(settings, options, engines=fake.engines())

    assert result.exit_code == 0
    assert {read[1] for read in fake.reads} == {"Flyer.pdf"}
    assert (result.summary.queued, result.summary.done) == (1, 1)
    queued = await tasks(database)
    assert {name: row.status for name, row in queued.items()} == {
        "Scan.pdf": "waiting",
        "Flyer.pdf": "done",
        "Foto.jpg": "waiting",
    }


async def test_nothing_queued_skips_the_later_steps(archive: Archive, database: str) -> None:
    settings = settings_for(database, archive)
    result = await run_ai(settings, options_for(settings), engines=Fake().engines())
    assert result.exit_code == 0 and result.summary.documents == 0
    job = await latest(database)
    assert steps(job) == {
        "check": "done",
        "ocr": "skipped",
        "transcribe": "skipped",
        "entities": "skipped",
        "signals": "skipped",
    }


async def test_auto_reads_images_and_uncertain_pages_with_the_vision_model(
    archive: Archive, database: str
) -> None:
    await queue(database, "Scan.pdf", "Foto.jpg")

    def unsure(name: str, number: int) -> OcrPage:
        confidence = 30.0 if number in (2, 3) else 95.0
        uncertain = confidence < 60
        return tesseract_page(name, number, confidence=confidence, uncertain=uncertain, seconds=1.0)

    def vision(name: str, number: int) -> OcrPage:
        body = "" if number == 3 else f"Vision {name} {number}"  # page 3: nothing better
        return OcrPage(
            number=number, engine="vision", text=body, tokens_in=7, tokens_out=3, seconds=4.0
        )

    fake = Fake(tesseract_reader=unsure, vision_reader=vision)
    settings = settings_for(
        database, archive, ai_vision_url=VISION_URL, ai_vision_model="lesemodell"
    )
    result = await run_ai(settings, options_for(settings), engines=fake.engines())

    assert result.exit_code == 0 and result.summary.vision == VISION_URL
    assert ("vision", "Foto.jpg", 1) in fake.reads
    assert ("tesseract", "Foto.jpg", 1) not in fake.reads
    assert [read for read in fake.reads if read[1] == "Scan.pdf"] == [
        ("tesseract", "Scan.pdf", 1),
        ("tesseract", "Scan.pdf", 2),
        ("vision", "Scan.pdf", 2),
        ("tesseract", "Scan.pdf", 3),
        ("vision", "Scan.pdf", 3),
    ]
    assert ("Scan.pdf", "vision", 2, 1) in fake.renders  # rendered again for the vision model
    scanned = await document(database, "Scan.pdf")
    assert [page["engine"] for page in scanned.read] == ["tesseract", "vision", "tesseract"]
    assert scanned.extracted_text == PAGE_SEPARATOR.join(
        ["Scan.pdf 1", "Vision Scan.pdf 2", "Scan.pdf 3"]
    )
    assert (scanned.result_engine, scanned.model, scanned.service_url) == (
        "mixed",
        "lesemodell",
        VISION_URL,
    )
    assert (scanned.prompt_version, scanned.remote) == (3, False)
    image = await document(database, "Foto.jpg")
    assert (image.extracted_text, image.result_engine) == ("Vision Foto.jpg 1", "vision")
    assert (result.summary.tokens_in, result.summary.tokens_out) == (21, 9)
    found = await rows(database, "SELECT engine, model, samples FROM ai_calibration ORDER BY 1")
    # The pages kept: Tesseract 1 and 3 of the scan, the vision model 2 and the photo.
    assert [tuple(row) for row in found] == [("tesseract", "", 2), ("vision", "lesemodell", 2)]


async def test_without_a_usable_vision_service_auto_reads_everything_with_tesseract(
    archive: Archive, database: str, caplog: pytest.LogCaptureFixture
) -> None:
    await queue(database, "Foto.jpg")
    fake = Fake(check_result={"reachable": False, "error": "connection refused"})
    settings = settings_for(database, archive, ai_vision_url=VISION_URL, ai_vision_model="m")
    with caplog.at_level(logging.INFO):
        result = await run_ai(settings, options_for(settings), engines=fake.engines())
    assert result.exit_code == 0 and result.summary.vision is None
    assert fake.reads == [("tesseract", "Foto.jpg", 1)]
    assert "everything goes to Tesseract: http://127.0.0.1:9/v1 does not answer" in caplog.text


def holding(number: int) -> tuple[Reader, threading.Event, threading.Event]:
    """A Tesseract reader that holds page number until released; and the events."""
    reading, release = threading.Event(), threading.Event()

    def slow(name: str, page: int) -> OcrPage:
        if page == number:
            reading.set()
            assert release.wait(10)
        return tesseract_page(name, page)

    return slow, reading, release


async def stopped_while_reading(
    database: str, reading: threading.Event, release: threading.Event, run: Any
) -> ai_run.AiRun:
    """Run, ask it to stop as the dashboard does while a page is read, then let the page end."""
    running = asyncio.create_task(run)
    async with asyncio.timeout(10):
        while not reading.is_set():
            await asyncio.sleep(0.02)
    engine = create_async_engine(database, poolclass=pool.NullPool)
    async with engine.begin() as connection:
        assert await jobs.job_alive(connection, JobKind.AI)
        assert await jobs.request_stop(connection, JobKind.AI) is not None
    await engine.dispose()
    await asyncio.sleep(0.3)  # the run reads the request at its next report
    release.set()
    return await asyncio.wait_for(running, 10)


async def test_a_stopped_run_continues_at_the_next_page(archive: Archive, database: str) -> None:
    await queue(database, "Scan.pdf")
    slow, reading, release = holding(2)
    fake = Fake(tesseract_reader=slow)
    settings = settings_for(database, archive)
    run = run_ai(settings, options_for(settings), engines=fake.engines())
    first = await stopped_while_reading(database, reading, release, run)

    assert first.exit_code == jobrun.EXIT_INTERRUPTED
    assert first.summary.status == "stopped" and first.summary.pages == 2
    task = (await tasks(database))["Scan.pdf"]
    assert (task.status, task.attempts, task.result_id) == ("waiting", 0, None)
    assert [page["number"] for page in task.partial["pages"]] == [1, 2]
    job = await latest(database)
    assert job.status == "stopped" and "stopped on request" in job.message
    assert steps(job) == {
        "check": "done",
        "ocr": "stopped",
        "transcribe": "waiting",
        "entities": "skipped",
        "signals": "skipped",
    }

    fake.reads.clear()
    second = await run_ai(settings, options_for(settings), engines=fake.engines())
    assert second.exit_code == 0
    assert fake.reads == [("tesseract", "Scan.pdf", 3)]
    assert fake.renders[-1] == ("Scan.pdf", "tesseract", 3, 1)
    scanned = await document(database, "Scan.pdf")
    assert [page["number"] for page in scanned.read] == [1, 2, 3]
    assert (await tasks(database))["Scan.pdf"].status == "done"


async def test_a_stop_during_the_last_page_stores_the_document(
    archive: Archive, database: str
) -> None:
    await queue(database, "Flyer.pdf", "Scan.pdf")
    slow, reading, release = holding(1)
    settings = settings_for(database, archive)
    run = run_ai(settings, options_for(settings), engines=Fake(tesseract_reader=slow).engines())
    result = await stopped_while_reading(database, reading, release, run)
    assert result.exit_code == jobrun.EXIT_INTERRUPTED and result.summary.done == 1
    queued = await tasks(database)
    assert (queued["Flyer.pdf"].status, queued["Scan.pdf"].status) == ("done", "waiting")
    assert (await document(database, "Flyer.pdf")).extracted_text == "Flyer.pdf 1"


async def test_a_pass_reads_at_most_max_pages_and_the_next_continues(
    archive: Archive, database: str
) -> None:
    await queue(database, "Scan.pdf")
    fake = Fake()
    settings = settings_for(database, archive)
    await run_ai(settings, options_for(settings, max_pages=2), engines=fake.engines())
    scanned = await document(database, "Scan.pdf")
    assert ([page["number"] for page in scanned.read], scanned.result_pages_total) == ([1, 2], 3)

    await queue(database, "Scan.pdf")  # done tasks leave room for a new one
    fake.reads.clear()
    await run_ai(settings, options_for(settings, max_pages=2), engines=fake.engines())
    assert fake.reads == [("tesseract", "Scan.pdf", 3)]
    scanned = await document(database, "Scan.pdf")
    assert [page["number"] for page in scanned.read] == [1, 2, 3]


async def test_a_task_left_running_by_a_dead_run_waits_again(
    archive: Archive, database: str, caplog: pytest.LogCaptureFixture
) -> None:
    await queue(database, "Flyer.pdf")
    await rows(database, "UPDATE ai_task SET status = 'running'")
    settings = settings_for(database, archive)
    with caplog.at_level(logging.WARNING):
        result = await run_ai(settings, options_for(settings), engines=Fake().engines())
    assert result.summary.done == 1
    assert "1 tasks left running by an earlier run wait again" in caplog.text


# Failures (D184) --------------------------------------------------------------------------------


async def test_tesseract_without_its_languages_stops_before_any_task(
    archive: Archive, database: str
) -> None:
    await queue(database, "Flyer.pdf")
    fake = Fake(tesseract_missing=True)
    settings = settings_for(database, archive)
    result = await run_ai(settings, options_for(settings), engines=fake.engines())
    assert result.exit_code == ai_run.EXIT_FAILED and fake.renders == []
    assert result.summary.message.endswith("Tesseract has no language data for deu+eng")
    assert (await tasks(database))["Flyer.pdf"].status == "waiting"


async def test_a_task_fails_after_three_attempts(archive: Archive, database: str) -> None:
    await queue(database, "Flyer.pdf", "Foto.jpg")
    fake = Fake(render_error={"Flyer.pdf"})
    settings = settings_for(database, archive)
    result = await run_ai(settings, options_for(settings), engines=fake.engines())
    assert result.exit_code == 0
    assert (result.summary.done, result.summary.failed) == (1, 1)
    assert [render[0] for render in fake.renders].count("Flyer.pdf") == 3
    flyer = (await tasks(database))["Flyer.pdf"]
    assert (flyer.status, flyer.attempts) == ("failed", 3)
    assert flyer.error == "cannot render: RenderError: pdftoppm ended with status 1"
    assert flyer.finished_at is not None
    assert (await document(database, "Flyer.pdf")).origin == "extracted"


async def test_an_unreadable_file_is_an_attempt(
    archive: Archive, database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await queue(database, "Flyer.pdf")

    def gone(mbox_dir: Path, source: Any) -> bytes:
        raise FileNotFoundError(f"{source.path} is not there")

    monkeypatch.setattr(ai_run, "read_attachment", gone)
    settings = settings_for(database, archive)
    result = await run_ai(settings, options_for(settings), engines=Fake().engines())
    assert result.summary.failed == 1
    flyer = (await tasks(database))["Flyer.pdf"]
    assert (flyer.status, flyer.attempts) == ("failed", 3)
    assert flyer.error == "unreadable: FileNotFoundError: ai.mbox is not there"


async def test_a_page_with_invalid_answers_is_kept_with_its_error(
    archive: Archive, database: str
) -> None:
    await queue(database, "Scan.pdf", engine="vision")

    def answers(name: str, number: int) -> OcrPage:
        if number == 2:
            raise AnswerError("the answer was cut at its length limit")
        return OcrPage(number=number, engine="vision", text=f"Text {number}")

    fake = Fake(vision_reader=answers)
    settings = settings_for(database, archive, ai_vision_url=VISION_URL, ai_vision_model="m")
    result = await run_ai(settings, options_for(settings), engines=fake.engines())
    assert result.exit_code == 0 and result.summary.done == 1
    assert fake.reads.count(("vision", "Scan.pdf", 2)) == 3
    scanned = await document(database, "Scan.pdf")
    assert scanned.extracted_text == PAGE_SEPARATOR.join(["Text 1", "Text 3"])
    assert scanned.read[1]["error"] == "AnswerError: the answer was cut at its length limit"


async def test_an_unreachable_service_is_waited_for_and_fails_nothing(
    archive: Archive, database: str, caplog: pytest.LogCaptureFixture
) -> None:
    await queue(database, "Foto.jpg", engine="vision")
    calls = 0

    def flaky(name: str, number: int) -> OcrPage:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise Unreachable("connection refused")
        return OcrPage(number=number, engine="vision", text="Schild")

    settings = settings_for(database, archive, ai_vision_url=VISION_URL, ai_vision_model="m")
    with caplog.at_level(logging.WARNING):
        result = await run_ai(
            settings, options_for(settings), engines=Fake(vision_reader=flaky).engines()
        )
    assert result.exit_code == 0 and result.summary.done == 1 and calls == 3
    assert caplog.text.count(f"waiting for {VISION_URL}") == 2
    job = await latest(database)
    assert AiProgress.model_validate(job.progress).unreachable_since is None


async def test_the_check_waits_for_a_service_tasks_need(
    archive: Archive, database: str, caplog: pytest.LogCaptureFixture
) -> None:
    await queue(database, "Foto.jpg", engine="vision")
    fake = Fake()
    asked = 0

    def check(service: Service, settings: Settings, *, test: bool) -> ServiceCheck:
        nonlocal asked
        asked += 1
        found = fake.check(service, settings, test=test)
        if asked == 1:
            return found.model_copy(update={"reachable": False, "error": "connection refused"})
        return found

    settings = settings_for(database, archive, ai_vision_url=VISION_URL, ai_vision_model="m")
    with caplog.at_level(logging.WARNING):
        result = await run_ai(
            settings, options_for(settings), engines=replace(fake.engines(), check=check)
        )
    assert result.exit_code == 0 and result.summary.done == 1 and asked == 2
    assert f"waiting for {VISION_URL} (connection refused)" in caplog.text


async def test_a_service_silent_too_long_stops_the_run(
    archive: Archive, database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ai_run, "WAIT_LIMIT", 0.05)
    await queue(database, "Scan.pdf", engine="vision")

    def silent(name: str, number: int) -> OcrPage:
        if number == 2:
            raise Unreachable("timed out")
        return OcrPage(number=number, engine="vision", text=f"Text {number}")

    settings = settings_for(database, archive, ai_vision_url=VISION_URL, ai_vision_model="m")
    result = await run_ai(
        settings, options_for(settings), engines=Fake(vision_reader=silent).engines()
    )
    assert result.exit_code == ai_run.EXIT_FAILED and result.summary.status == "stopped"
    job = await latest(database)
    assert job.status == "stopped" and job.message.endswith(
        f"{VISION_URL} did not answer for 0 minutes"
    )
    assert AiProgress.model_validate(job.progress).unreachable_since is not None
    task = (await tasks(database))["Scan.pdf"]
    assert (task.status, task.attempts, task.error) == ("waiting", 0, None)
    assert [page["number"] for page in task.partial["pages"]] == [1]


async def test_a_missing_model_stops_the_run_before_any_task(
    archive: Archive, database: str
) -> None:
    await queue(database, "Foto.jpg")
    fake = Fake(check_result={"model_found": False})
    settings = settings_for(database, archive, ai_vision_url=VISION_URL, ai_vision_model="weg")
    result = await run_ai(settings, options_for(settings), engines=fake.engines())
    assert result.exit_code == ai_run.EXIT_FAILED and fake.renders == []
    job = await latest(database)
    assert job.status == "failed"
    assert job.message.endswith(f"{VISION_URL} does not offer the model weg")
    task = (await tasks(database))["Foto.jpg"]
    assert (task.status, task.started_at) == ("waiting", None)


async def test_a_model_gone_during_the_run_stops_it(archive: Archive, database: str) -> None:
    await queue(database, "Scan.pdf", engine="vision")

    def gone(name: str, number: int) -> OcrPage:
        if number == 2:
            raise ModelMissing("the model m is not loaded")
        return OcrPage(number=number, engine="vision", text="Text")

    settings = settings_for(database, archive, ai_vision_url=VISION_URL, ai_vision_model="m")
    result = await run_ai(
        settings, options_for(settings), engines=Fake(vision_reader=gone).engines()
    )
    assert result.exit_code == ai_run.EXIT_FAILED
    assert (await latest(database)).message.endswith("ModelMissing: the model m is not loaded")
    task = (await tasks(database))["Scan.pdf"]
    assert (task.status, len(task.partial["pages"])) == ("waiting", 1)


async def test_tasks_needing_vision_fail_the_run_without_a_vision_service(
    archive: Archive, database: str
) -> None:
    await queue(database, "Flyer.pdf", engine="vision")
    settings = settings_for(database, archive)
    result = await run_ai(settings, options_for(settings), engines=Fake().engines())
    assert result.exit_code == ai_run.EXIT_FAILED
    assert result.summary.message.endswith(
        "tasks need the vision model: no vision service is configured (MAILROBBE_AI_VISION_URL)"
    )


# Remote services (D181) -------------------------------------------------------------------------


async def test_a_remote_service_is_refused_without_permission(
    archive: Archive, database: str
) -> None:
    await queue(database, "Flyer.pdf", engine="vision")
    fake = Fake()
    settings = settings_for(database, archive, ai_vision_url=REMOTE_URL, ai_vision_model="m")
    result = await run_ai(settings, options_for(settings), engines=fake.engines())
    assert result.exit_code == ai_run.EXIT_FAILED and fake.reads == []
    assert "set MAILROBBE_AI_ALLOW_REMOTE=true to use it" in result.summary.message
    assert await rows(database, "SELECT * FROM ai_send_log") == []


async def test_a_remote_service_logs_what_it_sends_and_keeps_to_the_budget(
    archive: Archive, database: str, caplog: pytest.LogCaptureFixture
) -> None:
    await queue(database, "Scan.pdf", engine="vision")
    settings = settings_for(
        database,
        archive,
        ai_vision_url=REMOTE_URL,
        ai_vision_model="m",
        ai_vision_key="geheim-123",
        ai_allow_remote=True,
        ai_remote_token_budget=15,
    )
    with caplog.at_level(logging.INFO):
        result = await run_ai(settings, options_for(settings), engines=Fake().engines())
    assert result.exit_code == ai_run.EXIT_FAILED and result.summary.status == "stopped"
    assert result.summary.pages == 2  # 10 tokens each: the second page went over 15
    assert "the budget of 15 tokens for services outside this machine is used up" in (
        result.summary.message
    )
    sent = await rows(database, "SELECT * FROM ai_send_log ORDER BY id")
    job = await latest(database)
    sha256 = (await document(database, "Scan.pdf")).sha256
    assert [(row.service_url, row.kind, row.target_sha256, row.job_id) for row in sent] == [
        (REMOTE_URL, "ocr", sha256, job.id)
    ] * 2
    assert [row.bytes for row in sent] == [len(b"Scan.pdf|1|vision"), len(b"Scan.pdf|2|vision")]
    assert job.options["vision_remote"] is True
    task = (await tasks(database))["Scan.pdf"]
    for stored in (
        str(job.options),
        str(job.progress),
        job.message,
        caplog.text,
        str(task.partial),
    ):
        assert "geheim" not in stored


# Exclusion (D187) -------------------------------------------------------------------------------


async def test_an_import_and_an_ai_run_exclude_each_other(archive: Archive, database: str) -> None:
    settings = settings_for(database, archive)
    engine = create_async_engine(database, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": jobs.AI_LOCK_KEY})
            await connection.commit()
            assert await run_import(settings, archive.mbox_dir, 1) == 1
            await connection.execute(text("SELECT pg_advisory_unlock_all()"))
            await connection.commit()

            await connection.execute(
                text("SELECT pg_advisory_lock(:k)"), {"k": jobs.IMPORT_LOCK_KEY}
            )
            await connection.commit()
            with pytest.raises(jobrun.RunRefused, match="an import is running"):
                await run_ai(settings, options_for(settings), engines=Fake().engines())
            await connection.execute(text("SELECT pg_advisory_unlock_all()"))
            await connection.commit()
    finally:
        await engine.dispose()
    found = await rows(database, "SELECT kind::text FROM job WHERE kind IN ('ai', 'import')")
    assert [row.kind for row in found] == ["import"]  # the archive's own import


# The real Tesseract -----------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("tesseract") is None or shutil.which("pdftoppm") is None,
    reason="needs tesseract and pdftoppm",
)
async def test_the_real_tesseract_makes_a_scan_searchable(archive: Archive, database: str) -> None:
    await queue(database, "Brief.pdf")
    settings = settings_for(database, archive)
    result = await run_ai(
        settings, options_for(settings, ocr_engine="tesseract"), engines=ai_run.default_engines()
    )
    assert result.exit_code == 0 and result.summary.done == 1
    found = await rows(
        database,
        "SELECT name, text_origin::text AS origin FROM document "
        "WHERE tsv @@ websearch_to_tsquery('german', :word)",
        {"word": WORD},
    )
    assert [(row.name, row.origin) for row in found] == [("Brief.pdf", "ocr")]


@pytest.mark.parametrize("flavour", ["lmstudio", "ollama"])
async def test_the_real_engines_read_a_photo_with_a_vision_service(
    archive: Archive, database: str, flavour: Any
) -> None:
    await queue(database, "Foto.jpg", "Brief.pdf")
    with fake_service(flavour, answer="Schild am Eingang", tokens=(900, 12)) as fake:
        settings = settings_for(
            database, archive, ai_vision_url=fake.url, ai_vision_model="vision-model"
        )
        result = await run_ai(settings, options_for(settings), engines=ai_run.default_engines())
        assert len(fake.chats) == 1  # the photo; the scan is Tesseract's and certain
        assert fake.images()[0].startswith(b"\x89PNG")
    assert result.exit_code == 0 and result.summary.done == 2
    image = await document(database, "Foto.jpg")
    assert (image.extracted_text, image.result_engine, image.model) == (
        "Schild am Eingang",
        "vision",
        "vision-model",
    )
    assert (image.service_url, image.prompt_version) == (fake.url, load_prompts().version)
    assert (result.summary.tokens_in, result.summary.tokens_out) == (900, 12)
    letter = await document(database, "Brief.pdf")
    assert WORD in letter.extracted_text and letter.result_engine == "tesseract"

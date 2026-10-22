"""Summaries in the AI run (D300 to D308) on a small imported archive: what the model reads of a
mail and a document, the step summarize against a fake text service, and the command line."""

import asyncio
import json
import logging
import re
import threading
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from sqlalchemy import make_url, pool
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import cli as main_cli
from mailrobbe import jobrun, jobs, migrate
from mailrobbe.ai import cli as ai_cli
from mailrobbe.ai import run as ai_run
from mailrobbe.ai.model import CHARS_PER_TOKEN, AiOptions, AiProgress, locality
from mailrobbe.ai.prompts import load_prompts
from mailrobbe.ai.queue import enqueue_summaries
from mailrobbe.ai.run import run_ai
from mailrobbe.ai.services import ChatAnswer
from mailrobbe.ai.summarize import step as summarize_step
from mailrobbe.ai.summarize.inputs import FORWARDED, document_input, mail_input
from mailrobbe.config import Settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.enums import JobKind
from mailrobbe.importer.cli import run_import
from mailrobbe.themes import load_themes
from tests.ai.fakes import FakeService, fake_service
from tests.ai.test_run import REMOTE_URL, Fake, Page, Rendered, rows
from tests.attachments.doubles import attachment_mail
from tests.conftest import _temporary_database
from tests.importer.doubles import SEPARATOR

pytestmark = pytest.mark.db

THEME = load_themes()[0].key
MODEL = "textmodell"
SOMMERFEST = (
    "Hallo Bert,\n\n"
    "das Sommerfest des Fördervereins findet am 14. Juni im Garten der Schule statt. Wir "
    "brauchen noch Helfer für den Aufbau am Vormittag, für den Kuchenstand und für die Kasse. "
    "Der Vorstand hat eine Spende über 500 Euro von der Sparkasse bekommen, die wir für Zelte "
    "und Bänke ausgeben. Bitte sag mir bis Freitag, ob du mitmachst und wen du noch fragen "
    "kannst. Die Einladungen gehen nächste Woche an alle Mitglieder.\n\n"
    "Viele Grüße\nAnna\n\n"
    "Am 01.01.2024 um 10:00 schrieb Bert <bert@b.example>:\n"
    "> Wann ist das Sommerfest?\n"
    "> Gruß Bert\n\n"
    "-- \nAnna Berger\nFörderverein\n"
)
FORWARD = (
    "Zur Info.\n\n"
    "---------- Forwarded message ---------\n"
    "Von: Carla <carla@c.example>\n"
    "Betreff: Kasse\n\n"
    "Die Kasse ist geprüft, alles stimmt.\n"
)
REPORT = "\n\n".join(
    f"Abschnitt {n}: " + "Der Kassenbericht des Jahres nennt Einnahmen und Ausgaben. " * 6
    for n in range(1, 41)
)
# subject, body, attachments; Sommerfest twice, the second a duplicate
MAILS: list[tuple[str, str, list[tuple[str, str, bytes]]]] = [
    ("Kurze Antwort", "Danke, passt so.\n\n-- \nAnna\n", []),
    ("Sommerfest", SOMMERFEST, []),
    ("Bericht", "Anbei der Bericht.\n", [("Bericht.txt", "text/plain", REPORT.encode())]),
    ("Weiterleitung", FORWARD, []),
]


@pytest.fixture(scope="module")
def archive(database_server_url: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    mbox_dir = tmp_path_factory.mktemp("summaries") / "mbox"
    mbox_dir.mkdir()
    with (mbox_dir / "summaries.mbox").open("wb") as handle:
        for index, (subject, body, files) in enumerate(MAILS):
            mail = attachment_mail(index, files, subject, body=body)
            handle.write(SEPARATOR + b"\n" + mail + b"\n")
            if subject == "Sommerfest":
                handle.write(SEPARATOR + b"\n" + mail + b"\n")
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(database_url=url, mbox_dir=mbox_dir)
        assert asyncio.run(run_import(settings, mbox_dir, 1)) == 0
        name = make_url(url).database
        assert name is not None
        yield database_server_url, name, mbox_dir


@pytest.fixture
def database(archive: Any) -> Iterator[str]:
    server, template, _ = archive
    with _temporary_database(server, template=template) as url:
        yield url


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobrun, "REPORT_SECONDS", 0.05)
    monkeypatch.setattr(ai_run, "WAIT_FIRST", 0.01)
    monkeypatch.setattr(ai_run, "WAIT_MAX", 0.02)


def settings_for(url: str, archive: Any, **values: Any) -> Settings:
    return Settings(database_url=url, mbox_dir=archive[2], import_workers=1, **values)


def options_for(settings: Settings, **values: Any) -> AiOptions:
    return AiOptions.from_settings(settings).model_copy(update=values)


async def mail_ids(url: str, subject: str) -> list[int]:
    found = await rows(url, "SELECT id FROM mail WHERE subject = :s ORDER BY id", {"s": subject})
    return [row.id for row in found]


async def report(url: str) -> Any:
    (found,) = await rows(url, "SELECT * FROM document WHERE name = 'Bericht.txt'")
    return found


async def queue(url: str, *subjects: str, report_too: bool = False) -> None:
    ids = [mail for subject in subjects for mail in (await mail_ids(url, subject))[:1]]
    documents = [(await report(url)).id] if report_too else []
    engine = create_engine(url)
    try:
        async with create_sessionmaker(engine).begin() as session:
            queued = await enqueue_summaries(session, mail_ids=ids, document_ids=documents)
    finally:
        await engine.dispose()
    assert queued.queued == len(ids) + len(documents)


async def tasks(url: str) -> dict[str, Any]:
    """The summarize tasks by subject or file name."""
    found = await rows(
        url,
        """
        SELECT COALESCE(
            (SELECT subject FROM mail WHERE raw_sha256 = t.target_sha256 ORDER BY id LIMIT 1),
            (SELECT name FROM document WHERE sha256 = t.target_sha256)) AS name, t.*
        FROM ai_task t WHERE t.kind = 'summarize'
        """,
    )
    return {row.name: row for row in found}


async def results(url: str) -> dict[str, Any]:
    """The valid summaries by subject or file name, with their tags and hints."""
    found = await rows(
        url,
        """
        SELECT COALESCE(
            (SELECT subject FROM mail WHERE raw_sha256 = r.target_sha256 ORDER BY id LIMIT 1),
            (SELECT name FROM document WHERE sha256 = r.target_sha256)) AS name, r.*,
            ARRAY(SELECT t.label FROM ai_tag_link l JOIN ai_tag t ON t.id = l.tag_id
                  WHERE l.result_id = r.id ORDER BY t.label COLLATE "C") AS tags,
            ARRAY(SELECT json_build_object('theme', h.theme, 'quote', h.quote,
                      'position', h.position)
                  FROM ai_theme_hint h WHERE h.result_id = r.id ORDER BY h.id) AS hints
        FROM ai_result r WHERE r.kind = 'summarize' AND r.state = 'valid'
        """,
    )
    return {row.name: row for row in found}


async def latest(url: str) -> Any:
    (job,) = await rows(url, "SELECT * FROM job WHERE kind = 'ai' ORDER BY id DESC LIMIT 1")
    return job


def steps(job: Any) -> dict[str, Any]:
    return {step.key: step for step in AiProgress.model_validate(job.progress).steps}


def reply(summary: str, tags: list[str], themes: Sequence[tuple[str, str]] = ()) -> str:
    found = [{"theme": theme, "quote": quote} for theme, quote in themes]
    return json.dumps({"summary": summary, "tags": tags, "themes": found})


def user_of(body: Any) -> str:
    return str(body["messages"][1]["content"])


class Model:
    """Answers as a text model would, from what it is asked; the part numbered hold waits until
    released. It asserts nothing: an error in the fake's thread would read as no answer."""

    def __init__(self, hold: int | None = None) -> None:
        self.hold = hold
        self.reading, self.release = threading.Event(), threading.Event()
        self.asked: list[str] = []  # "short", "whole", "part n of m", "combine"

    def __call__(self, body: Any) -> str:
        user = user_of(body)
        if user.startswith("Das Material ist kurz"):
            self.asked.append("short")
            return reply("Das sollte leer bleiben.", ["Dank"])
        if user.startswith("Das Material sind die Zusammenfassungen"):
            self.asked.append("combine")
            return reply("Der Kassenbericht des Jahres.", ["Kassenbericht", "Jahresbericht"])
        found = re.match(r"Das Material ist Teil (\d+) von (\d+)", user)
        if found is None:
            self.asked.append("whole")
            return reply(
                "Anna lädt zum Sommerfest ein und sucht Helfer.",
                ["Sommerfest", "Helfer", "sommerfest"],
                [(THEME, "„Spende über 500 Euro“"), (THEME, "Kuchenstand"), ("keins", "Kasse")],
            )
        number = int(found[1])
        self.asked.append(f"part {number} of {found[2]}")
        if number == self.hold:
            self.reading.set()
            self.release.wait(10)
        found = re.search(r"Abschnitt \d+", user.partition("Textquelle")[2])
        section = found[0] if found else "kein Abschnitt"
        return reply(
            f"Teil {number}: {section} und weitere.", ["Kassenbericht"], [(THEME, section)]
        )


def text_service(model: Model, flavour: Any = "lmstudio", **values: Any) -> Any:
    return fake_service(flavour, models={MODEL: None}, respond=model, delay=0.01, **values)


def text_settings(url: str, archive: Any, fake: FakeService, **values: Any) -> Settings:
    return settings_for(url, archive, ai_text_url=fake.url, ai_text_model=MODEL, **values)


# What the model reads (D302) -------------------------------------------------------------------


async def read_mail(url: str, subject: str) -> Any:
    engine = create_engine(url)
    try:
        async with create_sessionmaker(engine)() as session:
            (sha256,) = await rows(
                url, "SELECT raw_sha256 FROM mail WHERE subject = :s LIMIT 1", {"s": subject}
            )
            return await mail_input(session, sha256.raw_sha256)
    finally:
        await engine.dispose()


async def test_a_mail_is_read_with_its_head_and_its_own_text(database: str) -> None:
    found = await read_mail(database, "Sommerfest")
    assert found.head == (
        "Art: E-Mail",
        "Betreff: Sommerfest",
        "Datum: 02.01.2024 10:00 UTC",
        "Von: Anna <anna@a.example>",
        "An: Bert <bert@b.example>",
    )
    assert found.text.startswith("Hallo Bert,\n\ndas Sommerfest")
    assert found.text.endswith("Viele Grüße\nAnna")
    assert "Wann ist" not in found.text and "Anna Berger" not in found.text
    assert (found.short, found.words, found.name) == (False, len(found.text.split()), "Sommerfest")
    (body,) = await rows(
        database, "SELECT body_text FROM mail WHERE subject = 'Sommerfest' LIMIT 1"
    )
    at = found.text.index("Spende")
    stored = found.stored(at)
    assert stored is not None
    assert body.body_text[stored : stored + 20] == "Spende über 500 Euro"

    short = await read_mail(database, "Kurze Antwort")
    assert (short.text, short.words, short.short) == ("Danke, passt so.", 3, True)

    report_mail = await read_mail(database, "Bericht")
    assert report_mail.head[-1] == "Anhänge: Bericht.txt"


async def test_a_short_mail_with_a_forward_reads_the_forward(database: str) -> None:
    found = await read_mail(database, "Weiterleitung")
    assert found.short is True
    assert found.text.startswith(f"Zur Info.\n\n{FORWARDED}\n---------- Forwarded message")
    assert found.text.endswith("Die Kasse ist geprüft, alles stimmt.")
    assert found.stored(found.text.index(FORWARDED)) is None
    (body,) = await rows(database, "SELECT body_text FROM mail WHERE subject = 'Weiterleitung'")
    at = found.stored(found.text.index("Die Kasse"))
    assert at is not None and body.body_text[at:].startswith("Die Kasse ist geprüft")


@pytest.mark.parametrize(
    ("origin", "shown"),
    [("extracted", "aus der Datei"), ("ocr", "maschinell erkannt"), ("transcript", "Transkript")],
)
async def test_a_document_is_read_with_where_its_text_comes_from(
    database: str, origin: str, shown: str
) -> None:
    await rows(
        database,
        "UPDATE document SET text_origin = CAST(:o AS text_origin) WHERE name = 'Bericht.txt'",
        {"o": origin},
    )
    document = await report(database)
    engine = create_engine(database)
    try:
        async with create_sessionmaker(engine)() as session:
            found = await document_input(session, document.sha256)
    finally:
        await engine.dispose()
    assert found is not None
    assert found.head == (
        "Art: Dokument (Text)",
        "Dateiname: Bericht.txt",
        "Datum der ersten Mail: 03.01.2024 10:00 UTC",
        "Absender der ersten Mail: Anna <anna@a.example>",
        f"Textquelle: {shown}",
    )
    assert (found.text, found.origin, found.short) == (document.extracted_text, origin, False)
    assert found.stored(100) == 100


# The run ----------------------------------------------------------------------------------------


async def test_a_run_summarises_a_mail_and_a_short_one(archive: Any, database: str) -> None:
    await queue(database, "Sommerfest", "Kurze Antwort")
    model = Model()
    with text_service(model) as fake:
        settings = text_settings(database, archive, fake)
        result = await run_ai(settings, options_for(settings))
        chats = fake.chats

    assert result.exit_code == 0
    assert sorted(model.asked) == ["short", "whole"]
    summary = result.summary
    assert (summary.status, summary.summaries_queued, summary.summaries) == ("done", 2, 2)
    assert (summary.summaries_failed, summary.text, summary.documents) == (0, fake.url, 0)
    assert summary.tokens_in == 2 * 1200 and summary.tokens_out == 2 * 40
    for chat in chats:
        assert chat.body["response_format"]["json_schema"]["schema"]["properties"]["themes"]
        system = chat.body["messages"][0]["content"]
        assert "Vorhandene Schlagwörter:\n(noch keine)" in system

    found = await results(database)
    sommerfest, short = found["Sommerfest"], found["Kurze Antwort"]
    assert sommerfest.body == "Anna lädt zum Sommerfest ein und sucht Helfer."
    assert (sommerfest.engine, sommerfest.model, sommerfest.target) == ("text", MODEL, "mail")
    assert (sommerfest.remote, sommerfest.prompt_version) == (
        False,
        load_prompts().summarize.version,
    )
    assert sommerfest.service_url == fake.url
    assert sommerfest.tags == ["Helfer", "Sommerfest"]
    (body,) = await rows(
        database, "SELECT body_text FROM mail WHERE subject = 'Sommerfest' LIMIT 1"
    )
    assert sommerfest.hints == [
        {
            "theme": THEME,
            "quote": "Spende über 500 Euro",
            "position": body.body_text.index("Spende"),
        },
        {"theme": THEME, "quote": "Kuchenstand", "position": body.body_text.index("Kuchenstand")},
    ]
    options = sommerfest.options
    assert (options["short"], options["dropped_tags"], options["dropped_themes"]) == (False, 0, 1)
    assert (options["context_tokens"], options["origin"]) == (4096, None)
    assert sommerfest.pages_total == 1 and len(sommerfest.pages) == 1
    assert sommerfest.pages[0]["summary"] == sommerfest.body
    assert sommerfest.pages[0]["tokens_in"] == 1200
    assert (short.body, short.tags, short.options["short"]) == ("", ["Dank"], True)

    queued = await tasks(database)
    assert {row.status for row in queued.values()} == {"done"}
    assert all(row.partial == {} and row.result_id is not None for row in queued.values())
    (calibration,) = await rows(database, "SELECT * FROM ai_calibration")
    assert (calibration.kind, calibration.engine, calibration.model) == ("summarize", "text", MODEL)
    assert calibration.unit == "ktoken" and calibration.seconds_per_unit > 0
    assert 100 < calibration.samples * CHARS_PER_TOKEN < len(SOMMERFEST) + 400

    job = await latest(database)
    assert job.status == "done"
    assert job.message.endswith(", 2 of 2 texts summarised (0 failed), 2480 tokens")
    found_steps = steps(job)
    assert {key: step.status for key, step in found_steps.items()} == {
        "check": "done",
        "ocr": "skipped",
        "transcribe": "skipped",
        "summarize": "done",
        "entities": "skipped",
        "signals": "skipped",
    }
    counted = found_steps["summarize"]
    assert (counted.unit, counted.done, counted.total) == ("texts", 2, 2)
    assert AiProgress.model_validate(job.progress).summaries == 2


async def test_a_long_document_is_read_in_parts_and_a_stopped_run_continues(
    archive: Any, database: str
) -> None:
    await queue(database, report_too=True)
    model = Model(hold=2)
    with text_service(model) as fake:
        settings = text_settings(database, archive, fake)
        options = options_for(settings, context_tokens=4096)
        running = asyncio.create_task(run_ai(settings, options))
        async with asyncio.timeout(10):
            while not model.reading.is_set():
                await asyncio.sleep(0.02)
        engine = create_async_engine(database, poolclass=pool.NullPool)
        async with engine.begin() as connection:
            assert await jobs.request_stop(connection, JobKind.AI) is not None
        await engine.dispose()
        await asyncio.sleep(0.3)  # the run reads the request at its next report
        model.release.set()
        first = await asyncio.wait_for(running, 10)

        assert first.exit_code == jobrun.EXIT_INTERRUPTED
        assert (first.summary.status, first.summary.summaries) == ("stopped", 0)
        task = (await tasks(database))["Bericht.txt"]
        assert (task.status, task.attempts, task.result_id) == ("waiting", 0, None)
        total = task.partial["parts_total"]
        assert total >= 3
        assert [part["number"] for part in task.partial["parts"]] == [1, 2]
        assert model.asked == [f"part 1 of {total}", f"part 2 of {total}"]
        job = await latest(database)
        assert steps(job)["summarize"].status == "stopped"

        model.asked.clear()
        second = await run_ai(settings, options)
        combine = user_of(fake.chats[-1].body)
    assert second.exit_code == 0 and second.summary.summaries == 1
    assert "Teil 1:\nTeil 1: Abschnitt 1 und weitere.\nSchlagwörter: Kassenbericht" in combine
    assert model.asked == [*(f"part {n} of {total}" for n in range(3, total + 1)), "combine"]

    document = await report(database)
    result = (await results(database))["Bericht.txt"]
    assert (result.body, result.tags) == (
        "Der Kassenbericht des Jahres.",
        ["Jahresbericht", "Kassenbericht"],
    )
    assert (result.pages_total, len(result.pages)) == (total, total)
    assert [part["summary"].split(":")[0] for part in result.pages] == [
        f"Teil {n}" for n in range(1, total + 1)
    ]
    assert sum(part["characters"] for part in result.pages) <= len(document.extracted_text)
    hints = result.hints
    assert hints[0]["quote"] == "Abschnitt 1"
    assert len(hints) == 3  # one per part, three per theme (THEME_HINTS_PER_THEME)
    for hint in hints:
        at = hint["position"]
        assert document.extracted_text[at : at + len(hint["quote"])] == hint["quote"]
    assert result.options["context_tokens"] == 4096 and result.options["short"] is False
    assert result.options["origin"] == "extracted" and result.options["dropped_themes"] == total - 3
    assert (await tasks(database))["Bericht.txt"].partial == {}


async def test_a_run_for_one_mail_takes_only_its_content(archive: Any, database: str) -> None:
    await queue(database, "Sommerfest", "Kurze Antwort", report_too=True)
    original, duplicate = await mail_ids(database, "Sommerfest")
    model = Model()
    with text_service(model) as fake:
        settings = text_settings(database, archive, fake)
        result = await run_ai(settings, options_for(settings, mails=[duplicate]))
    assert result.exit_code == 0 and model.asked == ["whole"]
    assert (result.summary.summaries_queued, result.summary.summaries) == (1, 1)
    assert {name: row.status for name, row in (await tasks(database)).items()} == {
        "Sommerfest": "done",
        "Kurze Antwort": "waiting",
        "Bericht.txt": "waiting",
    }
    assert original < duplicate


async def test_an_answer_that_is_no_valid_one_is_an_attempt(archive: Any, database: str) -> None:
    await queue(database, "Sommerfest")
    with fake_service("ollama", models={MODEL: None}, answer="Kein JSON, nur Text.") as fake:
        settings = text_settings(database, archive, fake)
        result = await run_ai(settings, options_for(settings))
        assert len(fake.chats) == 3
    assert result.exit_code == 0
    assert (result.summary.summaries, result.summary.summaries_failed) == (0, 1)
    task = (await tasks(database))["Sommerfest"]
    assert (task.status, task.attempts) == ("failed", 3)
    assert task.error.startswith("no JSON object in the answer: Kein JSON")
    assert (await latest(database)).message.endswith(
        ", 0 of 1 texts summarised (1 failed), 3720 tokens"
    )


async def test_a_text_too_long_for_a_small_context_fails_at_once(
    archive: Any, database: str
) -> None:
    await queue(database, "Sommerfest")
    model = Model()
    with text_service(model) as fake:
        settings = text_settings(database, archive, fake)
        result = await run_ai(settings, options_for(settings, context_tokens=2048))
    assert result.exit_code == 0 and model.asked == []
    task = (await tasks(database))["Sommerfest"]
    assert (task.status, task.attempts) == ("failed", 0)
    assert "raise MAILROBBE_AI_CONTEXT_TOKENS" in task.error


async def test_without_a_usable_text_service_the_summaries_wait(
    archive: Any, database: str
) -> None:
    await queue(database, "Sommerfest")
    settings = settings_for(database, archive)
    result = await run_ai(settings, options_for(settings), engines=Fake().engines())
    assert result.exit_code == 0
    assert result.summary.message.endswith(
        ", 1 summaries wait: no text service is configured (MAILROBBE_AI_TEXT_URL)"
    )

    settings = settings_for(database, archive, ai_text_url=REMOTE_URL, ai_text_model=MODEL)
    result = await run_ai(settings, options_for(settings), engines=Fake().engines())
    assert result.exit_code == 0
    assert "set MAILROBBE_AI_ALLOW_REMOTE=true to use it" in result.summary.message
    assert (await tasks(database))["Sommerfest"].status == "waiting"
    assert steps(await latest(database))["summarize"].status == "skipped"
    assert await rows(database, "SELECT * FROM ai_send_log") == []


class AnyFake(Fake):
    """The engine doubles of test_run, rendering any file as one page."""

    def render(self, data: bytes, kind: str, *, purpose: str, **_: Any) -> Rendered:
        return Rendered(1, [Page(1, f"Bericht.txt|1|{purpose}".encode())])


async def test_a_text_service_that_does_not_answer_holds_up_no_ocr(
    archive: Any, database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await queue(database, "Sommerfest")
    await rows(
        database,
        "INSERT INTO ai_task (kind, target_sha256, engine) VALUES ('ocr', :sha256, 'tesseract')",
        {"sha256": (await report(database)).sha256},
    )
    silent = {"reachable": False, "protocol": None, "error": "connection refused"}
    fake = AnyFake(check_result=silent)
    settings = settings_for(
        database, archive, ai_text_url="http://127.0.0.1:9/v1", ai_text_model=MODEL
    )
    result = await run_ai(settings, options_for(settings), engines=fake.engines())
    assert result.exit_code == 0 and fake.reads == [("tesseract", "Bericht.txt", 1)]
    assert result.summary.message.endswith(
        ", 1 summaries wait: http://127.0.0.1:9/v1: connection refused"
    )
    assert (await tasks(database))["Sommerfest"].status == "waiting"

    # Only summaries wait: the run waits for the service, and stops when it stays silent.
    monkeypatch.setattr(ai_run, "WAIT_LIMIT", 0.05)
    result = await run_ai(settings, options_for(settings), engines=fake.engines())
    assert result.exit_code == ai_run.EXIT_FAILED and result.summary.status == "stopped"
    assert result.summary.message.endswith("http://127.0.0.1:9/v1 did not answer for 0 minutes")


async def test_a_missing_text_model_stops_the_run(archive: Any, database: str) -> None:
    await queue(database, "Sommerfest")
    with fake_service("lmstudio", models={"anderes": None}) as fake:
        settings = text_settings(database, archive, fake)
        result = await run_ai(settings, options_for(settings))
        assert not fake.chats
    assert result.exit_code == ai_run.EXIT_FAILED and result.summary.status == "failed"
    assert result.summary.message.endswith(f"{fake.url} does not offer the model {MODEL}")
    assert (await tasks(database))["Sommerfest"].status == "waiting"


async def test_a_remote_text_service_logs_what_it_sends_and_keeps_to_the_budget(
    archive: Any, database: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    await queue(database, "Sommerfest", "Kurze Antwort")
    sent: list[tuple[str, str]] = []

    def chat_text(service: Any, protocol: Any, *, system: str, user: str, **_: Any) -> ChatAnswer:
        assert locality(service.url) == "remote" and service.key == "geheim-123"
        sent.append((system, user))
        return ChatAnswer(Model()({"messages": [{}, {"content": user}]}), "stop", 10, 10)

    monkeypatch.setattr(summarize_step, "chat_text", chat_text)
    settings = settings_for(
        database,
        archive,
        ai_text_url=REMOTE_URL,
        ai_text_model=MODEL,
        ai_text_key="geheim-123",
        ai_allow_remote=True,
        ai_remote_token_budget=15,
    )
    with caplog.at_level(logging.INFO):
        result = await run_ai(settings, options_for(settings), engines=Fake().engines())
    assert result.exit_code == ai_run.EXIT_FAILED and result.summary.status == "stopped"
    assert result.summary.summaries == 1 and len(sent) == 1  # 20 tokens: over 15
    assert "the budget of 15 tokens for services outside this machine is used up" in (
        result.summary.message
    )
    job = await latest(database)
    (log,) = await rows(database, "SELECT * FROM ai_send_log")
    queued = await tasks(database)
    done = next(row for row in queued.values() if row.status == "done")
    assert (log.service_url, log.kind, log.target, log.job_id) == (
        REMOTE_URL,
        "summarize",
        "mail",
        job.id,
    )
    assert log.target_sha256 == done.target_sha256
    assert log.bytes == len(sent[0][0].encode()) + len(sent[0][1].encode())
    assert {row.status for row in queued.values()} == {"done", "waiting"}
    assert next(iter((await results(database)).values())).remote is True
    for stored in (str(job.options), str(job.progress), job.message, caplog.text):
        assert "geheim" not in stored


# The command line (D307, D308) ------------------------------------------------------------------


def test_the_command_line_takes_mails_and_a_text_model() -> None:
    args = main_cli.build_parser().parse_args(
        [
            "ai",
            "--origin",
            "ui",
            "run",
            "--mail=9",
            "--mail",
            "4",
            "--text-model= anderes ",
            "--document=2",
        ]
    )
    found = ai_cli.options(Settings(_env_file=None), args)  # type: ignore[call-arg]
    assert (found.mails, found.documents, found.text_model) == ([4, 9], [2], "anderes")


def test_queue_and_run_from_the_command_line(
    archive: Any, database: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAILROBBE_DATABASE_URL", database)
    for name in ("AI_TEXT_URL", "AI_TEXT_MODEL", "AI_VISION_URL", "AI_VISION_MODEL"):
        monkeypatch.delenv(f"MAILROBBE_{name}", raising=False)
    original, duplicate = asyncio.run(mail_ids(database, "Sommerfest"))
    (short,) = asyncio.run(mail_ids(database, "Kurze Antwort"))
    document = asyncio.run(report(database))
    asyncio.run(
        rows(
            database,
            """
            WITH akte AS (INSERT INTO collection (name) VALUES ('Fest') RETURNING id)
            INSERT INTO collection_mail (collection_id, mail_sha256)
            SELECT akte.id, m.raw_sha256 FROM akte, mail m WHERE m.id = :id
            """,
            {"id": original},
        )
    )
    (akte,) = asyncio.run(rows(database, "SELECT id FROM collection"))

    assert main_cli.main(["ai", "queue", "--mail", str(short)]) == 2  # without --summarize
    assert main_cli.main(["ai", "queue", "--summarize"]) == 2  # nothing named
    assert main_cli.main(["ai", "queue", "--summarize", "--scanned"]) == 2
    capsys.readouterr()
    arguments = [
        "ai",
        "queue",
        "--summarize",
        "--collection",
        str(akte.id),
        "--mail",
        str(duplicate),
    ]
    assert main_cli.main([*arguments, "--mail", str(short), "--document", str(document.id)]) == 0
    (characters,) = asyncio.run(
        rows(
            database,
            "SELECT sum(length(subject) + length(body_text)) AS mails FROM mail "
            "WHERE id = ANY(:ids)",
            {"ids": [original, short]},
        )
    )
    assert json.loads(capsys.readouterr().out) == {
        "queued": 3,
        "raised": 0,
        "unreadable": 0,
        "short": 1,
        "characters": characters.mails + len(document.extracted_text),
    }

    model = Model()
    with text_service(model) as fake:
        monkeypatch.setenv("MAILROBBE_AI_TEXT_URL", fake.url)
        monkeypatch.setenv("MAILROBBE_AI_TEXT_MODEL", "falsch")
        command = ["ai", "--origin", "ui", "run", f"--mail={duplicate}", f"--text-model={MODEL}"]
        assert main_cli.main(command) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["status"], summary["summaries"], summary["text"]) == ("done", 1, fake.url)
    assert model.asked == ["whole"]
    job = asyncio.run(latest(database))
    assert (job.origin, job.options["mails"], job.options["text_model"]) == (
        "ui",
        [duplicate],
        MODEL,
    )
    assert (asyncio.run(results(database)))["Sommerfest"].model == MODEL

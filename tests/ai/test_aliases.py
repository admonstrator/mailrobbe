"""The alias check (D321 to D323): candidate pairs, what the model reads, the verdict, and the
run with --aliases against a fake text service on a small imported archive."""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import make_url

from mailrobbe import cli as main_cli
from mailrobbe import jobrun, migrate
from mailrobbe.ai import cli as ai_cli
from mailrobbe.ai import run as ai_run
from mailrobbe.ai.aliases.candidates import Candidate, loose_key, loose_pairs, order
from mailrobbe.ai.aliases.material import PairFacts, PersonFacts, closing, material
from mailrobbe.ai.aliases.step import read_verdict
from mailrobbe.ai.model import AiOptions, AiProgress, alias_check_service
from mailrobbe.ai.prompts import MATERIAL_END, MATERIAL_START, load_prompts
from mailrobbe.ai.run import run_ai
from mailrobbe.ai.services import AnswerError
from mailrobbe.config import Settings
from mailrobbe.enums import AliasTier, AliasVerdict
from mailrobbe.importer.cli import run_import
from tests.ai.fakes import fake_service
from tests.ai.test_run import REMOTE_URL, rows
from tests.conftest import _temporary_database
from tests.importer.doubles import SEPARATOR

MODEL = "textmodell"
SIGNATURE = "-- \nAnna Berger\nSchriftführerin\nTel. 0123 456789\n"

# Pure ----------------------------------------------------------------------------------------


def test_the_loose_key_is_surname_and_first_initial() -> None:
    assert loose_key("hans-peter müller") == "mueller h"
    assert loose_key("Hans Mueller") == "mueller h"
    assert loose_key("hans") is None


def test_loose_pairs_leave_out_common_names_and_role_addresses() -> None:
    addresses = [
        (1, "hans.mueller@a.example", {"Hans Müller": 3}),
        (2, "hpm@b.example", {"Hans-Peter Mueller": 2}),
        (3, "info@c.example", {"Heinz Müller": 5}),  # a role address has no main name
        *[(10 + n, f"t{n}@d.example", {f"Tom{'m' * n} Meier": 1}) for n in range(5)],
    ]
    assert loose_pairs(addresses) == {(1, 2)}


def test_candidates_come_suggested_first_then_by_mails() -> None:
    suggestions = [
        (1, 2, AliasTier.UNCERTAIN, False),
        (3, 4, AliasTier.UNCERTAIN, True),
        (5, 6, AliasTier.CERTAIN, True),  # certain ones are not asked about
        (7, 8, AliasTier.UNCERTAIN, False),  # checked or dismissed
    ]
    loose = {(1, 2), (9, 10), (11, 12)}
    mails = {1: 5, 2: 50, 3: 1, 4: 1, 9: 3, 11: 30}
    found = order(suggestions, loose, {(7, 8), (11, 12)}, mails)
    assert found == [
        Candidate(3, 4, True, True, 1),
        Candidate(1, 2, True, False, 50),
        Candidate(9, 10, False, False, 3),
    ]


def test_a_closing_is_the_signature_or_the_last_lines_before_a_quote() -> None:
    assert closing(f"Hallo,\n\nanbei.\n\n{SIGNATURE}") == (
        "Anna Berger\nSchriftführerin\nTel. 0123 456789"
    )
    quoted = "Danke!\n\nGruß\nHans\nKreisverband Nord\n\nAm 1.1.2024 schrieb X:\n> Frage\n"
    assert closing(quoted) == "Danke!\nGruß\nHans\nKreisverband Nord"
    assert closing("---------- Forwarded message ---------\nVon: X\n\nText\n") == ""


def test_the_verdict_is_read_and_its_reason_tidied() -> None:
    answer = '<think>hm</think>```json\n{"verdict": "same", "reason": " Gleiche\\n Nummer. "}```'
    assert read_verdict(answer) == (AliasVerdict.SAME, "Gleiche Nummer.")
    long = read_verdict(json.dumps({"verdict": "unclear", "reason": "x" * 900}))[1]
    assert len(long) == 600 and long.endswith("…")
    for wrong in ("kein JSON", '{"verdict": "vielleicht", "reason": ""}', '{"verdict": "same"}'):
        with pytest.raises(AnswerError):
            read_verdict(wrong)


def test_the_material_names_both_persons_and_what_they_share() -> None:
    first = datetime(2019, 3, 1, tzinfo=UTC)
    anna = PersonFacts(
        name="Anna Berger",
        email="anna.berger@kv-nord.example",
        addresses=[("anna.berger@kv-nord.example", 2)],
        names=[("Anna Berger", 2)],
        sent=2,
        received=0,
        contacts=1,
        first=first,
        last=datetime(2023, 11, 2, tzinfo=UTC),
        frequent=["Carl Clever"],
        subjects=["Protokoll"],
        closings=["Anna Berger\nTel. 0123 456789"],
    )
    other = PersonFacts(
        name=None,
        email="anna@privat.test",
        addresses=[("anna@privat.test", 0)],
        names=[],
        sent=0,
        received=0,
        contacts=0,
        first=None,
        last=None,
        frequent=[],
        subjects=[],
        closings=[],
    )
    text = material(PairFacts(anna, other, 1, ["Dora Decker"], 0, 2, 1))
    assert text.split("\n\n")[0].split("\n") == [
        "Person A",
        "Name: Anna Berger",
        "Adressen: anna.berger@kv-nord.example (2 Mails mit Namen)",
        "Namen in Mails: Anna Berger (2)",
        "Zeitraum: 03.2019 bis 11.2023",
        "Mails: 2 gesendet, 0 empfangen, 1 Kontakte",
        "Häufige Kontakte: Carl Clever",
        "Betreffzeilen eigener Mails: „Protokoll“",
        "Schlusszeilen einer eigenen Mail (1):",
        "| Anna Berger",
        "| Tel. 0123 456789",
    ]
    assert "Name: (keiner)\nAdressen: anna@privat.test\nZeitraum: unbekannt" in text
    assert text.endswith(
        "Beide\nGemeinsame Kontakte: 1 (darunter Dora Decker)\n"
        "Mails zwischen beiden: 0 von A an B, 2 von B an A, 1 mit einem von beiden in Kopie"
    )


def test_the_prompt_names_the_answer_and_the_markers() -> None:
    prompt = load_prompts().aliases
    assert prompt.version >= 1
    for need in (MATERIAL_START, MATERIAL_END, '"verdict"', '"same"', '"different"', '"unclear"'):
        assert need in prompt.system


def test_only_a_text_service_on_this_machine_may_check() -> None:
    def settings(**values: Any) -> Settings:
        return Settings(_env_file=None, **values)  # type: ignore[call-arg]

    local = settings(ai_text_url="http://127.0.0.1:1234/v1", ai_text_model=MODEL)
    assert alias_check_service(local) is not None
    assert alias_check_service(settings(ai_text_url="http://127.0.0.1:1234/v1")) is None
    remote = settings(ai_text_url=REMOTE_URL, ai_text_model=MODEL, ai_allow_remote=True)
    assert alias_check_service(remote) is None
    assert alias_check_service(settings()) is None


def test_the_command_line_takes_aliases() -> None:
    args = main_cli.build_parser().parse_args(["ai", "run", "--aliases"])
    found = ai_cli.options(Settings(_env_file=None), args)  # type: ignore[call-arg]
    assert found.aliases is True


# The run -------------------------------------------------------------------------------------


def mail(index: int, sender: str, to: str, subject: str, body: str) -> bytes:
    return (
        f"Message-ID: <{index}@aliases.example>\nFrom: {sender}\nTo: {to}\nSubject: {subject}\n"
        f"Date: Mon, 0{1 + index % 8} Jan 2024 10:00:00 +0000\n"
        "Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 8bit\n\n"
        f"{body}\n"
    ).encode()


# Two Anna Bergers at different domains with the same signature (an uncertain suggestion), and
# Hans Müller and Hans-Peter Mueller (a loose pair no rule suggests).
MAILS = [
    mail(0, "Anna Berger <anna.berger@kv-nord.example>", "Carl Clever <carl@c.example>",
         "Protokoll", f"Hallo Carl,\n\nanbei das Protokoll.\n\n{SIGNATURE}"),
    mail(1, "Anna Berger <anna.berger@kv-nord.example>", "Carl Clever <carl@c.example>",
         "Termine", f"Hallo Carl,\n\ndie Termine.\n\n{SIGNATURE}"),
    mail(2, "Anna Berger <anna@privat.test>", "Dora Decker <dora@d.example>",
         "Privat", f"Hallo Dora,\n\nbis Sonntag.\n\n{SIGNATURE}"),
    mail(3, "Hans Müller <hans.mueller@a.example>", "Carl Clever <carl@c.example>",
         "Kasse", "Hallo Carl,\n\ndie Kasse stimmt.\n\nGruß\nHans"),
    mail(4, "Hans-Peter Mueller <hpm@b.example>", "Dora Decker <dora@d.example>",
         "Garten", "Hallo Dora,\n\nder Garten blüht.\n\nHans-Peter"),
]  # fmt: skip


@pytest.fixture(scope="module")
def archive(database_server_url: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    mbox_dir = tmp_path_factory.mktemp("aliases") / "mbox"
    mbox_dir.mkdir()
    with (mbox_dir / "aliases.mbox").open("wb") as handle:
        for raw in MAILS:
            handle.write(SEPARATOR + b"\n" + raw + b"\n")
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


def options_for(settings: Settings) -> AiOptions:
    return AiOptions.from_settings(settings).model_copy(update={"aliases": True})


def judge(body: Any) -> str:
    """Same for the Anna Bergers, whose closings agree; different for the rest."""
    user = str(body["messages"][1]["content"])
    same = user.count("Schriftführerin") == 2
    reason = "Beide nennen dieselbe Telefonnummer." if same else "Andere Vornamen, andere Kontakte."
    return json.dumps({"verdict": "same" if same else "different", "reason": reason})


async def checks(url: str) -> dict[frozenset[str], Any]:
    found = await rows(
        url,
        """
        SELECT a.canonical_email AS a, b.canonical_email AS b, c.*
        FROM alias_check c JOIN person a ON a.id = c.person_a JOIN person b ON b.id = c.person_b
        """,
    )
    return {frozenset((row.a, row.b)): row for row in found}


@pytest.mark.db
async def test_a_run_checks_the_suggestion_and_the_loose_pair(archive: Any, database: str) -> None:
    (suggested,) = await rows(database, "SELECT * FROM alias_suggestion")
    assert suggested.tier == "uncertain" and suggested.same_name == "anna berger"
    with fake_service("lmstudio", models={MODEL: None}, respond=judge) as fake:
        settings = settings_for(database, archive, ai_text_url=fake.url, ai_text_model=MODEL)
        result = await run_ai(settings, options_for(settings))
        chats = fake.chats

    assert result.exit_code == 0, result.summary.message
    summary = result.summary
    assert (summary.aliases_queued, summary.aliases, summary.aliases_same) == (2, 2, 1)
    assert (summary.aliases_failed, summary.text, summary.status) == (0, fake.url, "done")
    assert len(chats) == 2
    first = chats[0].body
    assert first["messages"][0]["content"] == load_prompts().aliases.system
    user = first["messages"][1]["content"]
    assert user.startswith(f"{MATERIAL_START}\nPerson A\n") and user.endswith(MATERIAL_END)
    assert user.count("| Tel. 0123 456789") == 2  # the suggestion comes first
    schema = first["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["verdict"]["enum"] == ["same", "different", "unclear"]

    found = await checks(database)
    anna = found[frozenset(("anna.berger@kv-nord.example", "anna@privat.test"))]
    hans = found[frozenset(("hans.mueller@a.example", "hpm@b.example"))]
    assert (anna.verdict, anna.reason) == ("same", "Beide nennen dieselbe Telefonnummer.")
    assert (hans.verdict, anna.model, anna.service_url) == ("different", MODEL, fake.url)
    assert anna.prompt_version == load_prompts().aliases.version and anna.job_id is not None
    assert (anna.tokens_in, anna.tokens_out) == (1200, 40)
    assert await rows(database, "SELECT 1 FROM person WHERE merged_into IS NOT NULL") == []

    (job,) = await rows(database, "SELECT * FROM job WHERE kind = 'ai'")
    assert job.status == "done" and job.options["aliases"] is True
    assert job.message.startswith("2 of 2 pairs of persons checked (1 one person, 0 failed)")
    progress = AiProgress.model_validate(job.progress)
    assert (progress.aliases, progress.aliases_same) == (2, 1)
    statuses = {step.key: step.status for step in progress.steps}
    assert statuses == {
        "check": "done",
        "ocr": "skipped",
        "transcribe": "skipped",
        "summarize": "skipped",
        "aliases": "done",
        "entities": "skipped",
        "signals": "skipped",
    }
    counted = next(step for step in progress.steps if step.key == "aliases")
    assert (counted.unit, counted.done, counted.total) == ("pairs", 2, 2)

    # A second run has nothing left to ask about.
    with fake_service("lmstudio", models={MODEL: None}, respond=judge) as fake:
        settings = settings_for(database, archive, ai_text_url=fake.url, ai_text_model=MODEL)
        again = await run_ai(settings, options_for(settings))
        assert fake.chats == []
    assert again.exit_code == 0 and again.summary.aliases_queued == 0


@pytest.mark.db
async def test_an_answer_that_is_no_valid_one_leaves_the_pair_for_later(
    archive: Any, database: str
) -> None:
    with fake_service("lmstudio", models={MODEL: None}, answer="Vielleicht.") as fake:
        settings = settings_for(database, archive, ai_text_url=fake.url, ai_text_model=MODEL)
        result = await run_ai(settings, options_for(settings))
        chats = fake.chats
    assert result.exit_code == 0
    assert (result.summary.aliases, result.summary.aliases_failed) == (0, 2)
    assert len(chats) == 2 * 3  # AI_TASK_ATTEMPTS per pair
    assert await checks(database) == {}


@pytest.mark.db
async def test_the_check_refuses_a_service_outside_this_machine(
    archive: Any, database: str
) -> None:
    settings = settings_for(
        database, archive, ai_text_url=REMOTE_URL, ai_text_model=MODEL, ai_allow_remote=True
    )
    result = await run_ai(settings, options_for(settings))
    assert result.exit_code == ai_run.EXIT_FAILED and result.summary.status == "failed"
    assert "to a text service on this machine only" in result.summary.message
    assert await checks(database) == {}


@pytest.mark.db
async def test_the_check_needs_a_text_service(archive: Any, database: str) -> None:
    settings = settings_for(database, archive)
    result = await run_ai(settings, options_for(settings))
    assert result.exit_code == ai_run.EXIT_FAILED
    assert "the alias check needs a text service" in result.summary.message

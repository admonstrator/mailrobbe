"""The alias check (D321 to D326): candidate groups, what the model reads, its answer, the run
with --aliases against a fake text service on a small imported archive, and merging what the
model was sure of."""

import asyncio
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mailrobbe import cli as main_cli
from mailrobbe import jobrun, migrate
from mailrobbe.ai import cli as ai_cli
from mailrobbe.ai import run as ai_run
from mailrobbe.ai.aliases.candidates import (
    GROUP_MAX,
    Group,
    fitting,
    groups,
    loose_key,
    loose_sets,
    read_groups,
)
from mailrobbe.ai.aliases.material import (
    GroupFacts,
    PairFacts,
    PersonFacts,
    closing,
    material,
)
from mailrobbe.ai.aliases.step import Seen, answer_schema, read_answer, verdicts
from mailrobbe.ai.model import AiOptions, AiProgress, alias_check_service
from mailrobbe.ai.prompts import MATERIAL_END, MATERIAL_START, load_prompts
from mailrobbe.ai.run import run_ai
from mailrobbe.ai.services import AnswerError
from mailrobbe.config import Settings
from mailrobbe.enums import AliasTier, AliasVerdict
from mailrobbe.importer.cli import run_import
from mailrobbe.persons.merge import certain_groups, merge_certain
from tests.ai.fakes import AtOnce, fake_service
from tests.ai.test_run import REMOTE_URL, rows
from tests.conftest import _temporary_database
from tests.importer.doubles import SEPARATOR

MODEL = "textmodell"
SIGNATURE = "-- \nAnna Berger\nSchriftführerin\nTel. 0123 456789\n"
U = AliasTier.UNCERTAIN

# Pure ----------------------------------------------------------------------------------------


def test_the_loose_key_is_surname_and_first_initial() -> None:
    assert loose_key("hans-peter müller") == "mueller h"
    assert loose_key("Hans Mueller") == "mueller h"
    assert loose_key("hans") is None


def test_titles_initials_and_turned_names_share_a_loose_key() -> None:
    addresses = [
        (1, "thomas.hermann@a.example", {"Dr. Thomas Hermann": 3}),
        (2, "th@b.example", {"Thomas Hermann": 2}),
        (3, "t.h@c.example", {"Dr. T. Hermann": 2}),
        (4, "x@d.example", {"Hermann, Thomas": 4}),
        (5, "info@e.example", {"Heinz Hermann": 5}),  # a role address has no main name
        *[(10 + n, f"m{n}@f.example", {f"Max{'x' * n} Meier": 1}) for n in range(GROUP_MAX + 1)],
    ]
    assert loose_sets(addresses) == [frozenset({1, 2, 3, 4})]


def test_only_fitting_first_names_join() -> None:
    assert fitting("thomas", "t") and fitting("hans", "hanspeter") and fitting("thomas", "tomas")
    assert not fitting("matthias", "miriam") and not fitting("anna", "jana")
    addresses = [
        (1, "a@a.example", {"Matthias Heinrich": 3}),
        (2, "b@b.example", {"Miriam Heinrich": 2}),
        (3, "c@c.example", {"M. Heinrich": 2}),  # an initial fits both
        (4, "d@d.example", {"Hans-Peter Mueller": 1}),
        (5, "e@e.example", {"Hans Müller": 1}),
        (6, "f@f.example", {"Heike Müller": 1}),
    ]
    assert loose_sets(addresses) == [frozenset({1, 2, 3}), frozenset({4, 5})]


def test_open_pairs_are_joined_into_groups() -> None:
    suggestions = [
        (1, 2, U, False),
        (2, 3, U, True),  # joins 1, 2 and 3
        (5, 6, AliasTier.CERTAIN, True),  # certain ones are not asked about
        (7, 8, U, False),  # checked or dismissed
    ]
    loose = [frozenset({9, 10, 11}), frozenset({5, 6})]
    mails = {1: 5, 2: 50, 3: 1, 9: 3, 10: 30}
    found = groups(suggestions, loose, {(7, 8), (9, 10)}, mails)
    assert found == [Group((1, 2, 3), True, True, 50), Group((9, 10, 11), False, False, 30)]


def test_a_cluster_too_large_is_asked_by_its_keys_and_pairs() -> None:
    chain = [(n, n + 1, U, False) for n in range(1, GROUP_MAX + 2)]  # 1 .. GROUP_MAX + 2
    found = groups(chain, [frozenset({1, 2, 3})], set(), {})
    members = [group.members for group in found]
    assert (1, 2, 3) in members and len(members) == 1 + GROUP_MAX - 1
    assert all(len(m) == 2 for m in members if m != (1, 2, 3))


def test_a_closing_is_the_signature_or_the_last_lines_before_a_quote() -> None:
    assert closing(f"Hallo,\n\nanbei.\n\n{SIGNATURE}") == (
        "Anna Berger\nSchriftführerin\nTel. 0123 456789"
    )
    quoted = "Danke!\n\nGruß\nHans\nKreisverband Nord\n\nAm 1.1.2024 schrieb X:\n> Frage\n"
    assert closing(quoted) == "Danke!\nGruß\nHans\nKreisverband Nord"
    assert closing("---------- Forwarded message ---------\nVon: X\n\nText\n") == ""


def test_an_answer_names_each_letter_once() -> None:
    answer = (
        '<think>hm</think>```json\n{"persons": [{"members": ["C", "A"], "sure": true, '
        '"reason": " Gleiche\\n Nummer. "}, {"members": ["B"], "sure": false, "reason": "?"}]}```'
    )
    assert read_answer(answer, 4) == [
        Seen((0, 2), True, "Gleiche Nummer."),
        Seen((1,), False, "?"),
        Seen((3,), False, ""),  # a letter missing is a person of its own, not sure
    ]
    for wrong in (
        "kein JSON",
        '{"persons": "A"}',
        '{"persons": [{"members": ["A", "A"], "sure": true, "reason": ""}]}',
        '{"persons": [{"members": ["E"], "sure": true, "reason": ""}]}',
        '{"persons": [{"members": ["A"], "reason": ""}]}',
    ):
        with pytest.raises(AnswerError):
            read_answer(wrong, 4)
    schema = answer_schema(3)["properties"]["persons"]["items"]["properties"]
    assert schema["members"]["items"]["enum"] == ["A", "B", "C"]


def test_the_pairs_of_an_answer() -> None:
    seen = [Seen((0, 2), True, "Eins."), Seen((1,), True, "Zwei."), Seen((3,), False, "")]
    found = {(v.a, v.b): (v.verdict, v.certain, v.reason) for v in verdicts(seen)}
    assert found == {
        (0, 2): (AliasVerdict.SAME, True, "Eins."),
        (0, 1): (AliasVerdict.DIFFERENT, False, "A: Eins. B: Zwei."),
        (1, 2): (AliasVerdict.DIFFERENT, False, "B: Zwei. C: Eins."),
        (0, 3): (AliasVerdict.UNCLEAR, False, "A: Eins."),
        (1, 3): (AliasVerdict.UNCLEAR, False, "B: Zwei."),
        (2, 3): (AliasVerdict.UNCLEAR, False, "C: Eins."),
    }
    unsure = verdicts([Seen((0, 1), False, "Vielleicht.")])
    assert [(v.verdict, v.certain) for v in unsure] == [(AliasVerdict.SAME, False)]


def person_facts(name: str | None, email: str, closings: list[str]) -> PersonFacts:
    return PersonFacts(
        name=name,
        email=email,
        addresses=[(email, 2 if name else 0)],
        names=[(name, 2)] if name else [],
        sent=2,
        received=0,
        contacts=1,
        first=datetime(2019, 3, 1, tzinfo=UTC) if name else None,
        last=datetime(2023, 11, 2, tzinfo=UTC) if name else None,
        frequent=["Carl Clever", "Dora Decker"] if name else [],
        subjects=["Protokoll", "Termine"] if name else [],
        closings=closings,
    )


def test_the_material_names_the_persons_and_what_they_share() -> None:
    anna = person_facts("Anna Berger", "anna.berger@kv-nord.example", ["Anna Berger\nTel. 0123"])
    other = person_facts(None, "anna@privat.test", [])
    third = person_facts("Anna Berger", "ab@c.example", [])
    facts = GroupFacts([1, 2, 3], [anna, other, third], [PairFacts(0, 2, 1, ["Dora"], 0, 2, 1)])
    found = material(facts, 10_000)
    assert found.split("\n\n")[0].split("\n") == [
        "Person A",
        "Name: Anna Berger",
        "Adressen: anna.berger@kv-nord.example (2 Mails mit Namen)",
        "Namen in Mails: Anna Berger (2)",
        "Zeitraum: 03.2019 bis 11.2023",
        "Mails: 2 gesendet, 0 empfangen, 1 Kontakte",
        "Häufige Kontakte: Carl Clever, Dora Decker",
        "Betreffzeilen eigener Mails: „Protokoll“; „Termine“",
        "Schlusszeilen einer eigenen Mail (1):",
        "| Anna Berger",
        "| Tel. 0123",
    ]
    assert "Person B\nName: (keiner)\nAdressen: anna@privat.test\nZeitraum: unbekannt" in found
    assert found.endswith(
        "Zwischen den Personen\nA und C: 1 gemeinsame Kontakte (darunter Dora); "
        "Mails: 0 von A an C, 2 von C an A, 1 mit einem von beiden in Kopie"
    )
    short = material(facts, len(found) - 1)  # less detail when the limit is tighter
    assert "Schlusszeilen" not in short and len(short) < len(found)
    alone = material(GroupFacts([1, 2], [anna, third], []), 10_000)
    assert alone.endswith(
        "Zwischen den Personen\nkeine gemeinsamen Kontakte, keine Mails untereinander"
    )


def test_the_prompt_names_the_answer_and_the_markers() -> None:
    prompt = load_prompts().aliases
    assert prompt.version >= 2
    for need in (MATERIAL_START, MATERIAL_END, '"persons"', '"members"', '"sure"', "Zeiträume"):
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
    line = ["ai", "run", "--aliases", "--person", "9", "--person", "4"]
    found = ai_cli.options(Settings(_env_file=None), main_cli.build_parser().parse_args(line))  # type: ignore[call-arg]
    assert (found.aliases, found.persons) == (True, [4, 9])


# The run -------------------------------------------------------------------------------------


def mail(index: int, sender: str, to: str, subject: str, body: str) -> bytes:
    return (
        f"Message-ID: <{index}@aliases.example>\nFrom: {sender}\nTo: {to}\nSubject: {subject}\n"
        f"Date: Mon, 0{1 + index % 8} Jan 2024 10:00:00 +0000\n"
        "Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 8bit\n\n"
        f"{body}\n"
    ).encode()


# Two Anna Bergers at different domains with the same signature (an uncertain suggestion), and
# Hans Müller, Dr. Hans Müller (an uncertain suggestion by name) and Hans-Peter Mueller (a loose
# key): two groups.
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
    mail(5, "Dr. Hans Müller <h.mueller@praxis.example>", "Erik Ernst <erik@e.example>",
         "Befund", "Hallo Erik,\n\nder Befund ist da.\n\nGruß\nHans"),
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


_PERSON = re.compile(r"^Person ([A-H])\nName: (.*)$", re.M)


def judge(body: Any) -> str:
    """The Anna Bergers one person, sure; Hans Müller with Dr. Hans Müller, sure; Hans-Peter
    Mueller alone, not sure."""
    found = _PERSON.findall(body["messages"][1]["content"])
    named = {name: letter for letter, name in found}
    if "Anna Berger" in named:
        letters = [letter for letter, _ in found]
        return json.dumps(
            {"persons": [{"members": letters, "sure": True, "reason": "Dieselbe Nummer."}]}
        )
    return json.dumps(
        {
            "persons": [
                {
                    "members": [named["Hans Müller"], named["Dr. Hans Müller"]],
                    "sure": True,
                    "reason": "Derselbe Gruß, nacheinander.",
                },
                {"members": [named["Hans-Peter Mueller"]], "sure": False, "reason": "Offen."},
            ]
        }
    )


async def checks(url: str) -> dict[frozenset[str], Any]:
    found = await rows(
        url,
        """
        SELECT a.canonical_email AS a, b.canonical_email AS b, c.*
        FROM alias_check c JOIN person a ON a.id = c.person_a JOIN person b ON b.id = c.person_b
        """,
    )
    return {frozenset((row.a, row.b)): row for row in found}


ANNA = frozenset(("anna.berger@kv-nord.example", "anna@privat.test"))
HANS = frozenset(("hans.mueller@a.example", "h.mueller@praxis.example"))


@pytest.mark.db
async def test_a_run_checks_the_groups_and_the_sure_ones_merge(archive: Any, database: str) -> None:
    tiers = {
        row.same_name: row.tier for row in await rows(database, "SELECT * FROM alias_suggestion")
    }
    assert tiers == {"anna berger": "uncertain", "hans müller": "uncertain"}
    with fake_service("lmstudio", models={MODEL: None}, respond=judge) as fake:
        settings = settings_for(database, archive, ai_text_url=fake.url, ai_text_model=MODEL)
        result = await run_ai(settings, options_for(settings))
        chats = fake.chats

    assert result.exit_code == 0, result.summary.message
    summary = result.summary
    assert (summary.aliases_queued, summary.aliases, summary.aliases_failed) == (2, 2, 0)
    assert (summary.aliases_same, summary.aliases_sure, summary.status) == (2, 2, "done")
    assert len(chats) == 2
    first = chats[0].body
    assert first["messages"][0]["content"] == load_prompts().aliases.system
    user = first["messages"][1]["content"]
    assert user.startswith(f"{MATERIAL_START}\nPerson A\n") and user.endswith(MATERIAL_END)
    assert user.count("| Tel. 0123 456789") == 2  # the group of a suggestion by name and part
    schema = first["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["persons"]["items"]["properties"]["members"]["items"]["enum"] == [
        "A",
        "B",
    ]

    found = await checks(database)
    assert len(found) == 1 + 3
    anna, hans = found[ANNA], found[HANS]
    assert (anna.verdict, anna.certain, anna.reason) == ("same", True, "Dieselbe Nummer.")
    assert (hans.verdict, hans.certain, anna.model, anna.service_url) == (
        "same",
        True,
        MODEL,
        fake.url,
    )
    other = found[frozenset(("hpm@b.example", "hans.mueller@a.example"))]
    assert (other.verdict, other.certain) == ("unclear", False)
    assert anna.prompt_version == load_prompts().aliases.version and anna.job_id is not None
    assert await rows(database, "SELECT 1 FROM person WHERE merged_into IS NOT NULL") == []

    (job,) = await rows(database, "SELECT * FROM job WHERE kind = 'ai'")
    assert job.status == "done" and job.options["aliases"] is True
    assert job.message.startswith(
        "2 of 2 groups of persons checked (2 pairs one person, 2 of them sure, 0 failed)"
    )
    progress = AiProgress.model_validate(job.progress)
    assert (progress.aliases, progress.aliases_same, progress.aliases_sure) == (2, 2, 2)
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
    assert (counted.unit, counted.done, counted.total) == ("groups", 2, 2)

    # A second run has nothing left to ask about; a verdict of an older prompt is asked again.
    with fake_service("lmstudio", models={MODEL: None}, respond=judge) as fake:
        settings = settings_for(database, archive, ai_text_url=fake.url, ai_text_model=MODEL)
        again = await run_ai(settings, options_for(settings))
        assert fake.chats == []
    assert again.exit_code == 0 and again.summary.aliases_queued == 0
    engine = create_async_engine(database, poolclass=pool.NullPool)
    try:
        async with async_sessionmaker(engine)() as session:
            await session.execute(
                text("UPDATE alias_check SET prompt_version = 1 WHERE verdict <> 'same'")
            )
            version = load_prompts().aliases.version
            [group] = await read_groups(session, version)
            assert len(group.members) == 3

            # The sure verdicts merge as one batch: two groups of two.
            plan = await certain_groups(session, ai=True)
            assert (len(plan.groups), plan.left_out) == (2, [])
            done = await merge_certain(session, "Team", ai=True)
            assert (done.merges, done.persons, done.batch_id is not None) == (2, 2, True)
            await session.commit()
    finally:
        await engine.dispose()
    merged = await rows(
        database, "SELECT canonical_email FROM person WHERE merged_into IS NOT NULL"
    )
    assert len(merged) == 2


@pytest.mark.db
async def test_the_groups_are_asked_about_at_once_up_to_the_concurrency(
    archive: Any, database: str
) -> None:
    respond = AtOnce(judge)
    with fake_service("lmstudio", models={MODEL: None}, respond=respond) as fake:
        settings = settings_for(database, archive, ai_text_url=fake.url, ai_text_model=MODEL)
        options = options_for(settings).model_copy(update={"concurrency": 2})
        result = await run_ai(settings, options)
    assert result.exit_code == 0, result.summary.message
    assert (result.summary.aliases, result.summary.aliases_sure, respond.most) == (2, 2, 2)


async def test_one_pair_is_asked_about_again_on_its_own(archive: Any, database: str) -> None:
    with fake_service("lmstudio", models={MODEL: None}, respond=judge) as fake:
        settings = settings_for(database, archive, ai_text_url=fake.url, ai_text_model=MODEL)
        assert (await run_ai(settings, options_for(settings))).exit_code == 0
        found = await rows(
            database,
            "SELECT id FROM person WHERE canonical_email = ANY(:emails) ORDER BY id",
            {"emails": sorted(ANNA)},
        )
        persons = [row.id for row in found]
        options = options_for(settings).model_copy(update={"persons": persons})
        result = await run_ai(settings, options)
        chats = fake.chats
    assert result.exit_code == 0, result.summary.message
    assert (result.summary.aliases_queued, result.summary.aliases) == (1, 1)
    assert len(chats) == 3  # two groups the first time, the pair again
    assert (await checks(database))[ANNA].verdict == "same"


async def test_a_verdict_against_keeps_a_sure_chain_apart(archive: Any, database: str) -> None:
    ids = {
        row.canonical_email: row.id
        for row in await rows(database, "SELECT id, canonical_email FROM person")
    }
    hans, praxis, hpm = (
        ids["hans.mueller@a.example"],
        ids["h.mueller@praxis.example"],
        ids["hpm@b.example"],
    )
    values = [
        (hans, praxis, "same", True),
        (praxis, hpm, "same", True),
        (hans, hpm, "different", False),
    ]
    engine = create_async_engine(database, poolclass=pool.NullPool)
    try:
        async with async_sessionmaker(engine)() as session:
            for a, b, verdict, certain in values:
                await session.execute(
                    text(
                        "INSERT INTO alias_check (person_a, person_b, verdict, certain, reason, "
                        "model, service_url, prompt_version, seconds, tokens_in, tokens_out) "
                        "VALUES (:a, :b, CAST(:v AS alias_verdict), :c, '', 'm', 'u', 2, 1, 1, 1)"
                    ),
                    {"a": min(a, b), "b": max(a, b), "v": verdict, "c": certain},
                )
            plan = await certain_groups(session, ai=True)
            assert plan.groups == [] and [sorted(g) for g in plan.left_out] == [
                sorted([hans, praxis, hpm])
            ]
    finally:
        await engine.dispose()


@pytest.mark.db
async def test_an_answer_that_is_no_valid_one_leaves_the_group_for_later(
    archive: Any, database: str
) -> None:
    with fake_service("lmstudio", models={MODEL: None}, answer="Vielleicht.") as fake:
        settings = settings_for(database, archive, ai_text_url=fake.url, ai_text_model=MODEL)
        result = await run_ai(settings, options_for(settings))
        chats = fake.chats
    assert result.exit_code == 0
    assert (result.summary.aliases, result.summary.aliases_failed) == (0, 2)
    assert len(chats) == 2 * 3  # AI_TASK_ATTEMPTS per group
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

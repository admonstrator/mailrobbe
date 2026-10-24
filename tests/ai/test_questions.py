"""The step ask of the AI run (D347): a question about a person read with the person's facts and
the summaries of its conversations, answered by the text model and kept."""

import json
from typing import Any

import pytest

from mailrobbe.ai.model import AiOptions
from mailrobbe.ai.prompts import MATERIAL_END, MATERIAL_START, load_prompts
from mailrobbe.ai.run import run_ai
from tests.ai.fakes import fake_service
from tests.ai.test_aliases import MODEL, archive, database, quick, settings_for
from tests.ai.test_run import rows
from tests.api.test_ai import summarized

pytestmark = pytest.mark.db

__all__ = ["archive", "database", "quick"]


async def carl(url: str) -> Any:
    [found] = await rows(url, "SELECT id FROM person WHERE canonical_email = 'carl@c.example'")
    return found.id


async def test_a_question_is_answered_from_the_summaries(database: str, archive: Any) -> None:
    person = await carl(database)
    [mail] = await rows(database, "SELECT raw_sha256 FROM mail WHERE subject = 'Kasse' LIMIT 1")
    await summarized(database, "mail", mail.raw_sha256, "Hans meldet, die Kasse stimme.")
    [question] = await rows(
        database,
        """INSERT INTO person_question (person_id, template, question)
           VALUES (:person, 'contacts', 'Mit wem schreibt Person A?') RETURNING id""",
        {"person": person},
    )
    answer = json.dumps({"answer": "Vor allem mit Anna Berger und Hans Müller."})
    with fake_service("lmstudio", models={MODEL: None}, answer=answer) as fake:
        settings = settings_for(database, archive, ai_text_url=fake.url, ai_text_model=MODEL)
        options = AiOptions.from_settings(settings).model_copy(update={"questions": [question.id]})
        result = await run_ai(settings, options)
        chats = fake.chats

    assert result.exit_code == 0, result.summary.message
    assert (result.summary.questions, result.summary.questions_failed) == (1, 0)
    [chat] = chats
    assert chat.body["messages"][0]["content"] == load_prompts().questions.system
    user = chat.body["messages"][1]["content"]
    assert user.startswith(f"{MATERIAL_START}\nPerson A: Carl Clever <carl@c.example>")
    assert "Zusammenfassung: Hans meldet, die Kasse stimme." in user
    assert user.endswith(f"{MATERIAL_END}\n\nFrage: Mit wem schreibt Person A?")
    [done] = await rows(database, "SELECT * FROM person_question")
    assert (done.status, done.answer, done.contents, done.model) == (
        "done",
        "Vor allem mit Anna Berger und Hans Müller.",
        1,
        MODEL,
    )


async def test_a_question_waits_for_its_prework(database: str, archive: Any) -> None:
    person = await carl(database)
    [mail] = await rows(database, "SELECT id, raw_sha256 FROM mail ORDER BY id LIMIT 1")
    await rows(
        database,
        """INSERT INTO ai_task (kind, target, target_sha256, priority)
           VALUES ('summarize', 'mail', :sha, 100)""",
        {"sha": mail.raw_sha256},
    )
    await rows(
        database,
        """INSERT INTO person_question (person_id, template, question, prework)
           VALUES (:person, 'topics', 'Welche Themen?', CAST(:prework AS jsonb))""",
        {"person": person, "prework": json.dumps({"mails": [mail.id]})},
    )
    # no text service: the summary waits, and the question with it
    settings = settings_for(database, archive)
    options = AiOptions.from_settings(settings).model_copy(update={"questions": [1]})
    result = await run_ai(settings, options)
    assert result.exit_code == 0, result.summary.message
    [waiting] = await rows(database, "SELECT status FROM person_question")
    assert waiting.status == "waiting"

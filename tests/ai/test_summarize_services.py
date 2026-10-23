"""A text request by the answer schema (D300, D304) against fake services of both protocols, and
the real test of a text service."""

import json
from dataclasses import replace

import pytest

from mailrobbe.ai import services
from mailrobbe.ai.model import SUMMARY_ANSWER_TOKENS, Reasoning, configured_services
from mailrobbe.ai.prompts import MATERIAL_END, MATERIAL_START
from mailrobbe.ai.services import (
    TEST_TEXT,
    TEST_WORD,
    ChatAnswer,
    ModelMissing,
    chat_text,
    check_service,
    cut_at_length,
)
from mailrobbe.ai.summarize.answer import answer_schema
from mailrobbe.config import Settings
from tests.ai.fakes import FakeService, fake_service

SCHEMA = answer_schema(["spenden"])
ANSWER = json.dumps({"summary": "Kurz gesagt.", "tags": ["Test"], "themes": []})


def ask(fake: FakeService, model: str | None = None) -> ChatAnswer:
    return chat_text(
        fake.service(model, capability="text"),
        fake.protocol,
        system="System",
        user="Nutzer",
        schema=SCHEMA,
        max_tokens=SUMMARY_ANSWER_TOKENS,
        timeout=5,
        context_tokens=4096,
    )


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


def test_an_openai_service_is_asked_for_an_answer_by_the_schema() -> None:
    with fake_service("lmstudio", models={"textmodell": None}, answer=ANSWER) as fake:
        found = ask(fake)
        (chat,) = fake.chats
    assert found == ChatAnswer(ANSWER, "stop", 1200, 40)
    assert chat.body == {
        "model": "textmodell",
        "messages": [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Nutzer"},
        ],
        "temperature": 0,
        "max_tokens": SUMMARY_ANSWER_TOKENS,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "summary", "strict": True, "schema": SCHEMA},
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_a_service_without_structured_answers_is_asked_again_without_the_schema() -> None:
    with fake_service(
        "openai", models={"textmodell": None}, answer=ANSWER, refuse_schema=True
    ) as fake:
        found = ask(fake)
        first, second = fake.chats
    assert found.text == ANSWER
    assert "response_format" in first.body and "response_format" not in second.body
    assert first.body["messages"] == second.body["messages"]


def test_ollama_gets_the_schema_as_format_and_the_context_as_num_ctx() -> None:
    with fake_service("ollama", models={"textmodell": None}, answer=ANSWER) as fake:
        found = ask(fake)
        (chat,) = fake.chats
    assert found.text == ANSWER
    assert chat.body["format"] == SCHEMA
    assert chat.body["options"] == {
        "temperature": 0,
        "num_ctx": 4096,
        "num_predict": SUMMARY_ANSWER_TOKENS,
    }
    assert (chat.body["think"], chat.body["stream"]) == (False, False)
    assert [message["role"] for message in chat.body["messages"]] == ["system", "user"]


def thinking(fake: FakeService, reasoning: Reasoning) -> ChatAnswer:
    service = replace(fake.service(capability="text"), reasoning=reasoning)
    return chat_text(
        service,
        fake.protocol,
        system="System",
        user="Nutzer",
        schema=SCHEMA,
        max_tokens=SUMMARY_ANSWER_TOKENS,
        timeout=5,
        context_tokens=4096,
    )


def test_the_text_model_thinks_as_deep_as_the_settings_say() -> None:
    with fake_service("lmstudio", models={"textmodell": None}, answer=ANSWER) as fake:
        thinking(fake, "medium")
        (chat,) = fake.chats
    assert chat.body["chat_template_kwargs"] == {"enable_thinking": True}
    assert chat.body["reasoning_effort"] == "medium"
    with fake_service("ollama", models={"textmodell": None}, answer=ANSWER) as fake:
        thinking(fake, "high")
        (chat,) = fake.chats
    assert chat.body["think"] == "high"
    assert (
        configured_services(settings(ai_text_url="http://127.0.0.1:1234/v1"))["text"].reasoning
        == "off"
    )


def test_ollama_takes_true_when_a_model_takes_no_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[object] = []

    def request(service: object, url: str, timeout: float, payload: dict[str, object]) -> object:
        sent.append(payload.get("think", "none"))
        if isinstance(payload.get("think"), str):
            raise services._HttpStatus(400, "think value low is not supported for this model")
        return {"message": {"content": ANSWER}, "done_reason": "stop"}

    monkeypatch.setattr(services, "_request", request)
    with fake_service("ollama", models={"textmodell": None}) as fake:
        assert thinking(fake, "low").text == ANSWER
    assert sent == ["low", True]


@pytest.mark.parametrize("flavour", ["openai", "ollama"])
def test_a_text_model_that_is_not_offered_raises_model_missing(flavour) -> None:
    with (
        fake_service(flavour, models={"textmodell": None}) as fake,
        pytest.raises(ModelMissing, match="'anderes'"),
    ):
        ask(fake, "anderes")


@pytest.mark.parametrize("flavour", ["lmstudio", "ollama"])
def test_an_answer_cut_at_its_length_says_so(flavour) -> None:
    with fake_service(
        flavour, models={"textmodell": None}, answer='{"summ', finish="length"
    ) as fake:
        found = ask(fake)
    assert found.finish == "length" and not found.thought
    assert cut_at_length(found, 900) == "cut at the length limit of 900 tokens"


def test_an_answer_cut_while_thinking_says_so() -> None:
    answer = "<think>Zuerst lese ich das Material"
    with fake_service(
        "ollama", models={"textmodell": None}, answer=answer, finish="length"
    ) as fake:
        found = ask(fake)
    assert found.thought
    assert cut_at_length(found, 900).endswith(
        "while the model was thinking; switch its thinking off"
    )


# The real test of a text service (D300)


def reply(summary: str, tags: list[str] | None = None) -> str:
    return json.dumps({"summary": summary, "tags": tags or [], "themes": []})


@pytest.mark.parametrize("flavour", ["lmstudio", "ollama"])
def test_the_text_test_passes_when_the_summary_names_the_word(flavour) -> None:
    answer = reply(f"Das Archivprojekt {TEST_WORD.lower()} beginnt im November in Bremen.")
    with fake_service(flavour, models={"textmodell": None}, answer=answer) as fake:
        check = check_service(fake.service(capability="text"), settings(ai_context_tokens=4096))
        (chat,) = fake.chats
    assert (check.test, check.model_found, check.error) == ("passed", True, None)
    assert check.test_detail is not None and check.test_detail.startswith("summarised: Das")
    assert check.seconds is not None
    system, user = (message["content"] for message in chat.body["messages"])
    assert "Themen (Schlüssel: Beschreibung)" in system and "{themes}" not in system
    assert user.startswith(MATERIAL_START) and user.endswith(MATERIAL_END)
    assert "Art: E-Mail\nBetreff: Neues Archivprojekt\n\n" + TEST_TEXT in user
    if flavour == "ollama":
        assert chat.body["options"]["num_ctx"] == 4096
        # the answer may use what the context leaves beside the short test text, not a fixed 1,200
        assert 2000 < chat.body["options"]["num_predict"] < 4096
        assert chat.body["format"]["required"] == ["summary", "tags", "themes"]
    else:
        assert chat.body["response_format"]["json_schema"]["strict"] is True


def test_the_word_among_the_tags_passes_too() -> None:
    answer = reply("Ein neues Projekt beginnt.", ["Archivprojekt", TEST_WORD])
    with fake_service("lmstudio", models={"textmodell": None}, answer=answer) as fake:
        check = check_service(fake.service(capability="text"), settings())
    assert check.test == "passed"


@pytest.mark.parametrize(
    ("answer", "finish", "detail"),
    [
        (reply("Ein Projekt beginnt in Bremen."), "stop", f"{TEST_WORD} not named: Ein Projekt"),
        ("Das Projekt heißt ROBBE-7342.", "stop", "no JSON object in the answer: Das Projekt"),
        (reply(f"Es heißt {TEST_WORD}"), "length", "cut at the length limit of "),
    ],
)
def test_the_text_test_fails_without_the_word_or_a_valid_answer(answer, finish, detail) -> None:
    with fake_service("ollama", models={"textmodell": None}, answer=answer, finish=finish) as fake:
        check = check_service(fake.service(capability="text"), settings())
    assert check.test == "failed"
    assert check.test_detail is not None and check.test_detail.startswith(detail)


def test_a_missing_text_model_is_named_and_not_tested() -> None:
    with fake_service("ollama", models={"textmodell": None}) as fake:
        check = check_service(fake.service("anderes", capability="text"), settings())
        assert check.model_found is False and check.test is None and not fake.chats

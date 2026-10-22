import io
import socket
from dataclasses import replace

import pytest
from PIL import Image

from mailrobbe.ai.model import NO_TEXT_MARK, OcrPage, Service, ServiceModel
from mailrobbe.ai.ocr import vision
from mailrobbe.ai.prompts import load_prompts
from mailrobbe.ai.services import (
    TEST_WORD,
    AnswerError,
    ModelMissing,
    Unreachable,
    check_service,
    detect_protocol,
    list_models,
    probe_picture,
)
from mailrobbe.config import Settings
from tests.ai.fakes import FakeService, fake_service

PNG = probe_picture()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def read(fake: FakeService, service: Service | None = None, timeout: float = 5.0) -> OcrPage:
    return vision.read_page(
        service or fake.service(),
        PNG,
        3,
        prompts=load_prompts(),
        protocol=fake.protocol,
        timeout=timeout,
    )


@pytest.mark.parametrize(
    ("flavour", "expected"), [("openai", "openai"), ("lmstudio", "openai"), ("ollama", "ollama")]
)
def test_the_protocol_is_detected_by_asking_for_ollamas_tags(flavour, expected) -> None:
    with fake_service(flavour) as fake:
        assert detect_protocol(fake.service(), 5) == expected
        assert detect_protocol(replace(fake.service(), protocol="ollama"), 5) == "ollama"


def test_an_unreachable_service_raises_unreachable() -> None:
    service = Service("vision", f"http://127.0.0.1:{free_port()}/v1", "m", "auto")
    with pytest.raises(Unreachable):
        detect_protocol(service, 2)
    with pytest.raises(Unreachable):
        list_models(replace(service, protocol="openai"), 2)


def test_lm_studio_says_which_models_read_pictures() -> None:
    models = {"qwen2.5-vl-7b": True, "llama-3-8b": False, "nomic-embed": None}
    with fake_service("lmstudio", models=models) as fake:
        assert list_models(fake.service(), 5) == [
            ServiceModel(name="qwen2.5-vl-7b", vision=True),
            ServiceModel(name="llama-3-8b", vision=False),
            ServiceModel(name="nomic-embed", vision=None),
        ]


def test_a_plain_openai_service_does_not_tell() -> None:
    with fake_service("openai", models={"gpt-vision": True}) as fake:
        assert list_models(fake.service(), 5) == [ServiceModel(name="gpt-vision", vision=None)]


def test_a_base_url_without_its_version_is_accepted() -> None:
    with fake_service("lmstudio") as fake:
        service = replace(fake.service(), url=fake.url.removesuffix("/v1"))
        assert [model.name for model in list_models(service, 5)] == ["vision-model"]
        assert read(fake, service).text == "Erkannter Text"
        assert fake.chats[-1].path == "/v1/chat/completions"


def test_ollama_lists_its_models_with_their_capabilities() -> None:
    with fake_service("ollama", models={"llava:latest": True, "llama3:8b": False}) as fake:
        assert list_models(fake.service(), 5) == [
            ServiceModel(name="llava:latest", vision=True),
            ServiceModel(name="llama3:8b", vision=False),
        ]


def test_openai_chat_sends_only_the_png_and_the_prompt() -> None:
    with fake_service("lmstudio", tokens=(900, 12)) as fake:
        page = read(fake)
        assert page.model_dump(exclude={"seconds"}) == {
            "number": 3,
            "engine": "vision",
            "text": "Erkannter Text",
            "confidence": None,
            "uncertain": False,
            "looped": False,
            "error": None,
            "tokens_in": 900,
            "tokens_out": 12,
        }
        (chat,) = fake.chats
        assert chat.body["temperature"] == 0
        assert chat.body["max_tokens"] == vision.MAX_TOKENS
        assert chat.body["chat_template_kwargs"] == {"enable_thinking": False}
        content = chat.body["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": load_prompts().ocr}
        assert fake.images() == [PNG]
        assert "Authorization" not in chat.headers


def test_ollama_chat_switches_thinking_off_and_keeps_the_model_loaded() -> None:
    with fake_service("ollama") as fake:
        assert read(fake).text == "Erkannter Text"
        (chat,) = fake.chats
        assert chat.body["think"] is False
        assert chat.body["stream"] is False
        assert chat.body["options"]["temperature"] == 0
        assert chat.body["options"]["num_ctx"] >= 8192
        assert chat.body["keep_alive"]
        assert fake.images() == [PNG]
        assert Image.open(io.BytesIO(fake.images()[0])).format == "PNG"


def test_the_key_goes_out_as_bearer_token_and_never_into_an_error() -> None:
    with fake_service("openai", status=401, body="wrong key sk-secret-123") as fake:
        service = fake.service(key="sk-secret-123")
        with pytest.raises(AnswerError) as raised:
            read(fake, service)
        assert raised.value.args[0] == "HTTP 401: wrong key ***"
        assert "sk-secret" not in repr(service)
        assert fake.chats[0].headers["Authorization"] == "Bearer sk-secret-123"


@pytest.mark.parametrize("flavour", ["openai", "ollama"])
def test_an_answer_cut_at_its_length_limit_fails_the_page(flavour) -> None:
    limit = f"length limit of {vision.MAX_TOKENS} tokens"
    with (
        fake_service(flavour, finish="length", answer="Ein halber") as fake,
        pytest.raises(AnswerError, match=limit),
    ):
        read(fake)


@pytest.mark.parametrize("flavour", ["lmstudio", "ollama"])
def test_a_model_that_is_not_offered_raises_model_missing(flavour) -> None:
    with fake_service(flavour) as fake, pytest.raises(ModelMissing, match="'gone'"):
        read(fake, fake.service("gone"))


def test_a_timeout_before_the_answer_is_unreachable() -> None:
    with fake_service("openai", delay=2) as fake, pytest.raises(Unreachable, match=r"0\.5 s"):
        read(fake, timeout=0.5)


def test_an_invalid_answer_is_an_answer_error() -> None:
    with (
        fake_service("openai", status=200, body="<html>proxy</html>") as fake,
        pytest.raises(AnswerError, match="not a JSON answer"),
    ):
        read(fake)
    with (
        fake_service("ollama", status=200, body='{"done": true}') as fake,
        pytest.raises(AnswerError, match="not a chat answer"),
    ):
        read(fake)


@pytest.mark.parametrize(
    ("answer", "text", "looped"),
    [
        ("<think>Ein Formular.</think>\nRechnung Nr. 4", "Rechnung Nr. 4", False),
        ("```markdown\n| A | B |\n```", "| A | B |", False),
        (NO_TEXT_MARK, "", False),
        ("  [Kein Text].  ", "", False),
        ("", "", False),
        ("Kopf\n" + "Zeile\n" * 7 + "Ende", "Kopf\nZeile", True),
    ],
)
def test_the_guards_apply_to_the_answer(answer, text, looped) -> None:
    with fake_service("ollama", answer=answer) as fake:
        page = read(fake)
        assert (page.text, page.looped, page.uncertain) == (text, looped, looped)


def test_a_local_service_is_asked_without_the_environments_proxy(monkeypatch) -> None:
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{free_port()}")
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{free_port()}")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    with fake_service("lmstudio") as fake:
        assert detect_protocol(fake.service(), 5) == "openai"


def test_a_remote_service_is_asked_through_the_environments_proxy(monkeypatch) -> None:
    with fake_service("openai") as proxy:
        monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy.port}")
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setenv("NO_PROXY", "")
        service = Service("vision", "http://203.0.113.9:8080/v1", "m", "openai")
        with pytest.raises(AnswerError):
            list_models(service, 5)
        assert [r.path for r in proxy.requests] == ["http://203.0.113.9:8080/v1/models"]


# check_service


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_a_remote_service_is_refused_without_asking_it() -> None:
    service = Service("vision", "https://api.example.com/v1", "m", "openai", key="sk-1")
    check = check_service(service, settings())
    assert check.refused is not None and "MAILROBBE_AI_ALLOW_REMOTE" in check.refused
    assert (check.locality, check.reachable, check.test) == ("remote", None, None)


def test_a_forbidden_url_is_refused() -> None:
    check = check_service(Service("vision", "http://169.254.169.254", "m", "auto"), settings())
    assert check.locality is None and check.refused


def test_an_unreachable_service_is_named() -> None:
    service = Service("vision", f"http://127.0.0.1:{free_port()}/v1", "m", "auto")
    check = check_service(service, settings())
    assert check.reachable is False
    assert check.error is not None and "not reachable" in check.error


def test_a_model_that_is_not_offered_is_named_and_not_tested() -> None:
    with fake_service("ollama", models={"llava:latest": True}) as fake:
        check = check_service(fake.service("minicpm-v"), settings())
        assert (check.reachable, check.protocol, check.model_found) == (True, "ollama", False)
        assert check.test is None and check.error and "'minicpm-v'" in check.error
        assert not fake.chats
        # Ollama's tag :latest may be left out.
        assert check_service(fake.service("llava"), settings(), test=False).model_found is True


def test_the_real_test_passes_when_the_word_comes_back() -> None:
    with fake_service("lmstudio", answer="robbe\u20107342\nPrüfung der Texterkennung") as fake:
        check = check_service(fake.service(), settings())
        assert (check.test, check.model_found, check.error) == ("passed", True, None)
        assert check.test_detail == "read back: robbe\u20107342 Prüfung der Texterkennung"
        assert check.seconds is not None and check.checked_at is not None
        (picture,) = fake.images()
        assert picture == probe_picture()


def test_the_real_test_fails_when_the_word_does_not_come_back() -> None:
    with fake_service("ollama", answer="Ein Bild mit Text. " * 30) as fake:
        check = check_service(fake.service(), settings())
        assert check.test == "failed"
        assert check.test_detail is not None
        assert check.test_detail.startswith(f"{TEST_WORD} not read back: Ein Bild")
        assert len(check.test_detail) <= 200 + len(TEST_WORD) + 20


def test_a_failed_test_request_is_reported() -> None:
    with fake_service("openai", status=500, body="busy") as fake:
        check = check_service(fake.service(), settings())
        assert (check.test, check.test_detail) == ("failed", "HTTP 500: busy")


def test_without_a_model_nothing_is_tested() -> None:
    with fake_service("lmstudio") as fake:
        check = check_service(fake.service(""), settings())
        assert check.error == "no model configured (MAILROBBE_AI_VISION_MODEL)"
        assert check.test is None and not fake.chats

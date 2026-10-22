import pytest

from mailrobbe.ai.model import (
    PAGE_SEPARATOR,
    AiOptions,
    ForbiddenService,
    OcrPage,
    configured_services,
    display_url,
    locality,
    page_text,
    refusal,
    result_engine,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import DOCUMENT_TEXT_LIMIT


def no_names(host: str) -> list[str]:
    return []


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:1234/v1",
        "http://host.docker.internal:11434",
        "http://ollama.localhost",
        "http://127.0.0.1:1234/v1",
        "http://10.1.2.3",
        "http://172.20.0.1:8080",
        "https://192.168.178.20:443/v1",
        "http://[::1]:1234",
        "http://[fd00::12]:1234",
    ],
)
def test_the_own_machine_and_private_networks_are_local(url: str) -> None:
    assert locality(url, no_names) == "local"


@pytest.mark.parametrize(
    "url", ["https://api.openai.com/v1", "http://8.8.8.8", "http://172.32.0.1", "http://unknown"]
)
def test_everything_else_is_remote(url: str) -> None:
    assert locality(url, no_names) == "remote"


def test_a_name_is_local_only_when_all_its_addresses_are_private() -> None:
    assert locality("http://mac-studio:1234", lambda host: ["192.168.1.5"]) == "local"
    assert locality("http://mixed:1234", lambda host: ["192.168.1.5", "1.1.1.1"]) == "remote"


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest",
        "http://[fe80::1]/",
        "ftp://localhost/",
        "localhost:1234",
        "http:///v1",
    ],
)
def test_metadata_addresses_and_non_http_urls_are_forbidden(url: str) -> None:
    with pytest.raises(ForbiddenService):
        locality(url, no_names)


def test_a_name_resolving_to_a_metadata_address_is_forbidden() -> None:
    with pytest.raises(ForbiddenService):
        locality("http://metadata.example", lambda host: ["169.254.169.254"])


def test_display_url_drops_credentials_query_and_trailing_slash() -> None:
    assert display_url("https://user:secret@api.example.com:8443/v1/?key=1#x") == (
        "https://api.example.com:8443/v1"
    )
    assert display_url("http://[::1]:1234/") == "http://[::1]:1234"


def test_the_settings_name_the_vision_service() -> None:
    assert configured_services(Settings(ai_vision_url="")) == {}
    settings = Settings(
        ai_vision_url=" http://host.docker.internal:1234/v1/ ",
        ai_vision_model="qwen2.5-vl-7b",
        ai_vision_key="secret",  # type: ignore[arg-type]
    )
    vision = configured_services(settings)["vision"]
    assert vision.url == "http://host.docker.internal:1234/v1"
    assert vision.model == "qwen2.5-vl-7b"
    assert vision.protocol == "auto"
    assert vision.key == "secret"
    assert "secret" not in repr(vision)
    assert refusal(vision, settings, no_names) is None


def test_a_remote_service_needs_the_permission() -> None:
    settings = Settings(ai_vision_url="https://api.example.com/v1", ai_vision_model="m")
    vision = configured_services(settings)["vision"]
    reason = refusal(vision, settings, no_names)
    assert reason is not None and "MAILROBBE_AI_ALLOW_REMOTE" in reason
    allowed = Settings(ai_vision_url="https://api.example.com/v1", ai_allow_remote=True)
    assert refusal(vision, allowed, no_names) is None
    metadata = configured_services(Settings(ai_vision_url="http://169.254.169.254"))["vision"]
    assert refusal(metadata, allowed, no_names) is not None


def test_page_text_joins_the_pages_with_a_text_in_order() -> None:
    pages = [
        OcrPage(number=2, engine="tesseract", text=" zwei \n"),
        OcrPage(number=1, engine="tesseract", text="eins"),
        OcrPage(number=3, engine="vision", text="", error="truncated"),
        OcrPage(number=4, engine="vision", text="vier"),
    ]
    assert page_text(pages) == (PAGE_SEPARATOR.join(["eins", "zwei", "vier"]), False)
    assert page_text([]) == ("", False)
    long = [OcrPage(number=1, engine="tesseract", text="x" * (DOCUMENT_TEXT_LIMIT + 5))]
    body, truncated = page_text(long)
    assert truncated and len(body) == DOCUMENT_TEXT_LIMIT


def test_result_engine_names_one_engine_or_mixed() -> None:
    tesseract = OcrPage(number=1, engine="tesseract")
    vision = OcrPage(number=2, engine="vision")
    failed = OcrPage(number=3, engine="vision", error="unreachable")
    assert result_engine([tesseract]) == "tesseract"
    assert result_engine([tesseract, failed]) == "tesseract"
    assert result_engine([tesseract, vision]) == "mixed"
    assert result_engine([failed]) == "vision"


def test_run_options_from_the_settings_carry_no_key() -> None:
    settings = Settings(
        ai_vision_url="http://user:pw@127.0.0.1:1234/v1",
        ai_vision_model="m",
        ai_vision_key="secret",  # type: ignore[arg-type]
        ai_ocr_max_pages=7,
    )
    options = AiOptions.from_settings(settings)
    assert options.vision_url == "http://127.0.0.1:1234/v1"
    assert options.vision_model == "m" and options.max_pages == 7
    assert not options.vision_remote
    assert "secret" not in options.model_dump_json() and "pw" not in options.model_dump_json()

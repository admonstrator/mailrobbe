"""Talking to AI services over HTTP with the standard library (D180): two protocols, the model
lists, one chat request with a picture or with a text and an answer schema (D300, D304), and the
real test of a service.

OpenAI-compatible (LM Studio, llama.cpp, vLLM, Ollama's /v1, services on the internet): the URL
is the base including /v1; a base without a version (http://host:1234) is accepted too, its
requests then go to {url}/v1/... when {url}/... answers 404. `GET models` lists the models; LM
Studio's `GET /api/v0/models` says which are vision models (type "vlm"). `POST
chat/completions` carries the picture as a PNG data URL, temperature 0, a max_tokens limit, and
for a local service chat_template_kwargs that switch thinking off (llama.cpp and LM Studio take
or ignore it; OpenAI itself refuses unknown fields, so a remote service never gets it).

Ollama: `GET /api/tags` lists the models, `POST /api/show` tells whether one has the capability
"vision", `POST /api/chat` carries the picture in `images`, with stream and thinking off, the
options temperature 0, num_ctx and num_predict, and keep_alive so a run does not reload the model
for every page. detect_protocol asks /api/tags unless the settings name the protocol: JSON with
`models` is Ollama, anything else OpenAI-compatible.

A text request (chat_text, the summaries of ai.summarize) sends a system and a user message and
asks for an answer by a JSON schema: `response_format` with `json_schema` (strict) for the
OpenAI-compatible protocol, asked again once without it when the service refuses the field;
Ollama's `format` with num_ctx set to the context the model was loaded with.

A service on this machine or a private network is asked without a proxy, whatever the
environment's proxy settings say (Docker Desktop's proxy would not reach host.docker.internal);
a remote one through the environment's proxy. The key goes out as a bearer token only when one
is set, and never into a message, a log or an error.

Errors: Unreachable (no connection, refused, DNS, no answer within the timeout) lets the run wait
(D184), ModelMissing stops it, AnswerError (an HTTP error, an answer that is not what the
protocol promises) counts as a failed attempt. Everything here is blocking; the run calls it in
threads.
"""

import base64
import io
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from mailrobbe.ai.model import (
    ForbiddenService,
    Protocol,
    Service,
    ServiceCheck,
    ServiceModel,
    locality,
    refusal,
)
from mailrobbe.config import Settings

USER_AGENT = "Mailrobbe"
CHECK_TIMEOUT = 20.0  # seconds for detection and the model lists of a check
NUM_CTX = 8192  # Ollama's context: a page picture of 1,600 px, the prompt and the answer
KEEP_ALIVE = "10m"  # Ollama keeps the model loaded between the pages of a run
# The real test (D180): a word no model knows by heart, and a German line around it.
TEST_WORD = "ROBBE-7342"
TEST_LINE = "Prüfung der Texterkennung: Größe, Maße und Übergänge"
# The text a text model summarises in its test (D300): the word is the project's name, which a
# summary names.
TEST_HEAD = ("Art: E-Mail", "Betreff: Neues Archivprojekt")
TEST_TEXT = (
    f"Liebe Kolleginnen und Kollegen, unser neues Archivprojekt heißt {TEST_WORD}. Es beginnt "
    "am 3. November in Bremen und soll bis Ende März abgeschlossen sein. Wer mitarbeiten "
    "möchte, meldet sich bitte bis Freitag bei Anna Berger."
)
_FONTS = Path(__file__).parent.parent / "export" / "fonts"
_DETAIL = 200  # characters of an answer or error body in a message


class ServiceError(Exception):
    """Something went wrong talking to a service (English, one line)."""


class Unreachable(ServiceError):
    """No connection, DNS, refused, or no answer within the timeout: the run waits (D184)."""


class ModelMissing(ServiceError):
    """The configured model is not offered by the service: the run stops."""


class AnswerError(ServiceError):
    """An HTTP error, an invalid answer, or one cut at its length limit: counts as an attempt."""


class _HttpStatus(AnswerError):
    """An HTTP error answer; status and the start of the body for the callers that tell a missing
    model or a missing endpoint from other errors."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:_DETAIL]}" if body else f"HTTP {status}")
        self.status = status
        self.body = body


@dataclass(frozen=True, slots=True)
class ChatAnswer:
    """What a chat request gave back, before the guards of ai.ocr.vision."""

    text: str
    finish: str | None  # finish_reason or done_reason; "length" when cut at max_tokens
    tokens_in: int
    tokens_out: int
    thought: bool = False  # the model reasoned before answering (a think block or its own field)


def cut_at_length(found: ChatAnswer, max_tokens: int) -> str:
    """Why an answer cut at max_tokens is none (D304), and whether thinking used them up."""
    detail = f"cut at the length limit of {max_tokens} tokens"
    if found.thought:
        detail += " while the model was thinking; switch its thinking off"
    return detail


# HTTP


def _opener(url: str) -> urllib.request.OpenerDirector:
    """Without a proxy for a service on this machine or a private network, with the
    environment's proxy for one elsewhere (module docstring)."""
    try:
        local = locality(url) == "local"
    except ForbiddenService as error:
        raise ServiceError(str(error)) from None
    if local:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _request(
    service: Service, url: str, timeout: float, payload: dict[str, Any] | None = None
) -> Any:
    """The JSON answer of GET (no payload) or POST url; see the module docstring for errors."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if service.key:
        headers["Authorization"] = f"Bearer {service.key}"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        response = _opener(url).open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        body = " ".join(error.read().decode("utf-8", "replace").split())
        if service.key:  # a service that repeats a wrong key in its error
            body = body.replace(service.key, "***")
        raise _HttpStatus(error.code, body) from None
    except TimeoutError:
        raise Unreachable(f"no answer from {service.display_url} within {timeout:g} s") from None
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        if isinstance(reason, TimeoutError):
            raise Unreachable(
                f"no answer from {service.display_url} within {timeout:g} s"
            ) from None
        raise Unreachable(f"{service.display_url} not reachable: {reason}"[:300]) from None
    except ValueError as error:  # an URL urllib cannot use
        raise ServiceError(f"unusable URL {service.display_url}: {error}") from None
    try:
        with response:
            body = response.read()
    except (TimeoutError, OSError) as error:
        raise AnswerError(f"the answer of {service.display_url} broke off: {error}") from None
    try:
        return json.loads(body)
    except ValueError:
        text = " ".join(body.decode("utf-8", "replace").split())
        raise AnswerError(f"not a JSON answer: {text[:_DETAIL]}") from None


def _versioned(url: str) -> bool:
    """Whether a base URL ends in an API version (/v1)."""
    return re.search(r"/v\d+$", url) is not None


def _openai(
    service: Service, path: str, timeout: float, payload: dict[str, Any] | None = None
) -> Any:
    """A request of the OpenAI-compatible protocol, at {url}/{path} and, for a base without a
    version that does not know the path there, at {url}/v1/{path}: 404, or LM Studio's 200 with
    only an error."""
    try:
        answer = _request(service, f"{service.url}/{path}", timeout, payload)
    except _HttpStatus as error:
        if error.status != 404 or _versioned(service.url):
            raise
    else:
        if _versioned(service.url) or not (isinstance(answer, dict) and set(answer) == {"error"}):
            return answer
    return _request(service, f"{service.url}/v1/{path}", timeout, payload)


def _root(url: str) -> str:
    """The server's address without the API version: where LM Studio has /api/v0."""
    return re.sub(r"/v\d+$", "", url)


# Protocols and models


def detect_protocol(service: Service, timeout: float) -> Protocol:
    """The service's protocol: the configured one, or for "auto" Ollama when /api/tags answers
    JSON with models, else OpenAI-compatible; raises Unreachable."""
    if service.protocol != "auto":
        return service.protocol
    try:
        answer = _request(service, f"{service.url}/api/tags", timeout)
    except AnswerError:
        return "openai"
    return "ollama" if isinstance(answer, dict) and "models" in answer else "openai"


def list_models(service: Service, timeout: float) -> list[ServiceModel]:
    """The models the service offers, by name, with whether each reads pictures where the service
    says so (LM Studio, Ollama); raises Unreachable, AnswerError."""
    if detect_protocol(service, timeout) == "ollama":
        answer = _request(service, f"{service.url}/api/tags", timeout)
        names = _names(answer, "models", "name")
        return [
            ServiceModel(name=name, vision=_ollama_vision(service, name, timeout)) for name in names
        ]
    names = _names(_openai(service, "models", timeout), "data", "id")
    kinds = _lmstudio_types(service, timeout)
    return [
        ServiceModel(name=name, vision=None if name not in kinds else kinds[name] == "vlm")
        for name in names
    ]


def _names(answer: Any, key: str, field: str) -> list[str]:
    entries = answer.get(key) if isinstance(answer, dict) else None
    if not isinstance(entries, list):
        raise AnswerError(f"the model list has no {key!r}")
    return [
        entry[field]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get(field), str)
    ]


def _ollama_vision(service: Service, name: str, timeout: float) -> bool | None:
    try:
        answer = _request(service, f"{service.url}/api/show", timeout, {"model": name})
    except AnswerError:
        return None
    capabilities = answer.get("capabilities") if isinstance(answer, dict) else None
    return "vision" in capabilities if isinstance(capabilities, list) else None


def _lmstudio_types(service: Service, timeout: float) -> dict[str, str]:
    """LM Studio's model types by name ("vlm", "llm", "embeddings"); empty for other services."""
    try:
        answer = _request(service, f"{_root(service.url)}/api/v0/models", timeout)
    except AnswerError:
        return {}
    entries = answer.get("data") if isinstance(answer, dict) else None
    if not isinstance(entries, list):
        return {}
    return {
        entry["id"]: entry["type"]
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and isinstance(entry.get("type"), str)
    }


def offers(models: list[ServiceModel], model: str) -> bool:
    """Whether a model list holds the model; Ollama's names carry a tag (":latest")."""
    names = {entry.name for entry in models}
    return model in names or f"{model}:latest" in names


# One chat request with a picture


def chat_image(
    service: Service,
    protocol: Protocol,
    png: bytes,
    prompt: str,
    *,
    max_tokens: int,
    timeout: float,
) -> ChatAnswer:
    """The model's answer to the prompt and one PNG; raises Unreachable, ModelMissing,
    AnswerError. Only the PNG and the prompt go out, to service.model."""
    model = service.model
    picture = base64.b64encode(png).decode("ascii")
    try:
        if protocol == "ollama":
            return _ollama_chat(service, model, picture, prompt, max_tokens, timeout)
        return _openai_chat(service, model, picture, prompt, max_tokens, timeout)
    except _HttpStatus as error:
        if _model_missing(error):
            raise ModelMissing(
                f"model {model!r} is not offered by {service.display_url} ({error})"
            ) from None
        raise


def _model_missing(error: _HttpStatus) -> bool:
    body = error.body.lower()
    named = "model" in body and ("not found" in body or "does not exist" in body)
    return error.status == 404 or (error.status in (400, 422) and named)


def _openai_chat(
    service: Service, model: str, picture: str, prompt: str, max_tokens: int, timeout: float
) -> ChatAnswer:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{picture}"}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if locality(service.url) == "local":
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return _openai_answer(_openai(service, "chat/completions", timeout, payload))


def _openai_answer(answer: Any) -> ChatAnswer:
    try:
        choice = answer["choices"][0]
        message = choice["message"]
        text = message.get("content") or ""
        thought = bool(message.get("reasoning_content") or message.get("reasoning"))
        finish = choice.get("finish_reason")
        usage = answer.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
    except (KeyError, IndexError, TypeError, AttributeError, ValueError):
        raise AnswerError(f"not a chat answer: {json.dumps(answer)[:_DETAIL]}") from None
    if not isinstance(text, str):
        raise AnswerError("the chat answer has no text")
    finish = finish if isinstance(finish, str) else None
    return ChatAnswer(text, finish, tokens_in, tokens_out, thought or "<think>" in text.lower())


def _ollama_chat(
    service: Service, model: str, picture: str, prompt: str, max_tokens: int, timeout: float
) -> ChatAnswer:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [picture]}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": max_tokens},
        "keep_alive": KEEP_ALIVE,
    }
    return _ollama_answer(_ollama_post(service, payload, timeout))


def _ollama_post(service: Service, payload: dict[str, Any], timeout: float) -> Any:
    """POST /api/chat; asked again without `think` when Ollama refuses it for a model without
    thinking."""
    url = f"{service.url}/api/chat"
    try:
        return _request(service, url, timeout, payload)
    except _HttpStatus as error:
        if error.status != 400 or "think" not in error.body.lower():
            raise
        del payload["think"]
        return _request(service, url, timeout, payload)


def _ollama_answer(answer: Any) -> ChatAnswer:
    try:
        text = answer["message"].get("content") or ""
        thought = bool(answer["message"].get("thinking"))
        finish = answer.get("done_reason")
        tokens_in = int(answer.get("prompt_eval_count") or 0)
        tokens_out = int(answer.get("eval_count") or 0)
    except (KeyError, TypeError, AttributeError, ValueError):
        raise AnswerError(f"not a chat answer: {json.dumps(answer)[:_DETAIL]}") from None
    if not isinstance(text, str):
        raise AnswerError("the chat answer has no text")
    finish = finish if isinstance(finish, str) else None
    return ChatAnswer(text, finish, tokens_in, tokens_out, thought or "<think>" in text.lower())


# One chat request with a text (D300)


def chat_text(
    service: Service,
    protocol: Protocol,
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int,
    timeout: float,
    context_tokens: int,
) -> ChatAnswer:
    """The model's answer to a system and a user message, asked for as JSON by schema (module
    docstring); raises Unreachable, ModelMissing, AnswerError. The caller checks the answer: one
    cut at max_tokens (finish "length") is never a valid one (D184, D304)."""
    model = service.model
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        if protocol == "ollama":
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0, "num_ctx": context_tokens, "num_predict": max_tokens},
                "keep_alive": KEEP_ALIVE,
            }
            return _ollama_answer(_ollama_post(service, payload, timeout))
        return _openai_text(service, model, messages, schema, max_tokens, timeout)
    except _HttpStatus as error:
        if _model_missing(error):
            raise ModelMissing(
                f"model {model!r} is not offered by {service.display_url} ({error})"
            ) from None
        raise


def _openai_text(
    service: Service,
    model: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    max_tokens: int,
    timeout: float,
) -> ChatAnswer:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "summary", "strict": True, "schema": schema},
        },
    }
    if locality(service.url) == "local":
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    try:
        answer = _openai(service, "chat/completions", timeout, payload)
    except _HttpStatus as error:
        body = error.body.lower()
        if error.status not in (400, 422) or not ("response_format" in body or "schema" in body):
            raise
        del payload["response_format"]  # a service without structured answers: the parser reads
        answer = _openai(service, "chat/completions", timeout, payload)
    return _openai_answer(answer)


# The check of the AI page and `mailrobbe ai check`


def check_service(service: Service, settings: Settings, *, test: bool = True) -> ServiceCheck:
    """What the service is and offers, and with `test` whether its model reads a picture with a
    known word back (D180) or, for text, answers a short text by the summary's JSON schema
    naming that word (D300); never raises. Nothing is asked when the settings refuse it."""
    try:
        where = locality(service.url)
    except ForbiddenService:
        where = None
    check = ServiceCheck(
        capability=service.capability,
        url=service.display_url,
        locality=where,
        model=service.model,
        checked_at=datetime.now(UTC),
    )
    check.refused = refusal(service, settings)
    if check.refused is not None:
        return check
    timeout = min(CHECK_TIMEOUT, settings.ai_timeout)
    try:
        check.protocol = detect_protocol(service, timeout)
        check.reachable = True
        check.models = list_models(service, timeout)
    except Unreachable as error:
        check.reachable = False
        check.error = str(error)
        return check
    except ServiceError as error:
        check.error = str(error)
        return check
    if check.models:
        check.model_found = offers(check.models, service.model) if service.model else False
    if not service.model:
        check.error = f"no model configured (MAILROBBE_AI_{service.capability.upper()}_MODEL)"
        return check
    if check.model_found is False:
        check.error = f"model {service.model!r} is not offered by {service.display_url}"
        return check
    if test and service.capability == "text":
        _test_text(service, settings, check)
    elif test:
        _test_vision(service, settings, check)
    return check


def _test_vision(service: Service, settings: Settings, check: ServiceCheck) -> None:
    """Reads probe_picture() through the vision model and records whether TEST_WORD came back."""
    from mailrobbe.ai.ocr import vision  # vision builds on this module
    from mailrobbe.ai.prompts import load_prompts

    assert check.protocol is not None
    started = time.monotonic()
    try:
        page = vision.read_page(
            service,
            probe_picture(),
            1,
            prompts=load_prompts(),
            protocol=check.protocol,
            timeout=settings.ai_timeout,
        )
    except ModelMissing as error:
        check.model_found = False
        check.test, check.test_detail, check.error = "failed", str(error), str(error)
        return
    except ServiceError as error:
        check.test, check.test_detail, check.error = "failed", str(error), str(error)
        return
    finally:
        check.seconds = round(time.monotonic() - started, 2)
    answer = " ".join(page.text.split())
    if _plain(TEST_WORD) in _plain(page.text):
        check.test, check.test_detail = "passed", f"read back: {answer[:_DETAIL]}"
    else:
        shown = answer[:_DETAIL] if answer else "no text"
        check.test, check.test_detail = "failed", f"{TEST_WORD} not read back: {shown}"


def _test_text(service: Service, settings: Settings, check: ServiceCheck) -> None:
    """Has the text model summarise TEST_TEXT as a run would (the summary prompts, the answer
    schema, the configured context) and records whether the answer reads by the schema and names
    TEST_WORD in its summary or its tags."""
    from mailrobbe.ai.prompts import load_prompts
    from mailrobbe.ai.summarize import answer, parts, prompt  # they build on this module
    from mailrobbe.themes import load_themes

    assert check.protocol is not None
    themes = load_themes()
    system = prompt.system_prompt(load_prompts().summarize, prompt.Vocabulary(themes, ()))
    user = prompt.user_message("", prompt.material(TEST_HEAD, TEST_TEXT))
    max_tokens = parts.answer_tokens(settings.ai_context_tokens, len(system) + len(user))
    started = time.monotonic()
    try:
        found = chat_text(
            service,
            check.protocol,
            system=system,
            user=user,
            schema=answer.answer_schema([theme.key for theme in themes]),
            max_tokens=max_tokens,
            timeout=settings.ai_timeout,
            context_tokens=settings.ai_context_tokens,
        )
        if found.finish == "length":
            raise AnswerError(cut_at_length(found, max_tokens))
        read = answer.read_answer(found.text)
    except ModelMissing as error:
        check.model_found = False
        check.test, check.test_detail, check.error = "failed", str(error), str(error)
        return
    except ServiceError as error:
        check.test, check.test_detail, check.error = "failed", str(error), str(error)
        return
    finally:
        check.seconds = round(time.monotonic() - started, 2)
    said = " ".join([read.summary, *read.tags])
    if _plain(TEST_WORD) in _plain(said):
        check.test, check.test_detail = "passed", f"summarised: {' '.join(said.split())[:_DETAIL]}"
    else:
        shown = " ".join(said.split())[:_DETAIL] or "an empty summary"
        check.test, check.test_detail = "failed", f"{TEST_WORD} not named: {shown}"


def _plain(text: str) -> str:
    """Text compared without case, spaces and the kind of dash."""
    return re.sub(r"[\u2010-\u2015\u2212]", "-", "".join(text.split())).casefold()


def probe_picture() -> bytes:
    """A PNG with TEST_WORD in large letters above TEST_LINE, drawn with the DejaVu fonts."""
    image = Image.new("L", (900, 260), 255)
    draw = ImageDraw.Draw(image)
    bold = ImageFont.truetype(str(_FONTS / "DejaVuSans-Bold.ttf"), 72)
    plain = ImageFont.truetype(str(_FONTS / "DejaVuSans.ttf"), 30)
    draw.text((40, 40), TEST_WORD, font=bold, fill=0)
    draw.text((40, 170), TEST_LINE, font=plain, fill=0)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()

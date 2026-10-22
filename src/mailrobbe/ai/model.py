"""What the AI modules hand each other (D180 to D189): services, OCR pages, run options and figures.

The contract between ai.services, ai.ocr, ai.run, ai.store and api/ai.py; nothing here does I/O
except locality's name lookup.
"""

import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from mailrobbe.config import Settings
from mailrobbe.db.models import DOCUMENT_TEXT_LIMIT
from mailrobbe.enums import AiTaskKind
from mailrobbe.jobs import RunProgress

Capability = Literal["vision"]  # M16 adds "audio", M17 "text"
Protocol = Literal["openai", "ollama"]
Locality = Literal["local", "remote"]
OcrEngine = Literal["tesseract", "vision"]
OcrEngineChoice = Literal["auto", "tesseract", "vision"]  # ai_task.engine, MAILROBBE_AI_OCR_ENGINE

AI_TASK_ATTEMPTS = 3  # attempts of a task before it fails (D184)
PRIORITY_SINGLE = 100  # queued for one document from its page: before everything else (D186)
PRIORITY_FILED = 10  # carried by a mail in an Akte or reviewed relevant
LOGO_MAILS = 50  # images in more mails are left out of a selection unless chosen (D186)
IMAGE_MIN_BYTES = 100 * 1024  # smaller images are not on the work list "Bilder"
NO_TEXT_MARK = "[kein Text]"  # the vision prompt's answer for a page without writing
PAGE_SEPARATOR = "\n\f\n"  # between the pages of a recognised text
# The steps of an AI run (job.steps, D187), in order.
AI_STEPS = ("check", "ocr", "entities", "signals")  # entities computes its figures at its end


class ForbiddenService(ValueError):
    """The URL cannot name an AI service: not http(s), no host, or a link-local (cloud metadata)
    address (D181)."""


# Names of the own machine as a container sees it (Docker Desktop, compose's host-gateway).
_LOCAL_NAMES = frozenset({"localhost", "host.docker.internal", "gateway.docker.internal"})
_PRIVATE = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)
_LINK_LOCAL = tuple(ipaddress.ip_network(network) for network in ("169.254.0.0/16", "fe80::/10"))
Resolver = Callable[[str], Sequence[str]]


def _resolve(host: str) -> list[str]:
    try:
        return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None)})
    except OSError:
        return []


def locality(url: str, resolve: Resolver = _resolve) -> Locality:
    """Whether the service at url is on the own machine or a private network ("local") or
    elsewhere ("remote", D181); raises ForbiddenService for what can never be a service.

    A name is local when it is one of the container's names for the machine, ends in .localhost
    or resolves only to private addresses; one that does not resolve counts as remote.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host:
        raise ForbiddenService(f"not an http(s) URL with a host: {display_url(url)}")
    if host in _LOCAL_NAMES or host.endswith(".localhost"):
        return "local"
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = [ipaddress.ip_address(address.split("%")[0]) for address in resolve(host)]
    if any(address in network for address in addresses for network in _LINK_LOCAL):
        raise ForbiddenService(f"link-local addresses are never AI services: {host}")
    if addresses and all(any(a in network for network in _PRIVATE) for a in addresses):
        return "local"
    return "remote"


def display_url(url: str) -> str:
    """The URL without user, password, query and fragment: what logs, results and the UI show."""
    parts = urlsplit(url.strip())
    netloc = parts.hostname or ""
    if ":" in netloc:
        netloc = f"[{netloc}]"
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))


@dataclass(frozen=True, slots=True)
class Service:
    """One configured service (D180): where it is, which model, how to talk to it."""

    capability: Capability
    url: str  # the configured base URL, without a trailing slash
    model: str  # "" when not configured: the run then refuses to use the service
    protocol: Protocol | Literal["auto"]
    key: str = field(default="", repr=False)  # sent as a bearer token; never logged or stored

    @property
    def display_url(self) -> str:
        return display_url(self.url)


def configured_services(settings: Settings) -> dict[Capability, Service]:
    """The services the settings name; a capability without a URL is absent."""
    services: dict[Capability, Service] = {}
    if settings.ai_vision_url.strip():
        services["vision"] = Service(
            capability="vision",
            url=settings.ai_vision_url.strip().rstrip("/"),
            model=settings.ai_vision_model.strip(),
            protocol=settings.ai_vision_protocol,
            key=settings.ai_vision_key.get_secret_value(),
        )
    return services


def refusal(service: Service, settings: Settings, resolve: Resolver = _resolve) -> str | None:
    """Why the settings forbid using this service (English, one line), or None (D181)."""
    try:
        where = locality(service.url, resolve)
    except ForbiddenService as error:
        return str(error)
    if where == "remote" and not settings.ai_allow_remote:
        return (
            f"{service.display_url} is outside this machine and its networks; "
            "set MAILROBBE_AI_ALLOW_REMOTE=true to use it"
        )
    return None


class ServiceModel(BaseModel):
    """A model a service offers (D180), with what it can do when the service says so."""

    name: str
    vision: bool | None = None  # None: the service does not tell


class ServiceCheck(BaseModel):
    """What checking one service found (ai.services.check_service): served by the API as is."""

    capability: Capability
    url: str  # display_url
    locality: Locality | None  # None: the URL is forbidden
    refused: str | None = None  # why the settings forbid it (refusal); then nothing was asked
    reachable: bool | None = None  # None: not asked
    protocol: Protocol | None = None  # detected or configured
    models: list[ServiceModel] = []
    model: str = ""  # the configured one
    model_found: bool | None = None  # None: the service lists no models
    # The real test (D180): a picture with a known word, read back by the model.
    test: Literal["passed", "failed"] | None = None
    test_detail: str | None = None  # English: what came back, or why it failed
    seconds: float | None = None  # of the test
    error: str | None = None  # English, one line
    checked_at: datetime | None = None


class OcrPage(BaseModel):
    """One page of an OCR result (ai_result.pages, ai_task.partial), numbered from 1."""

    number: int
    engine: OcrEngine
    text: str = ""  # "" without writing; never the NO_TEXT_MARK
    confidence: float | None = None  # Tesseract's mean word confidence, 0 to 100
    uncertain: bool = False  # below MAILROBBE_AI_OCR_UNCERTAIN, or a loop was cut (D184)
    looped: bool = False  # the answer repeated a line and was cut there
    error: str | None = None  # the page failed (English, one line); it is skipped
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


class Partial(BaseModel):
    """ai_task.partial of an OCR task: the pages read so far, kept across a stop."""

    pages: list[OcrPage] = []
    pages_total: int | None = None


def page_text(pages: Sequence[OcrPage]) -> tuple[str, bool]:
    """The text of the pages that have one, in page order, and whether it was cut at
    DOCUMENT_TEXT_LIMIT (D185)."""
    texts = [page.text.strip() for page in sorted(pages, key=lambda page: page.number)]
    joined = PAGE_SEPARATOR.join(text for text in texts if text)
    if len(joined) > DOCUMENT_TEXT_LIMIT:
        return joined[:DOCUMENT_TEXT_LIMIT], True
    return joined, False


def result_engine(pages: Sequence[OcrPage]) -> str:
    """ai_result.engine of these pages: "tesseract", "vision" or "mixed"."""
    engines = {page.engine for page in pages if page.error is None} or {
        page.engine for page in pages
    }
    return engines.pop() if len(engines) == 1 else "mixed"


class AiOptions(BaseModel):
    """What an AI run works with (job.options of kind ai); the dashboard's defaults (D49)."""

    kinds: list[AiTaskKind] = [AiTaskKind.OCR]
    ocr_engine: OcrEngineChoice = "auto"  # for tasks queued with "auto"
    vision_model: str = ""  # overrides MAILROBBE_AI_VISION_MODEL for this run when set
    max_pages: int = 50
    languages: str = "deu+eng"
    uncertain: float = 60.0
    concurrency: int = 1  # requests per service at once
    tesseract_workers: int = 1  # pages Tesseract reads at once
    vision_url: str = ""  # display_url of the vision service, "" without one
    vision_remote: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> "AiOptions":
        vision = configured_services(settings).get("vision")
        remote = False
        if vision is not None:
            try:
                remote = locality(vision.url) == "remote"
            except ForbiddenService:
                remote = False
        return cls(
            ocr_engine=settings.ai_ocr_engine,
            vision_model=vision.model if vision else "",
            max_pages=settings.ai_ocr_max_pages,
            languages=settings.ai_ocr_languages,
            uncertain=settings.ai_ocr_uncertain,
            concurrency=settings.ai_concurrency,
            tesseract_workers=max(1, min(4, settings.import_workers)),
            vision_url=vision.display_url if vision else "",
            vision_remote=remote,
        )


class AiProgress(RunProgress):
    """Live figures of an AI run (job.progress of kind ai); its pages are the ocr step's."""

    queued: int = 0  # tasks waiting when the run started
    done: int = 0  # tasks this run finished with a text
    no_text: int = 0  # finished without writing found
    failed: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    current: str | None = None  # the file name of the document in work
    unreachable_since: datetime | None = None  # a service did not answer since then (D184)

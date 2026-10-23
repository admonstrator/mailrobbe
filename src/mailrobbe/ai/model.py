"""What the AI modules hand each other (D180 to D189, D290 to D297, D300 to D311): services, OCR
pages, transcript segments, summaries, run options and figures.

The contract between ai.services, ai.ocr, ai.audio, ai.summarize, ai.run, ai.store and
api/ai.py; nothing here does I/O except locality's name lookup.
"""

import importlib.util
import ipaddress
import os
import re
import socket
import unicodedata
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

Capability = Literal["vision", "text"]  # M16 adds "audio"
Protocol = Literal["openai", "ollama"]
Locality = Literal["local", "remote"]
OcrEngine = Literal["tesseract", "vision"]
OcrEngineChoice = Literal["auto", "tesseract", "vision"]  # ai_task.engine, MAILROBBE_AI_OCR_ENGINE
# What reads a selection: the OCR engines and the transcriber (D290). Transcribe tasks keep the
# engine "auto" in ai_task, since there is only the one.
AiEngine = Literal["tesseract", "vision", "parakeet"]
TRANSCRIBE_MODEL = "parakeet-tdt-0.6b-v3"  # ai_result.model of a transcript (D290)

AI_TASK_ATTEMPTS = 3  # attempts of a task before it fails (D184)
PRIORITY_SINGLE = 100  # queued for one document from its page: before everything else (D186)
PRIORITY_FILED = 10  # carried by a mail in an Akte or reviewed relevant
LOGO_MAILS = 50  # images in more mails are left out of a selection unless chosen (D186)
IMAGE_MIN_BYTES = 100 * 1024  # smaller images are not on the work list "Bilder"
NO_TEXT_MARK = "[kein Text]"  # the vision prompt's answer for a page without writing
PAGE_SEPARATOR = "\n\f\n"  # between the pages of a recognised text
# The steps of an AI run (job.steps, D187), in order: summaries after OCR and transcription, so a
# text recognised or transcribed in the same run is what they read.
AI_STEPS = ("check", "ocr", "transcribe", "summarize", "entities", "signals")  # entities: figures
# Transcription (D292, D293): pieces of speech the transcriber reads at once, lines of a transcript
PIECE_SECONDS = 25.0  # longest piece, cut at a pause where there is one
SEGMENT_SECONDS = 15.0  # longest line of a transcript; a line ends at a sentence's end or a pause

# Summaries (D300 to D311).
SUMMARY_MIN_WORDS = 50  # own text below this: tags and theme hints only, no summary (D302)
SUMMARY_MAX_PARTS = 20  # parts of a long text summarised; beyond, the first ones only (D303)
SUMMARY_MAX_TAGS = 6  # AI tags kept per summary (D304)
SUMMARY_MAX_HINTS = 6  # theme quotes one answer may give (D304)
THREAD_MIN_MAILS = 2  # a thread summarised as a whole has at least this many mails (D316)
TAG_MAX_CHARS = 40  # longer tags are dropped, not cut
QUOTE_MAX_CHARS = 300  # longer quotes are dropped, not cut
THEME_HINTS_PER_THEME = 3  # quotes kept per theme and summary
CHARS_PER_TOKEN = 3.5  # German text, without a tokenizer (D303)
# An answer's max_tokens is what the context leaves beside the request (summarize.parts), at least
# the room a part always leaves for it and at most the ceiling against a model that never stops.
SUMMARY_ANSWER_TOKENS = 1200  # room for the answer that part_chars keeps free
SUMMARY_ANSWER_MAX_TOKENS = 8192
VOCABULARY_TAGS = 200  # the most used AI tags the prompt offers besides the team's tags (D305)
# Seconds without a measurement (D188): per task, and per 1,000 tokens of input.
SUMMARY_RULE_SECONDS_PER_TASK = 3.0
SUMMARY_RULE_SECONDS_PER_KTOKEN = 5.0


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
    if settings.ai_text_url.strip():
        services["text"] = Service(
            capability="text",
            url=settings.ai_text_url.strip().rstrip("/"),
            model=settings.ai_text_model.strip(),
            protocol=settings.ai_text_protocol,
            key=settings.ai_text_key.get_secret_value(),
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
    # The real test (D180): a picture with a known word, read back by the model; for text a short
    # text whose summary by the answer schema must name the word (D300).
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


class TranscriptSegment(BaseModel):
    """One line of a transcript (ai_result.pages of kind transcribe, D293): a sentence or what
    was said up to a pause, at most SEGMENT_SECONDS long."""

    start: float  # seconds from the recording's start
    end: float
    text: str
    confidence: float | None = None  # mean probability of its tokens, 0 to 1
    uncertain: bool = False  # confidence below MAILROBBE_AI_TRANSCRIBE_UNCERTAIN


class TranscriptPartial(BaseModel):
    """ai_task.partial of a transcribe task: the lines read so far, kept across a stop."""

    segments: list[TranscriptSegment] = []
    until: float = 0.0  # seconds of the recording read; the next run goes on from here
    duration: float | None = None  # of the recording, once decoded


def transcript_text(segments: Sequence[TranscriptSegment]) -> tuple[str, bool]:
    """The text of a transcript, one line per segment in time order, and whether it was cut at
    DOCUMENT_TEXT_LIMIT (D294); timestamps stay in the segments."""
    lines = [segment.text.strip() for segment in sorted(segments, key=lambda s: s.start)]
    joined = "\n".join(line for line in lines if line)
    if len(joined) > DOCUMENT_TEXT_LIMIT:
        return joined[:DOCUMENT_TEXT_LIMIT], True
    return joined, False


class AiOptions(BaseModel):
    """What an AI run works with (job.options of kind ai); the dashboard's defaults (D49)."""

    kinds: list[AiTaskKind] = [AiTaskKind.OCR, AiTaskKind.TRANSCRIBE]
    ocr_engine: OcrEngineChoice = "auto"  # for tasks queued with "auto"
    vision_model: str = ""  # overrides MAILROBBE_AI_VISION_MODEL for this run when set
    max_pages: int = 50
    languages: str = "deu+eng"
    uncertain: float = 60.0
    concurrency: int = 1  # requests per service at once
    tesseract_workers: int = 1  # pages Tesseract reads at once
    documents: list[int] = []  # only the tasks of these documents (one started from its page)
    vision_url: str = ""  # display_url of the vision service, "" without one
    vision_remote: bool = False
    max_minutes: int = 180  # of a recording per document and pass (D292)
    transcribe_threads: int = 4  # CPU threads of the transcriber
    transcribe_uncertain: float = 0.8  # lines below this mean token probability are uncertain
    # M17 (D300): with documents, a run for some elements only takes the tasks of these mails
    # too (one started from its page, D307); the text model overrides MAILROBBE_AI_TEXT_MODEL.
    mails: list[int] = []
    threads: list[int] = []  # and the summaries of these threads (D316)
    text_model: str = ""
    text_url: str = ""  # display_url of the text service, "" without one
    text_remote: bool = False
    context_tokens: int = 4096

    @property
    def only(self) -> dict[str, list[int]]:
        """The parameters of the run's restriction to some elements (ai.run._ONLY)."""
        return {"documents": self.documents, "mails": self.mails, "threads": self.threads}

    @classmethod
    def from_settings(cls, settings: Settings) -> "AiOptions":
        services = configured_services(settings)
        vision = services.get("vision")
        text = services.get("text")
        return cls(
            ocr_engine=settings.ai_ocr_engine,
            vision_model=vision.model if vision else "",
            max_pages=settings.ai_ocr_max_pages,
            languages=settings.ai_ocr_languages,
            uncertain=settings.ai_ocr_uncertain,
            concurrency=settings.ai_concurrency,
            tesseract_workers=max(1, min(4, settings.import_workers)),
            vision_url=vision.display_url if vision else "",
            vision_remote=_remote(vision),
            max_minutes=settings.ai_transcribe_max_minutes,
            transcribe_threads=transcribe_threads(settings),
            transcribe_uncertain=settings.ai_transcribe_uncertain,
            text_model=text.model if text else "",
            text_url=text.display_url if text else "",
            text_remote=_remote(text),
            context_tokens=settings.ai_context_tokens,
        )


def _remote(service: Service | None) -> bool:
    if service is None:
        return False
    try:
        return locality(service.url) == "remote"
    except ForbiddenService:
        return False


def transcribe_threads(settings: Settings) -> int:
    """MAILROBBE_AI_TRANSCRIBE_THREADS, or for 0 the CPUs up to four."""
    if settings.ai_transcribe_threads > 0:
        return settings.ai_transcribe_threads
    return max(1, min(4, os.cpu_count() or 1))


class AiProgress(RunProgress):
    """Live figures of an AI run (job.progress of kind ai); its pages are the ocr step's."""

    queued: int = 0  # tasks waiting when the run started
    done: int = 0  # tasks this run finished with a text
    no_text: int = 0  # finished without writing found
    failed: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    current: str | None = None  # the file name of the document in work
    minutes: float = 0.0  # of recordings transcribed by this run
    position: float | None = None  # seconds reached in the recording in work
    duration: float | None = None  # of the recording in work, once decoded
    unreachable_since: datetime | None = None  # a service did not answer since then (D184)
    summaries: int = 0  # summarize tasks done (D300); done, no_text and failed count OCR's


TRANSCRIBER_MODULES = ("onnx_asr", "onnxruntime", "av")  # what the transcriber needs installed


def transcriber_available() -> bool:
    """Whether the transcriber's libraries are installed (AiTranscriptionInfo.available); they
    are looked up, not imported."""
    return all(importlib.util.find_spec(name) is not None for name in TRANSCRIBER_MODULES)


# Summaries (D300 to D311) -----------------------------------------------------------------------


class ThemeHint(BaseModel):
    """A theme of themes.toml with the quote that shows it (D304), checked against the text."""

    theme: str  # a theme key of themes.toml
    quote: str  # as it stands in the text (its spelling, not the model's)
    # Character offset in the stored text (mail.body_text, document.extracted_text); None: it
    # stands only in the head (subject, file name) or in a line the input added ("Weitergeleitet:").
    position: int | None = None


class SummaryPart(BaseModel):
    """One part of a long text and what the model made of it (ai_result.pages of a summary)."""

    number: int  # from 1
    characters: int  # of the part's text
    summary: str = ""
    error: str | None = None  # the part failed (English, one line); the others count
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


class Summary(BaseModel):
    """What the summarize step hands ai.store.store_summary_result: the checked answer."""

    summary: str  # "" for a short text (short) or when the model found nothing to say
    tags: list[str]  # labels as checked (D304), at most SUMMARY_MAX_TAGS
    themes: list[ThemeHint]
    parts: list[SummaryPart]  # one for a text that fits the context
    parts_total: int  # the text's parts; more than len(parts) when cut at SUMMARY_MAX_PARTS
    short: bool = False  # own text below SUMMARY_MIN_WORDS: tags and hints only (D302)
    dropped_tags: int = 0  # too long, or beyond SUMMARY_MAX_TAGS
    dropped_themes: int = 0  # unknown theme, or the quote is not in the text (D304)
    words: int = 0  # of the text read
    origin: str | None = None  # a document's text_origin: extracted, ocr or transcript


def tag_key(label: str) -> str:
    """The key an AI tag is stored and matched by (D305): NFKC, case folded, umlauts and ß
    written out, every run of spaces, dashes and underscores one space, the ends trimmed: so
    "Spenden-Quittung" and "spenden quittung " are one tag, "Größe" and "groesse" too, while
    "Spendenquittung" is another."""
    folded = unicodedata.normalize("NFKC", label).casefold()
    for umlaut, written in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        folded = folded.replace(umlaut, written)
    return re.sub(r"[\s_\-\u2010-\u2015]+", " ", folded).strip()

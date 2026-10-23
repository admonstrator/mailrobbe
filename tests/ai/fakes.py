"""Fake AI services for tests: a small threaded HTTP server that plays an OpenAI-compatible
service (plain, or LM Studio with /api/v0/models) or Ollama.

    with fake_service("ollama", models={"llava:latest": True}, answer="Text") as fake:
        service = fake.service()          # an ai.model.Service pointing at it
        ...
        fake.chats                        # the chat requests received, as Recorded
        fake.images()                     # the pictures they carried, decoded

Everything is configurable on the FakeService while it runs, so a test can change the answer
between requests: `models` (name -> vision, None: the service does not tell), `answer` (or
`answers`, a list taken one per chat request before `answer`; or `respond`, a function making
the answer from the request's JSON body, before both), `finish` ("stop", "length"),
`delay` (seconds before each chat answer), `status` and `body` (an error answer of every chat
request), `tokens` (prompt and answer tokens it reports), `refuse_schema` (an OpenAI flavour
answers a chat request with `response_format` with 400, as a service without structured answers
does). It records every request (method, path, headers, JSON body) in `requests`.

The OpenAI flavours serve below /v1 (fake.url ends in /v1); "lmstudio" answers unknown paths with
200 and an error JSON as LM Studio does, "openai" with 404. A request to a model that is not
offered gets 404 with the message the real service gives.

FakeAudio plays ai.audio for the run (D290 to D293): the decoder, the transcriber and the model
files, as the Engines seam of ai.run takes them.

    audio = FakeAudio({digest(data): Recording(30.0, (Line(2.0, 6.5, "Guten Tag."),))})
    replace(engines, **audio.engines())   # decode, transcriber, model_state, download_model

A recording is known by the SHA-256 of its bytes; the decoder hands out samples that name it,
so the transcriber knows what it hears. Each line of a Recording is a piece of its own. The
model's files lack `missing` bytes until download_model fetched them in `chunk`s (or fails with
`unavailable`); `decode_errors` and `read_errors` name recordings that fail, `hold` a piece
(recording, start) whose reading waits until `release` is set, `reading` being set meanwhile.
Every call is recorded: `decodes`, `loads` (threads), `reads` (recording, piece start),
`downloads`.
"""

import base64
import hashlib
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal

import numpy as np

from mailrobbe.ai.audio.decode import SAMPLE_RATE, Decoded
from mailrobbe.ai.audio.parakeet import ModelState, Piece
from mailrobbe.ai.model import Capability, Protocol, Service, TranscriptSegment

Flavour = Literal["openai", "lmstudio", "ollama"]


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: Any  # the parsed JSON, None for a GET


@dataclass
class FakeService:
    flavour: Flavour
    models: dict[str, bool | None] = field(default_factory=lambda: {"vision-model": True})
    answer: str = "Erkannter Text"
    answers: list[str] = field(default_factory=list)
    respond: Callable[[Any], str] | None = None
    finish: str = "stop"
    delay: float = 0.0
    status: int | None = None
    body: str = '{"error": "fake failure"}'
    tokens: tuple[int, int] = (1200, 40)
    refuse_schema: bool = False
    requests: list[Recorded] = field(default_factory=list)
    port: int = 0

    @property
    def url(self) -> str:
        base = f"http://127.0.0.1:{self.port}"
        return base if self.flavour == "ollama" else f"{base}/v1"

    @property
    def protocol(self) -> Protocol:
        return "ollama" if self.flavour == "ollama" else "openai"

    def service(
        self,
        model: str | None = None,
        *,
        key: str = "",
        auto: bool = True,
        capability: Capability = "vision",
    ) -> Service:
        """A vision Service (or one of capability) at this fake, with the first model unless one
        is named; protocol "auto" unless `auto` is False."""
        return Service(
            capability=capability,
            url=self.url,
            model=next(iter(self.models), "") if model is None else model,
            protocol="auto" if auto else self.protocol,
            key=key,
        )

    @property
    def chats(self) -> list[Recorded]:
        return [r for r in self.requests if r.path.endswith(("/chat/completions", "/api/chat"))]

    def images(self) -> list[bytes]:
        """The pictures of the chat requests, decoded, in order."""
        found = []
        for chat in self.chats:
            for message in chat.body["messages"]:
                for picture in message.get("images", []):
                    found.append(base64.b64decode(picture))
                content = message.get("content")
                for part in content if isinstance(content, list) else []:
                    if part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        assert url.startswith("data:image/png;base64,")
                        found.append(base64.b64decode(url.partition(",")[2]))
        return found

    def next_answer(self, body: Any = None) -> str:
        if self.respond is not None:
            return self.respond(body)
        return self.answers.pop(0) if self.answers else self.answer


def _handler(fake: FakeService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            self._handle(None)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            self._handle(json.loads(self.rfile.read(length)))

        def _handle(self, body: Any) -> None:
            fake.requests.append(Recorded(self.command, self.path, dict(self.headers), body))
            path = self.path
            if fake.flavour == "ollama":
                self._ollama(path, body)
            else:
                self._openai(path, body)

        def _send(self, status: int, answer: Any) -> None:
            data = (answer if isinstance(answer, str) else json.dumps(answer)).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _unknown(self) -> None:
            if fake.flavour == "lmstudio":
                self._send(200, {"error": f"Unexpected endpoint or method. ({self.path})"})
            else:
                self._send(404, {"error": {"message": "not found"}})

        def _chat_failure(self, model: str) -> bool:
            if fake.delay:
                time.sleep(fake.delay)
            if fake.status is not None:
                self._send(fake.status, fake.body)
                return True
            if model not in fake.models:
                if fake.flavour == "ollama":
                    error: Any = {"error": f'model "{model}" not found, try pulling it first'}
                else:
                    error = {"error": {"message": f"The model `{model}` does not exist."}}
                self._send(404, error)
                return True
            return False

        def _openai(self, path: str, body: Any) -> None:
            if path == "/v1/models":
                self._send(200, {"object": "list", "data": [{"id": m} for m in fake.models]})
            elif path == "/api/v0/models" and fake.flavour == "lmstudio":
                data = [
                    {"id": m, "type": "vlm" if vision else "llm"}
                    for m, vision in fake.models.items()
                    if vision is not None
                ]
                self._send(200, {"data": data})
            elif path == "/v1/chat/completions" and body is not None:
                if self._chat_failure(body["model"]):
                    return
                if fake.refuse_schema and "response_format" in body:
                    error = {"error": {"message": "'response_format' is not supported"}}
                    self._send(400, error)
                    return
                self._send(
                    200,
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": fake.next_answer(body)},
                                "finish_reason": fake.finish,
                            }
                        ],
                        "usage": {
                            "prompt_tokens": fake.tokens[0],
                            "completion_tokens": fake.tokens[1],
                        },
                    },
                )
            else:
                self._unknown()

        def _ollama(self, path: str, body: Any) -> None:
            if path == "/api/tags":
                self._send(200, {"models": [{"name": m, "model": m} for m in fake.models]})
            elif path == "/api/show" and body is not None:
                if body["model"] not in fake.models:
                    self._send(404, {"error": f"model '{body['model']}' not found"})
                    return
                vision = fake.models[body["model"]]
                show: dict[str, Any] = {"details": {"family": "fake"}}
                if vision is not None:
                    show["capabilities"] = ["completion", *(["vision"] if vision else [])]
                self._send(200, show)
            elif path == "/api/chat" and body is not None:
                if self._chat_failure(body["model"]):
                    return
                self._send(
                    200,
                    {
                        "model": body["model"],
                        "message": {"role": "assistant", "content": fake.next_answer(body)},
                        "done": True,
                        "done_reason": fake.finish,
                        "prompt_eval_count": fake.tokens[0],
                        "eval_count": fake.tokens[1],
                    },
                )
            else:
                self._send(404, "404 page not found")

    return Handler


@contextmanager
def fake_service(flavour: Flavour, **options: Any) -> Iterator[FakeService]:
    """A FakeService of this flavour serving on a free port of 127.0.0.1 while the block runs."""
    fake = FakeService(flavour, **options)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    server.daemon_threads = True
    fake.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


# ai.audio ---------------------------------------------------------------------------------------


class DecodeError(Exception):
    pass


class ModelMissing(Exception):
    pass


MODEL_TOTAL = 670_000_000  # what FakeAudio's model files weigh


@dataclass(frozen=True, slots=True)
class Line:
    start: float
    end: float
    text: str
    confidence: float = 0.9


@dataclass(frozen=True, slots=True)
class Recording:
    """What a fake recording holds: its length, its lines of speech, whether it has sound and
    whether the decoder tells its length."""

    seconds: float
    lines: tuple[Line, ...] = ()
    audio: bool = True
    known: bool = True


@dataclass
class FakeAudio:
    """The decoder, the transcriber and the model files (module docstring)."""

    recordings: dict[str, Recording]  # by the SHA-256 of their bytes
    names: dict[str, str] = field(default_factory=dict)  # SHA-256 -> what the calls record
    missing: int = 0
    chunk: int = 100_000_000
    unavailable: str | None = None  # download_model fails with this
    decode_errors: set[str] = field(default_factory=set)  # names
    read_errors: set[str] = field(default_factory=set)
    hold: tuple[str, float] | None = None  # ("model", bytes fetched) holds the download
    reading: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    decodes: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    loads: list[int] = field(default_factory=list)
    reads: list[tuple[str, float]] = field(default_factory=list)
    downloads: list[int] = field(default_factory=list)  # bytes fetched per call

    def engines(self) -> dict[str, Any]:
        """The fields of ai.run.Engines this plays; its errors are DecodeError and ModelMissing
        of this module."""
        return {
            "decode": self.decode,
            "transcriber": self.transcriber,
            "model_state": self.model_state,
            "download_model": self.download_model,
        }

    def _name(self, sha256: str) -> str:
        return self.names.get(sha256, sha256[:12])

    def decode(self, data: bytes, *, timeout: float, memory: int, max_seconds: float) -> Decoded:
        sha256 = hashlib.sha256(data).hexdigest()
        name = self._name(sha256)
        self.decodes.append((name, {"timeout": timeout, "memory": memory, "max": max_seconds}))
        if name in self.decode_errors:
            raise DecodeError("Invalid data found when processing input")
        recording = self.recordings[sha256]
        if not recording.audio:
            return Decoded(np.zeros(0, dtype=np.int16), recording.seconds, audio=False)
        # The samples name the recording: its place among the recordings, in every sample.
        index = list(self.recordings).index(sha256) + 1
        length = int(min(recording.seconds, max_seconds) * SAMPLE_RATE)
        samples = np.full(length, index, dtype=np.int16)
        return Decoded(samples, recording.seconds if recording.known else None, audio=True)

    def model_state(self, model_dir: Path) -> ModelState:
        return ModelState(self.missing == 0, self.missing, MODEL_TOTAL)

    def download_model(
        self,
        model_dir: Path,
        *,
        progress: Callable[[int], None],
        stop: threading.Event,
        timeout: float = 60.0,
    ) -> None:
        fetched = 0
        try:
            if self.unavailable is not None:
                raise ModelMissing(self.unavailable)
            while self.missing > 0 and not stop.is_set():
                count = min(self.chunk, self.missing)
                self.missing -= count
                fetched += count
                progress(count)
                if self.hold == ("model", fetched):
                    self.reading.set()
                    assert self.release.wait(10)
        finally:
            self.downloads.append(fetched)

    def transcriber(self, model_dir: Path, *, threads: int) -> "FakeTranscriber":
        if self.missing:
            raise ModelMissing(f"{self.missing} bytes of the model are missing")
        self.loads.append(threads)
        return FakeTranscriber(self)

    def recording(self, samples: Any) -> tuple[str, Recording]:
        sha256 = list(self.recordings)[int(samples[0]) - 1]
        return self._name(sha256), self.recordings[sha256]


@dataclass
class FakeTranscriber:
    """Each line of a recording is a piece; reading a piece gives its line."""

    audio: FakeAudio

    def pieces(self, samples: Any, *, start: float = 0.0) -> list[Piece]:
        if not len(samples):
            return []
        _, recording = self.audio.recording(samples)
        heard = len(samples) / SAMPLE_RATE
        return [
            Piece(line.start, line.end)
            for line in recording.lines
            if line.start >= start and line.end <= heard
        ]

    def read(self, samples: Any, piece: Piece, *, uncertain: float) -> list[TranscriptSegment]:
        name, recording = self.audio.recording(samples)
        self.audio.reads.append((name, piece.start))
        if self.audio.hold == (name, piece.start):
            self.audio.reading.set()
            assert self.audio.release.wait(10)
        if name in self.audio.read_errors:
            raise RuntimeError("ONNXRuntimeError: bad allocation")
        return [
            TranscriptSegment(
                start=line.start,
                end=line.end,
                text=line.text,
                confidence=line.confidence,
                uncertain=line.confidence < uncertain,
            )
            for line in recording.lines
            if piece.start <= line.start < piece.end
        ]


class AtOnce:
    """Wraps a respond function and counts the requests answered at the same time: each one
    lingers a moment, so requests sent together overlap."""

    def __init__(self, respond: Callable[[Any], str], linger: float = 0.3) -> None:
        self.respond, self.linger = respond, linger
        self.lock = threading.Lock()
        self.now = self.most = 0

    def __call__(self, body: Any) -> str:
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
        try:
            time.sleep(self.linger)
            return self.respond(body)
        finally:
            with self.lock:
                self.now -= 1

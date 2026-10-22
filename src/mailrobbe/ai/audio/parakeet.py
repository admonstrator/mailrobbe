"""Parakeet TDT 0.6B v3 in the container (D290, D291, D293): its files and the Transcriber.

The model is NVIDIA's (CC-BY-4.0) in the int8 ONNX export of istupakov/parakeet-tdt-0.6b-v3-onnx,
read by onnx-asr on ONNX Runtime's CPU provider; Silero VAD (MIT) finds the speech. The files are
pinned to a revision and checked against their SHA-256: download_model fetches what is missing
into the model directory (resuming a cut download with a Range request, a file moved into place
only once its hash is right), model_state says what is there without reading the files through.

From the samples to the lines (D293), the two pure steps tested without the model:

    cut_pieces    Silero's speech, merged across pauses shorter than JOIN_SECONDS into stretches;
                  a stretch longer than PIECE_SECONDS is cut at the longest pause in the second
                  half of each window, so a piece holds whole sentences (and the model keeps the
                  language), and each piece is padded by PAD_SECONDS where the pauses allow it
    token_lines   the tokens of a piece with their times and log-probabilities, as lines: a line
                  ends after a word ending in ".", "?" or "!", before a pause longer than
                  PAUSE_SECONDS and before it would last longer than SEGMENT_SECONDS; its
                  confidence is the mean probability of its tokens. A line of nothing but
                  humming or hesitation (Mm-hmm, äh), which the model writes for tones and
                  noise Silero took for speech, is left out
"""

import contextlib
import hashlib
import http.client
import itertools
import math
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

import numpy as np
import numpy.typing as npt

from mailrobbe.ai.audio.decode import SAMPLE_RATE
from mailrobbe.ai.model import PIECE_SECONDS, SEGMENT_SECONDS, TranscriptSegment


@dataclass(frozen=True, slots=True)
class ModelFile:
    repository: str  # on Hugging Face
    revision: str  # the commit the file is pinned to
    name: str
    size: int
    sha256: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repository}/resolve/{self.revision}/{self.name}"


_PARAKEET = ("istupakov/parakeet-tdt-0.6b-v3-onnx", "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce")
_SILERO = ("istupakov/silero-vad-onnx", "b3e3ee3cce4c11ceb63b1a0b229d916069c1ddf6")
PARAKEET_DIR = "parakeet-tdt-0.6b-v3"  # below the model directory
SILERO_DIR = "silero-vad"
MODEL_FILES: dict[str, tuple[ModelFile, ...]] = {
    PARAKEET_DIR: (
        ModelFile(
            *_PARAKEET,
            "config.json",
            97,
            "666903c76b9798caf2c210afd4f6cd60b08a8dbf9800ec8d7a3bc0d2148ac466",
        ),
        ModelFile(
            *_PARAKEET,
            "vocab.txt",
            93_939,
            "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d",
        ),
        ModelFile(
            *_PARAKEET,
            "decoder_joint-model.int8.onnx",
            18_202_004,
            "eea7483ee3d1a30375daedc8ed83e3960c91b098812127a0d99d1c8977667a70",
        ),
        ModelFile(
            *_PARAKEET,
            "encoder-model.int8.onnx",
            652_183_999,
            "6139d2fa7e1b086097b277c7149725edbab89cc7c7ae64b23c741be4055aff09",
        ),
    ),
    SILERO_DIR: (
        ModelFile(
            *_SILERO,
            "config.json",
            30,
            "1094039d370c82889582ba739a3d1caac5754c8b3a17a66a534200c9f72086e2",
        ),
        ModelFile(
            *_SILERO,
            "silero_vad.onnx",
            2_327_524,
            "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
        ),
    ),
}
MODEL_BYTES = sum(file.size for files in MODEL_FILES.values() for file in files)

_CHUNK = 1024**2  # bytes read from the network at once
_ATTEMPTS = 3  # tries of a file whose transfer is cut after some bytes came


class ModelMissing(Exception):
    """The model files are not there and cannot be had (English, one line): no network, a wrong
    hash, a full disk."""


@dataclass(frozen=True, slots=True)
class ModelState:
    ready: bool  # every file present with its size (hashes are checked when downloaded)
    missing_bytes: int  # still to download
    total_bytes: int  # MODEL_BYTES


def model_state(model_dir: Path) -> ModelState:
    """What of the model is in model_dir, by the files' presence and sizes; the bytes of a cut
    download (a .part file) count as there."""
    missing = total = 0
    for directory, files in MODEL_FILES.items():
        for file in files:
            total += file.size
            path = model_dir / directory / file.name
            if _size(path) != file.size:
                missing += file.size - min(max(_size(_part(path)), 0), file.size)
    return ModelState(missing == 0, missing, total)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else -1
    except OSError:
        return -1


def _part(path: Path) -> Path:
    return path.with_name(f"{path.name}.part")


def download_model(
    model_dir: Path,
    *,
    progress: Callable[[int], None],
    stop: Event,
    timeout: float = 60.0,
) -> None:
    """Fetch the files model_dir lacks; progress gets each chunk's byte count as it arrives.
    Returns early, keeping what was fetched for the next run, once stop is set; ModelMissing
    when a file cannot be had."""
    for directory, files in MODEL_FILES.items():
        for file in files:
            path = model_dir / directory / file.name
            if _size(path) == file.size:
                continue
            for attempt in range(1, _ATTEMPTS + 1):
                if stop.is_set():
                    return
                try:
                    _fetch(file, path, progress, stop, timeout, model_dir)
                    break
                except _Cut as cut:
                    if not cut.received or attempt == _ATTEMPTS:
                        raise ModelMissing(_missing(model_dir, f"{file.name}: {cut}")) from None


class _Cut(Exception):
    """The transfer of a file failed on the network; received: bytes that came before."""

    def __init__(self, reason: str, received: int) -> None:
        super().__init__(reason)
        self.received = received


def _missing(model_dir: Path, reason: str) -> str:
    return f"{reason}; the model files can also be copied into {model_dir} by hand"


def _fetch(
    file: ModelFile,
    path: Path,
    progress: Callable[[int], None],
    stop: Event,
    timeout: float,
    model_dir: Path,
) -> None:
    """One try at a file: what its part holds is hashed again, the rest asked for with a Range
    request; once complete and right, the part becomes the file."""
    part = _part(path)
    digest = hashlib.sha256()
    have = _hashed(part, file.size, digest.update, model_dir)
    received = 0
    if have < file.size:
        writing = f"write {part}"
        _on_disk(lambda: part.parent.mkdir(parents=True, exist_ok=True), writing, model_dir)
        handle = _on_disk(lambda: part.open("ab", buffering=0), writing, model_dir)
        request = urllib.request.Request(file.url, headers={"Range": f"bytes={have}-"})
        try:
            with handle, urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 206:  # the whole file: start again
                    digest, have = hashlib.sha256(), 0
                    _on_disk(lambda: handle.truncate(0), writing, model_dir)
                while have <= file.size and not stop.is_set():
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    _on_disk(lambda: handle.write(chunk), writing, model_dir)  # noqa: B023
                    digest.update(chunk)
                    have += len(chunk)
                    received += len(chunk)
                    progress(len(chunk))
        except urllib.error.HTTPError as error:
            host = urlsplit(file.url).hostname
            raise ModelMissing(
                _missing(model_dir, f"{file.name}: {host} answered HTTP {error.code}")
            ) from None
        except (OSError, http.client.HTTPException) as error:
            raise _Cut(_reason(error), received) from None
        if have < file.size:
            if stop.is_set():
                return
            raise _Cut(f"the transfer ended after {have:,} of {file.size:,} bytes", received)
    if have != file.size or digest.hexdigest() != file.sha256:
        with contextlib.suppress(OSError):
            part.unlink()
        raise ModelMissing(_missing(model_dir, f"{file.name}: the download is not the pinned file"))
    _on_disk(lambda: os.replace(part, path), f"store {path}", model_dir)


def _hashed(part: Path, size: int, digest: Callable[[bytes], None], model_dir: Path) -> int:
    """The bytes a part holds, fed to digest; a part longer than its file is dropped."""
    try:
        if _size(part) > size:
            part.unlink()
        if _size(part) <= 0:
            return 0
        have = 0
        with part.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest(chunk)
                have += len(chunk)
        return have
    except OSError as error:
        raise ModelMissing(_missing(model_dir, f"cannot read {part}: {_reason(error)}")) from None


def _on_disk[T](action: Callable[[], T], what: str, model_dir: Path) -> T:
    """What action returns; ModelMissing when the disk refuses it (full, read-only, not a
    directory), which is no network error to try again."""
    try:
        return action()
    except OSError as error:
        raise ModelMissing(_missing(model_dir, f"cannot {what}: {_reason(error)}")) from None


def _reason(error: BaseException) -> str:
    if isinstance(error, urllib.error.URLError) and not isinstance(error.reason, str):
        error = error.reason  # the socket's error behind urllib's
    text = getattr(error, "strerror", None) or str(error) or type(error).__name__
    return " ".join(str(text).split())[:200]


@dataclass(frozen=True, slots=True)
class Piece:
    """A stretch of speech the transcriber reads at once, in seconds of the recording."""

    start: float
    end: float


JOIN_SECONDS = 1.0  # speech across shorter pauses stays in one stretch
PAD_SECONDS = 0.2  # of silence around a piece, where the pause allows
PAUSE_SECONDS = 0.8  # a longer pause between two words ends a line
_STEP = 0.24  # a line ends this long after its last token began (three encoder frames)
_SENTENCE_ENDS = (".", "?", "!")
_PUNCTUATION = ".,;:!?…\"'()"
# The model's vocabulary marks a word's start with a space (SentencePiece); onnx-asr joins its
# tokens this way: no space at the start or before punctuation.
_SPACES = re.compile(r"\A\s|\s\B|(\s)\b")
# What the model writes for humming, a hesitation or a tone that Silero took for speech (Mm,
# Mm-hmm, Hmm, äh, ähm): a line of nothing else is no line.
_FILLER = re.compile(r"[hm-]*m[hm-]*|[äöe]h+m*|u+h*m*", re.IGNORECASE)


def cut_pieces(
    speech: Sequence[tuple[float, float]],
    *,
    start: float = 0.0,
    end: float,
    limit: float = PIECE_SECONDS,
) -> list[Piece]:
    """The pieces the transcriber reads (module docstring): speech holds the stretches Silero
    found between start and end, in seconds and in order; no piece reaches beyond them."""
    width = limit - 2 * PAD_SECONDS
    cuts: list[tuple[float, float]] = []
    for run in _runs(speech):
        first, last = run[0][0], run[-1][1]
        while last - first > width:
            pauses = [
                (following[0] - previous[1], previous[1], following[0])
                for previous, following in itertools.pairwise(run)
                if first < previous[1] <= first + width
            ]
            later = [pause for pause in pauses if pause[1] >= first + width / 2]
            if pauses:
                _, before, after = max(later or pauses)
            else:  # no pause at all: cut in the speech
                before = after = first + width
            cuts.append((first, before))
            first = after
        cuts.append((first, last))
    pieces = []
    for index, (first, last) in enumerate(cuts):
        floor = cuts[index - 1][1] if index else start
        ceiling = cuts[index + 1][0] if index + 1 < len(cuts) else end
        before = min(PAD_SECONDS, (first - floor) / (2 if index else 1))
        after = min(PAD_SECONDS, (ceiling - last) / (2 if index + 1 < len(cuts) else 1))
        pieces.append(Piece(round(first - max(before, 0), 3), round(last + max(after, 0), 3)))
    return pieces


def _runs(speech: Sequence[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """The stretches of speech with pauses shorter than JOIN_SECONDS between them."""
    runs: list[list[tuple[float, float]]] = []
    for region in speech:
        if runs and region[0] - runs[-1][-1][1] < JOIN_SECONDS:
            runs[-1].append(region)
        else:
            runs.append([region])
    return runs


def token_lines(
    tokens: Sequence[str],
    times: Sequence[float],
    logprobs: Sequence[float] | None,
    *,
    piece: Piece,
    uncertain: float,
) -> list[TranscriptSegment]:
    """The lines of one piece (module docstring): tokens as the model wrote them (a word starts
    with a space), times in seconds of the piece, logprobs the natural log of each token's
    probability (None: no confidence). Times of the lines are seconds of the recording."""
    words: list[list[int]] = []
    for index, token in enumerate(tokens):
        if not words or token[:1].isspace():
            words.append([index])
        else:
            words[-1].append(index)
    groups: list[list[int]] = []
    for word in words:
        line = groups[-1] if groups else None
        if line is not None and (
            times[word[0]] - times[line[-1]] > PAUSE_SECONDS
            or times[word[-1]] + _STEP - times[line[0]] > SEGMENT_SECONDS
            or tokens[line[-1]].rstrip().endswith(_SENTENCE_ENDS)
        ):
            line = None
        if line is None:
            groups.append(list(word))
        else:
            line.extend(word)
    lines = []
    for number, group in enumerate(groups):
        text = _SPACES.sub(lambda m: " " if m.group(1) else "", "".join(tokens[i] for i in group))
        if all(_FILLER.fullmatch(word.strip(_PUNCTUATION)) for word in text.split()):
            continue  # also an empty text
        start = piece.start + times[group[0]]
        stop = piece.start + times[group[-1]] + _STEP
        if number + 1 < len(groups):
            stop = min(stop, piece.start + times[groups[number + 1][0]])
        confidence = None
        if logprobs is not None and len(logprobs) == len(tokens):
            confidence = round(sum(math.exp(logprobs[i]) for i in group) / len(group), 3)
        lines.append(
            TranscriptSegment(
                start=round(start, 2),
                end=round(max(min(stop, piece.end), start), 2),
                text=text.strip(),
                confidence=confidence,
                uncertain=confidence is not None and confidence < uncertain,
            )
        )
    return lines


class Transcriber:
    """Parakeet and Silero VAD, loaded once per run (about 1.3 GB of memory with four threads)."""

    def __init__(self, model_dir: Path, *, threads: int) -> None:
        """ModelMissing when the files are not all there (model_state)."""
        state = model_state(model_dir)
        if not state.ready:
            raise ModelMissing(
                _missing(model_dir, f"{state.missing_bytes:,} bytes of the model are missing")
            )
        import onnx_asr
        import onnxruntime
        from onnx_asr.vad import BaseVad

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False  # with it, memory grows with the longest piece
        providers = ["CPUExecutionProvider"]
        try:
            self._model = onnx_asr.load_model(
                "nemo-parakeet-tdt-0.6b-v3", model_dir / PARAKEET_DIR, quantization="int8",
                sess_options=options, providers=providers,
            ).with_timestamps()  # fmt: skip
            vad = onnx_asr.load_vad(
                "silero", model_dir / SILERO_DIR, sess_options=options, providers=providers
            )
        except Exception as error:  # damaged files of the right size, put there by hand
            reason = f"the model files cannot be loaded: {_reason(error)}"
            raise ModelMissing(_missing(model_dir, reason)) from None
        assert isinstance(vad, BaseVad)  # Silero's, with segment_batch
        self._vad = vad

    def pieces(self, samples: npt.NDArray[np.int16], *, start: float = 0.0) -> list[Piece]:
        """The speech in samples from start on (seconds), cut into pieces of at most
        PIECE_SECONDS at the longest pause; [] when nobody speaks."""
        first = max(0, int(start * SAMPLE_RATE))
        speech: list[tuple[float, float]] = []
        window = _VAD_WINDOW * SAMPLE_RATE
        for offset in range(first, len(samples), window):
            part = samples[offset : offset + window]
            waveform = _floats(part)
            found = next(
                self._vad.segment_batch(
                    waveform[None, :], np.array([len(waveform)], dtype=np.int64), SAMPLE_RATE,
                    **_VAD_OPTIONS,
                )
            )  # fmt: skip
            speech += [((offset + a) / SAMPLE_RATE, (offset + b) / SAMPLE_RATE) for a, b in found]
        return cut_pieces(speech, start=first / SAMPLE_RATE, end=len(samples) / SAMPLE_RATE)

    def read(
        self, samples: npt.NDArray[np.int16], piece: Piece, *, uncertain: float
    ) -> list[TranscriptSegment]:
        """The lines said in one piece, with times in seconds of the whole recording."""
        part = samples[int(piece.start * SAMPLE_RATE) : int(piece.end * SAMPLE_RATE)]
        if len(part) < _SHORTEST * SAMPLE_RATE:
            return []
        result = self._model.recognize(_floats(part), sample_rate=SAMPLE_RATE)
        if not result.tokens or result.timestamps is None:
            return []
        return token_lines(
            result.tokens, result.timestamps, result.logprobs, piece=piece, uncertain=uncertain
        )


def _floats(samples: npt.NDArray[np.int16]) -> npt.NDArray[np.float32]:
    waveform = samples.astype(np.float32)
    waveform /= 32768
    return waveform


_VAD_WINDOW = 600  # seconds of a recording Silero reads at once (38 MB of float samples)
# Silero's stretches of speech as they are: no padding, no cutting; cut_pieces does both.
_VAD_OPTIONS: dict[str, float] = {
    "min_speech_duration_ms": 250,
    "min_silence_duration_ms": 100,
    "speech_pad_ms": 0,
    "max_speech_duration_s": 10**6,
}
_SHORTEST = 0.1  # seconds; less is nothing to read

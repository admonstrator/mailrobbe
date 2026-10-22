"""Parakeet TDT 0.6B v3 in the container (D290, D291, D293): its files and the Transcriber.

The model is NVIDIA's (CC-BY-4.0) in the int8 ONNX export of istupakov/parakeet-tdt-0.6b-v3-onnx,
read by onnx-asr on ONNX Runtime's CPU provider; Silero VAD (MIT) finds the speech. The files are
pinned to a revision and checked against their SHA-256: download_model fetches what is missing
into the model directory (resuming a cut download with a Range request, a file moved into place
only once its hash is right), model_state says what is there without reading the files through.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import numpy as np
import numpy.typing as npt

from mailrobbe.ai.model import TranscriptSegment


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


class ModelMissing(Exception):
    """The model files are not there and cannot be had (English, one line): no network, a wrong
    hash, a full disk."""


@dataclass(frozen=True, slots=True)
class ModelState:
    ready: bool  # every file present with its size (hashes are checked when downloaded)
    missing_bytes: int  # still to download
    total_bytes: int  # MODEL_BYTES


def model_state(model_dir: Path) -> ModelState:
    """What of the model is in model_dir, by the files' presence and sizes."""
    raise NotImplementedError  # milestone 16, agent A


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
    raise NotImplementedError  # milestone 16, agent A


@dataclass(frozen=True, slots=True)
class Piece:
    """A stretch of speech the transcriber reads at once, in seconds of the recording."""

    start: float
    end: float


class Transcriber:
    """Parakeet and Silero VAD, loaded once per run (about 1.3 GB of memory with four threads)."""

    def __init__(self, model_dir: Path, *, threads: int) -> None:
        """ModelMissing when the files are not all there (model_state)."""
        raise NotImplementedError  # milestone 16, agent A

    def pieces(self, samples: npt.NDArray[np.int16], *, start: float = 0.0) -> list[Piece]:
        """The speech in samples from start on (seconds), cut into pieces of at most
        PIECE_SECONDS at the longest pause; [] when nobody speaks."""
        raise NotImplementedError

    def read(
        self, samples: npt.NDArray[np.int16], piece: Piece, *, uncertain: float
    ) -> list[TranscriptSegment]:
        """The lines said in one piece, with times in seconds of the whole recording."""
        raise NotImplementedError

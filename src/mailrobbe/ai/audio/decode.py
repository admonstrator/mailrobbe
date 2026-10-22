"""The sound of a recording, made in a process of its own (D292): the run's side (decode) and the
child's (main, run as python -m mailrobbe.ai.audio.decode).

Attachments may come from a hostile organisation, so the original is opened only here, as
ai.ocr.render opens a scan: a fresh interpreter in a session of its own with the file on stdin,
limited in address space, CPU time and file size. PyAV (FFmpeg's libraries) decodes the first
audio stream of an audio or video file, mixes it to mono and resamples it to SAMPLE_RATE; out
come 16-bit PCM samples and nothing else. A file without an audio stream is no error: it has no
sound (Decoded.audio False).
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

SAMPLE_RATE = 16_000  # what the transcriber reads


class DecodeError(Exception):
    """The recording gives no sound: damaged, unsupported, a time or memory limit (English, one
    line)."""


@dataclass(frozen=True, slots=True)
class Decoded:
    samples: npt.NDArray[np.int16]  # mono at SAMPLE_RATE, at most max_seconds of it
    duration: float | None  # of the whole recording in seconds; None when not known
    audio: bool  # False: the file has no audio stream, samples is empty


def decode(data: bytes, *, timeout: float, memory: int, max_seconds: float) -> Decoded:
    """The first max_seconds of the recording's sound; DecodeError when there is none to be had.

    The child is killed with its whole session after timeout seconds; memory is the address
    space it may take beyond its size."""
    raise NotImplementedError  # milestone 16, agent A

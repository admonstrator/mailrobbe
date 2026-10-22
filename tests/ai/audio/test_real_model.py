"""ai.audio with the real model (D290 to D293, D297): the committed speech is heard with its
marker and words, the tones give no lines. Runs only where MAILROBBE_TEST_MODEL_DIR names a
directory holding the model files (parakeet.MODEL_FILES, as download_model puts them)."""

import itertools
import os
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from mailrobbe.ai.audio.decode import SAMPLE_RATE, decode
from mailrobbe.ai.audio.parakeet import Piece, Transcriber, model_state
from mailrobbe.ai.model import PIECE_SECONDS, TranscriptSegment, transcript_text
from mailrobbe.generator import documents
from mailrobbe.generator import fileformats as ff

MODEL_DIR = Path(os.environ.get("MAILROBBE_TEST_MODEL_DIR") or "/nonexistent")
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not model_state(MODEL_DIR).ready, reason="MAILROBBE_TEST_MODEL_DIR names no model"
    ),
]
SPOKEN = [spoken for files in documents.SPOKEN.values() for spoken in files]
TONES = [
    f"{form}-{number}.{form}"
    for form, (_, count) in documents.RECORDING_FORMS.items()
    for number in range(1, count + 1)
]


@pytest.fixture(scope="module")
def transcriber() -> Transcriber:
    return Transcriber(MODEL_DIR, threads=4)


def sound(name: str) -> npt.NDArray[np.int16]:
    return decode(ff.fixture(name), timeout=60, memory=1024**3, max_seconds=600).samples


def transcribe(
    transcriber: Transcriber, samples: npt.NDArray[np.int16], start: float = 0.0
) -> tuple[list[Piece], list[TranscriptSegment]]:
    pieces = transcriber.pieces(samples, start=start)
    lines = [line for piece in pieces for line in transcriber.read(samples, piece, uncertain=0.5)]
    return pieces, lines


@pytest.mark.parametrize("spoken", SPOKEN, ids=lambda spoken: spoken.file)
def test_the_committed_speech_is_heard_with_its_marker_and_words(
    transcriber: Transcriber, spoken: documents.Spoken
) -> None:
    samples = sound(spoken.file)
    pieces, lines = transcribe(transcriber, samples)
    text, _ = transcript_text(lines)
    assert len(pieces) == 1  # 12 to 14 s with short pauses
    assert spoken.marker in text and all(word in text for word in spoken.words), text
    assert 3 <= len(lines) <= 6 and not any(line.uncertain for line in lines), lines
    assert all(0 <= line.start < line.end <= len(samples) / SAMPLE_RATE for line in lines)
    assert all(a.end <= b.start for a, b in itertools.pairwise(lines))


@pytest.mark.parametrize("name", TONES)
def test_tones_give_no_lines(transcriber: Transcriber, name: str) -> None:
    assert transcribe(transcriber, sound(name))[1] == []


def test_a_long_recording_is_read_in_pieces_and_from_where_it_stopped(
    transcriber: Transcriber,
) -> None:
    pause = np.zeros(int(1.5 * SAMPLE_RATE), np.int16)
    samples = np.concatenate([part for s in SPOKEN for part in (sound(s.file), pause)])
    pieces, lines = transcribe(transcriber, samples)
    assert len(pieces) == len(SPOKEN)
    assert all(piece.end - piece.start <= PIECE_SECONDS + 1e-3 for piece in pieces)
    text, _ = transcript_text(lines)
    assert all(spoken.marker in text for spoken in SPOKEN), text
    later = pieces[2].start
    rest, rest_lines = transcribe(transcriber, samples, start=later)
    assert len(rest) == len(SPOKEN) - 2 and rest[0].start >= later
    assert all(line.start >= later for line in rest_lines)
    text, _ = transcript_text(rest_lines)
    assert all(spoken.marker in text for spoken in SPOKEN[2:])
    assert not any(spoken.marker in text for spoken in SPOKEN[:2])

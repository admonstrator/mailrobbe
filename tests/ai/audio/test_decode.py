"""ai.audio.decode: the sound of a recording, made in a child process with limits (D292)."""

import io
import json
import sys

import av
import numpy as np
import pytest

from mailrobbe.ai.audio.decode import SAMPLE_RATE, DecodeError, _parse, decode
from mailrobbe.generator import documents
from mailrobbe.generator import fileformats as ff

MEMORY = 1024**3
RECORDINGS = [
    *(
        f"{form}-{number}.{form}"
        for form, (_, count) in documents.RECORDING_FORMS.items()
        for number in range(1, count + 1)
    ),
    *(spoken.file for files in documents.SPOKEN.values() for spoken in files),
]


def silent_video() -> bytes:
    """Two seconds of an MPEG-4 picture in MP4, without an audio stream."""
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as container:
        stream = container.add_stream("mpeg4", rate=5)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for _ in range(10):
            frame = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), np.uint8), format="rgb24")
            container.mux(stream.encode(frame))
        container.mux(stream.encode())
    return out.getvalue()


@pytest.mark.parametrize("name", RECORDINGS)
def test_every_committed_recording_decodes(name: str) -> None:
    decoded = decode(ff.fixture(name), timeout=60, memory=MEMORY, max_seconds=600)
    assert decoded.audio and decoded.samples.dtype == np.int16 and decoded.samples.ndim == 1
    assert decoded.duration is not None
    assert abs(len(decoded.samples) / SAMPLE_RATE - decoded.duration) < 0.15
    assert 0.9 < decoded.duration < (25 if name.startswith("spoken") else 4)
    assert np.abs(decoded.samples).max() > 2000  # sound, not silence


def test_max_seconds_cuts_the_sound_and_keeps_the_duration() -> None:
    decoded = decode(ff.fixture("spoken-1.ogg"), timeout=60, memory=MEMORY, max_seconds=3)
    assert len(decoded.samples) == 3 * SAMPLE_RATE
    assert decoded.duration == pytest.approx(14.08, abs=0.01)
    whole = decode(ff.fixture("spoken-1.ogg"), timeout=60, memory=MEMORY, max_seconds=600)
    assert np.array_equal(decoded.samples, whole.samples[: 3 * SAMPLE_RATE])


def test_a_video_without_sound_has_no_audio() -> None:
    decoded = decode(silent_video(), timeout=60, memory=MEMORY, max_seconds=600)
    assert not decoded.audio and len(decoded.samples) == 0
    assert decoded.duration == pytest.approx(2.0, abs=0.3)
    picture = decode(ff.fixture("jpeg-1.jpeg"), timeout=60, memory=MEMORY, max_seconds=600)
    assert not picture.audio and len(picture.samples) == 0  # FFmpeg reads pictures too


def test_a_cut_recording_gives_the_sound_up_to_the_cut() -> None:
    data = ff.fixture("spoken-2.mp3")
    decoded = decode(data[: len(data) // 2], timeout=60, memory=MEMORY, max_seconds=600)
    assert decoded.audio and 5 < len(decoded.samples) / SAMPLE_RATE < 8


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"garbage " * 2000,
        bytes(range(256)) * 50,
        ff.fixture("m4a-1.m4a")[:400],  # cut inside its index
        b"ffconcat version 1.0\nfile /etc/passwd\n",  # a playlist naming another file
    ],
)
def test_what_is_no_recording_raises_decode_error(data: bytes) -> None:
    with pytest.raises(DecodeError, match=r"not a recording|damaged recording"):
        decode(data, timeout=60, memory=MEMORY, max_seconds=600)


def test_the_time_limit_ends_the_child() -> None:
    with pytest.raises(DecodeError, match=r"time limit of 0\.001 s"):
        decode(ff.fixture("spoken-1.ogg"), timeout=0.001, memory=MEMORY, max_seconds=600)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="RLIMIT_AS is Linux only")
def test_the_memory_limit_ends_the_child() -> None:
    padded = ff.fixture("spoken-1.ogg") + bytes(16 * 1024**2)  # more than it may hold
    with pytest.raises(DecodeError, match="memory limit of 4 MiB exceeded"):
        decode(padded, timeout=60, memory=4 * 1024**2, max_seconds=600)


def test_a_duration_nobody_tells_is_the_length_read_to_the_end() -> None:
    def output(duration: float | None, seconds: float) -> bytes:
        meta = json.dumps({"audio": True, "duration": duration}).encode()
        pcm = np.ones(int(seconds * SAMPLE_RATE), np.int16).tobytes()
        return b"ok\n" + meta + (b"\n" if len(meta) % 2 == 0 else b" \n") + pcm

    assert _parse(output(None, 2.5), 3, max_seconds=60).duration == 2.5
    assert _parse(output(None, 2.0), 3, max_seconds=2).duration is None  # cut: not the end
    assert _parse(output(7.0, 2.0), 3, max_seconds=2).duration == 7.0

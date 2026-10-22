"""The sound of a recording, made in a process of its own (D292): the run's side (decode) and the
child's (main, run as python -m mailrobbe.ai.audio.decode).

Attachments may come from a hostile organisation, so the original is opened only here, as
ai.ocr.render opens a scan: a fresh interpreter (-I -B, an environment of only PATH and the
locale) in a session of its own with the file on stdin. The child imports PyAV and numpy, then
limits itself (address space to its size plus `memory` on Linux, CPU time to the time limit plus
a grace, no core dumps, no file it may write) before it reads the file. PyAV (FFmpeg's libraries)
opens any container it knows from memory, never a second file or URL the container names (an
HLS or concat playlist), decodes the first audio stream (packets FFmpeg cannot decode are skipped,
as its command line does), mixes it to mono and resamples it to SAMPLE_RATE 16-bit PCM, and stops
after max_seconds. A file without an audio stream is no error: it has no sound (Decoded.audio
False).

The child writes a status line to stdout: "ok" with a JSON line of audio and duration (the audio
stream's or the container's, null when neither says), then the PCM as it decodes; or "failed"
and the reason. Once the first samples are out, a later error ends the sound there. The parent
kills the child's whole session after `timeout` seconds and always waits for it; DecodeError says
why a recording gives no sound. Only these samples ever reach the transcriber.

The child imports nothing of mailrobbe but this module (the database models alone take most of a
second to import).
"""

import contextlib
import io
import json
import math
import os
import resource
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import IO, Any, Final

import numpy as np
import numpy.typing as npt

SAMPLE_RATE: Final = 16_000  # what the transcriber reads

_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
_OK, _FAILED = b"ok", b"failed"
_MEMORY_EXIT = 71  # the child ran out of memory
_CPU_GRACE = 10  # CPU seconds beyond the time limit before the kernel stops a child
_BATCH = SAMPLE_RATE  # samples the child collects before it writes them


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
    space it may take beyond its size. The samples are read-only, a view of the child's output.
    When neither the stream nor the container tells the duration, it is the length decoded,
    provided the child read to the end (less than max_seconds came)."""
    command = [
        sys.executable, "-I", "-B", "-m", "mailrobbe.ai.audio.decode",
        repr(float(timeout)), str(memory), repr(float(max_seconds)),
    ]  # fmt: skip
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={key: os.environ[key] for key in _ENVIRONMENT if key in os.environ},
        close_fds=True,
        start_new_session=True,
    )
    try:
        output, errors = process.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(process)
        process.communicate()
        raise DecodeError(f"decoding stopped after the time limit of {timeout:g} s") from None
    finally:
        if process.returncode is None:  # interrupted: no child may outlive this
            _kill(process)
            process.wait()
    status_end = output.find(b"\n")
    status = output[:status_end] if status_end >= 0 else output
    if process.returncode == 0 and status == _OK:
        return _parse(output, status_end + 1, max_seconds)
    if process.returncode == 0 and status == _FAILED:
        raise DecodeError(output[status_end + 1 :].decode("utf-8", "replace"))
    raise DecodeError(_death(process.returncode, errors, memory))


def _kill(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)


def _parse(output: bytes, start: int, max_seconds: float) -> Decoded:
    end = output.index(b"\n", start)
    meta = json.loads(output[start:end])
    samples = np.frombuffer(output, dtype=np.int16, offset=end + 1)  # no copy of the PCM
    duration = meta["duration"]
    if duration is None and meta["audio"] and len(samples) < int(max_seconds * SAMPLE_RATE):
        duration = len(samples) / SAMPLE_RATE  # read to the end
    return Decoded(samples, duration, bool(meta["audio"]))


def _death(code: int, errors: bytes, memory: int) -> str:
    if code == _MEMORY_EXIT:
        return f"memory limit of {memory // 1024**2} MiB exceeded"
    if code == -signal.SIGXCPU:
        return "decoding stopped at its CPU time limit"
    if code == -signal.SIGKILL:
        return "decoding process killed, probably out of memory"
    lines = errors.decode("utf-8", "replace").strip().splitlines()
    detail = f": {lines[-1][:200]}" if lines else ""
    return f"decoding process ended with exit code {code}{detail}"


# Child side


class _Failed(Exception):
    """Why the child gives no sound; becomes its "failed" line."""


def main(argv: list[str]) -> int:
    """The child: TIMEOUT MEMORY MAX_SECONDS as arguments, the file on stdin."""
    timeout, memory, max_seconds = float(argv[0]), int(argv[1]), float(argv[2])
    import av  # before the limits: its libraries are part of the child's size

    _confine(timeout, memory)
    out = sys.stdout.buffer
    try:
        _decode(av, sys.stdin.buffer.read(), max_seconds, out)
    except MemoryError:
        return _MEMORY_EXIT
    except _Failed as error:
        out.write(_FAILED + b"\n" + str(error).encode())
    out.flush()
    return 0


def _confine(timeout: float, memory: int) -> None:
    """The limits of ai.ocr.render, with no file to write."""
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    _set_limit(resource.RLIMIT_CORE, 0)
    _set_limit(resource.RLIMIT_FSIZE, 0)
    _set_limit(resource.RLIMIT_CPU, math.ceil(timeout) + _CPU_GRACE)
    try:
        with open("/proc/self/statm", "rb") as handle:
            size = int(handle.read().split()[0]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):  # not Linux: no memory limit
        return
    _set_limit(resource.RLIMIT_AS, size + memory)


def _set_limit(which: int, value: int) -> None:
    try:
        _, hard = resource.getrlimit(which)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(which, (value, value))
    except (ValueError, OSError):
        pass


def _refuse(url: str, flags: int, options: dict[str, Any]) -> None:
    raise OSError("a recording may not open other files")


def _decode(av: Any, data: bytes, max_seconds: float, out: IO[bytes]) -> None:
    """Writes the status line and the sound of data to out; _Failed before anything is out."""
    try:
        container = av.open(io.BytesIO(data), "r", io_open=_refuse)
    except (av.FFmpegError, OSError, UnicodeDecodeError) as error:
        raise _Failed(f"not a recording FFmpeg can read: {_reason(error)}") from None
    with container:
        streams = container.streams.audio
        stream = streams[0] if streams else None
        duration = _duration(container, stream)
        meta = json.dumps({"audio": stream is not None, "duration": duration}).encode()
        header = _OK + b"\n" + meta + b"\n"
        if len(header) % 2:  # the samples start at an even offset, so the parent's view aligns
            header = _OK + b"\n" + meta + b" \n"
        if stream is None:
            out.write(header)
            return
        _sound(av, container, stream, max(0, int(max_seconds * SAMPLE_RATE)), header, out)


def _sound(av: Any, container: Any, stream: Any, limit: int, header: bytes, out: IO[bytes]) -> None:
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    pending: list[npt.NDArray[np.int16]] = []
    held = written = 0
    error: Exception | None = None

    def emit(frames: list[Any]) -> None:
        nonlocal held
        for frame in frames:
            pcm = frame.to_ndarray().reshape(-1)[: limit - written - held]
            pending.append(pcm)
            held += len(pcm)

    def flush() -> None:
        nonlocal held, written, header
        if not pending:
            return
        if header:
            out.write(header)
            header = b""
        out.write(np.concatenate(pending).tobytes())
        written += held
        pending.clear()
        held = 0

    try:
        for packet in container.demux(stream):
            try:
                frames = packet.decode()
            except av.FFmpegError as failed:  # a damaged packet: skipped
                error = failed
                continue
            for frame in frames:
                emit(resampler.resample(frame))
            if held >= _BATCH:
                flush()
            if written + held >= limit:
                break
        else:
            emit(resampler.resample(None))
    except av.FFmpegError as failed:  # the container breaks off: the sound ends here
        error = failed
    flush()
    if header:  # nothing decoded
        if error is not None:
            raise _Failed(f"damaged recording: {_reason(error)}")
        out.write(header)


def _duration(container: Any, stream: Any) -> float | None:
    """The audio stream's duration in seconds, else the container's; None when unknown."""
    if stream is not None and stream.duration is not None and stream.time_base is not None:
        seconds = float(stream.duration * stream.time_base)
        if seconds > 0:
            return round(seconds, 3)
    if container.duration is not None and container.duration > 0:
        return round(float(container.duration) / 1_000_000, 3)
    return None


def _reason(error: Exception) -> str:
    text = getattr(error, "strerror", None) or str(error)
    return " ".join(str(text).split())[:200] or type(error).__name__


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

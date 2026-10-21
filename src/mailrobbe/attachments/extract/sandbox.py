"""Running one extraction in a child process with a time and a memory limit (D72).

One malicious or broken attachment among 100,000 must neither stop the import nor eat the
memory of the machine. run() forks a child per document; the child limits its address space to
what it has plus `memory` bytes (RLIMIT_AS, Linux), runs the extractor and streams the text
through a pipe as the extractor produces it (frames: text pieces, the page count, the result).
The parent reads until the child is done or the time limit passes; then it kills the child
(SIGKILL), keeps the text that arrived and reports timeout. A child that dies otherwise (memory
limit, crash) ends as failed with its reason. The parent always reaps the child, also when it is
interrupted itself.

Assumptions about the caller: fork copies only the calling thread, so the process must not run
other threads that may hold locks (the attachments phase runs extract_document in spawned worker
processes without threads). The child stays in the caller's process group, so killing that group
kills it too. It dies with its parent (PR_SET_PDEATHSIG on Linux), ignores SIGINT (the parent
decides when to stop), and has a CPU time limit and no core dumps as a backstop. Where os.fork
is missing, run_inline runs the extractor in the calling process: with the time limit checked
between lines, without a memory limit.

Heavy modules (pypdf) are imported by the extractor modules at import time, so a fork costs
only the copy of the page tables.

call() runs a function that returns a value instead of text (the metadata readers, D167) in the
same kind of child: its JSON comes back whole as one frame, or the call ends as an error.
"""

import contextlib
import ctypes
import json
import math
import os
import resource
import select
import signal
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mailrobbe.attachments.extract.base import (
    Damaged,
    DeadlineExceeded,
    Encrypted,
    Full,
    Sink,
    one_line,
    reason,
)
from mailrobbe.enums import DocumentTextStatus

Job = Callable[[Sink], DocumentTextStatus | None]

_FRAME = struct.Struct(">cI")  # kind, payload length
_TEXT, _PAGES, _RESULT = b"T", b"P", b"R"
_READ_SIZE = 1 << 16
_CPU_GRACE = 10  # CPU seconds beyond the time limit before the kernel stops a child
_FAILED_EXIT = 70  # the child could not even report its failure
_MEMORY_EXIT = 71  # ... because the memory limit was reached

_PR_SET_PDEATHSIG = 1


def _load_prctl() -> Callable[..., int] | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        prctl: Callable[..., int] = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return None
    return prctl


_PRCTL = _load_prctl()


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one extraction produced; text only for text and timeout."""

    status: DocumentTextStatus
    text: str = ""
    truncated: bool = False
    pages: int | None = None
    error: str | None = None


def run(job: Job, *, timeout: float, memory: int, max_chars: int) -> Outcome:
    """Run job(sink) in a child process; see the module docstring."""
    if not hasattr(os, "fork"):
        return run_inline(job, timeout=timeout, max_chars=max_chars)
    read_fd, write_fd = os.pipe()
    parent = os.getpid()
    pid = os.fork()
    if pid == 0:  # the child never returns from here
        os.close(read_fd)
        _child(job, write_fd, parent, timeout, memory, max_chars)
    os.close(write_fd)
    frames = _Frames()
    timed_out = False
    reaped = False
    try:
        timed_out = not _read_until_done(read_fd, frames, time.monotonic() + timeout)
        if timed_out:
            _kill(pid)
        _, wait_status = os.waitpid(pid, 0)
        reaped = True
    finally:
        os.close(read_fd)
        if not reaped:  # interrupted (KeyboardInterrupt, a stop): no child may outlive this
            _kill(pid)
            os.waitpid(pid, 0)
    text = "".join(frames.text)[:max_chars]
    if timed_out:
        error = f"stopped after the time limit of {timeout:g} s"
        return Outcome(DocumentTextStatus.TIMEOUT, text, True, frames.pages, error)
    if frames.result is None:
        return Outcome(DocumentTextStatus.FAILED, pages=frames.pages, error=_death(wait_status))
    status = DocumentTextStatus(frames.result["status"])
    keep = status in (DocumentTextStatus.TEXT, DocumentTextStatus.TIMEOUT)
    return Outcome(
        status,
        text if keep else "",
        bool(frames.result["truncated"]) and keep,
        frames.result["pages"],
        frames.result["error"],
    )


@dataclass(frozen=True, slots=True)
class Called:
    """What call() gave: the function's value, or why there is none (English, one line)."""

    value: Any = None
    error: str | None = None


def call(function: Callable[[], Any], *, timeout: float, memory: int) -> Called:
    """function() in a child process with the limits of run(); its value must be JSON. An
    exception, the time limit or the child's death is an error, never raised."""
    if not hasattr(os, "fork"):
        try:
            return Called(json.loads(json.dumps(function())))
        except Exception as error:
            return Called(error=reason(error))
    read_fd, write_fd = os.pipe()
    parent = os.getpid()
    pid = os.fork()
    if pid == 0:  # the child never returns from here
        os.close(read_fd)
        _call_child(function, write_fd, parent, timeout, memory)
    os.close(write_fd)
    frames = _Frames()
    reaped = False
    try:
        finished = _read_until_done(read_fd, frames, time.monotonic() + timeout)
        if not finished:
            _kill(pid)
        _, wait_status = os.waitpid(pid, 0)
        reaped = True
    finally:
        os.close(read_fd)
        if not reaped:
            _kill(pid)
            os.waitpid(pid, 0)
    if not finished:
        return Called(error=f"stopped after the time limit of {timeout:g} s")
    if frames.result is None:
        return Called(error=_death(wait_status))
    return Called(frames.result.get("value"), frames.result.get("error"))


def _call_child(
    function: Callable[[], Any], fd: int, parent: int, timeout: float, memory: int
) -> None:
    """Body of call()'s child process; ends it with os._exit and never returns."""
    code = _FAILED_EXIT
    try:
        _confine(parent, timeout, memory)
        try:
            result: dict[str, Any] = {"value": function()}
        except MemoryError:
            raise
        except RecursionError:
            result = {"error": "structure nested too deeply"}
        except Exception as error:
            result = {"error": reason(error)}
        _Writer(fd).send(_RESULT, json.dumps(result).encode())
        code = 0
    except MemoryError:
        code = _MEMORY_EXIT
    except BaseException:
        pass  # the parent reports the exit code
    finally:
        os._exit(code)


def run_inline(job: Job, *, timeout: float, max_chars: int) -> Outcome:
    """Run job(sink) in this process, with the time limit checked between lines."""
    sink = Sink(max_chars, deadline=time.monotonic() + timeout)
    try:
        status, error = execute(job, sink)
    except DeadlineExceeded:
        error = f"stopped after the time limit of {timeout:g} s"
        return Outcome(DocumentTextStatus.TIMEOUT, sink.collected, True, sink.pages, error)
    keep = status is DocumentTextStatus.TEXT
    text = sink.collected if keep else ""
    return Outcome(status, text, sink.truncated and keep, sink.pages, error)


def execute(job: Job, sink: Sink) -> tuple[DocumentTextStatus, str | None]:
    """Run the extractor and turn how it ended into a status and a reason."""
    try:
        status = job(sink)
    except Full:
        status = None
    except Encrypted:
        return DocumentTextStatus.ENCRYPTED, None
    except Damaged as error:
        return DocumentTextStatus.FAILED, one_line(str(error)) or "damaged file"
    except DeadlineExceeded:
        raise
    except MemoryError:
        return DocumentTextStatus.FAILED, "memory limit exceeded"
    except RecursionError:
        return DocumentTextStatus.FAILED, "structure nested too deeply"
    except Exception as error:
        return DocumentTextStatus.FAILED, reason(error)
    sink.flush()
    if status is None:
        status = DocumentTextStatus.TEXT if sink.has_text else DocumentTextStatus.EMPTY
    return status, None


# Parent side


class _Frames:
    """Reassembles the frames the child writes into the pipe."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.text: list[str] = []
        self.pages: int | None = None
        self.result: dict[str, Any] | None = None

    def feed(self, data: bytes) -> None:
        buffer = self._buffer
        buffer += data
        while len(buffer) >= _FRAME.size:
            kind, length = _FRAME.unpack_from(buffer)
            end = _FRAME.size + length
            if len(buffer) < end:
                return
            payload = bytes(buffer[_FRAME.size : end])
            del buffer[:end]
            if kind == _TEXT:
                self.text.append(payload.decode("utf-8", "replace"))
            elif kind == _PAGES:
                self.pages = int(payload)
            elif kind == _RESULT:
                self.result = json.loads(payload)


def _read_until_done(fd: int, frames: _Frames, deadline: float) -> bool:
    """Read frames until the child closes the pipe; False when the deadline passed first."""
    poller = select.poll()
    poller.register(fd, select.POLLIN | select.POLLHUP)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if not poller.poll(math.ceil(remaining * 1000)):
            continue
        data = os.read(fd, _READ_SIZE)
        if not data:
            return True
        frames.feed(data)


def _kill(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def _death(wait_status: int) -> str:
    """Why a child ended without reporting a result."""
    if os.WIFSIGNALED(wait_status):
        number = os.WTERMSIG(wait_status)
        try:
            name = signal.Signals(number).name
        except ValueError:
            name = f"signal {number}"
        if number == signal.SIGKILL:
            return f"extraction process killed ({name}), probably out of memory"
        if number == getattr(signal, "SIGXCPU", None):
            return "extraction process stopped at its CPU time limit"
        return f"extraction process killed by {name}"
    code = os.waitstatus_to_exitcode(wait_status)
    if code == _MEMORY_EXIT:
        return "memory limit exceeded"
    return f"extraction process ended without a result (exit code {code})"


# Child side


def _child(job: Job, fd: int, parent: int, timeout: float, memory: int, max_chars: int) -> None:
    """Body of the child process; ends it with os._exit and never returns."""
    code = _FAILED_EXIT
    try:
        _confine(parent, timeout, memory)
        writer = _Writer(fd)
        sink = Sink(max_chars, emit=writer.text, on_pages=writer.pages)
        status, error = execute(job, sink)
        result = {
            "status": status.value,
            "error": error,
            "pages": sink.pages,
            "truncated": sink.truncated,
        }
        writer.send(_RESULT, json.dumps(result).encode())
        code = 0
    except MemoryError:
        code = _MEMORY_EXIT
    except BaseException:
        pass  # the parent reports the exit code
    finally:
        os._exit(code)


def _confine(parent: int, timeout: float, memory: int) -> None:
    """Limits and signals of the child process."""
    with contextlib.suppress(ValueError):  # only possible in the main thread
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
    if _PRCTL is not None:
        args = (signal.SIGKILL, 0, 0, 0)
        _PRCTL(_PR_SET_PDEATHSIG, *(ctypes.c_ulong(arg) for arg in args))
    if os.getppid() != parent:  # the parent died before the line above took effect
        os._exit(_FAILED_EXIT)
    _set_limit(resource.RLIMIT_CORE, 0)
    _set_limit(resource.RLIMIT_CPU, math.ceil(timeout) + _CPU_GRACE)
    size = _address_space()
    if size is not None:
        _set_limit(resource.RLIMIT_AS, size + memory)


def _set_limit(which: int, value: int) -> None:
    """Lower a limit, the hard one with the soft one so that the child cannot raise it again;
    quietly nothing where unsupported."""
    try:
        _, hard = resource.getrlimit(which)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(which, (value, value))
    except (ValueError, OSError):
        pass


def _address_space() -> int | None:
    """The process's current address space in bytes (Linux), else None."""
    try:
        with open("/proc/self/statm", "rb") as handle:
            pages = int(handle.read().split()[0])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


class _Writer:
    """Writes frames into the pipe to the parent."""

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def text(self, piece: str) -> None:
        self.send(_TEXT, piece.encode("utf-8", "replace"))

    def pages(self, count: int) -> None:
        self.send(_PAGES, str(count).encode())

    def send(self, kind: bytes, payload: bytes) -> None:
        data = memoryview(_FRAME.pack(kind, len(payload)) + payload)
        while data:
            written = os.write(self._fd, data)
            data = data[written:]

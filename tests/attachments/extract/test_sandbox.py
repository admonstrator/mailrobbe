"""The child process of the text extraction (D72): time and memory limits, crashes, partial
text, and no child left behind, also when the caller is interrupted or killed."""

import faulthandler
import multiprocessing
import os
import signal
import sys
import time
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from types import FrameType

import pytest

from mailrobbe.attachments import extract as extraction
from mailrobbe.attachments.extract import ExtractionLimits, extract_document, sandbox
from mailrobbe.attachments.extract.base import Damaged, Encrypted, Sink
from mailrobbe.enums import DocumentTextStatus

pytestmark = pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
MiB = 1024**2


def run(
    job: sandbox.Job, timeout: float = 20, memory: int = 512 * MiB, chars: int = 10_000
) -> sandbox.Outcome:
    return sandbox.run(job, timeout=timeout, memory=memory, max_chars=chars)


def _alive(pid: int) -> bool:
    """Whether the process exists and is no zombie."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state not in ("Z", "X")


def _wait_gone(pid: int, seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.02)
    return False


def _pid_from(path: Path, seconds: float = 10) -> int:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and (text := path.read_text()).endswith("\n"):
            return int(text)
        time.sleep(0.02)
    raise AssertionError("the extraction process did not start")


# Jobs (they run in the child)


def _pages_then_sleep(pid_file: Path | None, sink: Sink) -> DocumentTextStatus | None:
    sink.set_pages(3)
    sink.line("Seite 1")
    sink.block()
    sink.line("Seite 2")
    sink.block()
    sink.line("Seite 3, nie gesendet")  # still in the sink's buffer at the time limit
    if pid_file is not None:
        pid_file.write_text(f"{os.getpid()}\n")
    time.sleep(120)
    return None


def _write_pid(pid_file: Path, sink: Sink) -> DocumentTextStatus | None:
    pid_file.write_text(f"{os.getpid()}\n")
    time.sleep(120)
    return None


def _allocate(sink: Sink) -> DocumentTextStatus | None:
    sink.line("vorher")
    sink.block()
    blocks = [bytearray(16 * MiB) for _ in range(256)]  # 4 GiB
    sink.line(str(len(blocks)))
    return None


def _segfault(sink: Sink) -> DocumentTextStatus | None:
    sink.set_pages(7)
    faulthandler.disable()  # pytest's traceback dump would only clutter the output
    os.kill(os.getpid(), signal.SIGSEGV)
    return None


def _exit(sink: Sink) -> DocumentTextStatus | None:
    os._exit(3)


def _raise(error: BaseException, sink: Sink) -> DocumentTextStatus | None:
    sink.line("Text vor dem Fehler")
    raise error


def _many_lines(sink: Sink) -> DocumentTextStatus | None:
    for number in range(100_000):
        sink.line(f"Zeile {number}")
    return None


def _scanned(sink: Sink) -> DocumentTextStatus | None:
    sink.set_pages(2)
    sink.line("nicht behalten")
    return DocumentTextStatus.SCANNED


def _process_group(path: Path, sink: Sink, pid: bool = False) -> DocumentTextStatus | None:
    path.write_text(f"{os.getpid() if pid else os.getpgrp()}\n")
    return None


def _slow_lines(sink: Sink) -> DocumentTextStatus | None:
    for number in range(1000):
        sink.line(f"Zeile {number}")
        time.sleep(0.01)
    return None


# Tests


def test_time_limit_keeps_the_text_of_finished_pages(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    started = time.monotonic()
    outcome = run(partial(_pages_then_sleep, pid_file), timeout=1.0)
    elapsed = time.monotonic() - started
    assert outcome.status is DocumentTextStatus.TIMEOUT
    assert (outcome.text, outcome.pages, outcome.truncated) == ("Seite 1\n\nSeite 2", 3, True)
    assert outcome.error == "stopped after the time limit of 1 s"
    assert 1.0 <= elapsed < 3
    assert _reaped(_pid_from(pid_file))  # killed and waited for


def test_a_slow_extractor_behind_extract_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        extraction.EXTRACTORS, "text", lambda data, sink: _pages_then_sleep(None, sink)
    )
    result = extract_document(b"egal", "a.txt", "text/plain", ExtractionLimits(timeout=0.5))
    assert (result.status, result.text, result.pages) == (
        DocumentTextStatus.TIMEOUT, "Seite 1\n\nSeite 2", 3
    )  # fmt: skip
    assert result.truncated and result.error == "stopped after the time limit of 0.5 s"


def test_memory_limit_fails_the_document_not_the_caller() -> None:
    outcome = run(_allocate, memory=256 * MiB)
    assert (outcome.status, outcome.text) == (DocumentTextStatus.FAILED, "")
    assert outcome.error == "memory limit exceeded"


def test_a_crash_fails_with_its_reason() -> None:
    outcome = run(_segfault)
    assert (outcome.status, outcome.pages) == (DocumentTextStatus.FAILED, 7)
    assert outcome.error == "extraction process killed by SIGSEGV"
    outcome = run(_exit)
    assert outcome.status is DocumentTextStatus.FAILED
    assert outcome.error == "extraction process ended without a result (exit code 3)"


def test_exceptions_become_statuses() -> None:
    cases = [
        (ValueError("kaputt"), DocumentTextStatus.FAILED, "ValueError: kaputt"),
        (Damaged("damaged PDF: no pages\nsecond line"), DocumentTextStatus.FAILED,
         "damaged PDF: no pages second line"),
        (Encrypted(), DocumentTextStatus.ENCRYPTED, None),
        (RecursionError(), DocumentTextStatus.FAILED, "structure nested too deeply"),
    ]  # fmt: skip
    for error, status, reason in cases:
        outcome = run(partial(_raise, error))
        assert (outcome.status, outcome.error, outcome.text) == (status, reason, "")


def test_text_is_cut_at_max_chars() -> None:
    outcome = run(_many_lines, chars=50_000)
    assert (outcome.status, outcome.truncated, len(outcome.text)) == (
        DocumentTextStatus.TEXT, True, 50_000
    )  # fmt: skip
    assert outcome.text.startswith("Zeile 0\nZeile 1\n")
    outcome = run(_scanned)
    assert (outcome.status, outcome.text, outcome.pages) == (DocumentTextStatus.SCANNED, "", 2)


def _reaped(pid: int) -> bool:
    """The process was a child of this one and has been waited for: no zombie is left."""
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return not _alive(pid)
    return False


def test_no_child_and_no_descriptor_left_behind(tmp_path: Path) -> None:
    descriptors = len(os.listdir("/proc/self/fd")) if Path("/proc/self/fd").exists() else None
    pids = []
    for number in range(20):
        path = tmp_path / str(number)
        assert run(partial(_process_group, path, pid=True)).status is DocumentTextStatus.EMPTY
        pids.append(int(path.read_text()))
    run(_exit)
    assert all(_reaped(pid) for pid in pids)
    if descriptors is not None:
        assert len(os.listdir("/proc/self/fd")) == descriptors


def test_the_child_stays_in_the_callers_process_group(tmp_path: Path) -> None:
    path = tmp_path / "group"
    assert run(partial(_process_group, path)).status is DocumentTextStatus.EMPTY
    assert int(path.read_text()) == os.getpgrp()


@pytest.fixture
def alarm() -> Iterator[None]:
    def interrupt(number: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGALRM, interrupt)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.usefixtures("alarm")
def test_an_interrupted_caller_kills_and_reaps_the_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    signal.setitimer(signal.ITIMER_REAL, 0.5)
    with pytest.raises(KeyboardInterrupt):
        run(partial(_write_pid, pid_file), timeout=60)
    assert _reaped(_pid_from(pid_file))


def _worker(pid_file: str) -> None:
    """A spawned worker, as the attachments phase runs them, extracting a slow document."""
    sandbox.run(partial(_write_pid, Path(pid_file)), timeout=60, memory=512 * MiB, max_chars=100)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is Linux")
@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGKILL])
def test_the_child_dies_with_a_killed_worker(tmp_path: Path, stop: signal.Signals) -> None:
    pid_file = tmp_path / "pid"
    worker = multiprocessing.get_context("spawn").Process(target=_worker, args=(str(pid_file),))
    worker.start()
    try:
        child = _pid_from(pid_file, seconds=30)
        assert _alive(child)
        assert worker.pid is not None
        os.kill(worker.pid, stop)
        worker.join(10)
        assert _wait_gone(child)
    finally:
        if worker.is_alive():
            worker.kill()
        worker.join()


def test_without_fork_the_extraction_runs_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(os, "fork")
    result = extract_document(b"Gr\xfc\xdfe", "a.txt", "text/plain", ExtractionLimits())
    assert (result.status, result.text) == (DocumentTextStatus.TEXT, "Grüße")
    started = time.monotonic()
    outcome = sandbox.run(_slow_lines, timeout=0.3, memory=MiB, max_chars=1000)
    assert outcome.status is DocumentTextStatus.TIMEOUT
    assert outcome.text.startswith("Zeile 0\nZeile 1") and outcome.truncated
    assert time.monotonic() - started < 2
    outcome = sandbox.run(partial(_raise, ValueError("x")), timeout=5, memory=MiB, max_chars=99)
    assert (outcome.status, outcome.error) == (DocumentTextStatus.FAILED, "ValueError: x")

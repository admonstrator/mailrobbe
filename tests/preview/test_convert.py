"""The conversion process (D122): real conversions end to end, the reasons of failures, the time
and memory limits, cancellation, and what the child inherits."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from mailrobbe.preview import convert as converting
from mailrobbe.preview.convert import ConversionFailed, convert
from tests.attachments.extract.samples import ole
from tests.preview.samples import docx, footnotes, odt, para, png, run

MiB = 1024**2
TIMEOUT, MEMORY = 30.0, 512 * MiB
linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs Linux")


def child(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    """Run this Python code as the conversion process: argv[1:] are FORMAT TIMEOUT MEMORY."""

    def command(fmt: str, timeout: float, memory: int) -> list[str]:
        return [sys.executable, "-c", script, fmt, f"{timeout:g}", str(memory)]

    monkeypatch.setattr(converting, "_command", command)


def gone(pid: int, seconds: float = 5) -> bool:
    """The process ended and was reaped (no /proc entry, not even a zombie)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not Path(f"/proc/{pid}").exists():
            return True
        time.sleep(0.02)
    return False


async def started(path: Path) -> int:
    for _ in range(500):
        if path.exists() and path.read_text().endswith("\n"):
            return int(path.read_text())
        await asyncio.sleep(0.02)
    raise AssertionError("the conversion process did not start")


async def test_documents_are_converted_in_the_child() -> None:
    picture = png()
    data = docx(
        para(
            run("Bericht "),
            run("vertraulich", "<w:b/>"),
            '<w:r><w:footnoteReference w:id="1"/></w:r>',
        )
        + para('<w:hyperlink r:id="rIdLink">' + run("Quelle") + "</w:hyperlink>"),
        related=(
            ("rIdLink", "hyperlink", "https://tracker.example/x", True),
            ("rIdNotes", "footnotes", "footnotes.xml", False),
        ),
        parts={"word/footnotes.xml": footnotes("Fußnote")},
    )
    page = (await convert(data, "docx", timeout=TIMEOUT, memory=MEMORY)).decode()
    assert page.startswith('<!doctype html>\n<html><head><meta charset="utf-8">')
    assert "<p>Bericht <strong>vertraulich</strong><sup>" in page
    assert "<p><a>Quelle</a></p>" in page and "tracker" not in page
    files = {"Pictures/a.png": picture}
    body = (
        '<text:p>Text <draw:frame><draw:image xlink:href="Pictures/a.png"/></draw:frame></text:p>'
    )
    page = (await convert(odt(body, files=files), "odt", timeout=TIMEOUT, memory=MEMORY)).decode()
    assert '<body><p>Text <img src="data:image/png;base64,iVBORw0KGgo' in page


async def test_why_a_document_has_no_page() -> None:
    cases = [
        (b"PK\x03\x04 not really", "docx", "damaged document: damaged ZIP container: BadZipFile: "),
        (ole("EncryptedPackage"), "docx", "the document is encrypted (it needs a password)"),
        (odt("<text:p>offen"), "odt", "damaged document: content.xml: malformed XML"),
        (b"", "odt", "damaged document: damaged ZIP container: BadZipFile: "),
    ]
    for data, fmt, reason in cases:
        with pytest.raises(ConversionFailed) as failure:
            await convert(data, fmt, timeout=TIMEOUT, memory=MEMORY)
        assert str(failure.value).startswith(reason)
        assert failure.value.lasting


async def test_the_time_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    child(
        monkeypatch,
        f"import os, time; open({str(pid_file)!r}, 'w').write(f'{{os.getpid()}}\\n'); "
        "time.sleep(60)",
    )
    begun = time.monotonic()
    with pytest.raises(ConversionFailed) as failure:
        await convert(b"x" * MiB, "docx", timeout=1, memory=512 * MiB)
    assert time.monotonic() - begun < 10
    assert str(failure.value) == "conversion stopped after the time limit of 1 s"
    assert failure.value.lasting
    assert gone(int(pid_file.read_text()))


async def test_a_cancelled_request_stops_the_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid_file = tmp_path / "pid"
    child(
        monkeypatch,
        f"import os, time; open({str(pid_file)!r}, 'w').write(f'{{os.getpid()}}\\n'); "
        "time.sleep(60)",
    )
    task = asyncio.create_task(convert(b"x", "docx", timeout=TIMEOUT, memory=MEMORY))
    pid = await started(pid_file)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gone(pid)


@linux
async def test_the_memory_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    child(
        monkeypatch,
        "import sys; from mailrobbe.preview import convert as c; "
        "c.CONVERTERS['docx'] = lambda data: str(bytearray(8 * 1024**3)); "
        "sys.exit(c.main(sys.argv[1:]))",
    )
    with pytest.raises(ConversionFailed) as failure:
        await convert(b"x", "docx", timeout=30, memory=256 * MiB)
    assert str(failure.value) == "memory limit of 256 MiB exceeded"
    assert failure.value.lasting


@linux
async def test_what_the_child_inherits_and_may_do(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MAILROBBE_DATABASE_URL", "postgresql+asyncpg://geheim@db/mailrobbe")
    monkeypatch.setenv("MAILROBBE_BASIC_AUTH_PASSWORD", "geheim")
    keep_open = os.open(tmp_path, os.O_RDONLY)  # a file the server has open
    script = f"""
import json, os, resource, sys
from mailrobbe.preview.convert import confine
confine(float(sys.argv[2]), int(sys.argv[3]))
fds = []
for fd in range(3, 1024):
    try:
        os.fstat(fd)
        fds.append(fd)
    except OSError:
        pass
try:
    with open({str(tmp_path / "written")!r}, "wb") as handle:
        handle.write(b"x")
    write = "written"
except OSError as error:
    write = error.strerror
limits = {{
    name: resource.getrlimit(getattr(resource, name))
    for name in ("RLIMIT_CORE", "RLIMIT_FSIZE", "RLIMIT_CPU", "RLIMIT_AS")
}}
report = {{"env": sorted(os.environ), "fds": fds, "write": write, "limits": limits}}
sys.stdout.write("ok\\n" + json.dumps(report))
"""
    try:
        child(monkeypatch, script)
        report = json.loads(await convert(b"x", "docx", timeout=5, memory=256 * MiB))
    finally:
        os.close(keep_open)
    assert not [name for name in report["env"] if name.startswith(("MAILROBBE", "PYTHON"))]
    assert set(report["env"]) <= {"PATH", "LANG", "LC_ALL", "LC_CTYPE"}
    assert report["fds"] == []
    assert report["write"] == "File too large"
    assert (tmp_path / "written").stat().st_size == 0  # opened, but nothing written
    limits = report["limits"]
    assert limits["RLIMIT_CORE"] == [0, 0]
    assert limits["RLIMIT_FSIZE"] == [0, 0]
    assert limits["RLIMIT_CPU"] == [15, 15]  # the time limit and a grace of 10 s
    soft, hard = limits["RLIMIT_AS"]
    assert soft == hard and 256 * MiB < soft < 4096 * MiB


def test_the_child_command() -> None:
    command = converting._command("odt", 60.0, 1024**3)
    assert command == [
        sys.executable,
        "-I",
        "-B",
        "-m",
        "mailrobbe.preview.convert",
        "odt",
        "60",
        str(1024**3),
    ]


async def test_children_that_end_without_a_status(monkeypatch: pytest.MonkeyPatch) -> None:
    child(monkeypatch, "import sys; sys.stderr.write('Traceback: boom\\n'); sys.exit(3)")
    with pytest.raises(ConversionFailed) as failure:
        await convert(b"x", "docx", timeout=TIMEOUT, memory=MEMORY)
    assert str(failure.value) == "conversion process ended with exit code 3"
    assert not failure.value.lasting  # not the document's fault, perhaps: tried again
    child(monkeypatch, "import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
    with pytest.raises(ConversionFailed) as failure:
        await convert(b"x", "docx", timeout=TIMEOUT, memory=MEMORY)
    assert str(failure.value) == "conversion process killed by SIGTERM"
    assert failure.value.lasting

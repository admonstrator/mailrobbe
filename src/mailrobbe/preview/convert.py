"""Converting a DOCX or ODT to a sanitized page in a process of its own (D122): the server's
side (convert) and the child's (main, run as python -m mailrobbe.preview.convert).

The server holds the database credentials and runs threads, so it neither parses an attachment
itself nor forks: convert starts a fresh interpreter (-I: no PYTHON* variables, no user site, no
working directory on sys.path; -B: no bytecode written) with an environment of only PATH and the
locale (no MAILROBBE_* setting, so neither the database URL nor the Basic Auth password), no open
file but its three pipes, the document on stdin. The child limits itself before it reads the
document: its address space to its current size plus `memory` (RLIMIT_AS, Linux), its CPU time
to the time limit plus a grace, no core dumps, no file it may write (RLIMIT_FSIZE 0, with SIGXFSZ
ignored so that a write fails instead of killing it). It converts (docx, odt), sanitizes,
wraps the page and writes a status line and its payload to stdout: "ok" and the page, or
"failed" and the reason. On macOS without Docker the memory limit is missing, as in the text
extraction (attachments.extract.sandbox).

The parent kills the child after `timeout` seconds and always waits for it, also when the
request waiting for the page is cancelled. ConversionFailed says why a document has no page:
damaged (with the reason), encrypted, the time, CPU or memory limit; `lasting` marks the reasons
the same bytes would meet again, which the cache may remember.
"""

import asyncio
import contextlib
import logging
import math
import os
import resource
import signal
import sys
from collections.abc import Callable

from mailrobbe.attachments.extract.base import Damaged, Encrypted, one_line, reason
from mailrobbe.attachments.extract.sandbox import _address_space, _set_limit
from mailrobbe.preview.docx import docx_html
from mailrobbe.preview.odt import odt_html
from mailrobbe.preview.sanitize import page, sanitize

log = logging.getLogger(__name__)

# kinds.HTML_FORMATS -> the HTML of the document's body
CONVERTERS: dict[str, Callable[[bytes], str]] = {"docx": docx_html, "odt": odt_html}
# Of the pages written (cache.py): raise it when a converter, the sanitizer or the page changes,
# and documents are converted again when they are opened.
VERSION = 1

_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
_CPU_GRACE = 10  # CPU seconds beyond the time limit before the kernel stops a child
_OK, _FAILED = b"ok", b"failed"
_MEMORY_EXIT = 71  # the child ran out of memory


class ConversionFailed(Exception):
    """The document has no page; the message says why (English, one line)."""

    def __init__(self, message: str, *, lasting: bool = True) -> None:
        super().__init__(message)
        self.lasting = lasting  # the same bytes would fail again


async def convert(data: bytes, fmt: str, *, timeout: float, memory: int) -> bytes:
    """The page of a document in one of the CONVERTERS formats; see the module docstring."""
    process = await asyncio.create_subprocess_exec(
        *_command(fmt, timeout, memory),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={key: os.environ[key] for key in _ENVIRONMENT if key in os.environ},
        close_fds=True,
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(data), timeout)
    except TimeoutError:
        raise ConversionFailed(
            f"conversion stopped after the time limit of {timeout:g} s"
        ) from None
    finally:
        if process.returncode is None:  # the time limit, or the request was cancelled
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    code = await process.wait()
    status, _, payload = output.partition(b"\n")
    if code == 0 and status == _OK:
        return payload
    if code == 0 and status == _FAILED:
        raise ConversionFailed(payload.decode("utf-8", "replace"))
    raise _death(code, errors, memory)


def _command(fmt: str, timeout: float, memory: int) -> list[str]:
    module = "mailrobbe.preview.convert"
    return [sys.executable, "-I", "-B", "-m", module, fmt, f"{timeout:g}", str(memory)]


def _death(code: int, errors: bytes, memory: int) -> ConversionFailed:
    """Why a child ended without a status line."""
    if code == _MEMORY_EXIT:
        return ConversionFailed(f"memory limit of {memory // 1024**2} MiB exceeded")
    if code == -signal.SIGXCPU:
        return ConversionFailed("conversion stopped at its CPU time limit")
    lines = errors.decode("utf-8", "replace").strip().splitlines()
    log.warning("preview conversion ended with %d: %s", code, one_line(lines[-1]) if lines else "")
    if code == -signal.SIGKILL:  # not by the parent: the system's memory, perhaps
        return ConversionFailed("conversion process killed, probably out of memory", lasting=False)
    if code < 0:  # a crash the same bytes would cause again
        try:
            name = signal.Signals(-code).name
        except ValueError:
            name = f"signal {-code}"
        return ConversionFailed(f"conversion process killed by {name}")
    return ConversionFailed(f"conversion process ended with exit code {code}", lasting=False)


# Child side


def main(argv: list[str]) -> int:
    """The child: FORMAT TIMEOUT MEMORY as arguments, the document on stdin, the status line and
    its payload on stdout."""
    fmt, timeout, memory = argv[0], float(argv[1]), int(argv[2])
    confine(timeout, memory)
    try:
        html = page(sanitize(CONVERTERS[fmt](sys.stdin.buffer.read())))
        result = _OK + b"\n" + html.encode("utf-8", "replace")
    except MemoryError:
        return _MEMORY_EXIT
    except Encrypted:
        result = _FAILED + b"\nthe document is encrypted (it needs a password)"
    except Damaged as error:
        result = _FAILED + f"\ndamaged document: {one_line(str(error)) or 'unreadable'}".encode()
    except RecursionError:
        result = _FAILED + b"\ndamaged document: structure nested too deeply"
    except Exception as error:
        result = _FAILED + f"\ndamaged document: {reason(error)}".encode()
    sys.stdout.buffer.write(result)
    sys.stdout.buffer.flush()
    return 0


def confine(timeout: float, memory: int) -> None:
    """The child's limits (see the module docstring); quietly fewer where unsupported."""
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    _set_limit(resource.RLIMIT_CORE, 0)
    _set_limit(resource.RLIMIT_FSIZE, 0)
    _set_limit(resource.RLIMIT_CPU, math.ceil(timeout) + _CPU_GRACE)
    size = _address_space()
    if size is not None:
        _set_limit(resource.RLIMIT_AS, size + memory)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

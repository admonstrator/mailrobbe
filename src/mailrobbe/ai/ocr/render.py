"""Page pictures of a scanned PDF or an image, made in a process of its own (D183): the run's
side (render) and the child's (main, run as python -m mailrobbe.ai.ocr.render).

Attachments may come from a hostile organisation, so the original is opened only here: render
starts a fresh interpreter (-I -B, an environment of only PATH and the locale, as
preview.convert) in a session of its own with the file on stdin. The child limits itself first
as preview.convert.confine does (address space to its size plus `memory` on Linux, CPU time, no
core dumps, files only up to _FILE_LIMIT) and works in a temporary directory:

    pdf     pdfinfo counts the pages and gives their sizes; pdftoppm renders each asked page,
            at 300 dpi for Tesseract (less for a page that would get longer than _TESSERACT_SIDE
            pixels) in grey, or scaled so its longest side is 1,600 px for a vision model
    image   Pillow opens JPEG, PNG, WebP, TIFF, GIF or BMP (the first frame), turns it by its
            EXIF orientation, puts transparency on white, makes it RGB or grey, scales it down
            to the side of its purpose and saves it as a new PNG; a picture above Pillow's pixel
            limit (a decompression bomb) is refused

pdftoppm and pdfinfo are the child's children and inherit its limits. It writes a status line
and its payload to stdout: "ok", a JSON line with pages_total and the length of each PNG, then
the PNGs; or "failed" and the reason. The parent kills the child's whole session after
`timeout` seconds (so no pdftoppm outlives it) and always waits for it. RenderError says why a
document has no pictures. Only these PNGs ever go to Tesseract or a service.

The child starts once per document and pass, so it imports nothing of mailrobbe but this module
(the database models alone take most of a second to import) and Pillow only for an image.
"""

import contextlib
import io
import json
import math
import os
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mailrobbe.ai.model import OcrEngine

VISION_SIDE = 1600  # longest side of a page picture for a vision model
TESSERACT_DPI = 300
_TESSERACT_SIDE = 4000  # longest side of a page picture for Tesseract
_FILE_LIMIT = 512 * 1024**2  # largest file the child (and pdftoppm) may write
_IMAGE_FORMATS = ("JPEG", "PNG", "WEBP", "TIFF", "GIF", "BMP")
_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
_OK, _FAILED = b"ok", b"failed"
_MEMORY_EXIT = 71  # the child ran out of memory
_CPU_GRACE = 10  # CPU seconds beyond the time limit before the kernel stops a child


class RenderError(Exception):
    """The document gives no page pictures: damaged, unsupported, a time or memory limit
    (English, one line)."""


@dataclass(frozen=True, slots=True)
class RenderedPage:
    number: int  # from 1
    png: bytes


@dataclass(frozen=True, slots=True)
class Rendering:
    pages_total: int | None  # of the document; None when unknown
    pages: list[RenderedPage]


def render(
    data: bytes,
    kind: Literal["pdf", "image"],
    *,
    purpose: "OcrEngine",
    first: int,
    count: int,
    timeout: float,
    memory: int,
) -> Rendering:
    """Pages first to first + count - 1 (from 1) of a PDF, or an image as page 1 of 1, as PNGs
    for `purpose`; see the module docstring. Raises RenderError."""
    command = [
        sys.executable, "-I", "-B", "-m", "mailrobbe.ai.ocr.render",
        kind, purpose, str(first), str(count), f"{timeout:g}", str(memory),
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
        raise RenderError(f"rendering stopped after the time limit of {timeout:g} s") from None
    finally:
        if process.returncode is None:  # interrupted: no child may outlive this
            _kill(process)
            process.wait()
    status, _, payload = output.partition(b"\n")
    if process.returncode == 0 and status == _OK:
        return _parse(payload)
    if process.returncode == 0 and status == _FAILED:
        raise RenderError(payload.decode("utf-8", "replace"))
    raise RenderError(_death(process.returncode, errors, memory))


def _kill(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)


def _parse(payload: bytes) -> Rendering:
    header, _, rest = payload.partition(b"\n")
    meta = json.loads(header)
    pages = []
    offset = 0
    for number, length in meta["pages"]:
        pages.append(RenderedPage(number, rest[offset : offset + length]))
        offset += length
    return Rendering(meta["pages_total"], pages)


def _death(code: int, errors: bytes, memory: int) -> str:
    if code == _MEMORY_EXIT:
        return f"memory limit of {memory // 1024**2} MiB exceeded"
    if code == -signal.SIGXCPU:
        return "rendering stopped at its CPU time limit"
    if code == -signal.SIGKILL:
        return "rendering process killed, probably out of memory"
    lines = errors.decode("utf-8", "replace").strip().splitlines()
    detail = f": {lines[-1][:200]}" if lines else ""
    return f"rendering process ended with exit code {code}{detail}"


# Child side


class _Failed(Exception):
    """Why the child gives no pictures; becomes its "failed" line."""


def main(argv: list[str]) -> int:
    """The child: KIND PURPOSE FIRST COUNT TIMEOUT MEMORY as arguments, the file on stdin."""
    kind, purpose = argv[0], argv[1]
    first, count, timeout, memory = int(argv[2]), int(argv[3]), float(argv[4]), int(argv[5])
    _confine(timeout, memory)
    deadline = time.monotonic() + timeout
    try:
        data = sys.stdin.buffer.read()
        if kind == "pdf":
            total, pages = _pdf_pages(data, purpose, first, count, deadline)
        else:
            total, pages = 1, ([(1, _image_page(data, purpose))] if first == 1 and count else [])
        header = {"pages_total": total, "pages": [[number, len(png)] for number, png in pages]}
        result = b"".join(
            [_OK, b"\n", json.dumps(header).encode(), b"\n", *(png for _, png in pages)]
        )
    except MemoryError:
        return _MEMORY_EXIT
    except _Failed as error:
        result = _FAILED + b"\n" + str(error).encode()
    sys.stdout.buffer.write(result)
    sys.stdout.buffer.flush()
    return 0


def _confine(timeout: float, memory: int) -> None:
    """The limits of preview.convert.confine, with files up to _FILE_LIMIT for pdftoppm."""
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    _set_limit(resource.RLIMIT_CORE, 0)
    _set_limit(resource.RLIMIT_FSIZE, _FILE_LIMIT)
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


def _pdf_pages(
    data: bytes, purpose: str, first: int, count: int, deadline: float
) -> tuple[int, list[tuple[int, bytes]]]:
    with tempfile.TemporaryDirectory(prefix="mailrobbe-render-") as folder:
        source = Path(folder) / "in.pdf"
        source.write_bytes(data)
        found = re.search(r"^Pages:\s+(\d+)", _tool(["pdfinfo", str(source)], deadline), re.M)
        if found is None:
            raise _Failed("damaged PDF: pdfinfo found no pages")
        total = int(found.group(1))
        last = min(first + count - 1, total)
        if first > last:
            return total, []
        info = ""
        if purpose != "vision":  # the page sizes decide the resolution
            info = _tool(["pdfinfo", "-f", str(first), "-l", str(last), str(source)], deadline)
        sizes = {
            int(number): max(float(width), float(height))
            for number, width, height in re.findall(
                r"^Page\s+(\d+) size:\s+([\d.]+) x ([\d.]+)", info, re.MULTILINE
            )
        }
        pages = []
        for number in range(first, last + 1):
            out = Path(folder) / f"page-{number}"
            command = ["pdftoppm", "-f", str(number), "-l", str(number), "-png", "-singlefile"]
            if purpose == "vision":
                command += ["-scale-to", str(VISION_SIDE)]
            else:
                points = sizes.get(number, 842.0)
                dpi = min(TESSERACT_DPI, _TESSERACT_SIDE * 72 / max(points, 1.0))
                command += ["-gray", "-r", f"{dpi:.2f}"]
            _tool([*command, str(source), str(out)], deadline)
            png = out.with_suffix(".png")
            pages.append((number, png.read_bytes()))
            png.unlink()
        return total, pages


def _tool(command: list[str], deadline: float) -> str:
    """The output of pdfinfo or pdftoppm; _Failed with poppler's reason when it fails."""
    try:
        done = subprocess.run(
            command, capture_output=True, timeout=max(deadline - time.monotonic(), 1), check=False
        )
    except FileNotFoundError:
        raise _Failed(f"{command[0]} is not installed (package poppler-utils)") from None
    except subprocess.TimeoutExpired:
        raise _Failed(f"{command[0]} stopped at the time limit") from None
    if done.returncode == 0:
        return done.stdout.decode("utf-8", "replace")
    if done.returncode < 0:  # under RLIMIT_AS an allocation that fails often aborts
        try:
            name = signal.Signals(-done.returncode).name
        except ValueError:
            name = f"signal {-done.returncode}"
        raise _Failed(f"{command[0]} killed by {name}, perhaps at the memory limit")
    errors = done.stderr.decode("utf-8", "replace")
    if "password" in errors.lower():
        raise _Failed("the PDF is encrypted (it needs a password)")
    lines = [line for line in errors.strip().splitlines() if line.strip()]
    reason = lines[-1][:200] if lines else f"exit code {done.returncode}"
    if "alloc" in reason.lower() or "memory" in reason.lower():
        raise MemoryError
    raise _Failed(f"damaged PDF: {reason}")


def _image_page(data: bytes, purpose: str) -> bytes:
    from PIL import Image, ImageOps, UnidentifiedImageError

    warnings.simplefilter("error", Image.DecompressionBombWarning)
    side = VISION_SIDE if purpose == "vision" else _TESSERACT_SIDE
    try:
        with Image.open(io.BytesIO(data), formats=_IMAGE_FORMATS) as opened:
            opened.seek(0)
            image = ImageOps.exif_transpose(opened)
            image.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise _Failed(f"picture too large: {error}") from None
    except UnidentifiedImageError:
        raise _Failed("not a picture of a supported format") from None
    except (OSError, ValueError, SyntaxError, EOFError) as error:
        raise _Failed(f"damaged picture: {str(error)[:200]}") from None
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        image = Image.new("RGB", rgba.size, (255, 255, 255))
        image.paste(rgba, mask=rgba.getchannel("A"))
    image = image.convert("L" if image.mode in ("1", "L", "I", "I;16", "F") else "RGB")
    if max(image.size) > side:
        image.thumbnail((side, side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

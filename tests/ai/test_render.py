import io
import random
import struct
import sys
import zlib
from datetime import UTC, datetime

import pytest
from PIL import Image

from mailrobbe.ai.ocr.render import VISION_SIDE, RenderError, render
from mailrobbe.generator import documents
from mailrobbe.generator import fileformats as ff
from mailrobbe.generator.model import DocumentSpec

MEMORY = 1024**3


def scan(pages: int) -> bytes:
    """A generated scan of set text with this many pages."""
    lines = ["Kassenbericht", "Aktenzeichen: ScanmarkeTEST47", "Spende 50,00 €"]
    pictures = [ff.scan_page([*lines, f"Seite {n}"]) for n in range(1, pages + 1)]
    return ff.pdf([], random.Random(1), images=pictures)


def size(png: bytes) -> tuple[int, int]:
    picture = Image.open(io.BytesIO(png))
    assert picture.format == "PNG"
    return picture.size


def test_pdf_pages_are_rendered_at_300_dpi_for_tesseract() -> None:
    rendering = render(scan(3), "pdf", purpose="tesseract", first=2, count=5, timeout=60,
                       memory=MEMORY)  # fmt: skip
    assert rendering.pages_total == 3
    assert [page.number for page in rendering.pages] == [2, 3]
    width, height = size(rendering.pages[0].png)  # A4 at 300 dpi
    assert abs(width - 2480) <= 1 and abs(height - 3508) <= 1


def test_pdf_pages_are_scaled_to_1600_pixels_for_a_vision_model() -> None:
    rendering = render(scan(3), "pdf", purpose="vision", first=1, count=2, timeout=60,
                       memory=MEMORY)  # fmt: skip
    assert [page.number for page in rendering.pages] == [1, 2]
    assert max(size(rendering.pages[1].png)) == VISION_SIDE


def test_a_generated_scan_renders_beyond_its_last_page_as_nothing() -> None:
    for seed in range(200):
        spec = DocumentSpec(seed, "pdf_scan", "scan", datetime(2020, 1, 1, tzinfo=UTC))
        if documents.set_text(spec) is not None:
            break
    data, pages = documents.document_bytes(spec, 300_000)
    rendering = render(data, "pdf", purpose="vision", first=(pages or 1) + 1, count=3,
                       timeout=60, memory=MEMORY)  # fmt: skip
    assert (rendering.pages_total, rendering.pages) == (pages, [])


def jpeg_with_orientation(orientation: int) -> bytes:
    picture = Image.new("RGB", (400, 100), "white")
    exif = Image.Exif()
    exif[0x0112] = orientation
    out = io.BytesIO()
    picture.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def test_an_image_is_turned_by_its_exif_and_written_anew() -> None:
    data = jpeg_with_orientation(6)  # rotated 90 degrees: the picture stands upright
    rendering = render(data, "image", purpose="tesseract", first=1, count=50, timeout=60,
                       memory=MEMORY)  # fmt: skip
    assert rendering.pages_total == 1
    (page,) = rendering.pages
    assert page.number == 1 and size(page.png) == (100, 400)
    assert "exif" not in Image.open(io.BytesIO(page.png)).info


def test_an_image_is_scaled_down_for_a_vision_model_and_put_on_white() -> None:
    picture = Image.new("RGBA", (3200, 1000), (0, 0, 0, 0))
    out = io.BytesIO()
    picture.save(out, "WEBP", lossless=True)
    rendering = render(out.getvalue(), "image", purpose="vision", first=1, count=1, timeout=60,
                       memory=MEMORY)  # fmt: skip
    result = Image.open(io.BytesIO(rendering.pages[0].png))
    assert result.size == (1600, 500)
    assert result.mode == "RGB" and result.getpixel((10, 10)) == (255, 255, 255)


def test_an_image_has_no_second_page() -> None:
    rendering = render(jpeg_with_orientation(1), "image", purpose="vision", first=2, count=1,
                       timeout=60, memory=MEMORY)  # fmt: skip
    assert (rendering.pages_total, rendering.pages) == (1, [])


def png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(data, zlib.crc32(kind))
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def test_a_decompression_bomb_is_refused() -> None:
    header = struct.pack(">IIBBBBB", 40_000, 40_000, 8, 2, 0, 0, 0)
    bomb = b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", header),
            png_chunk(b"IDAT", zlib.compress(b"\x00" * 1000)),
            png_chunk(b"IEND", b""),
        )
    )
    with pytest.raises(RenderError, match="too large"):
        render(bomb, "image", purpose="vision", first=1, count=1, timeout=60, memory=MEMORY)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="RLIMIT_AS is Linux only")
def test_the_memory_limit_ends_the_child() -> None:
    picture = Image.effect_noise((6000, 6000), 60).convert("RGB")
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=20)
    with pytest.raises(RenderError, match="memory"):
        render(out.getvalue(), "image", purpose="vision", first=1, count=1, timeout=60,
               memory=40 * 1024**2)  # fmt: skip


def test_the_time_limit_ends_the_child() -> None:
    with pytest.raises(RenderError, match=r"time limit of 0\.001 s"):
        render(scan(1), "pdf", purpose="tesseract", first=1, count=1, timeout=0.001,
               memory=MEMORY)  # fmt: skip


@pytest.mark.parametrize(
    ("data", "kind", "message"),
    [
        (b"%PDF-1.4\nnothing else", "pdf", "damaged PDF"),
        (ff.pdf([["geheim"]], random.Random(2), password="pw"), "pdf", "encrypted"),
        (jpeg_with_orientation(1)[:400], "image", "damaged picture"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image", "not a picture"),
    ],
)
def test_a_file_without_pictures_raises_render_error(data, kind, message) -> None:
    with pytest.raises(RenderError, match=message):
        render(data, kind, purpose="vision", first=1, count=1, timeout=60, memory=MEMORY)

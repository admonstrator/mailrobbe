"""One page through Tesseract (D182): `tesseract stdin stdout -l <languages> --psm 3 tsv`.

One run gives words with their place and confidence; the text is rebuilt from them in
Tesseract's reading order, a line break per line and an empty line between paragraphs and
blocks. The page's confidence is the mean of its word confidences (0 to 100; Tesseract writes
-1 for the boxes that are no words); a page below the threshold is uncertain, so `auto` reads it
again with the vision model. A page without words has the text "" and is not uncertain.

The PNG comes from ai.ocr.render, so Tesseract never sees an original. Tesseract runs with one
thread (OMP_THREAD_LIMIT=1): a run reads several pages at once instead. A missing program or
language stops the run (TesseractMissing, naming the package); a page Tesseract fails on or
that passes the time limit gets OcrPage.error.
"""

import os
import subprocess
import time
from functools import cache

from mailrobbe.ai.model import OcrPage
from mailrobbe.attachments.extract.base import one_line

PROGRAM = "tesseract"
PAGE_SEGMENTATION = "3"  # fully automatic page segmentation, without orientation detection


class TesseractMissing(Exception):
    """Tesseract or one of the languages is not installed; the message names the package."""


@cache
def installed_languages() -> frozenset[str]:
    """The languages Tesseract has data for; raises TesseractMissing without the program."""
    try:
        listed = subprocess.run(
            [PROGRAM, "--list-langs"], capture_output=True, text=True, timeout=30, check=False
        )
    except FileNotFoundError:
        raise TesseractMissing("tesseract is not installed (package tesseract-ocr)") from None
    except subprocess.TimeoutExpired:
        raise TesseractMissing("tesseract --list-langs did not answer") from None
    lines = listed.stdout.splitlines()
    return frozenset(line.strip() for line in lines[1:] if line.strip())


def check_languages(languages: str) -> None:
    """Raises TesseractMissing unless every language of `languages` (deu+eng) is installed."""
    missing = [code for code in languages.split("+") if code not in installed_languages()]
    if missing:
        packages = ", ".join(f"tesseract-ocr-{code}" for code in missing)
        raise TesseractMissing(
            f"Tesseract has no language data for {'+'.join(missing)} (package {packages})"
        )


def read_page(
    png: bytes, number: int, *, languages: str, uncertain: float, timeout: float
) -> OcrPage:
    """Page `number` read from its PNG; see the module docstring."""
    check_languages(languages)
    started = time.monotonic()
    command = [PROGRAM, "stdin", "stdout", "-l", languages, "--psm", PAGE_SEGMENTATION, "tsv"]
    try:
        done = subprocess.run(
            command,
            input=png,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except FileNotFoundError:
        raise TesseractMissing("tesseract is not installed (package tesseract-ocr)") from None
    except subprocess.TimeoutExpired:
        return OcrPage(
            number=number,
            engine="tesseract",
            error=f"Tesseract stopped after the time limit of {timeout:g} s",
            seconds=round(time.monotonic() - started, 3),
        )
    seconds = round(time.monotonic() - started, 3)
    if done.returncode != 0 or not done.stdout.startswith(b"level"):
        errors = done.stderr.decode("utf-8", "replace").strip().splitlines()
        detail = one_line(errors[-1]) if errors else f"exit code {done.returncode}"
        return OcrPage(
            number=number, engine="tesseract", error=f"Tesseract failed: {detail}", seconds=seconds
        )
    text, confidence = parse_tsv(done.stdout.decode("utf-8", "replace"))
    return OcrPage(
        number=number,
        engine="tesseract",
        text=text,
        confidence=confidence,
        uncertain=confidence is not None and confidence < uncertain,
        seconds=seconds,
    )


def parse_tsv(tsv: str) -> tuple[str, float | None]:
    """The text of Tesseract's TSV and the mean confidence of its words (None without words)."""
    paragraphs: list[list[list[str]]] = []  # paragraphs of lines of words
    place: tuple[str, ...] | None = None
    line: tuple[str, ...] | None = None
    confidences: list[float] = []
    for row in tsv.splitlines()[1:]:
        cells = row.split("\t")
        if len(cells) < 12 or cells[0] != "5":  # level 5: a word
            continue
        word = cells[11].strip()
        try:
            confidence = float(cells[10])
        except ValueError:
            continue
        if not word or confidence < 0:
            continue
        confidences.append(confidence)
        # page, block, paragraph and line numbers
        if tuple(cells[1:4]) != place:
            place = tuple(cells[1:4])
            paragraphs.append([])
            line = None
        if tuple(cells[1:5]) != line:
            line = tuple(cells[1:5])
            paragraphs[-1].append([])
        paragraphs[-1][-1].append(word)
    text = "\n\n".join("\n".join(" ".join(words) for words in lines) for lines in paragraphs)
    mean = round(sum(confidences) / len(confidences), 1) if confidences else None
    return text, mean

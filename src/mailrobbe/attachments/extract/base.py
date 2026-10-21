"""What every extractor shares: the Sink it writes its text to, and how it reports a document
that cannot be read.

An extractor is a function (data, sink) -> DocumentTextStatus | None. It writes the text as it
finds it, page by page or sheet by sheet, with sink.line and sink.text; sink.block separates
pages, sheets, slides and parts by a blank line and passes what is buffered on, so a document
stopped at the time limit keeps the pages read until then. It returns None when the sink decides
(text, or empty without any), or a status of its own (scanned, unsupported). It raises Encrypted
for a document that needs a password and Damaged, with a one-line English reason, for one that
cannot be read; any other exception counts as damage as well.

The sink normalises as it goes: no NUL or other control characters, LF line ends, runs of spaces
collapsed to one, tabs kept (they separate cells), at most one empty line in a row. It stops the
extractor with Full once max_chars characters are written.
"""

import re
import time
from collections.abc import Callable

from mailrobbe.enums import DocumentTextStatus


class Encrypted(Exception):
    """The document needs a password."""


class Damaged(Exception):
    """The document cannot be read; the message is the reason, English, one line."""


class Full(Exception):
    """The sink holds max_chars characters; the extractor stops here (Extraction.truncated)."""


class DeadlineExceeded(Exception):
    """The time limit passed (only where no child process can be killed: sandbox.run_inline)."""


Extractor = Callable[[bytes, "Sink"], DocumentTextStatus | None]

_SPACES = re.compile(r"[^\S\t]+")  # whitespace within a line other than tabs
_CONTROL = re.compile("[\x00-\x08\x0e-\x1f\x7f\ud800-\udfff]")
_FLUSH_CHARS = 16_384  # buffered characters that are passed on without waiting for a block end


def one_line(text: str, limit: int = 300) -> str:
    """A message on one line, at most `limit` characters."""
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 3] + "..."


def reason(error: BaseException) -> str:
    """One line naming an exception: its type and message."""
    message = str(error)
    return one_line(f"{type(error).__name__}: {message}" if message else type(error).__name__)


class Sink:
    """Collects the normalised text of one document, at most max_chars characters.

    `emit` receives the text in pieces as it is produced (the child process sends them to its
    parent); without it the pieces are kept and `text` returns them. `deadline` (a monotonic
    time) raises DeadlineExceeded from line() once passed.
    """

    def __init__(
        self,
        max_chars: int,
        emit: Callable[[str], None] | None = None,
        on_pages: Callable[[int], None] | None = None,
        deadline: float | None = None,
    ) -> None:
        self.max_chars = max_chars
        self.pages: int | None = None
        self.truncated = False
        self.has_text = False
        self._emit = emit
        self._on_pages = on_pages
        self._deadline = deadline
        self._buffer: list[str] = []
        self._buffered = 0
        self._kept: list[str] = []
        self._chars = 0
        self._gap = False  # an empty line is wanted before the next line

    def set_pages(self, pages: int) -> None:
        """Pages, sheets or slides of the document, as soon as the extractor knows them."""
        self.pages = pages
        if self._on_pages is not None:
            self._on_pages(pages)

    def line(self, text: str) -> None:
        """One line of text; an empty one stands for a paragraph break."""
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise DeadlineExceeded
        text = _CONTROL.sub("", _SPACES.sub(" ", text)).strip(" ").rstrip()
        if not text:
            self._gap = True
            return
        if self._chars:
            text = ("\n\n" if self._gap else "\n") + text
        self._gap = False
        self.has_text = True
        room = self.max_chars - self._chars
        if len(text) >= room:
            self._add(text[:room])
            self.truncated = len(text) > room
            if self.truncated:
                self.flush()
                raise Full
            return
        self._add(text)

    def text(self, text: str) -> None:
        """Text of several lines, split at any line break."""
        for line in text.splitlines():
            self.line(line)

    def block(self) -> None:
        """End of a page, sheet, slide or part: an empty line follows, and the text so far is
        passed on."""
        self._gap = True
        self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        piece = "".join(self._buffer)
        self._buffer.clear()
        self._buffered = 0
        if self._emit is None:
            self._kept.append(piece)
        else:
            self._emit(piece)

    @property
    def collected(self) -> str:
        """Everything written, when the sink has no `emit`."""
        self.flush()
        return "".join(self._kept)

    def _add(self, text: str) -> None:
        self._buffer.append(text)
        self._buffered += len(text)
        self._chars += len(text)
        if self._buffered >= _FLUSH_CHARS:
            self.flush()

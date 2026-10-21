"""The preview cache (D124): converted pages and media files below MAILROBBE_PREVIEW_DIR, by the
attachment's SHA-256 and the version of what wrote them.

    html/<sha[:2]>/<sha>.v<convert.VERSION>.html    the page of a DOCX or ODT
    html/<sha[:2]>/<sha>.v<convert.VERSION>.failed  why its conversion failed (UTF-8, one line)
    media/<sha[:2]>/<sha>.v<media.VERSION>          the bytes of an audio or video attachment

A file is written under a temporary name in its directory, synced and renamed (os.replace), so a
stopped conversion or a crash never leaves a half written file under a name that is read; the
directories are made on demand. Nothing in here is needed: a missing or unwritable directory
only means that previews are not cached, which is logged once. Files of an older version are not
read any more; like everything else here they may be deleted at any time.
"""

import contextlib
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mailrobbe.preview import convert, media

log = logging.getLogger(__name__)

_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class Failed:
    """A conversion that failed, and why (English, one line)."""

    reason: str


class PreviewCache:
    """The cache below one directory. Blocking: call its methods in a thread."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._warned = False

    def page(self, sha256: str) -> bytes | Failed | None:
        """The cached page of a document, or why its conversion failed; None for neither."""
        page = self._read(self._path("html", sha256, f".v{convert.VERSION}.html"))
        if page is not None:
            return page
        reason = self._read(self._path("html", sha256, f".v{convert.VERSION}.failed"))
        return None if reason is None else Failed(reason.decode("utf-8", "replace"))

    def store_page(self, sha256: str, page: bytes) -> None:
        self._write(self._path("html", sha256, f".v{convert.VERSION}.html"), page)

    def store_failure(self, sha256: str, reason: str) -> None:
        self._write(self._path("html", sha256, f".v{convert.VERSION}.failed"), reason.encode())

    def media(self, sha256: str) -> Path | None:
        """The cached media file of an attachment, when there is one."""
        path = self._path("media", sha256, f".v{media.VERSION}")
        try:
            return path if path.is_file() else None
        except OSError as error:
            self._warn(error)
            return None

    def store_media(self, sha256: str, data: bytes) -> Path | None:
        """Cache an attachment's bytes; where they are now, None when they cannot be stored."""
        path = self._path("media", sha256, f".v{media.VERSION}")
        return path if self._write(path, data) else None

    def _path(self, kind: str, sha256: str, suffix: str) -> Path:
        if not _SHA256.fullmatch(sha256):
            raise ValueError(f"not a SHA-256: {sha256!r}")
        return self.root / kind / sha256[:2] / f"{sha256}{suffix}"

    def _read(self, path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            self._warn(error)
            return None

    def _write(self, path: Path, data: bytes) -> bool:
        """Write the file atomically; False (and a warning, once) when it cannot be written."""
        temporary: str | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as error:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)
            self._warn(error)
            return False
        return True

    def _warn(self, error: OSError) -> None:
        if not self._warned:
            self._warned = True
            log.warning(
                "preview cache %s is not usable (%s); previews are not cached", self.root, error
            )

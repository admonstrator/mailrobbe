"""Which preview an attachment gets (D120): the one place deciding it, from what the database
knows (document kind, file name, declared MIME type, size). The endpoints check the content's
first bytes again before they convert or stream, so a hint can only offer too much, never
show something else.
"""

from typing import Literal

from mailrobbe.attachments.kinds import classify
from mailrobbe.enums import DocumentKind

PreviewKind = Literal["image", "pdf", "html", "audio", "video"]

# Raster images an <img> shows (D76); the content endpoint keeps their type only when the first
# bytes prove it.
RASTER_TYPES = frozenset({"image/png", "image/jpeg", "image/pjpeg", "image/gif", "image/webp"})
RASTER_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "jpe", "gif", "webp"})
# kinds.FORMATS names converted to HTML (D122); DOC, RTF and the rest are download only.
HTML_FORMATS = frozenset({"docx", "odt"})
# Formats current browsers play (D123), by extension or declared type. MOV is offered because
# most are H.264 in an MP4-like container; the player says so when a browser cannot play one.
AUDIO_EXTENSIONS = frozenset({"mp3", "m4a", "aac", "wav", "ogg", "oga", "opus", "flac"})
AUDIO_TYPES = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/x-m4a",
        "audio/aac",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/vnd.wave",
        "audio/ogg",
        "audio/opus",
        "audio/flac",
        "audio/x-flac",
    }
)
VIDEO_EXTENSIONS = frozenset({"mp4", "m4v", "webm", "mov"})
VIDEO_TYPES = frozenset({"video/mp4", "video/webm", "video/quicktime", "video/x-m4v"})


def preview_kind(
    kind: DocumentKind | None,
    filename: str | None,
    mime_type: str,
    size: int,
    *,
    hashed: bool,
    max_size: int,
) -> PreviewKind | None:
    """How the browser shows this attachment; None: download only.

    kind is the document's kind (from the first bytes once finalize classified it), None before;
    then the file name and declared type decide. Empty attachments and those above max_size
    (MAILROBBE_PREVIEW_MAX_SIZE) get none; converted and cached previews (html, audio, video)
    need the SHA-256 they are cached by (hashed).
    """
    if size <= 0 or size > max_size:
        return None
    declared = mime_type.partition(";")[0].strip().lower()
    extension = _extension(filename)
    if kind is None:
        kind = classify(filename, mime_type).kind
    if kind is DocumentKind.PDF:
        return "pdf"
    if kind is DocumentKind.IMAGE:
        raster = declared in RASTER_TYPES or extension in RASTER_EXTENSIONS
        return "image" if raster else None
    if not hashed:
        return None
    if kind is DocumentKind.DOCUMENT:
        return "html" if classify(filename, mime_type).name in HTML_FORMATS else None
    if kind is DocumentKind.MEDIA:
        if extension in AUDIO_EXTENSIONS:
            return "audio"
        if extension in VIDEO_EXTENSIONS:
            return "video"
        if classify(filename, "").kind is DocumentKind.MEDIA:
            return None  # a media file by its name that browsers do not play (WMA, AVI, ...)
        if declared in AUDIO_TYPES:
            return "audio"
        if declared in VIDEO_TYPES:
            return "video"
    return None


def _extension(filename: str | None) -> str:
    """The file name's extension in lower case, as attachments.kinds reads it; "" without."""
    if not filename:
        return ""
    stem, dot, extension = filename.strip().rpartition(".")
    return extension.lower() if dot and stem else ""

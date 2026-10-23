"""Previews of attachments (D120 to D124): DOCX and ODT as sanitized pages, audio and video with
Range requests. Endpoints and error codes are in schemas.py; preview.kinds decides which
attachment offers which preview, and these endpoints check its first bytes again.

Routes: GET /api/attachments/{id}/html, /api/attachments/{id}/media.

Both decide from the attachment's row before reading anything: 404 without it, 413 above
MAILROBBE_PREVIEW_MAX_SIZE or without a SHA-256, by which the cache keeps previews (D124). What
the cache holds is served without reading the MBOX file. Otherwise the bytes are read as the
download reads them (409 for a missing or changed file) and checked by their first bytes (415
when they are not what the endpoint shows). A page is converted in a process of its own
(preview.convert), at most MAILROBBE_PREVIEW_WORKERS at once; when that fails, the reason is a
422 and is remembered in the cache unless it may pass (preview.convert.ConversionFailed). Media
bytes are stored in the cache and served from there with Range requests (Starlette's
FileResponse: 206, 416, ETag); when the cache cannot store them, from memory without ranges.

One document is converted or stored once at a time: a second request for it waits for the first
and then finds the result in the cache. An opened document (D236) is decrypted first, in a
process of its own (attachments.protected.decrypt); its page is cached under a key of its own
(the SHA-256 of its SHA-256 and "opened"), apart from what the locked bytes gave before, and the
plain bytes are never stored (D209).
"""

import asyncio
import hashlib
import logging
import weakref
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.documents import AttachmentId, content_disposition
from mailrobbe.attachments.content import (
    AttachmentChanged,
    AttachmentSource,
    attachment_source,
    read_attachment,
)
from mailrobbe.attachments.kinds import HEAD_SIZE, classify
from mailrobbe.attachments.protected import DecryptFailed, decrypt
from mailrobbe.config import Settings
from mailrobbe.preview.cache import Failed, PreviewCache
from mailrobbe.preview.convert import ConversionFailed, convert
from mailrobbe.preview.kinds import HTML_FORMATS
from mailrobbe.preview.media import media_type

router = APIRouter(prefix="/api", tags=["documents"])
log = logging.getLogger(__name__)

# The app shows the page in <iframe sandbox="" srcdoc>; opened directly it is just as inert: no
# script, nothing loaded from anywhere, only inline styles and data: images (D122).
HTML_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'self'; sandbox"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, no-cache",
}
# Played by <audio> and <video> in the app (D123); opened directly, the browser's own player
# document may load the file and nothing else.
MEDIA_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; media-src 'self'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, no-cache",
}
_MEDIA_FORMATS = "MP3, AAC, M4A, MP4, MOV, WAV, Ogg, FLAC or WebM"


class Previews:
    """What the preview endpoints of one app share: the cache, the conversion slots and a lock
    per document whose preview is being made."""

    def __init__(self, settings: Settings) -> None:
        self.cache = PreviewCache(settings.preview_dir)
        self._workers = max(1, settings.preview_workers)
        self._slots = asyncio.Semaphore(self._workers)
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def slots(self, settings: Settings) -> asyncio.Semaphore:
        """The conversion slots, preview_workers of them; a changed setting (D313) holds for the
        conversions that start after it, the running ones finish in the old slots."""
        workers = max(1, settings.preview_workers)
        if workers != self._workers:
            self._workers, self._slots = workers, asyncio.Semaphore(workers)
        return self._slots

    def lock(self, key: str) -> asyncio.Lock:
        """The lock of one preview; it lives as long as someone holds or awaits it."""
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock


def _previews(request: Request) -> Previews:
    previews: Previews = request.app.state.previews
    return previews


AppPreviews = Annotated[Previews, Depends(_previews)]


@router.get("/attachments/{attachment_id}/html")
async def attachment_html(
    attachment_id: AttachmentId, session: Session, settings: AppSettings, previews: AppPreviews
) -> Response:
    source, sha256 = await _source(session, settings, attachment_id)
    if source.password is not None:  # the page of the opened document, not of its locked bytes
        sha256 = hashlib.sha256(f"{sha256} opened".encode()).hexdigest()
    found = await asyncio.to_thread(previews.cache.page, sha256)
    if found is None:
        async with previews.lock(f"html {sha256}"):
            found = await asyncio.to_thread(previews.cache.page, sha256)
            if found is None:
                found = await _convert(source, sha256, settings, previews)
    if isinstance(found, Failed):
        raise api_error(422, "preview_failed", found.reason)
    return Response(found, media_type="text/html; charset=utf-8", headers=HTML_HEADERS)


@router.get("/attachments/{attachment_id}/media")
async def attachment_media(
    attachment_id: AttachmentId, session: Session, settings: AppSettings, previews: AppPreviews
) -> Response:
    source, sha256 = await _source(session, settings, attachment_id)
    name = source.filename or f"attachment-{attachment_id}"
    headers = {**MEDIA_HEADERS, "Content-Disposition": inline_disposition(name)}
    found = await asyncio.to_thread(_cached_media, previews.cache, sha256)
    if found is None:
        async with previews.lock(f"media {sha256}"):
            found = await asyncio.to_thread(_cached_media, previews.cache, sha256)
            if found is None:
                data = await _read(settings, source)
                kind = media_type(data[:HEAD_SIZE])
                if kind is None:
                    raise api_error(
                        415,
                        "no_preview",
                        f"attachment {attachment_id} is no audio or video a browser plays "
                        f"({_MEDIA_FORMATS})",
                    )
                path = await asyncio.to_thread(previews.cache.store_media, sha256, data)
                if path is None:  # not cached: this response only, without ranges
                    return Response(data, media_type=kind, headers=headers)
                found = path, kind
    path, kind = found
    return FileResponse(path, media_type=kind, headers=headers)


def inline_disposition(filename: str) -> str:
    """content_disposition shown in the browser instead of saved: the same file name."""
    return "inline" + content_disposition(filename).removeprefix("attachment")


async def _source(
    session: AsyncSession, settings: Settings, attachment_id: int
) -> tuple[AttachmentSource, str]:
    """The attachment and its SHA-256; 404 without it, 413 when it gets no preview."""
    source = await attachment_source(session, attachment_id)
    if source is None:
        raise api_error(404, "not_found", f"no attachment with id {attachment_id}")
    await session.commit()  # reading, converting and serving may be slow: hold no connection
    limit = settings.preview_max_size
    if source.size_bytes > limit:
        raise api_error(
            413,
            "preview_too_large",
            f"attachment {attachment_id} has {source.size_bytes} bytes, more than the preview "
            f"limit of {limit.human_readable(decimal=False)}",
        )
    if source.sha256 is None:
        raise api_error(
            413,
            "preview_too_large",
            f"attachment {attachment_id} is above the hash limit: no preview without a SHA-256",
        )
    return source, source.sha256


async def _read(settings: Settings, source: AttachmentSource) -> bytes:
    """The attachment's bytes, as the download reads them (D76); 409 when they are gone."""
    try:
        return await asyncio.to_thread(read_attachment, settings.mbox_dir, source)
    except OSError as error:
        log.warning("attachment %d: cannot read %s: %s", source.attachment_id, source.path, error)
        raise api_error(409, "source_missing", f"cannot read {source.path}: {error}") from None
    except AttachmentChanged as error:
        log.warning("attachment %d: %s", source.attachment_id, error)
        raise api_error(409, "source_changed", str(error)) from None


async def _convert(
    source: AttachmentSource, sha256: str, settings: Settings, previews: Previews
) -> bytes | Failed:
    """Read, check and convert a document, and cache what came of it."""
    data = await _read(settings, source)
    if source.password is not None:  # an opened document (D236): decrypted first, never stored
        async with previews.slots(settings):
            try:
                data = await decrypt(
                    data,
                    source.filename,
                    source.mime_type,
                    source.password,
                    timeout=settings.preview_timeout,
                    memory=int(settings.preview_memory),
                )
            except DecryptFailed as error:
                raise api_error(422, "decrypt_failed", str(error)) from None
    fmt = classify(source.filename, source.mime_type, data[:HEAD_SIZE])
    if fmt.name not in HTML_FORMATS:
        raise api_error(
            415,
            "no_preview",
            f"attachment {source.attachment_id} is {fmt.name}: only DOCX and ODT are shown as HTML",
        )
    async with previews.slots(settings):
        try:
            page = await convert(
                data, fmt.name, timeout=settings.preview_timeout, memory=settings.preview_memory
            )
        except ConversionFailed as failure:
            log.warning("attachment %d: no preview: %s", source.attachment_id, failure)
            if failure.lasting:
                await asyncio.to_thread(previews.cache.store_failure, sha256, str(failure))
            return Failed(str(failure))
    await asyncio.to_thread(previews.cache.store_page, sha256, page)
    return page


def _cached_media(cache: PreviewCache, sha256: str) -> tuple[Path, str] | None:
    """The cached media file of an attachment and its type, when there is one."""
    path = cache.media(sha256)
    if path is None:
        return None
    try:
        with path.open("rb") as handle:
            kind = media_type(handle.read(HEAD_SIZE))
    except OSError:
        return None
    return None if kind is None else (path, kind)

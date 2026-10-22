"""Serving the built frontend: static files, index.html for client-side routes (D24), the PDF
viewer below viewer/ with a policy of its own (D121) and the overview map below map/ (D244)."""

import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

log = logging.getLogger(__name__)

# Vite gives the files below assets/ content-hashed names, so a name never changes its content.
ASSET_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}
# index.html names the current assets, so it is always revalidated. Everything comes from this
# server; frames only from it too (the sandboxed mail HTML, D22).
INDEX_HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
}
# The PDF viewer (D121) runs pdf.js on an opaque origin: the sandbox lacks allow-same-origin
# also when its page is opened directly, so it can neither read the app's data nor call its API
# as the app. It fetches nothing (the app hands it the PDF by postMessage) and opens no frames,
# forms or windows. Its scripts run by a nonce given per response, which the page carries as
# NONCE_PLACEHOLDER: from an opaque origin, 'self' does not name this server in every browser.
VIEWER_DIR = "viewer"
NONCE_PLACEHOLDER = "__CSP_NONCE__"
VIEWER_FILE_HEADERS = {"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"}
# The overview map (D244) keeps its file names when a release changes the files, so the browser
# asks again each time and gets a 304 for the file it has (by the ETag FileResponse gives) rather
# than keeping an old copy. A file it lacks is a 404, never index.html, which MapLibre would read
# as a glyph range or as GeoJSON.
MAP_DIR = "map"
MAP_HEADERS = {"Cache-Control": "no-cache"}


def viewer_headers(nonce: str) -> dict[str, str]:
    """Headers of a viewer page whose scripts carry this nonce."""
    return {
        "Content-Security-Policy": (
            f"sandbox allow-scripts; default-src 'none'; script-src 'nonce-{nonce}'; "
            "style-src 'unsafe-inline'; img-src blob: data:; font-src data:; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'self'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }


def mount(app: FastAPI, frontend_dir: Path) -> None:
    """Serve frontend_dir for every GET path outside /api; nothing when it does not exist."""
    if not (frontend_dir / "index.html").is_file():
        log.warning(
            "frontend not built: no index.html in %s; serving the API only", frontend_dir.resolve()
        )
        return
    root = frontend_dir.resolve()
    index = root / "index.html"

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def frontend(path: str, request: Request) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)  # an unknown API path stays a JSON 404
        file = _file(root, path)
        if file is None and path.startswith(f"{VIEWER_DIR}/"):
            raise HTTPException(404)  # not the app: the viewer's paths are open (auth.py)
        if file is None and path.startswith(f"{MAP_DIR}/"):
            raise HTTPException(404)
        if file is None or file == index:
            return FileResponse(index, headers=INDEX_HEADERS)
        top = file.relative_to(root).parts[0]
        if top == VIEWER_DIR:
            if file.suffix == ".html":
                nonce = secrets.token_urlsafe(18)
                page = file.read_text("utf-8").replace(NONCE_PLACEHOLDER, nonce)
                return HTMLResponse(page, headers=viewer_headers(nonce))
            return FileResponse(file, headers=VIEWER_FILE_HEADERS)
        if top == MAP_DIR:
            response = FileResponse(file, headers=MAP_HEADERS, stat_result=file.stat())
            if request.headers.get("if-none-match") == response.headers["etag"]:
                return Response(
                    status_code=304, headers={**MAP_HEADERS, "etag": response.headers["etag"]}
                )
            return response
        return FileResponse(file, headers=ASSET_HEADERS if top == "assets" else None)


def _file(root: Path, path: str) -> Path | None:
    """The file at path below root; None for directories, missing files and paths outside it."""
    try:
        file = (root / path).resolve()
    except (OSError, ValueError):  # ValueError: a NUL character
        return None
    return file if file.is_relative_to(root) and file.is_file() else None

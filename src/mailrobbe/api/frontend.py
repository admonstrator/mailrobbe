"""Serving the built frontend: static files, index.html for client-side routes (D24)."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

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
    async def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)  # an unknown API path stays a JSON 404
        file = _file(root, path)
        if file is None or file == index:
            return FileResponse(index, headers=INDEX_HEADERS)
        assets = file.relative_to(root).parts[0] == "assets"
        return FileResponse(file, headers=ASSET_HEADERS if assets else None)


def _file(root: Path, path: str) -> Path | None:
    """The file at path below root; None for directories, missing files and paths outside it."""
    try:
        file = (root / path).resolve()
    except (OSError, ValueError):  # ValueError: a NUL character
        return None
    return file if file.is_relative_to(root) and file.is_file() else None

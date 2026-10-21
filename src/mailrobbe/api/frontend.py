"""Serving the built frontend: static files, index.html for client-side routes (D24)."""

from pathlib import Path

from fastapi import FastAPI


def mount(app: FastAPI, frontend_dir: Path) -> None:
    """Serve frontend_dir for every GET path outside /api; nothing when it does not exist."""

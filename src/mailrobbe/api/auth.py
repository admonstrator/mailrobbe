"""Optional HTTP Basic Auth for everything but /api/health (D4, D24)."""

from fastapi import FastAPI

from mailrobbe.config import Settings


def install(app: FastAPI, settings: Settings) -> None:
    """Require MAILROBBE_BASIC_AUTH_USER/PASSWORD on every request when both are set."""

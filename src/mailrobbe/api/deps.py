"""Request dependencies shared by the routers: database session, settings, editor, errors."""

import logging
import unicodedata
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import ApiErrorDetail, ErrorCode
from mailrobbe.config import Settings
from mailrobbe.stored_settings import apply, stored_rows

log = logging.getLogger(__name__)


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


async def refresh_settings(app: FastAPI) -> None:
    """The environment's settings with the stored ones over them (D313) into app.state.settings,
    at the server's start and after a save. When the database does not answer they stay as they
    are, and the next request needing them tries again."""
    state = app.state
    try:
        async with state.sessionmaker() as session:
            rows = await stored_rows(session)
    except (SQLAlchemyError, OSError) as error:
        log.warning("stored settings not read, the environment's apply: %s", error)
        return
    state.settings = apply(state.env_settings, {name: row.value for name, row in rows.items()})
    state.settings_read = True


async def _settings(request: Request) -> Settings:
    if not request.app.state.settings_read:
        await refresh_settings(request.app)
    settings: Settings = request.app.state.settings
    return settings


# The name the web UI sends with every write (D54): percent-encoded UTF-8, since header values
# are Latin-1. No authentication; it only gives notes and marks an author.
EDITOR_HEADER = "X-Mailrobbe-Editor"
EDITOR_LIMIT = 100  # characters kept


def editor_name(raw: str | None) -> str | None:
    """The editor's name from the header value: decoded, without control characters, trimmed
    and cut to EDITOR_LIMIT; None when nothing is left."""
    if raw is None:
        return None
    text = unquote(raw, errors="replace")
    text = "".join(" " if unicodedata.category(char)[0] == "C" else char for char in text)
    return " ".join(text.split())[:EDITOR_LIMIT].strip() or None


def _editor(
    raw: Annotated[str | None, Header(alias=EDITOR_HEADER, include_in_schema=False)] = None,
) -> str | None:
    return editor_name(raw)


Session = Annotated[AsyncSession, Depends(_session)]
AppSettings = Annotated[Settings, Depends(_settings)]
Editor = Annotated[str | None, Depends(_editor)]


def api_error(status_code: int, code: ErrorCode, message: str) -> HTTPException:
    """An HTTPException with the {"detail": {"code", "message"}} body of the contract."""
    return HTTPException(status_code, ApiErrorDetail(code=code, message=message).model_dump())

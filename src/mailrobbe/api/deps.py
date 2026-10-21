"""Request dependencies shared by the routers: database session, settings, editor, errors."""

import unicodedata
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import unquote

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import ApiErrorDetail, ErrorCode
from mailrobbe.config import Settings


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def _settings(request: Request) -> Settings:
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

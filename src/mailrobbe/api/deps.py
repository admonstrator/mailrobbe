"""Request dependencies shared by the routers: database session, settings, error responses."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import ApiErrorDetail, ErrorCode
from mailrobbe.config import Settings


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


Session = Annotated[AsyncSession, Depends(_session)]
AppSettings = Annotated[Settings, Depends(_settings)]


def api_error(status_code: int, code: ErrorCode, message: str) -> HTTPException:
    """An HTTPException with the {"detail": {"code", "message"}} body of the contract."""
    return HTTPException(status_code, ApiErrorDetail(code=code, message=message).model_dump())

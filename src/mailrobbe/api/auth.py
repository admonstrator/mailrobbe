"""Optional HTTP Basic Auth for everything but /api/health (D4, D24)."""

import base64
import binascii
import secrets

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mailrobbe.config import Settings

OPEN_PATH = "/api/health"  # for container health checks, GET only


def install(app: FastAPI, settings: Settings) -> None:
    """Require MAILROBBE_BASIC_AUTH_USER/PASSWORD on every request when both are set."""
    user = settings.basic_auth_user
    password = settings.basic_auth_password.get_secret_value()
    if not user and not password:
        return
    if not user or not password:
        raise ValueError(
            "MAILROBBE_BASIC_AUTH_USER and MAILROBBE_BASIC_AUTH_PASSWORD must be set together; "
            "leave both empty to turn Basic Auth off"
        )
    app.add_middleware(BasicAuth, user=user.encode(), password=password.encode())


class BasicAuth:
    """ASGI middleware: requests without the configured credentials get a 401."""

    def __init__(self, app: ASGIApp, *, user: bytes, password: bytes) -> None:
        self.app = app
        self._user = user
        self._password = password

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan" or self._open(scope) or self._authorized(scope):
            await self.app(scope, receive, send)
        elif scope["type"] == "http":
            denied = JSONResponse(
                {"detail": "authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Mailrobbe", charset="UTF-8"'},
            )
            await denied(scope, receive, send)
        else:  # a websocket: refused before the handshake completes
            await send({"type": "websocket.close", "code": 1008})

    @staticmethod
    def _open(scope: Scope) -> bool:
        return scope["type"] == "http" and (scope["method"], scope["path"]) == ("GET", OPEN_PATH)

    def _authorized(self, scope: Scope) -> bool:
        header = next((value for name, value in scope["headers"] if name == b"authorization"), b"")
        scheme, _, token = header.partition(b" ")
        if scheme.lower() != b"basic":
            return False
        try:
            credentials = base64.b64decode(token.strip(), validate=True)
        except binascii.Error:
            return False
        user, colon, password = credentials.partition(b":")
        # Both comparisons always run, so the time taken tells nothing about which one failed.
        user_ok = secrets.compare_digest(user, self._user)
        password_ok = secrets.compare_digest(password, self._password)
        return bool(colon) and user_ok and password_ok

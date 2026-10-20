from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from mailspider.config import Settings, get_settings
from mailspider.db.session import create_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title="Mailspider", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> JSONResponse:
        try:
            async with engine.connect() as connection:
                revision = None
                if await connection.scalar(text("SELECT to_regclass('alembic_version')")):
                    revision = await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
        except (SQLAlchemyError, OSError):
            return JSONResponse(
                {"status": "error", "database": "unavailable", "schema_revision": None},
                status_code=503,
            )
        return JSONResponse({"status": "ok", "database": "ok", "schema_revision": revision})

    return app

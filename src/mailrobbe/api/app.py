from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from mailrobbe.api import auth, detail, frontend, mails, stats
from mailrobbe.config import Settings, get_settings
from mailrobbe.db.session import create_engine, create_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title="Mailrobbe", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)

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

    app.include_router(stats.router)
    app.include_router(mails.router)  # before detail: /api/mails/summary is no mail id
    app.include_router(detail.router)
    auth.install(app, settings)
    frontend.mount(app, settings.frontend_dir)  # last: its catch-all must not shadow /api
    return app

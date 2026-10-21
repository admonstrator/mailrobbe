from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError

from mailrobbe.api import (
    auth,
    detail,
    documents,
    entities,
    exports,
    frontend,
    graph,
    imports,
    mails,
    marks,
    notes,
    persons,
    processes,
    research,
    stats,
)
from mailrobbe.config import Settings, get_settings
from mailrobbe.db.session import create_engine, create_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    event.listen(engine.sync_engine, "connect", _plan_each_query)

    runs = processes.Runs()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await runs.stop()  # the dashboard's runs end with the server (D46)
        await engine.dispose()

    app = FastAPI(title="Mailrobbe", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.runs = runs

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
    app.include_router(research.router)
    app.include_router(marks.router)  # before detail: /api/mails/bulk is no mail id
    app.include_router(notes.router)
    app.include_router(exports.router)
    app.include_router(entities.router)  # before detail: /api/mails/facets is no mail id
    app.include_router(detail.router)
    app.include_router(persons.router)
    app.include_router(graph.router)
    app.include_router(imports.router)
    app.include_router(documents.router)  # /api/documents/summary before {id}, as for mails
    auth.install(app, settings)
    frontend.mount(app, settings.frontend_dir)  # last: its catch-all must not shadow /api
    return app


def _plan_each_query(dbapi_connection: Any, _record: Any) -> None:
    """Plan every statement for its parameters. A filter's values (an address part, a word, a
    date) decide the best plan, and the generic plan PostgreSQL switches to after five runs of a
    prepared statement made filtered pages several times slower. Set outside a transaction, so
    it lasts as long as the pooled connection."""
    dbapi_connection.run_async(
        lambda connection: connection.execute("SET plan_cache_mode = force_custom_plan")
    )

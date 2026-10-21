from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str, application_name: str | None = None) -> AsyncEngine:
    # asyncpg waits 60 s for a connection by default; fail fast so health checks stay responsive.
    # JIT off (D35): it compiles every query the planner deems costly and adds 300 ms or more to
    # filters that then run in 60 ms. application_name names the connections in pg_stat_activity
    # (a run's, jobs.application_name).
    server_settings = {"jit": "off"}
    if application_name is not None:
        server_settings["application_name"] = application_name
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"timeout": 5, "server_settings": server_settings},
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)

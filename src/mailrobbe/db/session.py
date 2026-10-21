from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    # asyncpg waits 60 s for a connection by default; fail fast so health checks stay responsive.
    # JIT off (D35): it compiles every query the planner deems costly and adds 300 ms or more to
    # filters that then run in 60 ms.
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"timeout": 5, "server_settings": {"jit": "off"}},
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    # asyncpg waits 60 s for a connection by default; fail fast so health checks stay responsive.
    return create_async_engine(database_url, pool_pre_ping=True, connect_args={"timeout": 5})


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)

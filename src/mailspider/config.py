import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from MAILSPIDER_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="MAILSPIDER_", env_ignore_empty=True)

    database_url: str = "postgresql+asyncpg://mailspider:mailspider@localhost:5432/mailspider"
    mbox_dir: Path = Path("/data/mbox")
    host: str = "0.0.0.0"
    port: int = 8000
    # Sized for the target machine: about 10 GB RAM shared by Postgres and the importer.
    import_workers: int = min(8, os.cpu_count() or 1)


def get_settings() -> Settings:
    return Settings()

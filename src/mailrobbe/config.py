import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from MAILROBBE_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="MAILROBBE_", env_ignore_empty=True)

    database_url: str = "postgresql+asyncpg://mailrobbe:mailrobbe@localhost:5432/mailrobbe"
    mbox_dir: Path = Path("/data/mbox")
    host: str = "0.0.0.0"
    port: int = 8000
    # Sized for the target machine: about 10 GB RAM shared by Postgres and the importer.
    import_workers: int = min(8, os.cpu_count() or 1)
    # DKIM key lookups (SPEC 3.4, mailrobbe/dkim/checker.py). The override table answers the
    # names it lists; unset means mbox_dir/_generator/dns_override.json when that file exists.
    dkim_dns_override: Path | None = None
    dkim_offline: bool = False  # no DNS lookups: keys not in the cache become temp_error
    dkim_dns_timeout: float = 5.0  # seconds per key name, retries included
    dkim_nameservers: str = ""  # comma-separated IP addresses; empty: the system resolver


def get_settings() -> Settings:
    return Settings()

import os
from pathlib import Path

from pydantic import ByteSize, SecretStr
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
    # Attachments above this size get metadata only, no SHA-256 (SPEC 3.5). Accepts "50MiB".
    import_attachment_hash_limit: ByteSize = ByteSize(50 * 1024**2)
    # Mails above this size are imported with their headers only, so a damaged file without
    # separators cannot exhaust memory. Parsing needs up to about 8 times a mail's size, so the
    # default keeps one worker below about 1 GB; mail servers rarely accept more than 150 MB.
    import_max_mail_size: ByteSize = ByteSize(128 * 1024**2)
    # Text extraction of attachments (D72): larger documents are not read; each extraction runs
    # in a child process that is stopped after the timeout (seconds) and may use this much more
    # memory (Linux).
    attachment_text_max_size: ByteSize = ByteSize(50 * 1024**2)
    attachment_text_timeout: float = 60.0
    attachment_text_memory: ByteSize = ByteSize(1024**3)
    # Previews in the browser (D120 to D124): converted documents and decoded audio and video are
    # cached here by SHA-256 (deleting the directory is always safe); attachments above
    # preview_max_size are download only. A conversion runs in a process of its own that is
    # stopped after preview_timeout seconds and may use preview_memory bytes (Linux); at most
    # preview_workers run at once.
    preview_dir: Path = Path("data/previews")
    preview_max_size: ByteSize = ByteSize(50 * 1024**2)
    preview_timeout: float = 60.0
    preview_memory: ByteSize = ByteSize(1024**3)
    preview_workers: int = 2
    # DKIM key lookups (SPEC 3.4, mailrobbe/dkim/checker.py). The override table answers the
    # names it lists; unset means mbox_dir/_generator/dns_override.json when that file exists.
    dkim_dns_override: Path | None = None
    dkim_offline: bool = False  # no DNS lookups: keys not in the cache become temp_error
    dkim_dns_timeout: float = 5.0  # seconds per key name, retries included
    dkim_nameservers: str = ""  # comma-separated IP addresses; empty: the system resolver
    # Web UI and API (milestone 4). Basic Auth (D4) is on when both are set, an error when only
    # one is; /api/health stays open for container health checks.
    basic_auth_user: str = ""
    basic_auth_password: SecretStr = SecretStr("")
    # The built frontend (npm run build in frontend/); relative paths are taken from the working
    # directory, /app in the Docker image. Missing: the API runs without the UI.
    frontend_dir: Path = Path("frontend/dist")
    # Comma-separated domains of the archive owner for the "Nur extern <-> intern" filter (D21);
    # their subdomains count too. Empty: the filter is not offered.
    internal_domains: str = ""
    # Time budget for exact hit counts of a filtered mail list; above it the count is a lower
    # bound (D19).
    api_count_timeout: float = 2.0
    # global_stats older than this many seconds are recomputed when the API reads them (D19).
    stats_max_age: int = 300


def get_settings() -> Settings:
    return Settings()

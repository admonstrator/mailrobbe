import os
from pathlib import Path
from typing import Literal

from pydantic import ByteSize, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from MAILROBBE_* environment variables. All but the ones
    stored_settings.FIXED names can be changed on the page "Einstellungen" too, which stores them
    over the environment (D313)."""

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
    # Protected and packed attachments (D230 to D237). Containers (ZIP, 7z, attached mails) are
    # unpacked within these bounds, in a child process with the text extraction's limits; entries
    # beyond them are listed, not unpacked. Passwords found in the archive or typed in by hand are
    # tried on every locked document, each tier up to password_seconds (D235); no word lists.
    archive_max_members: int = 1000
    archive_max_size: ByteSize = ByteSize(500 * 1024**2)
    password_seconds: float = 10.0
    # DKIM key lookups (SPEC 3.4, mailrobbe/dkim/checker.py). The override table answers the
    # names it lists; unset means mbox_dir/_generator/dns_override.json when that file exists.
    dkim_dns_override: Path | None = None
    dkim_offline: bool = False  # no DNS lookups: keys not in the cache become temp_error
    dkim_dns_timeout: float = 5.0  # seconds per key name, retries included
    dkim_nameservers: str = ""  # comma-separated IP addresses; empty: the system resolver
    # Keys of deleted selectors (D102): the ZK Email DKIM archive, asked only on request, one
    # request per domain; "off" switches it off (an empty variable counts as unset).
    dkim_key_archive_url: str = "https://archive.zk.email"
    dkim_key_archive_timeout: float = 30.0  # seconds per request
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
    # Signals (D131, D133): the time zone of night hours and weekends, a name PostgreSQL knows
    # (pg_timezone_names), and domains of private mail providers beside the list in
    # themes.toml, comma-separated.
    timezone: str = "Europe/Berlin"
    private_domains: str = ""
    # Time budget for exact hit counts of a filtered mail list; above it the count is a lower
    # bound (D19).
    api_count_timeout: float = 2.0
    # global_stats older than this many seconds are recomputed when the API reads them (D19).
    stats_max_age: int = 300
    # Standard blocks (D225): a paragraph at the end of at least this many mails that are no
    # duplicates, used by their senders twice on average, is detected as one at the next import.
    block_min_mails: int = Field(default=25, ge=2)
    # The detail map (D245, D246): downloaded on request into map_dir, from the newest daily
    # build of Protomaps ("protomaps"), from the https URL of another PMTiles v3 file, or not at
    # all ("off"); map_timeout is seconds per request, retries not counted.
    map_dir: Path = Path("data/maps")
    map_source: str = "protomaps"
    map_timeout: float = 60.0
    # AI services (D180 to D189). The vision service reads page images (OCR, D182): an
    # OpenAI-compatible base URL such as http://host.docker.internal:1234/v1 (LM Studio) or an
    # Ollama one such as http://host.docker.internal:11434; empty: no vision service. The
    # protocol is detected unless set. A service outside the own machine and private networks is
    # refused unless ai_allow_remote (D181); then a run stops after ai_remote_token_budget
    # tokens. ai_concurrency requests per service at once (pages read by the vision model,
    # summaries, groups of the alias check, D327), ai_timeout seconds each.
    ai_vision_url: str = ""
    ai_vision_model: str = ""
    ai_vision_key: SecretStr = SecretStr("")
    ai_vision_protocol: Literal["auto", "openai", "ollama"] = "auto"
    ai_allow_remote: bool = False
    ai_remote_token_budget: int = Field(default=2_000_000, ge=0)
    ai_concurrency: int = Field(default=1, ge=1)
    ai_timeout: float = 600.0
    # OCR (D182): "auto" reads scanned PDFs with Tesseract and images with the vision service
    # when one is set (else Tesseract too), and reads pages Tesseract is unsure of (mean word
    # confidence below ai_ocr_uncertain, 0 to 100) again with it; "tesseract" or "vision" use
    # only that engine. At most ai_ocr_max_pages pages per document and pass; the rest can be
    # continued. ai_ocr_languages are Tesseract's (-l).
    ai_ocr_engine: Literal["auto", "tesseract", "vision"] = "auto"
    ai_ocr_max_pages: int = Field(default=50, ge=1)
    ai_ocr_languages: str = "deu+eng"
    ai_ocr_uncertain: float = Field(default=60.0, ge=0, le=100)
    # Transcription (D290 to D293): Parakeet TDT 0.6B v3 in the container, on the CPU through
    # ONNX Runtime. Its files (about 670 MB) are downloaded once from Hugging Face into
    # ai_model_dir by the first run that needs them, or put there by hand. At most
    # ai_transcribe_max_minutes minutes per recording and pass; ai_transcribe_threads CPU threads
    # (0: the CPUs, up to four); lines whose mean token probability is below
    # ai_transcribe_uncertain (0 to 1) are marked uncertain.
    ai_model_dir: Path = Path("data/models")
    ai_transcribe_max_minutes: int = Field(default=180, ge=1)
    ai_transcribe_threads: int = Field(default=0, ge=0)
    ai_transcribe_uncertain: float = Field(default=0.8, ge=0, le=1)
    # Summaries and AI tags (M17, D300): the text service, set like the vision service (it may
    # be the same server with another model); empty: no "Zusammenfassen". ai_context_tokens is
    # the context the model was loaded with (LM Studio's slider, Ollama's num_ctx): a longer
    # text is summarised in parts that fit it (D303).
    ai_text_url: str = ""
    ai_text_model: str = ""
    ai_text_key: SecretStr = SecretStr("")
    ai_text_protocol: Literal["auto", "openai", "ollama"] = "auto"
    ai_context_tokens: int = Field(default=4096, ge=2048)


def get_settings() -> Settings:
    return Settings()

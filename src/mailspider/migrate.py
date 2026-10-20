from alembic import command
from alembic.config import Config

from mailspider.config import get_settings


def alembic_config(database_url: str | None = None) -> Config:
    """Alembic configuration without alembic.ini, so it works from the installed package."""
    config = Config()
    config.set_main_option("script_location", "mailspider:migrations")
    config.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    return config


def upgrade(revision: str = "head", database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(revision: str, database_url: str | None = None) -> None:
    command.downgrade(alembic_config(database_url), revision)

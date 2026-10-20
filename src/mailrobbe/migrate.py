from alembic import command
from alembic.config import Config

from mailrobbe.config import get_settings


def alembic_config(database_url: str | None = None) -> Config:
    """Alembic configuration without alembic.ini, so it works from the installed package."""
    config = Config()
    config.set_main_option("script_location", "mailrobbe:migrations")
    url = database_url or get_settings().database_url
    # configparser interpolation: a percent-encoded password would otherwise raise.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(revision: str = "head", database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(revision: str, database_url: str | None = None) -> None:
    command.downgrade(alembic_config(database_url), revision)

"""The settings of the page "Einstellungen" (D313, D314): stored in the table `setting`, over the
environment.

config.Settings reads the MAILROBBE_* variables. Every setting but the FIXED ones can also be
changed in the web UI, which stores it in `setting` as JSON (json_value); a stored value wins over
the environment, and deleting it brings back the environment's value or the default. The FIXED
ones stay in the environment: the database's address is needed to read the table, Basic Auth
guards the page itself, the paths, host and port belong to the container, and whether archive
content may leave this machine for an AI service is not a click away.

Who reads the table: the API at its first request and after every save (api.configuration), and a
command started on the command line at its start (command_settings). A run the dashboard starts
gets the server's settings in its environment (api.processes.child_environment) with the run's own
choices over them, so it reads nothing itself. A run keeps the values it started with.
"""

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from pydantic import ByteSize, SecretStr, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.config import Settings, get_settings
from mailrobbe.db.models import Setting
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.enums import JobOrigin

log = logging.getLogger(__name__)

FIXED = frozenset(
    {
        "database_url",
        "basic_auth_user",
        "basic_auth_password",
        "host",
        "port",
        "mbox_dir",
        "frontend_dir",
        "preview_dir",
        "map_dir",
        "ai_model_dir",
        "dkim_dns_override",  # tests and generated archives only
        # Sending archive content off this machine stays a decision of the environment (D181).
        "ai_allow_remote",
        "ai_remote_token_budget",
    }
)
EDITABLE = tuple(name for name in Settings.model_fields if name not in FIXED)


def json_value(value: object) -> Any:
    """A setting's value as the table and the API hold it: a secret's text, a size in bytes."""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, ByteSize):
        return int(value)
    return value


def validate(base: Settings, values: Mapping[str, Any]) -> Settings:
    """base with values over it, checked as the environment's are; ValidationError."""
    return type(base).model_validate({**base.model_dump(), **values})


def apply(base: Settings, stored: Mapping[str, Any]) -> Settings:
    """base with the stored values of EDITABLE settings over it. A value the settings no longer
    accept (a bound tightened by an update) is logged and left out, so a row never stops the
    server or a run."""
    values = {name: value for name, value in stored.items() if name in EDITABLE}
    while True:
        try:
            return validate(base, values)
        except ValidationError as error:
            bad = {str(entry["loc"][0]) for entry in error.errors() if entry["loc"]} & set(values)
            if not bad:
                raise
            for name in sorted(bad):
                log.warning("the stored setting %s is not accepted and left out", name)
                del values[name]


async def stored_rows(session: AsyncSession) -> dict[str, Setting]:
    """The rows of `setting` by name; none before migration 0022."""
    if not await session.scalar(text("SELECT to_regclass('setting') IS NOT NULL")):
        return {}
    return {row.name: row for row in await session.scalars(select(Setting))}


async def load(base: Settings) -> Settings:
    """base with the stored settings over it; base alone when the database does not answer (the
    command then reports that itself)."""
    engine = create_engine(base.database_url)
    try:
        async with create_sessionmaker(engine)() as session:
            rows = await stored_rows(session)
    except (SQLAlchemyError, OSError) as error:
        log.debug("stored settings not read: %s", error)
        return base
    finally:
        await engine.dispose()
    return apply(base, {name: row.value for name, row in rows.items()})


def command_settings(origin: JobOrigin) -> Settings:
    """The settings of a command (module docstring): the environment's, and for one started on
    the command line the stored ones over them."""
    settings = get_settings()
    if origin is JobOrigin.UI:
        return settings
    return asyncio.run(load(settings))

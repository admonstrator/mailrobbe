"""The migrations against SPEC 3.3, and the ORM models against the migrated schema."""

import asyncio
import io
from enum import StrEnum
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from mailspider import migrate
from mailspider.db import models  # noqa: F401  (registers all tables on the metadata)
from mailspider.db.base import Base
from mailspider.enums import DkimStatus, DnsStatus, MboxStatus, ParticipationRole

TABLES = {
    "mbox_file",
    "mail",
    "mail_header",
    "person",
    "person_email",
    "participation",
    "attachment",
    "dkim_result",
    "dns_cache",
    "import_error",
    "edge",
    "edge_year",
    "person_stats",
    "person_year",
    "global_stats",
}

ENUMS: dict[str, tuple[type[StrEnum], list[str]]] = {
    "dkim_status": (DkimStatus, ["pass", "fail", "no_key", "unsigned", "temp_error"]),
    "participation_role": (ParticipationRole, ["from", "to", "cc", "bcc"]),
    "mbox_status": (MboxStatus, ["pending", "running", "paused", "done", "error"]),
    "dns_status": (DnsStatus, ["found", "not_found", "temp_error"]),
}

# pg_get_indexdef() output: method, column order and operator class in one string.
INDEXES = {
    "ix_mail_date_utc": "CREATE INDEX ix_mail_date_utc ON public.mail USING btree (date_utc)",
    "ix_mail_message_id": "CREATE INDEX ix_mail_message_id ON public.mail USING btree (message_id)",
    "ix_participation_person_id_role": "CREATE INDEX ix_participation_person_id_role "
    "ON public.participation USING btree (person_id, role, mail_id)",
    "ix_mail_tsv": "CREATE INDEX ix_mail_tsv ON public.mail USING gin (tsv)",
    "uq_person_canonical_email": "CREATE UNIQUE INDEX uq_person_canonical_email "
    "ON public.person USING btree (canonical_email)",
    "ix_person_domain": "CREATE INDEX ix_person_domain ON public.person USING btree (domain)",
    "ix_person_canonical_email_trgm": "CREATE INDEX ix_person_canonical_email_trgm "
    "ON public.person USING gin (canonical_email gin_trgm_ops)",
    "ix_person_display_name_trgm": "CREATE INDEX ix_person_display_name_trgm "
    "ON public.person USING gin (display_name gin_trgm_ops)",
    "ix_person_email_email_trgm": "CREATE INDEX ix_person_email_email_trgm "
    "ON public.person_email USING gin (email gin_trgm_ops)",
    "ix_edge_person_b": "CREATE INDEX ix_edge_person_b ON public.edge USING btree (person_b)",
    "ix_edge_mails_total": "CREATE INDEX ix_edge_mails_total "
    "ON public.edge USING btree (mails_total)",
    "pk_edge": "CREATE UNIQUE INDEX pk_edge ON public.edge USING btree (person_a, person_b)",
}

# Everything in the database apart from system catalogs: relations (tables, indexes, sequences),
# enum types and extensions.
SCHEMA_OBJECTS = """
    SELECT 'relation', relname FROM pg_class WHERE relnamespace = 'public'::regnamespace
    UNION ALL
    SELECT 'enum', typname FROM pg_type
    WHERE typnamespace = 'public'::regnamespace AND typtype = 'e'
    UNION ALL
    SELECT 'extension', extname FROM pg_extension
"""


async def _rows(connection: AsyncConnection | AsyncSession, sql: str) -> list[tuple[Any, ...]]:
    result = await connection.execute(text(sql))
    return [tuple(row) for row in result]


def _schema_diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    return list(compare_metadata(context, Base.metadata))


@pytest.mark.db
async def test_upgrade_creates_all_tables(db_session: AsyncSession) -> None:
    tables = await db_session.scalars(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    assert set(tables) == {*TABLES, "alembic_version"}
    assert await db_session.scalar(text("SELECT version_num FROM alembic_version")) == "0001"


@pytest.mark.db
async def test_enums_have_exactly_the_python_values(db_session: AsyncSession) -> None:
    rows = await _rows(
        db_session,
        """
        SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)
        FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typnamespace = 'public'::regnamespace
        GROUP BY t.typname
        """,
    )
    assert dict(rows) == {name: values for name, (_, values) in ENUMS.items()}
    for enum_cls, values in ENUMS.values():
        assert [member.value for member in enum_cls] == values


@pytest.mark.db
async def test_pg_trgm_is_installed(db_session: AsyncSession) -> None:
    extensions = await db_session.scalars(text("SELECT extname FROM pg_extension"))
    assert "pg_trgm" in set(extensions)


@pytest.mark.db
async def test_named_indexes_have_method_and_operator_class(db_session: AsyncSession) -> None:
    rows = await _rows(
        db_session,
        """
        SELECT c.relname, pg_get_indexdef(i.indexrelid)
        FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
        WHERE c.relnamespace = 'public'::regnamespace
        """,
    )
    definitions = dict(rows)
    assert {name: definitions.get(name) for name in INDEXES} == INDEXES
    primary_key = await db_session.scalar(
        text(
            """
            SELECT indexrelid::regclass::text FROM pg_index
            WHERE indrelid = 'edge'::regclass AND indisprimary
            """
        )
    )
    assert primary_key == "pk_edge"


@pytest.mark.db
async def test_models_match_migrated_schema(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    assert await connection.run_sync(_schema_diff) == []


# compare_metadata ignores check constraints and the names of primary and foreign keys.
@pytest.mark.db
async def test_constraint_names_match_models(db_session: AsyncSession) -> None:
    expected = {
        (table.name, str(constraint.name))
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
    }
    rows = await _rows(
        db_session,
        """
        SELECT conrelid::regclass::text, conname FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace AND contype IN ('c', 'f', 'p', 'u')
          AND conrelid <> 'alembic_version'::regclass
        """,
    )
    assert set(rows) == expected


@pytest.mark.db
async def test_downgrade_to_base_and_upgrade_again(empty_database_url: str) -> None:
    async def schema_objects() -> set[tuple[Any, ...]]:
        engine = create_async_engine(empty_database_url, poolclass=pool.NullPool)
        try:
            async with engine.connect() as connection:
                return set(await _rows(connection, SCHEMA_OBJECTS))
        finally:
            await engine.dispose()

    await asyncio.to_thread(migrate.upgrade, "head", empty_database_url)
    migrated = await schema_objects()
    assert ("extension", "pg_trgm") in migrated

    await asyncio.to_thread(migrate.downgrade, "base", empty_database_url)
    assert await schema_objects() == {
        ("relation", "alembic_version"),
        ("relation", "alembic_version_pkc"),
        ("extension", "plpgsql"),
    }

    await asyncio.to_thread(migrate.upgrade, "head", empty_database_url)
    assert await schema_objects() == migrated


def test_alembic_config_keeps_percent_encoded_url() -> None:
    # Passwords with special characters are percent-encoded; % is configparser syntax.
    url = "postgresql+asyncpg://mailspider:p%40ss@db:5432/mailspider"
    assert migrate.alembic_config(url).get_main_option("sqlalchemy.url") == url


def test_upgrade_renders_offline_without_database() -> None:
    # Offline mode only takes the dialect from the URL; nothing listens there.
    config = migrate.alembic_config("postgresql+asyncpg://nobody:secret@127.0.0.1:1/none")
    config.output_buffer = buffer = io.StringIO()
    command.upgrade(config, "head", sql=True)
    sql = buffer.getvalue()

    assert sql.count("CREATE TABLE ") == len(TABLES) + 1
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm;" in sql
    assert (
        "CREATE TYPE dkim_status AS ENUM ('pass', 'fail', 'no_key', 'unsigned', 'temp_error');"
        in sql
    )
    assert "CREATE INDEX ix_mail_tsv ON mail USING gin (tsv);" in sql
    assert "INSERT INTO alembic_version (version_num) VALUES ('0001')" in sql

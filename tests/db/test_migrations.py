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

from mailrobbe import migrate
from mailrobbe.db import models  # noqa: F401  (registers all tables on the metadata)
from mailrobbe.db.base import Base
from mailrobbe.enums import (
    AiResultState,
    AiTaskKind,
    AiTaskStatus,
    AliasTier,
    AliasVerdict,
    DkimStatus,
    DnsStatus,
    DocumentKind,
    DocumentMembersStatus,
    DocumentMemberStatus,
    DocumentMetadataStatus,
    DocumentProtection,
    DocumentTextStatus,
    EntityKind,
    JobKind,
    JobStatus,
    KeyOrigin,
    MboxStatus,
    ParticipationRole,
    PasswordTier,
    PersonKind,
    ReviewStatus,
    TextOrigin,
)

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
    "alias_suggestion",
    "alias_dismissal",
    "job",
    "mail_mark",
    "note",
    "tag",
    "mail_tag",
    "collection",
    "collection_mail",
    "saved_search",
    "mail_export",
    "document",
    "entity",
    "mail_entity",
    "document_entity",
    "mail_entity_scan",
    "document_entity_scan",
    "dkim_key",
    "dkim_key_lookup",
    "dkim_key_evidence",
    "topic_state",
    "topic_term",
    "topic_period",
    "topic_period_term",
    "topic_cluster",
    "topic_cluster_term",
    "topic_cluster_month",
    "mail_signal",
    "person_signal",
    "merge_batch",
    "person_merge",
    "person_merge_member",
    "mail_near",
    "calendar_scan",
    "calendar_event",
    "calendar_attendee",
    "person_label",
    "hide_rule",
    "mail_hidden",
    "mail_paragraph_scan",
    "mail_paragraph",
    "paragraph_block",
    "paragraph_override",
    "document_member",
    "password",
    "password_finding",
    "document_password",
    "ai_result",
    "ai_task",
    "ai_calibration",
    "ai_send_log",
    "ai_tag",
    "ai_tag_link",
    "ai_theme_hint",
    "setting",
    "alias_check",
    "person_question",
}

ENUMS: dict[str, tuple[type[StrEnum], list[str]]] = {
    "dkim_status": (
        DkimStatus,
        ["pass", "consistent", "fail", "no_key", "unsigned", "temp_error"],
    ),
    "participation_role": (ParticipationRole, ["from", "to", "cc", "bcc"]),
    "mbox_status": (MboxStatus, ["pending", "running", "paused", "done", "error"]),
    "dns_status": (DnsStatus, ["found", "not_found", "temp_error"]),
    "person_kind": (PersonKind, ["list", "automated"]),
    "alias_tier": (AliasTier, ["certain", "uncertain"]),
    "alias_verdict": (AliasVerdict, ["same", "different", "unclear"]),
    "document_metadata_status": (
        DocumentMetadataStatus,
        ["pending", "found", "empty", "unsupported", "too_large", "failed"],
    ),
    "job_kind": (JobKind, ["import", "dkim", "dkim_keys", "map", "ai"]),
    "job_status": (JobStatus, ["running", "done", "stopped", "failed"]),
    "review_status": (ReviewStatus, ["seen", "relevant", "irrelevant"]),
    "key_origin": (KeyOrigin, ["dns", "observed", "documented", "reconstructed"]),
    "document_kind": (
        DocumentKind,
        [
            "pdf",
            "document",
            "spreadsheet",
            "presentation",
            "text",
            "email",
            "image",
            "archive",
            "media",
            "other",
        ],
    ),
    "document_text_status": (
        DocumentTextStatus,
        [
            "pending",
            "text",
            "empty",
            "scanned",
            "encrypted",
            "unsupported",
            "too_large",
            "failed",
            "timeout",
            "unreadable",
        ],
    ),
    "entity_kind": (
        EntityKind,
        [
            "amount",
            "iban",
            "account",
            "organization",
            "person",
            "place",
            "phone",
            "email",
            "url",
            "domain",
            "date",
            "term",
        ],
    ),
    "document_protection": (DocumentProtection, ["locked", "open"]),
    "document_members_status": (
        DocumentMembersStatus,
        ["done", "locked", "too_deep", "unsupported", "failed", "unreadable"],
    ),
    "document_member_status": (
        DocumentMemberStatus,
        ["document", "locked", "too_large", "too_many", "failed"],
    ),
    "password_tier": (
        PasswordTier,
        ["manual", "mail", "thread", "contacts", "attachments", "opened", "archive", "typed"],
    ),
    "text_origin": (TextOrigin, ["extracted", "ocr", "transcript"]),
    "ai_task_kind": (AiTaskKind, ["ocr", "transcribe", "summarize"]),
    "ai_task_status": (AiTaskStatus, ["waiting", "running", "done", "failed", "cancelled"]),
    "ai_result_state": (AiResultState, ["valid", "replaced", "discarded"]),
}

# pg_get_indexdef() output: method, column order and operator class in one string.
INDEXES = {
    "ix_mail_date_utc": "CREATE INDEX ix_mail_date_utc ON public.mail USING btree (date_utc)",
    "ix_mail_message_id": "CREATE INDEX ix_mail_message_id ON public.mail USING btree (message_id)",
    "ix_participation_person_id_role": "CREATE INDEX ix_participation_person_id_role "
    "ON public.participation USING btree (person_id, role, mail_id)",
    "ix_mail_tsv": "CREATE INDEX ix_mail_tsv ON public.mail USING gin (tsv)",
    "ix_mail_is_duplicate_of": "CREATE INDEX ix_mail_is_duplicate_of ON public.mail "
    "USING btree (is_duplicate_of) WHERE (is_duplicate_of IS NOT NULL)",
    "ix_mail_list_id": "CREATE INDEX ix_mail_list_id ON public.mail "
    "USING btree (list_id) WHERE (list_id IS NOT NULL)",
    "ix_mail_paragraph_hash": "CREATE INDEX ix_mail_paragraph_hash ON public.mail_paragraph "
    "USING btree (hash, mail_id)",
    "ix_mail_sort": "CREATE INDEX ix_mail_sort ON public.mail "
    "USING btree (COALESCE(date_utc, '-infinity'::timestamp with time zone), id)",
    "ix_mail_dkim_sort": "CREATE INDEX ix_mail_dkim_sort ON public.mail USING btree "
    "(dkim_status, COALESCE(date_utc, '-infinity'::timestamp with time zone), id)",
    "ix_mail_subject_trgm": "CREATE INDEX ix_mail_subject_trgm "
    "ON public.mail USING gin (subject gin_trgm_ops)",
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
    "ix_person_stats_mails": "CREATE INDEX ix_person_stats_mails "
    "ON public.person_stats USING btree (mails, person_id)",
    "ix_person_stats_last_date": "CREATE INDEX ix_person_stats_last_date ON public.person_stats "
    "USING btree (COALESCE(last_date, '-infinity'::timestamp with time zone), person_id)",
    "ix_document_tsv": "CREATE INDEX ix_document_tsv ON public.document USING gin (tsv)",
    "ix_document_names_trgm": "CREATE INDEX ix_document_names_trgm "
    "ON public.document USING gin (names gin_trgm_ops)",
    "ix_document_first_date": "CREATE INDEX ix_document_first_date ON public.document "
    "USING btree (COALESCE(first_date, '-infinity'::timestamp with time zone), id)",
    "uq_document_sha256": "CREATE UNIQUE INDEX uq_document_sha256 "
    "ON public.document USING btree (sha256)",
    "ix_attachment_document_id": "CREATE INDEX ix_attachment_document_id "
    "ON public.attachment USING btree (document_id, mail_id)",
    "uq_entity_kind_key": "CREATE UNIQUE INDEX uq_entity_kind_key "
    "ON public.entity USING btree (kind, key)",
    "ix_entity_kind_mails": "CREATE INDEX ix_entity_kind_mails "
    "ON public.entity USING btree (kind, mails, id)",
    "ix_entity_first_date": "CREATE INDEX ix_entity_first_date ON public.entity "
    "USING btree (COALESCE(first_date, '-infinity'::timestamp with time zone), id)",
    "ix_entity_value": "CREATE INDEX ix_entity_value ON public.entity "
    "USING btree (value, id) WHERE (value IS NOT NULL)",
    "ix_entity_label_trgm": "CREATE INDEX ix_entity_label_trgm "
    "ON public.entity USING gin (label gin_trgm_ops)",
    "pk_mail_entity": "CREATE UNIQUE INDEX pk_mail_entity "
    "ON public.mail_entity USING btree (entity_id, mail_id)",
    "ix_mail_entity_mail_id": "CREATE INDEX ix_mail_entity_mail_id "
    "ON public.mail_entity USING btree (mail_id, entity_id)",
    "ix_document_entity_document_id": "CREATE INDEX ix_document_entity_document_id "
    "ON public.document_entity USING btree (document_id, entity_id)",
    "ix_dkim_result_key_id": "CREATE INDEX ix_dkim_result_key_id ON public.dkim_result "
    "USING btree (key_id) WHERE (key_id IS NOT NULL)",
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
    assert await db_session.scalar(text("SELECT version_num FROM alembic_version")) == "0026"


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
    url = "postgresql+asyncpg://mailrobbe:p%40ss@db:5432/mailrobbe"
    assert migrate.alembic_config(url).get_main_option("sqlalchemy.url") == url


def test_upgrade_renders_offline_without_database() -> None:
    # Offline mode only takes the dialect from the URL; nothing listens there.
    config = migrate.alembic_config("postgresql+asyncpg://nobody:secret@127.0.0.1:1/none")
    config.output_buffer = buffer = io.StringIO()
    command.upgrade(config, "head", sql=True)
    sql = buffer.getvalue()

    # alembic_version, and mail_note of 0003, which 0007 replaces by mail_mark and note
    assert sql.count("CREATE TABLE ") == len(TABLES) + 2
    assert "DROP TABLE mail_note;" in sql
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm;" in sql
    assert (
        "CREATE TYPE dkim_status AS ENUM ('pass', 'fail', 'no_key', 'unsigned', 'temp_error');"
        in sql
    )
    assert "CREATE INDEX ix_mail_tsv ON mail USING gin (tsv);" in sql
    assert "INSERT INTO alembic_version (version_num) VALUES ('0001')" in sql
    assert (
        "UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0003' WHERE alembic_version.version_num = '0002'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0004' WHERE alembic_version.version_num = '0003'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0005' WHERE alembic_version.version_num = '0004'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0006' WHERE alembic_version.version_num = '0005'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0007' WHERE alembic_version.version_num = '0006'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0008' WHERE alembic_version.version_num = '0007'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0009' WHERE alembic_version.version_num = '0008'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0010' WHERE alembic_version.version_num = '0009'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0011' WHERE alembic_version.version_num = '0010'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0012' WHERE alembic_version.version_num = '0011'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0013' WHERE alembic_version.version_num = '0012'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0014' WHERE alembic_version.version_num = '0013'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0015' WHERE alembic_version.version_num = '0014'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0016' WHERE alembic_version.version_num = '0015'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0017' WHERE alembic_version.version_num = '0016'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0018' WHERE alembic_version.version_num = '0017'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0019' WHERE alembic_version.version_num = '0018'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0020' WHERE alembic_version.version_num = '0019'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0021' WHERE alembic_version.version_num = '0020'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0022' WHERE alembic_version.version_num = '0021'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0023' WHERE alembic_version.version_num = '0022'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0024' WHERE alembic_version.version_num = '0023'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0025' WHERE alembic_version.version_num = '0024'"
        in sql
    )
    assert (
        "UPDATE alembic_version SET version_num='0026' WHERE alembic_version.version_num = '0025'"
        in sql
    )


@pytest.mark.db
async def test_research_migration_keeps_flags_and_notes(empty_database_url: str) -> None:
    """0007 turns D23's flag and note into a mark and a note keyed by content, and back."""

    async def sql(statement: str) -> list[tuple[Any, ...]]:
        engine = create_async_engine(empty_database_url, poolclass=pool.NullPool)
        try:
            async with engine.begin() as connection:
                result = await connection.execute(text(statement))
                return [tuple(row) for row in result] if result.returns_rows else []
        finally:
            await engine.dispose()

    await asyncio.to_thread(migrate.upgrade, "0006", empty_database_url)
    await sql(
        "INSERT INTO mbox_file (id, path, size_bytes) OVERRIDING SYSTEM VALUE VALUES (1, 'a', 9)"
    )
    await sql(
        "INSERT INTO mail (id, mbox_file_id, byte_offset, byte_length, raw_sha256)"
        " OVERRIDING SYSTEM VALUE VALUES (1, 1, 0, 3, 'aa'), (2, 1, 3, 3, 'bb'), (3, 1, 6, 3, 'aa')"
    )
    await sql(
        "INSERT INTO mail_note (mail_id, flagged, note) VALUES"
        " (1, true, ''), (2, false, 'Rückruf bei Eva'), (3, false, 'Kopie')"
    )
    await asyncio.to_thread(migrate.upgrade, "head", empty_database_url)
    assert await sql("SELECT mail_sha256, flagged, flagged_at IS NOT NULL FROM mail_mark") == [
        ("aa", True, True)
    ]
    assert await sql("SELECT mail_sha256, body, author FROM note ORDER BY id") == [
        ("bb", "Rückruf bei Eva", None),
        ("aa", "Kopie", None),
    ]

    await asyncio.to_thread(migrate.downgrade, "0006", empty_database_url)
    assert await sql("SELECT mail_id, flagged, note FROM mail_note ORDER BY mail_id") == [
        (1, True, "Kopie"),
        (2, False, "Rückruf bei Eva"),
    ]


async def test_0008_numbers_the_attachments_of_older_imports(empty_database_url: str) -> None:
    await asyncio.to_thread(migrate.upgrade, "0006", empty_database_url)
    engine = create_async_engine(empty_database_url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO mbox_file (id, path, size_bytes) OVERRIDING SYSTEM VALUE "
                    "VALUES (1, 'a.mbox', 10)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO mail (id, mbox_file_id, byte_offset, byte_length, raw_sha256) "
                    "OVERRIDING SYSTEM VALUE VALUES (1, 1, 0, 5, 'a'), (2, 1, 5, 5, 'b')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO attachment (mail_id, filename, mime_type, size_bytes) VALUES "
                    "(1, 'x', 'text/plain', 1), (2, 'p', 'text/plain', 1), "
                    "(1, 'y', 'text/plain', 1), (1, 'z', 'text/plain', 1)"
                )
            )
        await asyncio.to_thread(migrate.upgrade, "head", empty_database_url)
        async with engine.connect() as connection:
            rows = await _rows(
                connection,
                "SELECT mail_id, filename, position, document_id FROM attachment ORDER BY id",
            )
    finally:
        await engine.dispose()
    assert rows == [(1, "x", 0, None), (2, "p", 0, None), (1, "y", 1, None), (1, "z", 2, None)]


async def test_0011_marks_older_results_as_dns_and_forgets_other_keys_on_downgrade(
    empty_database_url: str,
) -> None:
    """Results before 0011 rest on today's DNS where they rest on a key; a downgrade forgets
    the results that rest on a key from another source, so `mailrobbe dkim` checks them again."""

    async def sql(statement: str) -> list[tuple[Any, ...]]:
        engine = create_async_engine(empty_database_url, poolclass=pool.NullPool)
        try:
            async with engine.begin() as connection:
                result = await connection.execute(text(statement))
                return [tuple(row) for row in result] if result.returns_rows else []
        finally:
            await engine.dispose()

    await asyncio.to_thread(migrate.upgrade, "0010", empty_database_url)
    await sql(
        "INSERT INTO mbox_file (id, path, size_bytes) OVERRIDING SYSTEM VALUE VALUES (1, 'a', 9)"
    )
    await sql(
        "INSERT INTO mail (id, mbox_file_id, byte_offset, byte_length, raw_sha256, dkim_status)"
        " OVERRIDING SYSTEM VALUE VALUES (1, 1, 0, 3, 'aa', 'pass'), (2, 1, 3, 3, 'bb', 'fail'),"
        " (3, 1, 6, 3, 'cc', 'no_key')"
    )
    await sql(
        "INSERT INTO dkim_result (mail_id, signature_index, status, reason) VALUES"
        " (1, 0, 'pass', NULL), (2, 0, 'fail', 'body_hash_mismatch'),"
        " (2, 1, 'fail', 'from_not_signed'), (3, 0, 'no_key', 'key_not_found')"
    )
    await asyncio.to_thread(migrate.upgrade, "head", empty_database_url)
    assert await sql(
        "SELECT mail_id, signature_index, key_origin::text FROM dkim_result ORDER BY 1, 2"
    ) == [(1, 0, "dns"), (2, 0, "dns"), (2, 1, None), (3, 0, None)]

    await sql(
        "INSERT INTO dkim_key (id, name, domain, selector, key_type, bits, key_sha256, record,"
        " origin) OVERRIDING SYSTEM VALUE VALUES (7, 's._domainkey.a.example', 'a.example', 's',"
        " 'rsa', 2048, 'ff', 'p=', 'reconstructed')"
    )
    await sql(
        "UPDATE dkim_result SET status = 'consistent', reason = NULL, key_id = 7,"
        " key_origin = 'reconstructed' WHERE mail_id = 3"
    )
    await sql("UPDATE mail SET dkim_status = 'consistent' WHERE id = 3")
    await asyncio.to_thread(migrate.downgrade, "0010", empty_database_url)
    assert await sql("SELECT id, dkim_status::text FROM mail ORDER BY id") == [
        (1, "pass"),
        (2, "fail"),
        (3, None),
    ]
    assert await sql("SELECT mail_id FROM dkim_result ORDER BY 1, signature_index") == [
        (1,),
        (2,),
        (2,),
    ]


@pytest.mark.db
async def test_0009_sends_texts_archives_and_xps_files_to_the_next_extraction(
    empty_database_url: str,
) -> None:
    await asyncio.to_thread(migrate.upgrade, "0008", empty_database_url)
    engine = create_async_engine(empty_database_url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO document (name, mime_type, size_bytes, kind, text_status) VALUES "
                    "('Logo', 'text/plain', 1, 'text', 'text'), "
                    "('Brief.xps', 'application/zip', 1, 'archive', 'text'), "
                    "('Druck.XPS', 'application/octet-stream', 1, 'other', 'unsupported'), "
                    "(NULL, 'application/oxps', 1, 'other', 'unsupported'), "
                    "('Vertrag.pdf', 'application/pdf', 1, 'pdf', 'text'), "
                    "('Foto.jpg', 'image/jpeg', 1, 'image', 'unsupported'), "
                    "('fehlt.txt', 'text/plain', 1, 'text', 'unreadable'), "
                    "('gross.zip', 'application/zip', 1, 'archive', 'too_large')"
                )
            )
        await asyncio.to_thread(migrate.upgrade, "head", empty_database_url)
        async with engine.connect() as connection:
            rows = await _rows(connection, "SELECT text_status::text FROM document ORDER BY id")
    finally:
        await engine.dispose()
    assert [status for (status,) in rows] == [
        *["pending"] * 4,
        "text",
        "unsupported",
        "unreadable",
        "too_large",
    ]


async def test_0016_keeps_every_tsvector_and_weighs_the_ranges(empty_database_url: str) -> None:
    """0016 drops the generated expression of mail.tsv without touching a stored tsvector; the
    trigger then computes it, the same as before without ranges and weighted by them (D226), and
    the downgrade makes it a generated column again."""
    await asyncio.to_thread(migrate.upgrade, "0015", empty_database_url)
    engine = create_async_engine(empty_database_url, poolclass=pool.NullPool)
    body = "Wir planen eine Spende.\n> zitierte Spende\n\nDiese Mail ist vertraulich."
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO mbox_file (id, path, size_bytes) OVERRIDING SYSTEM VALUE "
                    "VALUES (1, 'a.mbox', 10)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO mail (id, mbox_file_id, byte_offset, byte_length, raw_sha256, "
                    "subject, body_text) OVERRIDING SYSTEM VALUE VALUES "
                    "(1, 1, 0, 5, 'a', 'Betreff Spende', :body)"
                ),
                {"body": body},
            )
            before = await connection.scalar(text("SELECT tsv::text FROM mail WHERE id = 1"))
        await asyncio.to_thread(migrate.upgrade, "head", empty_database_url)
        async with engine.begin() as connection:
            kept = await connection.scalar(text("SELECT tsv::text FROM mail WHERE id = 1"))
            await connection.execute(
                text(
                    "INSERT INTO mail (id, mbox_file_id, byte_offset, byte_length, raw_sha256, "
                    "subject, body_text) OVERRIDING SYSTEM VALUE VALUES "
                    "(2, 1, 5, 5, 'b', 'Betreff Spende', :body)"
                ),
                {"body": body},
            )
            inserted = await connection.scalar(text("SELECT tsv::text FROM mail WHERE id = 2"))
            await connection.execute(
                text("UPDATE mail SET history = '{[24,41)}', blocks = '{[43,70)}' WHERE id = 2")
            )
            weighted = await connection.scalar(text("SELECT tsv::text FROM mail WHERE id = 2"))
            cut = await connection.scalar(
                text("SELECT mailrobbe_cut(body_text, history + blocks) FROM mail WHERE id = 2")
            )
        await asyncio.to_thread(migrate.downgrade, "0015", empty_database_url)
        async with engine.connect() as connection:
            generated = await connection.scalar(
                text(
                    "SELECT is_generated FROM information_schema.columns "
                    "WHERE table_name = 'mail' AND column_name = 'tsv'"
                )
            )
            again = await connection.scalar(text("SELECT tsv::text FROM mail WHERE id = 2"))
    finally:
        await engine.dispose()
    assert kept == before
    assert inserted == before
    assert weighted == (
        "'betreff':1A 'mail':10 'plan':4B 'spend':2A,6B,8C 'vertraulich':12 'zitiert':7C"
    )
    assert cut == "Wir planen eine Spende.\n" + "\n" + "\n\n"  # the ranges joined by a line break
    assert generated == "ALWAYS"
    assert again == before

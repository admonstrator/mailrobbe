"""Initial schema: core tables, aggregation tables, enums, indices, pg_trgm

Revision ID: 0001
Revises:
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS = {
    "dkim_status": ("pass", "fail", "no_key", "unsigned", "temp_error"),
    "participation_role": ("from", "to", "cc", "bcc"),
    "mbox_status": ("pending", "running", "paused", "done", "error"),
    "dns_status": ("found", "not_found", "temp_error"),
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _timestamptz() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def _person_fk(column: str) -> sa.Column[int]:
    return sa.Column(
        column,
        sa.BigInteger(),
        sa.ForeignKey("person.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind)

    op.create_table(
        "mbox_file",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_head", sa.Text()),
        sa.Column("status", _enum("mbox_status"), nullable=False, server_default="pending"),
        sa.Column("mails_parsed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("bytes_done", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", _timestamptz()),
        sa.Column("finished_at", _timestamptz()),
        sa.UniqueConstraint("path", name="uq_mbox_file_path"),
    )

    op.create_table(
        "mail",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "mbox_file_id",
            sa.BigInteger(),
            sa.ForeignKey("mbox_file.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("byte_offset", sa.BigInteger(), nullable=False),
        sa.Column("byte_length", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Text()),
        sa.Column("in_reply_to", sa.Text()),
        sa.Column("thread_id", sa.BigInteger()),
        sa.Column("subject", sa.Text()),
        sa.Column("date_utc", _timestamptz()),
        sa.Column("raw_sha256", sa.Text(), nullable=False),
        sa.Column("has_attachments", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("body_text", sa.Text()),
        sa.Column("tsv", postgresql.TSVECTOR()),
        sa.Column("dkim_status", _enum("dkim_status")),
        sa.Column(
            "is_duplicate_of", sa.BigInteger(), sa.ForeignKey("mail.id", ondelete="SET NULL")
        ),
        sa.UniqueConstraint("mbox_file_id", "byte_offset", name="uq_mail_mbox_file_id_byte_offset"),
    )
    op.create_index("ix_mail_date_utc", "mail", ["date_utc"])
    op.create_index("ix_mail_message_id", "mail", ["message_id"])
    op.create_index("ix_mail_raw_sha256", "mail", ["raw_sha256"])
    op.create_index("ix_mail_thread_id", "mail", ["thread_id"])
    op.create_index("ix_mail_dkim_status", "mail", ["dkim_status"])
    op.create_index("ix_mail_tsv", "mail", ["tsv"], postgresql_using="gin")

    op.create_table(
        "mail_header",
        sa.Column(
            "mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.SmallInteger(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
    )

    op.create_table(
        "person",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("canonical_email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text()),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("merged_into", sa.BigInteger(), sa.ForeignKey("person.id", ondelete="SET NULL")),
        sa.UniqueConstraint("canonical_email", name="uq_person_canonical_email"),
    )
    op.create_index("ix_person_domain", "person", ["domain"])
    op.create_index("ix_person_merged_into", "person", ["merged_into"])
    op.create_index(
        "ix_person_canonical_email_trgm",
        "person",
        ["canonical_email"],
        postgresql_using="gin",
        postgresql_ops={"canonical_email": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_person_display_name_trgm",
        "person",
        ["display_name"],
        postgresql_using="gin",
        postgresql_ops={"display_name": "gin_trgm_ops"},
    )

    op.create_table(
        "person_email",
        sa.Column("email", sa.Text(), primary_key=True),
        _person_fk("person_id"),
        sa.Column(
            "display_names",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_person_email_person_id", "person_email", ["person_id"])
    op.create_index(
        "ix_person_email_email_trgm",
        "person_email",
        ["email"],
        postgresql_using="gin",
        postgresql_ops={"email": "gin_trgm_ops"},
    )

    op.create_table(
        "participation",
        sa.Column(
            "mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "person_id",
            sa.BigInteger(),
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", _enum("participation_role"), primary_key=True),
    )
    op.create_index(
        "ix_participation_person_id_role", "participation", ["person_id", "role", "mail_id"]
    )

    op.create_table(
        "attachment",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text()),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text()),
    )
    op.create_index("ix_attachment_mail_id", "attachment", ["mail_id"])
    op.create_index("ix_attachment_sha256", "attachment", ["sha256"])

    op.create_table(
        "dkim_result",
        sa.Column(
            "mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("signature_index", sa.SmallInteger(), primary_key=True),
        sa.Column("status", _enum("dkim_status"), nullable=False),
        sa.Column("domain", sa.Text()),
        sa.Column("selector", sa.Text()),
        sa.Column("algorithm", sa.Text()),
        sa.Column("key_bits", sa.Integer()),
        sa.Column("signed_headers", postgresql.ARRAY(sa.Text())),
        sa.Column("body_hash_ok", sa.Boolean()),
        sa.Column("signed_at", _timestamptz()),
        sa.Column("aligned", sa.Boolean()),
        sa.Column("reason", sa.Text()),
        sa.Column("checked_at", _timestamptz(), nullable=False, server_default=sa.func.now()),
        sa.Column("dns_cached", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_dkim_result_domain_selector", "dkim_result", ["domain", "selector"])

    op.create_table(
        "dns_cache",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("record", sa.Text()),
        sa.Column("status", _enum("dns_status"), nullable=False),
        sa.Column("fetched_at", _timestamptz(), nullable=False, server_default=sa.func.now()),
        sa.Column("ttl", sa.Integer(), nullable=False),
    )

    op.create_table(
        "import_error",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "mbox_file_id", sa.BigInteger(), sa.ForeignKey("mbox_file.id", ondelete="CASCADE")
        ),
        sa.Column("byte_offset", sa.BigInteger()),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", _timestamptz(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_import_error_mbox_file_id_created_at", "import_error", ["mbox_file_id", "created_at"]
    )

    # Aggregation tables
    op.create_table(
        "edge",
        sa.Column(
            "person_a",
            sa.BigInteger(),
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "person_b",
            sa.BigInteger(),
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mails_a_to_b", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mails_b_to_a", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mails_cc", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "mails_total",
            sa.Integer(),
            sa.Computed("mails_a_to_b + mails_b_to_a + mails_cc", persisted=True),
            nullable=False,
        ),
        sa.Column("first_date", _timestamptz()),
        sa.Column("last_date", _timestamptz()),
        # op.f: the name is final; the ck naming convention would wrap it a second time.
        sa.CheckConstraint("person_a < person_b", name=op.f("ck_edge_ordered")),
    )
    op.create_index("ix_edge_person_b", "edge", ["person_b"])
    op.create_index("ix_edge_mails_total", "edge", ["mails_total"])

    op.create_table(
        "edge_year",
        sa.Column(
            "person_a",
            sa.BigInteger(),
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "person_b",
            sa.BigInteger(),
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("year", sa.SmallInteger(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_edge_year_person_b", "edge_year", ["person_b"])

    op.create_table(
        "person_stats",
        sa.Column(
            "person_id",
            sa.BigInteger(),
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cc_only", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contacts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_date", _timestamptz()),
        sa.Column("last_date", _timestamptz()),
        sa.Column("dkim_pass_ratio", sa.REAL()),
    )

    op.create_table(
        "person_year",
        sa.Column(
            "person_id",
            sa.BigInteger(),
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("year", sa.SmallInteger(), primary_key=True),
        sa.Column("sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "global_stats",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", _timestamptz(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in (
        "global_stats",
        "person_year",
        "person_stats",
        "edge_year",
        "edge",
        "import_error",
        "dns_cache",
        "dkim_result",
        "attachment",
        "participation",
        "person_email",
        "person",
        "mail_header",
        "mail",
        "mbox_file",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(bind)
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")

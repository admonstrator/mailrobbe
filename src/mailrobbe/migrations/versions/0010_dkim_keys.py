"""DKIM keys of deleted selectors: keys from other sources, their evidence, the origin per result

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY_ORIGINS = ("dns", "observed", "documented", "reconstructed")
DKIM_STATUSES = ("pass", "fail", "no_key", "unsigned", "temp_error")  # before this revision
JOB_KINDS = ("import", "dkim")  # before this revision
# Reasons of a fail that rests on the key found in DNS: older results with them, and every
# pass, get key_origin dns.
KEY_REASONS = ("body_hash_mismatch", "signature_mismatch", "key_malformed", "key_too_short")


def upgrade() -> None:
    # A new enum value can be added inside the migration's transaction as long as nothing in
    # it uses the value (PostgreSQL 12 and later).
    op.execute("ALTER TYPE dkim_status ADD VALUE 'consistent' AFTER 'pass'")
    op.execute("ALTER TYPE job_kind ADD VALUE 'dkim_keys'")
    bind = op.get_bind()
    postgresql.ENUM(*KEY_ORIGINS, name="key_origin").create(bind)
    origin = postgresql.ENUM(*KEY_ORIGINS, name="key_origin", create_type=False)

    # One key per name and content, from any source but today's DNS (dns_cache stays as it is).
    op.create_table(
        "dkim_key",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("selector", sa.Text(), nullable=False),
        sa.Column("key_type", sa.Text(), nullable=False),
        sa.Column("bits", sa.Integer(), nullable=False),
        sa.Column("key_sha256", sa.Text(), nullable=False),
        sa.Column("record", sa.Text(), nullable=False),
        sa.Column("origin", origin, nullable=False),
        sa.Column("factorable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("name", "key_sha256", name="uq_dkim_key_name_key_sha256"),
    )
    op.create_index("ix_dkim_key_domain", "dkim_key", ["domain"])
    # Every question to a source, with its answer unchanged, also when nothing was found.
    op.create_table(
        "dkim_key_lookup",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column(
            "asked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("raw", sa.LargeBinary()),
        sa.Column("raw_sha256", sa.Text()),
        sa.Column("raw_type", sa.Text()),
        sa.Column("raw_name", sa.Text()),
        sa.Column("message", sa.Text()),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column("editor", sa.Text()),
    )
    op.create_index("ix_dkim_key_lookup_domain", "dkim_key_lookup", ["domain"])
    op.create_index("ix_dkim_key_lookup_name", "dkim_key_lookup", ["name"])
    # What a lookup says about a key: its origin and the source's own times.
    op.create_table(
        "dkim_key_evidence",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "key_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "dkim_key.id", name="fk_dkim_key_evidence_key_id_dkim_key", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "lookup_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "dkim_key_lookup.id",
                name="fk_dkim_key_evidence_lookup_id_dkim_key_lookup",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("origin", origin, nullable=False),
        sa.Column("observed_from", sa.DateTime(timezone=True)),
        sa.Column("observed_to", sa.DateTime(timezone=True)),
        sa.Column("reference", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column(
            "details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("editor", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("key_id", "lookup_id", name="uq_dkim_key_evidence_key_id_lookup_id"),
    )
    op.create_index("ix_dkim_key_evidence_lookup_id", "dkim_key_evidence", ["lookup_id"])

    op.add_column(
        "dkim_result",
        sa.Column(
            "key_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "dkim_key.id", name="fk_dkim_result_key_id_dkim_key", ondelete="SET NULL"
            ),
        ),
    )
    op.add_column("dkim_result", sa.Column("key_origin", origin))
    op.create_index(
        "ix_dkim_result_key_id",
        "dkim_result",
        ["key_id"],
        postgresql_where=sa.text("key_id IS NOT NULL"),
    )
    # Every result so far rests on today's DNS, where it rests on a key at all.
    reasons = ", ".join(f"'{reason}'" for reason in KEY_REASONS)
    op.execute(
        "UPDATE dkim_result SET key_origin = 'dns' "
        f"WHERE status = 'pass' OR (status = 'fail' AND reason IN ({reasons}))"
    )


def downgrade() -> None:
    # Results that rest on a key from another source are forgotten: their mails count as not
    # checked, and the next `mailrobbe dkim` checks them against DNS alone (D13).
    op.execute(
        """
        UPDATE mail SET dkim_status = NULL
        WHERE dkim_status = 'consistent' OR id IN (
            SELECT mail_id FROM dkim_result
            WHERE key_id IS NOT NULL OR status = 'consistent' OR reason = 'key_mismatch'
        )
        """
    )
    op.execute(
        "DELETE FROM dkim_result WHERE mail_id IN (SELECT id FROM mail WHERE dkim_status IS NULL)"
    )
    op.drop_index("ix_dkim_result_key_id", table_name="dkim_result")
    op.drop_column("dkim_result", "key_origin")
    op.drop_column("dkim_result", "key_id")
    op.drop_index("ix_dkim_key_evidence_lookup_id", table_name="dkim_key_evidence")
    op.drop_table("dkim_key_evidence")
    op.drop_index("ix_dkim_key_lookup_name", table_name="dkim_key_lookup")
    op.drop_index("ix_dkim_key_lookup_domain", table_name="dkim_key_lookup")
    op.drop_table("dkim_key_lookup")
    op.drop_index("ix_dkim_key_domain", table_name="dkim_key")
    op.drop_table("dkim_key")
    postgresql.ENUM(name="key_origin").drop(op.get_bind())
    op.execute("DELETE FROM job WHERE kind = 'dkim_keys'")
    _drop_value("job_kind", JOB_KINDS, [("job", "kind")])
    _drop_value("dkim_status", DKIM_STATUSES, [("mail", "dkim_status"), ("dkim_result", "status")])


def _drop_value(name: str, values: Sequence[str], columns: Sequence[tuple[str, str]]) -> None:
    """PostgreSQL cannot drop an enum value: the type is made again without it."""
    op.execute(f"ALTER TYPE {name} RENAME TO {name}_old")
    postgresql.ENUM(*values, name=name).create(op.get_bind())
    for table, column in columns:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {name} USING {column}::text::{name}"
        )
    op.execute(f"DROP TYPE {name}_old")

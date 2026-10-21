"""Entities: amounts, accounts, names, places, contacts, dates and theme terms found in the texts

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTITY_KINDS = (
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
)
# db/models.py FIRST_DATE_SORT_KEY
FIRST_DATE_SORT_KEY = "COALESCE(first_date, '-infinity'::timestamp with time zone)"


def _mention(table: str, source: str, source_table: str) -> None:
    """mail_entity or document_entity: where an entity is mentioned (D80)."""
    op.create_table(
        table,
        sa.Column(
            "entity_id",
            sa.BigInteger(),
            sa.ForeignKey("entity.id", name=f"fk_{table}_entity_id_entity", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            source,
            sa.BigInteger(),
            sa.ForeignKey(
                f"{source_table}.id",
                name=f"fk_{table}_{source}_{source_table}",
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("context", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index(f"ix_{table}_{source}", table, [source, "entity_id"])


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*ENTITY_KINDS, name="entity_kind").create(bind)
    # One row per kind and normalised key (D81); the figures are recomputed at the end of every
    # entities phase (D85).
    op.create_table(
        "entity",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "kind",
            postgresql.ENUM(*ENTITY_KINDS, name="entity_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(18, 2)),
        sa.Column("currency", sa.Text()),
        sa.Column("detail", sa.Text()),
        sa.Column("mails", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("documents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_date", sa.DateTime(timezone=True)),
        sa.Column("last_date", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("kind", "key", name="uq_entity_kind_key"),
    )
    op.create_index("ix_entity_kind_mails", "entity", ["kind", "mails", "id"])
    op.create_index("ix_entity_mails", "entity", ["mails", "id"])
    op.create_index("ix_entity_first_date", "entity", [sa.text(FIRST_DATE_SORT_KEY), "id"])
    op.create_index(
        "ix_entity_value", "entity", ["value", "id"], postgresql_where=sa.text("value IS NOT NULL")
    )
    op.create_index(
        "ix_entity_label_trgm",
        "entity",
        ["label"],
        postgresql_using="gin",
        postgresql_ops={"label": "gin_trgm_ops"},
    )
    _mention("mail_entity", "mail_id", "mail")
    _mention("document_entity", "document_id", "document")
    # What the entities phase scanned (D84). Empty after the migration: the next import scans
    # every mail and document text of an archive imported before, without importing it again.
    op.create_table(
        "mail_entity_scan",
        sa.Column(
            "mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", name="fk_mail_entity_scan_mail_id_mail", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "document_entity_scan",
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "document.id",
                name="fk_document_entity_scan_document_id_document",
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("document_entity_scan")
    op.drop_table("mail_entity_scan")
    op.drop_table("document_entity")
    op.drop_table("mail_entity")
    op.drop_table("entity")
    postgresql.ENUM(name="entity_kind").drop(op.get_bind())

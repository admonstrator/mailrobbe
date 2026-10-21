"""Attachments: documents with their text, and where each attachment sits in its mail

Revision ID: 0008
Revises: 0006
Create Date: 2026-10-21

Milestone 8 (Rechercheakte) takes 0007 in parallel; whichever merges second points its
down_revision at the other one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_KINDS = (
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
)
TEXT_STATUSES = (
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
)
# db/models.py DOCUMENT_TSV_EXPRESSION and FIRST_DATE_SORT_KEY
TSV_EXPRESSION = (
    "setweight(to_tsvector('german'::regconfig, translate(names, '_.-'::text, '   '::text)), "
    "'A'::\"char\") || "
    "setweight(to_tsvector('german'::regconfig, COALESCE(extracted_text, ''::text)), 'B'::\"char\")"
)
FIRST_DATE_SORT_KEY = "COALESCE(first_date, '-infinity'::timestamp with time zone)"


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*DOCUMENT_KINDS, name="document_kind").create(bind)
    postgresql.ENUM(*TEXT_STATUSES, name="document_text_status").create(bind)
    # One row per distinct content (D70); finalize creates them and computes the figures, the
    # import's attachments phase extracts the text (D72).
    op.create_table(
        "document",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("sha256", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column("names", sa.Text(), nullable=False, server_default=""),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind", postgresql.ENUM(*DOCUMENT_KINDS, name="document_kind", create_type=False)
        ),
        sa.Column(
            "text_status",
            postgresql.ENUM(*TEXT_STATUSES, name="document_text_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("extracted_text", sa.Text()),
        sa.Column("text_truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("text_error", sa.Text()),
        sa.Column("pages", sa.Integer()),
        sa.Column("extractor_version", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("extracted_at", sa.DateTime(timezone=True)),
        sa.Column("mails", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attachments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_date", sa.DateTime(timezone=True)),
        sa.Column("last_date", sa.DateTime(timezone=True)),
        sa.Column(
            "first_mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", name="fk_document_first_mail_id_mail", ondelete="SET NULL"),
        ),
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed(TSV_EXPRESSION, persisted=True)),
        sa.UniqueConstraint("sha256", name="uq_document_sha256"),
    )
    op.create_index("ix_document_tsv", "document", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_document_names_trgm",
        "document",
        ["names"],
        postgresql_using="gin",
        postgresql_ops={"names": "gin_trgm_ops"},
    )
    op.create_index("ix_document_first_date", "document", [sa.text(FIRST_DATE_SORT_KEY), "id"])
    op.create_index("ix_document_mails", "document", ["mails", "id"])
    op.create_index("ix_document_size_bytes", "document", ["size_bytes", "id"])
    op.create_index("ix_document_kind", "document", ["kind"])
    op.create_index("ix_document_text_status", "document", ["text_status"])
    # The importer stored the attachments of a mail in the order mime_parts finds them, and
    # identity ids follow that order, so the position of older rows is their rank by id.
    op.add_column("attachment", sa.Column("position", sa.SmallInteger()))
    op.execute(
        """
        UPDATE attachment SET position = r.position
        FROM (
            SELECT id, row_number() OVER (PARTITION BY mail_id ORDER BY id) - 1 AS position
            FROM attachment
        ) r
        WHERE attachment.id = r.id
        """
    )
    op.alter_column("attachment", "position", nullable=False)
    op.add_column(
        "attachment",
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "document.id", name="fk_attachment_document_id_document", ondelete="SET NULL"
            ),
        ),
    )
    # The mails of a document, read from the index alone (the search through attachments, D73).
    op.create_index("ix_attachment_document_id", "attachment", ["document_id", "mail_id"])


def downgrade() -> None:
    op.drop_index("ix_attachment_document_id", table_name="attachment")
    op.drop_column("attachment", "document_id")
    op.drop_column("attachment", "position")
    op.drop_table("document")
    bind = op.get_bind()
    postgresql.ENUM(name="document_text_status").drop(bind)
    postgresql.ENUM(name="document_kind").drop(bind)

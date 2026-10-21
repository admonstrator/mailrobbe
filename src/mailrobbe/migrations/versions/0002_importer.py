"""Importer: references, display names per participation, generated full text vector, worker id

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept literally here so the revision never changes; db/models.py builds the same expression.
# Spelled the way PostgreSQL renders it back, so the schema drift test can compare it.
TSV_EXPRESSION = (
    "setweight(to_tsvector('german'::regconfig, COALESCE(subject, ''::text)), 'A'::\"char\") || "
    "setweight(to_tsvector('german'::regconfig, COALESCE(body_text, ''::text)), 'B'::\"char\")"
)


def upgrade() -> None:
    op.add_column("mail", sa.Column("reference_ids", postgresql.ARRAY(sa.Text())))
    op.drop_index("ix_mail_tsv", table_name="mail")
    op.drop_column("mail", "tsv")
    op.add_column(
        "mail",
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed(TSV_EXPRESSION, persisted=True)),
    )
    op.create_index("ix_mail_tsv", "mail", ["tsv"], postgresql_using="gin")
    op.add_column("participation", sa.Column("display_name", sa.Text()))
    op.add_column("mbox_file", sa.Column("worker_id", sa.SmallInteger()))
    # The ON DELETE SET NULL of is_duplicate_of looks up referencing mails once per deleted mail;
    # without an index that is a scan of all mails each time a replaced file's mails go.
    op.create_index(
        "ix_mail_is_duplicate_of",
        "mail",
        ["is_duplicate_of"],
        postgresql_where=sa.text("is_duplicate_of IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_mail_is_duplicate_of", table_name="mail")
    op.drop_column("mbox_file", "worker_id")
    op.drop_column("participation", "display_name")
    op.drop_index("ix_mail_tsv", table_name="mail")
    op.drop_column("mail", "tsv")
    op.add_column("mail", sa.Column("tsv", postgresql.TSVECTOR()))
    op.create_index("ix_mail_tsv", "mail", ["tsv"], postgresql_using="gin")
    op.drop_column("mail", "reference_ids")

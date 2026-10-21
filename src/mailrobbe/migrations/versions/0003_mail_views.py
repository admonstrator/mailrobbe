"""Mail list and detail: sort index for keyset paging, subject search, per-mail flag and note

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The mail list sorts by date, then id, with mails without a date last when newest come first
# (D19). Keyset paging compares (MAIL_SORT_KEY, id) as a row, which needs both in one index;
# db/models.py builds the same expression. Spelled the way PostgreSQL renders it back.
MAIL_SORT_KEY = "COALESCE(date_utc, '-infinity'::timestamp with time zone)"


def upgrade() -> None:
    op.create_index("ix_mail_sort", "mail", [sa.text(MAIL_SORT_KEY), "id"])
    # subject: matches part of the subject (D20), as from:/to: do for addresses.
    op.create_index(
        "ix_mail_subject_trgm",
        "mail",
        ["subject"],
        postgresql_using="gin",
        postgresql_ops={"subject": "gin_trgm_ops"},
    )
    op.create_table(
        "mail_note",
        sa.Column(
            "mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("mail_note")
    op.drop_index("ix_mail_subject_trgm", table_name="mail")
    op.drop_index("ix_mail_sort", table_name="mail")

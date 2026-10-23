"""Settings of the page "Einstellungen": one row per setting changed in the web UI

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A row overrides the environment's value of its setting (D313); none at first, so every
    # setting keeps what .env says until someone changes it on the page.
    op.create_table(
        "setting",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("changed_by", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("setting")

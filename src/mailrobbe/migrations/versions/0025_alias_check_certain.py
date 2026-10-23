"""Alias checks: whether the text model was sure

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A verdict of the checks of groups (D324) says whether the model was sure; the verdicts of
    # before were not, so they keep false and are merged one at a time only (D326).
    op.add_column(
        "alias_check",
        sa.Column("certain", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("alias_check", "certain")

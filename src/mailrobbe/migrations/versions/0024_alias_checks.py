"""Alias checks: what the text model said about a pair of persons

Revision ID: 0024
Revises: 0022
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALIAS_VERDICTS = ("same", "different", "unclear")


def upgrade() -> None:
    # One row per pair of root persons the text model judged (D323); none at first, the AI run
    # with --aliases fills it. Nothing is read from the MBOX files.
    bind = op.get_bind()
    postgresql.ENUM(*ALIAS_VERDICTS, name="alias_verdict").create(bind)
    verdict = postgresql.ENUM(*ALIAS_VERDICTS, name="alias_verdict", create_type=False)
    op.create_table(
        "alias_check",
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
        sa.Column("verdict", verdict, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("service_url", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.REAL(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("job.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # op.f: the name is final; the ck naming convention would wrap it a second time.
        sa.CheckConstraint("person_a < person_b", name=op.f("ck_alias_check_ordered")),
    )
    op.create_index("ix_alias_check_person_b", "alias_check", ["person_b"])


def downgrade() -> None:
    op.drop_table("alias_check")
    postgresql.ENUM(name="alias_verdict").drop(op.get_bind())

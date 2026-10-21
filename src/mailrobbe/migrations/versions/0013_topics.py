"""Topics: the vocabulary, the terms of every period and the clusters of the topics phase

Revision ID: 0013
Revises: 0010
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIT_CHECK = "unit IN ('month', 'quarter', 'year')"  # topics.model.Unit


def _term_id(table: str) -> sa.Column[int]:
    return sa.Column(
        "term_id",
        sa.Integer(),
        sa.ForeignKey("topic_term.id", name=f"fk_{table}_term_id_topic_term", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    # Everything here is computed by the topics phase (D146) and replaced as a whole; the tables
    # stay empty until the next import, which computes them for an archive imported before.
    op.create_table(
        "topic_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mails", sa.Integer(), nullable=False),
        sa.Column("terms", sa.Integer(), nullable=False),
        sa.Column("clusters", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.REAL(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_topic_state_single")),
    )
    op.create_table(
        "topic_term",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("lexeme", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("mails", sa.Integer(), nullable=False),
        sa.Column(
            "themes", sa.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")
        ),
        sa.UniqueConstraint("lexeme", name="uq_topic_term_lexeme"),
    )
    op.create_table(
        "topic_period",
        sa.Column("unit", sa.Text(), primary_key=True),
        sa.Column("period_start", sa.Date(), primary_key=True),
        sa.Column("mails", sa.Integer(), nullable=False),
        sa.CheckConstraint(UNIT_CHECK, name=op.f("ck_topic_period_unit")),
    )
    op.create_table(
        "topic_period_term",
        sa.Column("unit", sa.Text(), primary_key=True),
        sa.Column("period_start", sa.Date(), primary_key=True),
        sa.Column("rank", sa.SmallInteger(), primary_key=True),
        _term_id("topic_period_term"),
        sa.Column("mails", sa.Integer(), nullable=False),
        sa.Column("score", sa.REAL(), nullable=False),
        sa.ForeignKeyConstraint(
            ["unit", "period_start"],
            ["topic_period.unit", "topic_period.period_start"],
            name="fk_topic_period_term_unit_topic_period",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_topic_period_term_term_id", "topic_period_term", ["term_id"])
    op.create_table(
        "topic_cluster",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("mails", sa.Integer(), nullable=False),
        sa.Column("first_date", sa.DateTime(timezone=True)),
        sa.Column("last_date", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("rank", name="uq_topic_cluster_rank"),
    )
    op.create_table(
        "topic_cluster_term",
        sa.Column(
            "cluster_id",
            sa.Integer(),
            sa.ForeignKey(
                "topic_cluster.id",
                name="fk_topic_cluster_term_cluster_id_topic_cluster",
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column("rank", sa.SmallInteger(), primary_key=True),
        _term_id("topic_cluster_term"),
        sa.Column("weight", sa.REAL(), nullable=False),
    )
    op.create_index("ix_topic_cluster_term_term_id", "topic_cluster_term", ["term_id"])
    op.create_table(
        "topic_cluster_month",
        sa.Column(
            "cluster_id",
            sa.Integer(),
            sa.ForeignKey(
                "topic_cluster.id",
                name="fk_topic_cluster_month_cluster_id_topic_cluster",
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column("month", sa.Date(), primary_key=True),
        sa.Column("mails", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("topic_cluster_month")
    op.drop_table("topic_cluster_term")
    op.drop_table("topic_cluster")
    op.drop_table("topic_period_term")
    op.drop_table("topic_period")
    op.drop_table("topic_term")
    op.drop_table("topic_state")

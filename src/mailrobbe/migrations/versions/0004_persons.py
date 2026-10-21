"""Persons: sort keys of the person list, alias suggestions and dismissed suggestions

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import SchemaItem

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The person list sorts by mails or by the latest mail, then person id (D31); persons without a
# dated mail sort last. db/models.py builds the same expression. Spelled the way PostgreSQL
# renders it back.
LAST_DATE_SORT_KEY = "COALESCE(last_date, '-infinity'::timestamp with time zone)"


def _person_pair(table: str) -> list[SchemaItem]:
    """person_a < person_b, both root persons, removed with either person."""
    return [
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
        # op.f: the name is final; the ck naming convention would wrap it a second time.
        sa.CheckConstraint("person_a < person_b", name=op.f(f"ck_{table}_ordered")),
    ]


def upgrade() -> None:
    op.add_column(
        "person_stats",
        sa.Column(
            "mails",
            sa.Integer(),
            sa.Computed("sent + received", persisted=True),
            nullable=False,
        ),
    )
    op.create_index("ix_person_stats_mails", "person_stats", ["mails", "person_id"])
    op.create_index(
        "ix_person_stats_last_date", "person_stats", [sa.text(LAST_DATE_SORT_KEY), "person_id"]
    )
    # Computed with the person figures (D30); one row per pair, with what both share.
    op.create_table(
        "alias_suggestion",
        *_person_pair("alias_suggestion"),
        sa.Column("same_name", sa.Text()),
        sa.Column("same_local_part", sa.Text()),
        sa.CheckConstraint(
            "same_name IS NOT NULL OR same_local_part IS NOT NULL",
            name=op.f("ck_alias_suggestion_reason"),
        ),
    )
    op.create_index("ix_alias_suggestion_person_b", "alias_suggestion", ["person_b"])
    # Written by the user (D28): pairs that are not the same person and are never suggested again.
    op.create_table(
        "alias_dismissal",
        *_person_pair("alias_dismissal"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("alias_dismissal")
    op.drop_table("alias_suggestion")
    op.drop_index("ix_person_stats_last_date", table_name="person_stats")
    op.drop_index("ix_person_stats_mails", table_name="person_stats")
    op.drop_column("person_stats", "mails")

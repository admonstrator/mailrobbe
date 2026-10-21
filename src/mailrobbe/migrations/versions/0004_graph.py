"""Relationship map: edge counters for the map options, list and automated senders

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERSON_KINDS = ("list", "automated")
# The directed To/Bcc counters and the undirected Cc counter, over all mails and over the mails
# whose DKIM check passed (D36); edge and edge_year carry the same set.
COUNTERS = ("mails_a_to_b", "mails_b_to_a", "mails_cc", "pass_a_to_b", "pass_b_to_a", "pass_cc")


def _counter(name: str) -> sa.Column[int]:
    return sa.Column(name, sa.Integer(), nullable=False, server_default="0")


def upgrade() -> None:
    postgresql.ENUM(*PERSON_KINDS, name="person_kind").create(op.get_bind())
    # Filled by the importer from List-Id, Auto-Submitted and Precedence (D39).
    op.add_column("mail", sa.Column("list_id", sa.Text()))
    op.add_column(
        "mail",
        sa.Column("automated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Set by refresh_edges on root persons; NULL is a human or unknown (D39).
    op.add_column(
        "person",
        sa.Column("kind", postgresql.ENUM(*PERSON_KINDS, name="person_kind", create_type=False)),
    )
    for name in COUNTERS[3:]:
        op.add_column("edge", _counter(name))
    op.drop_column("edge_year", "count")
    for name in COUNTERS:
        op.add_column("edge_year", _counter(name))


def downgrade() -> None:
    for name in COUNTERS:
        op.drop_column("edge_year", name)
    op.add_column("edge_year", _counter("count"))
    for name in COUNTERS[3:]:
        op.drop_column("edge", name)
    op.drop_column("person", "kind")
    op.drop_column("mail", "automated")
    op.drop_column("mail", "list_id")
    postgresql.ENUM(name="person_kind").drop(op.get_bind())

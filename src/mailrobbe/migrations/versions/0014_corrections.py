"""Corrections from the real archive: alias tiers, merge log with undo, document metadata

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALIAS_TIERS = ("certain", "uncertain")


def upgrade() -> None:
    # Alias suggestions (D160): every one gets a tier. The old ones are deleted rather than
    # guessed; the finalize of the next run computes them anew from person and person_email
    # (D33), nothing is read from the MBOX files.
    bind = op.get_bind()
    postgresql.ENUM(*ALIAS_TIERS, name="alias_tier").create(bind)
    tier = postgresql.ENUM(*ALIAS_TIERS, name="alias_tier", create_type=False)
    op.execute("DELETE FROM alias_suggestion")
    op.add_column("alias_suggestion", sa.Column("tier", tier, nullable=False))

    # Merge log (D163): every merge from now on, with the persons it moved and where each one
    # pointed before, so it can be undone exactly. Merges made before have no entry and are
    # split per address as before (D28).
    op.create_table(
        "merge_batch",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("editor", sa.Text()),
    )
    op.create_table(
        "person_merge",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "target",
            sa.BigInteger(),
            sa.ForeignKey("person.id", name="fk_person_merge_target_person", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "merge_batch.id", name="fk_person_merge_batch_id_merge_batch", ondelete="SET NULL"
            ),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("editor", sa.Text()),
        sa.Column("undone_at", sa.DateTime(timezone=True)),
        sa.Column("undone_by", sa.Text()),
    )
    op.create_index("ix_person_merge_target", "person_merge", ["target"])
    op.create_index("ix_person_merge_batch_id", "person_merge", ["batch_id"])
    op.create_table(
        "person_merge_member",
        sa.Column(
            "merge_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "person_merge.id",
                name="fk_person_merge_member_merge_id_person_merge",
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column(
            "person_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "person.id", name="fk_person_merge_member_person_id_person", ondelete="CASCADE"
            ),
            primary_key=True,
        ),
        # person.merged_into before the merge: NULL for a root, else the root it belonged to
        sa.Column("previous_root", sa.BigInteger()),
    )
    op.create_index("ix_person_merge_member_person_id", "person_merge_member", ["person_id"])

    # Document metadata (D167): added by the metadata part of this revision.


def downgrade() -> None:
    op.drop_table("person_merge_member")
    op.drop_table("person_merge")
    op.drop_table("merge_batch")
    op.drop_column("alias_suggestion", "tier")
    op.execute("DROP TYPE alias_tier")

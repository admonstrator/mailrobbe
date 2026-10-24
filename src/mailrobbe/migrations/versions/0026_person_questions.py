"""Person questions: what the team asked the text model about one person or two

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per question "KI fragen" asked on a person's page (D347); none at first, the AI run
    # answers them in its step ask. Nothing is read from the MBOX files.
    status = postgresql.ENUM(name="ai_task_status", create_type=False)
    op.create_table(
        "person_question",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "person_id",
            sa.BigInteger(),
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("other_id", sa.BigInteger(), sa.ForeignKey("person.id", ondelete="CASCADE")),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", status, nullable=False, server_default="waiting"),
        sa.Column(
            "prework",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("answer", sa.Text()),
        sa.Column("contents", sa.Integer()),
        sa.Column("model", sa.Text()),
        sa.Column("prompt_version", sa.Integer()),
        sa.Column("seconds", sa.REAL()),
        sa.Column("tokens_in", sa.Integer()),
        sa.Column("tokens_out", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("queued_by", sa.Text()),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("job.id", ondelete="SET NULL")),
    )
    op.create_index("ix_person_question_person_id", "person_question", ["person_id", "id"])
    op.create_index("ix_person_question_other_id", "person_question", ["other_id"])
    op.create_index(
        "ix_person_question_waiting",
        "person_question",
        ["id"],
        postgresql_where=sa.text("status = 'waiting'"),
    )


def downgrade() -> None:
    op.drop_table("person_question")

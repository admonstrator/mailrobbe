"""Summaries of whole threads: the target thread with the thread it reads

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGET_TABLES = ("ai_task", "ai_result", "ai_send_log")
THREAD_TABLES = ("ai_task", "ai_result")


def _targets(*targets: str) -> None:
    listed = ", ".join(f"'{target}'" for target in targets)
    for table in TARGET_TABLES:
        op.drop_constraint(op.f(f"ck_{table}_target"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_target"), table, f"target IN ({listed})")


def upgrade() -> None:
    # A thread's summary (D316): target_sha256 is the SHA-256 of its mails' raw_sha256, sorted
    # and joined by line ends, so a thread that gained a mail is another content; thread_id is
    # mail.thread_id, which the task reads and the views find the thread's summary by.
    _targets("document", "mail", "thread")
    for table in THREAD_TABLES:
        op.add_column(table, sa.Column("thread_id", sa.BigInteger(), nullable=True))
        op.create_check_constraint(
            op.f(f"ck_{table}_thread"), table, "(target = 'thread') = (thread_id IS NOT NULL)"
        )
    op.create_index(
        "ix_ai_result_thread_id",
        "ai_result",
        ["thread_id"],
        postgresql_where=sa.text("thread_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM ai_send_log WHERE target = 'thread'")
    op.execute("DELETE FROM ai_task WHERE target = 'thread'")
    op.execute("DELETE FROM ai_result WHERE target = 'thread'")
    op.drop_index("ix_ai_result_thread_id", table_name="ai_result")
    for table in THREAD_TABLES:
        op.drop_constraint(op.f(f"ck_{table}_thread"), table, type_="check")
        op.drop_column(table, "thread_id")
    _targets("document", "mail")

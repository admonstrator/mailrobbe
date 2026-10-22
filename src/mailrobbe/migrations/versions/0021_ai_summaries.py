"""AI summaries and tags: a target per task, result and send, AI tags and theme hints

Revision ID: 0021
Revises: 0019
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGET_TABLES = ("ai_task", "ai_result", "ai_send_log")


def upgrade() -> None:
    # What a task, a result and a send are about (D301): a document by document.sha256, or a
    # mail by mail.raw_sha256 (as the research file, D53). Every row so far is a document's.
    for table in TARGET_TABLES:
        op.add_column(
            table, sa.Column("target", sa.Text(), nullable=False, server_default="document")
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_target"), table, "target IN ('document', 'mail')"
        )
    op.drop_index("ux_ai_task_open", table_name="ai_task")
    op.create_index(
        "ux_ai_task_open",
        "ai_task",
        ["kind", "target", "target_sha256"],
        unique=True,
        postgresql_where=sa.text("status IN ('waiting', 'running')"),
    )
    op.drop_index("ux_ai_result_valid", table_name="ai_result")
    op.create_index(
        "ux_ai_result_valid",
        "ai_result",
        ["kind", "target", "target_sha256"],
        unique=True,
        postgresql_where=sa.text("state = 'valid'"),
    )

    # AI tags (D305): one row per normalised key, shown by the spelling it was first given.
    op.create_table(
        "ai_tag",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ux_ai_tag_key", "ai_tag", ["key"], unique=True)
    op.create_table(
        "ai_tag_link",
        sa.Column(
            "result_id",
            sa.BigInteger(),
            sa.ForeignKey("ai_result.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.BigInteger(),
            sa.ForeignKey("ai_tag.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_ai_tag_link_tag_id", "ai_tag_link", ["tag_id"])

    # Theme hints (D304): a theme of themes.toml with the quote found in the text it names.
    op.create_table(
        "ai_theme_hint",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "result_id",
            sa.BigInteger(),
            sa.ForeignKey("ai_result.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("theme", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer()),
    )
    op.create_index("ix_ai_theme_hint_result_id", "ai_theme_hint", ["result_id"])
    op.create_index("ix_ai_theme_hint_theme", "ai_theme_hint", ["theme"])


def downgrade() -> None:
    op.drop_table("ai_theme_hint")
    op.drop_table("ai_tag_link")
    op.drop_table("ai_tag")
    # Rows of mails go: the M15 indexes cannot hold a mail and a document of the same content.
    op.execute("DELETE FROM ai_send_log WHERE target = 'mail'")
    op.execute("DELETE FROM ai_task WHERE target = 'mail'")
    op.execute("DELETE FROM ai_result WHERE target = 'mail'")
    op.drop_index("ux_ai_result_valid", table_name="ai_result")
    op.create_index(
        "ux_ai_result_valid",
        "ai_result",
        ["kind", "target_sha256"],
        unique=True,
        postgresql_where=sa.text("state = 'valid'"),
    )
    op.drop_index("ux_ai_task_open", table_name="ai_task")
    op.create_index(
        "ux_ai_task_open",
        "ai_task",
        ["kind", "target_sha256"],
        unique=True,
        postgresql_where=sa.text("status IN ('waiting', 'running')"),
    )
    for table in TARGET_TABLES:
        op.drop_constraint(op.f(f"ck_{table}_target"), table, type_="check")
        op.drop_column(table, "target")

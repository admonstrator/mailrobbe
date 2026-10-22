"""AI services: the task queue, results with their origin, calibration, what left the house

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_KINDS = ("import", "dkim", "dkim_keys", "map")  # before this revision
TEXT_ORIGINS = ("extracted", "ocr", "transcript")
TASK_KINDS = ("ocr", "transcribe", "summarize")
TASK_STATUSES = ("waiting", "running", "done", "failed", "cancelled")
RESULT_STATES = ("valid", "replaced", "discarded")


def upgrade() -> None:
    # A new enum value can be added inside the migration's transaction as long as nothing in
    # it uses the value (PostgreSQL 12 and later).
    op.execute("ALTER TYPE job_kind ADD VALUE 'ai'")
    bind = op.get_bind()
    for name, values in (
        ("text_origin", TEXT_ORIGINS),
        ("ai_task_kind", TASK_KINDS),
        ("ai_task_status", TASK_STATUSES),
        ("ai_result_state", RESULT_STATES),
    ):
        postgresql.ENUM(*values, name=name).create(bind)
    origin = postgresql.ENUM(*TEXT_ORIGINS, name="text_origin", create_type=False)
    kind = postgresql.ENUM(*TASK_KINDS, name="ai_task_kind", create_type=False)
    status = postgresql.ENUM(*TASK_STATUSES, name="ai_task_status", create_type=False)
    state = postgresql.ENUM(*RESULT_STATES, name="ai_result_state", create_type=False)
    timestamptz = sa.TIMESTAMP(timezone=True)

    # Every result with its origin (D185), named by the SHA-256 of what it was made from, so it
    # outlives a new import of a changed MBOX file. At most one valid result per kind and content.
    op.create_table(
        "ai_result",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", kind, nullable=False),
        sa.Column("target_sha256", sa.Text(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("model", sa.Text()),
        sa.Column("service_url", sa.Text()),
        sa.Column("remote", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("prompt_version", sa.SmallInteger()),
        sa.Column(
            "options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "pages", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("pages_total", sa.Integer()),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("job.id", ondelete="SET NULL")),
        sa.Column("state", state, nullable=False, server_default="valid"),
        sa.Column("created_at", timestamptz, nullable=False, server_default=sa.func.now()),
        sa.Column("discarded_by", sa.Text()),
        sa.Column("discarded_at", timestamptz),
    )
    op.create_index("ix_ai_result_target", "ai_result", ["target_sha256", "kind"])
    op.create_index(
        "ux_ai_result_valid",
        "ai_result",
        ["kind", "target_sha256"],
        unique=True,
        postgresql_where=sa.text("state = 'valid'"),
    )
    op.create_index("ix_ai_result_job", "ai_result", ["job_id"])

    # The queue (D186): what someone selected, worked through by `mailrobbe ai run`.
    op.create_table(
        "ai_task",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", kind, nullable=False),
        sa.Column("target_sha256", sa.Text(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False, server_default="auto"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", status, nullable=False, server_default="waiting"),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column(
            "partial", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("queued_by", sa.Text()),
        sa.Column("queued_at", timestamptz, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", timestamptz),
        sa.Column("finished_at", timestamptz),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("job.id", ondelete="SET NULL")),
        sa.Column("result_id", sa.BigInteger(), sa.ForeignKey("ai_result.id", ondelete="SET NULL")),
        sa.CheckConstraint(
            "engine IN ('auto', 'tesseract', 'vision')", name=op.f("ck_ai_task_engine")
        ),
    )
    op.create_index(
        "ux_ai_task_open",
        "ai_task",
        ["kind", "target_sha256"],
        unique=True,
        postgresql_where=sa.text("status IN ('waiting', 'running')"),
    )
    op.create_index(
        "ix_ai_task_waiting",
        "ai_task",
        ["kind", sa.text("priority DESC"), "id"],
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.create_index("ix_ai_task_status", "ai_task", ["status", "id"])

    # Measured speed per engine, model and task kind (D188).
    op.create_table(
        "ai_calibration",
        sa.Column("kind", kind, primary_key=True),
        sa.Column("engine", sa.Text(), primary_key=True),
        sa.Column("model", sa.Text(), primary_key=True, server_default=""),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("seconds_per_unit", sa.Float(), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("updated_at", timestamptz, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "unit IN ('page', 'minute', 'ktoken')", name=op.f("ck_ai_calibration_unit")
        ),
    )

    # What went to a service outside the own machine and network (D181).
    op.create_table(
        "ai_send_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("sent_at", timestamptz, nullable=False, server_default=sa.func.now()),
        sa.Column("service_url", sa.Text(), nullable=False),
        sa.Column("kind", kind, nullable=False),
        sa.Column("target_sha256", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("job.id", ondelete="SET NULL")),
    )
    op.create_index("ix_ai_send_log_sent_at", "ai_send_log", ["sent_at"])

    # Where a document's searchable text comes from (D185); every stored text was extracted.
    op.add_column(
        "document", sa.Column("text_origin", origin, nullable=False, server_default="extracted")
    )
    op.add_column(
        "document",
        sa.Column(
            "ai_result_id", sa.BigInteger(), sa.ForeignKey("ai_result.id", ondelete="SET NULL")
        ),
    )
    op.create_index(
        "ix_document_text_origin",
        "document",
        ["text_origin"],
        postgresql_where=sa.text("text_origin <> 'extracted'"),
    )


def downgrade() -> None:
    op.drop_index("ix_document_text_origin", table_name="document")
    op.drop_column("document", "ai_result_id")
    op.drop_column("document", "text_origin")
    op.drop_table("ai_send_log")
    op.drop_table("ai_calibration")
    op.drop_table("ai_task")
    op.drop_table("ai_result")
    bind = op.get_bind()
    for name in ("ai_result_state", "ai_task_status", "ai_task_kind", "text_origin"):
        postgresql.ENUM(name=name).drop(bind)
    op.execute("DELETE FROM job WHERE kind = 'ai'")
    _drop_value("job_kind", JOB_KINDS, [("job", "kind")])


def _drop_value(name: str, values: Sequence[str], columns: Sequence[tuple[str, str]]) -> None:
    """PostgreSQL cannot drop an enum value: the type is made again without it."""
    op.execute(f"ALTER TYPE {name} RENAME TO {name}_old")
    postgresql.ENUM(*values, name=name).create(op.get_bind())
    for table, column in columns:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {name} USING {column}::text::{name}"
        )
    op.execute(f"DROP TYPE {name}_old")

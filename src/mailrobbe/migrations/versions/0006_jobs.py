"""Import dashboard: runs of the importer and the DKIM check, header version of MBOX files

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_KINDS = ("import", "dkim")
JOB_STATUSES = ("running", "done", "stopped", "failed")
# db/models.py HEADER_VERSION: files imported from now on have every parsed header field.
HEADER_VERSION = 1


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*JOB_KINDS, name="job_kind").create(bind)
    postgresql.ENUM(*JOB_STATUSES, name="job_status").create(bind)
    # One row per `mailrobbe import` or `mailrobbe dkim` run (D47), written by the run itself.
    op.create_table(
        "job",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "kind",
            postgresql.ENUM(*JOB_KINDS, name="job_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*JOB_STATUSES, name="job_status", create_type=False),
            nullable=False,
            server_default="running",
        ),
        sa.Column("phase", sa.Text()),
        sa.Column(
            "options",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "progress",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("message", sa.Text()),
        sa.Column("stop_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("origin IN ('cli', 'ui')", name=op.f("ck_job_origin")),
    )
    op.create_index("ix_job_kind", "job", ["kind", "id"])
    # Files imported before this revision may lack list_id and automated (D39): the next import
    # reads the headers of their mails again (D52). New rows get the current version.
    op.add_column(
        "mbox_file",
        sa.Column("header_version", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.alter_column("mbox_file", "header_version", server_default=str(HEADER_VERSION))


def downgrade() -> None:
    op.drop_column("mbox_file", "header_version")
    op.drop_index("ix_job_kind", table_name="job")
    op.drop_table("job")
    bind = op.get_bind()
    postgresql.ENUM(name="job_status").drop(bind)
    postgresql.ENUM(name="job_kind").drop(bind)

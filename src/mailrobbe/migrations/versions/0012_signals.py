"""Signals: private addresses, Bcc, recipients, forwards, night and weekend, silent persons

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The signals phase of the next import fills both tables for every mail already imported
    # (D135); nothing is read from the MBOX files.
    op.create_table(
        "mail_signal",
        sa.Column("signal", sa.Text(), primary_key=True),
        sa.Column(
            "mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", name="fk_mail_signal_mail_id_mail", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_mail_signal_mail_id", "mail_signal", ["mail_id", "signal"])
    op.create_table(
        "person_signal",
        sa.Column("signal", sa.Text(), primary_key=True),
        sa.Column(
            "person_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "person.id", name="fk_person_signal_person_id_person", ondelete="CASCADE"
            ),
            primary_key=True,
        ),
        sa.Column("mails", sa.Integer(), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_person_signal_mails", "person_signal", ["signal", "mails", "person_id"])


def downgrade() -> None:
    op.drop_table("person_signal")
    op.drop_table("mail_signal")
    op.execute("DELETE FROM global_stats WHERE key = 'signals'")

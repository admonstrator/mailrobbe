"""Near duplicates, calendar invitations and named accounts

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _mail_id(table: str, primary_key: bool) -> sa.Column[int]:
    return sa.Column(
        "mail_id",
        sa.BigInteger(),
        sa.ForeignKey("mail.id", name=f"fk_{table}_mail_id_mail", ondelete="CASCADE"),
        primary_key=primary_key,
        nullable=False,
    )


def upgrade() -> None:
    # The near phase of the next import fingerprints every mail already imported from the
    # database alone (D152, D153).
    op.create_table(
        "mail_near",
        _mail_id("mail_near", primary_key=True),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("fingerprint", sa.LargeBinary(), nullable=True),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_mail_near_fingerprint",
        "mail_near",
        ["fingerprint"],
        postgresql_where=sa.text("fingerprint IS NOT NULL"),
    )
    op.create_index(
        "ix_mail_near_group_id",
        "mail_near",
        ["group_id", "mail_id"],
        postgresql_where=sa.text("group_id IS NOT NULL"),
    )

    # The calendar phase of the next import looks at every mail already imported and reads the
    # candidates from the MBOX files (D154).
    op.create_table(
        "calendar_scan",
        _mail_id("calendar_scan", primary_key=True),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("events", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "calendar_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        _mail_id("calendar_event", primary_key=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("uid", sa.Text(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_local", sa.DateTime(timezone=False), nullable=True),
        sa.Column("ends_local", sa.DateTime(timezone=False), nullable=True),
        sa.Column("time_zone", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("recurrence", sa.Text(), nullable=True),
        sa.Column("organizer_email", sa.Text(), nullable=True),
        sa.Column("organizer_name", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('request', 'reply', 'cancel')", name=op.f("ck_calendar_event_kind")
        ),
        sa.UniqueConstraint("mail_id", "position", name="uq_calendar_event_mail_id_position"),
    )
    op.create_index("ix_calendar_event_uid", "calendar_event", ["uid"])
    op.create_index("ix_calendar_event_organizer_email", "calendar_event", ["organizer_email"])
    op.create_table(
        "calendar_attendee",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "calendar_event.id",
                name="fk_calendar_attendee_event_id_calendar_event",
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column("position", sa.SmallInteger(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("partstat", sa.Text(), nullable=True),
    )
    op.create_index("ix_calendar_attendee_email", "calendar_attendee", ["email"])

    # Labels the team gives to addresses (D156): user data like the research file.
    op.create_table(
        "person_label",
        sa.Column("email", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("editor", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "name IS NOT NULL OR role IS NOT NULL OR note IS NOT NULL",
            name=op.f("ck_person_label_something"),
        ),
    )


def downgrade() -> None:
    op.drop_table("person_label")
    op.drop_table("calendar_attendee")
    op.drop_table("calendar_event")
    op.drop_table("calendar_scan")
    op.drop_table("mail_near")
    op.execute("DELETE FROM global_stats WHERE key IN ('near', 'calendar')")

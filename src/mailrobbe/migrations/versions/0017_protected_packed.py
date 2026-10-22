"""Protected and packed attachments: containers, their members, and found passwords

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROTECTIONS = ("locked", "open")
MEMBERS_STATUSES = (
    "done",
    "locked",
    "too_deep",
    "unsupported",
    "failed",
    "unreadable",
)
MEMBER_STATUSES = ("document", "locked", "too_large", "too_many", "failed")
PASSWORD_TIERS = (
    "manual",
    "mail",
    "thread",
    "contacts",
    "attachments",
    "opened",
    "archive",
    "typed",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in (
        ("document_protection", PROTECTIONS),
        ("document_members_status", MEMBERS_STATUSES),
        ("document_member_status", MEMBER_STATUSES),
        ("password_tier", PASSWORD_TIERS),
    ):
        postgresql.ENUM(*values, name=name).create(bind)
    protection = postgresql.ENUM(*PROTECTIONS, name="document_protection", create_type=False)
    members_status = postgresql.ENUM(
        *MEMBERS_STATUSES, name="document_members_status", create_type=False
    )
    member_status = postgresql.ENUM(
        *MEMBER_STATUSES, name="document_member_status", create_type=False
    )
    tier = postgresql.ENUM(*PASSWORD_TIERS, name="password_tier", create_type=False)

    # A member attachment (D231): an entry of a container attachment of the same mail, with its
    # path there. The mail's own MIME attachments have container_id and path NULL, byte for byte
    # as before, so no existing row changes (the columns have no default).
    op.add_column(
        "attachment",
        sa.Column(
            "container_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "attachment.id", name="fk_attachment_container_id_attachment", ondelete="CASCADE"
            ),
        ),
    )
    op.add_column("attachment", sa.Column("path", sa.Text()))
    op.create_index(
        "ix_attachment_container_id",
        "attachment",
        ["container_id"],
        postgresql_where=sa.text("container_id IS NOT NULL"),
    )

    # Protection and unpacking of a document (D233, D231), and how far the passwords step got
    # (D235). Existing documents start with members_status NULL (decided at the next run's
    # archives step); the columns have constant defaults, so adding them rewrites no row, and
    # nothing is read from the MBOX files here.
    op.add_column("document", sa.Column("protection", protection))
    op.add_column("document", sa.Column("members_status", members_status))
    op.add_column(
        "document",
        sa.Column("members_version", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column("document", sa.Column("members_error", sa.Text()))
    op.add_column(
        "document",
        sa.Column("password_tried_until", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "document",
        sa.Column("password_tries", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("document", sa.Column("password_tried_at", sa.DateTime(timezone=True)))
    op.add_column(
        "mail_export",
        sa.Column(
            "include_passwords", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    # The documents the text extraction already found encrypted are locked from the start, so the
    # list, the figures and the typed-in passwords (D237) see them before the next run.
    op.execute("UPDATE document SET protection = 'locked' WHERE text_status = 'encrypted'")
    op.create_index(
        "ix_document_protection",
        "document",
        ["protection"],
        postgresql_where=sa.text("protection IS NOT NULL"),
    )
    op.create_index(
        "ix_document_members_status",
        "document",
        ["members_status"],
        postgresql_where=sa.text("members_status IS NOT NULL"),
    )

    # The entries of a container, once per distinct container content (D231). member_id is the
    # entry's own document once it is unpacked.
    op.create_table(
        "document_member",
        sa.Column(
            "container_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "document.id", name="fk_document_member_container_id_document", ondelete="CASCADE"
            ),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("status", member_status, nullable=False),
        sa.Column(
            "member_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "document.id", name="fk_document_member_member_id_document", ondelete="SET NULL"
            ),
        ),
        sa.Column("error", sa.Text()),
    )
    op.create_index(
        "ix_document_member_member_id",
        "document_member",
        ["member_id"],
        postgresql_where=sa.text("member_id IS NOT NULL"),
    )

    # A distinct password and where it stands (D234). password.id orders the passwords step's
    # progress (document.password_tried_until).
    op.create_table(
        "password",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "password_finding",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "password_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "password.id", name="fk_password_finding_password_id_password", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", name="fk_password_finding_mail_id_mail", ondelete="CASCADE"),
        ),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "document.id", name="fk_password_finding_document_id_document", ondelete="CASCADE"
            ),
        ),
        sa.Column("context", sa.Text(), nullable=False, server_default=""),
        sa.Column("editor", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "password_id",
            "mail_id",
            "document_id",
            name="uq_password_finding_place",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_password_finding_mail_id",
        "password_finding",
        ["mail_id"],
        postgresql_where=sa.text("mail_id IS NOT NULL"),
    )
    op.create_index(
        "ix_password_finding_document_id",
        "password_finding",
        ["document_id"],
        postgresql_where=sa.text("document_id IS NOT NULL"),
    )

    # The password that opened a document (D236), as evidence; the bytes are never stored (D209).
    op.create_table(
        "document_password",
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "document.id", name="fk_document_password_document_id_document", ondelete="CASCADE"
            ),
            primary_key=True,
        ),
        sa.Column(
            "password_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "password.id", name="fk_document_password_password_id_password", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "finding_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "password_finding.id",
                name="fk_document_password_finding_id_password_finding",
                ondelete="SET NULL",
            ),
        ),
        sa.Column("tier", tier, nullable=False),
        sa.Column(
            "found_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("found_by", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("document_password")
    op.drop_index("ix_password_finding_document_id", table_name="password_finding")
    op.drop_index("ix_password_finding_mail_id", table_name="password_finding")
    op.drop_table("password_finding")
    op.drop_table("password")
    op.drop_index("ix_document_member_member_id", table_name="document_member")
    op.drop_table("document_member")
    op.drop_index("ix_document_members_status", table_name="document")
    op.drop_index("ix_document_protection", table_name="document")
    for column in (
        "password_tried_at",
        "password_tries",
        "password_tried_until",
        "members_error",
        "members_version",
        "members_status",
        "protection",
    ):
        op.drop_column("document", column)
    op.drop_column("mail_export", "include_passwords")
    op.drop_index("ix_attachment_container_id", table_name="attachment")
    op.drop_column("attachment", "path")
    op.drop_column("attachment", "container_id")
    bind = op.get_bind()
    for name in (
        "password_tier",
        "document_member_status",
        "document_members_status",
        "document_protection",
    ):
        postgresql.ENUM(name=name).drop(bind)

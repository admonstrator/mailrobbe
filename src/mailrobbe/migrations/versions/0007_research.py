"""Research file: review status and bookmark, notes, tags, Akten, saved searches, exports

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVIEW_STATUSES = ("seen", "relevant", "irrelevant")


def _created(name: str = "created_at") -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*REVIEW_STATUSES, name="review_status").create(bind)
    # Research data is keyed by the mail's raw SHA-256, not mail.id (D53): it outlives a
    # re-import of a file and a rebuilt database, so it has no foreign key to mail.
    op.create_table(
        "mail_mark",
        sa.Column("mail_sha256", sa.Text(), primary_key=True),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("flagged_by", sa.Text()),
        sa.Column("flagged_at", sa.DateTime(timezone=True)),
        sa.Column(
            "review", postgresql.ENUM(*REVIEW_STATUSES, name="review_status", create_type=False)
        ),
        sa.Column("review_by", sa.Text()),
        sa.Column("review_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "note",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("mail_sha256", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author", sa.Text()),
        _created(),
        _created("updated_at"),
    )
    op.create_index("ix_note_mail_sha256", "note", ["mail_sha256", "id"])
    op.create_index(
        "ix_note_body_trgm",
        "note",
        ["body"],
        postgresql_using="gin",
        postgresql_ops={"body": "gin_trgm_ops"},
    )
    op.create_table(
        "tag",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Text()),
        _created(),
    )
    op.create_index("ux_tag_name", "tag", [sa.text("lower(name)")], unique=True)
    op.create_table(
        "mail_tag",
        sa.Column(
            "tag_id",
            sa.BigInteger(),
            sa.ForeignKey("tag.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mail_sha256", sa.Text(), primary_key=True),
        sa.Column("added_by", sa.Text()),
        _created("added_at"),
    )
    op.create_index("ix_mail_tag_mail_sha256", "mail_tag", ["mail_sha256"])
    op.create_table(
        "collection",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Text()),
        _created(),
        _created("updated_at"),
    )
    op.create_index("ux_collection_name", "collection", [sa.text("lower(name)")], unique=True)
    op.create_table(
        "collection_mail",
        sa.Column(
            "collection_id",
            sa.BigInteger(),
            sa.ForeignKey("collection.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mail_sha256", sa.Text(), primary_key=True),
        sa.Column("added_by", sa.Text()),
        _created("added_at"),
    )
    op.create_index("ix_collection_mail_mail_sha256", "collection_mail", ["mail_sha256"])
    op.create_table(
        "saved_search",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column(
            "collection_id",
            sa.BigInteger(),
            sa.ForeignKey("collection.id", ondelete="SET NULL"),
        ),
        sa.Column("created_by", sa.Text()),
        _created(),
        _created("updated_at"),
    )
    op.create_index("ix_saved_search_collection_id", "saved_search", ["collection_id"])
    op.create_table(
        "mail_export",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("selection", postgresql.JSONB(), nullable=False),
        sa.Column(
            "include_research", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("mail_sha256", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("manifest_sha256", sa.Text()),
        sa.Column("downloaded_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Text()),
        _created(),
    )
    # The flag and note of D23 become a mark and a note without author (D55, D56).
    op.execute(
        """
        INSERT INTO mail_mark (mail_sha256, flagged, flagged_at)
        SELECT m.raw_sha256, true, max(n.updated_at)
        FROM mail_note n JOIN mail m ON m.id = n.mail_id
        WHERE n.flagged
        GROUP BY m.raw_sha256
        """
    )
    op.execute(
        """
        INSERT INTO note (mail_sha256, body, created_at, updated_at)
        SELECT m.raw_sha256, n.note, n.updated_at, n.updated_at
        FROM mail_note n JOIN mail m ON m.id = n.mail_id
        WHERE n.note <> ''
        ORDER BY n.updated_at, n.mail_id
        """
    )
    op.drop_table("mail_note")


def downgrade() -> None:
    op.create_table(
        "mail_note",
        sa.Column(
            "mail_id",
            sa.BigInteger(),
            sa.ForeignKey("mail.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        _created("updated_at"),
    )
    # Back onto the original of each content (lowest id among those that are no duplicate).
    op.execute(
        """
        INSERT INTO mail_note (mail_id, flagged, note, updated_at)
        SELECT (SELECT m.id FROM mail m WHERE m.raw_sha256 = r.mail_sha256
                ORDER BY m.is_duplicate_of IS NOT NULL, m.id LIMIT 1),
               bool_or(r.flagged), coalesce(string_agg(r.body, E'\n\n' ORDER BY r.id), ''),
               max(r.at)
        FROM (
            SELECT mail_sha256, flagged, NULL::text AS body, NULL::bigint AS id,
                   coalesce(flagged_at, review_at, now()) AS at
            FROM mail_mark
            UNION ALL
            SELECT mail_sha256, false, body, id, updated_at FROM note
        ) r
        WHERE EXISTS (SELECT 1 FROM mail m WHERE m.raw_sha256 = r.mail_sha256)
        GROUP BY r.mail_sha256
        HAVING bool_or(r.flagged) OR count(r.body) > 0
        """
    )
    op.drop_table("mail_export")
    op.drop_table("saved_search")
    op.drop_table("collection_mail")
    op.drop_table("collection")
    op.drop_table("mail_tag")
    op.drop_table("tag")
    op.drop_table("note")
    op.drop_table("mail_mark")
    postgresql.ENUM(name="review_status").drop(op.get_bind())

"""Documents judged again after D78: markup and encoded data without text, XPS read

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The next import's attachments phase reads these again and classifies them by their first
    # bytes: texts and archives, which may be SVG, keys, scripts or ZIPs of other formats, and
    # XPS files, which were unsupported. A text read before stays searchable until then.
    op.execute(
        """
        UPDATE document SET text_status = 'pending'
        WHERE text_status NOT IN ('pending', 'unreadable', 'too_large')
          AND (kind IN ('text', 'archive')
               OR name ~* '\\.o?xps$'
               OR mime_type IN ('application/vnd.ms-xpsdocument', 'application/oxps'))
        """
    )


def downgrade() -> None:
    pass  # the older extractors read pending documents the way they read any other

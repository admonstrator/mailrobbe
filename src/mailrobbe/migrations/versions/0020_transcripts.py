"""Transcripts of audio and video: the length of a recording and of the media a result read

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Seconds of a recording (D293): known once a transcription decoded it, NULL before and for
    # every other document. A transcript result keeps the seconds of its media and how far it read.
    op.add_column("document", sa.Column("duration", sa.Float()))
    op.add_column("ai_result", sa.Column("duration", sa.Float()))
    op.add_column("ai_result", sa.Column("transcribed", sa.Float()))


def downgrade() -> None:
    op.drop_column("ai_result", "transcribed")
    op.drop_column("ai_result", "duration")
    op.drop_column("document", "duration")

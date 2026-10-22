"""Places: the positions of photos, the points of place entities and invitations, map runs

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

JOB_KINDS = ("import", "dkim", "dkim_keys")  # before this revision
# db.models.PLACE_STATUS_CHECK: NULL until the places step looked at the row (D242, D243)
PLACE_STATUSES = "place_status IN ('found', 'ambiguous', 'unknown')"

# The position the metadata step stored (D167, D241), as attachments.metadata.model.summarize
# takes it for later documents: both coordinates numbers in range and not exactly 0, 0; the GPS
# time when it is ISO 8601 in UTC with a valid second, of the years 1900 to 2199. Nothing is
# read from the MBOX files.
_POSITIONS = r"""
UPDATE document SET
    metadata_latitude = (metadata_fields #>> '{gps,latitude}')::float8,
    metadata_longitude = (metadata_fields #>> '{gps,longitude}')::float8,
    metadata_gps_time = CASE
        WHEN metadata_fields #>> '{gps,timestamp}'
                 ~ '^(19\d\d|2[01]\d\d)-\d\d-\d\dT\d\d:\d\d:[0-5]\d(\.\d+)?Z$'
        THEN (metadata_fields #>> '{gps,timestamp}')::timestamptz
    END
WHERE metadata_gps
  AND jsonb_typeof(metadata_fields #> '{gps,latitude}') = 'number'
  AND jsonb_typeof(metadata_fields #> '{gps,longitude}') = 'number'
  AND abs((metadata_fields #>> '{gps,latitude}')::float8) <= 90
  AND abs((metadata_fields #>> '{gps,longitude}')::float8) <= 180
  AND NOT ((metadata_fields #>> '{gps,latitude}')::float8 = 0
           AND (metadata_fields #>> '{gps,longitude}')::float8 = 0)
"""


def upgrade() -> None:
    # A new enum value can be added inside the migration's transaction as long as nothing in
    # it uses the value (PostgreSQL 12 and later).
    op.execute("ALTER TYPE job_kind ADD VALUE 'map'")

    op.add_column("document", sa.Column("metadata_latitude", sa.Float()))
    op.add_column("document", sa.Column("metadata_longitude", sa.Float()))
    op.add_column("document", sa.Column("metadata_gps_time", postgresql.TIMESTAMP(timezone=True)))
    op.execute(_POSITIONS)
    op.create_index(
        "ix_document_metadata_position",
        "document",
        ["metadata_latitude", "metadata_longitude"],
        postgresql_where=sa.text("metadata_latitude IS NOT NULL"),
    )

    for table in ("entity", "calendar_event"):
        op.add_column(table, sa.Column("latitude", sa.Float()))
        op.add_column(table, sa.Column("longitude", sa.Float()))
        op.add_column(table, sa.Column("place_status", sa.Text()))
        op.add_column(table, sa.Column("place_label", sa.Text()))
        op.create_check_constraint("place_status", table, PLACE_STATUSES)
    op.create_index(
        "ix_entity_located",
        "entity",
        ["mails", "id"],
        postgresql_where=sa.text("latitude IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_entity_located", table_name="entity")
    for table in ("calendar_event", "entity"):
        # place_status's check constraint goes with its column
        for column in ("place_label", "place_status", "longitude", "latitude"):
            op.drop_column(table, column)
    op.drop_index("ix_document_metadata_position", table_name="document")
    for column in ("metadata_gps_time", "metadata_longitude", "metadata_latitude"):
        op.drop_column("document", column)
    op.execute("DELETE FROM job WHERE kind = 'map'")
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

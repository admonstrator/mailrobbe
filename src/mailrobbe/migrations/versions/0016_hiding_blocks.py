"""Hide rules, paragraphs and standard blocks, and the weighted full text index of mail

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-22
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The ranges of a text that are kept or cut, joined by a line break; character offsets from 0
# as Python counts them (code points), so the ranges the paragraphs step computes on body_text
# apply here unchanged (D226).
_KEEP = """
CREATE FUNCTION mailrobbe_keep(t text, keep int4multirange) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT COALESCE(string_agg(substr(t, lower(r) + 1, upper(r) - lower(r)), E'\\n'
                             ORDER BY lower(r)), '')
  FROM unnest(keep) AS r
$$
"""
_CUT = """
CREATE FUNCTION mailrobbe_cut(t text, cut int4multirange) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN t IS NULL OR cut IS NULL OR isempty(cut) THEN t
    ELSE mailrobbe_keep(t, int4multirange(int4range(0, length(t))) - cut) END
$$
"""
# mail.tsv by weight (D226): A the subject, B the own text without standard blocks, C the quoted
# text (quotes, originals, forwards) without standard blocks, D the standard blocks. Without
# history and blocks it is exactly the generated expression of migration 0002, so the mails the
# paragraphs step leaves alone keep their tsvector byte for byte.
_MAIL_TSV = """
CREATE FUNCTION mailrobbe_mail_tsv(
  subject text, body text, history int4multirange, blocks int4multirange
) RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN (history IS NULL OR isempty(history)) AND (blocks IS NULL OR isempty(blocks))
    THEN setweight(to_tsvector('german'::regconfig, COALESCE(subject, ''::text)), 'A'::"char")
      || setweight(to_tsvector('german'::regconfig, COALESCE(body, ''::text)), 'B'::"char")
    ELSE setweight(to_tsvector('german'::regconfig, COALESCE(subject, ''::text)), 'A'::"char")
      || setweight(to_tsvector('german'::regconfig, mailrobbe_cut(COALESCE(body, ''::text),
           COALESCE(history, '{}') + COALESCE(blocks, '{}'))), 'B'::"char")
      || setweight(to_tsvector('german'::regconfig, mailrobbe_keep(COALESCE(body, ''::text),
           COALESCE(history, '{}') - COALESCE(blocks, '{}'))), 'C'::"char")
      || setweight(to_tsvector('german'::regconfig, mailrobbe_keep(COALESCE(body, ''::text),
           COALESCE(blocks, '{}'))), 'D'::"char")
    END
$$
"""
_TRIGGER_FUNCTION = """
CREATE FUNCTION mailrobbe_mail_tsv_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.tsv := mailrobbe_mail_tsv(NEW.subject, NEW.body_text, NEW.history, NEW.blocks);
  RETURN NEW;
END
$$
"""
_TRIGGER = """
CREATE TRIGGER mail_tsv BEFORE INSERT OR UPDATE OF subject, body_text, history, blocks ON mail
FOR EACH ROW EXECUTE FUNCTION mailrobbe_mail_tsv_trigger()
"""
# The generated expression of migration 0002, for the downgrade.
_GENERATED = (
    "setweight(to_tsvector('german'::regconfig, COALESCE(subject, ''::text)), 'A'::\"char\") || "
    "setweight(to_tsvector('german'::regconfig, COALESCE(body_text, ''::text)), 'B'::\"char\")"
)


def _mail_id(table: str, primary_key: bool) -> sa.Column[int]:
    return sa.Column(
        "mail_id",
        sa.BigInteger(),
        sa.ForeignKey("mail.id", name=f"fk_{table}_mail_id_mail", ondelete="CASCADE"),
        primary_key=primary_key,
        nullable=False,
    )


def _times() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    # Hide rules (D221): the team's rules and the mails each one matches.
    op.create_table(
        "hide_rule",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("sender", sa.Text(), nullable=True),
        sa.Column("person_id", sa.BigInteger(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("list_id", sa.Text(), nullable=True),
        sa.Column("automated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("subject_match", sa.Text(), nullable=False, server_default="contains"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("mails", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Text(), nullable=True),
        *_times(),
        sa.CheckConstraint(
            "sender IS NOT NULL OR person_id IS NOT NULL OR domain IS NOT NULL "
            "OR list_id IS NOT NULL OR automated OR subject IS NOT NULL",
            name=op.f("ck_hide_rule_something"),
        ),
        sa.CheckConstraint(
            "subject_match IN ('contains', 'starts')", name=op.f("ck_hide_rule_subject_match")
        ),
    )
    op.create_table(
        "mail_hidden",
        sa.Column(
            "rule_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "hide_rule.id", name="fk_mail_hidden_rule_id_hide_rule", ondelete="CASCADE"
            ),
            primary_key=True,
        ),
        _mail_id("mail_hidden", primary_key=True),
    )
    op.create_index("ix_mail_hidden_mail_id", "mail_hidden", ["mail_id"])
    # Rules and suggestions by List-Id read the mails of one list (D221, D223).
    op.create_index(
        "ix_mail_list_id", "mail", ["list_id"], postgresql_where=sa.text("list_id IS NOT NULL")
    )

    # Paragraphs (D224) and standard blocks (D225): what the paragraphs step found in a mail's
    # stored text, the blocks the blocks step derived, and the team's choices.
    op.create_table(
        "mail_paragraph_scan",
        _mail_id("mail_paragraph_scan", primary_key=True),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("history", postgresql.INT4MULTIRANGE(), nullable=True),
    )
    op.create_table(
        "mail_paragraph",
        _mail_id("mail_paragraph", primary_key=True),
        sa.Column("position", sa.SmallInteger(), primary_key=True),
        sa.Column("hash", sa.BigInteger(), nullable=False),
        sa.Column("span", postgresql.INT4RANGE(), nullable=False),
        sa.Column("quoted", sa.Boolean(), nullable=False),
        sa.Column("tail", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_mail_paragraph_hash", "mail_paragraph", ["hash", "mail_id"])
    op.create_table(
        "paragraph_block",
        sa.Column("hash", sa.BigInteger(), primary_key=True),
        sa.Column("standard", sa.Boolean(), nullable=False),
        sa.Column("detected", sa.Boolean(), nullable=False),
        sa.Column("mails", sa.Integer(), nullable=False),
        sa.Column("senders", sa.Integer(), nullable=False),
        sa.Column("first_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sample", sa.Text(), nullable=False),
    )
    op.create_table(
        "paragraph_override",
        sa.Column("hash", sa.BigInteger(), primary_key=True),
        sa.Column("standard", sa.Boolean(), nullable=False),
        sa.Column("sample", sa.Text(), nullable=False),
        sa.Column("editor", sa.Text(), nullable=True),
        *_times(),
    )

    # The weighted full text index (D226): mail.tsv stops being a generated column, which keeps
    # every stored tsvector (no rewrite of mail); a trigger computes it from now on, also from the
    # ranges the blocks step sets.
    op.add_column("mail", sa.Column("history", postgresql.INT4MULTIRANGE(), nullable=True))
    op.add_column("mail", sa.Column("blocks", postgresql.INT4MULTIRANGE(), nullable=True))
    op.execute("ALTER TABLE mail ALTER COLUMN tsv DROP EXPRESSION")
    for statement in (_KEEP, _CUT, _MAIL_TSV, _TRIGGER_FUNCTION, _TRIGGER):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER mail_tsv ON mail")
    op.execute("DROP FUNCTION mailrobbe_mail_tsv_trigger()")
    op.execute("DROP FUNCTION mailrobbe_mail_tsv(text, text, int4multirange, int4multirange)")
    op.execute("DROP FUNCTION mailrobbe_cut(text, int4multirange)")
    op.execute("DROP FUNCTION mailrobbe_keep(text, int4multirange)")
    op.drop_index("ix_mail_tsv", table_name="mail")
    op.drop_column("mail", "tsv")
    op.add_column(
        "mail",
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(_GENERATED, persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_mail_tsv", "mail", ["tsv"], postgresql_using="gin")
    op.drop_column("mail", "blocks")
    op.drop_column("mail", "history")
    op.drop_table("paragraph_override")
    op.drop_table("paragraph_block")
    op.drop_table("mail_paragraph")
    op.drop_table("mail_paragraph_scan")
    op.drop_table("mail_hidden")
    op.drop_table("hide_rule")
    op.drop_index("ix_mail_list_id", table_name="mail")
    op.execute("DELETE FROM global_stats WHERE key IN ('hidden', 'blocks')")

"""ORM models for the data model in docs/SPEC.md section 3.3.

The schema itself is owned by the Alembic migrations in mailrobbe/migrations; these models must
stay identical to it (tests/db checks for drift). Deviations from the spec sketch:

- mail.offset/length and import_error.offset are named byte_offset/byte_length, because OFFSET is
  a reserved word in SQL and would need quoting in every hand-written query.
- mail.dkim_status is NULL until the DKIM check has run.
- mail_header and dkim_result carry a position/signature_index as part of the primary key, since
  headers repeat and a mail can carry several DKIM signatures.
- mbox_file has started_at/finished_at and worker_id (the importer worker reading it) for the
  import dashboard; path is relative to MAILROBBE_MBOX_DIR.
- mail.reference_ids holds the References header for threading; participation.display_name the
  name shown with the address in that mail, from which person_email.display_names is derived.
- mail.tsv is a stored generated column over subject (weight A) and body_text (weight B) with
  the TEXT_SEARCH_CONFIG configuration; queries must use the same configuration.
- edge.mails_total is a stored generated column (sum of all three counters) for the index the
  spec asks for.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from mailrobbe.db.base import Base
from mailrobbe.enums import DkimStatus, DnsStatus, MboxStatus, ParticipationRole


def _pg_enum(enum_cls: type[StrEnum], name: str) -> ENUM:
    return ENUM(
        enum_cls,
        name=name,
        values_callable=lambda cls: [member.value for member in cls],
        create_type=False,
    )


dkim_status_enum = _pg_enum(DkimStatus, "dkim_status")
participation_role_enum = _pg_enum(ParticipationRole, "participation_role")
mbox_status_enum = _pg_enum(MboxStatus, "mbox_status")
dns_status_enum = _pg_enum(DnsStatus, "dns_status")

TIMESTAMPTZ = DateTime(timezone=True)

# Full text search configuration of mail.tsv (migration 0002); search queries must use it too.
TEXT_SEARCH_CONFIG = "german"
TSV_EXPRESSION = " || ".join(
    f"setweight(to_tsvector('{TEXT_SEARCH_CONFIG}'::regconfig, COALESCE({column}, ''::text)), "
    f"'{weight}'::\"char\")"
    for column, weight in (("subject", "A"), ("body_text", "B"))
)


class MboxFile(Base):
    __tablename__ = "mbox_file"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    path: Mapped[str] = mapped_column(Text, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256_head: Mapped[str | None] = mapped_column(Text)
    status: Mapped[MboxStatus] = mapped_column(mbox_status_enum, server_default="pending")
    mails_parsed: Mapped[int] = mapped_column(BigInteger, server_default="0")
    bytes_done: Mapped[int] = mapped_column(BigInteger, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    worker_id: Mapped[int | None] = mapped_column(SmallInteger)


class Mail(Base):
    __tablename__ = "mail"
    __table_args__ = (
        UniqueConstraint("mbox_file_id", "byte_offset"),
        Index("ix_mail_date_utc", "date_utc"),
        Index("ix_mail_message_id", "message_id"),
        Index("ix_mail_raw_sha256", "raw_sha256"),
        Index("ix_mail_thread_id", "thread_id"),
        Index("ix_mail_dkim_status", "dkim_status"),
        Index("ix_mail_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_mail_is_duplicate_of",
            "is_duplicate_of",
            postgresql_where=text("is_duplicate_of IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mbox_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mbox_file.id", ondelete="CASCADE")
    )
    byte_offset: Mapped[int] = mapped_column(BigInteger)
    byte_length: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[str | None] = mapped_column(Text)
    in_reply_to: Mapped[str | None] = mapped_column(Text)
    thread_id: Mapped[int | None] = mapped_column(BigInteger)
    subject: Mapped[str | None] = mapped_column(Text)
    date_utc: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    raw_sha256: Mapped[str] = mapped_column(Text)
    has_attachments: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    body_text: Mapped[str | None] = mapped_column(Text)
    tsv: Mapped[Any | None] = mapped_column(TSVECTOR, Computed(TSV_EXPRESSION, persisted=True))
    dkim_status: Mapped[DkimStatus | None] = mapped_column(dkim_status_enum)
    is_duplicate_of: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("mail.id", ondelete="SET NULL")
    )
    reference_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text))


class MailHeader(Base):
    __tablename__ = "mail_header"

    mail_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mail.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)


class Person(Base):
    __tablename__ = "person"
    __table_args__ = (
        Index("ix_person_domain", "domain"),
        Index("ix_person_merged_into", "merged_into"),
        Index(
            "ix_person_canonical_email_trgm",
            "canonical_email",
            postgresql_using="gin",
            postgresql_ops={"canonical_email": "gin_trgm_ops"},
        ),
        Index(
            "ix_person_display_name_trgm",
            "display_name",
            postgresql_using="gin",
            postgresql_ops={"display_name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    canonical_email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text)
    merged_into: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="SET NULL")
    )


class PersonEmail(Base):
    __tablename__ = "person_email"
    __table_args__ = (
        Index("ix_person_email_person_id", "person_id"),
        Index(
            "ix_person_email_email_trgm",
            "email",
            postgresql_using="gin",
            postgresql_ops={"email": "gin_trgm_ops"},
        ),
    )

    email: Mapped[str] = mapped_column(Text, primary_key=True)
    person_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("person.id", ondelete="CASCADE"))
    display_names: Mapped[dict[str, int]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class Participation(Base):
    __tablename__ = "participation"
    __table_args__ = (Index("ix_participation_person_id_role", "person_id", "role", "mail_id"),)

    mail_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mail.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[ParticipationRole] = mapped_column(participation_role_enum, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text)


class Attachment(Base):
    __tablename__ = "attachment"
    __table_args__ = (
        Index("ix_attachment_mail_id", "mail_id"),
        Index("ix_attachment_sha256", "sha256"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mail_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mail.id", ondelete="CASCADE"))
    filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(Text)


class DkimResult(Base):
    __tablename__ = "dkim_result"
    __table_args__ = (Index("ix_dkim_result_domain_selector", "domain", "selector"),)

    mail_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mail.id", ondelete="CASCADE"), primary_key=True
    )
    signature_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    status: Mapped[DkimStatus] = mapped_column(dkim_status_enum)
    domain: Mapped[str | None] = mapped_column(Text)
    selector: Mapped[str | None] = mapped_column(Text)
    algorithm: Mapped[str | None] = mapped_column(Text)
    key_bits: Mapped[int | None] = mapped_column(Integer)
    signed_headers: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    body_hash_ok: Mapped[bool | None] = mapped_column(Boolean)
    signed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    aligned: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    dns_cached: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class DnsCache(Base):
    __tablename__ = "dns_cache"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    record: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DnsStatus] = mapped_column(dns_status_enum)
    fetched_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    ttl: Mapped[int] = mapped_column(Integer)


class ImportErrorRecord(Base):
    __tablename__ = "import_error"
    __table_args__ = (
        Index("ix_import_error_mbox_file_id_created_at", "mbox_file_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mbox_file_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("mbox_file.id", ondelete="CASCADE")
    )
    byte_offset: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


# Aggregation tables (SPEC 3.3): every figure, top list and the graph read from here.


class Edge(Base):
    __tablename__ = "edge"
    __table_args__ = (
        CheckConstraint("person_a < person_b", name="ordered"),
        Index("ix_edge_person_b", "person_b"),
        Index("ix_edge_mails_total", "mails_total"),
    )

    person_a: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    person_b: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    mails_a_to_b: Mapped[int] = mapped_column(Integer, server_default="0")
    mails_b_to_a: Mapped[int] = mapped_column(Integer, server_default="0")
    mails_cc: Mapped[int] = mapped_column(Integer, server_default="0")
    mails_total: Mapped[int] = mapped_column(
        Integer, Computed("mails_a_to_b + mails_b_to_a + mails_cc", persisted=True)
    )
    first_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class EdgeYear(Base):
    __tablename__ = "edge_year"
    __table_args__ = (Index("ix_edge_year_person_b", "person_b"),)

    person_a: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    person_b: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, server_default="0")


class PersonStats(Base):
    __tablename__ = "person_stats"

    person_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    sent: Mapped[int] = mapped_column(Integer, server_default="0")
    received: Mapped[int] = mapped_column(Integer, server_default="0")
    cc_only: Mapped[int] = mapped_column(Integer, server_default="0")
    contacts: Mapped[int] = mapped_column(Integer, server_default="0")
    first_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    dkim_pass_ratio: Mapped[float | None] = mapped_column(REAL)


class PersonYear(Base):
    __tablename__ = "person_year"

    person_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    sent: Mapped[int] = mapped_column(Integer, server_default="0")
    received: Mapped[int] = mapped_column(Integer, server_default="0")


class GlobalStats(Base):
    __tablename__ = "global_stats"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

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
- ix_mail_sort orders mails by MAIL_SORT_KEY (date, missing dates oldest) and id, for keyset
  paging in the mail list (D19), ix_mail_dkim_sort the same within one DKIM status (it replaced
  ix_mail_dkim_status); ix_mail_subject_trgm serves the subject: search (D20).
- The research file (migration 0007, D53 to D62) is the data users write, apart from merges
  (person.merged_into) and alias_dismissal (D28): mail_mark (bookmark and review status), note,
  tag/mail_tag, collection/collection_mail (Akten), saved_search and mail_export. Rows about a
  mail are keyed by its raw_sha256 (mail_sha256) instead of mail.id, so they have no foreign key
  to mail and outlive re-imports (D53); mail_mark replaced mail_note (D23).
- edge and edge_year carry the same counters (migration 0004, D36): mails_a_to_b/mails_b_to_a
  (To and Bcc), mails_cc (either direction) and their pass_* counterparts over the mails whose
  DKIM check passed; edge_year has no single count. Both join root persons only.
- mail.list_id and mail.automated record List-Id and automation headers, person.kind marks
  lists and automated senders among the root persons (D39).
- person_stats.mails is a stored generated column (sent + received); it and LAST_DATE_SORT_KEY
  are the sort keys of the person list (migration 0005, D31). alias_suggestion holds the
  computed suggestions (D30); both pair tables order their persons (person_a < person_b).
- job holds one row per run of `mailrobbe import` and `mailrobbe dkim` with its live figures
  and the dashboard's stop request (migration 0006, D47); mbox_file.header_version says whether
  the mails of a file have every parsed header field (HEADER_VERSION, D52).
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
from mailrobbe.enums import (
    DkimStatus,
    DnsStatus,
    JobKind,
    JobStatus,
    MboxStatus,
    ParticipationRole,
    PersonKind,
    ReviewStatus,
)


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
person_kind_enum = _pg_enum(PersonKind, "person_kind")
job_kind_enum = _pg_enum(JobKind, "job_kind")
job_status_enum = _pg_enum(JobStatus, "job_status")
review_status_enum = _pg_enum(ReviewStatus, "review_status")

TIMESTAMPTZ = DateTime(timezone=True)

# Full text search configuration of mail.tsv (migration 0002); search queries must use it too.
TEXT_SEARCH_CONFIG = "german"
TSV_EXPRESSION = " || ".join(
    f"setweight(to_tsvector('{TEXT_SEARCH_CONFIG}'::regconfig, COALESCE({column}, ''::text)), "
    f"'{weight}'::\"char\")"
    for column, weight in (("subject", "A"), ("body_text", "B"))
)


# Sort key of the mail list (migration 0003, D19): mails without a date sort as the oldest.
# Keyset conditions and ORDER BY must use exactly this expression to use ix_mail_sort.
MAIL_SORT_KEY = "COALESCE(date_utc, '-infinity'::timestamp with time zone)"

# Sort key of the person list by latest mail (migration 0005, D31): persons without one last.
LAST_DATE_SORT_KEY = "COALESCE(last_date, '-infinity'::timestamp with time zone)"

# mbox_file.header_version of a file whose stored mails have every header field the importer
# parses (migration 0006, D52): 1 = with list_id and automated (D39). Files imported before
# have 0, and the importer reads the headers of their mails again.
HEADER_VERSION = 1


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
    header_version: Mapped[int] = mapped_column(SmallInteger, server_default=str(HEADER_VERSION))


class Mail(Base):
    __tablename__ = "mail"
    __table_args__ = (
        UniqueConstraint("mbox_file_id", "byte_offset"),
        Index("ix_mail_date_utc", "date_utc"),
        Index("ix_mail_message_id", "message_id"),
        Index("ix_mail_raw_sha256", "raw_sha256"),
        Index("ix_mail_thread_id", "thread_id"),
        Index("ix_mail_tsv", "tsv", postgresql_using="gin"),
        Index("ix_mail_sort", text(MAIL_SORT_KEY), "id"),
        Index("ix_mail_dkim_sort", "dkim_status", text(MAIL_SORT_KEY), "id"),
        Index(
            "ix_mail_subject_trgm",
            "subject",
            postgresql_using="gin",
            postgresql_ops={"subject": "gin_trgm_ops"},
        ),
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
    list_id: Mapped[str | None] = mapped_column(Text)
    automated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


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
    kind: Mapped[PersonKind | None] = mapped_column(person_kind_enum)


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
    pass_a_to_b: Mapped[int] = mapped_column(Integer, server_default="0")
    pass_b_to_a: Mapped[int] = mapped_column(Integer, server_default="0")
    pass_cc: Mapped[int] = mapped_column(Integer, server_default="0")


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
    mails_a_to_b: Mapped[int] = mapped_column(Integer, server_default="0")
    mails_b_to_a: Mapped[int] = mapped_column(Integer, server_default="0")
    mails_cc: Mapped[int] = mapped_column(Integer, server_default="0")
    pass_a_to_b: Mapped[int] = mapped_column(Integer, server_default="0")
    pass_b_to_a: Mapped[int] = mapped_column(Integer, server_default="0")
    pass_cc: Mapped[int] = mapped_column(Integer, server_default="0")


class PersonStats(Base):
    __tablename__ = "person_stats"
    __table_args__ = (
        Index("ix_person_stats_mails", "mails", "person_id"),
        Index("ix_person_stats_last_date", text(LAST_DATE_SORT_KEY), "person_id"),
    )

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
    mails: Mapped[int] = mapped_column(Integer, Computed("sent + received", persisted=True))


class PersonYear(Base):
    __tablename__ = "person_year"

    person_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    sent: Mapped[int] = mapped_column(Integer, server_default="0")
    received: Mapped[int] = mapped_column(Integer, server_default="0")


class AliasSuggestion(Base):
    __tablename__ = "alias_suggestion"
    __table_args__ = (
        CheckConstraint("person_a < person_b", name="ordered"),
        CheckConstraint("same_name IS NOT NULL OR same_local_part IS NOT NULL", name="reason"),
        Index("ix_alias_suggestion_person_b", "person_b"),
    )

    person_a: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    person_b: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    same_name: Mapped[str | None] = mapped_column(Text)  # the normalized display name both use
    same_local_part: Mapped[str | None] = mapped_column(Text)  # the local part both addresses have


class AliasDismissal(Base):
    __tablename__ = "alias_dismissal"
    __table_args__ = (CheckConstraint("person_a < person_b", name="ordered"),)

    person_a: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    person_b: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class GlobalStats(Base):
    __tablename__ = "global_stats"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class Job(Base):
    """A run of `mailrobbe import` or `mailrobbe dkim` (D47); mailrobbe.jobs reads and writes it."""

    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint("origin IN ('cli', 'ui')", name="origin"),
        Index("ix_job_kind", "kind", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[JobKind] = mapped_column(job_kind_enum)
    origin: Mapped[str] = mapped_column(Text)
    status: Mapped[JobStatus] = mapped_column(job_status_enum, server_default="running")
    phase: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    message: Mapped[str | None] = mapped_column(Text)
    stop_requested: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


# Research file (migration 0007, D53 to D62): mails are named by their raw SHA-256.


class MailMark(Base):
    """Bookmark and review status of a mail's content (D55); no row: neither set yet."""

    __tablename__ = "mail_mark"

    mail_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    flagged: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    flagged_by: Mapped[str | None] = mapped_column(Text)
    flagged_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    review: Mapped[ReviewStatus | None] = mapped_column(review_status_enum)
    review_by: Mapped[str | None] = mapped_column(Text)
    review_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class Note(Base):
    __tablename__ = "note"
    __table_args__ = (
        Index("ix_note_mail_sha256", "mail_sha256", "id"),
        Index(
            "ix_note_body_trgm",
            "body",
            postgresql_using="gin",
            postgresql_ops={"body": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mail_sha256: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class Tag(Base):
    __tablename__ = "tag"
    __table_args__ = (Index("ux_tag_name", text("lower(name)"), unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text)  # schemas.TagColor
    description: Mapped[str] = mapped_column(Text, server_default="")
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class MailTag(Base):
    __tablename__ = "mail_tag"
    __table_args__ = (Index("ix_mail_tag_mail_sha256", "mail_sha256"),)

    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )
    mail_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    added_by: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class Collection(Base):
    """An Akte (D58): a named collection of mails."""

    __tablename__ = "collection"
    __table_args__ = (Index("ux_collection_name", text("lower(name)"), unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class CollectionMail(Base):
    __tablename__ = "collection_mail"
    __table_args__ = (Index("ix_collection_mail_mail_sha256", "mail_sha256"),)

    collection_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("collection.id", ondelete="CASCADE"), primary_key=True
    )
    mail_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    added_by: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class SavedSearch(Base):
    __tablename__ = "saved_search"
    __table_args__ = (Index("ix_saved_search_collection_id", "collection_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text)  # query string of the mail list (D59)
    collection_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("collection.id", ondelete="SET NULL")
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class MailExport(Base):
    """One export (D62): who asked for which mails, in export order, and its manifest hash."""

    __tablename__ = "mail_export"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    label: Mapped[str] = mapped_column(Text, server_default="")
    selection: Mapped[dict[str, Any]] = mapped_column(JSONB)  # the MailSelection as requested
    include_research: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    mail_sha256: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # SHA-256 of the ZIP's SHA256SUMS and the time of the first complete download; None before
    manifest_sha256: Mapped[str | None] = mapped_column(Text)
    downloaded_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

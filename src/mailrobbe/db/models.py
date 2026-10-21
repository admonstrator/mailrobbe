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
- Entities (migration 0010, D80 to D85): entity holds one row per kind and normalised key with
  its figures; mail_entity and document_entity record where each is mentioned (the mail's own
  subject and text, or a document's extracted text); mail_entity_scan and document_entity_scan
  record which mails and document texts were scanned, by which scan version.
- Keys of deleted selectors (migration 0011, D100 to D103): dkim_key holds every key known from
  a source other than today's DNS, dkim_key_lookup every question to a source with its answer
  unchanged, dkim_key_evidence what a lookup says about a key; dkim_result.key_id and key_origin
  name the key a result rests on (key_id NULL for today's DNS).
- Topics (migration 0012, D140 to D146): the topics phase replaces all of them at once.
  topic_term is the vocabulary (a lexeme of mail.tsv with its label and mails), topic_period and
  topic_period_term the terms that stand out per month, quarter and year, topic_cluster with
  topic_cluster_term and topic_cluster_month the clusters, topic_state the single row saying for
  which archive (fingerprint) and when they were computed.
- Signals (migration 0013, D130 to D135): mail_signal holds the signals that hold for each mail
  (duplicates included), person_signal per root person the mails it sent with each signal and
  whether it fell silent; both are recomputed by the signals phase of every import, and
  global_stats 'signals' keeps that phase's figures and rules (mailrobbe.signals.model).
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
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
    DocumentKind,
    DocumentTextStatus,
    EntityKind,
    JobKind,
    JobStatus,
    KeyOrigin,
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
document_kind_enum = _pg_enum(DocumentKind, "document_kind")
document_text_status_enum = _pg_enum(DocumentTextStatus, "document_text_status")
entity_kind_enum = _pg_enum(EntityKind, "entity_kind")
key_origin_enum = _pg_enum(KeyOrigin, "key_origin")

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

# Text of a document (migration 0008, D72): stored and indexed up to this many characters, which
# keeps document.tsv well below PostgreSQL's 1 MB limit of a tsvector for ordinary text.
DOCUMENT_TEXT_LIMIT = 400_000
# document.extractor_version of a text extracted by the current extractors; raising it extracts
# the documents of lower versions again at the next import (D72).
EXTRACTOR_VERSION = 1
# document.tsv: file names (one per line, "_" "." "-" read as spaces) weighted A, extracted_text B.
DOCUMENT_TSV_EXPRESSION = (
    f"setweight(to_tsvector('{TEXT_SEARCH_CONFIG}'::regconfig, "
    "translate(names, '_.-'::text, '   '::text)), 'A'::\"char\") || "
    f"setweight(to_tsvector('{TEXT_SEARCH_CONFIG}'::regconfig, "
    "COALESCE(extracted_text, ''::text)), 'B'::\"char\")"
)
# Sort key of the document list by first appearance (D74): documents without a dated mail last.
# The entity list sorts by the same expression over entity.first_date (D88).
FIRST_DATE_SORT_KEY = "COALESCE(first_date, '-infinity'::timestamp with time zone)"

# Version of the entity extraction's code (migration 0010, D84): raising it scans every mail and
# document again at the next import. The scan tables store entities.model.scan_version(), which
# also changes when the word lists or gazetteers change.
ENTITY_VERSION = 1


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
        # the mails of a document, read from the index alone (search through attachments, D73)
        Index("ix_attachment_document_id", "document_id", "mail_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mail_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("mail.id", ondelete="CASCADE"))
    filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(Text)
    # 0-based among the mail's attachments in the order importer.parse.mime_parts finds them
    position: Mapped[int] = mapped_column(SmallInteger)
    # NULL until the next finalize assigns it (attachments.documents)
    document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("document.id", ondelete="SET NULL")
    )


class Document(Base):
    """One distinct attachment content (D70): its text and figures over the mails carrying it."""

    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint("sha256"),
        Index("ix_document_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_document_names_trgm",
            "names",
            postgresql_using="gin",
            postgresql_ops={"names": "gin_trgm_ops"},
        ),
        Index("ix_document_first_date", text(FIRST_DATE_SORT_KEY), "id"),
        Index("ix_document_mails", "mails", "id"),
        Index("ix_document_size_bytes", "size_bytes", "id"),
        Index("ix_document_kind", "kind"),
        Index("ix_document_text_status", "text_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # NULL for an attachment above the hash limit (D18), which is a document of its own
    sha256: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)  # the file name used most
    names: Mapped[str] = mapped_column(Text, server_default="")  # every file name, one per line
    mime_type: Mapped[str] = mapped_column(Text)  # the declared MIME type used most
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[DocumentKind | None] = mapped_column(document_kind_enum)  # NULL: unclassified
    text_status: Mapped[DocumentTextStatus] = mapped_column(
        document_text_status_enum, server_default="pending"
    )
    # at most DOCUMENT_TEXT_LIMIT characters; NULL until extracted or without text
    extracted_text: Mapped[str | None] = mapped_column(Text)
    text_truncated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    text_error: Mapped[str | None] = mapped_column(Text)  # English, one line
    pages: Mapped[int | None] = mapped_column(Integer)  # pages, sheets or slides
    extractor_version: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    extracted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    # Figures over the mails carrying it that are not duplicates (D70), set by finalize.
    mails: Mapped[int] = mapped_column(Integer, server_default="0")
    attachments: Mapped[int] = mapped_column(Integer, server_default="0")  # duplicates included
    first_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    first_mail_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("mail.id", ondelete="SET NULL")
    )
    tsv: Mapped[Any | None] = mapped_column(
        TSVECTOR, Computed(DOCUMENT_TSV_EXPRESSION, persisted=True)
    )


class DkimResult(Base):
    __tablename__ = "dkim_result"
    __table_args__ = (
        Index("ix_dkim_result_domain_selector", "domain", "selector"),
        Index("ix_dkim_result_key_id", "key_id", postgresql_where=text("key_id IS NOT NULL")),
    )

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
    # The dkim_key that verified the signature; NULL for a key from today's DNS and without key.
    key_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dkim_key.id", ondelete="SET NULL")
    )
    # Origin of the key the result rests on (D100); NULL when it rests on none (no_key,
    # temp_error, a signature that failed before its key was asked for).
    key_origin: Mapped[KeyOrigin | None] = mapped_column(key_origin_enum)


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


class Entity(Base):
    """One thing found in the texts (D80, D81): a kind and its normalised key, with figures."""

    __tablename__ = "entity"
    __table_args__ = (
        UniqueConstraint("kind", "key"),
        Index("ix_entity_kind_mails", "kind", "mails", "id"),
        Index("ix_entity_mails", "mails", "id"),
        Index("ix_entity_first_date", text(FIRST_DATE_SORT_KEY), "id"),
        Index("ix_entity_value", "value", "id", postgresql_where=text("value IS NOT NULL")),
        Index(
            "ix_entity_label_trgm",
            "label",
            postgresql_using="gin",
            postgresql_ops={"label": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[EntityKind] = mapped_column(entity_kind_enum)
    key: Mapped[str] = mapped_column(Text)  # normalised, unique within the kind (D81)
    label: Mapped[str] = mapped_column(Text)  # the display form, as first stored
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # amount: the sum
    currency: Mapped[str | None] = mapped_column(Text)  # amount: ISO 4217 code
    # term: theme key; place: city or country; iban, phone: country code; url: host
    detail: Mapped[str | None] = mapped_column(Text)
    # Figures over the mentioning mails that are not duplicates (D85), set at the end of the
    # entities phase; documents: documents whose text mentions it.
    mails: Mapped[int] = mapped_column(Integer, server_default="0")
    documents: Mapped[int] = mapped_column(Integer, server_default="0")
    first_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class MailEntity(Base):
    """An entity mentioned in a mail's own subject or text (entities.model.scanned_text)."""

    __tablename__ = "mail_entity"
    __table_args__ = (Index("ix_mail_entity_mail_id", "mail_id", "entity_id"),)

    entity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE"), primary_key=True
    )
    mail_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mail.id", ondelete="CASCADE"), primary_key=True
    )
    occurrences: Mapped[int] = mapped_column(Integer)
    context: Mapped[int] = mapped_column(SmallInteger, server_default="0")  # EntityContext
    position: Mapped[int] = mapped_column(Integer)  # of the first occurrence in the scanned text


class DocumentEntity(Base):
    """An entity mentioned in a document's extracted text; it counts for every mail carrying
    the document (D80)."""

    __tablename__ = "document_entity"
    __table_args__ = (Index("ix_document_entity_document_id", "document_id", "entity_id"),)

    entity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document.id", ondelete="CASCADE"), primary_key=True
    )
    occurrences: Mapped[int] = mapped_column(Integer)
    context: Mapped[int] = mapped_column(SmallInteger, server_default="0")  # EntityContext
    position: Mapped[int] = mapped_column(Integer)  # of the first occurrence in extracted_text


class MailEntityScan(Base):
    """A mail whose text the entities phase scanned, by which scan version (D84)."""

    __tablename__ = "mail_entity_scan"

    mail_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mail.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer)  # entities.model.scan_version()


class DocumentEntityScan(Base):
    """A document text the entities phase scanned: by which scan version, and the document's
    extracted_at of that text, so that a text extracted again is scanned again (D84)."""

    __tablename__ = "document_entity_scan"

    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer)  # entities.model.scan_version()
    extracted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


# Keys of deleted selectors (migration 0011, D100 to D103).


class DkimKey(Base):
    """A key for one key name from a source other than today's DNS; one row per content."""

    __tablename__ = "dkim_key"
    __table_args__ = (
        UniqueConstraint("name", "key_sha256"),
        Index("ix_dkim_key_domain", "domain"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)  # '<selector>._domainkey.<domain>', normalised
    domain: Mapped[str] = mapped_column(Text)
    selector: Mapped[str] = mapped_column(Text)
    key_type: Mapped[str] = mapped_column(Text)  # rsa or ed25519
    bits: Mapped[int] = mapped_column(Integer)
    # SHA-256 of the public key (keys.identity): the key's identity across sources
    key_sha256: Mapped[str] = mapped_column(Text)
    record: Mapped[str] = mapped_column(Text)  # the TXT record as found, or one made for it
    origin: Mapped[KeyOrigin] = mapped_column(key_origin_enum)  # strongest of its evidence
    # Shares a prime factor with another known RSA modulus (Batch-GCD): never used to verify.
    factorable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class DkimKeyLookup(Base):
    """One question to a key source and its answer unchanged, found or not (D101)."""

    __tablename__ = "dkim_key_lookup"
    __table_args__ = (
        Index("ix_dkim_key_lookup_domain", "domain"),
        Index("ix_dkim_key_lookup_name", "name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(Text)  # enums.KeyLookupSource
    query: Mapped[str] = mapped_column(Text)  # URL, key name or what was searched; no secrets
    domain: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)  # the key name, when it was about one
    asked_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    outcome: Mapped[str] = mapped_column(Text)  # enums.LookupOutcome
    http_status: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[bytes | None] = mapped_column(LargeBinary)  # the answer, or the evidence file
    raw_sha256: Mapped[str | None] = mapped_column(Text)
    raw_type: Mapped[str | None] = mapped_column(Text)  # media type of raw
    raw_name: Mapped[str | None] = mapped_column(Text)  # file name of an uploaded evidence file
    message: Mapped[str | None] = mapped_column(Text)  # English: the error, or what was done
    tool_version: Mapped[str] = mapped_column(Text)  # Mailrobbe's version
    editor: Mapped[str | None] = mapped_column(Text)  # D54


class DkimKeyEvidence(Base):
    """What one lookup says about one key: its origin and the source's own times (D100)."""

    __tablename__ = "dkim_key_evidence"
    __table_args__ = (
        UniqueConstraint("key_id", "lookup_id"),
        Index("ix_dkim_key_evidence_lookup_id", "lookup_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    key_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dkim_key.id", ondelete="CASCADE"))
    lookup_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dkim_key_lookup.id", ondelete="CASCADE")
    )
    origin: Mapped[KeyOrigin] = mapped_column(key_origin_enum)
    # The source's times: first and last seen in DNS, or the date of the document
    observed_from: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    observed_to: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    reference: Mapped[str | None] = mapped_column(Text)  # URL, /m/<hash>, /anhaenge/<id>, file
    note: Mapped[str | None] = mapped_column(Text)
    # Per source (keys.store): the signatures of a reconstruction, the archive's entry, ...
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    editor: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


# Topics (migration 0012, D140 to D146): computed by the topics phase and replaced as a whole.

TOPIC_UNIT_CHECK = "unit IN ('month', 'quarter', 'year')"  # topics.model.Unit


class TopicState(Base):
    """For which archive and when the topics were computed (D146); at most one row."""

    __tablename__ = "topic_state"
    __table_args__ = (CheckConstraint("id = 1", name="single"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text)  # topics.phase.waiting
    computed_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    mails: Mapped[int] = mapped_column(Integer)  # N: the archive's mails that are no duplicates
    terms: Mapped[int] = mapped_column(Integer)  # rows of topic_term
    clusters: Mapped[int] = mapped_column(Integer)  # rows of topic_cluster
    seconds: Mapped[float] = mapped_column(REAL)  # the phase took


class TopicTerm(Base):
    """A term of the vocabulary (D141)."""

    __tablename__ = "topic_term"
    __table_args__ = (UniqueConstraint("lexeme"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    lexeme: Mapped[str] = mapped_column(Text)  # as in mail.tsv
    label: Mapped[str] = mapped_column(Text)  # the spelling used most
    mails: Mapped[int] = mapped_column(Integer)  # df: mails that are no duplicates holding it
    themes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))


class TopicPeriod(Base):
    """A month, quarter or year with mails (D143)."""

    __tablename__ = "topic_period"
    __table_args__ = (CheckConstraint(TOPIC_UNIT_CHECK, name="unit"),)

    unit: Mapped[str] = mapped_column(Text, primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)  # its first day (UTC)
    mails: Mapped[int] = mapped_column(Integer)  # n: its mails that are no duplicates


class TopicPeriodTerm(Base):
    """A term that stands out in a period, by rank (D142, D143)."""

    __tablename__ = "topic_period_term"
    __table_args__ = (
        ForeignKeyConstraint(
            ["unit", "period_start"],
            ["topic_period.unit", "topic_period.period_start"],
            ondelete="CASCADE",
        ),
        Index("ix_topic_period_term_term_id", "term_id"),
    )

    unit: Mapped[str] = mapped_column(Text, primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger, primary_key=True)  # 1 = stands out most
    term_id: Mapped[int] = mapped_column(Integer, ForeignKey("topic_term.id", ondelete="CASCADE"))
    mails: Mapped[int] = mapped_column(Integer)  # a: the period's mails holding it
    score: Mapped[float] = mapped_column(REAL)  # G2


class TopicCluster(Base):
    """A cluster of terms that stand together (D145)."""

    __tablename__ = "topic_cluster"
    __table_args__ = (UniqueConstraint("rank"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger)  # 1 = most mails
    label: Mapped[str] = mapped_column(Text)  # topics.model.cluster_label
    query: Mapped[str] = mapped_column(Text)  # topics.model.cluster_query
    mails: Mapped[int] = mapped_column(Integer)
    first_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_date: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class TopicClusterTerm(Base):
    __tablename__ = "topic_cluster_term"
    __table_args__ = (Index("ix_topic_cluster_term_term_id", "term_id"),)

    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topic_cluster.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(SmallInteger, primary_key=True)  # 1 = strongest
    term_id: Mapped[int] = mapped_column(Integer, ForeignKey("topic_term.id", ondelete="CASCADE"))
    weight: Mapped[float] = mapped_column(REAL)  # its links inside the cluster


class TopicClusterMonth(Base):
    __tablename__ = "topic_cluster_month"

    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topic_cluster.id", ondelete="CASCADE"), primary_key=True
    )
    month: Mapped[date] = mapped_column(Date, primary_key=True)  # first day (UTC)
    mails: Mapped[int] = mapped_column(Integer)


# Signals (migration 0013, D130 to D135).


class MailSignal(Base):
    """A signal that holds for a mail (D132): a SignalKind value or "term:<theme key>"."""

    __tablename__ = "mail_signal"
    __table_args__ = (Index("ix_mail_signal_mail_id", "mail_id", "signal"),)

    signal: Mapped[str] = mapped_column(Text, primary_key=True)
    mail_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mail.id", ondelete="CASCADE"), primary_key=True
    )


class PersonSignal(Base):
    """A root person's figure for a signal at the last signals phase (D134, D135): for a mail
    signal the mails it sent with it (no duplicates); for silent the mails of the window before
    its silence and the month it began."""

    __tablename__ = "person_signal"
    __table_args__ = (Index("ix_person_signal_mails", "signal", "mails", "person_id"),)

    signal: Mapped[str] = mapped_column(Text, primary_key=True)
    person_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    mails: Mapped[int] = mapped_column(Integer)
    since: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)  # silent: first silent month

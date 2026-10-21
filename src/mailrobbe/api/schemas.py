"""The HTTP contract of the web UI (SPEC 4, milestone 4): query parameters and response bodies.

frontend/src/api/types.ts mirrors these models by hand; change both together. Times are ISO 8601
in UTC, ids are mail.id/person.id/mbox_file.id. Errors are {"detail": ApiErrorDetail} with the
HTTP status named at each code (ErrorCode); FastAPI's own validation errors stay 422.

    GET  /api/health                             no Basic Auth; schema revision
    GET  /api/stats                              Stats
    GET  /api/stats/sender-domains?q=&limit=     list[DomainCount], all sender domains
    GET  /api/mbox-files                         list[MboxFileInfo]
    GET  /api/mails?MailListParams               MailPage
    GET  /api/mails/summary?MailFilters          MailSummary
    GET  /api/mails/export.csv?MailOrderParams   text/csv, every match (D25)
    GET  /api/mails/{id}                         MailDetail
    GET  /api/mails/{id}/neighbors?MailOrderParams  MailNeighbors
    GET  /api/mails/{id}/body?format=text        MailText
    GET  /api/mails/{id}/body?format=html        text/html for a sandboxed iframe (D22)
    GET  /api/mails/{id}/body?format=headers     MailHeaders
    GET  /api/mails/{id}/body?format=raw         MailRaw
    GET  /api/mails/{id}/eml                     message/rfc822 download
    POST /api/mails/{id}/dkim/recheck            MailDkim, after checking the mail again
    PUT  /api/mails/{id}/note                    NoteUpdate -> Note (D23)
    GET  /api/graph?GraphParams                  Graph (D37); graph_too_large above the limit
    GET  /api/graph/size?GraphParams             GraphSize, also above the limit
    GET  /api/graph/export.graphml?GraphParams   GraphML download of the same excerpt (D38)

Every other GET path outside /api serves the frontend (index.html for client-side routes).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from mailrobbe.enums import DkimReason, DkimStatus, MboxStatus, ParticipationRole, PersonKind

# Exact counts stop here (SPEC 6.6): MailSummary falls back to "more than COUNT_LIMIT" and
# MailNeighbors.position is None beyond it.
COUNT_LIMIT = 10_000
PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
RECIPIENT_PREVIEW = 3  # recipients listed per row of the mail list
TOP_SENDER_DOMAINS = 10  # in Stats; the full list comes from /api/stats/sender-domains
THREAD_LIMIT = 200  # thread members in MailDetail
DUPLICATES_LIMIT = 50
TEXT_LIMIT = 1_000_000  # characters of MailText.text
RAW_LIMIT = 2 * 1024**2  # bytes of the message shown as MailRaw.raw; the EML has all
NOTE_LIMIT = 10_000  # characters of a note

# mail.dkim_status values as filter and count keys; unchecked stands for NULL (not checked yet).
DkimKey = Literal["pass", "fail", "no_key", "unsigned", "temp_error", "unchecked"]
SortOrder = Literal["date_desc", "date_asc"]
QueryKey = Literal[
    "text", "from", "to", "cc", "subject", "domain", "has", "dkim", "before", "after", "message_id"
]
ErrorCode = Literal[
    "not_found",  # 404: no mail with this id
    "invalid_query",  # 400: q has an operator with an unusable value; message names the term
    "invalid_cursor",  # 400: cursor not issued by this API, or for another sort order
    "invalid_filter",  # 400: a filter parameter cannot be used, e.g. between without two ids
    "no_html",  # 404: format=html for a mail without an HTML part
    "source_missing",  # 409: the mail's MBOX file is not there or cannot be read
    "source_changed",  # 409: the bytes at the stored offset are not the imported mail any more
    "graph_too_large",  # 400: the excerpt has more than MAX_GRAPH_NODES nodes
]


class ApiErrorDetail(BaseModel):
    code: ErrorCode
    message: str  # English, for logs; the UI shows its own German text per code


# Query parameters ------------------------------------------------------------------------------


class MailFilters(BaseModel):
    """Filters of the mail list; every given one must hold (AND). Lists repeat the parameter."""

    q: str = ""  # search syntax (SPEC 4, D20): operators plus full text
    dkim: list[DkimKey] = []  # any of these statuses; empty: all
    sender_domain: list[str] = []  # the sender's domain is one of these (lowercase); empty: all
    date_from: date | None = None  # UTC day, inclusive; mails without a date never match
    date_to: date | None = None  # UTC day, inclusive
    has_attachment: bool = False
    in_thread: bool = False  # thread_id is set
    hide_duplicates: bool = False  # is_duplicate_of is NULL
    external: bool = False  # between internal and external domains (D21)
    flagged: bool = False  # flagged in mail_note (D23)
    mbox_file: int | None = None
    person: list[int] = []  # each of these persons takes part, in any role
    between: list[int] = []  # exactly two persons: one sent it, the other received it (to/cc/bcc)


class MailOrderParams(MailFilters):
    sort: SortOrder = "date_desc"


class MailListParams(MailOrderParams):
    cursor: str | None = None  # next_cursor or prev_cursor of a MailPage with the same sort
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class NoteUpdate(BaseModel):
    flagged: bool
    note: str = Field("", max_length=NOTE_LIMIT)


# Mail list ------------------------------------------------------------------------------------


class PersonRef(BaseModel):
    person_id: int
    email: str
    name: str | None  # the display name used in this mail, else the person's display name


class QueryTerm(BaseModel):
    """One understood part of q, for the filter chips."""

    key: QueryKey  # text: full text words; message_id: a bare <id@host> token
    value: str  # unquoted, e.g. 'finale Fassung' for subject:"finale Fassung"
    raw: str  # the exact substring of q; removing it from q removes this term


class MailListItem(BaseModel):
    id: int
    date: datetime | None
    subject: str | None
    dkim_status: DkimStatus | None  # None: not checked yet
    has_attachments: bool
    sender: PersonRef | None
    recipients: list[PersonRef]  # To, then Cc, then Bcc; at most RECIPIENT_PREVIEW
    recipient_count: int  # all To, Cc and Bcc recipients
    thread_id: int | None
    is_duplicate: bool
    flagged: bool
    size: int  # byte_length of the MBOX record
    mbox_file_id: int


class MailPage(BaseModel):
    items: list[MailListItem]
    next_cursor: str | None  # None on the last page
    prev_cursor: str | None  # None on the first page
    query_terms: list[QueryTerm]


class MailSummary(BaseModel):
    """Figures of the filtered list (D19); from global_stats when no filter is set."""

    total: int | None  # None: unknown, even the bounded count ran out of time
    exact: bool  # False: total is a lower bound, shown as "mehr als ..."
    dkim: dict[DkimKey, int] | None  # every key present; None when counting ran out of time
    persons: int | None  # distinct persons taking part in the matches
    domains: int | None  # distinct domains of those persons
    date_min: datetime | None
    date_max: datetime | None


class MailNeighbors(BaseModel):
    prev_id: int | None  # the mail before this one in the filtered, sorted list
    next_id: int | None
    position: int | None  # 1-based; None beyond COUNT_LIMIT or when the mail does not match


# Stats and files -------------------------------------------------------------------------------


class DomainCount(BaseModel):
    domain: str
    mails: int  # mails sent from this domain


class ImportState(BaseModel):
    running: bool  # some MBOX file has status running
    files_total: int
    files_done: int
    progress: float  # bytes done / bytes of all files, 0 to 1; 1 without files


class Stats(BaseModel):
    """Whole-archive figures from global_stats (D19), import state live from mbox_file."""

    mails: int
    persons: int  # not merged into another person
    domains: int
    date_min: datetime | None
    date_max: datetime | None
    dkim: dict[DkimKey, int]  # every key present
    sender_domains: list[DomainCount]  # top TOP_SENDER_DOMAINS by mails sent
    sender_domain_count: int
    mbox_files: int
    internal_domains: list[str]  # MAILROBBE_INTERNAL_DOMAINS; empty: no external filter
    importer: ImportState
    updated_at: datetime | None  # when global_stats were computed; None: never


class MboxFileInfo(BaseModel):
    id: int
    path: str  # relative to MAILROBBE_MBOX_DIR
    size_bytes: int
    status: MboxStatus
    mails_parsed: int
    bytes_done: int


# Mail detail -----------------------------------------------------------------------------------


class MailSource(BaseModel):
    mbox_file_id: int
    path: str
    byte_offset: int
    byte_length: int


class DkimSignature(BaseModel):
    """One dkim_result row, with the dns_cache row of its key when there is one."""

    index: int  # signature_index: header order, topmost first
    status: DkimStatus
    reason: DkimReason | None
    domain: str | None
    selector: str | None
    algorithm: str | None
    key_bits: int | None
    signed_headers: list[str] | None
    body_hash_ok: bool | None
    signed_at: datetime | None
    aligned: bool | None
    checked_at: datetime
    dns_cached: bool  # the key answer came from the cache
    dns_record: str | None  # dns_cache.record for <selector>._domainkey.<domain>
    dns_fetched_at: datetime | None
    dns_ttl: int | None  # seconds


class MailDkim(BaseModel):
    status: DkimStatus | None  # None: not checked yet
    signatures: list[DkimSignature]


class Participant(PersonRef):
    role: ParticipationRole
    # From person_stats and edge, which milestone 5 fills (D26); None until then.
    mails: int | None  # sent + received
    contacts: int | None
    mails_with_sender: int | None  # edge.mails_total with the sender; None for the sender


class AttachmentInfo(BaseModel):
    id: int
    filename: str | None
    mime_type: str
    size: int
    sha256: str | None  # None above the hash limit (D18)


class ThreadMail(BaseModel):
    id: int
    date: datetime | None
    subject: str | None
    sender: PersonRef | None
    dkim_status: DkimStatus | None


class Note(BaseModel):
    flagged: bool
    note: str  # empty: no note
    updated_at: datetime | None  # None: never set


class MailDetail(BaseModel):
    id: int
    subject: str | None
    date: datetime | None
    message_id: str | None
    in_reply_to: str | None
    in_reply_to_id: int | None  # the archived mail with that Message-ID, if any
    reference_ids: list[str]
    source: MailSource
    raw_sha256: str
    has_attachments: bool
    dkim: MailDkim
    participants: list[Participant]  # from, to, cc, bcc, in that order
    attachments: list[AttachmentInfo]
    thread_id: int | None
    thread: list[ThreadMail]  # by date, this mail included; at most THREAD_LIMIT
    thread_size: int  # all mails of the thread
    duplicate_of: int | None
    duplicates: list[int]  # mails that are duplicates of this one; at most DUPLICATES_LIMIT
    note: Note


# Bodies, read on demand from the MBOX file -------------------------------------------------


class MailText(BaseModel):
    text: str  # the text part the importer indexes (D3 order), in full up to TEXT_LIMIT
    truncated: bool
    source: Literal["text/plain", "text/html", "none"]  # text/html: converted to text
    has_html: bool  # an HTML part exists, so format=html has something to show


class HeaderField(BaseModel):
    name: str  # as written in the mail
    value: str  # unfolded, encoded words decoded


class MailHeaders(BaseModel):
    headers: list[HeaderField]  # all header fields in mail order


class MailRaw(BaseModel):
    raw: str  # the message as UTF-8 (invalid bytes replaced), at most RAW_LIMIT bytes of it
    truncated: bool
    size: int  # bytes of the whole message


# Relationship map (milestone 6, D36 to D38) ------------------------------------------------

MAX_GRAPH_NODES = 2_000  # hard limit per view (SPEC 5.4, D8); /api/graph refuses larger excerpts
GRAPH_TOP = 50  # default number of persons in the top mode

GraphMode = Literal["ego", "top", "domains"]


class GraphParams(BaseModel):
    """One excerpt of the relationship map (D37). Lists repeat the parameter.

    The counted graph: edges from edge, or summed from edge_year when a year is given; their
    weight is a_to_b + b_to_a, plus cc when cc is set, over all mails or only those whose DKIM
    check passed; without the persons in hide and, with hide_lists, those with a person.kind.
    Ego follows edges of at least min_edge from the centers, top takes the persons with the most
    mails, domains the persons of two domains with an edge between them. The excerpt shows every
    counted edge of at least min_edge between its nodes.
    """

    mode: GraphMode = "ego"
    center: list[int] = []  # ego: at least one person; a merged address counts as its root
    depth: int = Field(1, ge=1, le=3)  # ego: steps from the centers
    limit: int = Field(GRAPH_TOP, ge=1, le=MAX_GRAPH_NODES)  # top: number of persons
    domain: list[str] = []  # domains: exactly two, each with its subdomains (lowercase)
    min_edge: int = Field(1, ge=1)  # lighter edges are neither shown nor followed
    year_from: int | None = Field(None, ge=1900, le=2200)  # UTC year, inclusive
    year_to: int | None = Field(None, ge=1900, le=2200)  # UTC year, inclusive
    dkim_only: bool = False  # count only mails whose DKIM check passed
    cc: bool = False  # Cc counts towards the weight
    hide_lists: bool = False  # leave out lists and automated senders, apart from centers
    expand: list[int] = []  # add these persons and their neighbours (edges of min_edge or more)
    hide: list[int] = []  # leave out these persons; ignored for centers


class GraphNode(BaseModel):
    id: int  # the root person
    name: str | None  # person.display_name
    email: str  # person.canonical_email
    domain: str
    kind: PersonKind | None  # None: a human, or not recognised as list or automated sender
    mails: int  # weight of all the person's counted edges, shown or not (D37)
    contacts: int  # persons with a counted edge to this one
    center: bool  # a center of the ego mode


class GraphEdge(BaseModel):
    source: int  # person_a, the smaller id
    target: int  # person_b
    a_to_b: int  # mails from source to target (To or Bcc), counted as the parameters say
    b_to_a: int
    cc: int  # mails with one of them in Cc of the other's mail, either direction
    weight: int  # a_to_b + b_to_a, plus cc when the parameters count Cc


class EdgeTable(BaseModel):
    pairs: int  # rows of edge
    refreshed_at: datetime | None  # end of the last refresh_edges; None: never


class Graph(BaseModel):
    nodes: list[GraphNode]  # most mails first
    edges: list[GraphEdge]  # heaviest first
    mails: int  # sum of the shown edges' weights ("Mails im Ausschnitt")
    centers: list[int]  # ego: the centers as root persons, in the given order; else empty
    edge_table: EdgeTable


class GraphSize(BaseModel):
    """The size /api/graph would have, for the preview next to the threshold slider."""

    nodes: int
    edges: int
    mails: int
    too_large: bool  # nodes > MAX_GRAPH_NODES, so /api/graph answers graph_too_large

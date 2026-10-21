"""The HTTP contract of the web UI (SPEC 4, milestones 4 to 13): query parameters and responses.

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
    GET  /api/persons?PersonListParams           PersonPage (D31)
    GET  /api/persons/suggestions?SuggestionListParams  SuggestionPage, every open one (D30)
    POST /api/persons/suggestions/dismiss        SuggestionDismiss -> 204 (D28)
    POST /api/persons/merge                      MergeRequest -> PersonProfile of the target (D28)
    GET  /api/persons/{id}                       PersonProfile; of the root when id is an alias
    GET  /api/persons/{id}/contacts?ContactListParams   ContactPage
    GET  /api/persons/{id}/mail-counts?PersonMailCountParams  PersonMailCounts (D32)
    POST /api/persons/{id}/unmerge               PersonProfile of the root it was merged into
    GET  /api/graph?GraphParams                  Graph (D37); graph_too_large above the limit
    GET  /api/graph/size?GraphParams             GraphSize, also above the limit
    GET  /api/graph/export.graphml?GraphParams   GraphML download of the same excerpt (D38)
    GET  /api/import/status                      ImportStatus: files, totals, latest runs (D48)
    GET  /api/import/summary                     ImportSummary: archive figures (D48)
    GET  /api/import/errors?ImportErrorParams    ImportErrorPage, newest first
    POST /api/import/start                       ImportStartRequest -> 202 ImportJob (D46, D49)
    POST /api/import/pause                       ImportJob, its stop requested (D46)
    POST /api/import/rescan                      ScanResult (D50)
    POST /api/dkim/recheck                       DkimRecheckRequest -> 202 DkimJob (D46)
    POST /api/dkim/recheck/stop                  DkimJob, its stop requested
    GET  /api/documents?DocumentListParams       DocumentPage (D74)
    GET  /api/documents/summary?DocumentFilters  DocumentSummary
    GET  /api/documents/{id}                     DocumentDetail (D75)
    GET  /api/documents/{id}/text                DocumentText
    GET  /api/attachments/{id}/content           the attachment's bytes as a download (D76)
    GET  /api/attachments/{id}/html              text/html of a DOCX or ODT for a sandboxed
                                                 iframe, converted and cached (D122)
    GET  /api/attachments/{id}/media             audio or video, with Range requests (D123)
    GET  /api/mails/{id}/hits?q=                 MailHits: where q's words occur in the mail (D79)
    GET  /api/timeline?TimelineParams            Timeline: the matching mails over time (D90)
    GET  /api/timeline/first-mentions?FirstMentionParams  FirstMentions, earliest first (D94)

Keys of deleted selectors (D100 to D104); a key name is '<selector>._domainkey.<domain>':

    GET  /api/dkim/selectors/summary             SelectorSummary: figures of the dashboard card
    GET  /api/dkim/selectors?SelectorListParams  SelectorPage: key names whose signatures do
                                                 not pass, most mails first
    GET  /api/dkim/selectors/{name}              SelectorDetail: keys with evidence, lookups,
                                                 mails
    POST /api/dkim/selectors/{name}/keys         ManualKeyRequest -> 201 SelectorDetail (D103)
    GET  /api/dkim/lookups/{id}/raw              a source's answer unchanged, as a download
    GET  /api/dkim/archive/preview               KeyArchivePreview: what a fetch would send
    POST /api/dkim/keys/run                      DkimKeysRunRequest -> 202 DkimKeysJob (D101)
    POST /api/dkim/keys/run/stop                 DkimKeysJob, its stop requested

Research file (milestone 8, D53 to D63); writes take the editor from X-Mailrobbe-Editor (D54):

    GET    /api/research                         ResearchOverview: tags, Akten, searches, counts
    GET    /api/research/themes                  list[ThemeInfo], the themes of themes.toml (D64)
    POST   /api/research/starter                 ResearchOverview, after creating the themes'
                                                 missing tags and searches (D64)
    POST   /api/tags                             TagCreate -> 201 TagInfo
    PATCH  /api/tags/{id}                        TagUpdate -> TagInfo
    DELETE /api/tags/{id}                        204; off every mail
    POST   /api/collections                      CollectionCreate -> 201 CollectionInfo
    GET    /api/collections/{id}                 CollectionDetail
    PATCH  /api/collections/{id}                 CollectionUpdate -> CollectionInfo
    DELETE /api/collections/{id}                 204; its mails stay, its searches lose it
    POST   /api/searches                         SavedSearchCreate -> 201 SavedSearch
    PATCH  /api/searches/{id}                    SavedSearchUpdate -> SavedSearch
    DELETE /api/searches/{id}                    204
    PUT    /api/mails/{id}/mark                  MarkUpdate -> Mark
    POST   /api/mails/{id}/tags                  LinkChange -> list[TagRef], the mail's tags now
    POST   /api/mails/{id}/collections           LinkChange -> list[CollectionRef]
    POST   /api/mails/{id}/notes                 NoteCreate -> 201 NoteInfo
    PATCH  /api/notes/{id}                       NoteEdit -> NoteInfo
    DELETE /api/notes/{id}                       204
    GET    /api/notes?NoteListParams             NotePage, newest first
    POST   /api/mails/bulk                       BulkRequest -> BulkResult (D60)
    GET    /api/permalink/{hash}                 PermalinkTarget (D61)
    GET    /api/mails/{id}/pdf?research=         application/pdf rendition of one mail (D63)
    POST   /api/exports                          ExportRequest -> 201 ExportInfo (D62)
    GET    /api/exports                          list[ExportInfo], newest first
    GET    /api/exports/{id}/download            application/zip, the export (D62)

Entities (milestone 10, D80 to D89):

    GET  /api/entities?EntityListParams          EntityPage (D88)
    GET  /api/entities/summary                   EntitySummary: entities per kind, texts waiting
    GET  /api/entities/refs?id=                  list[EntityRef] of these ids, for filter chips
    GET  /api/entities/{id}                      EntityDetail (D88)
    GET  /api/mails/facets?EntityFacetParams     EntityFacets: top entities of a filter (D87)
    GET  /api/mails/{id}/entities                list[MailEntity], what was found in one mail

Topics (milestone 13, D140 to D148):

    GET  /api/topics/periods?TopicPeriodParams   TopicPeriods: terms per month, quarter, year
    GET  /api/topics/terms?TopicTermParams       TopicTerms: terms of a selection (D144)
    GET  /api/topics/clusters                    TopicClusters (D145)

The mails of a person (SPEC 5.3) are GET /api/mails with person=<id> and person_role (D32), so
paging, neighbours and the CSV export work as for the mail list; the mails carrying a document
(D75) are GET /api/mails with document=<id>.

Every other GET path outside /api serves the frontend (index.html for client-side routes).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from mailrobbe.dkim.keys.model import (
    DkimKeysOptions,
    DkimKeysPhase,
    DkimKeysProgress,
    DkimKeysTask,
)
from mailrobbe.enums import (
    DkimReason,
    DkimStatus,
    DnsStatus,
    DocumentKind,
    DocumentTextStatus,
    EntityKind,
    ImportErrorKind,
    JobKind,
    JobOrigin,
    JobStatus,
    KeyLookupSource,
    KeyOrigin,
    LookupOutcome,
    MboxStatus,
    ParticipationRole,
    PersonKind,
    ReviewStatus,
)
from mailrobbe.jobs import DbActivity, DkimOptions, DkimProgress, ImportOptions, ImportProgress
from mailrobbe.preview.kinds import PreviewKind

# Tag colours (D57): the UI maps each to a fixed pair of background and text colours.
TagColor = Literal["blue", "teal", "green", "amber", "red", "pink", "violet", "gray"]

# Exact counts stop here (SPEC 6.6): MailSummary falls back to "more than COUNT_LIMIT" and
# MailNeighbors.position is None beyond it.
COUNT_LIMIT = 10_000
PAGE_SIZE = 50  # also the page size of persons, contacts and suggestions
MAX_PAGE_SIZE = 200
RECIPIENT_PREVIEW = 3  # recipients listed per row of the mail list
TOP_SENDER_DOMAINS = 10  # in Stats; the full list comes from /api/stats/sender-domains
THREAD_LIMIT = 200  # thread members in MailDetail
DUPLICATES_LIMIT = 50
TEXT_LIMIT = 1_000_000  # characters of MailText.text
RAW_LIMIT = 2 * 1024**2  # bytes of the message shown as MailRaw.raw; the EML has all
NOTE_LIMIT = 10_000  # characters of a note

# What an amount, IBAN or account number is written next to (D82; enums.EntityContext).
EntityContextKey = Literal["cash", "donation", "receipt"]

# Review statuses as filter and count keys (D55); unreviewed stands for no status.
ReviewKey = Literal["unreviewed", "seen", "relevant", "irrelevant"]
# mail.dkim_status values as filter and count keys; unchecked stands for NULL (not checked yet).
DkimKey = Literal["pass", "consistent", "fail", "no_key", "unsigned", "temp_error", "unchecked"]
SortOrder = Literal["date_desc", "date_asc"]
QueryKey = Literal[
    "text", "from", "to", "cc", "subject", "domain", "has", "dkim", "before", "after", "message_id"
]
# Tabs of a person's mail list (D29, D32): sent = From; received = To, Cc or Bcc but not From;
# cc = Cc only (neither From, To nor Bcc).
PersonRole = Literal["sent", "received", "cc"]
PersonSort = Literal["mails", "name", "recent"]  # most mails first, A to Z, latest mail first
ErrorCode = Literal[
    "not_found",  # 404: no mail or person with this id
    "invalid_query",  # 400: q has an operator with an unusable value; message names the term
    "invalid_cursor",  # 400: cursor not issued by this API, or for another sort order
    "invalid_filter",  # 400: a filter parameter cannot be used, e.g. between without two ids
    "no_html",  # 404: format=html for a mail without an HTML part
    "source_missing",  # 409: the mail's MBOX file is not there or cannot be read
    "source_changed",  # 409: the bytes at the stored offset are not the imported mail any more
    "invalid_merge",  # 400: merging a person into itself, or unmerging one that is no alias
    "graph_too_large",  # 400: the excerpt has more than MAX_GRAPH_NODES nodes
    "job_running",  # 409: an import or DKIM run is alive, so this one cannot start (D46)
    "no_job",  # 409: no run of that kind is alive to stop
    "mbox_dir_missing",  # 409: MAILROBBE_MBOX_DIR is no directory the server can read
    "invalid_option",  # 400: an option of a start request cannot be used; message names it
    "job_failed",  # 500: the started process ended before it recorded its run
    "duplicate_name",  # 409: a tag, Akte or saved search of this name (any case) exists
    "invalid_selection",  # 400: not exactly one of ids and filters, or an action lacks its value
    "empty_selection",  # 400: the selection matches no mail
    "too_many_mails",  # 400: above BULK_LIMIT or EXPORT_LIMIT; message names the count
    "ambiguous_permalink",  # 409: the hash prefix fits mails with different contents
    "no_preview",  # 415: the content is no format this preview shows (D120); message says what
    "preview_too_large",  # 413: above MAILROBBE_PREVIEW_MAX_SIZE, or unhashed (D124)
    "preview_failed",  # 422: the conversion failed, ran out of time or memory; message says why
    "invalid_key",  # 400: no DKIM key name, or a record without a usable key (D103)
    "archive_off",  # 409: the key archive is switched off (MAILROBBE_DKIM_KEY_ARCHIVE_URL=off)
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
    flagged: bool = False  # bookmarked (mail_mark.flagged, D55)
    mbox_file: int | None = None
    person: list[int] = []  # each of these persons takes part, in any role
    between: list[int] = []  # exactly two persons: one sent it, the other received it (to/cc/bcc)
    # The role of the person in `person`, which must then name exactly one (D32); None: any role.
    person_role: PersonRole | None = None
    # Research file (D55 to D58): the mail's content has any of these review statuses, carries
    # any of these tags, is in any of these Akten, has at least one note.
    review: list[ReviewKey] = []
    tag: list[int] = []
    collection: list[int] = []
    has_note: bool = False
    document: int | None = None  # one of the mail's attachments is this document (D75)
    thread: int | None = None  # the mail's thread_id is this one (D17, D95)
    # Entities (D86): each of these entities is mentioned in the mail's subject or text or in
    # one of its attachments; an amount of at least amount_min (any currency) is mentioned,
    # and, with amount_context, one such amount next to any of these contexts.
    entity: list[int] = []
    amount_min: float | None = Field(default=None, ge=0)
    amount_context: list[EntityContextKey] = []


class MailOrderParams(MailFilters):
    sort: SortOrder = "date_desc"


class MailListParams(MailOrderParams):
    cursor: str | None = None  # next_cursor or prev_cursor of a MailPage with the same sort
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


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
    flagged: bool  # bookmarked (D55)
    size: int  # byte_length of the MBOX record
    mbox_file_id: int
    # With exactly one person filtered for: that person's first role in the mail (from, to, cc,
    # bcc, counting its aliases); None otherwise.
    person_role: ParticipationRole | None = None
    review: ReviewStatus | None = None  # None: unreviewed (D55)
    tags: list[int] = []  # ids of the mail's tags, by tag name
    notes: int = 0  # notes on the mail
    # q has full text words and the text of one of the mail's attachments matches them (D73)
    attachment_match: bool = False


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
    running: bool  # an import run is alive (D47)
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
    bytes_done: int  # the import's progress: end of the last committed record
    error_count: int  # import errors recorded for this file
    worker_id: int | None  # the worker importing it while status is running (W1, W2, ...)
    started_at: datetime | None  # when the last import of it started
    finished_at: datetime | None  # when it was imported to the end; None while not done


# Mail detail -----------------------------------------------------------------------------------


class MailSource(BaseModel):
    mbox_file_id: int
    path: str
    byte_offset: int
    byte_length: int


class UsedSignature(BaseModel):
    mail_id: int | None  # None when no mail of the archive has this content any more
    mail_sha256: str
    signature_index: int


class KeyEvidenceInfo(BaseModel):
    """One piece of evidence for a key (D100): what one lookup of a source says about it."""

    id: int
    origin: KeyOrigin
    source: KeyLookupSource
    lookup_id: int
    asked_at: datetime  # when Mailrobbe asked the source, or the key was entered
    observed_from: datetime | None  # the source's own times: first seen, a document's date
    observed_to: datetime | None  # last seen
    reference: str | None  # URL, permalink /m/<hash>, /anhaenge/<id>, file name
    note: str | None
    editor: str | None  # D54
    raw_sha256: str | None  # of the lookup's answer; /api/dkim/lookups/{lookup_id}/raw
    raw_size: int | None  # bytes
    # reconstruction: the signatures the key was computed from (dkim_key_evidence.details)
    signatures: list[UsedSignature] = []


class DkimKeyInfo(BaseModel):
    """A key from a source other than today's DNS (dkim_key) with all its evidence."""

    id: int
    name: str  # '<selector>._domainkey.<domain>'
    key_type: str  # rsa or ed25519
    bits: int
    key_sha256: str  # identity across sources: SHA-256 of the public key
    record: str
    origin: KeyOrigin  # the strongest of its evidence
    factorable: bool  # shares a prime factor with another key: never used to verify
    signatures: int  # signatures (dkim_result rows) this key verified
    evidence: list[KeyEvidenceInfo]  # strongest origin first, then oldest


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
    # Origin of the key the result rests on (D100); None when it rests on none (no_key,
    # temp_error, a failure found before the key was asked for).
    key_origin: KeyOrigin | None = None
    key: DkimKeyInfo | None = None  # the dkim_key that verified it; None for today's DNS


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
    # Its document (D70); None until the next finalize assigns it.
    document_id: int | None = None
    kind: DocumentKind | None = None
    text_status: DocumentTextStatus | None = None
    pages: int | None = None
    document_mails: int | None = None  # mails carrying the document, duplicates not counted
    preview: PreviewKind | None = None  # how the browser shows it (D120); None: download only


class ThreadMail(BaseModel):
    id: int
    date: datetime | None
    subject: str | None
    sender: PersonRef | None
    dkim_status: DkimStatus | None


class Mark(BaseModel):
    """Bookmark and review status of a mail (D55); *_by None: no editor name was given."""

    flagged: bool
    flagged_by: str | None
    flagged_at: datetime | None  # last change of the bookmark; None: never set
    review: ReviewStatus | None  # None: unreviewed
    review_by: str | None
    review_at: datetime | None


class TagRef(BaseModel):
    id: int
    name: str
    color: TagColor


class CollectionRef(BaseModel):
    id: int
    name: str


class NoteInfo(BaseModel):
    id: int
    body: str
    author: str | None  # the editor who wrote it; None: unknown (D54)
    created_at: datetime
    updated_at: datetime  # equals created_at until edited


class MailResearch(BaseModel):
    """The research file's data on one mail (D53 to D58), shared by its byte-identical copies."""

    mark: Mark
    tags: list[TagRef]  # by name
    collections: list[CollectionRef]  # by name
    notes: list[NoteInfo]  # oldest first


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
    research: MailResearch


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


# Persons (milestone 5, D28 to D33) ----------------------------------------------------------
#
# A person is a root person (D28): its own address plus the addresses merged into it (aliases).
# Every id a response names is a root, apart from AliasAddress.person_id and the PersonRef ids
# of mails, which name the address used.

TOP_CONTACTS = 10  # in PersonProfile; all of them come from /api/persons/{id}/contacts
DISPLAY_NAME_LIMIT = 10  # display names listed in PersonProfile
SUGGESTION_LIMIT = 10  # open alias suggestions listed in PersonProfile
MERGE_LIMIT = 50  # sources of one merge request


class PersonListParams(BaseModel):
    # Part of an address or display name of the person or of one of its aliases, any case.
    q: str = ""
    sort: PersonSort = "mails"
    cursor: str | None = None  # next_cursor or prev_cursor of a PersonPage with the same q, sort
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class ContactListParams(BaseModel):
    cursor: str | None = None  # next_cursor of a ContactPage of the same person
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class SuggestionListParams(BaseModel):
    cursor: str | None = None  # next_cursor of a SuggestionPage
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class PersonMailCountParams(BaseModel):
    year: int | None = Field(default=None, ge=1, le=9999)  # mails dated in this UTC year
    contact: int | None = None  # mails between both persons, as the between filter counts them


class MergeRequest(BaseModel):
    target: int  # the person that stays; its root when it is an alias
    sources: list[int] = Field(min_length=1, max_length=MERGE_LIMIT)  # with all their aliases


class SuggestionDismiss(BaseModel):
    persons: list[int] = Field(min_length=2, max_length=2)  # the two persons of the suggestion


class PersonFigures(BaseModel):
    """person_stats of a root person (D29), over the mails that are not duplicates."""

    mails: int  # sent + received
    sent: int
    received: int  # To, Cc or Bcc, not From
    cc_only: int  # part of received: only in Cc
    contacts: int  # edges of the person (persons it wrote to or got mail from)
    first_date: datetime | None
    last_date: datetime | None
    dkim_pass_ratio: float | None  # 0 to 1, pass among the checked sent mails; None: none


class PersonSummary(BaseModel):
    """A root person in a list: the person list, suggestions, the graph's person search."""

    id: int
    name: str | None  # person.display_name, the name used most for its own address
    email: str  # canonical_email
    domain: str
    aliases: int  # addresses merged into this person
    figures: PersonFigures


class PersonPage(BaseModel):
    items: list[PersonSummary]
    next_cursor: str | None  # None on the last page
    prev_cursor: str | None  # None on the first page
    total: int  # persons matching q


class Contact(BaseModel):
    """An edge of the person: the other root person and the mails between both (D29)."""

    person: PersonRef  # the contact; name is its display name
    domain: str
    mails: int  # edge.mails_total
    sent: int  # from this person to the contact (To or Bcc)
    received: int  # from the contact to this person (To or Bcc)
    cc: int  # one of both sent it, the other was in Cc
    first_date: datetime | None
    last_date: datetime | None


class ContactPage(BaseModel):
    items: list[Contact]  # most mails first, then person id
    next_cursor: str | None
    total: int  # all contacts of the person


class AliasAddress(BaseModel):
    person_id: int  # the alias's own person id, for unmerging it
    email: str
    name: str | None
    mails: int  # mails this address takes part in that are not duplicates


class DisplayNameCount(BaseModel):
    name: str
    mails: int  # mails using this name with one of the person's addresses


class YearActivity(BaseModel):
    year: int  # UTC
    sent: int
    received: int


class AliasCandidate(BaseModel):
    """An open alias suggestion (D30) seen from one of its two persons."""

    person: PersonSummary  # the other person
    same_name: str | None  # the normalized display name both use
    same_local_part: str | None  # the local part both addresses have


class AliasSuggestion(BaseModel):
    first: PersonSummary  # the one with more mails; merging keeps it by default
    second: PersonSummary
    same_name: str | None
    same_local_part: str | None


class SuggestionPage(BaseModel):
    items: list[AliasSuggestion]  # both reasons first, then by the mails of `first`, then ids
    next_cursor: str | None
    total: int  # every open suggestion


class PersonProfile(BaseModel):
    id: int  # the root; differs from the requested id when that was an alias
    name: str | None
    email: str
    domain: str
    aliases: list[AliasAddress]  # most mails first
    display_names: list[DisplayNameCount]  # over all addresses, most used first, at most LIMIT
    figures: PersonFigures | None  # None until the person's mails were aggregated (D33)
    years: list[YearActivity]  # oldest first; only years with mails
    top_contacts: list[Contact]  # most mails first, at most TOP_CONTACTS
    suggestions: list[AliasCandidate]  # most mails first, at most SUGGESTION_LIMIT


class PersonMailCounts(BaseModel):
    """Mails of each tab for one person (D32) under the count budget of D19; None: ran out."""

    all: int | None
    sent: int | None
    received: int | None
    cc: int | None


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
    year_from: int | None = Field(default=None, ge=1900, le=2200)  # UTC year, inclusive
    year_to: int | None = Field(default=None, ge=1900, le=2200)  # UTC year, inclusive
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


# Import dashboard (milestone 7, D46 to D50) ------------------------------------------------

ERROR_PAGE_SIZE = 50  # default page of /api/import/errors
ImportPhase = Literal[
    "scan", "headers", "import", "finalize", "attachments", "entities", "topics"
]  # jobs.ImportPhase
DkimPhase = Literal["check", "aggregates"]  # jobs.DkimPhase


class JobInfo(BaseModel):
    """One run of `mailrobbe import` or `mailrobbe dkim` from the job table (D47)."""

    id: int
    kind: JobKind
    origin: JobOrigin  # cli: started on a command line; ui: from the dashboard
    status: JobStatus
    # The run's process holds its lock. False with status running: the process ended without
    # recording it (killed, container stopped); the UI shows such a run as aborted.
    alive: bool
    stop_requested: bool  # a stop was asked for; the run ends at its next report
    started_at: datetime
    updated_at: datetime  # its last report
    report_age_seconds: float  # since its last report, by the database's clock (D111)
    finished_at: datetime | None
    message: str | None  # English one-line summary or failure reason, for the log view
    # The longest statement a run left running in the database although its process ended
    # (alive false with status running): it runs until it would send its result, holding its
    # locks; the next run of the kind ends it. None otherwise (D113).
    leftover: DbActivity | None


class ImportJob(JobInfo):
    phase: ImportPhase | None
    options: ImportOptions
    progress: ImportProgress


class DkimJob(JobInfo):
    phase: DkimPhase | None
    options: DkimOptions
    progress: DkimProgress


class DkimKeysJob(JobInfo):
    """A run of `mailrobbe dkim-keys` (D101)."""

    phase: DkimKeysPhase | None
    options: DkimKeysOptions
    progress: DkimKeysProgress


class ImportTotals(BaseModel):
    """Sums over every mbox_file row, live."""

    files: int
    done: int
    running: int
    pending: int
    paused: int
    error: int
    size_bytes: int
    bytes_done: int
    mails_parsed: int
    # mails_parsed extrapolated to every file's size by the bytes done so far ("ca. 412.000");
    # None before the first byte is done
    mails_estimated: int | None
    error_count: int  # import errors of all files


class ImportStatus(BaseModel):
    """What the dashboard polls: every 2 s while a run is alive, else less often (D48)."""

    mbox_dir: str  # the server's MAILROBBE_MBOX_DIR ("Quelle")
    mbox_dir_ok: bool  # the server can read it; start and rescan need it
    totals: ImportTotals
    files: list[MboxFileInfo]  # every row, sorted by path
    import_job: ImportJob | None  # the latest import run; None before the first
    dkim_job: DkimJob | None  # the latest DKIM run
    # What a start from the dashboard uses unless the request says otherwise: the options of
    # the latest import run, or the server's settings before the first (D49).
    defaults: ImportOptions
    keys_job: DkimKeysJob | None = None  # the latest dkim-keys run (D101)


class FailReasonCount(BaseModel):
    reason: DkimReason
    mails: int  # mails with status fail and a failing signature with this reason


class ImportSummary(BaseModel):
    """Archive figures beside the import (D48): sizes live, the rest from global_stats."""

    db_size_bytes: int  # pg_database_size: metadata, full text and every index
    raw_size_bytes: int  # sum of the MBOX files' sizes, for "x % der Rohdaten"
    fulltext_index_bytes: int  # the GIN index of mail.tsv
    dns_cache: dict[DnsStatus, int]  # dns_cache rows by status, every status present, live
    # Share of DKIM signatures whose key came from the cache instead of a lookup; None
    # without signatures
    dns_hit_ratio: float | None
    persons: int  # root persons
    open_suggestions: int  # alias suggestions not dismissed (D30)
    edge_table: EdgeTable
    duplicates: int
    dkim: dict[DkimKey, int]  # every key present
    fail_reasons: list[FailReasonCount]  # most mails first
    updated_at: datetime | None  # when global_stats were computed; None: never
    attachments: int = 0  # attachment rows, live (D70)
    documents: dict[DocumentTextStatus, int] = {}  # documents by text status, every one, live


class ImportErrorParams(BaseModel):
    kind: ImportErrorKind | None = None
    mbox_file: int | None = None
    cursor: str | None = None  # next_cursor of the previous page with the same filters
    limit: int = Field(ERROR_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class ImportErrorItem(BaseModel):
    id: int
    mbox_file_id: int | None
    path: str | None  # of the file; None when the error belongs to no file
    byte_offset: int | None  # where in the file
    kind: ImportErrorKind
    message: str  # English, technical; the UI shows a German text per kind
    created_at: datetime


class ImportErrorPage(BaseModel):
    items: list[ImportErrorItem]  # newest first
    next_cursor: str | None
    total: int  # errors matching the filters
    kinds: dict[ImportErrorKind, int]  # every error by kind, without the filters; only kinds seen


class ImportStartRequest(BaseModel):
    """Options of an import started from the dashboard (D49); None: as in ImportStatus.defaults."""

    workers: int | None = Field(default=None, ge=1, le=64)
    attachment_hash_limit: int | None = Field(default=None, ge=0)  # bytes
    dkim_nameservers: str | None = None  # comma-separated IP addresses; "": system resolver


class DkimRecheckRequest(BaseModel):
    """A DKIM run from the dashboard: by default the mails of D13 (unchecked, no_key,
    temp_error)."""

    statuses: list[DkimKey] = Field(["unchecked", "no_key", "temp_error"], min_length=1)
    workers: int | None = Field(default=None, ge=1, le=64)


class FileProblem(BaseModel):
    path: str
    reason: str  # English, as the importer logs it


class ScanResult(BaseModel):
    """What the scan of MAILROBBE_MBOX_DIR found (D14, D50)."""

    files: int  # MBOX files found
    pending: int  # of those, the ones an import would read (new, grown, changed, unfinished)
    new: list[str]
    replaced: list[FileProblem]  # changed files whose mails were removed, imported again
    missing: list[str]  # known files no longer there; their mails stay
    unreadable: list[FileProblem]  # skipped


# Research file (milestone 8, D53 to D63) -----------------------------------------------------
#
# Research data is keyed by the raw SHA-256 of a mail (D53): it holds for every byte-identical
# copy and outlives re-imports. Writes record the editor of X-Mailrobbe-Editor (D54); *_by and
# author are None without one. Counts of mails are of mail rows, as the list's filters count.

NAME_LIMIT = 120  # characters of an Akte's or saved search's name
TAG_NAME_LIMIT = 60
DESCRIPTION_LIMIT = 4_000
QUERY_LIMIT = 4_000  # characters of a saved search's query string
LABEL_LIMIT = 200  # characters of an export's label
SELECTION_IDS_LIMIT = 1_000  # ids in one MailSelection
BULK_LIMIT = 50_000  # mails one bulk change may touch (D60)
EXPORT_LIMIT = 2_000  # mails in one export (D62)
EXPORTS_LISTED = 100  # newest exports in /api/exports
COLLECTION_PERSONS = 10  # persons listed in CollectionDetail
PERMALINK_DIGITS = 16  # hex digits of the raw SHA-256 in a permalink (D61)
PERMALINK_MIN_DIGITS = 12

BulkAction = Literal[
    "tag_add", "tag_remove", "collection_add", "collection_remove", "review", "flag"
]


class TagInfo(TagRef):
    description: str
    mails: int  # mails carrying it
    created_by: str | None
    created_at: datetime


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=TAG_NAME_LIMIT)  # trimmed; unique ignoring case
    color: TagColor = "blue"
    description: str = Field(default="", max_length=DESCRIPTION_LIMIT)


class TagUpdate(BaseModel):
    """Fields left out stay as they are."""

    name: str | None = Field(default=None, min_length=1, max_length=TAG_NAME_LIMIT)
    color: TagColor | None = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_LIMIT)


class CollectionInfo(CollectionRef):
    description: str
    mails: int  # mails in it, as the collection filter counts them
    created_by: str | None
    created_at: datetime
    updated_at: datetime  # last change of name, description or mails


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_LIMIT)  # trimmed; unique ignoring case
    description: str = Field(default="", max_length=DESCRIPTION_LIMIT)


class CollectionUpdate(BaseModel):
    """Fields left out stay as they are."""

    name: str | None = Field(default=None, min_length=1, max_length=NAME_LIMIT)
    description: str | None = Field(default=None, max_length=DESCRIPTION_LIMIT)


class SavedSearch(BaseModel):
    """A search of the mail list kept under a name (D59)."""

    id: int
    name: str
    query: str  # query string of /mails as the UI writes it (MailListParams without cursor)
    collection_id: int | None  # the Akte it belongs to
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_LIMIT)
    query: str = Field(default="", max_length=QUERY_LIMIT)
    collection_id: int | None = None


class SavedSearchUpdate(BaseModel):
    """Fields left out stay as they are; collection_id null detaches it from its Akte."""

    name: str | None = Field(default=None, min_length=1, max_length=NAME_LIMIT)
    query: str | None = Field(default=None, max_length=QUERY_LIMIT)
    collection_id: int | None = None


class ResearchOverview(BaseModel):
    """Everything the filter column and the Akten screen list, in one request."""

    tags: list[TagInfo]  # by name, ignoring case
    collections: list[CollectionInfo]  # last changed first
    searches: list[SavedSearch]  # by name, ignoring case
    review: dict[ReviewKey, int]  # mails per review status, every key present
    flagged: int  # bookmarked mails
    notes: int  # notes in total
    # Tags and saved searches of the themes (D64) without one of the same name, ignoring case;
    # POST /api/research/starter creates them.
    starter_missing: int


class ThemeSearchInfo(BaseModel):
    name: str
    query: str  # query string of /mails, as SavedSearch.query


class ThemeInfo(BaseModel):
    """A research theme of themes.toml (D64): its word field and search templates."""

    key: str
    name: str  # also the name of its tag
    color: TagColor
    description: str
    terms: list[str]  # the word field; each one a full-text search on its own
    searches: list[ThemeSearchInfo]


class CollectionPerson(BaseModel):
    person: PersonRef  # a root person; name is its display name
    mails: int  # mails of the Akte it takes part in, any role


class CollectionDetail(CollectionInfo):
    date_min: datetime | None  # of its mails
    date_max: datetime | None
    missing: int  # contents in it that are in no mail of the archive (any more)
    persons: list[CollectionPerson]  # most mails first, at most COLLECTION_PERSONS
    searches: list[SavedSearch]  # by name


class MarkUpdate(BaseModel):
    """Fields left out stay as they are; "review": null makes the mail unreviewed again."""

    flagged: bool | None = None
    review: ReviewStatus | None = None


class LinkChange(BaseModel):
    """Tags or Akten to add to and remove from one mail; unknown ids are not_found."""

    add: list[int] = []
    remove: list[int] = []


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=NOTE_LIMIT)


class NoteEdit(BaseModel):
    body: str = Field(min_length=1, max_length=NOTE_LIMIT)


class NoteListParams(BaseModel):
    q: str = ""  # part of the note text, any case
    cursor: str | None = None  # next_cursor of the previous page with the same q
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class NoteMail(BaseModel):
    id: int | None  # the original mail with this content; None: not in the archive (any more)
    subject: str | None
    date: datetime | None
    sender: PersonRef | None


class NoteItem(NoteInfo):
    mail_sha256: str
    mail: NoteMail


class NotePage(BaseModel):
    items: list[NoteItem]  # newest first (created_at, then id)
    next_cursor: str | None
    total: int  # notes matching q


class MailSelection(BaseModel):
    """The mails a bulk change or an export applies to: exactly one of ids and filters."""

    ids: list[int] | None = Field(default=None, max_length=SELECTION_IDS_LIMIT)  # these mails
    filters: MailFilters | None = None  # every mail matching these filters


class BulkRequest(MailSelection):
    """One change to every selected mail (D60); the field named by the action must be set:
    tag_id for tag_*, collection_id for collection_*, review (null: unreviewed) for review,
    flagged for flag."""

    action: BulkAction
    tag_id: int | None = None
    collection_id: int | None = None
    review: ReviewStatus | None = None
    flagged: bool | None = None


class BulkResult(BaseModel):
    mails: int  # mails selected
    changed: int  # contents whose research data changed (byte-identical mails count once)


class PermalinkTarget(BaseModel):
    mail_id: int  # the original (no duplicate, lowest id) among the mails with this content
    raw_sha256: str


class ExportRequest(MailSelection):
    """An export of the selected mails, oldest first (D62)."""

    include_research: bool = False  # notes, tags, status and Akten in PDFs and manifest
    label: str = Field(
        default="", max_length=LABEL_LIMIT
    )  # e.g. the Akte's name, for the export log


class ExportInfo(BaseModel):
    id: int
    label: str
    mails: int
    include_research: bool
    created_by: str | None
    created_at: datetime
    # SHA-256 of the ZIP's SHA256SUMS (which lists every other file) at the first complete
    # download; None before
    manifest_sha256: str | None
    downloaded_at: datetime | None
    download_url: str  # /api/exports/{id}/download


# Attachments and documents (milestone 9, D70 to D77) -----------------------------------------
#
# A document is one distinct attachment content (D70); the list, its figures and the search
# read document rows, never the attachments one by one.

DocumentSort = Literal["recent", "oldest", "mails", "size"]  # first seen, newest or oldest first
DOCUMENT_NAMES_LIMIT = 20  # file names listed in DocumentDetail
DOCUMENT_PERSONS_LIMIT = 10  # senders and recipients listed in DocumentDetail
SNIPPET_LENGTH = 240  # characters of DocumentListItem.snippet


class DocumentFilters(BaseModel):
    """Filters of the document list (D74); every given one must hold. Lists repeat the parameter.

    The conditions on mails (date, person, external) hold when one mail carrying the document
    that is not a duplicate meets them all.
    """

    q: str = ""  # full text over content and file names (websearch_to_tsquery, German)
    name: str = ""  # part of one of its file names, any case
    kind: list[DocumentKind] = []  # any of these; empty: all
    text_status: list[DocumentTextStatus] = []  # any of these; empty: all
    date_from: date | None = None  # UTC day, inclusive: a mail carrying it is dated within
    date_to: date | None = None
    person: int | None = None  # this person (root, with its aliases) took part in such a mail
    person_role: Literal["sent", "received"] | None = None  # how; None: either
    shared: bool = False  # carried by at least two mails
    external: bool = False  # in a mail between internal and external domains (D21)


class DocumentListParams(DocumentFilters):
    sort: DocumentSort = "recent"
    cursor: str | None = None  # next_cursor or prev_cursor of a DocumentPage with the same sort
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class DocumentListItem(BaseModel):
    id: int
    name: str | None  # the file name used most; None when it was sent without one
    names: int  # distinct file names it was sent under
    kind: DocumentKind | None  # None: not classified yet
    mime_type: str
    size: int
    sha256: str | None  # None above the hash limit (D18)
    pages: int | None
    text_status: DocumentTextStatus
    mails: int  # mails carrying it, duplicates not counted
    first_date: datetime | None  # earliest of those mails
    last_date: datetime | None
    first_sender: PersonRef | None  # the sender of the earliest mail
    # With full text words in q: the extracted text around the first place one of them occurs
    # literally, at most SNIPPET_LENGTH characters; None otherwise or when none occurs as typed.
    snippet: str | None = None


class DocumentPage(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None
    prev_cursor: str | None


class DocumentSummary(BaseModel):
    """Figures of the filtered document list under the count budget of D19."""

    total: int | None  # None: counting ran out of time
    exact: bool  # False: total is a lower bound
    kinds: dict[DocumentKind, int] | None  # every kind present; None: ran out of time
    text_status: dict[DocumentTextStatus, int] | None  # every status present


class DocumentNameCount(BaseModel):
    name: str
    attachments: int  # attachments with this file name, duplicates included


class PersonCount(BaseModel):
    person: PersonRef  # a root person; name is its display name
    mails: int  # mails carrying the document that it sent, or received


class DocumentDetail(BaseModel):
    id: int
    name: str | None
    mime_type: str
    kind: DocumentKind | None
    size: int
    sha256: str | None
    pages: int | None
    text_status: DocumentTextStatus
    text_error: str | None  # English, technical; the UI shows a German text per status
    text_truncated: bool
    extracted_at: datetime | None
    mails: int  # duplicates not counted
    attachments: int  # every occurrence, duplicates included
    first_date: datetime | None
    last_date: datetime | None
    first_mail: ThreadMail | None  # the earliest mail carrying it
    names: list[DocumentNameCount]  # most used first, at most DOCUMENT_NAMES_LIMIT
    senders: list[PersonCount]  # most mails first, at most DOCUMENT_PERSONS_LIMIT
    sender_count: int  # all distinct senders
    recipients: list[PersonCount]  # To, Cc or Bcc; most mails first, at most the limit
    recipient_count: int
    attachment_id: int  # the occurrence /api/attachments/{id}/content reads it from
    preview: PreviewKind | None  # how the browser shows it (D120); None: download only


class DocumentText(BaseModel):
    text: str  # the stored text, at most DOCUMENT_TEXT_LIMIT characters; "" without text
    truncated: bool  # the extraction stopped at the limit or the time limit
    text_status: DocumentTextStatus


class AttachmentHit(BaseModel):
    attachment_id: int
    in_name: bool  # one of its document's file names holds a word
    # the text around the first place a word occurs, as typed or as a word one of the query's
    # stems begins; None: only the name holds it, or a form the stems do not begin (rare)
    snippet: str | None


class MailHits(BaseModel):
    """Where the full text words of a mail list's q occur in one mail (D79)."""

    words: list[str]  # the words and phrases as typed, which the browser marks; [] without any
    stems: list[str]  # the lexemes of the query (German stems, lower case, no umlauts), ditto
    in_mail: bool  # the mail's own subject or text holds a word
    attachments: list[AttachmentHit]  # the attachments whose document holds a word, in mail order


# Keys of deleted selectors (D100 to D104) ------------------------------------------------------

# A key name is '<selector>._domainkey.<domain>', lowercase (dkim.override.key_name). A key name
# "concerned" has signatures in the archive that are no_key, or fail with signature_mismatch and
# an intact body (a new key under the old name); the selector pages list those.

SELECTOR_MAILS_LIMIT = 200  # mails listed on a selector page, newest first
EVIDENCE_FILE_LIMIT = 10 * 1024**2  # bytes of an evidence file a manual key may carry

# Which names the selector list shows: concerned names that still have no key (open), concerned
# names whose signatures a key from another source now verifies (resolved), or every name
# with a signature (all).
SelectorFilter = Literal["open", "resolved", "all"]


class SelectorListParams(BaseModel):
    q: str = ""  # part of the key name, any case
    show: SelectorFilter = "open"
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(0, ge=0)


class SelectorItem(BaseModel):
    name: str
    domain: str
    selector: str
    signatures: int  # dkim_result rows of mails that are no duplicates
    mails: int
    statuses: dict[DkimStatus, int]  # those signatures by status, only statuses present
    rsa_signatures: int  # distinct RSA signatures (b=): reconstructable from 2 on
    first_signed: datetime | None  # t= of the oldest and newest signature
    last_signed: datetime | None
    keys: int  # dkim_key rows for the name
    best_origin: KeyOrigin | None  # the strongest origin of those keys
    dns_status: DnsStatus | None  # today's answer in dns_cache; None: not asked yet


class SelectorPage(BaseModel):
    items: list[SelectorItem]
    total: int


class SelectorSummary(BaseModel):
    """The figures of the dashboard card "Gelöschte Selektoren", live."""

    names_missing: int  # key names with no_key signatures
    mails_missing: int  # mails with status no_key
    reconstructable: int  # of those names, the ones with at least 2 distinct RSA signatures
    names_resolved: int  # key names whose signatures a key from another source verifies
    mails_consistent: int  # mails with status consistent
    keys: dict[KeyOrigin, int]  # dkim_key rows by origin, every origin present
    factorable: int  # keys sharing a prime factor (never used)
    signatures: dict[KeyOrigin, int]  # dkim_result rows by key_origin, every origin present
    lookups: dict[KeyLookupSource, int]  # lookups by source, every source present
    last_lookup_at: datetime | None


class KeyLookupInfo(BaseModel):
    """One question to a source (dkim_key_lookup), the answer itself at .../raw."""

    id: int
    source: KeyLookupSource
    query: str
    domain: str | None
    name: str | None
    asked_at: datetime
    outcome: LookupOutcome
    http_status: int | None
    raw_sha256: str | None
    raw_size: int | None
    raw_type: str | None
    raw_name: str | None
    message: str | None  # English
    tool_version: str
    editor: str | None
    keys: int  # keys this lookup gave evidence for


class SelectorMail(BaseModel):
    id: int
    date: datetime | None
    subject: str | None
    sender: PersonRef | None
    signature_index: int
    status: DkimStatus  # of this signature
    reason: DkimReason | None
    key_origin: KeyOrigin | None
    key_id: int | None
    signed_at: datetime | None  # t=


class SelectorDetail(BaseModel):
    name: str
    domain: str
    selector: str
    dns_status: DnsStatus | None  # today's answer in dns_cache; None: not asked yet
    dns_record: str | None
    dns_fetched_at: datetime | None
    signatures: int
    mails: int
    statuses: dict[DkimStatus, int]
    rsa_signatures: int
    first_signed: datetime | None
    last_signed: datetime | None
    keys: list[DkimKeyInfo]  # strongest origin first
    lookups: list[KeyLookupInfo]  # about this name or its domain, newest first
    recent_mails: list[SelectorMail]  # newest first, at most SELECTOR_MAILS_LIMIT


class ManualKeyRequest(BaseModel):
    """A key a person found elsewhere (D103): a zone file, a provider's mail, a screenshot."""

    record: str = Field(min_length=1, max_length=8192)  # the TXT record, or only the p= value
    reference: str = Field(min_length=1, max_length=2000)  # where the key comes from
    note: str = Field("", max_length=NOTE_LIMIT)
    observed_from: datetime | None = None  # when the source says the key was published
    observed_to: datetime | None = None
    file_name: str | None = Field(None, max_length=255)  # the evidence file, if any
    file_base64: str | None = None  # its bytes, at most EVIDENCE_FILE_LIMIT once decoded


class ArchiveDomain(BaseModel):
    domain: str
    names: int  # concerned key names of the domain
    mails: int  # mails with a signature of those names
    last_asked_at: datetime | None  # the latest ZK Email lookup of the domain


class KeyArchivePreview(BaseModel):
    """What "Schlüsselarchiv abfragen" would send, before anything is sent (D102)."""

    url: str | None  # the archive's base URL; None: switched off
    domains: list[ArchiveDomain]  # concerned domains, most mails first
    # Domains under reserved TLDs (.example, .test, ...) go only to an archive on this machine
    skipped: list[str]


class DkimKeysRunRequest(BaseModel):
    task: DkimKeysTask
    names: list[str] = Field([], max_length=1000)  # reconstruct, check: only these key names
    domains: list[str] = Field([], max_length=1000)  # fetch: only these domains
    workers: int | None = Field(default=None, ge=1, le=64)


# Timeline (milestone 11, D90 to D95) -----------------------------------------------------------

MAX_TIMELINE_BUCKETS = 1_500  # a finer bucket that would give more is coarsened (D91)
TIMELINE_SERIES = 6  # default number of split series without split_id (D92)
MAX_TIMELINE_SERIES = 12  # also the most split_id values
MAX_TIMELINE_TERMS = 6  # search strings of split term
FIRST_MENTIONS = 100  # default number of first mentions listed (D94)
MAX_FIRST_MENTIONS = 500

# Bucket of the timeline in UTC: a day, an ISO week (Monday to Sunday) or a calendar month.
TimelineBucket = Literal["day", "week", "month"]
# Series beside the total: none; per person, per thread, or per search string (D92).
TimelineSplit = Literal["none", "person", "thread", "term"]
OutlierKind = Literal["high", "low"]  # well above or well below the moving mean (D93)
FirstMentionRole = Literal["any", "sent"]  # sent or received the mail; only sent it


class TimelineParams(MailFilters):
    """The mails of the mail list's filters (MailFilters) over time (D90)."""

    bucket: TimelineBucket | None = None  # None: chosen by the span of the axis (D91)
    split: TimelineSplit = "none"
    # split person: these persons (an alias counts as its root), split thread: these threads, in
    # this order; empty: the `series` persons or threads with the most matching mails (D92)
    split_id: list[int] = Field([], max_length=MAX_TIMELINE_SERIES)
    # split term: search strings in the syntax of q (D20); each series is the filters AND it
    term: list[str] = Field([], max_length=MAX_TIMELINE_TERMS)
    series: int = Field(TIMELINE_SERIES, ge=1, le=MAX_TIMELINE_SERIES)


class TimelineOutlier(BaseModel):
    index: int  # into Timeline.starts
    kind: OutlierKind
    expected: float  # the moving mean it was compared with (D93)


class TimelineSeries(BaseModel):
    key: str  # "all", "person:<id>", "thread:<id>" or "term:<index into term>"
    # The person's display name, else its address; the subject of the thread's first mail; the
    # search string; None for the total and for a thread without subject.
    label: str | None
    person: PersonRef | None  # split person: the root person (its own name and address)
    thread_id: int | None  # split thread
    term: str | None  # split term: the search string as given
    counts: list[int]  # matching mails per bucket, aligned with Timeline.starts
    total: int  # sum of counts
    outliers: list[TimelineOutlier]  # by index
    # First day of the bucket from which the series has no mail up to the end of the archive or
    # date_to, after steady activity before (D93); None: not silent.
    silent_from: date | None


class Timeline(BaseModel):
    bucket: TimelineBucket  # the bucket of starts
    coarsened: bool  # the requested bucket would have given more than MAX_TIMELINE_BUCKETS
    starts: list[date]  # first day of every bucket of the axis, ascending, without gaps (D91)
    total: TimelineSeries | None  # every matching dated mail, key "all"; None: out of time
    series: list[TimelineSeries]  # the split's series in order; empty without split or out of time
    undated: int | None  # matching mails without a date, which the axis cannot show
    archive_end: date | None  # the archive's latest date not after today (D91); None: no mails
    timed_out: bool  # a count ran out of MAILROBBE_API_COUNT_TIMEOUT; its part is None or empty


class FirstMentionParams(MailFilters):
    """Per root person, the earliest matching mail it takes part in (D94)."""

    role: FirstMentionRole = "any"
    limit: int = Field(FIRST_MENTIONS, ge=1, le=MAX_FIRST_MENTIONS)
    lists: bool = False  # also lists and automated senders (person.kind, D39)


class FirstMention(BaseModel):
    person: PersonRef  # the root person: its own display name and address
    kind: PersonKind | None
    role: ParticipationRole  # its role in that mail, From before To, Cc, Bcc; aliases count
    date: datetime
    mail_id: int
    subject: str | None
    mails: int  # all matching mails the person takes part in (with role sent: sent)


class FirstMentions(BaseModel):
    items: list[FirstMention]  # earliest first (date, then mail id, then person id)
    persons: int | None  # persons with a first mention in all; None: out of time
    timed_out: bool  # the search ran out of MAILROBBE_API_COUNT_TIMEOUT; items is then empty


# Entities (milestone 10, D80 to D89) ---------------------------------------------------------
#
# An entity is one kind and normalised key (D81) found in the subject and text of mails and in
# the extracted text of documents; a mention in a document counts for every mail carrying it.
# entity.mails and the dates count the mentioning mails that are not duplicates, as documents
# do (D70, D85); facets count the mails of the filter as the list shows them.

EntitySort = Literal["mails", "recent", "oldest", "value", "label"]
FACET_MAILS = 10_000  # mails of a filter the facets count over at most (D87)
FACET_LIMIT = 8  # entities per kind in EntityFacets by default
MAX_FACET_LIMIT = 50
ENTITY_PERSONS_LIMIT = 10  # senders and recipients in EntityDetail
ENTITY_RELATED_LIMIT = 20  # entities mentioned in the same mails, in EntityDetail
ENTITY_SAMPLES = 5  # earliest mentions in EntityDetail
ENTITY_SNIPPET_LENGTH = 200  # characters of EntitySample.snippet
ENTITY_REFS_LIMIT = 100  # ids in one /api/entities/refs request


class EntityRef(BaseModel):
    id: int
    kind: EntityKind
    label: str  # display form: "5.000,00 EUR", "DE89 3704 0044 0532 0130 00", "Muster GmbH"
    # term: theme key (themes.toml); place: "city" or "country"; iban, phone: country code
    # (ISO 3166, e.g. "DE"); url: host; None otherwise
    detail: str | None


class EntityListParams(BaseModel):
    """Filters of the entity list (D88); every given one must hold. Lists repeat the parameter."""

    kind: list[EntityKind] = []  # any of these; empty: all
    q: str = ""  # part of the label, any case (pg_trgm)
    detail: str | None = None  # exactly this detail, e.g. a theme key
    value_min: float | None = None  # amounts of at least this value (any currency)
    value_max: float | None = None
    sort: EntitySort = "mails"  # most mails, latest or earliest first mention, value, A to Z
    cursor: str | None = None  # next_cursor or prev_cursor of an EntityPage with the same sort
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class EntityListItem(EntityRef):
    value: float | None  # amount: the sum
    currency: str | None  # amount: ISO 4217 code (EUR, USD, CHF, GBP, DEM)
    mails: int  # mentioning mails, duplicates not counted
    documents: int  # documents whose text mentions it
    first_date: datetime | None  # earliest mentioning mail
    last_date: datetime | None


class EntityPage(BaseModel):
    items: list[EntityListItem]
    next_cursor: str | None
    prev_cursor: str | None


class EntitySummary(BaseModel):
    """What the entity list and the dashboard show beside it (D84)."""

    kinds: dict[EntityKind, int]  # entities per kind, every kind present
    mails_waiting: int  # mails not scanned by the current extraction yet; the next import does
    documents_waiting: int  # document texts not scanned yet (or extracted again since)


class EntityCount(BaseModel):
    entity: EntityRef
    mails: int  # distinct mails


class EntityFacetParams(MailFilters):
    kind: list[EntityKind] = []  # only these kinds; empty: all
    limit: int = Field(FACET_LIMIT, ge=1, le=MAX_FACET_LIMIT)  # entities per kind


class EntityFacets(BaseModel):
    """The entities most mentioned in the mails of a filter (D87).

    Without filters the counts are entity.mails; with filters they count the matching mails,
    all of them up to FACET_MAILS, else FACET_MAILS of them (sampled).
    """

    kinds: dict[EntityKind, list[EntityCount]]  # kinds with entities only; most mails first
    mails: int | None  # mails the counts are over; None without filters (the whole archive)
    sampled: bool  # the filter matches more than FACET_MAILS mails


class EntityYear(BaseModel):
    year: int  # UTC
    mails: int


class EntitySample(BaseModel):
    """A mail mentioning the entity, with the text around its first mention."""

    mail: ThreadMail
    snippet: str | None  # at most ENTITY_SNIPPET_LENGTH characters; None without stored text
    document_id: int | None  # found in this attachment's document; None: in the mail itself
    document_name: str | None


class EntityDetail(EntityListItem):
    key: str  # normalised form (D81)
    contexts: dict[EntityContextKey, int]  # mentioning mails per context (D82), every key present
    years: list[EntityYear]  # mentioning mails per year, oldest first, years without mails left out
    # Root persons who sent or received the mentioning mails, most mails first; counted over
    # the same mails as related, at most FACET_MAILS of them (persons_sampled).
    senders: list[PersonCount]
    sender_count: int
    recipients: list[PersonCount]
    recipient_count: int
    related: list[EntityCount]  # mentioned in the same mails most often, other entities only
    persons_sampled: bool  # senders, recipients and related count FACET_MAILS of the mails
    samples: list[EntitySample]  # the earliest mentions, oldest first
    # The archive's person with this address (email) or, when exactly one has it, this display
    # name (person); None otherwise.
    archive_person: PersonRef | None


class MailEntity(BaseModel):
    """An entity found in one mail (GET /api/mails/{id}/entities)."""

    entity: EntityRef
    occurrences: int
    context: list[EntityContextKey]
    document_id: int | None  # found in this attachment's document; None: in the mail's text
    document_name: str | None


# Topics (milestone 13, D140 to D148) ---------------------------------------------------------
#
# A term is a lexeme of mail.tsv (the German stem PostgreSQL indexes) with the spelling used most
# as its label, which is also the word the mail list searches for (q). Figures count the mails
# that are no duplicates, from their own subject and text; attachments do not count (D140). A
# term stands out in a scope when keyness.keyness says so (D142); share is its share of the
# scope's mails, rest_share its share of the rest of the archive. Before the first topics phase
# (state.computed_at None) every list is empty.

TopicUnit = Literal["month", "quarter", "year"]  # topics.model.Unit
TOPIC_TERMS = 10  # default terms per period in TopicPeriods
TOPIC_PERIOD_TERMS = 30  # terms kept per period (topics.model.PERIOD_TERMS)
TOPIC_SELECTION_TERMS = 30  # default terms of a selection in TopicTerms
MAX_TOPIC_SELECTION_TERMS = 100
TOPIC_SAMPLE = 5_000  # mails of a selection the terms are counted over at most (D144)


class TopicState(BaseModel):
    """What the topics phase last computed (D146)."""

    computed_at: datetime | None  # None: never; the next import computes them
    mails: int  # the archive's mails that are no duplicates, then; the N of every comparison
    terms: int  # the vocabulary
    clusters: int


class TopicTerm(BaseModel):
    term: str  # the lexeme, as in mail.tsv; stable across computations
    label: str  # the spelling used most; the word to search for
    mails: int  # mails of the scope holding it (estimated from a sample when sampled)
    share: float  # of the scope's mails, 0 to 1
    rest_share: float  # of the other mails of the archive, 0 to 1
    ratio: float | None  # share / rest_share; None: no other mail holds it
    score: float  # G2 (D142)
    themes: list[str]  # keys of the themes (themes.toml) whose word field holds the word


class TopicPeriodParams(BaseModel):
    unit: TopicUnit = "month"
    # Only periods overlapping these UTC days, both inclusive; None: from the first, to the last.
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(TOPIC_TERMS, ge=1, le=TOPIC_PERIOD_TERMS)  # terms per period


class TopicPeriod(BaseModel):
    start: date  # first day (UTC)
    end: date  # last day, inclusive, as date_to of the mail list
    mails: int  # its mails that are no duplicates
    terms: list[TopicTerm]  # standing out most first; may be empty


class TopicPeriods(BaseModel):
    state: TopicState
    unit: TopicUnit
    periods: list[TopicPeriod]  # newest first; periods without mails left out


class TopicTermParams(MailFilters):
    """The terms of the mails of the mail list's filters (D144)."""

    limit: int = Field(TOPIC_SELECTION_TERMS, ge=1, le=MAX_TOPIC_SELECTION_TERMS)


class TopicTerms(BaseModel):
    state: TopicState
    mails: int | None  # the selection's mails that are no duplicates; None: not counted in time
    counted: int  # mails the terms were counted over: all, or TOPIC_SAMPLE of them
    sampled: bool  # counted over TOPIC_SAMPLE of more mails; figures are estimates
    terms: list[TopicTerm]  # standing out and not common, highest score first, at most limit
    # Standing out in more than half of the selection's mails (signatures, greetings, a list's
    # footer; D142), most mails first, at most limit.
    common: list[TopicTerm]
    timed_out: bool  # a query ran out of MAILROBBE_API_COUNT_TIMEOUT; the lists are then empty


class TopicClusterTerm(BaseModel):
    term: str  # the lexeme
    label: str
    mails: int  # archive mails holding it (no duplicates)
    weight: float  # its links inside the cluster (D145)
    themes: list[str]


class TopicMonth(BaseModel):
    month: date  # first day (UTC)
    mails: int


class TopicCluster(BaseModel):
    id: int  # valid until the next computation
    label: str  # its first three term labels
    query: str  # search string in the syntax of q: its first five labels joined by "or"
    mails: int  # mails the query finds in their own text, no duplicates
    first_date: datetime | None
    last_date: datetime | None
    terms: list[TopicClusterTerm]  # strongest first
    months: list[TopicMonth]  # months with such mails, ascending


class TopicClusters(BaseModel):
    state: TopicState
    clusters: list[TopicCluster]  # most mails first

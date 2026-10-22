"""The HTTP contract of the web UI (SPEC 4, milestones 4 to 14): query parameters and responses.

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
    GET  /api/mails/{id}/social?SocialParams     SocialCard: what the image blacks out (D214)
    GET  /api/mails/{id}/social.png?SocialParams image/png of the same card
    POST /api/mails/{id}/dkim/recheck            MailDkim, after checking the mail again
    GET  /api/persons?PersonListParams           PersonPage (D31)
    GET  /api/persons/suggestions?SuggestionListParams  SuggestionPage, the open ones of a tier
                                                 with the counts of both (D30, D160)
    POST /api/persons/suggestions/dismiss        SuggestionDismiss -> 204 (D28)
    POST /api/persons/merge                      MergeRequest -> PersonProfile of the target (D28)
    GET  /api/persons/merge-certain              CertainMergePlan: what merging every certain
                                                 suggestion would do (D162)
    POST /api/persons/merge-certain              CertainMergeResult, one batch of merges (D162)
    GET  /api/persons/merges?MergeLogParams      MergeLogPage, newest first (D163)
    POST /api/persons/merges/{id}/undo           MergeUndoResult (D163); 409 merge_undone
    POST /api/persons/merge-batches/{id}/undo    MergeUndoResult, every merge of the batch not
                                                 undone yet (D162); 409 merge_undone
    GET  /api/persons/{id}                       PersonProfile; of the root when id is an alias
    GET  /api/persons/{id}/contacts?ContactListParams   ContactPage
    GET  /api/persons/{id}/mail-counts?PersonMailCountParams  PersonMailCounts (D32)
    POST /api/persons/{id}/unmerge               PersonProfile of the root it was merged into

Merges and undoing them take the editor from X-Mailrobbe-Editor (D54), as the research file
does.
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
    GET  /api/documents/metadata-values?MetadataValueParams  MetadataValues: authors or
                                                 programs of the filtered documents (D167)
    GET  /api/attachments/{id}/content           the attachment's bytes as a download (D76)
    GET  /api/attachments/{id}/html              text/html of a DOCX or ODT for a sandboxed
                                                 iframe, converted and cached (D122)
    GET  /api/attachments/{id}/media             audio or video, with Range requests (D123)
    GET  /api/mails/{id}/hits?MailHitsParams     MailHits: where q's words occur in the mail (D79,
                                                 D176)
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

Signals (milestone 12, D130 to D139):

    GET  /api/signals                            SignalOverview: figures, rules, silent persons
    GET  /api/mails/signals?MailFilters          SignalFacets: mails per signal of a filter (D136)
    GET  /api/mails/{id}/signals                 MailSignals: the signals of one mail, with why
    GET  /api/persons/{id}/signals               PersonSignals: of the root when id is an alias

Milestone 14 (D150 to D157): quoted text, near duplicates, calendar invitations, named accounts.
MailText has the text's segments (D151), MailDetail the near duplicates and the events, the
mail list filters both (collapse_near, near_group, event, event_uid), and every PersonRef,
PersonSummary and GraphNode carries the label of its address (D156, persons.labels):

    GET  /api/persons/{id}/events                PersonEvents: events the person organised or
                                                 was invited to (D155), of the root for an alias
    PUT  /api/persons/{id}/label                 PersonLabelUpdate -> PersonProfile; sets the
                                                 label of the root's address, or removes it when
                                                 every field is empty (D156)

Milestone 18 (D220 to D229): hide rules and standard blocks. MailFilters has include_hidden,
body_part and block, MailHitsParams body_part, q the proximity term "a b"~N (QueryKey near),
MailSummary the hidden mails, MailDetail why it is hidden, MailText the standard blocks as
segments and its paragraphs; writes take the editor from X-Mailrobbe-Editor (D54):

    GET    /api/hide-rules                       HideRuleList
    POST   /api/hide-rules/preview               HideRuleFields -> HideRulePreview (D223)
    POST   /api/hide-rules                       HideRuleFields -> 201 HideRuleInfo, its mails
                                                 computed; 400 invalid_rule
    PUT    /api/hide-rules/{id}                  HideRuleUpdate -> HideRuleInfo
    DELETE /api/hide-rules/{id}                  204
    GET    /api/hide-rules/suggestions           list[HideSuggestion], most mails first
    GET    /api/blocks/summary                   BlockSummary
    GET    /api/blocks?BlockListParams           BlockPage
    GET    /api/blocks/{hash}                    BlockDetail; 404 for a hash neither a block nor
                                                 the team's choice knows
    PUT    /api/blocks/{hash}/override           BlockOverrideUpdate -> BlockInfo (D225);
                                                 400 invalid_block

Milestone 19 (D230 to D239): protected and packed attachments. AttachmentInfo has a container's
members and the protection, DocumentFilters and DocumentSummary the protection, DocumentDetail the
password with where it was found, the container's entries and the containers holding it,
ExportRequest include_passwords; writes take the editor from X-Mailrobbe-Editor (D54):

    POST /api/documents/{id}/password            PasswordTry -> PasswordTryResult: a typed-in
                                                 password tried on one locked document (D237);
                                                 409 not_locked
    POST /api/documents/passwords                PasswordTry -> PasswordTryResult: on every
                                                 locked document
    GET  /api/attachments/{id}/content?decrypted=true  the opened document's bytes decrypted,
                                                 made for the download and never stored (D209);
                                                 409 not_locked, 422 decrypt_failed

Places (milestone 20, D240 to D249). The map's filters are PlaceParams: the mail filters, which
a mail carrying the photo, mentioning the place or carrying the invitation must meet, and the
photo's capture time and device. MailFilters has photo_area, MetadataSummary the position:

    GET    /api/places/summary                   PlaceSummary: photos, devices, the places
                                                 step's figures
    GET    /api/places/photos?PlaceParams        PhotoPoints: the photos with a position (D247)
    GET    /api/places/photos/{id}               PhotoDetail of one document with a position,
                                                 its mails and the nearest town (D248)
    GET    /api/places/photo-list?PhotoListParams  PhotoList: around a point, nearest first, or
                                                 by capture time (D248)
    GET    /api/places/texts?PlaceParams         TextPlaces: places named in the mails (D242)
    GET    /api/places/events?PlaceParams        EventPlaces: places of invitations (D243)
    GET    /api/map/towns                        list[TownLabel], the overview map's labels (D244)
    GET    /api/map/status                       MapStatus: the detail map, the offer, the run
    POST   /api/map/download                     MapDownloadRequest -> 202 MapJob (D246); 409
                                                 map_off, job_running for a map run alive
    POST   /api/map/download/stop                MapJob, its stop requested
    DELETE /api/map/detail                       204; the detail map and a stopped download's
                                                 part are deleted; 409 job_running
    GET    /api/map/tiles/{file}                 the detail map's PMTiles file, with Range
                                                 requests (206, 416, ETag); 404 for any other

AI services (milestone 15, D180 to D189). DocumentFilters has text_origin, DocumentListItem and
DocumentDetail the text origin, DocumentDetail the AI result and open task and whether OCR can
read it, DocumentSummary the readable documents, AttachmentHit and MailListItem whether a hit
stands in a machine made text, ImportStatus the latest AI run; writes take the editor from
X-Mailrobbe-Editor (D54):

    GET  /api/ai/status                          AiStatus: services as configured, queue, work
                                                 lists with estimates, the latest run (D188)
    POST /api/ai/services/{capability}/check     ServiceCheck: the service asked and tested
                                                 now; 404 not_found without one
    POST /api/ai/tasks                           AiQueueRequest -> AiQueued (D186); 400
                                                 invalid_selection, too_many_documents; with
                                                 start a run for just these documents (D280)
    GET  /api/ai/tasks?AiTaskParams              AiTaskPage, newest first
    POST /api/ai/tasks/retry                     AiTaskAction -> AiChanged: failed and cancelled
                                                 ones queued again
    POST /api/ai/tasks/cancel                    AiTaskAction -> AiChanged: waiting ones taken off
    GET  /api/ai/results?AiResultParams          AiResultPage, newest first
    POST /api/ai/results/{id}/discard            AiChanged; 404 not_found for none or one
                                                 discarded before (D185)
    POST /api/ai/jobs/{id}/discard               AiChanged: every valid result of the run
    GET  /api/ai/send-log?AiSendLogParams        AiSendLogPage, newest first (D181)
    POST /api/ai/run                             AiRunRequest -> 202 AiJob (D187); 409
                                                 job_running while an import or AI run lives
    POST /api/ai/run/stop                        AiJob, its stop requested

Summaries and AI tags (milestone 17, D300 to D311): POST /api/ai/tasks takes kind summarize with
mail_ids, mail_filters (an Akte is collection=<id>), document_ids or the document list's filters,
and with preview only counts and estimates; tasks, results and the send log name a mail or a
document (target). MailFilters has ai_tag and ai_theme, DocumentFilters ai_tag:

    GET  /api/ai/summary?AiSummaryParams         AiSummaryView: the summary of one mail or
                                                 document, its open task, and for a mail the
                                                 summaries of its attachments (D307); 400
                                                 invalid_selection unless exactly one is given,
                                                 404 not_found for an unknown one
    GET  /api/ai/facets?MailFilters              AiFacets: AI tags and themes of the matching
                                                 mails, counted as the entity facets (D309)
    GET  /api/ai/tags?AiTagParams                list[AiTagCount]: AI tags by id or by part of
                                                 their name, most mails first (D309)
    POST /api/ai/tags/{id}/adopt                 AiTagAdopt -> AiTagAdopted: a team tag of the
                                                 same name on the mails carrying the AI tag
                                                 (D310); 404 not_found for an unknown AI tag

The mails of a person (SPEC 5.3) are GET /api/mails with person=<id> and person_role (D32), so
paging, neighbours and the CSV export work as for the mail list; the mails carrying a document
(D75) are GET /api/mails with document=<id>.

Paging with page numbers (D193, api/paging.py): the mail, person, document and entity lists take
page (a jump to that page) or last (the last page) instead of a cursor and answer the page's
number in their page model; 400 page_too_far when a jump does not answer within the count budget.
The selector list pages by offset and has its total.

Every other GET path outside /api serves the frontend (index.html for client-side routes).
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from mailrobbe.ai.model import (
    AiOptions,
    AiProgress,
    Capability,
    Locality,
    OcrEngine,
    OcrEngineChoice,
    Protocol,
)
from mailrobbe.dkim.keys.model import (
    DkimKeysOptions,
    DkimKeysPhase,
    DkimKeysProgress,
    DkimKeysTask,
)
from mailrobbe.enums import (
    AiResultState,
    AiTarget,
    AiTaskKind,
    AiTaskStatus,
    AliasTier,
    DkimReason,
    DkimStatus,
    DnsStatus,
    DocumentKind,
    DocumentMembersStatus,
    DocumentMemberStatus,
    DocumentMetadataStatus,
    DocumentProtection,
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
    PasswordTier,
    PersonKind,
    ReviewStatus,
    TextOrigin,
)
from mailrobbe.jobs import DbActivity, DkimOptions, DkimProgress, ImportOptions, ImportProgress
from mailrobbe.persons.suggestions import SuggestionReason
from mailrobbe.places.model import (
    BBox,
    MapDetailKey,
    MapOptions,
    MapPhase,
    MapProgress,
    MapRegionKey,
)
from mailrobbe.preview.kinds import PreviewKind
from mailrobbe.social.model import TERM_LIMIT, TERMS_LIMIT, CardShape, RedactionKind

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

# Kinds of calendar events (D154): request (an invitation or update: METHOD REQUEST, PUBLISH, ADD
# or none), reply (an answer: REPLY, COUNTER, DECLINECOUNTER), cancel (CANCEL, or STATUS
# CANCELLED). Filter, count and display keys.
EventKey = Literal["request", "reply", "cancel"]

# Review statuses as filter and count keys (D55); unreviewed stands for no status.
ReviewKey = Literal["unreviewed", "seen", "relevant", "irrelevant"]
# mail.dkim_status values as filter and count keys; unchecked stands for NULL (not checked yet).
DkimKey = Literal["pass", "consistent", "fail", "no_key", "unsigned", "temp_error", "unchecked"]
SortOrder = Literal["date_desc", "date_asc"]
QueryKey = Literal[
    "text",
    "from",
    "to",
    "cc",
    "subject",
    "domain",
    "has",
    "dkim",
    "before",
    "after",
    "message_id",
    # Full text words in one place (D172), written betreff:, text:, anhang:, datei:
    "in_subject",
    "in_body",
    "in_attachment",
    "in_filename",
    # Two words at most QueryTerm.distance words apart, in either order (D229): "a b"~N
    "near",
]
# Where the full text words of q are looked for (D171): the mail's subject and its text, the
# text of its attachments' documents and their file names.
SearchField = Literal["subject", "body", "attachment", "filename"]
MIN_HITS_LIMIT = 999  # the largest min_hits (D174)
# The parts of a mail's own text the full text words are looked for in (D226, D228): clean
# leaves out the standard blocks, own also the quotes, originals and forwards (the words the
# sender wrote), full looks at all of it. The subject is always looked at.
BodyPart = Literal["clean", "own", "full"]
PROXIMITY_LIMIT = 20  # the largest N of "a b"~N (D229)
# A paragraph's hash: 16 lower-case hex digits (blocks.model).
BLOCK_HASH_PATTERN = r"^[0-9a-f]{16}$"
# An area of the map (D248): west,south,east,north in decimal degrees.
AREA_PATTERN = r"^-?\d{1,3}(\.\d+)?(,-?\d{1,3}(\.\d+)?){3}$"
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
    "merge_undone",  # 409: the merge, or every merge of the batch, was undone already (D163)
    "invalid_rule",  # 400: a hide rule without any criterion, or one that cannot be used (D221)
    "invalid_block",  # 400: a sample that is no paragraph of this hash, or none where needed
    "page_too_far",  # 400: a jump to a page did not answer within the count budget (D193)
    "not_locked",  # 409: the document is not locked, or (decrypted) has no password found yet
    "decrypt_failed",  # 422: the found password did not decrypt it; message says why
    "map_off",  # 409: no detail map is offered (MAILROBBE_MAP_SOURCE=off, D245)
    "too_many_documents",  # 400: a selection for the AI queue above AI_QUEUE_LIMIT (D186)
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
    # Signals (D136): each of these holds for the mail; SignalKind values of mails or
    # "term:<theme key>" (signals.model); an unknown key is invalid_filter.
    signal: list[str] = []
    # Near duplicates (D153): per group only its earliest mail meeting the other filters, so a
    # group shows as one mail; the mails of this group.
    collapse_near: bool = False
    near_group: int | None = None
    # Calendar (D155): the mail carries an event of any of these kinds; an event with this UID.
    event: list[EventKey] = []
    event_uid: str | None = None
    # Full text options (D171 to D174), without effect when q has no full text words: where its
    # free words are looked for (empty: everywhere), whole words only (no German stems, no part
    # of a longer word, any case, umlauts and accents count), and at least min_hits occurrences
    # of the words in those places of the mail and its attachments together.
    scope: list[SearchField] = []
    whole_word: bool = False
    min_hits: int | None = Field(default=None, ge=1, le=MIN_HITS_LIMIT)
    # Milestone 18: mails a hide rule hides are left out unless include_hidden (D222); the parts
    # of the mail's own text the full text words are looked for in (D226); the mails holding
    # this paragraph anywhere in their stored text, a standard block or not (D227).
    include_hidden: bool = False
    body_part: BodyPart = "clean"
    block: str | None = Field(default=None, pattern=BLOCK_HASH_PATTERN)
    # Milestone 20 (D248): the mail carries a photo whose position lies in this area,
    # "west,south,east,north" in decimal degrees; west above east crosses the 180th meridian.
    photo_area: str | None = Field(default=None, pattern=AREA_PATTERN)
    # Milestone 17 (D309): a valid summary of the mail or of one of its attachments' documents
    # has each of these AI tags (ai_tag.id); has a theme hint for each of these theme keys of
    # themes.toml (an unknown key is invalid_filter).
    ai_tag: list[int] = []
    ai_theme: list[str] = []


class MailOrderParams(MailFilters):
    sort: SortOrder = "date_desc"


class MailListParams(MailOrderParams):
    cursor: str | None = None  # next_cursor or prev_cursor of a MailPage with the same sort
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    # A jump instead of a cursor (D193): this page (from 1) of `limit` mails, a page beyond the
    # end being the last one; or with last the last `limit` mails, read from the end.
    page: int | None = Field(default=None, ge=1)
    last: bool = False


# Mail list ------------------------------------------------------------------------------------


class AccountLabel(BaseModel):
    """The team's label of an address (D156), shown with the person wherever it appears."""

    name: str | None  # Klarname
    role: str | None  # Rolle


class PersonRef(BaseModel):
    person_id: int
    email: str
    name: str | None  # the display name used in this mail, else the person's display name
    # The label of this address, else of its root, else the newest of the root's other
    # addresses (D156); set by persons.labels.attach_labels.
    label: AccountLabel | None = None


class QueryTerm(BaseModel):
    """One understood part of q, for the filter chips."""

    key: QueryKey  # text: full text words; message_id: a bare <id@host> token
    value: str  # unquoted, e.g. 'finale Fassung' for subject:"finale Fassung"
    raw: str  # the exact substring of q; removing it from q removes this term
    # An operator or Message-ID written with a leading minus: it must not hold (D175). Free
    # text words keep their minus in value, as websearch_to_tsquery reads it.
    negated: bool = False
    # key near: the most words between the two words of value (1 to PROXIMITY_LIMIT, D229)
    distance: int | None = None


class MailHitCounts(BaseModel):
    """How often the full text words of q occur in one mail, by place (D176): the words that
    count for min_hits, each counted in the places it is looked for, 0 elsewhere."""

    subject: int
    body: int
    attachment: int  # in the texts of its attachments' documents, every attachment counted
    filename: int  # in the file names of its attachments' documents


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
    near_count: int = 0  # the other mails of its group of near duplicates (D153); 0: none
    event: EventKey | None = None  # the kind of the mail's first calendar event (D155)
    hits: MailHitCounts | None = None  # q has full text words: where they occur (D176)
    # the text of an attachment that holds a counted word was recognised by an AI run, not read
    # from its file (D189); the UI marks the hit "maschinell erkannt"
    attachment_machine: bool = False


class MailPage(BaseModel):
    items: list[MailListItem]
    next_cursor: str | None  # None on the last page
    prev_cursor: str | None  # None on the first page
    query_terms: list[QueryTerm]
    # The page's number (D193): 1 for the first page, the page a jump read; None after a
    # cursor and for the last page read from the end (last).
    page: int | None = None


class MailSummary(BaseModel):
    """Figures of the filtered list (D19); from global_stats when no filter is set."""

    total: int | None  # None: unknown, even the bounded count ran out of time
    exact: bool  # False: total is a lower bound, shown as "mehr als ..."
    dkim: dict[DkimKey, int] | None  # every key present; None when counting ran out of time
    persons: int | None  # distinct persons taking part in the matches
    domains: int | None  # distinct domains of those persons
    date_min: datetime | None
    date_max: datetime | None
    # Without include_hidden: the mails the other filters match that a hide rule hides (D222);
    # None with include_hidden, or when counting ran out of time.
    hidden: int | None = None


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


class NearFigures(BaseModel):
    """What the last near phase found (D153), from global_stats 'near'."""

    groups: int  # groups of near duplicates
    mails: int  # mails in them that are no duplicates
    hidden: int  # mails that collapse_near leaves out (duplicates in a group included)


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
    near: NearFigures | None = None  # None: the near phase never ran (D153)
    # Mails with an event of each kind at the last calendar phase (D155); every key present.
    events: dict[EventKey, int] = {}


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
    """A stored key (dkim_key): kept from DNS (D106) or from another source, with all its
    evidence."""

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
    # the stored key that verified it; None when today's DNS answer did, or none verified
    key: DkimKeyInfo | None = None


class MailDkim(BaseModel):
    status: DkimStatus | None  # None: not checked yet
    signatures: list[DkimSignature]


class Participant(PersonRef):
    role: ParticipationRole
    # From person_stats and edge, which milestone 5 fills (D26); None until then.
    mails: int | None  # sent + received
    contacts: int | None
    mails_with_sender: int | None  # edge.mails_total with the sender; None for the sender


class MetadataSummary(BaseModel):
    """The few metadata fields of a document shown next to an attachment (D167), as found in
    the file (EXIF, PDF info dictionary and XMP, office properties), never rated. None for a
    field the file does not have; the document page shows every field found."""

    author: str | None = None  # Artist, Author, dc:creator, initial creator
    modified_by: str | None = None  # lastModifiedBy, dc:creator of ODF
    software: str | None = None  # Software, CreatorTool, Creator/Producer, Application, generator
    device: str | None = None  # camera or scanner: Make and Model
    created: datetime | None = None  # when the file says it was made or taken, UTC
    gps: bool = False  # the file names a place (EXIF GPS)
    # The position it states (D241): decimal degrees, south and west negative; None without one.
    latitude: float | None = None
    longitude: float | None = None


# Where the text recognition stands for an attachment's document (D280): OCR can read it and
# nothing has yet; a task is open; its text was recognised; it was read and holds no writing.
# None: OCR has nothing to do with it (a text of its own, no SHA-256, no document yet).
AttachmentOcr = Literal["readable", "queued", "recognised", "no_text"]


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
    metadata: MetadataSummary | None = None  # what the file says about itself (D167)
    # Locked: it needs a password; open: one was found (D233). None: not protected.
    protection: DocumentProtection | None = None
    path: str | None = None  # a member's path inside its container (D231); None otherwise
    # A container (ZIP, 7z, attached mail): whether it was unpacked, and its entries that became
    # documents, in the container's order (D231); None and [] for any other attachment.
    members_status: DocumentMembersStatus | None = None
    members: list["AttachmentInfo"] = []
    ocr: AttachmentOcr | None = None  # the text recognition of its document (D280)


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


class NearMail(ThreadMail):
    """Another mail of the same group of near duplicates (D153)."""

    recipients: list[PersonRef]  # To, then Cc, then Bcc; at most RECIPIENT_PREVIEW
    recipient_count: int
    is_duplicate: bool  # an exact duplicate (D16) of a mail of the group


class CalendarAttendee(BaseModel):
    """An organizer or attendee of an event (D154), as the iCalendar part names it."""

    email: str | None  # lower case; None: no mailto address
    name: str | None  # CN
    role: str | None  # ROLE: CHAIR, REQ-PARTICIPANT, OPT-PARTICIPANT, NON-PARTICIPANT
    partstat: str | None  # PARTSTAT: ACCEPTED, DECLINED, TENTATIVE, NEEDS-ACTION, DELEGATED
    person: PersonRef | None  # the archive's person of the address; None: not in the archive


class CalendarEventInfo(BaseModel):
    """One event of an iCalendar part of a mail (D154, D155)."""

    id: int
    mail_id: int
    kind: EventKey
    method: str | None  # METHOD as written, upper case
    uid: str | None
    sequence: int | None
    status: str | None  # STATUS: CONFIRMED, TENTATIVE, CANCELLED
    summary: str | None
    location: str | None
    description: str | None  # at most ical.model.DESCRIPTION_LIMIT characters
    # The wall time as written (no zone, ISO without offset) and its TZID ("UTC" for a time in
    # UTC); starts_at and ends_at the instant when the zone is known, else None.
    starts_local: datetime | None
    ends_local: datetime | None
    time_zone: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    all_day: bool  # DTSTART is a date: starts_local and ends_local at midnight
    recurrence: str | None  # RRULE as written
    organizer: CalendarAttendee | None
    attendees: list[CalendarAttendee]  # in the order of the part
    uid_mails: int  # mails with an event of this UID, this one included; 0 without a UID


# Hide rules (milestone 18, D221 to D223) -------------------------------------------------------

# How a hide rule compares the subject (D204): it holds the text, or starts with it; any case,
# no regular expressions.
SubjectMatch = Literal["contains", "starts"]
HIDE_EXAMPLES = 5  # mails a preview shows
HIDE_SUGGESTIONS = 20  # suggestions of each kind


class HideRuleFields(BaseModel):
    """The criteria of a hide rule (D221): every one given must hold, at least one is given."""

    name: str | None = None  # the team's name for it; None: the UI describes the criteria
    sender: str | None = None  # the sender's address, any case
    person_id: int | None = None  # a person: every address of its root
    domain: str | None = None  # the sender's domain or a subdomain of it, any case
    list_id: str | None = None  # the List-Id as stored (mail.list_id)
    automated: bool = False  # sent automatically (mail.automated, D39)
    subject: str | None = None  # compared by subject_match, any case
    subject_match: SubjectMatch = "contains"


class HideRuleUpdate(HideRuleFields):
    enabled: bool = True  # a disabled rule hides nothing and keeps its criteria


class HideRuleInfo(HideRuleFields):
    id: int
    enabled: bool
    person: PersonRef | None  # the person of person_id; None without one or when it is gone
    mails: int  # mails it matches, those D203 keeps visible included
    computed_at: datetime | None  # when its mails were last computed
    created_by: str | None  # D54
    created_at: datetime
    updated_by: str | None
    updated_at: datetime


class HideRuleList(BaseModel):
    rules: list[HideRuleInfo]  # newest first
    hidden: int  # mails an enabled rule hides, without those D203 keeps visible
    kept: int  # mails an enabled rule matches that stay visible (D203)


class HideRulePreview(BaseModel):
    """What a rule would hide (D223), before it is saved."""

    mails: int  # mails it matches
    kept: int  # of these, in an Akte, with a note, bookmarked or relevant: they stay visible
    with_terms: int  # of these, with a word-field signal (term:*, D138)
    examples: list[MailListItem]  # the newest HIDE_EXAMPLES of them


HideSuggestionKind = Literal["list", "sender"]


class HideSuggestion(BaseModel):
    """A mailing list or an automated sender with many mails (D223); a click makes it a rule."""

    kind: HideSuggestionKind
    list_id: str | None  # kind list
    person: PersonRef | None  # kind sender: a root person of kind list or automated (D39)
    mails: int


class MailHiding(BaseModel):
    """Why a mail is hidden (D222)."""

    rules: list[HideRuleInfo]  # the enabled rules matching it
    kept: bool  # it stays visible all the same (D203)


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
    # Near duplicates (D153): its group (the group's first mail id; None: in no group), the
    # other mails of the group, oldest first, at most NEAR_LIMIT, and the group's size with
    # this mail (0: in no group).
    near_group: int | None = None
    near: list[NearMail] = []
    near_size: int = 0
    events: list[CalendarEventInfo] = []  # its calendar events in mail order (D155)
    hidden: MailHiding | None = None  # an enabled hide rule matches it (D222)
    list_id: str | None = None  # its List-Id, as a hide rule names it (D221)


# Bodies, read on demand from the MBOX file -------------------------------------------------


# Segments of a mail's text (D151): its own words, a quote ('>' lines with the attribution above
# them), an original message (Outlook's header block and everything after it), a forwarded
# message (the forward's header block and everything after it), and a signature ("-- " on a
# line, up to the next segment of another kind or the end); a standard block (D227) is cut out
# of the segment it stands in.
SegmentKind = Literal["text", "quote", "original", "forward", "signature", "standard"]


class TextSegment(BaseModel):
    kind: SegmentKind
    start: int  # character offset in MailText.text
    end: int  # exclusive; the segments cover the text in order, without gaps
    lines: int  # lines of the segment that are not blank
    folded: bool  # shown folded at first (D151); the UI opens one holding a search word
    block: str | None = None  # kind standard: the block's hash


class TextParagraph(BaseModel):
    """A paragraph of MailText.text that counts (D224), for the team's choice about it (D225)."""

    start: int  # character offsets in MailText.text
    end: int
    hash: str
    standard: bool  # a standard block as the last blocks step applied them
    mails: int  # mails holding it (paragraph_block); 0 when the blocks step did not count it
    override: bool | None  # the team's choice, applied at the next run; None: none


class MailText(BaseModel):
    text: str  # the text part the importer indexes (D3 order), in full up to TEXT_LIMIT
    truncated: bool
    source: Literal["text/plain", "text/html", "none"]  # text/html: converted to text
    has_html: bool  # an HTML part exists, so format=html has something to show
    segments: list[TextSegment] = []  # quotes.split_text (D151); one text segment without any
    paragraphs: list[TextParagraph] = []  # in text order (D224)


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
NEAR_LIMIT = 50  # other mails of a group of near duplicates in MailDetail (D153)
PERSON_EVENT_LIMIT = 50  # events in PersonEvents (D155)
LABEL_NAME_LIMIT = 200  # characters of a label's name and of its role (D156)
LABEL_NOTE_LIMIT = 10_000  # characters of a label's note
DISPLAY_NAME_LIMIT = 10  # display names listed in PersonProfile
SUGGESTION_LIMIT = 10  # open alias suggestions listed in PersonProfile
MERGE_LIMIT = 50  # sources of one merge request


class PersonLabelUpdate(BaseModel):
    """The label of a person's root address (D156); blank fields are removed, all blank removes
    the label."""

    name: str = Field("", max_length=LABEL_NAME_LIMIT)
    role: str = Field("", max_length=LABEL_NAME_LIMIT)
    note: str = Field("", max_length=LABEL_NOTE_LIMIT)


class PersonListParams(BaseModel):
    # Part of an address, display name, label name or role (D157) of the person or of one of
    # its aliases, any case.
    q: str = ""
    labelled: bool = False  # only persons with a label (D157)
    sort: PersonSort = "mails"
    cursor: str | None = None  # next_cursor or prev_cursor of a PersonPage with the same q, sort
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    # A jump instead of a cursor (D193), as in MailListParams.
    page: int | None = Field(default=None, ge=1)
    last: bool = False


class ContactListParams(BaseModel):
    cursor: str | None = None  # next_cursor of a ContactPage of the same person
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class SuggestionListParams(BaseModel):
    cursor: str | None = None  # next_cursor of a SuggestionPage of the same tier
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    tier: AliasTier = AliasTier.CERTAIN  # D160


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
    label: AccountLabel | None = None  # D156, as PersonRef.label for the root


class PersonPage(BaseModel):
    items: list[PersonSummary]
    next_cursor: str | None  # None on the last page
    prev_cursor: str | None  # None on the first page
    total: int  # persons matching q
    page: int | None = None  # as MailPage.page (D193)


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
    label: AccountLabel | None = None  # the label of this address itself (D156)


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
    same_name: str | None  # the main name both use (D161)
    same_local_part: str | None  # the local part both addresses have
    tier: AliasTier  # D160
    reason: SuggestionReason  # which signs agree; the UI says it in German


class AliasSuggestion(BaseModel):
    first: PersonSummary  # the one with more mails; merging keeps it by default
    second: PersonSummary
    same_name: str | None
    same_local_part: str | None
    tier: AliasTier
    reason: SuggestionReason


class SuggestionCounts(BaseModel):
    certain: int
    uncertain: int


class MergeLogEntry(BaseModel):
    """A logged merge (D163): the persons it moved into its target."""

    id: int
    target: PersonRef  # the root merged into; name is its display name
    moved: list[PersonRef]  # every person it moved, the aliases of its sources too, by id
    batch_id: int | None  # the batch of "Alle sicheren zusammenführen" (D162); None: one merge
    editor: str | None
    created_at: datetime
    undone_at: datetime | None
    undone_by: str | None


class SuggestionPage(BaseModel):
    items: list[AliasSuggestion]  # both reasons first, then by the mails of `first`, then ids
    next_cursor: str | None
    total: int  # every open suggestion of the tier asked for
    counts: SuggestionCounts  # every open suggestion per tier
    computed: bool  # False until a refresh computed them by the current rules (with tiers)


class PersonLabel(AccountLabel):
    """A label with its note and who set it (D156), in the profile."""

    email: str  # the address it belongs to: the root's own, or one of its aliases'
    note: str | None
    editor: str | None  # D54
    updated_at: datetime


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
    suggestions: list[AliasCandidate]  # certain first, then most mails, at most SUGGESTION_LIMIT
    suggestion_counts: SuggestionCounts  # every open suggestion with this person, per tier
    merges: list[MergeLogEntry]  # merges not undone that brought addresses it still has (D163)
    label: PersonLabel | None = None  # D156: the label the person shows, with its note


class PersonEvent(BaseModel):
    """An event of a person (D155): one per UID, the latest mail carrying it."""

    event: CalendarEventInfo
    organizer: bool  # the person (one of its addresses) organised it; else it is an attendee
    partstat: str | None  # the person's answer as an attendee, from the latest reply or the event
    mail: ThreadMail  # the mail carrying the event


class PersonEvents(BaseModel):
    items: list[PersonEvent]  # latest start first (undated last), at most PERSON_EVENT_LIMIT
    total: int  # distinct events of the person


class PersonMailCounts(BaseModel):
    """Mails of each tab for one person (D32) under the count budget of D19; None: ran out."""

    all: int | None
    sent: int | None
    received: int | None
    cc: int | None


class MergeLogParams(BaseModel):
    cursor: str | None = None  # next_cursor of a MergeLogPage
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class MergeBatchInfo(BaseModel):
    """A batch of "Alle sicheren zusammenführen" (D162)."""

    id: int
    created_at: datetime
    editor: str | None
    merges: int
    undone: int  # of its merges, those undone


class MergeLogPage(BaseModel):
    items: list[MergeLogEntry]  # newest first
    batches: list[MergeBatchInfo]  # the batches of these items, newest first
    next_cursor: str | None
    total: int  # every logged merge


class CertainMergePlan(BaseModel):
    """What "Alle sicheren zusammenführen" merges (D162): the persons joined by certain
    suggestions, each group into the person with the most mails."""

    merges: int  # groups of at most persons.merge.MERGE_GROUP persons
    persons: int  # persons that become aliases
    left_out_groups: int  # larger groups, or with a dismissed pair: for a look of their own
    left_out_persons: int


class CertainMergeResult(CertainMergePlan):
    batch_id: int | None  # for undoing the batch; None when there was nothing to merge


class MergeUndoResult(BaseModel):
    merges: int  # merges marked undone
    persons: int  # persons put back where they were before


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
    label: AccountLabel | None = None  # D156, as PersonRef.label for the root


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
    "scan", "headers", "import", "finalize", "attachments", "entities", "signals", "topics"
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
    ai_job: "AiJob | None" = None  # the latest AI run (D187), which an import waits for


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
    open_suggestions: int  # certain alias suggestions not dismissed (D160)
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
    # The term entity (D83) of each term, in the order of terms; None while no scan found it.
    # The Akten screen links a term with an entity to the mail list filtered by it (D138).
    term_ids: list[int | None]
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
    include_passwords: bool = False  # the passwords that opened attachments (D208)
    label: str = Field(
        default="", max_length=LABEL_LIMIT
    )  # e.g. the Akte's name, for the export log


class ExportInfo(BaseModel):
    id: int
    label: str
    mails: int
    include_research: bool
    include_passwords: bool = False
    created_by: str | None
    created_at: datetime
    # SHA-256 of the ZIP's SHA256SUMS (which lists every other file) at the first complete
    # download; None before
    manifest_sha256: str | None
    downloaded_at: datetime | None
    download_url: str  # /api/exports/{id}/download


# Social media image (D214 to D217) -------------------------------------------------------------
#
# One mail as a PNG that looks like a mail client, with the persons in it blacked out before
# anything is drawn (D216). The picture is made for the request and stored nowhere.


class SocialParams(BaseModel):
    """What the image shows and what it blacks out; the defaults are those of D215."""

    shape: CardShape = CardShape.PORTRAIT
    participants: bool = True  # From, To, Cc and Bcc with their names and labels (D156)
    contacts: bool = True  # addresses, phone numbers, IBANs and account numbers in the text
    names: bool = True  # persons' names in the text
    organizations: bool = False  # organisations, places, URLs and domains in the text
    terms: list[Annotated[str, Field(max_length=TERM_LIMIT)]] = Field(
        default_factory=list, max_length=TERMS_LIMIT
    )  # the team's own terms, blacked out wherever they stand
    quotes: bool = False  # show the quoted text too
    dkim: bool = True  # the DKIM seal beside the date
    checksum: bool = True  # the first 16 digits of the mail's SHA-256 in the footer (D61)


class SocialRedaction(BaseModel):
    places: int  # places blacked out
    kind: RedactionKind


class SocialCard(BaseModel):
    """What the image of the same parameters holds, for the dialog beside the preview (D217)."""

    width: int
    height: int
    places: int  # places blacked out, over every text of the card
    redactions: list[SocialRedaction]  # by category, in the order of RedactionKind
    lines: int  # lines of the text the card shows
    truncated: bool  # the text does not fit the format and is cut


# Attachments and documents (milestone 9, D70 to D77) -----------------------------------------
#
# A document is one distinct attachment content (D70); the list, its figures and the search
# read document rows, never the attachments one by one.

DocumentSort = Literal["recent", "oldest", "mails", "size"]  # first seen, newest or oldest first
DOCUMENT_NAMES_LIMIT = 20  # file names listed in DocumentDetail
DOCUMENT_PERSONS_LIMIT = 10  # senders and recipients listed in DocumentDetail
SNIPPET_LENGTH = 240  # characters of DocumentListItem.snippet
PASSWORD_LENGTH = 128  # characters of a typed-in password (passwords.candidates)


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
    # What the file says about itself (D167): any of these values, exact (MetadataSummary.author
    # and .software as stored); empty: all.
    author: list[str] = []
    program: list[str] = []
    protection: list[DocumentProtection] = []  # any of these (D233); empty: all
    text_origin: list[TextOrigin] = []  # where its text comes from (D185, D189); empty: all
    ai_tag: list[int] = []  # a valid summary of it has each of these AI tags (D309)


class DocumentListParams(DocumentFilters):
    sort: DocumentSort = "recent"
    cursor: str | None = None  # next_cursor or prev_cursor of a DocumentPage with the same sort
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    # A jump instead of a cursor (D193), as in MailListParams.
    page: int | None = Field(default=None, ge=1)
    last: bool = False


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
    protection: DocumentProtection | None = None  # D233
    contained: bool = False  # it was found inside a container (D231)
    text_origin: TextOrigin = TextOrigin.EXTRACTED  # ocr: its text is machine made (D189)


class DocumentPage(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None
    prev_cursor: str | None
    page: int | None = None  # as MailPage.page (D193); DocumentSummary has the total


METADATA_VALUES_LIMIT = 20  # authors and programs in DocumentSummary and MetadataValues


class MetadataValueCount(BaseModel):
    value: str  # an author or a program as stored (MetadataSummary), as the file states it
    documents: int  # filtered documents with this value


class DocumentSummary(BaseModel):
    """Figures of the filtered document list under the count budget of D19."""

    total: int | None  # None: counting ran out of time
    exact: bool  # False: total is a lower bound
    kinds: dict[DocumentKind, int] | None  # every kind present; None: ran out of time
    text_status: dict[DocumentTextStatus, int] | None  # every status present
    # The most frequent authors and programs (D167), most documents first, at most
    # METADATA_VALUES_LIMIT each; None: ran out of time.
    authors: list[MetadataValueCount] | None = None
    programs: list[MetadataValueCount] | None = None
    protection: dict[DocumentProtection, int] | None = None  # every protection, 0 if none (D233)
    # Of them, those OCR can read (ai.queue.OCR_READABLE), logos included: what "Für KI vormerken"
    # would queue at most (D186); None: ran out of time.
    ocr_readable: int | None = None


class DocumentNameCount(BaseModel):
    name: str
    attachments: int  # attachments with this file name, duplicates included


class PersonCount(BaseModel):
    person: PersonRef  # a root person; name is its display name
    mails: int  # mails carrying the document that it sent, or received


# A metadata value as found (attachments.metadata.model): a text, a count, a number (GPS) or a
# list of texts.
MetadataValue = str | int | float | list[str]


class DocumentMetadata(BaseModel):
    """What the file says about itself (D167), every field as found and never rated, grouped by
    where it stands in the file (attachments.metadata.model: exif, gps, xmp, png, pdf,
    pdf_custom, office, office_custom, odf, odf_custom), each source with stable English keys
    (png and the *_custom sources keep the file's own). Dates are ISO 8601 with the offset the
    file gives, or without one when it gives none; a date that could not be read is the text as
    found."""

    status: DocumentMetadataStatus  # pending: not read yet (the next import's metadata step)
    error: str | None  # English, technical: why it failed, or the part found damaged
    fields: dict[str, dict[str, MetadataValue]]  # source -> key -> value; {} without any
    summary: MetadataSummary | None  # the values the list filters by; None without fields


# Protected and packed attachments (milestone 19, D230 to D239) ------------------------------


class DocumentRef(BaseModel):
    id: int
    name: str | None


class PasswordFinding(BaseModel):
    """Where a password stands (D208): in a mail, in a document's text, or typed in by hand."""

    id: int
    context: str  # the line(s) around it, as written
    mail: ThreadMail | None  # the mail it was found in
    recipients: list[PersonRef] = []  # that mail's To, at most RECIPIENT_PREVIEW
    document: DocumentRef | None = None  # the document whose text holds it
    editor: str | None = None  # typed in by hand by this editor (D237)
    created_at: datetime


class DocumentPassword(BaseModel):
    """The password that opened a document (D236), in plain text as evidence (D208)."""

    value: str
    tier: PasswordTier  # where it was found, nearest first (D235)
    found_at: datetime
    found_by: str | None  # the editor who typed it in (tier typed)
    finding: PasswordFinding | None  # where it was found; None when that is not known


class DocumentMember(BaseModel):
    """One entry of a container (D231)."""

    position: int
    path: str
    size: int | None  # unpacked, as declared or read
    status: DocumentMemberStatus  # document: it became a member document
    error: str | None  # English, technical
    document_id: int | None  # the member document, once finalize assigned it
    kind: DocumentKind | None = None
    text_status: DocumentTextStatus | None = None
    protection: DocumentProtection | None = None


class DocumentMembers(BaseModel):
    status: DocumentMembersStatus | None  # None: not unpacked yet (the next import's archives)
    error: str | None  # English, technical: why it failed, or the entries not listed
    entries: list[DocumentMember]  # in the container's order


class DocumentContainerRef(BaseModel):
    document_id: int  # the container document
    name: str | None
    path: str  # where the document sits in it


class PasswordTry(BaseModel):
    # as typed; white space around it is left out (passwords hold none, D234)
    password: str = Field(min_length=1, max_length=PASSWORD_LENGTH, pattern=r"\S")


class PasswordTryResult(BaseModel):
    tried: int  # locked documents the password was tried on
    opened: list[int]  # the documents it opened, now open with their text; a container is
    # unpacked by the next import, an opened document's metadata read by it too
    errors: int = 0  # documents that could not be read or tried (missing MBOX file, damage)


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
    metadata: DocumentMetadata  # what the file says about itself (D167)
    # Protection (D233 to D237). password_trial: a password can be tried on it (PDF, OOXML, ZIP,
    # 7z; not ODF, D239). password_tries: passwords tried on it by the imports, last at
    # password_tried_at. password: the one that opened it, with where it was found.
    protection: DocumentProtection | None = None
    password_trial: bool = False
    password_tries: int = 0
    password_tried_at: datetime | None = None
    password: DocumentPassword | None = None
    members: DocumentMembers | None = None  # a container's entries (D231); None otherwise
    containers: list[DocumentContainerRef] = []  # where it was found inside (D231)
    text_origin: TextOrigin = TextOrigin.EXTRACTED  # D185
    ai: "DocumentAi | None" = None  # its OCR result and open task (D189); None without either
    ocr_readable: bool = False  # OCR can read it (ai.queue.OCR_READABLE): "Text erkennen"


class DocumentText(BaseModel):
    text: str  # the stored text, at most DOCUMENT_TEXT_LIMIT characters; "" without text
    truncated: bool  # the extraction stopped at the limit or the time limit
    text_status: DocumentTextStatus


class MailHitsParams(BaseModel):
    """The search of the mail list whose words GET /api/mails/{id}/hits looks for (D176)."""

    q: str = ""
    scope: list[SearchField] = []
    whole_word: bool = False
    body_part: BodyPart = "clean"  # D226


class AttachmentHit(BaseModel):
    attachment_id: int
    in_name: bool  # one of its document's file names holds a word
    # the text around the first place a word occurs, as typed or as a word one of the query's
    # stems begins; None: only the name holds it, or a form the stems do not begin (rare)
    snippet: str | None
    in_text: bool = False  # its document's text holds a word (D176)
    machine: bool = False  # that text was recognised by an AI run (D189)


class MailHits(BaseModel):
    """Where the full text words of a mail list's q occur in one mail (D79), in the places the
    search looks (D171); with whole_word only the words as written (D173)."""

    words: list[str]  # the words and phrases as typed, which the browser marks; [] without any
    stems: list[str]  # the lexemes of the query (German stems, lower case, no umlauts), ditto;
    # [] with whole_word, where the browser marks the words alone
    in_mail: bool  # the mail's own subject or text holds a word
    attachments: list[AttachmentHit]  # the attachments whose document holds a word, in mail order
    whole_word: bool = False  # mark whole words only (D173)
    in_subject: bool = False  # the subject holds a word (D176)
    in_body: bool = False  # the mail's own text holds a word
    counts: MailHitCounts | None = None  # as MailListItem.hits; None without full text words


class MetadataValueParams(DocumentFilters):
    """The authors or programs of the filtered documents whose value holds `search` (D167), for
    the search within a facet of the document list."""

    field: Literal["author", "program"]
    search: str = ""  # part of the value, any case; empty: every value
    limit: int = Field(METADATA_VALUES_LIMIT, ge=1, le=100)


class MetadataValues(BaseModel):
    """Under the count budget of D19."""

    values: list[MetadataValueCount] | None  # most documents first; None: ran out of time


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
    done: bool  # answered by the interrupted fetch a fetch over every domain continues (D107)


class KeyArchivePreview(BaseModel):
    """What "Schlüsselarchiv abfragen" would send, before anything is sent (D102)."""

    url: str | None  # the archive's base URL; None: switched off
    domains: list[ArchiveDomain]  # concerned domains, most mails first
    # Domains under reserved TLDs (.example, .test, ...) go only to an archive on this machine
    skipped: list[str]
    continues: datetime | None  # start of the interrupted fetch a new one goes on with (D107)


RUN_LIST_LIMIT = 1000  # names or domains one run request names; "every" needs no list (D107)


class DkimKeysRunRequest(BaseModel):
    task: DkimKeysTask
    # reconstruct, check: only these key names
    names: list[str] = Field([], max_length=RUN_LIST_LIMIT)
    domains: list[str] = Field([], max_length=RUN_LIST_LIMIT)  # fetch: only these domains
    # fetch without domains: every concerned domain but these
    skip_domains: list[str] = Field([], max_length=RUN_LIST_LIMIT)
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
    # A jump instead of a cursor (D193), as in MailListParams.
    page: int | None = Field(default=None, ge=1)
    last: bool = False


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
    page: int | None = None  # as MailPage.page (D193)
    # With q, detail or a value bound: the matching entities, counted under the count budget of
    # D19 (exact False: at least total; total None: even the bounded count ran out of time).
    # Without them total is None, as EntitySummary.kinds counts the list (D193).
    total: int | None = None
    exact: bool = False


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


# Signals (milestone 12, D130 to D139) ---------------------------------------------------------

# A signal is a simple condition that holds for a mail (D132) or a person (D134) and points to
# something worth reading; it rates nothing. Keys are SignalKind values and "term:<theme key>"
# per research theme (signals.model). Figures count the mails that are no duplicates, as of the
# last signals phase of an import (D135); filters and facets read mail_signal as it is.

SignalGroup = Literal["addresses", "recipients", "time", "attachments", "wording", "persons"]
SIGNAL_SENDERS = 5  # senders listed per signal in SignalOverview
SILENT_LISTED = 50  # persons fallen silent listed in SignalOverview
SIGNAL_DOMAINS = 10  # sender domains offered as a help for MAILROBBE_INTERNAL_DOMAINS


class SignalSettings(BaseModel):
    """The rules' settings as configured now (D131 to D133)."""

    internal_domains: list[str]  # MAILROBBE_INTERNAL_DOMAINS; empty: internal signals are off
    private_domains: int  # domains of private providers (themes.toml and MAILROBBE_PRIVATE_DOMAINS)
    timezone: str  # MAILROBBE_TIMEZONE, e.g. "Europe/Berlin"
    timezone_known: bool  # PostgreSQL knows it; otherwise the signals phase fails
    night_from: int  # night from this hour (local time) ...
    night_to: int  # ... up to before this one
    many_recipients: int  # many recipients: at least this many in To, Cc and Bcc together
    forward_prefixes: list[str]  # subject prefixes of a forward, without the colon


class SignalInfo(BaseModel):
    """One signal of a mail in the overview, with the figures of the last signals phase."""

    key: str
    group: SignalGroup
    theme: str | None  # term signals: the theme's name; None otherwise
    available: bool  # False: needs MAILROBBE_INTERNAL_DOMAINS, which is empty
    mails: int  # mails with it that are no duplicates
    persons: int  # root persons who sent such a mail
    senders: list[PersonCount]  # who sent most of them, at most SIGNAL_SENDERS


class SilentPerson(BaseModel):
    """A person fallen silent (D134): no mail from a month on, after steady activity."""

    person: PersonRef  # a root person; name is its display name
    since: datetime  # the first day (UTC) of its first month without mail
    mails: int  # its mails in the six months before


class SignalOverview(BaseModel):
    """The screen /auffaelligkeiten (D137)."""

    signals: list[SignalInfo]  # every signal of a mail under the current rules, display order
    settings: SignalSettings
    computed_at: datetime | None  # end of the last signals phase; None: none ran yet
    # The last phase applied other rules or word fields than the current ones: the next import
    # computes the signals again.
    outdated: bool
    mails: int  # mails that are no duplicates at the last phase, the base of every share
    silent: list[SilentPerson]  # most mails before their silence first, at most SILENT_LISTED
    silent_count: int
    # Without internal domains: the sender domains with most mails that are no private
    # provider, at most SIGNAL_DOMAINS, as a help for setting MAILROBBE_INTERNAL_DOMAINS.
    sender_domains: list[DomainCount]


class SignalFacets(BaseModel):
    """Mails per signal among the mails of a filter (D136), counted as EntityFacets count."""

    signals: dict[str, int]  # signals with mails only, display order
    mails: int | None  # mails counted over; None without filters (the last phase's figures)
    sampled: bool  # the filter matches more than FACET_MAILS mails


class SignalReason(BaseModel):
    """One signal of one mail and what makes it hold (D137)."""

    key: str
    group: SignalGroup
    theme: str | None  # term signals: the theme's name
    # The participants it concerns: the private addresses (private, private_alias), the
    # internal sender and private recipients (internal_to_private) or the other way round, the
    # Bcc recipients (bcc), the recipients outside (forward_out); empty otherwise.
    persons: list[PersonRef]
    # night, weekend: the mail's date in the configured time zone, ISO 8601 with its offset
    local_time: str | None
    recipients: int | None  # many_recipients: the distinct recipients in To, Cc and Bcc
    forward_prefix: str | None  # forward, forward_out: the subject's prefix as written ("WG")
    forwarded_mail: str | None  # forward, forward_out: an attached mail's file name ("" unnamed)
    terms: list[EntityRef]  # term signals: the theme's terms found in the mail or attachments
    # encrypted_attachment: the mail's protected documents; password_separate: the documents of
    # other mails its password opened (D238); empty otherwise.
    documents: list[DocumentRef] = []


class MailSignals(BaseModel):
    signals: list[SignalReason]  # display order
    timezone: str  # of local_time
    computed_at: datetime | None  # end of the last signals phase; None: none ran yet


class PersonSignalCount(BaseModel):
    key: str
    group: SignalGroup
    theme: str | None
    mails: int  # mails it or one of its aliases sent with the signal, no duplicates
    archive_share: float | None  # the archive's share of mails with it; None before a phase


class PersonSignals(BaseModel):
    """The signals of a person's sent mails and whether it fell silent (D134, D137); counted
    on request, so merges count at once."""

    sent: int  # mails it or one of its aliases sent, no duplicates
    signals: list[PersonSignalCount]  # signals with mails only, display order
    silent_since: datetime | None  # D134 over its mails in any role; None: not silent
    silent_mails: int | None  # its mails in the six months before


# Standard blocks (milestone 18, D224 to D227) --------------------------------------------------

# Which blocks the list shows: those applied, or those detected and taken back by the team.
BlockState = Literal["standard", "dismissed"]
BlockSort = Literal["mails", "recent"]  # most mails first, latest occurrence first
BLOCK_SAMPLE_LIMIT = 2_000  # characters of BlockInfo.sample
BLOCK_SENDERS = 50  # senders and domains of BlockDetail


class BlockInfo(BaseModel):
    hash: str
    sample: str  # one occurrence as written, at most BLOCK_SAMPLE_LIMIT characters
    standard: bool  # applied by the last blocks step
    detected: bool  # by the rule of D225; False: marked by hand
    override: bool | None  # the team's choice (True marked, False taken back); None: none
    pending: bool  # the choice differs from what the last blocks step applied
    mails: int  # mails holding it, duplicates left out
    senders: int  # distinct sender addresses of those
    first_date: datetime | None
    last_date: datetime | None


class BlockListParams(BaseModel):
    state: BlockState = "standard"
    q: str = ""  # part of the sample, any case
    sort: BlockSort = "mails"
    offset: int = Field(0, ge=0)
    limit: int = Field(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class BlockPage(BaseModel):
    items: list[BlockInfo]
    total: int


class BlockSummary(BaseModel):
    """Figures of the last blocks step and of the team's choices (global_stats 'blocks')."""

    blocks: int  # standard blocks applied
    detected: int  # of these, by the rule
    marked: int  # of these, by hand
    dismissed: int  # detected and taken back
    pending: int  # choices the next run applies
    mails: int  # mails holding at least one standard block
    waiting: int  # mails the paragraphs step has not split yet
    min_mails: int  # MAILROBBE_BLOCK_MIN_MAILS (D225)
    computed_at: datetime | None  # end of the last blocks step; None: never ran


class BlockSender(BaseModel):
    person: PersonRef
    mails: int


class BlockDetail(BaseModel):
    block: BlockInfo
    senders: list[BlockSender]  # most mails first, at most BLOCK_SENDERS
    domains: list[DomainCount]  # sender domains, most mails first, at most BLOCK_SENDERS


class BlockOverrideUpdate(BaseModel):
    """The team's choice (D225): True marks a paragraph as a standard block, False takes a
    detected one back, None removes the choice. sample is the paragraph as shown; it is needed
    when the blocks step has not counted the paragraph, and must have this hash."""

    standard: bool | None
    sample: str | None = None


# Places (milestone 20, D240 to D249) ---------------------------------------------------------

PHOTO_POINT_LIMIT = 20_000  # photos PhotoPoints draws at most (D248)
TEXT_PLACE_LIMIT = 2_000  # places TextPlaces and EventPlaces draw at most
PHOTO_MAILS_LIMIT = 20  # mails a PhotoDetail lists, earliest first
PHOTO_LIST_LIMIT = 200  # photos a PhotoList lists at most
PLACE_LOCATIONS_LIMIT = 5  # locations as written per EventPlace
PLACE_EVENTS_LIMIT = 10  # events per EventPlace
DEVICE_LIMIT = 200  # devices in PlaceSummary, most photos first
RADIUS_LIMIT_KM = 200.0  # the largest radius of "Fotos im Umkreis"
# A compass direction in German (N, NO, O, SO, S, SW, W, NW): from the nearest town towards the
# photo.
CompassDirection = Literal["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
PlaceDetailKind = Literal["city", "country"]  # entity.detail of a place (D81)


class PlaceParams(MailFilters):
    """The map's filters (D247): a photo shows when one mail carrying it meets the mail
    filters, a place when mails meeting them mention it, an invitation's place when its mail
    meets them; and the photo's own capture time (D241) and device."""

    taken_from: date | None = None  # UTC day of the capture time, inclusive; photos without a
    taken_to: date | None = None  # capture time never match either
    device: str | None = None  # the photo's device (metadata_device) exactly


class PhotoPoint(BaseModel):
    id: int  # document id
    lat: float
    lon: float


class PhotoPoints(BaseModel):
    points: list[PhotoPoint]  # by document id, at most PHOTO_POINT_LIMIT
    total: int  # photos matching
    truncated: bool  # total is above PHOTO_POINT_LIMIT


class PlaceMail(BaseModel):
    id: int
    date: datetime | None
    subject: str | None
    sender: PersonRef | None
    recipients: list[PersonRef]  # To, then Cc, then Bcc; at most RECIPIENT_PREVIEW
    recipient_count: int


class NearestTown(BaseModel):
    """The town of the shipped lists nearest to a photo (D248), within 50 km."""

    name: str
    region: str | None  # Bundesland, Kanton
    country: str  # ISO 3166-1 alpha-2
    distance_km: float
    direction: CompassDirection | None  # None within 0.5 km of the town


class PhotoDetail(BaseModel):
    """GET /api/places/photos/{id}: one document with a position (D248)."""

    document_id: int
    attachment_id: int  # the occurrence /api/attachments/{id}/content reads it from
    name: str | None
    mime_type: str
    preview: PreviewKind | None  # image: the browser shows it (D120)
    latitude: float
    longitude: float
    altitude: float | None  # metres, below sea level negative
    taken_at: datetime | None  # the capture time (D241), UTC
    taken_text: str | None  # the capture time as found when the file gives no zone
    device: str | None
    nearest: NearestTown | None
    mails: list[PlaceMail]  # the mails carrying it, earliest first, at most PHOTO_MAILS_LIMIT;
    mail_count: int  # duplicates and hidden mails included (D222: the detail shows everything)


class PhotoListParams(PlaceParams):
    """The photos around a point (lat and lon, nearest first) or, without a point, every photo
    matching the filters by capture time, earliest first (with device: one device's photos)."""

    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=2.0, gt=0, le=RADIUS_LIMIT_KM)
    limit: int = Field(default=50, ge=1, le=PHOTO_LIST_LIMIT)


class PhotoListItem(BaseModel):
    document_id: int
    attachment_id: int
    name: str | None
    latitude: float
    longitude: float
    taken_at: datetime | None
    device: str | None
    distance_km: float | None  # from the point; None without one
    first_mail: PlaceMail | None  # the earliest mail carrying it that meets the filters


class PhotoList(BaseModel):
    items: list[PhotoListItem]
    total: int  # photos matching
    truncated: bool  # total is above limit


class TextPlace(BaseModel):
    entity_id: int
    label: str  # as the texts write it (entity.label)
    place: str  # what the point stands for (entity.place_label)
    detail: PlaceDetailKind
    lat: float
    lon: float
    mails: int  # mails meeting the filters that mention it (of the sample when not exact)


class TextPlaces(BaseModel):
    places: list[TextPlace]  # most mails first, at most TEXT_PLACE_LIMIT
    total: int  # places with a point mentioned by the mails counted
    exact: bool  # False: counted over FACET_MAILS of the matching mails (D87)


class PlaceEvent(BaseModel):
    event_id: int
    mail_id: int
    kind: EventKey
    summary: str | None
    location: str | None  # as written
    starts_at: datetime | None  # UTC; None when the zone is unknown
    starts_local: datetime | None  # as written, without a zone
    all_day: bool
    uid: str | None


class EventPlace(BaseModel):
    lat: float
    lon: float
    place: str  # what the point stands for
    locations: list[str]  # the locations as written, most events first, at most
    events: int  # events at this point whose mail meets the filters
    first: datetime | None  # the earliest and latest start (starts_at) of those
    last: datetime | None
    samples: list[PlaceEvent]  # the latest ones, at most PLACE_EVENTS_LIMIT


class EventPlaces(BaseModel):
    places: list[EventPlace]  # most events first, at most TEXT_PLACE_LIMIT
    total: int  # points with events


class PlaceCounts(BaseModel):
    """What the places step found for place entities or invitation locations (D242, D243)."""

    found: int
    ambiguous: int
    unknown: int
    waiting: int  # not looked at yet: the next import run's step places


class DeviceCount(BaseModel):
    device: str
    photos: int


class PlaceSummary(BaseModel):
    photos: int  # documents with a position
    photos_dated: int  # of those, with a capture time
    devices: list[DeviceCount]  # most photos first, at most DEVICE_LIMIT
    texts: PlaceCounts  # place entities
    events: PlaceCounts  # calendar events with a location
    outdated: bool  # the lists or rules changed since the last step places (D242)
    computed_at: datetime | None  # end of the last step places; None: never ran


class TownLabel(BaseModel):
    """A town the overview map labels (D244)."""

    name: str
    lat: float
    lon: float
    population: int
    country: str  # ISO 3166-1 alpha-2
    capital: bool


class MapRegionInfo(BaseModel):
    key: MapRegionKey  # a preset region, never view
    bbox: BBox  # west, south, east, north
    sizes: dict[MapDetailKey, int]  # bytes of each detail on the build of size_hints_build


class MapDetailInfo(BaseModel):
    key: MapDetailKey
    max_zoom: int


class DetailMap(BaseModel):
    """The detail map in MAILROBBE_MAP_DIR (D245)."""

    url: str  # /api/map/tiles/<file>, which the browser reads by range requests
    region: MapRegionKey
    bbox: BBox
    detail: MapDetailKey
    max_zoom: int
    build: str | None  # the Protomaps build, e.g. "20261022"; None for another source
    source_url: str  # the PMTiles file it was taken from
    size: int  # bytes of the file
    tiles: int
    downloaded_at: datetime


class MapPartial(BaseModel):
    """A download that stopped: the next run with the same options continues it (D246)."""

    region: MapRegionKey
    bbox: BBox
    detail: MapDetailKey
    build: str | None
    bytes_done: int
    bytes_total: int


class MapJob(JobInfo):
    """A run of `mailrobbe map download` (D246)."""

    phase: MapPhase | None
    options: MapOptions
    progress: MapProgress


class MapStatus(BaseModel):
    offered: bool  # MAILROBBE_MAP_SOURCE is not off
    source_host: str | None  # the host a download asks (build.protomaps.com); None when off
    detail_map: DetailMap | None
    partial: MapPartial | None
    regions: list[MapRegionInfo]  # in the order of places.model.REGIONS
    details: list[MapDetailInfo]
    size_hints_build: str  # the Protomaps build the sizes were measured on
    free_bytes: int | None  # free space in MAILROBBE_MAP_DIR; None when it cannot be told
    job: MapJob | None  # the latest map run; None before the first


class MapDownloadRequest(BaseModel):
    region: MapRegionKey
    detail: MapDetailKey
    bbox: BBox | None = None  # region view: the map's view, west below east; else not given


# AI services (milestone 15, D180 to D189) ----------------------------------------------------
#
# The services are configured in the .env only (D180); the status shows them as configured,
# without asking them, and the check asks one and runs its real test. The queue holds a
# selection, never the whole archive (D186); a run of kind ai works it through (D187).

AiWorkList = Literal["scanned", "images"]  # ai.queue.WorkList
AiPhase = Literal["check", "ocr", "summarize", "entities", "signals"]  # ai.model.AI_STEPS
AI_QUEUE_LIMIT = 50_000  # documents one request may queue (D186)
AI_PAGE_SIZE = 50  # default page of the task, result and send log lists
# Seconds per page without a measurement (D188); an image counts as one page.
AI_RULE_SECONDS: dict[OcrEngine, float] = {"tesseract": 4.0, "vision": 40.0}


class AiServiceInfo(BaseModel):
    """One configured service as the settings name it (D180, D181), not asked."""

    capability: Capability
    url: str  # display_url: without credentials, query and fragment
    model: str  # MAILROBBE_AI_<CAPABILITY>_MODEL; "" when not set
    protocol: Protocol | Literal["auto"]  # the setting; the check says what was detected
    locality: Locality | None  # None: the URL can never name a service (refused says why)
    refused: str | None  # English, one line: why the settings forbid it (ai.model.refusal)
    key: bool  # a key is set (never shown)


class AiEstimate(BaseModel):
    """How long a selection takes with one engine (D188)."""

    engine: OcrEngine
    model: str  # the vision model; "" for Tesseract
    seconds: float
    # True: by the rule of thumb (AI_RULE_SECONDS), "geschätzt"; False: from ai_calibration
    estimated: bool
    seconds_per_page: float


class AiWorkListInfo(BaseModel):
    """A work list of the AI page (D186): what is still without a valid OCR result."""

    key: AiWorkList
    documents: int
    pages: int  # pages known; an image counts as one
    without_pages: int  # documents whose pages are not known, one page each in the estimate
    bytes: int
    # One per engine at hand (Tesseract always, the vision model when one is usable), for at
    # most max_pages of the defaults per document.
    estimates: list[AiEstimate]
    engine: OcrEngine  # the engine "auto" takes for this list (D182)


class AiJob(JobInfo):
    """A run of `mailrobbe ai run` (D187)."""

    phase: AiPhase | None
    options: AiOptions
    progress: AiProgress


class AiStatus(BaseModel):
    """What the AI page polls: every 2 s while a run is alive, else rarely (D48)."""

    # OCR is always possible: Tesseract runs in the server's container; vision says whether a
    # vision model is configured and allowed besides.
    enabled: bool
    vision: bool
    tesseract: bool  # the tesseract program is installed where the server runs
    ocr_languages: str  # MAILROBBE_AI_OCR_LANGUAGES
    services: list[AiServiceInfo]  # every configured one, by capability
    allow_remote: bool  # MAILROBBE_AI_ALLOW_REMOTE (D181)
    remote_token_budget: int  # MAILROBBE_AI_REMOTE_TOKEN_BUDGET
    ocr_engine: OcrEngineChoice  # MAILROBBE_AI_OCR_ENGINE
    queue: dict[AiTaskKind, dict[AiTaskStatus, int]]  # every kind and status present
    work_lists: list[AiWorkListInfo]  # scanned, then images
    # The send log has entries, or a configured service is remote: the page shows "Gesendet".
    remote_used: bool
    job: AiJob | None  # the latest AI run; None before the first
    defaults: AiOptions  # the options of the latest run, or the settings' before the first (D49)
    # A text service is configured and allowed (D300): "Zusammenfassen" shows, else a hint.
    text: bool = False


class AiQueueRequest(BaseModel):
    """What to queue: for OCR exactly one of work_list, document_ids and filters (D186); for
    summarize exactly one of mail_ids, mail_filters, document_ids and filters (D308)."""

    work_list: AiWorkList | None = None
    document_ids: list[int] | None = Field(default=None, max_length=AI_QUEUE_LIMIT)
    filters: DocumentFilters | None = None  # the document list's, resolved by its own SQL
    engine: OcrEngineChoice = "auto"
    include_logos: bool = False  # images in more than LOGO_MAILS mails too
    single: bool = False  # one document from its page: first in the queue, a logo too
    # With document_ids or mail_ids: start a run for only these at once (D280, D307); with
    # filters or mail_filters (summarize only): start a run for the whole queue unless an AI run
    # is alive (D308).
    start: bool = False
    # Only this kind of task; None: what fits each document (OCR). Summaries are asked for by
    # name (D308); 400 invalid_option for a kind the selection cannot have.
    kind: AiTaskKind | None = None
    mail_ids: list[int] | None = Field(default=None, max_length=AI_QUEUE_LIMIT)
    mail_filters: MailFilters | None = None  # the mail list's; an Akte is collection=[id]
    # Nothing is queued: AiQueued says how many would be and, for summarize, how long (D308).
    preview: bool = False


# What start did (D280): a run for these documents began; an AI run is alive already and takes
# them next (single puts them first); another run (an import) keeps it from starting, so they
# wait in the queue.
AiQueuedRun = Literal["started", "running", "busy"]


class AiQueued(BaseModel):
    """What queuing did (ai.queue.Queued)."""

    queued: int  # new tasks
    raised: int  # already open: priority and engine updated
    unreadable: int  # not readable by OCR: a text of its own, no SHA-256, unknown id
    logos: int  # images in more than LOGO_MAILS mails, left out
    run: AiQueuedRun | None = None  # with start, None without
    # Summaries (D302, D308): mails among them with less own text than SUMMARY_MIN_WORDS (tags
    # and theme hints only), and how long the queued (with preview: the queueable) ones take.
    short: int = 0
    estimate: "AiTextEstimate | None" = None


class AiTextEstimate(BaseModel):
    """How long summarising a selection takes (D188, D308): per task and per 1,000 tokens of
    input, measured for the model (ai_calibration, unit ktoken) or by the rule of thumb."""

    model: str  # the text model; "" when none is set
    tasks: int
    tokens: int  # of the input, estimated from its characters (CHARS_PER_TOKEN)
    seconds: float
    estimated: bool  # True: by SUMMARY_RULE_SECONDS_*, "geschätzt"


class AiDocumentRef(BaseModel):
    """The document a task, result or send is about, by its content."""

    id: int
    name: str | None
    kind: DocumentKind | None
    pages: int | None


class AiMailRef(BaseModel):
    """The mail a task, result or send is about, by its content (the earliest such mail)."""

    id: int
    subject: str | None
    date: datetime | None


class AiTaskParams(BaseModel):
    status: list[AiTaskStatus] = []  # any of these; empty: all
    cursor: str | None = None  # next_cursor of an AiTaskPage with the same status
    limit: int = Field(AI_PAGE_SIZE, ge=1, le=200)


class AiTaskItem(BaseModel):
    id: int
    kind: AiTaskKind
    document: AiDocumentRef | None  # None: no document has the content any more
    engine: OcrEngineChoice
    priority: int
    status: AiTaskStatus
    attempts: int
    error: str | None  # English, one line
    queued_by: str | None  # D54
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    pages_read: int  # pages of ai_task.partial, kept across a stop (D187)
    pages_total: int | None
    result_id: int | None
    target: AiTarget = AiTarget.DOCUMENT  # D301: document or mail names it
    mail: AiMailRef | None = None  # None: a document's task, or no mail has the content any more


class AiTaskPage(BaseModel):
    items: list[AiTaskItem]
    next_cursor: str | None


class AiTaskAction(BaseModel):
    """Retry or cancel: these tasks, or with all every one the action applies to."""

    ids: list[int] = Field(default=[], max_length=AI_QUEUE_LIMIT)
    all: bool = False


class AiChanged(BaseModel):
    changed: int  # tasks put back or taken off, results discarded


class AiResultParams(BaseModel):
    state: list[AiResultState] = []  # any of these; empty: all
    job_id: int | None = None  # of this run only
    cursor: str | None = None
    limit: int = Field(AI_PAGE_SIZE, ge=1, le=200)


class AiResultItem(BaseModel):
    """One ai_result (D185), without its text."""

    id: int
    kind: AiTaskKind
    document: AiDocumentRef | None
    engine: str  # tesseract, vision or mixed
    model: str | None
    remote: bool
    pages_read: int  # pages it holds, failed ones included
    pages_text: int  # of them, pages with writing
    pages_total: int | None
    uncertain: list[int]  # page numbers marked uncertain (D184)
    failed: list[int]  # page numbers that failed and were skipped
    characters: int  # of its text
    seconds: float
    state: AiResultState
    created_at: datetime
    job_id: int | None
    discarded_by: str | None
    discarded_at: datetime | None
    target: AiTarget = AiTarget.DOCUMENT  # D301
    mail: AiMailRef | None = None
    # A summary (D300): characters is its length, pages_read and pages_total its parts.
    tags: int = 0
    themes: int = 0


class AiResultPage(BaseModel):
    items: list[AiResultItem]
    next_cursor: str | None


class AiSendLogParams(BaseModel):
    cursor: str | None = None
    limit: int = Field(AI_PAGE_SIZE, ge=1, le=200)


class AiSendItem(BaseModel):
    """One request to a service outside the own machine and network (D181)."""

    id: int
    sent_at: datetime
    service_url: str  # without credentials
    kind: AiTaskKind
    document: AiDocumentRef | None
    bytes: int
    job_id: int | None
    target: AiTarget = AiTarget.DOCUMENT  # D301
    mail: AiMailRef | None = None


class AiSendLogPage(BaseModel):
    items: list[AiSendItem]
    next_cursor: str | None
    total: int


class AiRunRequest(BaseModel):
    """A start of `mailrobbe ai run` from the AI page; what is left out comes from the defaults
    (D49)."""

    engine: OcrEngineChoice | None = None  # for tasks queued with auto
    vision_model: str | None = Field(default=None, max_length=200)
    max_pages: int | None = Field(default=None, ge=1, le=10_000)
    text_model: str | None = Field(default=None, max_length=200)  # summaries (D300)


class DocumentAiResult(BaseModel):
    """The valid OCR result of a document's content, as its text card names it (D189)."""

    id: int
    engine: str  # tesseract, vision or mixed
    model: str | None
    remote: bool
    created_at: datetime
    pages_total: int | None
    pages_read: int
    pages_text: int
    uncertain: list[int]
    failed: list[int]
    characters: int  # 0: no writing found


class DocumentAiTask(BaseModel):
    """The open OCR task of a document's content: vorgemerkt or läuft."""

    id: int
    status: AiTaskStatus  # waiting or running
    engine: OcrEngineChoice
    pages_read: int


class DocumentAi(BaseModel):
    result: DocumentAiResult | None
    task: DocumentAiTask | None


# Summaries and AI tags (milestone 17, D300 to D311) ------------------------------------------
#
# A summary is a valid ai_result of kind summarize for a mail (by raw_sha256) or a document (by
# sha256); its tags and theme hints hang on it and leave every view with it (D306). Everything
# here is "maschinell erzeugt" (D311): the UI says so with model and date wherever it shows.


AI_FACET_TAGS = 20  # AI tags in AiFacets


class AiSummaryParams(BaseModel):
    """Exactly one of mail and document."""

    mail: int | None = None
    document: int | None = None


class AiTagCount(BaseModel):
    """An AI tag with the mails it describes: those whose own summary or whose attachment's
    document's summary has it (D309), duplicates included."""

    id: int
    label: str
    mails: int


class AiSummaryTheme(BaseModel):
    theme: str  # the key of themes.toml
    label: str  # the theme's name there
    quote: str  # as it stands in the text
    position: int | None  # character offset in the text the summary read; None: in its head


class AiSummaryResult(BaseModel):
    """One valid summary (D307)."""

    id: int  # ai_result.id: "Verwerfen" is POST /api/ai/results/{id}/discard
    target: AiTarget
    summary: str  # "" when short (or the model found nothing to say)
    short: bool  # own text below SUMMARY_MIN_WORDS: tags and theme hints only (D302)
    tags: list[AiTagCount]
    themes: list[AiSummaryTheme]
    parts_read: int  # parts of the text summarised
    parts_total: int  # more than parts_read: only the first ones (D303)
    origin: TextOrigin | None  # a document's text it read: extracted, ocr or transcript
    model: str | None
    remote: bool  # made by a service outside this machine (D181)
    prompt_version: int | None
    created_at: datetime


class AiSummaryTask(BaseModel):
    """The open summarize task of the element: vorgemerkt or läuft."""

    id: int
    status: AiTaskStatus  # waiting or running
    parts_done: int  # parts of a long text summarised so far
    parts_total: int | None


class AiAttachmentSummary(BaseModel):
    """The summary of one of a mail's attachments, by its document."""

    document_id: int
    name: str | None
    result: AiSummaryResult


class AiSummaryView(BaseModel):
    """What the card "KI-Zusammenfassung" shows (D307); asked again every 3 s while task is open."""

    available: bool  # a text service is configured and allowed (AiStatus.text)
    # The element has something to summarise: a mail with a subject or text, a document with a
    # SHA-256 and a text (extracted, recognised or transcribed).
    summarizable: bool
    result: AiSummaryResult | None
    task: AiSummaryTask | None
    failed: str | None  # the latest task failed with this reason (English) and none is open
    attachments: list[AiAttachmentSummary]  # a mail's attachments with a summary; [] else


class AiFacetTheme(BaseModel):
    key: str
    label: str
    mails: int


class AiFacets(BaseModel):
    """AI tags and themes among the mails of a filter (D309), counted as EntityFacets count."""

    tags: list[AiTagCount]  # most mails first, at most AI_FACET_TAGS
    themes: list[AiFacetTheme]  # in the order of themes.toml, themes with mails only
    mails: int | None  # mails counted over; None without filters (the whole archive)
    sampled: bool  # the filter matches more than FACET_MAILS mails


class AiTagParams(BaseModel):
    id: list[int] = []  # these AI tags; empty: by q
    q: str = ""  # part of the label, any case
    limit: int = Field(FACET_LIMIT, ge=1, le=MAX_FACET_LIMIT)


class AiTagAdopt(BaseModel):
    """Which mails get the team tag (D310): one mail, the mails of a filter that carry the AI
    tag, or without either every mail carrying it. Never more than BULK_LIMIT mails."""

    mail_id: int | None = None
    filters: MailFilters | None = None


class AiTagAdopted(BaseModel):
    tag_id: int  # the team tag (tag.id), found by its name or made with it
    created: bool  # the team tag was made now
    mails: int  # mails it was added to now (those that had it already not counted)


AiQueued.model_rebuild()


ImportStatus.model_rebuild()
DocumentDetail.model_rebuild()

// The HTTP contract of the backend, mirrored by hand from src/mailrobbe/api/schemas.py.
// Change both together. Times are ISO 8601 strings in UTC.

export const COUNT_LIMIT = 10_000;
export const PAGE_SIZE = 50;
export const RECIPIENT_PREVIEW = 3;
export const NOTE_LIMIT = 10_000;

/** consistent: verified only with a reconstructed key, which binds it to no domain (D100). */
export type DkimStatus = "pass" | "consistent" | "fail" | "no_key" | "unsigned" | "temp_error";
/** Filter and count keys: the statuses plus "unchecked" for mails not checked yet. */
export type DkimKey = DkimStatus | "unchecked";
export type DkimCounts = Record<DkimKey, number>;

export type DkimReason =
  | "body_hash_mismatch"
  | "signature_mismatch"
  | "signature_malformed"
  | "unsupported_algorithm"
  | "from_not_signed"
  | "key_malformed"
  | "key_too_short"
  | "message_malformed"
  | "key_not_found"
  | "key_revoked"
  | "key_mismatch"
  | "dns_timeout"
  | "dns_offline";

export type ParticipationRole = "from" | "to" | "cc" | "bcc";
/** Tabs of a person's mail list: sent = From; received = To, Cc or Bcc but not From;
 *  cc = Cc only. */
export type PersonRole = "sent" | "received" | "cc";
export type PersonSort = "mails" | "name" | "recent";
export type MboxStatus = "pending" | "running" | "paused" | "done" | "error";
export type SortOrder = "date_desc" | "date_asc";
/** Review status of a mail (D55); null is unreviewed. */
export type ReviewStatus = "seen" | "relevant" | "irrelevant";
/** Filter and count keys: the statuses plus "unreviewed" for mails without one. */
export type ReviewKey = "unreviewed" | ReviewStatus;
/** Tag colours (D57); lib/research.ts maps them to colour pairs. */
export type TagColor = "blue" | "teal" | "green" | "amber" | "red" | "pink" | "violet" | "gray";

export type QueryKey =
  | "text"
  | "from"
  | "to"
  | "cc"
  | "subject"
  | "domain"
  | "has"
  | "dkim"
  | "before"
  | "after"
  | "message_id";

export type ErrorCode =
  | "not_found"
  | "invalid_query"
  | "invalid_cursor"
  | "invalid_filter"
  | "no_html"
  | "source_missing"
  | "source_changed"
  | "invalid_merge"
  | "graph_too_large"
  | "job_running"
  | "no_job"
  | "mbox_dir_missing"
  | "invalid_option"
  | "job_failed"
  | "duplicate_name"
  | "invalid_selection"
  | "empty_selection"
  | "too_many_mails"
  | "ambiguous_permalink"
  | "invalid_key" // 400: no DKIM key name, or a record without a usable key (D103)
  | "archive_off"; // 409: the key archive is switched off

/** Body of every contract error: {"detail": ApiErrorDetail}. */
export interface ApiErrorDetail {
  code: ErrorCode;
  message: string;
}

// Query parameters ----------------------------------------------------------------------------

/** Filters of the mail list; every given one must hold. Lists repeat the parameter. */
export interface MailFilters {
  q?: string;
  dkim?: DkimKey[];
  sender_domain?: string[];
  date_from?: string; // YYYY-MM-DD, UTC day, inclusive
  date_to?: string; // YYYY-MM-DD, UTC day, inclusive
  has_attachment?: boolean;
  in_thread?: boolean;
  hide_duplicates?: boolean;
  external?: boolean;
  flagged?: boolean;
  mbox_file?: number;
  person?: number[];
  between?: number[]; // exactly two person ids
  person_role?: PersonRole; // role of the one person in `person`
  review?: ReviewKey[]; // any of these review statuses (D55)
  tag?: number[]; // carries any of these tags
  collection?: number[]; // in any of these Akten
  has_note?: boolean;
  document?: number; // one of the mail's attachments is this document (D75)
}

export interface MailOrderParams extends MailFilters {
  sort?: SortOrder;
}

export interface MailListParams extends MailOrderParams {
  cursor?: string;
  limit?: number;
}

// Mail list -------------------------------------------------------------------------------------

export interface PersonRef {
  person_id: number;
  email: string;
  name: string | null;
}

export interface QueryTerm {
  key: QueryKey;
  value: string;
  raw: string; // exact substring of q; removing it from q removes the term
}

export interface MailListItem {
  id: number;
  date: string | null;
  subject: string | null;
  dkim_status: DkimStatus | null;
  has_attachments: boolean;
  sender: PersonRef | null;
  recipients: PersonRef[];
  recipient_count: number;
  thread_id: number | null;
  is_duplicate: boolean;
  flagged: boolean;
  size: number;
  mbox_file_id: number;
  /** With exactly one person filtered for: its first role in the mail, else null. */
  person_role: ParticipationRole | null;
  review: ReviewStatus | null;
  tags: number[]; // tag ids, by tag name
  notes: number;
  /** q has full text words and the text of one of its attachments matches them (D73). */
  attachment_match: boolean;
}

export interface MailPage {
  items: MailListItem[];
  next_cursor: string | null;
  prev_cursor: string | null;
  query_terms: QueryTerm[];
}

export interface MailSummary {
  total: number | null; // null: unknown
  exact: boolean; // false: total is a lower bound
  dkim: DkimCounts | null;
  persons: number | null;
  domains: number | null;
  date_min: string | null;
  date_max: string | null;
}

export interface MailNeighbors {
  prev_id: number | null;
  next_id: number | null;
  position: number | null;
}

// Stats and files -------------------------------------------------------------------------------

export interface DomainCount {
  domain: string;
  mails: number;
}

export interface ImportState {
  running: boolean;
  files_total: number;
  files_done: number;
  progress: number; // 0 to 1
}

export interface Stats {
  mails: number;
  persons: number;
  domains: number;
  date_min: string | null;
  date_max: string | null;
  dkim: DkimCounts;
  sender_domains: DomainCount[];
  sender_domain_count: number;
  mbox_files: number;
  internal_domains: string[];
  importer: ImportState;
  updated_at: string | null;
}

export interface MboxFileInfo {
  id: number;
  path: string;
  size_bytes: number;
  status: MboxStatus;
  mails_parsed: number;
  bytes_done: number; // the import's progress: end of the last committed record
  error_count: number;
  worker_id: number | null; // while status is running (W1, W2, ...)
  started_at: string | null;
  finished_at: string | null;
}

// Mail detail -----------------------------------------------------------------------------------

export interface MailSource {
  mbox_file_id: number;
  path: string;
  byte_offset: number;
  byte_length: number;
}

export interface DkimSignature {
  index: number;
  status: DkimStatus;
  reason: DkimReason | null;
  domain: string | null;
  selector: string | null;
  algorithm: string | null;
  key_bits: number | null;
  signed_headers: string[] | null;
  body_hash_ok: boolean | null;
  signed_at: string | null;
  aligned: boolean | null;
  checked_at: string;
  dns_cached: boolean;
  dns_record: string | null;
  dns_fetched_at: string | null;
  dns_ttl: number | null;
  /** Origin of the key the result rests on (D100); null when it rests on none. */
  key_origin: KeyOrigin | null;
  /** The key from another source that verified it; null for today's DNS. */
  key: DkimKeyInfo | null;
}

export interface MailDkim {
  status: DkimStatus | null;
  signatures: DkimSignature[];
}

export interface Participant extends PersonRef {
  role: ParticipationRole;
  mails: number | null; // filled by milestone 5
  contacts: number | null;
  mails_with_sender: number | null;
}

export interface AttachmentInfo {
  id: number;
  filename: string | null;
  mime_type: string;
  size: number;
  sha256: string | null;
  /** Its document (D70); null until the next finalize assigns it. */
  document_id: number | null;
  kind: DocumentKind | null;
  text_status: DocumentTextStatus | null;
  pages: number | null;
  document_mails: number | null; // mails carrying the document, duplicates not counted
}

export interface ThreadMail {
  id: number;
  date: string | null;
  subject: string | null;
  sender: PersonRef | null;
  dkim_status: DkimStatus | null;
}

/** Bookmark and review status of a mail (D55); *_by null: no editor name was given. */
export interface Mark {
  flagged: boolean;
  flagged_by: string | null;
  flagged_at: string | null;
  review: ReviewStatus | null;
  review_by: string | null;
  review_at: string | null;
}

export interface TagRef {
  id: number;
  name: string;
  color: TagColor;
}

export interface CollectionRef {
  id: number;
  name: string;
}

export interface NoteInfo {
  id: number;
  body: string;
  author: string | null;
  created_at: string;
  updated_at: string; // equals created_at until edited
}

/** The research file's data on one mail, shared by its byte-identical copies (D53). */
export interface MailResearch {
  mark: Mark;
  tags: TagRef[]; // by name
  collections: CollectionRef[]; // by name
  notes: NoteInfo[]; // oldest first
}

export interface MailDetail {
  id: number;
  subject: string | null;
  date: string | null;
  message_id: string | null;
  in_reply_to: string | null;
  in_reply_to_id: number | null;
  reference_ids: string[];
  source: MailSource;
  raw_sha256: string;
  has_attachments: boolean;
  dkim: MailDkim;
  participants: Participant[];
  attachments: AttachmentInfo[];
  thread_id: number | null;
  thread: ThreadMail[];
  thread_size: number;
  duplicate_of: number | null;
  duplicates: number[];
  research: MailResearch;
}

// Bodies --------------------------------------------------------------------------------------

export interface MailText {
  text: string;
  truncated: boolean;
  source: "text/plain" | "text/html" | "none";
  has_html: boolean;
}

export interface HeaderField {
  name: string;
  value: string;
}

export interface MailHeaders {
  headers: HeaderField[];
}

export interface MailRaw {
  raw: string;
  truncated: boolean;
  size: number;
}

// Persons (milestone 5) -----------------------------------------------------------------------
// A person is a root person: its own address plus the addresses merged into it (aliases).

export const TOP_CONTACTS = 10;
export const DISPLAY_NAME_LIMIT = 10;
export const SUGGESTION_LIMIT = 10;
export const MERGE_LIMIT = 50;

export interface PersonListParams {
  q?: string; // part of an address or display name of the person or an alias
  sort?: PersonSort;
  cursor?: string;
  limit?: number;
}

export interface ContactListParams {
  cursor?: string;
  limit?: number;
}

export interface SuggestionListParams {
  cursor?: string;
  limit?: number;
}

export interface PersonMailCountParams {
  year?: number; // UTC year
  contact?: number; // person id: mails between both
}

export interface MergeRequest {
  target: number; // stays
  sources: number[]; // 1 to MERGE_LIMIT, merged with their aliases
}

export interface SuggestionDismiss {
  persons: [number, number];
}

export interface PersonFigures {
  mails: number; // sent + received
  sent: number;
  received: number; // To, Cc or Bcc, not From
  cc_only: number; // part of received
  contacts: number;
  first_date: string | null;
  last_date: string | null;
  dkim_pass_ratio: number | null; // 0 to 1 among checked sent mails; null: none
}

export interface PersonSummary {
  id: number;
  name: string | null;
  email: string;
  domain: string;
  aliases: number;
  figures: PersonFigures;
}

export interface PersonPage {
  items: PersonSummary[];
  next_cursor: string | null;
  prev_cursor: string | null;
  total: number;
}

export interface Contact {
  person: PersonRef;
  domain: string;
  mails: number;
  sent: number; // from this person to the contact (To or Bcc)
  received: number; // from the contact to this person (To or Bcc)
  cc: number;
  first_date: string | null;
  last_date: string | null;
}

export interface ContactPage {
  items: Contact[];
  next_cursor: string | null;
  total: number;
}

export interface AliasAddress {
  person_id: number;
  email: string;
  name: string | null;
  mails: number;
}

export interface DisplayNameCount {
  name: string;
  mails: number;
}

export interface YearActivity {
  year: number;
  sent: number;
  received: number;
}

export interface AliasCandidate {
  person: PersonSummary; // the other person
  same_name: string | null;
  same_local_part: string | null;
}

export interface AliasSuggestion {
  first: PersonSummary; // more mails; stays by default when merging
  second: PersonSummary;
  same_name: string | null;
  same_local_part: string | null;
}

export interface SuggestionPage {
  items: AliasSuggestion[];
  next_cursor: string | null;
  total: number;
}

export interface PersonProfile {
  id: number; // the root; differs from the requested id when that was an alias
  name: string | null;
  email: string;
  domain: string;
  aliases: AliasAddress[];
  display_names: DisplayNameCount[];
  figures: PersonFigures | null; // null until aggregated
  years: YearActivity[]; // oldest first
  top_contacts: Contact[];
  suggestions: AliasCandidate[];
}

/** Mails per tab; null where counting ran out of time. */
export interface PersonMailCounts {
  all: number | null;
  sent: number | null;
  received: number | null;
  cc: number | null;
}

// Relationship map (milestone 6, D36 to D38) --------------------------------------------------

export const MAX_GRAPH_NODES = 2_000;
export const GRAPH_TOP = 50;

export type GraphMode = "ego" | "top" | "domains";
/** person.kind: no human (D39). null: a human, or not recognised. */
export type PersonKind = "list" | "automated";

/** One excerpt of the map; the counted graph and the modes are described in schemas.py. */
export interface GraphParams {
  mode?: GraphMode;
  center?: number[]; // ego: at least one person
  depth?: number; // ego: 1 to 3
  limit?: number; // top: number of persons, up to MAX_GRAPH_NODES
  domain?: string[]; // domains: exactly two
  min_edge?: number; // lighter edges are neither shown nor followed
  year_from?: number; // UTC year, inclusive
  year_to?: number; // UTC year, inclusive
  dkim_only?: boolean;
  cc?: boolean; // Cc counts towards the weight
  hide_lists?: boolean; // leave out lists and automated senders, apart from centers
  expand?: number[]; // add these persons and their neighbours
  hide?: number[]; // leave out these persons; ignored for centers
}

export interface GraphNode {
  id: number;
  name: string | null;
  email: string;
  domain: string;
  kind: PersonKind | null;
  mails: number; // weight of all the person's counted edges, shown or not
  contacts: number;
  center: boolean;
}

export interface GraphEdge {
  source: number; // the smaller person id
  target: number;
  a_to_b: number; // source to target, To or Bcc
  b_to_a: number;
  cc: number; // either direction
  weight: number; // a_to_b + b_to_a, plus cc when counted
}

export interface EdgeTable {
  pairs: number;
  refreshed_at: string | null;
}

export interface Graph {
  nodes: GraphNode[]; // most mails first
  edges: GraphEdge[]; // heaviest first
  mails: number; // "Mails im Ausschnitt"
  centers: number[];
  edge_table: EdgeTable;
}

export interface GraphSize {
  nodes: number;
  edges: number;
  mails: number;
  too_large: boolean; // /api/graph would answer graph_too_large
}

// Import dashboard (milestone 7) ----------------------------------------------------------------

export const ERROR_PAGE_SIZE = 50;

export type JobKind = "import" | "dkim" | "dkim_keys";
export type JobStatus = "running" | "done" | "stopped" | "failed";
export type JobOrigin = "cli" | "ui";
export type ImportPhase = "scan" | "headers" | "import" | "finalize" | "attachments";
export type DkimPhase = "check" | "aggregates";
export type DnsStatus = "found" | "not_found" | "temp_error";
export type ImportErrorKind =
  | "separator"
  | "too_large"
  | "encoding"
  | "date"
  | "message_id"
  | "address"
  | "parse"
  | "dkim"
  | "io"
  | "internal";

/** What an import run works with; the defaults of a start from the dashboard. */
export interface ImportOptions {
  workers: number;
  attachment_hash_limit: number; // bytes
  max_mail_size: number; // bytes
  dkim_nameservers: string; // comma-separated; "" = system resolver
  dkim_offline: boolean;
  mbox_dir: string;
  text_max_size: number; // bytes; larger documents are not read (D72)
  text_timeout: number; // seconds per document
}

/** Live figures of an import run, reported every 2 s. */
export interface ImportProgress {
  workers: number; // busy now
  files_queued: number;
  files_finished: number;
  mails_imported: number; // by this run
  bytes_imported: number;
  mails_per_second: number; // over the last 60 s
  dkim_per_second: number;
  bytes_per_second: number;
  eta_seconds: number | null;
  headers_total: number; // phase "headers": mails whose headers are read again
  headers_done: number;
  documents_total: number; // phase "attachments": documents whose text this run extracts
  documents_done: number;
  documents_per_second: number;
}

export interface DkimOptions {
  statuses: string[] | null; // DKIM keys selected; null: every mail
  mail_ids: number[];
  workers: number;
  offline: boolean;
}

export interface DkimProgress {
  workers: number;
  selected: number;
  checked: number;
  skipped: number;
  mails_per_second: number;
  eta_seconds: number | null;
}

/** One run of `mailrobbe import` or `mailrobbe dkim`. */
interface JobInfo {
  id: number;
  origin: JobOrigin;
  status: JobStatus;
  /** Its process lives. false with status "running": it ended without recording it. */
  alive: boolean;
  stop_requested: boolean;
  started_at: string;
  updated_at: string; // its last report
  finished_at: string | null;
  message: string | null; // English summary or failure reason
}

export interface ImportJob extends JobInfo {
  kind: "import";
  phase: ImportPhase | null;
  options: ImportOptions;
  progress: ImportProgress;
}

export interface DkimJob extends JobInfo {
  kind: "dkim";
  phase: DkimPhase | null;
  options: DkimOptions;
  progress: DkimProgress;
}

/** A run of `mailrobbe dkim-keys` (D101). */
export interface DkimKeysJob extends JobInfo {
  kind: "dkim_keys";
  phase: DkimKeysPhase | null;
  options: DkimKeysOptions;
  progress: DkimKeysProgress;
}

export interface ImportTotals {
  files: number;
  done: number;
  running: number;
  pending: number;
  paused: number;
  error: number;
  size_bytes: number;
  bytes_done: number;
  mails_parsed: number;
  mails_estimated: number | null; // extrapolated by bytes; null before the first byte
  error_count: number;
}

export interface ImportStatus {
  mbox_dir: string;
  mbox_dir_ok: boolean; // start and rescan need it
  totals: ImportTotals;
  files: MboxFileInfo[]; // sorted by path
  import_job: ImportJob | null;
  dkim_job: DkimJob | null;
  defaults: ImportOptions;
  keys_job: DkimKeysJob | null; // the latest dkim-keys run (D101)
}

export interface FailReasonCount {
  reason: DkimReason;
  mails: number;
}

export interface ImportSummary {
  db_size_bytes: number;
  raw_size_bytes: number;
  fulltext_index_bytes: number;
  dns_cache: Record<DnsStatus, number>;
  dns_hit_ratio: number | null; // 0 to 1
  persons: number;
  open_suggestions: number;
  edge_table: EdgeTable;
  duplicates: number;
  dkim: DkimCounts;
  fail_reasons: FailReasonCount[]; // most first
  updated_at: string | null;
  attachments: number; // attachment rows, live (D70)
  documents: Record<DocumentTextStatus, number>; // documents by text status, live
}

export interface ImportErrorParams {
  kind?: ImportErrorKind;
  mbox_file?: number;
  cursor?: string;
  limit?: number;
}

export interface ImportErrorItem {
  id: number;
  mbox_file_id: number | null;
  path: string | null;
  byte_offset: number | null;
  kind: ImportErrorKind;
  message: string; // English, technical
  created_at: string;
}

export interface ImportErrorPage {
  items: ImportErrorItem[]; // newest first
  next_cursor: string | null;
  total: number; // matching the filters
  kinds: Partial<Record<ImportErrorKind, number>>; // all errors, only kinds seen
}

export interface ImportStartRequest {
  workers?: number | null;
  attachment_hash_limit?: number | null; // bytes
  dkim_nameservers?: string | null;
}

export interface DkimRecheckRequest {
  statuses?: DkimKey[]; // default: unchecked, no_key, temp_error
  workers?: number | null;
}

export interface FileProblem {
  path: string;
  reason: string; // English
}

export interface ScanResult {
  files: number;
  pending: number;
  new: string[];
  replaced: FileProblem[];
  missing: string[];
  unreadable: FileProblem[];
}

// Research file (milestone 8, D53 to D64) -------------------------------------------------------
// Writes send the editor's name (lib/editor.ts) as X-Mailrobbe-Editor (D54).

export const NAME_LIMIT = 120;
export const TAG_NAME_LIMIT = 60;
export const DESCRIPTION_LIMIT = 4_000;
export const QUERY_LIMIT = 4_000;
export const LABEL_LIMIT = 200;
export const SELECTION_IDS_LIMIT = 1_000;
export const BULK_LIMIT = 50_000;
export const EXPORT_LIMIT = 2_000;
export const PERMALINK_DIGITS = 16;

export type BulkAction =
  "tag_add" | "tag_remove" | "collection_add" | "collection_remove" | "review" | "flag";

export interface TagInfo extends TagRef {
  description: string;
  mails: number;
  created_by: string | null;
  created_at: string;
}

export interface TagCreate {
  name: string;
  color?: TagColor;
  description?: string;
}

/** Fields left out stay as they are. */
export interface TagUpdate {
  name?: string;
  color?: TagColor;
  description?: string;
}

export interface CollectionInfo extends CollectionRef {
  description: string;
  mails: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface CollectionCreate {
  name: string;
  description?: string;
}

export interface CollectionUpdate {
  name?: string;
  description?: string;
}

export interface SavedSearch {
  id: number;
  name: string;
  query: string; // query string of /mails, without cursor and page
  collection_id: number | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SavedSearchCreate {
  name: string;
  query: string;
  collection_id?: number | null;
}

/** Fields left out stay as they are; collection_id null detaches it from its Akte. */
export interface SavedSearchUpdate {
  name?: string;
  query?: string;
  collection_id?: number | null;
}

export interface ResearchOverview {
  tags: TagInfo[]; // by name
  collections: CollectionInfo[]; // last changed first
  searches: SavedSearch[]; // by name
  review: Record<ReviewKey, number>;
  flagged: number;
  notes: number;
  starter_missing: number; // tags and searches of the themes not created yet (D64)
}

export interface ThemeSearchInfo {
  name: string;
  query: string;
}

/** A research theme of themes.toml (D64). */
export interface ThemeInfo {
  key: string;
  name: string;
  color: TagColor;
  description: string;
  terms: string[];
  searches: ThemeSearchInfo[];
}

export interface CollectionPerson {
  person: PersonRef;
  mails: number;
}

export interface CollectionDetail extends CollectionInfo {
  date_min: string | null;
  date_max: string | null;
  missing: number; // contents in no mail of the archive (any more)
  persons: CollectionPerson[];
  searches: SavedSearch[];
}

/** Fields left out stay as they are; review null makes the mail unreviewed again. */
export interface MarkUpdate {
  flagged?: boolean;
  review?: ReviewStatus | null;
}

/** Tags or Akten to add to and remove from one mail. */
export interface LinkChange {
  add?: number[];
  remove?: number[];
}

export interface NoteCreate {
  body: string;
}

export interface NoteEdit {
  body: string;
}

export interface NoteListParams {
  q?: string;
  cursor?: string | null;
  limit?: number;
}

export interface NoteMail {
  id: number | null; // null: not in the archive (any more)
  subject: string | null;
  date: string | null;
  sender: PersonRef | null;
}

export interface NoteItem extends NoteInfo {
  mail_sha256: string;
  mail: NoteMail;
}

export interface NotePage {
  items: NoteItem[]; // newest first
  next_cursor: string | null;
  total: number;
}

/** Exactly one of ids and filters. */
export interface MailSelection {
  ids?: number[] | null;
  filters?: MailFilters | null;
}

export interface BulkRequest extends MailSelection {
  action: BulkAction;
  tag_id?: number | null;
  collection_id?: number | null;
  review?: ReviewStatus | null;
  flagged?: boolean | null;
}

export interface BulkResult {
  mails: number;
  changed: number;
}

export interface PermalinkTarget {
  mail_id: number;
  raw_sha256: string;
}

export interface ExportRequest extends MailSelection {
  include_research?: boolean;
  label?: string;
}

export interface ExportInfo {
  id: number;
  label: string;
  mails: number;
  include_research: boolean;
  created_by: string | null;
  created_at: string;
  manifest_sha256: string | null; // of the ZIP's SHA256SUMS at the first complete download
  downloaded_at: string | null;
  download_url: string;
}

// Attachments and documents (milestone 9, D70 to D77) -------------------------------------------

export const DOCUMENT_NAMES_LIMIT = 20;
export const DOCUMENT_PERSONS_LIMIT = 10;

export type DocumentKind =
  | "pdf"
  | "document"
  | "spreadsheet"
  | "presentation"
  | "text"
  | "email"
  | "image"
  | "archive"
  | "media"
  | "other";
export type DocumentTextStatus =
  | "pending"
  | "text"
  | "empty"
  | "scanned" // a PDF of images without text: a scan, for a later OCR
  | "encrypted"
  | "unsupported"
  | "too_large"
  | "failed"
  | "timeout" // stopped at the time limit; the text read until then is kept
  | "unreadable"; // the MBOX file is missing or changed; tried again at the next import
export type DocumentSort = "recent" | "oldest" | "mails" | "size";

/** Filters of the document list (D74). Mail conditions hold for one carrying mail. */
export interface DocumentFilters {
  q?: string; // full text over content and file names
  name?: string; // part of a file name
  kind?: DocumentKind[];
  text_status?: DocumentTextStatus[];
  date_from?: string; // YYYY-MM-DD, UTC, inclusive
  date_to?: string;
  person?: number;
  person_role?: "sent" | "received";
  shared?: boolean; // carried by at least two mails
  external?: boolean;
}

export interface DocumentListParams extends DocumentFilters {
  sort?: DocumentSort;
  cursor?: string;
  limit?: number;
}

export interface DocumentListItem {
  id: number;
  name: string | null;
  names: number; // distinct file names
  kind: DocumentKind | null;
  mime_type: string;
  size: number;
  sha256: string | null;
  pages: number | null;
  text_status: DocumentTextStatus;
  mails: number; // duplicates not counted
  first_date: string | null;
  last_date: string | null;
  first_sender: PersonRef | null;
  snippet: string | null; // with full text words in q: text around the first literal match
}

export interface DocumentPage {
  items: DocumentListItem[];
  next_cursor: string | null;
  prev_cursor: string | null;
}

export interface DocumentSummary {
  total: number | null; // null: counting ran out of time
  exact: boolean;
  kinds: Record<DocumentKind, number> | null;
  text_status: Record<DocumentTextStatus, number> | null;
}

export interface DocumentNameCount {
  name: string;
  attachments: number;
}

export interface PersonCount {
  person: PersonRef; // a root person
  mails: number;
}

export interface DocumentDetail {
  id: number;
  name: string | null;
  mime_type: string;
  kind: DocumentKind | null;
  size: number;
  sha256: string | null;
  pages: number | null;
  text_status: DocumentTextStatus;
  text_error: string | null; // English, technical
  text_truncated: boolean;
  extracted_at: string | null;
  mails: number;
  attachments: number; // duplicates included
  first_date: string | null;
  last_date: string | null;
  first_mail: ThreadMail | null;
  names: DocumentNameCount[]; // most used first
  senders: PersonCount[]; // most mails first
  sender_count: number;
  recipients: PersonCount[];
  recipient_count: number;
  attachment_id: number; // GET /api/attachments/{id}/content reads it
  preview: boolean; // a raster image the browser can show
}

export interface DocumentText {
  text: string;
  truncated: boolean;
  text_status: DocumentTextStatus;
}

// Keys of deleted selectors (D100 to D104) ------------------------------------------------------
// A key name is "<selector>._domainkey.<domain>", lowercase. A name is "concerned" when it has
// signatures that are no_key, or fail with signature_mismatch and an intact body.

export const SELECTOR_MAILS_LIMIT = 200;
export const EVIDENCE_FILE_LIMIT = 10 * 1024 ** 2; // bytes

/** Strongest first: today's DNS, seen in DNS by a third party, in a document, reconstructed. */
export type KeyOrigin = "dns" | "observed" | "documented" | "reconstructed";
export type KeyLookupSource = "reconstruction" | "archive_text" | "manual" | "zkemail" | "dns";
export type LookupOutcome = "found" | "not_found" | "error";
export type DkimKeysTask = "reconstruct" | "search" | "fetch" | "check";
export type DkimKeysPhase =
  "select" | "reconstruct" | "search" | "fetch" | "compare" | "check" | "aggregates";
export type SelectorFilter = "open" | "resolved" | "all";

export interface DkimKeysOptions {
  task: DkimKeysTask;
  names: string[]; // empty: every name concerned
  domains: string[]; // fetch; empty: every domain concerned
  workers: number;
  archive_url: string | null; // fetch: the key archive asked
}

/** Done, total, rate and remaining time of the phases come with the run's progress steps. */
export interface DkimKeysProgress {
  workers: number;
  names: number; // key names the run works on
  keys_found: number;
  factorable: number;
  mails_checked: number;
  mails_changed: number;
}

export interface UsedSignature {
  mail_id: number | null; // null: no mail has this content any more
  mail_sha256: string;
  signature_index: number;
}

export interface KeyEvidenceInfo {
  id: number;
  origin: KeyOrigin;
  source: KeyLookupSource;
  lookup_id: number;
  asked_at: string; // when Mailrobbe asked, or the key was entered
  observed_from: string | null; // the source's own times
  observed_to: string | null;
  reference: string | null; // URL, /m/<hash>, /anhaenge/<id>, file name
  note: string | null;
  editor: string | null;
  raw_sha256: string | null; // GET /api/dkim/lookups/{lookup_id}/raw
  raw_size: number | null;
  signatures: UsedSignature[]; // reconstruction: the signatures used
}

export interface DkimKeyInfo {
  id: number;
  name: string;
  key_type: string; // rsa or ed25519
  bits: number;
  key_sha256: string;
  record: string;
  origin: KeyOrigin; // the strongest of its evidence
  factorable: boolean; // never used to verify
  signatures: number; // signatures it verified
  evidence: KeyEvidenceInfo[]; // strongest first, then oldest
}

export interface SelectorListParams {
  q?: string;
  show?: SelectorFilter;
  limit?: number;
  offset?: number;
}

export interface SelectorItem {
  name: string;
  domain: string;
  selector: string;
  signatures: number;
  mails: number;
  statuses: Partial<Record<DkimStatus, number>>; // only statuses present
  rsa_signatures: number; // reconstructable from 2 on
  first_signed: string | null;
  last_signed: string | null;
  keys: number;
  best_origin: KeyOrigin | null;
  dns_status: DnsStatus | null; // null: not asked yet
}

export interface SelectorPage {
  items: SelectorItem[];
  total: number;
}

export interface SelectorSummary {
  names_missing: number;
  mails_missing: number;
  reconstructable: number;
  names_resolved: number;
  mails_consistent: number;
  keys: Record<KeyOrigin, number>;
  factorable: number;
  signatures: Record<KeyOrigin, number>;
  lookups: Record<KeyLookupSource, number>;
  last_lookup_at: string | null;
}

export interface KeyLookupInfo {
  id: number;
  source: KeyLookupSource;
  query: string;
  domain: string | null;
  name: string | null;
  asked_at: string;
  outcome: LookupOutcome;
  http_status: number | null;
  raw_sha256: string | null;
  raw_size: number | null;
  raw_type: string | null;
  raw_name: string | null;
  message: string | null; // English
  tool_version: string;
  editor: string | null;
  keys: number;
}

export interface SelectorMail {
  id: number;
  date: string | null;
  subject: string | null;
  sender: PersonRef | null;
  signature_index: number;
  status: DkimStatus;
  reason: DkimReason | null;
  key_origin: KeyOrigin | null;
  key_id: number | null;
  signed_at: string | null;
}

export interface SelectorDetail {
  name: string;
  domain: string;
  selector: string;
  dns_status: DnsStatus | null;
  dns_record: string | null;
  dns_fetched_at: string | null;
  signatures: number;
  mails: number;
  statuses: Partial<Record<DkimStatus, number>>;
  rsa_signatures: number;
  first_signed: string | null;
  last_signed: string | null;
  keys: DkimKeyInfo[]; // strongest first
  lookups: KeyLookupInfo[]; // newest first
  recent_mails: SelectorMail[]; // newest first, at most SELECTOR_MAILS_LIMIT
}

export interface ManualKeyRequest {
  record: string; // the TXT record, or only the p= value
  reference: string;
  note?: string;
  observed_from?: string | null;
  observed_to?: string | null;
  file_name?: string | null;
  file_base64?: string | null; // at most EVIDENCE_FILE_LIMIT bytes decoded
}

export interface ArchiveDomain {
  domain: string;
  names: number;
  mails: number;
  last_asked_at: string | null;
}

export interface KeyArchivePreview {
  url: string | null; // null: switched off
  domains: ArchiveDomain[]; // most mails first
  skipped: string[]; // reserved TLDs, sent only to an archive on this machine
}

export interface DkimKeysRunRequest {
  task: DkimKeysTask;
  names?: string[];
  domains?: string[];
  workers?: number | null;
}

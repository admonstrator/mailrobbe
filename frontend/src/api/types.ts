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
/** Tier of an alias suggestion (D160): certain when several signs agree. */
export type AliasTier = "certain" | "uncertain";
/** Why a suggestion was made: name and local part, a name that fits both addresses of one
 *  organisation (both certain, with shared contacts), name and local part with too few shared
 *  contacts, a name alone, a local part alone (all three uncertain). */
export type SuggestionReason =
  | "name_and_local_part"
  | "name_fits_addresses"
  | "name_and_local_part_few_contacts"
  | "name"
  | "local_part";
export type MboxStatus = "pending" | "running" | "paused" | "done" | "error";
export type SortOrder = "date_desc" | "date_asc";
/** Review status of a mail (D55); null is unreviewed. */
export type ReviewStatus = "seen" | "relevant" | "irrelevant";
/** Filter and count keys: the statuses plus "unreviewed" for mails without one. */
export type ReviewKey = "unreviewed" | ReviewStatus;
/** Kinds of calendar events (D154): request (an invitation or update), reply (an answer),
 *  cancel (a cancellation). */
export type EventKey = "request" | "reply" | "cancel";
export const EVENT_KEYS: readonly EventKey[] = ["request", "reply", "cancel"];
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
  | "message_id"
  // Full text words in one place (D172), written betreff:, text:, anhang:, datei:
  | "in_subject"
  | "in_body"
  | "in_attachment"
  | "in_filename"
  // Two words at most QueryTerm.distance words apart, in either order (D229): "a b"~N
  | "near";

/** Where the full text words of q are looked for (D171): the mail's subject and its text, the
 *  text of its attachments' documents and their file names. */
export type SearchField = "subject" | "body" | "attachment" | "filename";
export const SEARCH_FIELDS: readonly SearchField[] = ["subject", "body", "attachment", "filename"];
/** The largest min_hits (D174). */
export const MIN_HITS_LIMIT = 999;
/** The parts of a mail's own text the full text words are looked for in (D226, D228): clean
 *  leaves out the standard blocks, own also the quotes, originals and forwards (the words the
 *  sender wrote), full looks at all of it. The subject is always looked at. */
export type BodyPart = "clean" | "own" | "full";
export const BODY_PARTS: readonly BodyPart[] = ["clean", "own", "full"];
/** The largest N of "a b"~N (D229). */
export const PROXIMITY_LIMIT = 20;
/** A paragraph's hash: 16 lower-case hex digits. */
export const BLOCK_HASH_PATTERN = /^[0-9a-f]{16}$/;
/** An area of the map (D248): west,south,east,north in decimal degrees. */
export const AREA_PATTERN = /^-?\d{1,3}(\.\d+)?(,-?\d{1,3}(\.\d+)?){3}$/;

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
  | "no_preview"
  | "preview_too_large"
  | "preview_failed"
  | "invalid_key" // 400: no DKIM key name, or a record without a usable key (D103)
  | "archive_off" // 409: the key archive is switched off
  | "merge_undone" // 409: the merge, or every merge of the batch, was undone already (D163)
  | "invalid_rule" // 400: a hide rule without any criterion, or one that cannot be used (D221)
  | "invalid_block" // 400: a sample that is no paragraph of this hash, or none where needed
  | "page_too_far" // 400: a jump to a page did not answer within the count budget (D193)
  | "not_locked" // 409: the document is not locked, or (decrypted) has no password found yet
  | "decrypt_failed" // 422: the found password did not decrypt it; message says why
  | "map_off" // 409: no detail map is offered (MAILROBBE_MAP_SOURCE=off, D245)
  | "too_many_documents"; // 400: a selection for the AI queue above AI_QUEUE_LIMIT (D186)

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
  thread?: number; // the mail's thread_id is this one (D95)
  entity?: number[]; // each of these entities is mentioned, in the mail or an attachment (D86)
  amount_min?: number; // an amount of at least this value is mentioned, any currency
  amount_context?: EntityContextKey[]; // such an amount next to any of these contexts
  signal?: SignalKey[]; // each of these signals holds for the mail (D136)
  /** Per group of near duplicates only its earliest mail meeting the other filters (D153). */
  collapse_near?: boolean;
  near_group?: number; // the mails of this group of near duplicates (its first mail's id)
  event?: EventKey[]; // carries a calendar event of any of these kinds (D155)
  event_uid?: string; // carries a calendar event with this UID
  /** Full text options (D171 to D174), without effect when q has no full text words: where its
   *  free words are looked for (empty: everywhere), whole words only (no German stems, no part
   *  of a longer word, any case, umlauts and accents count), and at least min_hits occurrences
   *  of the words in those places of the mail and its attachments together. */
  scope?: SearchField[];
  whole_word?: boolean;
  min_hits?: number; // 1 to MIN_HITS_LIMIT
  /** Milestone 18: mails a hide rule hides are left out unless include_hidden (D222); the parts
   *  of the mail's own text the full text words are looked for in (default clean, D226); the
   *  mails holding this paragraph anywhere in their stored text (D227). */
  include_hidden?: boolean;
  body_part?: BodyPart;
  block?: string;
  /** Milestone 20 (D248): the mail carries a photo whose position lies in this area,
   *  "west,south,east,north" (AREA_PATTERN); west above east crosses the 180th meridian. */
  photo_area?: string;
}

export interface MailOrderParams extends MailFilters {
  sort?: SortOrder;
}

export interface MailListParams extends MailOrderParams {
  cursor?: string;
  limit?: number;
  /** A jump instead of a cursor (D193): this page (from 1) of `limit` mails, a page beyond the
   *  end being the last one; or with last the last `limit` mails, read from the end. */
  page?: number;
  last?: boolean;
}

// Mail list -------------------------------------------------------------------------------------

/** The team's label of an address (D156): Klarname and Rolle. */
export interface AccountLabel {
  name: string | null;
  role: string | null;
}

export interface PersonRef {
  person_id: number;
  email: string;
  name: string | null; // the display name used in this mail, else the person's
  /** The label of the address, else of its root, else the newest of the root's other
   *  addresses (D156); lib/person.ts reads it. */
  label?: AccountLabel | null;
}

export interface QueryTerm {
  key: QueryKey;
  value: string;
  raw: string; // exact substring of q; removing it from q removes the term
  /** An operator or Message-ID written with a leading minus: it must not hold (D175). Free text
   *  words keep their minus in value. */
  negated: boolean;
  /** key near: the most words between the two words of value (1 to PROXIMITY_LIMIT, D229). */
  distance?: number | null;
}

/** How often the full text words of q occur in one mail, by place (D176): the words that count
 *  for min_hits, each counted in the places it is looked for, 0 elsewhere. */
export interface MailHitCounts {
  subject: number;
  body: number;
  attachment: number; // in the texts of its attachments' documents, every attachment counted
  filename: number; // in the file names of its attachments' documents
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
  near_count: number; // the other mails of its group of near duplicates (D153); 0: none
  event: EventKey | null; // the kind of the mail's first calendar event (D155)
  /** q has full text words: where they occur (D176); null otherwise. */
  hits: MailHitCounts | null;
  /** The text of an attachment holding a counted word was recognised by an AI run (D189). */
  attachment_machine?: boolean;
  /** That machine made text is a recording's transcript (D296); attachment_machine is true too. */
  attachment_transcript?: boolean;
}

export interface MailPage {
  items: MailListItem[];
  next_cursor: string | null;
  prev_cursor: string | null;
  query_terms: QueryTerm[];
  /** The page's number (D193): 1 for the first page, the page a jump read; null after a cursor
   *  and for the last page read from the end (last). */
  page?: number | null;
}

export interface MailSummary {
  total: number | null; // null: unknown
  exact: boolean; // false: total is a lower bound
  dkim: DkimCounts | null;
  persons: number | null;
  domains: number | null;
  date_min: string | null;
  date_max: string | null;
  /** Without include_hidden: the mails the other filters match that a hide rule hides (D222);
   *  null with include_hidden, or when counting ran out of time. */
  hidden?: number | null;
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
  near: NearFigures | null; // null: the near phase never ran (D153)
  events: Record<EventKey, number>; // mails with an event of each kind (D155)
}

/** What the last near phase found (D153). */
export interface NearFigures {
  groups: number;
  mails: number; // in groups, duplicates not counted
  hidden: number; // mails collapse_near leaves out
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

/** How the browser shows an attachment (D120): image in an <img>, pdf in the isolated PDF
 *  viewer, html (DOCX, ODT converted on the server) in an iframe without scripts, audio and
 *  video in the media elements. */
export type PreviewKind = "image" | "pdf" | "html" | "audio" | "video";

/** Where the text recognition stands for an attachment's document (D280); null: OCR has
 *  nothing to do with it. */
export type AttachmentOcr = "readable" | "queued" | "recognised" | "no_text";
/** The same for a recording's transcript (D296); null: the transcriber has nothing to do with
 *  it. no_text: read, and nobody speaks (or it has no sound). */
export type AttachmentTranscript = "transcribable" | "queued" | "transcribed" | "no_text";

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
  preview: PreviewKind | null; // how the browser shows it (D120); null: download only
  metadata: MetadataSummary | null; // what the file says about itself (D167)
  /** Locked: it needs a password; open: one was found (D233); null: not protected. */
  protection?: DocumentProtection | null;
  path?: string | null; // a member's path inside its container (D231)
  /** A container (ZIP, 7z, attached mail): whether it was unpacked, and its entries that became
   *  documents, in the container's order (D231); null and [] for any other attachment. */
  members_status?: DocumentMembersStatus | null;
  ocr?: AttachmentOcr | null; // the text recognition of its document (D280)
  transcript?: AttachmentTranscript | null; // the transcription of its recording (D296)
  duration?: number | null; // seconds of its recording, once transcribed (D293)
  members?: AttachmentInfo[];
}

/** The few metadata fields of a document shown next to an attachment (D167), as found in the
 *  file, never rated; null for a field the file does not have. */
export interface MetadataSummary {
  author: string | null; // Artist, Author, dc:creator, initial creator
  modified_by: string | null; // lastModifiedBy, dc:creator of ODF
  software: string | null; // Software, CreatorTool, Creator/Producer, Application, generator
  device: string | null; // camera or scanner: Make and Model
  created: string | null; // when the file says it was made or taken, ISO 8601 UTC
  gps: boolean; // the file names a place (EXIF GPS)
  /** The position it states (D241): decimal degrees, south and west negative. */
  latitude: number | null;
  longitude: number | null;
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
  /** Near duplicates (D153): the group's first mail id (null: in no group), the other mails of
   *  the group, oldest first, at most NEAR_LIMIT, and the group's size with this mail. */
  near_group: number | null;
  near: NearMail[];
  near_size: number;
  events: CalendarEventInfo[]; // its calendar events in mail order (D155)
  hidden?: MailHiding | null; // an enabled hide rule matches it (D222)
  list_id?: string | null; // its List-Id, as a hide rule names it (D221)
}

export const NEAR_LIMIT = 50;

export interface NearMail extends ThreadMail {
  recipients: PersonRef[]; // at most RECIPIENT_PREVIEW
  recipient_count: number;
  is_duplicate: boolean;
}

/** An organizer or attendee of an event (D154). */
export interface CalendarAttendee {
  email: string | null;
  name: string | null; // CN
  role: string | null; // CHAIR, REQ-PARTICIPANT, OPT-PARTICIPANT, NON-PARTICIPANT
  partstat: string | null; // ACCEPTED, DECLINED, TENTATIVE, NEEDS-ACTION, DELEGATED
  person: PersonRef | null; // the archive's person of the address
}

/** One event of an iCalendar part of a mail (D154, D155). */
export interface CalendarEventInfo {
  id: number;
  mail_id: number;
  kind: EventKey;
  method: string | null;
  uid: string | null;
  sequence: number | null;
  status: string | null;
  summary: string | null;
  location: string | null;
  description: string | null;
  /** Wall time as written, ISO without offset, and its TZID ("UTC" for a time in UTC); the
   *  instants when the zone is known. */
  starts_local: string | null;
  ends_local: string | null;
  time_zone: string | null;
  starts_at: string | null;
  ends_at: string | null;
  all_day: boolean;
  recurrence: string | null; // RRULE as written
  organizer: CalendarAttendee | null;
  attendees: CalendarAttendee[];
  uid_mails: number; // mails with an event of this UID, this one included; 0 without a UID
}

// Bodies --------------------------------------------------------------------------------------

/** Segments of a mail's text (D151); a standard block (D227) is cut out of the segment it
 *  stands in. */
export type SegmentKind = "text" | "quote" | "original" | "forward" | "signature" | "standard";

export interface TextSegment {
  kind: SegmentKind;
  start: number; // character offset in MailText.text
  end: number; // exclusive; the segments cover the text in order, without gaps
  lines: number; // lines that are not blank
  folded: boolean; // shown folded at first; the UI opens one holding a search word
  block?: string | null; // kind standard: the block's hash
}

/** A paragraph of MailText.text that counts (D224), for the team's choice about it (D225). */
export interface TextParagraph {
  start: number; // character offsets in MailText.text
  end: number;
  hash: string;
  standard: boolean; // a standard block as the last blocks step applied them
  mails: number; // mails holding it; 0 when the blocks step did not count it
  override: boolean | null; // the team's choice, applied at the next run; null: none
}

export interface MailText {
  text: string;
  truncated: boolean;
  source: "text/plain" | "text/html" | "none";
  has_html: boolean;
  segments: TextSegment[];
  paragraphs?: TextParagraph[]; // in text order (D224)
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
  /** Part of an address, display name, label name or role of the person or an alias. */
  q?: string;
  labelled?: boolean; // only persons with a label (D157)
  sort?: PersonSort;
  cursor?: string;
  limit?: number;
  page?: number; // a jump instead of a cursor (D193), as in MailListParams
  last?: boolean;
}

export interface ContactListParams {
  cursor?: string;
  limit?: number;
}

export interface SuggestionListParams {
  cursor?: string;
  limit?: number;
  tier?: AliasTier; // default certain
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
  label?: AccountLabel | null; // D156
}

export interface PersonPage {
  items: PersonSummary[];
  next_cursor: string | null;
  prev_cursor: string | null;
  total: number;
  page?: number | null; // as MailPage.page (D193)
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
  label?: AccountLabel | null; // the label of this address itself (D156)
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
  tier: AliasTier;
  reason: SuggestionReason;
}

export interface AliasSuggestion {
  first: PersonSummary; // more mails; stays by default when merging
  second: PersonSummary;
  same_name: string | null;
  same_local_part: string | null;
  tier: AliasTier;
  reason: SuggestionReason;
}

export interface SuggestionCounts {
  certain: number;
  uncertain: number;
}

/** One logged merge (D163): the persons it moved into target's root. */
export interface MergeLogEntry {
  id: number;
  target: PersonRef; // the root merged into
  moved: PersonRef[]; // every person it moved, the source roots with their aliases
  batch_id: number | null; // the run of "Alle sicheren zusammenführen" (D162)
  editor: string | null;
  created_at: string;
  undone_at: string | null;
  undone_by: string | null;
}

export interface SuggestionPage {
  items: AliasSuggestion[];
  next_cursor: string | null;
  total: number; // every open suggestion of the tier asked for
  counts: SuggestionCounts; // every open suggestion per tier
  computed: boolean; // false until a refresh computed them by the current rules (with tiers)
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
  suggestions: AliasCandidate[]; // certain ones first
  suggestion_counts: SuggestionCounts; // all open suggestions with this person per tier
  merges: MergeLogEntry[]; // logged merges not undone that moved aliases into it, newest first
  label: PersonLabel | null; // the label the person shows, with its note (D156)
}

export const LABEL_NAME_LIMIT = 200;
export const LABEL_NOTE_LIMIT = 10_000;

/** A label with its note and who set it (D156). */
export interface PersonLabel extends AccountLabel {
  email: string; // the address it belongs to: the root's own or an alias's
  note: string | null;
  editor: string | null;
  updated_at: string;
}

/** PUT /api/persons/{id}/label: blank fields are removed, all blank removes the label. */
export interface PersonLabelUpdate {
  name: string;
  role: string;
  note: string;
}

export const PERSON_EVENT_LIMIT = 50;

/** An event of a person (D155): one per UID, the latest mail carrying it. */
export interface PersonEvent {
  event: CalendarEventInfo;
  organizer: boolean; // the person organised it; else it is an attendee
  partstat: string | null; // its answer as an attendee
  mail: ThreadMail;
}

export interface PersonEvents {
  items: PersonEvent[]; // latest start first, undated last
  total: number;
}

/** Mails per tab; null where counting ran out of time. */
export interface PersonMailCounts {
  all: number | null;
  sent: number | null;
  received: number | null;
  cc: number | null;
}

export interface MergeLogParams {
  cursor?: string;
  limit?: number;
}

/** A run of "Alle sicheren zusammenführen" (D162) with merges on the page. */
export interface MergeBatchInfo {
  id: number;
  created_at: string;
  editor: string | null;
  merges: number; // all merges of the run
  undone: number; // of them undone
}

export interface MergeLogPage {
  items: MergeLogEntry[]; // newest first
  batches: MergeBatchInfo[]; // the runs of the page's merges, newest first
  next_cursor: string | null;
  total: number; // every logged merge
}

/** What "Alle sicheren zusammenführen" merges now (D162). */
export interface CertainMergePlan {
  merges: number; // groups, each merged into the person with most mails
  persons: number; // persons that become aliases
  left_out_groups: number; // more than five persons, or a dismissed pair inside
  left_out_persons: number;
}

export interface CertainMergeResult extends CertainMergePlan {
  batch_id: number | null; // null when there was nothing to merge
}

export interface MergeUndoResult {
  merges: number; // merges marked undone
  persons: number; // persons put back
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
  label?: AccountLabel | null; // D156
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

export type JobKind = "import" | "dkim" | "dkim_keys" | "map" | "ai";
export type JobStatus = "running" | "done" | "stopped" | "failed";
export type JobOrigin = "cli" | "ui";
export type ImportPhase =
  | "scan"
  | "headers"
  | "import"
  | "finalize"
  | "attachments"
  | "calendar"
  | "near"
  | "hidden"
  | "paragraphs"
  | "entities"
  | "places"
  | "signals"
  | "topics";
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

export type StepStatus = "waiting" | "running" | "done" | "stopped" | "skipped" | "failed";
export type StepUnit = "bytes" | "mails" | "documents" | "names" | "domains" | "places" | "pages"; // names: DKIM key names

/** One step of a run, in the order the run goes through them (D110). */
export interface StepProgress {
  key: string; // English name, e.g. "edges"; labels.ts has the German label
  /** stopped: left on a stop request short of its total; skipped: nothing to do this run. */
  status: StepStatus;
  unit: StepUnit | null; // null: the step does not count its work
  done: number;
  total: number | null;
  started_at: string | null;
  seconds: number; // in the step: so far while it runs, in all once it ended
  rate: number | null; // units per second over the last 60 s, while it runs
  eta_seconds: number | null; // an estimate, while it runs
}

/** The run's longest running database statement (D110). */
export interface DbActivity {
  seconds: number;
  wait: string | null; // null: computing; "IO": reading or writing; "Lock": waiting for a lock
}

/** What every run reports beside its own figures. */
interface RunProgress {
  steps: StepProgress[];
  database: DbActivity | null;
}

/** Live figures of an import run, reported every 2 s. */
export interface ImportProgress extends RunProgress {
  workers: number; // busy now
  files_queued: number;
  files_finished: number;
  mails_imported: number; // by this run
  bytes_imported: number;
  mails_per_second: number; // over the last 60 s
  dkim_per_second: number;
  bytes_per_second: number;
  eta_seconds: number | null;
}

export interface DkimOptions {
  statuses: string[] | null; // DKIM keys selected; null: every mail
  mail_ids: number[];
  workers: number;
  offline: boolean;
}

export interface DkimProgress extends RunProgress {
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
  report_age_seconds: number; // since its last report
  finished_at: string | null;
  message: string | null; // English summary or failure reason
  /** A statement the run left running in the database although its process ended. */
  leftover: DbActivity | null;
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
  ai_job?: AiJob | null; // the latest AI run (D187), which an import waits for
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
  /** The term entity (D83) of each term, in the order of terms; null while no scan found it.
   *  A term with an entity links to the mail list filtered by it (D138). */
  term_ids: (number | null)[];
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
  include_passwords?: boolean; // the passwords that opened attachments (D208)
  label?: string;
}

export interface ExportInfo {
  id: number;
  label: string;
  mails: number;
  include_research: boolean;
  include_passwords?: boolean;
  created_by: string | null;
  created_at: string;
  manifest_sha256: string | null; // of the ZIP's SHA256SUMS at the first complete download
  downloaded_at: string | null;
  download_url: string;
}

// Social media image (D214 to D217) -------------------------------------------------------------
// One mail as a PNG that looks like a mail client, with the persons in it blacked out before
// anything is drawn. The picture is made for the request and stored nowhere.

export type CardShape = "square" | "wide" | "portrait";

export type RedactionKind = "participant" | "contact" | "name" | "organization" | "term";

export const SOCIAL_TERMS_LIMIT = 20; // own terms per image
export const SOCIAL_TERM_LIMIT = 200; // characters of one term

export interface SocialParams {
  shape?: CardShape;
  participants?: boolean; // From, To, Cc and Bcc with their names and labels
  contacts?: boolean; // addresses, phone numbers, IBANs and account numbers in the text
  names?: boolean; // persons' names in the text
  organizations?: boolean; // organisations, places, URLs and domains in the text
  terms?: string[]; // the team's own terms
  quotes?: boolean; // show the quoted text too
  dkim?: boolean; // the DKIM seal beside the date
  checksum?: boolean; // the first 16 digits of the mail's SHA-256 in the footer
}

export interface SocialRedaction {
  places: number;
  kind: RedactionKind;
}

export interface SocialCard {
  width: number;
  height: number;
  places: number; // places blacked out, over every text of the card
  redactions: SocialRedaction[]; // by category, in the order of RedactionKind
  lines: number; // lines of the text the card shows
  truncated: boolean; // the text does not fit the format and is cut
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

// Protected and packed attachments (milestone 19, D230 to D239) ----------------------------------

/** document.protection (D233): locked needs a password, open was opened with one. */
export type DocumentProtection = "locked" | "open";
/** How the unpacking of a container stands (D231); null: waits for the next import. */
export type DocumentMembersStatus =
  | "done"
  | "locked" // entries need a password not known yet; the others are unpacked
  | "too_deep" // found only inside another container: listed there, not unpacked
  | "unsupported" // a format not unpacked (RAR, tar, gzip, D239)
  | "failed"
  | "unreadable"; // its MBOX file is missing or changed; tried again at the next import
/** What became of one entry of a container (D231). */
export type DocumentMemberStatus =
  | "document" // it became a member document
  | "locked" // needs a password not known yet
  | "too_large" // past MAILROBBE_ARCHIVE_MAX_SIZE unpacked
  | "too_many" // past MAILROBBE_ARCHIVE_MAX_MEMBERS entries
  | "failed";
/** Where the password that opened a document was found, nearest first (D235). */
export type PasswordTier =
  | "manual" // typed in by hand for every locked document
  | "mail" // the mail carrying the document
  | "thread" // a mail of the same thread
  | "contacts" // a mail between the same persons, 30 days before or after
  | "attachments" // the text of a document attached to one of those mails
  | "opened" // it opened another document
  | "archive" // any other mail or document of the archive
  | "typed"; // typed in on this document's page (POST /api/documents/{id}/password)
export const PASSWORD_LENGTH = 128;

export interface DocumentRef {
  id: number;
  name: string | null;
}

/** Where a password stands (D208): in a mail, in a document's text, or typed in by hand. */
export interface PasswordFinding {
  id: number;
  context: string; // the line(s) around it, as written
  mail: ThreadMail | null; // the mail it was found in
  recipients: PersonRef[]; // that mail's To, at most RECIPIENT_PREVIEW
  document: DocumentRef | null; // the document whose text holds it
  editor: string | null; // typed in by hand by this editor (D237)
  created_at: string;
}

/** The password that opened a document (D236), in plain text as evidence (D208). */
export interface DocumentPassword {
  value: string;
  tier: PasswordTier;
  found_at: string;
  found_by: string | null; // the editor who typed it in (tier typed)
  finding: PasswordFinding | null; // null when where it was found is not known
}

/** One entry of a container (D231). */
export interface DocumentMember {
  position: number;
  path: string;
  size: number | null; // unpacked, as declared or read
  status: DocumentMemberStatus;
  error: string | null; // English, technical
  document_id: number | null; // the member document, once assigned
  kind: DocumentKind | null;
  text_status: DocumentTextStatus | null;
  protection: DocumentProtection | null;
}

export interface DocumentMembers {
  status: DocumentMembersStatus | null; // null: not unpacked yet (the next import)
  error: string | null; // English, technical
  entries: DocumentMember[]; // in the container's order
}

export interface DocumentContainerRef {
  document_id: number; // the container document
  name: string | null;
  path: string; // where the document sits in it
}

/** POST /api/documents/{id}/password and /api/documents/passwords (D237). */
export interface PasswordTry {
  password: string; // 1 to PASSWORD_LENGTH characters
}

export interface PasswordTryResult {
  tried: number; // locked documents the password was tried on
  /** The documents it opened, now open with their text; a container is unpacked by the next
   *  import, an opened document's metadata read by it too. */
  opened: number[];
  errors: number; // documents that could not be read or tried
}

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
  /** What the file says about itself (D167): any of these values, exact. */
  author?: string[];
  program?: string[]; // MetadataSummary.software as stored
  protection?: DocumentProtection[]; // any of these (D233)
  text_origin?: TextOrigin[]; // where its text comes from (D185, D189)
}

export interface DocumentListParams extends DocumentFilters {
  sort?: DocumentSort;
  cursor?: string;
  limit?: number;
  page?: number; // a jump instead of a cursor (D193), as in MailListParams
  last?: boolean;
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
  protection?: DocumentProtection | null; // D233
  contained?: boolean; // it was found inside a container (D231)
  text_origin?: TextOrigin; // ocr: its text is machine made (D189)
}

export interface DocumentPage {
  items: DocumentListItem[];
  next_cursor: string | null;
  prev_cursor: string | null;
  page?: number | null; // as MailPage.page (D193); DocumentSummary has the total
}

export const METADATA_VALUES_LIMIT = 20; // authors and programs in DocumentSummary

export interface MetadataValueCount {
  value: string; // an author or a program, as the file states it
  documents: number; // filtered documents with this value
}

export interface DocumentSummary {
  total: number | null; // null: counting ran out of time
  exact: boolean;
  kinds: Record<DocumentKind, number> | null;
  text_status: Record<DocumentTextStatus, number> | null;
  /** The most frequent authors and programs (D167), most documents first; null: ran out of
   *  time. */
  authors: MetadataValueCount[] | null;
  programs: MetadataValueCount[] | null;
  protection?: Partial<Record<DocumentProtection, number>> | null; // every one present (D233)
  /** Of them, those OCR can read, logos included (D186); null: ran out of time. */
  ocr_readable?: number | null;
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
  preview: PreviewKind | null; // how the browser shows it (D120); null: download only
  metadata: DocumentMetadata; // what the file says about itself (D167)
  /** Protection (D233 to D237). password_trial: a password can be tried on it (PDF, OOXML,
   *  ZIP, 7z; not ODF, D239). password_tries: passwords the imports tried on it, last at
   *  password_tried_at. password: the one that opened it, with where it was found. */
  protection?: DocumentProtection | null;
  password_trial?: boolean;
  password_tries?: number;
  password_tried_at?: string | null;
  password?: DocumentPassword | null;
  members?: DocumentMembers | null; // a container's entries (D231); null otherwise
  containers?: DocumentContainerRef[]; // where it was found inside (D231)
  text_origin?: TextOrigin; // D185
  ai?: DocumentAi | null; // its OCR result and open task (D189)
  ocr_readable?: boolean; // OCR can read it: "Text erkennen"
  duration?: number | null; // seconds of a recording, once transcribed (D293)
  transcript?: DocumentTranscript | null; // its transcript and open task (D296)
  transcribable?: boolean; // the transcriber can read it: "Transkribieren"
}

export type DocumentMetadataStatus =
  | "pending" // not read yet: the next import's metadata step reads it
  | "found"
  | "empty" // a format that can carry metadata, without any
  | "unsupported" // a format whose metadata Mailrobbe does not read
  | "too_large"
  | "failed";

/** A metadata value as found: a text, a count, a number (GPS) or a list of texts. */
export type MetadataValue = string | number | string[];

/** What the file says about itself (D167), every field as found and never rated, grouped by
 *  where it stands in the file: exif, gps, xmp, png, pdf, pdf_custom, office, office_custom,
 *  odf, odf_custom. Keys are stable English names (png and the *_custom sources keep the
 *  file's own); dates are ISO 8601 with the
 *  offset the file gives, or without one when it gives none. */
export interface DocumentMetadata {
  status: DocumentMetadataStatus;
  error: string | null; // English, technical
  fields: Record<string, Record<string, MetadataValue>>; // source -> key -> value
  summary: MetadataSummary | null; // the values the list filters by; null without fields
}

export interface DocumentText {
  text: string;
  truncated: boolean;
  text_status: DocumentTextStatus;
}

/** The search of the mail list whose words GET /api/mails/{id}/hits looks for (D176). */
export interface MailHitsParams {
  q?: string;
  scope?: SearchField[];
  whole_word?: boolean;
  body_part?: BodyPart; // D226
}

export interface AttachmentHit {
  attachment_id: number;
  /** One of its document's file names holds a word. */
  in_name: boolean;
  /** The text around the first place a word occurs as typed; null: only another form of a word
   *  occurs (German stemming), or only the name holds it. */
  snippet: string | null;
  /** Its document's text holds a word (D176). */
  in_text: boolean;
  /** That text was recognised by an AI run (D189). */
  machine?: boolean;
}

/** Where the full text words of a mail list's q occur in one mail (D79). */
export interface MailHits {
  /** The words and phrases as typed, which the browser marks; [] without any. */
  words: string[];
  /** The lexemes of the query (German stems, lower case, no umlauts); the browser marks the
   *  words they begin. */
  stems: string[];
  /** The mail's own subject or text holds a word. */
  in_mail: boolean;
  /** The attachments whose document holds a word, in mail order. */
  attachments: AttachmentHit[];
  /** Mark whole words only (D173); stems is then []. */
  whole_word: boolean;
  /** The subject holds a word (D176). */
  in_subject: boolean;
  /** The mail's own text holds a word. */
  in_body: boolean;
  /** As MailListItem.hits; null without full text words. */
  counts: MailHitCounts | null;
}

/** GET /api/documents/metadata-values: the authors or programs of the filtered documents whose
 *  value holds search (D167), for the search within a facet. */
export interface MetadataValueParams extends DocumentFilters {
  field: "author" | "program";
  search?: string;
  limit?: number; // at most 100
}

export interface MetadataValues {
  values: MetadataValueCount[] | null; // most documents first; null: ran out of time
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
  skip_domains: string[]; // fetch without domains: every domain concerned but these
  workers: number;
  archive_url: string | null; // fetch: the key archive asked
}

/** Done, total, rate and remaining time of each phase are its steps' (D110). */
export interface DkimKeysProgress extends RunProgress {
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
  done: boolean; // answered by the interrupted fetch a fetch over every domain continues (D107)
}

export interface KeyArchivePreview {
  url: string | null; // null: switched off
  domains: ArchiveDomain[]; // most mails first
  skipped: string[]; // reserved TLDs, sent only to an archive on this machine
  continues: string | null; // start of the interrupted fetch a new one goes on with (D107)
}

/** Names or domains one run request names; "every" needs no list (D107). */
export const RUN_LIST_LIMIT = 1000;

export interface DkimKeysRunRequest {
  task: DkimKeysTask;
  names?: string[];
  domains?: string[]; // fetch: only these
  skip_domains?: string[]; // fetch without domains: every domain concerned but these
  workers?: number | null;
}

// Timeline (milestone 11, D90 to D95) -----------------------------------------------------------

export const MAX_TIMELINE_BUCKETS = 1_500;
export const TIMELINE_SERIES = 6;
export const MAX_TIMELINE_SERIES = 12;
export const MAX_TIMELINE_TERMS = 6;
export const FIRST_MENTIONS = 100;
export const MAX_FIRST_MENTIONS = 500;

/** UTC day, ISO week (Monday to Sunday) or calendar month. */
export type TimelineBucket = "day" | "week" | "month";
export type TimelineSplit = "none" | "person" | "thread" | "term";
export type OutlierKind = "high" | "low";
export type FirstMentionRole = "any" | "sent";

export interface TimelineParams extends MailFilters {
  bucket?: TimelineBucket; // absent: chosen by the span of the axis (D91)
  split?: TimelineSplit;
  split_id?: number[]; // split person/thread: these, in order; absent: the top `series` (D92)
  term?: string[]; // split term: search strings in the syntax of q, at most MAX_TIMELINE_TERMS
  series?: number; // 1 to MAX_TIMELINE_SERIES, default TIMELINE_SERIES
}

export interface TimelineOutlier {
  index: number; // into Timeline.starts
  kind: OutlierKind;
  expected: number; // the moving mean it was compared with (D93)
}

export interface TimelineSeries {
  key: string; // "all", "person:<id>", "thread:<id>", "term:<index>"
  label: string | null; // person name or address, thread subject, search string; null: total
  person: PersonRef | null;
  thread_id: number | null;
  term: string | null;
  counts: number[]; // aligned with Timeline.starts
  total: number;
  outliers: TimelineOutlier[];
  silent_from: string | null; // YYYY-MM-DD, first day of the silent stretch (D93)
}

export interface Timeline {
  bucket: TimelineBucket;
  coarsened: boolean;
  starts: string[]; // YYYY-MM-DD, first day of every bucket, ascending, without gaps
  total: TimelineSeries | null; // null: out of time
  series: TimelineSeries[];
  undated: number | null;
  archive_end: string | null; // YYYY-MM-DD
  timed_out: boolean;
}

export interface FirstMentionParams extends MailFilters {
  role?: FirstMentionRole;
  limit?: number;
  lists?: boolean; // also lists and automated senders
}

export interface FirstMention {
  person: PersonRef; // the root person
  kind: PersonKind | null;
  role: ParticipationRole;
  date: string;
  mail_id: number;
  subject: string | null;
  mails: number;
}

export interface FirstMentions {
  items: FirstMention[]; // earliest first
  persons: number | null; // null: out of time
  timed_out: boolean;
}

// Entities (milestone 10, D80 to D89) -------------------------------------------------------

export const FACET_MAILS = 10_000;
export const FACET_LIMIT = 8;
export const MAX_FACET_LIMIT = 50;
export const ENTITY_REFS_LIMIT = 100;

export type EntityKind =
  | "amount"
  | "iban"
  | "account"
  | "organization"
  | "person"
  | "place"
  | "phone"
  | "email"
  | "url"
  | "domain"
  | "date"
  | "term";
/** What an amount, IBAN or account number is written next to (D82). */
export type EntityContextKey = "cash" | "donation" | "receipt";
export type EntitySort = "mails" | "recent" | "oldest" | "value" | "label";

export interface EntityRef {
  id: number;
  kind: EntityKind;
  label: string; // display form: "5.000,00 EUR", "DE89 3704 0044 0532 0130 00", "Muster GmbH"
  /** term: theme key; place: "city" or "country"; iban, phone: country code; url: host. */
  detail: string | null;
}

export interface EntityListParams {
  kind?: EntityKind[];
  q?: string; // part of the label, any case
  detail?: string;
  value_min?: number; // amounts, any currency
  value_max?: number;
  sort?: EntitySort;
  cursor?: string;
  limit?: number;
  page?: number; // a jump instead of a cursor (D193), as in MailListParams
  last?: boolean;
}

export interface EntityListItem extends EntityRef {
  value: number | null; // amount: the sum
  currency: string | null; // amount: EUR, USD, CHF, GBP, DEM
  mails: number; // duplicates not counted
  documents: number;
  first_date: string | null;
  last_date: string | null;
}

export interface EntityPage {
  items: EntityListItem[];
  next_cursor: string | null;
  prev_cursor: string | null;
  page?: number | null; // as MailPage.page (D193)
  /** With q, detail or a value bound: the matching entities, counted under the count budget
   *  of D19 (exact false: at least total; total null: even the bounded count ran out of time).
   *  Without them total is null, as EntitySummary.kinds counts the list (D193). */
  total?: number | null;
  exact?: boolean;
}

export interface EntitySummary {
  kinds: Record<EntityKind, number>;
  mails_waiting: number; // not scanned yet; the next import does
  documents_waiting: number;
}

export interface EntityCount {
  entity: EntityRef;
  mails: number;
}

export interface EntityFacetParams extends MailFilters {
  kind?: EntityKind[];
  limit?: number; // per kind
}

export interface EntityFacets {
  kinds: Partial<Record<EntityKind, EntityCount[]>>; // kinds with entities only
  mails: number | null; // null without filters: the whole archive
  sampled: boolean; // counted over FACET_MAILS of more matching mails
}

export interface EntityYear {
  year: number;
  mails: number;
}

export interface EntitySample {
  mail: ThreadMail;
  snippet: string | null;
  document_id: number | null; // found in this attachment's document
  document_name: string | null;
}

export interface EntityDetail extends EntityListItem {
  key: string;
  contexts: Record<EntityContextKey, number>;
  years: EntityYear[]; // oldest first
  senders: PersonCount[];
  sender_count: number;
  recipients: PersonCount[];
  recipient_count: number;
  related: EntityCount[];
  persons_sampled: boolean;
  samples: EntitySample[]; // earliest mentions first
  archive_person: PersonRef | null;
}

export interface MailEntity {
  entity: EntityRef;
  occurrences: number;
  context: EntityContextKey[];
  document_id: number | null; // found in this attachment's document
  document_name: string | null;
}

// Topics (milestone 13, D140 to D148) ------------------------------------------------------
//
// A term is a lexeme of the full text index with its most used spelling as label, which is
// also the word to search for (q). Figures count mails that are no duplicates, from their own
// subject and text (D140). Before the first topics phase (state.computed_at null) every list is
// empty.

export type TopicUnit = "month" | "quarter" | "year";
export const TOPIC_TERMS = 10; // default terms per period
export const TOPIC_PERIOD_TERMS = 30; // terms kept per period
export const TOPIC_SELECTION_TERMS = 30; // default terms of a selection
export const MAX_TOPIC_SELECTION_TERMS = 100;
export const TOPIC_SAMPLE = 5_000; // mails of a selection the terms are counted over at most

export interface TopicState {
  computed_at: string | null; // null: never; the next import computes them
  mails: number; // the archive's mails that are no duplicates, then
  terms: number;
  clusters: number;
}

export interface TopicTerm {
  term: string; // the lexeme; stable across computations
  label: string; // the spelling used most; the word to search for
  mails: number; // mails of the scope holding it (estimated when sampled)
  share: number; // of the scope's mails, 0 to 1
  rest_share: number; // of the other mails of the archive, 0 to 1
  ratio: number | null; // share / rest_share; null: no other mail holds it
  score: number; // G2 (D142)
  themes: string[]; // keys of the research themes whose word field holds the word
}

export interface TopicPeriodParams {
  unit?: TopicUnit;
  date_from?: string | null; // only periods overlapping these UTC days
  date_to?: string | null;
  limit?: number; // terms per period, up to TOPIC_PERIOD_TERMS
}

export interface TopicPeriod {
  start: string; // first day (UTC)
  end: string; // last day, inclusive, as date_to of the mail list
  mails: number;
  terms: TopicTerm[]; // standing out most first; may be empty
}

export interface TopicPeriods {
  state: TopicState;
  unit: TopicUnit;
  periods: TopicPeriod[]; // newest first; periods without mails left out
}

/** The terms of the mails of the mail list's filters (D144). */
export interface TopicTermParams extends MailFilters {
  limit?: number; // up to MAX_TOPIC_SELECTION_TERMS
}

export interface TopicTerms {
  state: TopicState;
  mails: number | null; // the selection's mails that are no duplicates; null: not counted in time
  counted: number; // mails the terms were counted over
  sampled: boolean; // counted over TOPIC_SAMPLE of more mails; figures are estimates
  terms: TopicTerm[]; // highest score first
  common: TopicTerm[]; // in more than half of the selection's mails (D142), most mails first
  timed_out: boolean;
}

export interface TopicClusterTerm {
  term: string;
  label: string;
  mails: number; // archive mails holding it
  weight: number; // its links inside the cluster (D145)
  themes: string[];
}

export interface TopicMonth {
  month: string; // first day (UTC)
  mails: number;
}

export interface TopicCluster {
  id: number; // valid until the next computation
  label: string; // its first three term labels
  query: string; // search string for q: its first five labels joined by "or"
  mails: number; // mails the query finds in their own text, no duplicates
  first_date: string | null;
  last_date: string | null;
  terms: TopicClusterTerm[]; // strongest first
  months: TopicMonth[]; // months with such mails, ascending
}

export interface TopicClusters {
  state: TopicState;
  clusters: TopicCluster[]; // most mails first
}

// Signals (milestone 12, D130 to D139) ----------------------------------------------------------
// A signal is a simple condition that holds for a mail (D132) or a person (D134) and points to
// something worth reading; it rates nothing. Figures count mails that are no duplicates, as of
// the last signals phase of an import (D135); filters and facets read the signals as they are.

/** The signals of a mail (enums.SignalKind without silent), in display order. */
export const MAIL_SIGNAL_KINDS = [
  "private",
  "internal_to_private",
  "private_to_internal",
  "private_alias",
  "bcc",
  "many_recipients",
  "forward",
  "forward_out",
  "night",
  "weekend",
  "encrypted_attachment",
  "password_separate",
  "encrypted_mail",
] as const;
export type MailSignalKind = (typeof MAIL_SIGNAL_KINDS)[number];
/** A signal of a mail: a kind, or the word field of a research theme ("term:<theme key>"). */
export type SignalKey = MailSignalKind | `term:${string}`;
export type SignalGroup =
  "addresses" | "recipients" | "time" | "attachments" | "wording" | "persons";

export interface SignalSettings {
  internal_domains: string[]; // MAILROBBE_INTERNAL_DOMAINS; empty: internal signals are off
  private_domains: number; // domains of private providers
  timezone: string; // MAILROBBE_TIMEZONE
  timezone_known: boolean; // PostgreSQL knows it; otherwise the signals phase fails
  night_from: number; // night from this hour (local time) ...
  night_to: number; // ... up to before this one
  many_recipients: number; // at least this many recipients in To, Cc and Bcc together
  forward_prefixes: string[]; // without the colon
}

export interface SignalInfo {
  key: SignalKey;
  group: SignalGroup;
  theme: string | null; // term signals: the theme's name
  available: boolean; // false: needs MAILROBBE_INTERNAL_DOMAINS, which is empty
  mails: number; // mails with it that are no duplicates
  persons: number; // root persons who sent such a mail
  senders: PersonCount[]; // who sent most of them, at most SIGNAL_SENDERS
}

export interface SilentPerson {
  person: PersonRef;
  since: string; // first day (UTC) of its first month without mail
  mails: number; // its mails in the six months before
}

/** The screen /auffaelligkeiten (D137). */
export interface SignalOverview {
  signals: SignalInfo[]; // every signal of a mail under the current rules, display order
  settings: SignalSettings;
  computed_at: string | null; // end of the last signals phase; null: none ran yet
  outdated: boolean; // the last phase applied other rules or word fields than the current ones
  mails: number; // mails that are no duplicates, the base of every share
  silent: SilentPerson[]; // most mails before their silence first, at most SILENT_LISTED
  silent_count: number;
  sender_domains: DomainCount[]; // without internal domains: a help for setting them
}

export interface SignalFacets {
  signals: Partial<Record<SignalKey, number>>; // signals with mails only
  mails: number | null; // null without filters (the last phase's figures)
  sampled: boolean;
}

/** One signal of one mail and what makes it hold (D137). */
export interface SignalReason {
  key: SignalKey;
  group: SignalGroup;
  theme: string | null;
  persons: PersonRef[]; // the participants it concerns
  local_time: string | null; // night, weekend: ISO 8601 with the zone's offset
  recipients: number | null; // many_recipients
  forward_prefix: string | null; // forward, forward_out: "WG"
  forwarded_mail: string | null; // forward, forward_out: an attached mail's file name
  terms: EntityRef[]; // term signals: the theme's terms found
  /** encrypted_attachment: the mail's protected documents; password_separate: the documents of
   *  other mails its password opened (D238). */
  documents?: DocumentRef[];
}

export interface MailSignals {
  signals: SignalReason[];
  timezone: string;
  computed_at: string | null;
}

export interface PersonSignalCount {
  key: SignalKey;
  group: SignalGroup;
  theme: string | null;
  mails: number; // mails it or one of its aliases sent with the signal
  archive_share: number | null; // the archive's share; null before a phase
}

export interface PersonSignals {
  sent: number; // mails it or one of its aliases sent, no duplicates
  signals: PersonSignalCount[];
  silent_since: string | null;
  silent_mails: number | null;
}

export const SIGNAL_SENDERS = 5;
export const SILENT_LISTED = 50;

// Hide rules (milestone 18, D221 to D223) -------------------------------------------------------

/** How a hide rule compares the subject (D204): holds the text, or starts with it; any case. */
export type SubjectMatch = "contains" | "starts";
export const HIDE_EXAMPLES = 5;
export const HIDE_SUGGESTIONS = 20;

/** The criteria of a hide rule (D221): every one given must hold, at least one is given. */
export interface HideRuleFields {
  name?: string | null; // the team's name for it; null: the UI describes the criteria
  sender?: string | null; // the sender's address, any case
  person_id?: number | null; // a person: every address of its root
  domain?: string | null; // the sender's domain or a subdomain of it, any case
  list_id?: string | null; // the List-Id as stored
  automated?: boolean; // sent automatically (D39)
  subject?: string | null; // compared by subject_match, any case
  subject_match?: SubjectMatch;
}

export interface HideRuleUpdate extends HideRuleFields {
  enabled?: boolean; // a disabled rule hides nothing and keeps its criteria
}

export interface HideRuleInfo {
  id: number;
  name: string | null;
  sender: string | null;
  person_id: number | null;
  domain: string | null;
  list_id: string | null;
  automated: boolean;
  subject: string | null;
  subject_match: SubjectMatch;
  enabled: boolean;
  person: PersonRef | null; // the person of person_id; null without one or when it is gone
  mails: number; // mails it matches, those D203 keeps visible included
  computed_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_by: string | null;
  updated_at: string;
}

export interface HideRuleList {
  rules: HideRuleInfo[]; // newest first
  hidden: number; // mails an enabled rule hides, without those D203 keeps visible
  kept: number; // mails an enabled rule matches that stay visible (D203)
}

/** What a rule would hide (D223), before it is saved. */
export interface HideRulePreview {
  mails: number;
  kept: number; // in an Akte, with a note, bookmarked or relevant: they stay visible
  with_terms: number; // with a word-field signal (term:*, D138)
  examples: MailListItem[]; // the newest HIDE_EXAMPLES
}

export type HideSuggestionKind = "list" | "sender";

/** A mailing list or an automated sender with many mails (D223). */
export interface HideSuggestion {
  kind: HideSuggestionKind;
  list_id: string | null;
  person: PersonRef | null;
  mails: number;
}

/** Why a mail is hidden (D222). */
export interface MailHiding {
  rules: HideRuleInfo[]; // the enabled rules matching it
  kept: boolean; // it stays visible all the same (D203)
}

// Standard blocks (milestone 18, D224 to D227) --------------------------------------------------

export type BlockState = "standard" | "dismissed";
export type BlockSort = "mails" | "recent";
export const BLOCK_SAMPLE_LIMIT = 2_000;
export const BLOCK_SENDERS = 50;

export interface BlockInfo {
  hash: string;
  sample: string; // one occurrence as written, at most BLOCK_SAMPLE_LIMIT characters
  standard: boolean; // applied by the last blocks step
  detected: boolean; // by the rule of D225; false: marked by hand
  override: boolean | null; // the team's choice (true marked, false taken back); null: none
  pending: boolean; // the choice differs from what the last blocks step applied
  mails: number; // mails holding it, duplicates left out
  senders: number;
  first_date: string | null;
  last_date: string | null;
}

export interface BlockListParams {
  state?: BlockState;
  q?: string;
  sort?: BlockSort;
  offset?: number;
  limit?: number;
}

export interface BlockPage {
  items: BlockInfo[];
  total: number;
}

/** Figures of the last blocks step and of the team's choices. */
export interface BlockSummary {
  blocks: number;
  detected: number;
  marked: number;
  dismissed: number;
  pending: number; // choices the next run applies
  mails: number; // mails holding at least one standard block
  waiting: number; // mails the paragraphs step has not split yet
  min_mails: number; // MAILROBBE_BLOCK_MIN_MAILS (D225)
  computed_at: string | null;
}

export interface BlockSender {
  person: PersonRef;
  mails: number;
}

export interface BlockDetail {
  block: BlockInfo;
  senders: BlockSender[]; // most mails first, at most BLOCK_SENDERS
  domains: DomainCount[];
}

/** The team's choice (D225): true marks a paragraph, false takes a detected one back, null
 *  removes the choice. sample is the paragraph as shown, needed when the blocks step has not
 *  counted it. */
export interface BlockOverrideUpdate {
  standard: boolean | null;
  sample?: string | null;
}

// Places (milestone 20, D240 to D249) ---------------------------------------------------------

export const PHOTO_POINT_LIMIT = 20_000; // photos PhotoPoints draws at most (D248)
export const TEXT_PLACE_LIMIT = 2_000; // places TextPlaces and EventPlaces draw at most
export const PHOTO_MAILS_LIMIT = 20;
export const PHOTO_LIST_LIMIT = 200;
export const PLACE_LOCATIONS_LIMIT = 5;
export const PLACE_EVENTS_LIMIT = 10;
export const DEVICE_LIMIT = 200;
export const RADIUS_LIMIT_KM = 200;
/** A compass direction in German, from the nearest town towards the photo. */
export type CompassDirection = "N" | "NO" | "O" | "SO" | "S" | "SW" | "W" | "NW";
export type PlaceDetailKind = "city" | "country";

/** The map's filters (D247): a photo shows when one mail carrying it meets the mail filters, a
 *  place when mails meeting them mention it, an invitation's place when its mail meets them; and
 *  the photo's own capture time (D241) and device. */
export interface PlaceParams extends MailFilters {
  taken_from?: string; // YYYY-MM-DD, UTC day of the capture time, inclusive
  taken_to?: string;
  device?: string; // exactly
}

export interface PhotoPoint {
  id: number; // document id
  lat: number;
  lon: number;
}

export interface PhotoPoints {
  points: PhotoPoint[]; // by document id, at most PHOTO_POINT_LIMIT
  total: number;
  truncated: boolean;
}

export interface PlaceMail {
  id: number;
  date: string | null;
  subject: string | null;
  sender: PersonRef | null;
  recipients: PersonRef[]; // at most RECIPIENT_PREVIEW
  recipient_count: number;
}

/** The town of the shipped lists nearest to a photo (D248), within 50 km. */
export interface NearestTown {
  name: string;
  region: string | null; // Bundesland, Kanton
  country: string; // ISO 3166-1 alpha-2
  distance_km: number;
  direction: CompassDirection | null; // null within 0.5 km of the town
}

/** GET /api/places/photos/{id}: one document with a position (D248). */
export interface PhotoDetail {
  document_id: number;
  attachment_id: number; // the occurrence /api/attachments/{id}/content reads it from
  name: string | null;
  mime_type: string;
  preview: PreviewKind | null;
  latitude: number;
  longitude: number;
  altitude: number | null; // metres
  taken_at: string | null; // the capture time (D241), UTC
  taken_text: string | null; // the capture time as found when the file gives no zone
  device: string | null;
  nearest: NearestTown | null;
  mails: PlaceMail[]; // earliest first, at most PHOTO_MAILS_LIMIT
  mail_count: number;
}

/** The photos around a point (lat and lon, nearest first) or, without a point, every photo
 *  matching the filters by capture time, earliest first. */
export interface PhotoListParams extends PlaceParams {
  lat?: number;
  lon?: number;
  radius_km?: number; // default 2, at most RADIUS_LIMIT_KM
  limit?: number; // default 50, at most PHOTO_LIST_LIMIT
}

export interface PhotoListItem {
  document_id: number;
  attachment_id: number;
  name: string | null;
  latitude: number;
  longitude: number;
  taken_at: string | null;
  device: string | null;
  distance_km: number | null; // from the point; null without one
  first_mail: PlaceMail | null; // the earliest mail carrying it that meets the filters
}

export interface PhotoList {
  items: PhotoListItem[];
  total: number;
  truncated: boolean;
}

export interface TextPlace {
  entity_id: number;
  label: string; // as the texts write it
  place: string; // what the point stands for
  detail: PlaceDetailKind;
  lat: number;
  lon: number;
  mails: number; // mails meeting the filters that mention it (of the sample when not exact)
}

export interface TextPlaces {
  places: TextPlace[]; // most mails first, at most TEXT_PLACE_LIMIT
  total: number;
  exact: boolean; // false: counted over FACET_MAILS of the matching mails (D87)
}

export interface PlaceEvent {
  event_id: number;
  mail_id: number;
  kind: EventKey;
  summary: string | null;
  location: string | null;
  starts_at: string | null; // UTC; null when the zone is unknown
  starts_local: string | null; // as written, without a zone
  all_day: boolean;
  uid: string | null;
}

export interface EventPlace {
  lat: number;
  lon: number;
  place: string;
  locations: string[]; // as written, most events first, at most PLACE_LOCATIONS_LIMIT
  events: number;
  first: string | null;
  last: string | null;
  samples: PlaceEvent[]; // the latest ones, at most PLACE_EVENTS_LIMIT
}

export interface EventPlaces {
  places: EventPlace[]; // most events first, at most TEXT_PLACE_LIMIT
  total: number;
}

/** What the places step found for place entities or invitation locations (D242, D243). */
export interface PlaceCounts {
  found: number;
  ambiguous: number;
  unknown: number;
  waiting: number; // not looked at yet: the next import run's step places
}

export interface DeviceCount {
  device: string;
  photos: number;
}

export interface PlaceSummary {
  photos: number;
  photos_dated: number;
  devices: DeviceCount[]; // most photos first, at most DEVICE_LIMIT
  texts: PlaceCounts;
  events: PlaceCounts;
  outdated: boolean; // the lists or rules changed since the last step places
  computed_at: string | null;
}

/** A town the overview map labels (D244). */
export interface TownLabel {
  name: string;
  lat: number;
  lon: number;
  population: number;
  country: string;
  capital: boolean;
}

/** (west, south, east, north) in decimal degrees. */
export type BBox = [number, number, number, number];
export type MapRegionKey = "de" | "at" | "ch" | "dach" | "view"; // view: the map's current view
export type MapDetailKey = "overview" | "streets" | "full";
export type MapPhase = "plan" | "download" | "finish";

export interface MapRegionInfo {
  key: MapRegionKey; // a preset region, never view
  bbox: BBox;
  sizes: Record<MapDetailKey, number>; // bytes on the build of size_hints_build
}

export interface MapDetailInfo {
  key: MapDetailKey;
  max_zoom: number;
}

/** The detail map in MAILROBBE_MAP_DIR (D245). */
export interface DetailMap {
  url: string; // /api/map/tiles/<file>, read by range requests
  region: MapRegionKey;
  bbox: BBox;
  detail: MapDetailKey;
  max_zoom: number;
  build: string | null;
  source_url: string;
  size: number;
  tiles: number;
  downloaded_at: string;
}

/** A download that stopped: the next run with the same options continues it (D246). */
export interface MapPartial {
  region: MapRegionKey;
  bbox: BBox;
  detail: MapDetailKey;
  build: string | null;
  bytes_done: number;
  bytes_total: number;
}

export interface MapOptions {
  region: MapRegionKey;
  detail: MapDetailKey;
  bbox: BBox;
  max_zoom: number;
  source: string;
}

export interface MapProgress extends RunProgress {
  source_url: string | null;
  build: string | null;
  tiles: number;
  bytes_total: number | null;
  bytes_done: number;
  continued_bytes: number; // downloaded by an earlier run this one continued
}

/** A run of `mailrobbe map download` (D246). */
export interface MapJob extends JobInfo {
  kind: "map";
  phase: MapPhase | null;
  options: MapOptions;
  progress: MapProgress;
}

export interface MapStatus {
  offered: boolean; // MAILROBBE_MAP_SOURCE is not off
  source_host: string | null;
  detail_map: DetailMap | null;
  partial: MapPartial | null;
  regions: MapRegionInfo[];
  details: MapDetailInfo[];
  size_hints_build: string;
  free_bytes: number | null;
  job: MapJob | null;
}

export interface MapDownloadRequest {
  region: MapRegionKey;
  detail: MapDetailKey;
  bbox?: BBox; // region view only
}

// AI services (milestone 15, D180 to D189) ------------------------------------------------------

export type TextOrigin = "extracted" | "ocr" | "transcript";
export type AiCapability = "vision";
export type AiProtocol = "openai" | "ollama";
export type AiLocality = "local" | "remote";
export type OcrEngine = "tesseract" | "vision";
/** What reads a selection: the OCR engines and the transcriber (D290). */
export type AiEngine = OcrEngine | "parakeet";
export type OcrEngineChoice = "auto" | "tesseract" | "vision";
export type AiTaskKind = "ocr" | "transcribe" | "summarize";
export type AiTaskStatus = "waiting" | "running" | "done" | "failed" | "cancelled";
export type AiResultState = "valid" | "replaced" | "discarded";
export type AiWorkList = "scanned" | "images" | "media";
export type AiPhase = "check" | "ocr" | "transcribe" | "entities" | "signals";

export const AI_QUEUE_LIMIT = 50_000; // documents one request may queue
export const AI_PAGE_SIZE = 50;

/** One configured service as the settings name it, not asked (D180, D181). */
export interface AiServiceInfo {
  capability: AiCapability;
  url: string; // without credentials
  model: string; // "" when not set
  protocol: AiProtocol | "auto";
  locality: AiLocality | null; // null: the URL can never name a service
  refused: string | null; // English: why the settings forbid it
  key: boolean; // a key is set (never shown)
}

export interface AiServiceModel {
  name: string;
  vision: boolean | null;
}

/** What asking a service and running its test found (ai.model.ServiceCheck). */
export interface ServiceCheck {
  capability: AiCapability;
  url: string;
  locality: AiLocality | null;
  refused: string | null;
  reachable: boolean | null; // null: not asked
  protocol: AiProtocol | null;
  models: AiServiceModel[];
  model: string;
  model_found: boolean | null; // null: the service lists no models
  test: "passed" | "failed" | null;
  test_detail: string | null; // English: what came back, or why it failed
  seconds: number | null;
  error: string | null; // English
  checked_at: string | null;
}

export interface AiEstimate {
  engine: AiEngine;
  model: string; // "" for Tesseract, the transcription model for parakeet
  seconds: number;
  estimated: boolean; // true: by the rule of thumb, "geschätzt"
  seconds_per_page: number; // 0 for the transcriber
  seconds_per_minute?: number | null; // the transcriber's, per minute of a recording
}

export interface AiWorkListInfo {
  key: AiWorkList;
  documents: number;
  pages: number; // pages known; an image counts as one
  without_pages: number; // documents whose pages are not known
  bytes: number;
  estimates: AiEstimate[]; // Tesseract always, the vision model when usable; media: parakeet
  engine: AiEngine; // the engine "auto" takes for this list
  minutes?: number; // media: minutes of the recordings whose length is known
  without_minutes?: number; // media: recordings of unknown length, one minute each
}

/** What an AI run works with (job.options of kind ai); the defaults of a start. */
export interface AiOptions {
  kinds: AiTaskKind[];
  ocr_engine: OcrEngineChoice;
  vision_model: string;
  max_pages: number;
  languages: string;
  uncertain: number;
  concurrency: number;
  tesseract_workers: number;
  documents: number[]; // only these documents' tasks (D280); empty: the whole queue
  vision_url: string; // "" without one
  vision_remote: boolean;
  max_minutes?: number; // of a recording per document and pass (D292)
  transcribe_threads?: number;
  transcribe_uncertain?: number; // lines below this mean token probability are uncertain
}

/** Live figures of an AI run; its pages are the ocr step's. */
export interface AiProgress extends RunProgress {
  queued: number;
  done: number;
  no_text: number;
  failed: number;
  tokens_in: number;
  tokens_out: number;
  current: string | null; // the file name in work
  unreachable_since: string | null; // a service did not answer since then (D184)
  minutes?: number; // of recordings transcribed by this run
  position?: number | null; // seconds reached in the recording in work
  duration?: number | null; // of the recording in work, once decoded
}

/** A run of `mailrobbe ai run` (D187). */
export interface AiJob extends JobInfo {
  kind: "ai";
  phase: AiPhase | null;
  options: AiOptions;
  progress: AiProgress;
}

export interface AiStatus {
  enabled: boolean; // OCR is always possible: Tesseract runs in the container
  vision: boolean; // a vision model is configured and allowed
  tesseract: boolean;
  ocr_languages: string;
  services: AiServiceInfo[];
  allow_remote: boolean;
  remote_token_budget: number;
  ocr_engine: OcrEngineChoice;
  queue: Record<AiTaskKind, Record<AiTaskStatus, number>>;
  work_lists: AiWorkListInfo[]; // scanned, then images
  remote_used: boolean; // "Gesendet" is shown
  job: AiJob | null;
  defaults: AiOptions;
  transcription?: AiTranscriptionInfo | null; // the transcriber (D290, D291)
}

/** The transcriber in the server's container (D290, D291): Parakeet and its files. */
export interface AiTranscriptionInfo {
  available: boolean; // its libraries are installed
  model: string;
  ready: boolean; // the files are in the model directory
  missing_bytes: number; // downloaded first by the next run that transcribes
  total_bytes: number;
  threads: number;
  max_minutes: number;
}

/** Exactly one of work_list, document_ids and filters (D186). */
export interface AiQueueRequest {
  work_list?: AiWorkList;
  document_ids?: number[];
  filters?: DocumentFilters;
  engine?: OcrEngineChoice;
  include_logos?: boolean;
  single?: boolean; // one document from its page: first in the queue
  start?: boolean; // with document_ids: a run for just these documents at once (D280)
  kind?: AiTaskKind; // only this kind; left out: OCR or transcription, what fits each document
}

/** What start did (D280): a run began; an AI run lives already and takes them next; another
 *  run (an import) keeps it from starting, so they wait in the queue. */
export type AiQueuedRun = "started" | "running" | "busy";

export interface AiQueued {
  queued: number;
  raised: number; // already open: priority and engine updated
  unreadable: number;
  logos: number; // images in many mails, left out
  run: AiQueuedRun | null; // with start, null without
}

export interface AiDocumentRef {
  id: number;
  name: string | null;
  kind: DocumentKind | null;
  pages: number | null;
  duration?: number | null; // seconds of a recording, once known
}

export interface AiTaskParams {
  status?: AiTaskStatus[];
  cursor?: string;
  limit?: number;
}

export interface AiTaskItem {
  id: number;
  kind: AiTaskKind;
  document: AiDocumentRef | null;
  engine: OcrEngineChoice;
  priority: number;
  status: AiTaskStatus;
  attempts: number;
  error: string | null; // English
  queued_by: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  pages_read: number;
  pages_total: number | null;
  result_id: number | null;
  seconds_read?: number | null; // transcribe: seconds of the recording read so far
}

export interface AiTaskPage {
  items: AiTaskItem[];
  next_cursor: string | null;
}

/** Retry or cancel: these tasks, or every one with all. */
export interface AiTaskAction {
  ids?: number[];
  all?: boolean;
}

export interface AiChanged {
  changed: number;
}

export interface AiResultParams {
  state?: AiResultState[];
  job_id?: number;
  cursor?: string;
  limit?: number;
}

export interface AiResultItem {
  id: number;
  kind: AiTaskKind;
  document: AiDocumentRef | null;
  engine: string; // tesseract, vision or mixed
  model: string | null;
  remote: boolean;
  pages_read: number;
  pages_text: number;
  pages_total: number | null;
  uncertain: number[];
  failed: number[];
  characters: number;
  seconds: number;
  state: AiResultState;
  created_at: string;
  job_id: number | null;
  discarded_by: string | null;
  discarded_at: string | null;
  duration?: number | null; // a transcript's; pages_* are 0 for it
  transcribed?: number | null; // seconds read
  segments?: number;
  uncertain_segments?: number;
}

export interface AiResultPage {
  items: AiResultItem[];
  next_cursor: string | null;
}

export interface AiSendLogParams {
  cursor?: string;
  limit?: number;
}

export interface AiSendItem {
  id: number;
  sent_at: string;
  service_url: string;
  kind: AiTaskKind;
  document: AiDocumentRef | null;
  bytes: number;
  job_id: number | null;
}

export interface AiSendLogPage {
  items: AiSendItem[];
  next_cursor: string | null;
  total: number;
}

export interface AiRunRequest {
  engine?: OcrEngineChoice;
  vision_model?: string;
  max_pages?: number;
  max_minutes?: number; // per recording (D292)
}

export interface DocumentAiResult {
  id: number;
  engine: string; // tesseract, vision or mixed
  model: string | null;
  remote: boolean;
  created_at: string;
  pages_total: number | null;
  pages_read: number;
  pages_text: number;
  uncertain: number[];
  failed: number[];
  characters: number; // 0: no writing found
}

export interface DocumentAiTask {
  id: number;
  status: AiTaskStatus; // waiting or running
  engine: OcrEngineChoice;
  pages_read: number;
}

export interface DocumentAi {
  result: DocumentAiResult | null;
  task: DocumentAiTask | null;
}

/** The valid transcript of a document's content (D296). */
export interface DocumentTranscriptResult {
  id: number;
  model: string;
  created_at: string;
  duration: number | null; // seconds of the recording
  transcribed: number | null; // seconds read: less than duration when cut at max_minutes
  segments: number;
  uncertain: number; // lines marked uncertain
  characters: number; // 0: nobody speaks
  audio: boolean; // false: the file has no sound at all
}

export interface DocumentTranscriptTask {
  id: number;
  status: AiTaskStatus; // waiting or running
  seconds_read: number;
}

export interface DocumentTranscript {
  result: DocumentTranscriptResult | null;
  task: DocumentTranscriptTask | null;
}

/** One line of a transcript (ai.model.TranscriptSegment), times in seconds. */
export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  confidence: number | null; // mean token probability, 0 to 1
  uncertain: boolean;
}

/** GET /api/documents/{id}/transcript (D296). */
export interface TranscriptView {
  result: DocumentTranscriptResult;
  segments: TranscriptSegment[]; // in time order
}

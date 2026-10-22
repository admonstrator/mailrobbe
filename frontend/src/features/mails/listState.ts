// The mail list's state lives in the URL: the query string uses the API's parameter names
// (MailListParams; lists repeated, booleans as "true", defaults left out), and its page as every
// list's (lib/paging.ts, D193): page=N or page=last to jump, a cursor to step, and limit.

import { buildQuery } from "../../api/client";
import {
  AREA_PATTERN,
  BLOCK_HASH_PATTERN,
  BODY_PARTS,
  EVENT_KEYS,
  MAIL_SIGNAL_KINDS,
  MIN_HITS_LIMIT,
  PAGE_SIZE,
  SEARCH_FIELDS,
  type BodyPart,
  type DkimKey,
  type EntityContextKey,
  type EventKey,
  type MailFilters,
  type MailHitsParams,
  type MailListParams,
  type MailOrderParams,
  type PersonRole,
  type ReviewKey,
  type SearchField,
  type SignalKey,
  type SortOrder,
} from "../../api/types";
import { DKIM_KEYS } from "../../lib/dkim";
import { pagingParams, pagingQuery, parsePaging, type PageNumber } from "../../lib/paging";
import { REVIEW_KEYS } from "../../lib/research";
import { amountParam } from "../entities/amount";
import { ENTITY_CONTEXTS } from "../entities/labels";

export interface ListState {
  q: string;
  dkim: DkimKey[];
  sender_domain: string[];
  date_from: string | null;
  date_to: string | null;
  has_attachment: boolean;
  in_thread: boolean;
  hide_duplicates: boolean;
  external: boolean;
  flagged: boolean;
  mbox_file: number | null;
  person: number[];
  between: number[];
  /** The role of the one person in `person` (D32); null: any role. */
  person_role: PersonRole | null;
  /** Research file (D55 to D58): review statuses, tag ids, Akte ids, "has a note". */
  review: ReviewKey[];
  tag: number[];
  collection: number[];
  has_note: boolean;
  /** Mails carrying this document (D75). */
  document: number | null;
  /** Mails of this thread (D95). */
  thread: number | null;
  /** Entities (D86): each of these is mentioned; an amount of at least amount_min (any
   *  currency) is mentioned; such an amount stands next to any of these contexts. */
  entity: number[];
  amount_min: number | null;
  amount_context: EntityContextKey[];
  /** Signals (D136): each of these holds for the mail. */
  signal: SignalKey[];
  /** Near duplicates (D153): one mail per group; the mails of one group. */
  collapse_near: boolean;
  near_group: number | null;
  /** Calendar invitations (D155): any of these kinds; the mails of one event (its UID). */
  event: EventKey[];
  event_uid: string | null;
  /** Options of q's full text words (D171 to D174): the places its free words are looked for,
   *  in the order of SEARCH_FIELDS (empty: everywhere, so all four are stored as none), whole
   *  words only, and the occurrences a mail needs at least. */
  scope: SearchField[];
  whole_word: boolean;
  min_hits: number | null;
  /** Milestone 18: hidden mails included (D222), the parts of the mail's own text searched
   *  (D226), the mails holding this paragraph (D227). */
  include_hidden: boolean;
  body_part: BodyPart;
  block: string | null;
  /** Milestone 20 (D248): the mail carries a photo inside this area of the map,
   *  "west,south,east,north". */
  photo_area: string | null;
  /** Milestone 17 (D309): a valid summary of the mail or of an attachment's document has each of
   *  these AI tags and a hint of each of these themes (keys of themes.toml). */
  ai_tag: number[];
  ai_theme: string[];
  sort: SortOrder;
  /** The page (D193): a step's cursor, the page's number or "last", the page size. */
  cursor: string | null;
  limit: number;
  page: PageNumber;
}

/** The parts of ListState a filter change may touch; cursor and page follow from them. */
export type FilterPatch = Partial<Omit<ListState, "cursor" | "page" | "limit">>;

export const DEFAULT_LIST_STATE: ListState = {
  q: "",
  dkim: [],
  sender_domain: [],
  date_from: null,
  date_to: null,
  has_attachment: false,
  in_thread: false,
  hide_duplicates: false,
  external: false,
  flagged: false,
  mbox_file: null,
  person: [],
  between: [],
  person_role: null,
  review: [],
  tag: [],
  collection: [],
  has_note: false,
  document: null,
  thread: null,
  entity: [],
  amount_min: null,
  amount_context: [],
  signal: [],
  collapse_near: false,
  near_group: null,
  event: [],
  event_uid: null,
  scope: [],
  whole_word: false,
  min_hits: null,
  include_hidden: false,
  body_part: "clean",
  block: null,
  photo_area: null,
  ai_tag: [],
  ai_theme: [],
  sort: "date_desc",
  cursor: null,
  limit: PAGE_SIZE,
  page: 1,
};

const BOOLEAN_KEYS = [
  "has_attachment",
  "in_thread",
  "hide_duplicates",
  "external",
  "flagged",
  "collapse_near",
] as const;
export const PERSON_ROLES: readonly PersonRole[] = ["sent", "received", "cc"];

export function positiveInt(value: string | null, max = Number.MAX_SAFE_INTEGER): number | null {
  if (value === null || !/^\d+$/.test(value)) return null;
  const n = Number(value);
  return n >= 1 && n <= max ? n : null;
}

export function isDay(value: string | null): value is string {
  if (value === null || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
}

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}

function ids(search: URLSearchParams, key: string): number[] {
  return unique(search.getAll(key).flatMap((v) => positiveInt(v) ?? []));
}

/** A signal of a mail as the filter takes it: a kind, or "term:" and a theme key (D132). Which
 *  themes exist the API knows; an unknown one is its invalid_filter. */
export function isSignalKey(value: string): value is SignalKey {
  return (
    (MAIL_SIGNAL_KINDS as readonly string[]).includes(value) || /^term:[a-z0-9_-]+$/.test(value)
  );
}

/** A theme key as ai_theme takes it (D309); which themes exist the API knows, an unknown one is
 *  its invalid_filter. */
export function isThemeKey(value: string): boolean {
  return /^[a-z0-9_-]+$/.test(value);
}

/** An area of the map as photo_area takes it (D248): west, south, east and north in degrees,
 *  south below north; west above east crosses the 180th meridian. */
export function isArea(value: string): boolean {
  if (!AREA_PATTERN.test(value)) return false;
  const [west, south, east, north] = value.split(",").map(Number);
  const longitude = (x: number) => x >= -180 && x <= 180;
  return longitude(west) && longitude(east) && south >= -90 && north <= 90 && south < north;
}

/** The places among values in the order of SEARCH_FIELDS, once each; all four is the same as
 *  none, both mean everywhere (D171). */
export function canonicalScope(values: readonly string[]): SearchField[] {
  const scope = SEARCH_FIELDS.filter((key) => values.includes(key));
  return scope.length === SEARCH_FIELDS.length ? [] : scope;
}

/** The list state a query string describes; values that cannot be used are ignored. */
export function parseListState(search: URLSearchParams): ListState {
  const state: ListState = { ...DEFAULT_LIST_STATE };
  state.q = search.get("q")?.trim() ?? "";
  state.dkim = DKIM_KEYS.filter((key) => search.getAll("dkim").includes(key));
  state.sender_domain = unique(
    search.getAll("sender_domain").flatMap((v) => v.trim().toLowerCase() || []),
  );
  const from = search.get("date_from");
  const to = search.get("date_to");
  state.date_from = isDay(from) ? from : null;
  state.date_to = isDay(to) ? to : null;
  for (const key of BOOLEAN_KEYS) state[key] = search.get(key) === "true";
  state.mbox_file = positiveInt(search.get("mbox_file"));
  state.person = ids(search, "person");
  state.between = ids(search, "between");
  const role = search.get("person_role");
  // The API takes a role only together with exactly one person.
  state.person_role =
    state.person.length === 1 ? (PERSON_ROLES.find((key) => key === role) ?? null) : null;
  state.review = REVIEW_KEYS.filter((key) => search.getAll("review").includes(key));
  state.tag = ids(search, "tag");
  state.collection = ids(search, "collection");
  state.has_note = search.get("has_note") === "true";
  state.document = positiveInt(search.get("document"));
  state.thread = positiveInt(search.get("thread"));
  state.entity = ids(search, "entity");
  state.amount_min = amountParam(search.get("amount_min"));
  state.amount_context = ENTITY_CONTEXTS.filter((key) =>
    search.getAll("amount_context").includes(key),
  );
  state.signal = unique(search.getAll("signal").filter(isSignalKey));
  state.near_group = positiveInt(search.get("near_group"));
  state.event = EVENT_KEYS.filter((key) => search.getAll("event").includes(key));
  state.event_uid = search.get("event_uid")?.trim() || null;
  state.scope = canonicalScope(search.getAll("scope"));
  state.whole_word = search.get("whole_word") === "true";
  state.min_hits = positiveInt(search.get("min_hits"), MIN_HITS_LIMIT);
  state.include_hidden = search.get("include_hidden") === "true";
  state.body_part = BODY_PARTS.find((part) => part === search.get("body_part")) ?? "clean";
  const block = search.get("block");
  state.block = block && BLOCK_HASH_PATTERN.test(block) ? block : null;
  const area = search.get("photo_area");
  state.photo_area = area && isArea(area) ? area : null;
  state.ai_tag = ids(search, "ai_tag");
  state.ai_theme = unique(search.getAll("ai_theme").filter(isThemeKey));
  const sort = search.get("sort");
  state.sort = sort === "date_asc" ? "date_asc" : "date_desc";
  return { ...state, ...parsePaging(search) };
}

/** The filters of state with the defaults left out: the same object for the same filters, so
 *  list and detail share their cached summary. */
export function toFilters(state: ListState): MailFilters {
  const filters: MailFilters = {};
  if (state.q) filters.q = state.q;
  if (state.dkim.length) filters.dkim = state.dkim;
  if (state.sender_domain.length) filters.sender_domain = state.sender_domain;
  if (state.date_from) filters.date_from = state.date_from;
  if (state.date_to) filters.date_to = state.date_to;
  for (const key of BOOLEAN_KEYS) if (state[key]) filters[key] = true;
  if (state.mbox_file !== null) filters.mbox_file = state.mbox_file;
  if (state.person.length) filters.person = state.person;
  if (state.between.length) filters.between = state.between;
  if (state.person_role) filters.person_role = state.person_role;
  if (state.review.length) filters.review = state.review;
  if (state.tag.length) filters.tag = state.tag;
  if (state.collection.length) filters.collection = state.collection;
  if (state.has_note) filters.has_note = true;
  if (state.document !== null) filters.document = state.document;
  if (state.thread !== null) filters.thread = state.thread;
  if (state.entity.length) filters.entity = state.entity;
  if (state.amount_min !== null) filters.amount_min = state.amount_min;
  if (state.amount_context.length) filters.amount_context = state.amount_context;
  if (state.signal.length) filters.signal = state.signal;
  if (state.near_group !== null) filters.near_group = state.near_group;
  if (state.event.length) filters.event = state.event;
  if (state.event_uid) filters.event_uid = state.event_uid;
  if (state.scope.length) filters.scope = state.scope;
  if (state.whole_word) filters.whole_word = true;
  if (state.min_hits !== null) filters.min_hits = state.min_hits;
  if (state.include_hidden) filters.include_hidden = true;
  if (state.body_part !== "clean") filters.body_part = state.body_part;
  if (state.block) filters.block = state.block;
  if (state.photo_area) filters.photo_area = state.photo_area;
  if (state.ai_tag.length) filters.ai_tag = state.ai_tag;
  if (state.ai_theme.length) filters.ai_theme = state.ai_theme;
  return filters;
}

export function toOrderParams(state: ListState): MailOrderParams {
  const params: MailOrderParams = toFilters(state);
  if (state.sort !== DEFAULT_LIST_STATE.sort) params.sort = state.sort;
  return params;
}

export function toListParams(state: ListState): MailListParams {
  return { ...toOrderParams(state), ...pagingParams(state) };
}

/** What GET /api/mails/{id}/hits needs of the list (D176): q, its places, whole words and the
 *  parts of the text (D226), the defaults left out. */
export function toHitsParams(state: ListState): MailHitsParams {
  const params: MailHitsParams = { q: state.q };
  if (state.scope.length) params.scope = state.scope;
  if (state.whole_word) params.whole_word = true;
  if (state.body_part !== "clean") params.body_part = state.body_part;
  return params;
}

/** The query string of state, the inverse of parseListState. */
export function listSearch(state: ListState): URLSearchParams {
  return buildQuery({ ...toOrderParams(state), ...pagingQuery(state) });
}

/** state with a filter changed; a new filter starts again at the first page, at its size. */
export function withFilters(state: ListState, patch: FilterPatch): ListState {
  return { ...state, ...patch, cursor: null, page: 1 };
}

/** The options of the search menu: those of q's full text words (D171 to D174, D226) and
 *  whether hidden mails are included (D222). */
export type SearchOptions = Pick<
  ListState,
  "scope" | "whole_word" | "min_hits" | "body_part" | "include_hidden"
>;

/** The search options of state, which a new search from the header keeps (D177). */
export function searchOptions(state: ListState): SearchOptions {
  return {
    scope: state.scope,
    whole_word: state.whole_word,
    min_hits: state.min_hits,
    body_part: state.body_part,
    include_hidden: state.include_hidden,
  };
}

/** state without any filter, keeping the search text and the sort order. */
export function withoutSidebarFilters(state: ListState): ListState {
  return { ...DEFAULT_LIST_STATE, q: state.q, sort: state.sort, limit: state.limit };
}

export function hasFilters(state: ListState): boolean {
  return Object.keys(toFilters(state)).length > 0;
}

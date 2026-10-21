// The mail list's state lives in the URL: the query string uses the API's parameter names
// (MailListParams; lists repeated, booleans as "true", defaults left out) plus the UI-only "page".

import { buildQuery } from "../../api/client";
import {
  PAGE_SIZE,
  type DkimKey,
  type EntityContextKey,
  type MailFilters,
  type MailListParams,
  type MailOrderParams,
  type PersonRole,
  type ReviewKey,
  type SortOrder,
} from "../../api/types";
import { DKIM_KEYS } from "../../lib/dkim";
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
  /** Entities (D86): each of these is mentioned; an amount of at least amount_min (any
   *  currency) is mentioned; such an amount stands next to any of these contexts. */
  entity: number[];
  amount_min: number | null;
  amount_context: EntityContextKey[];
  sort: SortOrder;
  cursor: string | null;
  limit: number;
  /** 1-based number of the page the cursor points to, for the "51–100" range. */
  page: number;
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
  entity: [],
  amount_min: null,
  amount_context: [],
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
] as const;
const MAX_LIMIT = 200;
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
  state.entity = ids(search, "entity");
  state.amount_min = amountParam(search.get("amount_min"));
  state.amount_context = ENTITY_CONTEXTS.filter((key) =>
    search.getAll("amount_context").includes(key),
  );
  const sort = search.get("sort");
  state.sort = sort === "date_asc" ? "date_asc" : "date_desc";
  state.cursor = search.get("cursor") || null;
  state.limit = positiveInt(search.get("limit"), MAX_LIMIT) ?? PAGE_SIZE;
  state.page = state.cursor ? (positiveInt(search.get("page")) ?? 1) : 1;
  return state;
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
  if (state.entity.length) filters.entity = state.entity;
  if (state.amount_min !== null) filters.amount_min = state.amount_min;
  if (state.amount_context.length) filters.amount_context = state.amount_context;
  return filters;
}

export function toOrderParams(state: ListState): MailOrderParams {
  const params: MailOrderParams = toFilters(state);
  if (state.sort !== DEFAULT_LIST_STATE.sort) params.sort = state.sort;
  return params;
}

export function toListParams(state: ListState): MailListParams {
  const params: MailListParams = toOrderParams(state);
  if (state.cursor) params.cursor = state.cursor;
  if (state.limit !== PAGE_SIZE) params.limit = state.limit;
  return params;
}

/** The query string of state, the inverse of parseListState. */
export function listSearch(state: ListState): URLSearchParams {
  return buildQuery({
    ...toListParams(state),
    page: state.cursor && state.page > 1 ? state.page : null,
  });
}

/** state with a filter changed; a new filter starts again at the first page. */
export function withFilters(state: ListState, patch: FilterPatch): ListState {
  return { ...state, ...patch, cursor: null, page: 1 };
}

/** state without any filter, keeping the search text and the sort order. */
export function withoutSidebarFilters(state: ListState): ListState {
  return { ...DEFAULT_LIST_STATE, q: state.q, sort: state.sort, limit: state.limit };
}

export function hasFilters(state: ListState): boolean {
  return Object.keys(toFilters(state)).length > 0;
}

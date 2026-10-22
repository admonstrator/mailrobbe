// The document screens keep their state in the URL, so a search can be bookmarked and shared:
// the list (/anhaenge) with the API's parameter names (DocumentListParams; lists repeated,
// booleans as "true", defaults left out), and the mail list of a document page (/anhaenge/:id:
// its page alone). Pages as every list's (lib/paging.ts, D193).

import { buildQuery } from "../../api/client";
import {
  PAGE_SIZE,
  type DocumentFilters,
  type DocumentKind,
  type DocumentListParams,
  type DocumentProtection,
  type DocumentSort,
  type DocumentTextStatus,
  type TextOrigin,
} from "../../api/types";
import { FIRST_PAGE, pagingParams, pagingQuery, parsePaging, type Paging } from "../../lib/paging";
import {
  DEFAULT_LIST_STATE,
  isDay,
  listSearch,
  positiveInt,
  type ListState,
} from "../mails/listState";
import { DOCUMENT_KINDS, PROTECTIONS, TEXT_ORIGINS, TEXT_STATUSES } from "./labels";

export type DocumentPersonRole = NonNullable<DocumentFilters["person_role"]>;

export interface DocumentListState extends Paging {
  q: string;
  name: string;
  kind: DocumentKind[];
  text_status: DocumentTextStatus[];
  /** Locked or opened with a password (D233): any of these. */
  protection: DocumentProtection[];
  date_from: string | null;
  date_to: string | null;
  person: number | null;
  /** How the person took part; null: sent or received. */
  person_role: DocumentPersonRole | null;
  shared: boolean;
  external: boolean;
  /** What the files say about themselves (D167): any of these authors and programs, exact. */
  author: string[];
  program: string[];
  /** Where the text comes from (D185): the file, a text recognition, a transcript. */
  text_origin: TextOrigin[];
  sort: DocumentSort;
}

/** The parts a filter change may touch; cursor and page follow from them. */
export type DocumentFilterPatch = Partial<Omit<DocumentListState, "cursor" | "page" | "limit">>;

export const DEFAULT_DOCUMENT_LIST_STATE: DocumentListState = {
  q: "",
  name: "",
  kind: [],
  text_status: [],
  protection: [],
  date_from: null,
  date_to: null,
  person: null,
  person_role: null,
  shared: false,
  external: false,
  author: [],
  program: [],
  text_origin: [],
  sort: "recent",
  cursor: null,
  page: 1,
  limit: PAGE_SIZE,
};

const SORTS: readonly DocumentSort[] = ["recent", "oldest", "mails", "size"];
const ROLES: readonly DocumentPersonRole[] = ["sent", "received"];

/** The list state a query string describes; values that cannot be used are ignored. */
export function parseDocumentListState(search: URLSearchParams): DocumentListState {
  const from = search.get("date_from");
  const to = search.get("date_to");
  const person = positiveInt(search.get("person"));
  const role = search.get("person_role");
  return {
    ...parsePaging(search),
    q: search.get("q")?.trim() ?? "",
    name: search.get("name")?.trim() ?? "",
    kind: DOCUMENT_KINDS.filter((kind) => search.getAll("kind").includes(kind)),
    text_status: TEXT_STATUSES.filter((status) => search.getAll("text_status").includes(status)),
    protection: PROTECTIONS.filter((value) => search.getAll("protection").includes(value)),
    date_from: isDay(from) ? from : null,
    date_to: isDay(to) ? to : null,
    person,
    // A role only means something together with a person.
    person_role: person === null ? null : (ROLES.find((key) => key === role) ?? null),
    shared: search.get("shared") === "true",
    external: search.get("external") === "true",
    author: metadataValues(search.getAll("author")),
    program: metadataValues(search.getAll("program")),
    text_origin: TEXT_ORIGINS.filter((origin) => search.getAll("text_origin").includes(origin)),
    sort: SORTS.find((sort) => sort === search.get("sort")) ?? "recent",
  };
}

/** Exact values as the facets list them: each once, empty ones dropped. */
function metadataValues(values: string[]): string[] {
  return [...new Set(values.filter((value) => value.trim() !== ""))];
}

/** The filters of state with the defaults left out: the same object for the same filters, so
 *  equal summaries are asked for once. */
export function toDocumentFilters(state: DocumentListState): DocumentFilters {
  const filters: DocumentFilters = {};
  if (state.q) filters.q = state.q;
  if (state.name) filters.name = state.name;
  if (state.kind.length) filters.kind = state.kind;
  if (state.text_status.length) filters.text_status = state.text_status;
  if (state.protection.length) filters.protection = state.protection;
  if (state.date_from) filters.date_from = state.date_from;
  if (state.date_to) filters.date_to = state.date_to;
  if (state.person !== null) filters.person = state.person;
  if (state.person !== null && state.person_role) filters.person_role = state.person_role;
  if (state.shared) filters.shared = true;
  if (state.external) filters.external = true;
  if (state.author.length) filters.author = state.author;
  if (state.program.length) filters.program = state.program;
  if (state.text_origin.length) filters.text_origin = state.text_origin;
  return filters;
}

function sorted(state: DocumentListState): DocumentListParams {
  const params: DocumentListParams = toDocumentFilters(state);
  if (state.sort !== "recent") params.sort = state.sort;
  return params;
}

export function toDocumentListParams(state: DocumentListState): DocumentListParams {
  return { ...sorted(state), ...pagingParams(state) };
}

/** The query string of state, the inverse of parseDocumentListState. */
export function documentListSearch(state: DocumentListState): URLSearchParams {
  return buildQuery({ ...sorted(state), ...pagingQuery(state) });
}

export function documentPath(id: number): string {
  return `/anhaenge/${id}`;
}

export function documentListHref(state: DocumentListState): string {
  const search = documentListSearch(state).toString();
  return search ? `/anhaenge?${search}` : "/anhaenge";
}

/** The document list of one author or one program (D167), as the document page links it. */
export function metadataListHref(field: "author" | "program", value: string): string {
  return documentListHref({ ...DEFAULT_DOCUMENT_LIST_STATE, [field]: [value] });
}

/** state with a filter changed; a new filter starts again at the first page. */
export function withDocumentFilters(
  state: DocumentListState,
  patch: DocumentFilterPatch,
): DocumentListState {
  return { ...state, ...patch, cursor: null, page: 1 };
}

/** state without the filter column's filters, keeping the search text and the sort. */
export function withoutDocumentFilters(state: DocumentListState): DocumentListState {
  return { ...DEFAULT_DOCUMENT_LIST_STATE, q: state.q, sort: state.sort, limit: state.limit };
}

export function hasDocumentFilters(state: DocumentListState): boolean {
  return Object.keys(toDocumentFilters(state)).length > 0;
}

/** The filters whose summary counts one group of checkboxes: all but the group's own, so its
 *  other values keep their counts while some are checked. */
export function facetFilters(
  filters: DocumentFilters,
  group: "kind" | "text_status" | "protection" | "author" | "program" | "text_origin",
): DocumentFilters {
  const rest = { ...filters };
  delete rest[group];
  return rest;
}

/** The page of a document's mail list: the URL of the document page holds only that. */
export type DocumentMailState = Paging;

export function parseDocumentMailState(search: URLSearchParams): DocumentMailState {
  return parsePaging(search);
}

export function documentMailSearch(state: DocumentMailState): URLSearchParams {
  return buildQuery(pagingQuery(state));
}

/** "Wer hat dieses Dokument wann an wen geschickt" (D75): the mail list of the mails carrying
 *  the document, oldest first, without duplicates as in the document's figures. */
export function documentMailList(documentId: number, state: DocumentMailState): ListState {
  return {
    ...DEFAULT_LIST_STATE,
    document: documentId,
    hide_duplicates: true,
    sort: "date_asc",
    cursor: state.cursor,
    page: state.page,
    limit: state.limit,
  };
}

/** The same list in the mail list, where it can be narrowed further or exported as CSV. */
export function documentMailsHref(documentId: number): string {
  const first = { ...FIRST_PAGE, limit: PAGE_SIZE };
  return `/mails?${listSearch(documentMailList(documentId, first))}`;
}

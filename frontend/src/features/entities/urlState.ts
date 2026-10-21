// The entity list (/entitaeten) keeps its state in the URL with the API's parameter names
// (EntityListParams; kinds repeated, defaults left out) plus the UI-only "page"; a tab is the
// kinds of its group. Also the links every screen uses to an entity and to its mails.

import { buildQuery } from "../../api/client";
import type { EntityKind, EntityListParams, EntitySort } from "../../api/types";
import {
  DEFAULT_LIST_STATE,
  listSearch,
  positiveInt,
  withFilters,
  type FilterPatch,
} from "../mails/listState";
import { amountParam } from "./amount";
import { ENTITY_GROUPS, ENTITY_KINDS, GROUP_KINDS, type EntityGroup } from "./labels";

export type EntityTab = EntityGroup | "all";

export interface EntityListState {
  tab: EntityTab;
  q: string;
  /** A theme's key on the terms' tab (D83). */
  detail: string | null;
  /** The value range of the amounts' tab, any currency. */
  value_min: number | null;
  value_max: number | null;
  sort: EntitySort;
  cursor: string | null;
  /** 1-based number of the page the cursor points to, for the "51–100" range. */
  page: number;
}

export type EntityListPatch = Partial<Omit<EntityListState, "cursor" | "page">>;

export const DEFAULT_ENTITY_LIST_STATE: EntityListState = {
  tab: "all",
  q: "",
  detail: null,
  value_min: null,
  value_max: null,
  sort: "mails",
  cursor: null,
  page: 1,
};

const SORTS: readonly EntitySort[] = ["mails", "recent", "oldest", "value", "label"];

/** The tab of the kinds a URL names: the group with exactly these kinds, or the one holding all
 *  of them (kind=iban alone opens Konten); "all" for none or a mix. */
function tabOf(kinds: EntityKind[]): EntityTab {
  if (kinds.length === 0) return "all";
  return (
    ENTITY_GROUPS.find((group) => kinds.every((kind) => GROUP_KINDS[group].includes(kind))) ?? "all"
  );
}

/** The list state a query string describes; values that cannot be used are ignored. Sorting by
 *  value and the value range belong to the amounts. */
export function parseEntityListState(search: URLSearchParams): EntityListState {
  const kinds = ENTITY_KINDS.filter((kind) => search.getAll("kind").includes(kind));
  const tab = tabOf(kinds);
  const amounts = tab === "amount";
  const sort = SORTS.find((key) => key === search.get("sort")) ?? "mails";
  const cursor = search.get("cursor") || null;
  return {
    tab,
    q: search.get("q")?.trim() ?? "",
    detail: search.get("detail")?.trim() || null,
    value_min: amounts ? amountParam(search.get("value_min")) : null,
    value_max: amounts ? amountParam(search.get("value_max")) : null,
    sort: sort === "value" && !amounts ? "mails" : sort,
    cursor,
    page: cursor ? (positiveInt(search.get("page")) ?? 1) : 1,
  };
}

/** The request of state with the defaults left out. */
export function toEntityListParams(state: EntityListState): EntityListParams {
  const params: EntityListParams = {};
  if (state.tab !== "all") params.kind = [...GROUP_KINDS[state.tab]];
  if (state.q) params.q = state.q;
  if (state.detail) params.detail = state.detail;
  if (state.value_min !== null) params.value_min = state.value_min;
  if (state.value_max !== null) params.value_max = state.value_max;
  if (state.sort !== "mails") params.sort = state.sort;
  if (state.cursor) params.cursor = state.cursor;
  return params;
}

/** The query string of state, the inverse of parseEntityListState. */
export function entityListSearch(state: EntityListState): URLSearchParams {
  return buildQuery({
    ...toEntityListParams(state),
    page: state.cursor && state.page > 1 ? state.page : null,
  });
}

export function entityListHref(state: EntityListState): string {
  const search = entityListSearch(state).toString();
  return search ? `/entitaeten?${search}` : "/entitaeten";
}

/** state with a filter changed, from the first page. Another tab drops what belongs to the
 *  previous one: the theme, the value range and the sort by value. */
export function withEntityFilters(state: EntityListState, patch: EntityListPatch): EntityListState {
  const next = { ...state, ...patch, cursor: null, page: 1 };
  if (patch.tab !== undefined && patch.tab !== state.tab) {
    next.detail = patch.detail ?? null;
    if (next.tab !== "amount") {
      next.value_min = null;
      next.value_max = null;
      if (next.sort === "value") next.sort = "mails";
    }
  }
  return next;
}

export function hasEntityFilters(state: EntityListState): boolean {
  return Boolean(state.q || state.detail || state.value_min !== null || state.value_max !== null);
}

export function entityPath(id: number): string {
  return `/entitaeten/${id}`;
}

/** The mail list filtered by these entities (D86), plus other filters. */
export function entityMailsHref(ids: number[], patch: FilterPatch = {}): string {
  return `/mails?${listSearch(withFilters(DEFAULT_LIST_STATE, { ...patch, entity: ids }))}`;
}

/** The mails of one UTC year that mention the entity; the API's date filters are UTC days. */
export function entityYearHref(id: number, year: number): string {
  return entityMailsHref([id], { date_from: `${year}-01-01`, date_to: `${year}-12-31` });
}

// The selector list (/import/selektoren) keeps its state in the URL like the other lists: the
// API's parameter names q and show, defaults left out, and the 1-based page instead of the
// offset.

import { buildQuery } from "../../api/client";
import { PAGE_SIZE, type SelectorFilter, type SelectorListParams } from "../../api/types";
import { positiveInt } from "../mails/listState";
import { SELECTOR_FILTERS } from "./labels";

export const SELECTOR_LIST_PATH = "/import/selektoren";

export interface SelectorListState {
  q: string;
  show: SelectorFilter;
  page: number;
}

export const DEFAULT_SELECTOR_LIST_STATE: SelectorListState = { q: "", show: "open", page: 1 };

/** The list state a query string describes; values that cannot be used are ignored. */
export function parseSelectorListState(search: URLSearchParams): SelectorListState {
  return {
    q: search.get("q")?.trim() ?? "",
    show: SELECTOR_FILTERS.find((show) => show === search.get("show")) ?? "open",
    page: positiveInt(search.get("page")) ?? 1,
  };
}

/** The query string of state, the inverse of parseSelectorListState. */
export function selectorListSearch(state: SelectorListState): URLSearchParams {
  return buildQuery({
    q: state.q,
    show: state.show === "open" ? null : state.show,
    page: state.page > 1 ? state.page : null,
  });
}

export function selectorListHref(state: SelectorListState): string {
  const search = selectorListSearch(state).toString();
  return search ? `${SELECTOR_LIST_PATH}?${search}` : SELECTOR_LIST_PATH;
}

export function toSelectorListParams(state: SelectorListState): SelectorListParams {
  const params: SelectorListParams = {};
  if (state.q) params.q = state.q;
  if (state.show !== "open") params.show = state.show;
  if (state.page > 1) params.offset = (state.page - 1) * PAGE_SIZE;
  return params;
}

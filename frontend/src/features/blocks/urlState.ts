// The standard block list (/ausgeblendet/bloecke) keeps its state in the URL like the other
// lists: the API's parameter names q, state and sort, defaults left out, and the 1-based page
// instead of the offset.

import { buildQuery } from "../../api/client";
import { PAGE_SIZE, type BlockListParams, type BlockSort, type BlockState } from "../../api/types";
import { DEFAULT_LIST_STATE, listSearch, positiveInt, withFilters } from "../mails/listState";

export const BLOCKS_PATH = "/ausgeblendet/bloecke";

export const BLOCK_STATES: readonly BlockState[] = ["standard", "dismissed"];
export const BLOCK_SORTS: readonly BlockSort[] = ["mails", "recent"];

export interface BlockListState {
  q: string;
  state: BlockState;
  sort: BlockSort;
  page: number;
}

export const DEFAULT_BLOCK_LIST_STATE: BlockListState = {
  q: "",
  state: "standard",
  sort: "mails",
  page: 1,
};

/** The list state a query string describes; values that cannot be used are ignored. */
export function parseBlockListState(search: URLSearchParams): BlockListState {
  return {
    q: search.get("q")?.trim() ?? "",
    state: BLOCK_STATES.find((state) => state === search.get("state")) ?? "standard",
    sort: BLOCK_SORTS.find((sort) => sort === search.get("sort")) ?? "mails",
    page: positiveInt(search.get("page")) ?? 1,
  };
}

/** The query string of state, the inverse of parseBlockListState. */
export function blockListSearch(state: BlockListState): URLSearchParams {
  return buildQuery({
    q: state.q,
    state: state.state === "standard" ? null : state.state,
    sort: state.sort === "mails" ? null : state.sort,
    page: state.page > 1 ? state.page : null,
  });
}

export function blockListHref(state: BlockListState): string {
  const search = blockListSearch(state).toString();
  return search ? `${BLOCKS_PATH}?${search}` : BLOCKS_PATH;
}

export function toBlockListParams(state: BlockListState): BlockListParams {
  const params: BlockListParams = {};
  if (state.q) params.q = state.q;
  if (state.state !== "standard") params.state = state.state;
  if (state.sort !== "mails") params.sort = state.sort;
  if (state.page > 1) params.offset = (state.page - 1) * PAGE_SIZE;
  return params;
}

export function blockPath(hash: string): string {
  return `${BLOCKS_PATH}/${hash}`;
}

/** The mail list of the mails holding the block (filter block, D227). */
export function blockMailsHref(hash: string): string {
  return `/mails?${listSearch(withFilters(DEFAULT_LIST_STATE, { block: hash }))}`;
}

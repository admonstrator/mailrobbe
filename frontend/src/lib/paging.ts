// Paging with page numbers (D193), shared by every list. The URL says where a list is: page=N
// is a jump to page N, page=last the last page, and a cursor a step by Zurück or Weiter, with
// page=N the number of the page it reaches when that is known (a step from a last page read from
// the end does not know it). limit is the page size, PAGE_SIZE left out. A jump and the first
// page are answered with their number; a step keeps the number of the page it came from plus or
// minus one. Zurück from page 2 goes to the first page without a cursor, as the list starts.
//
// Pages are numbered as far as the list's total is known: all of them with an exact total, the
// ones the lower bound fills with "mehr als 10.000" (D19), whose last page is then the last
// `limit` rows read from the end and has no number.

import { PAGE_SIZE } from "../api/types";
import type { PaginationProps } from "../components/Pagination";
import { formatNumber } from "./format";

export const PAGE_SIZES: readonly number[] = [25, 50, 100, 200];
export const MAX_LIMIT = 200;

/** Which page: its number from 1, "last" for the last page read from the end, or null for a
 *  page a step reached whose number is not known. */
export type PageNumber = number | "last" | null;

export interface Paging {
  cursor: string | null;
  page: PageNumber;
  limit: number;
}

/** The first page of a list, at any page size. */
export const FIRST_PAGE = { cursor: null, page: 1 } as const;

/** What a list knows of its length: count rows, or with exact false at least count. */
export interface Total {
  count: number;
  exact: boolean;
}

function whole(value: string | null, max = Number.MAX_SAFE_INTEGER): number | null {
  if (value === null || !/^\d+$/.test(value)) return null;
  const n = Number(value);
  return n >= 1 && n <= max ? n : null;
}

/** The paging a query string describes; values that cannot be used are left at the defaults. */
export function parsePaging(search: URLSearchParams): Paging {
  const cursor = search.get("cursor") || null;
  const page = search.get("page");
  return {
    cursor,
    page: cursor ? whole(page) : page === "last" ? "last" : (whole(page) ?? 1),
    limit: whole(search.get("limit"), MAX_LIMIT) ?? PAGE_SIZE,
  };
}

/** The paging part of a query string for buildQuery, defaults left out; the inverse of
 *  parsePaging. */
export function pagingQuery(state: Paging): {
  cursor: string | null;
  limit: number | null;
  page: number | "last" | null;
} {
  const numbered = typeof state.page === "number" && state.page > 1 ? state.page : null;
  return {
    cursor: state.cursor,
    limit: state.limit === PAGE_SIZE ? null : state.limit,
    page: !state.cursor && state.page === "last" ? "last" : numbered,
  };
}

/** The paging of a request: the cursor of a step, or the page or the last page to jump to,
 *  defaults left out. */
export function pagingParams(state: Paging): {
  cursor?: string;
  page?: number;
  last?: boolean;
  limit?: number;
} {
  const params: { cursor?: string; page?: number; last?: boolean; limit?: number } = {};
  if (state.cursor) params.cursor = state.cursor;
  else if (state.page === "last") params.last = true;
  else if (typeof state.page === "number" && state.page > 1) params.page = state.page;
  if (state.limit !== PAGE_SIZE) params.limit = state.limit;
  return params;
}

/** The number of the page shown: the answer's for a jump and the first page, else the step's. */
export function shownPage(state: Paging, answered: number | null | undefined): number | null {
  if (answered !== null && answered !== undefined) return answered;
  return typeof state.page === "number" ? state.page : null;
}

/** "mehr als 10.000" for a lower bound. */
export function totalText(total: Total): string {
  return total.exact ? formatNumber(total.count) : `mehr als ${formatNumber(total.count)}`;
}

/** "51–100 von 12.345"; "die letzten 50 von mehr als 10.000" on a last page without a number;
 *  "50 von …" after a step whose number is not known. */
export function rangeText(
  page: number | null,
  last: boolean,
  limit: number,
  count: number,
  total: Total | null,
): string {
  const of = total ? ` von ${totalText(total)}` : "";
  if (page === null) return `${last ? "die letzten " : ""}${formatNumber(count)}${of}`;
  const first = (page - 1) * limit + 1;
  return `${formatNumber(first)}–${formatNumber(first + count - 1)}${of}`;
}

/** The pages a list numbers: all with an exact total, else those its lower bound fills, more
 *  telling that the list goes on after them. */
export function pageCount(total: Total, limit: number): { pages: number; more: boolean } {
  return total.exact
    ? { pages: Math.max(1, Math.ceil(total.count / limit)), more: false }
    : { pages: Math.max(1, Math.floor(total.count / limit)), more: true };
}

/** The first and the last page of state's list, which every list reaches without counting:
 *  the way out of a jump too far (PageTooFar). */
export function edgePages<S extends Paging>(
  state: S,
  href: (state: S) => string,
): { first: string; last: string } {
  return {
    first: href({ ...state, ...FIRST_PAGE }),
    last: href({ ...state, cursor: null, page: "last" }),
  };
}

/** What a list answered about one page. */
export interface PageAnswer {
  next_cursor: string | null;
  prev_cursor: string | null;
  page?: number | null;
}

/** The Pagination of a list's page: range, steps, first and last page, the page numbers, the
 *  jump and the page size. href turns a state into the list's URL, total is what the list knows
 *  of its length (null: nothing). */
export function listPagination<S extends Paging>(
  state: S,
  answer: PageAnswer,
  count: number,
  total: Total | null,
  href: (state: S) => string,
): PaginationProps {
  const current = shownPage(state, answer.page);
  const at = (page: PageNumber, cursor: string | null = null) => href({ ...state, cursor, page });
  const counted = total && pageCount(total, state.limit);
  // The last page by number where the total is exact, else read from the end (D193).
  const lastPage = counted && !counted.more ? counted.pages : "last";
  return {
    range: rangeText(current, state.page === "last", state.limit, count, total),
    prev: answer.prev_cursor
      ? current === 2
        ? at(1)
        : at(current && current - 1, answer.prev_cursor)
      : null,
    next: answer.next_cursor ? at(current && current + 1, answer.next_cursor) : null,
    first: answer.prev_cursor ? at(1) : null,
    last: answer.next_cursor ? at(lastPage) : null,
    numbers: counted
      ? {
          current,
          pages: Math.max(counted.pages, current ?? 0),
          more: counted.more,
          href: (page) => at(page),
        }
      : undefined,
    size: {
      limit: state.limit,
      href: (limit) => href({ ...state, ...FIRST_PAGE, limit }),
    },
  };
}

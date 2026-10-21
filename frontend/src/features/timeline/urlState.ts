// The timeline keeps its state in the URL (D90), so a link from another screen opens exactly
// that view: the mail list's filters with the mail list's parameter names, parsed and written by
// features/mails/listState.ts so every filter carries over, plus the timeline's own bucket,
// split, split_id and term and the first mentions' role and lists. Defaults are left out.

import { buildQuery } from "../../api/client";
import {
  FIRST_MENTIONS,
  MAX_TIMELINE_SERIES,
  MAX_TIMELINE_TERMS,
  type FirstMentionParams,
  type FirstMentionRole,
  type TimelineBucket,
  type TimelineParams,
  type TimelineSeries,
  type TimelineSplit,
} from "../../api/types";
import {
  DEFAULT_LIST_STATE,
  listSearch,
  parseListState,
  positiveInt,
  toFilters,
  withFilters,
  type ListState,
} from "../mails/listState";
import { bucketRange } from "./buckets";

export interface TimelineState {
  /** The mail list's filters; sort, cursor and page stay the mail list's defaults. */
  list: ListState;
  /** null: chosen by the span of the axis (D91). */
  bucket: TimelineBucket | null;
  split: TimelineSplit;
  /** Split person or thread: these, in order; empty: the six with the most matches (D92). */
  split_id: number[];
  /** Split term: search strings in the syntax of q. */
  term: string[];
  /** First mentions: "sent" counts only mails the person sent (D94). */
  role: FirstMentionRole;
  /** First mentions: also lists and automated senders. */
  lists: boolean;
}

export const DEFAULT_TIMELINE_STATE: TimelineState = {
  list: DEFAULT_LIST_STATE,
  bucket: null,
  split: "none",
  split_id: [],
  term: [],
  role: "any",
  lists: false,
};

export const TIMELINE_BUCKETS: readonly TimelineBucket[] = ["day", "week", "month"];
export const TIMELINE_SPLITS: readonly TimelineSplit[] = ["none", "person", "thread", "term"];

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}

/** Whether a split is chosen by ids (persons, threads) rather than by search strings. */
function splitById(split: TimelineSplit): boolean {
  return split === "person" || split === "thread";
}

/** The timeline state a query string describes; values that cannot be used are ignored, and so
 *  are ids and terms of a split that does not use them. */
export function parseTimelineState(search: URLSearchParams): TimelineState {
  const split = TIMELINE_SPLITS.find((key) => key === search.get("split")) ?? "none";
  const bucket = search.get("bucket");
  return {
    list: {
      ...parseListState(search),
      sort: DEFAULT_LIST_STATE.sort,
      cursor: null,
      limit: DEFAULT_LIST_STATE.limit,
      page: 1,
    },
    bucket: TIMELINE_BUCKETS.find((key) => key === bucket) ?? null,
    split,
    split_id: splitById(split)
      ? unique(search.getAll("split_id").flatMap((v) => positiveInt(v) ?? [])).slice(
          0,
          MAX_TIMELINE_SERIES,
        )
      : [],
    term:
      split === "term"
        ? unique(search.getAll("term").flatMap((v) => v.trim() || [])).slice(0, MAX_TIMELINE_TERMS)
        : [],
    role: search.get("role") === "sent" ? "sent" : "any",
    lists: search.get("lists") === "true",
  };
}

/** The request of the chart: the filters plus the timeline's own parameters, defaults left out. */
export function toTimelineParams(state: TimelineState): TimelineParams {
  const params: TimelineParams = toFilters(state.list);
  if (state.bucket) params.bucket = state.bucket;
  // Split term without a search string yet is the total alone.
  if (state.split !== "none" && (state.split !== "term" || state.term.length)) {
    params.split = state.split;
  }
  if (state.split_id.length) params.split_id = state.split_id;
  if (state.term.length) params.term = state.term;
  return params;
}

/** The request of the first mentions: the same filters, its toggles and the number to list. */
export function toFirstMentionParams(state: TimelineState, limit: number): FirstMentionParams {
  const params: FirstMentionParams = toFilters(state.list);
  if (state.role !== "any") params.role = state.role;
  if (limit !== FIRST_MENTIONS) params.limit = limit;
  if (state.lists) params.lists = true;
  return params;
}

/** The query string of state, the inverse of parseTimelineState. */
export function timelineSearch(state: TimelineState): URLSearchParams {
  // The split stays even without a search string, so the control keeps showing it.
  return buildQuery({
    ...toTimelineParams(state),
    split: state.split === "none" ? null : state.split,
    role: state.role === "sent" ? state.role : null,
    lists: state.lists,
  });
}

export function timelineHref(state: TimelineState): string {
  const search = timelineSearch(state).toString();
  return search ? `/zeitachse?${search}` : "/zeitachse";
}

/** The mail list of a list state, as the mail list writes it. */
export function mailListHref(list: ListState): string {
  const search = listSearch(list).toString();
  return search ? `/mails?${search}` : "/mails";
}

/** The list narrowed to a person as well; a role only holds for one person (D32). */
export function withPerson(list: ListState, personId: number): ListState {
  const person = list.person.includes(personId) ? list.person : [...list.person, personId];
  return withFilters(list, { person, person_role: person.length > 1 ? null : list.person_role });
}

/** q and one more search string, both of which must hold. */
function withSearch(q: string, more: string): string {
  return [q, more].filter(Boolean).join(" ");
}

/** The mails behind a bar: the filters, the bucket's days within their Zeitraum, and the
 *  condition of the series it belongs to (its person, thread or search string); null for the
 *  total. */
export function bucketList(
  state: TimelineState,
  start: string,
  bucket: TimelineBucket,
  series: TimelineSeries | null,
): ListState {
  let list = withFilters(state.list, bucketRange(start, bucket, state.list));
  if (series?.person) list = withPerson(list, series.person.person_id);
  if (series?.thread_id) list = withFilters(list, { thread: series.thread_id });
  if (series?.term) list = withFilters(list, { q: withSearch(list.q, series.term) });
  return list;
}

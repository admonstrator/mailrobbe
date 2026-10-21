// The topics screen keeps its state in the URL (D148), as the timeline does: the view, the unit
// of the periods, and the selection as the mail list's filters with the mail list's parameter
// names, parsed and written by features/mails/listState.ts, so the mail list, the timeline and
// the person profile open exactly their selection. Defaults are left out. The links of a term
// open the mail list or the timeline; the profile card uses this module too, so it stays small.

import { buildQuery } from "../../api/client";
import type { TopicUnit } from "../../api/types";
import {
  DEFAULT_LIST_STATE,
  listSearch,
  parseListState,
  toFilters,
  withFilters,
  type ListState,
} from "../mails/listState";
import { timelinePath } from "../timeline/buckets";

export type TopicView = "periods" | "selection" | "clusters";

export const TOPIC_VIEWS: readonly TopicView[] = ["periods", "selection", "clusters"];
export const TOPIC_UNITS: readonly TopicUnit[] = ["month", "quarter", "year"];

export interface TopicsState {
  view: TopicView;
  /** The periods' unit. */
  unit: TopicUnit;
  /** The selection: the mail list's filters; sort, cursor and page stay the list's defaults. */
  list: ListState;
}

export const DEFAULT_TOPICS_STATE: TopicsState = {
  view: "periods",
  unit: "month",
  list: DEFAULT_LIST_STATE,
};

/** The topics state a query string describes; values that cannot be used are ignored. Every
 *  part stays whatever the view, so switching views keeps the selection. */
export function parseTopicsState(search: URLSearchParams): TopicsState {
  return {
    view: TOPIC_VIEWS.find((key) => key === search.get("view")) ?? "periods",
    unit: TOPIC_UNITS.find((key) => key === search.get("unit")) ?? "month",
    list: {
      ...parseListState(search),
      sort: DEFAULT_LIST_STATE.sort,
      cursor: null,
      limit: DEFAULT_LIST_STATE.limit,
      page: 1,
    },
  };
}

/** The query string of state, the inverse of parseTopicsState: view and unit, then the
 *  filters. */
export function topicsSearch(state: TopicsState): URLSearchParams {
  return buildQuery({
    view: state.view === "periods" ? null : state.view,
    unit: state.unit === "month" ? null : state.unit,
    ...toFilters(state.list),
  });
}

export function topicsHref(state: TopicsState): string {
  const search = topicsSearch(state).toString();
  return search ? `/themen?${search}` : "/themen";
}

/** The Auswahl view for the filters of a list state: the link "Begriffe" of the mail list, the
 *  timeline and the person profile. */
export function selectionHref(list: ListState): string {
  return topicsHref({ ...DEFAULT_TOPICS_STATE, view: "selection", list });
}

/** Whether the filters select some of the archive's mails; hiding duplicates alone does not,
 *  since the terms never count duplicates (D140). */
export function hasSelection(list: ListState): boolean {
  return Object.keys(toFilters(withFilters(list, { hide_duplicates: false }))).length > 0;
}

/** A token of q as the search syntax splits it (api/query.py): quotes group. */
const TOKEN = /(?:[^\s"]+|"[^"]*(?:"|$))+/g;

/** q and a term's label, both of which must hold. q's alternatives ("Spende or Kasse") are
 *  joined by "or", which binds weaker than the words around it, so the label goes into every
 *  alternative: "Spende Vorstand or Kasse Vorstand". */
export function withTerm(q: string, label: string): string {
  const tokens = q.match(TOKEN) ?? [];
  const words = tokens.flatMap((token) => (token.toLowerCase() === "or" ? [label, token] : token));
  return [...words, label].join(" ");
}

/** The mail list of a list state, as the mail list writes it. */
export function mailsHref(list: ListState): string {
  const search = listSearch(list).toString();
  return search ? `/mails?${search}` : "/mails";
}

/** The mails of a term within a list state: the label added to q and duplicates hidden, so the
 *  list counts the mails the term counts (D140). */
export function termMailsHref(list: ListState, label: string): string {
  return mailsHref(withFilters(list, { q: withTerm(list.q, label), hide_duplicates: true }));
}

/** The timeline of a list state's mails, without duplicates, with a lane of their own for each
 *  of the labels beside the total, to compare them over time. */
export function termTimelineHref(list: ListState, labels: string[]): string {
  return timelinePath(toFilters(withFilters(list, { hide_duplicates: true })), {
    split: "term",
    term: labels,
  });
}

/** The days of a period as the mail list's Zeitraum. */
export function periodList(start: string, end: string): ListState {
  return withFilters(DEFAULT_LIST_STATE, { date_from: start, date_to: end });
}

/** The mails of a period's days, duplicates hidden, as the period counts them. */
export function periodMailsHref(start: string, end: string): string {
  return mailsHref(withFilters(periodList(start, end), { hide_duplicates: true }));
}

/** The timeline of a period's days, duplicates hidden. */
export function periodTimelineHref(start: string, end: string): string {
  return timelinePath({ date_from: start, date_to: end, hide_duplicates: true });
}

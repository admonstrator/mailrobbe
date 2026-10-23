// The persons screens keep their state in the URL: search, sort, page, tab and "Nur benannte"
// of the person list (/personen) with the view of the suggestions, and the mail card
// of a profile (/personen/:id: role, year, contact, search, page). Pages as every list's (D193).

import { buildQuery } from "../../api/client";
import {
  PAGE_SIZE,
  type PersonListParams,
  type PersonRole,
  type PersonSort,
  type SuggestionView,
} from "../../api/types";
import { pagingParams, pagingQuery, parsePaging, type Paging } from "../../lib/paging";
import { DEFAULT_LIST_STATE, PERSON_ROLES, positiveInt, type ListState } from "../mails/listState";

export type PersonsTab = "personen" | "vorschlaege" | "zusammengefuehrt";

const TABS: readonly PersonsTab[] = ["personen", "vorschlaege", "zusammengefuehrt"];

export interface PersonListState extends Paging {
  q: string;
  sort: PersonSort;
  tab: PersonsTab;
  /** Only persons the team named (D157). */
  labelled: boolean;
  /** What the suggestions tab shows: the certain suggestions, the uncertain ones (D160), or the
   *  pairs the text model judged one person (D323). */
  suggestions: SuggestionView;
}

export const DEFAULT_PERSON_LIST_STATE: PersonListState = {
  q: "",
  sort: "mails",
  cursor: null,
  page: 1,
  limit: PAGE_SIZE,
  tab: "personen",
  labelled: false,
  suggestions: "certain",
};

const SORTS: readonly PersonSort[] = ["mails", "name", "recent"];

export function parsePersonListState(search: URLSearchParams): PersonListState {
  return {
    ...parsePaging(search),
    q: search.get("q")?.trim() ?? "",
    sort: SORTS.find((sort) => sort === search.get("sort")) ?? "mails",
    tab: TABS.find((tab) => tab === search.get("tab")) ?? "personen",
    labelled: search.get("labelled") === "true",
    suggestions:
      search.get("ki") === "1" ? "ai" : search.get("unsicher") === "1" ? "uncertain" : "certain",
  };
}

/** The query string of state, defaults left out; the inverse of parsePersonListState. */
export function personListSearch(state: PersonListState): URLSearchParams {
  return buildQuery({
    tab: state.tab === "personen" ? null : state.tab,
    unsicher: state.suggestions === "uncertain" ? 1 : null,
    ki: state.suggestions === "ai" ? 1 : null,
    q: state.q,
    sort: state.sort === "mails" ? null : state.sort,
    labelled: state.labelled,
    ...pagingQuery(state),
  });
}

export function toPersonListParams(state: PersonListState): PersonListParams {
  const params: PersonListParams = {};
  if (state.q) params.q = state.q;
  if (state.sort !== "mails") params.sort = state.sort;
  if (state.labelled) params.labelled = true;
  return { ...params, ...pagingParams(state) };
}

export interface ProfileMailState extends Paging {
  /** The tab: null for "Alle". */
  role: PersonRole | null;
  year: number | null;
  /** A contact's person id: only the mails between both. */
  contact: number | null;
  /** A search in the person's mails, in the mail list's syntax (D330). */
  q: string;
}

export const DEFAULT_PROFILE_MAIL_STATE: ProfileMailState = {
  role: null,
  year: null,
  contact: null,
  q: "",
  cursor: null,
  page: 1,
  limit: PAGE_SIZE,
};

export function parseProfileMailState(search: URLSearchParams): ProfileMailState {
  return {
    ...parsePaging(search),
    role: PERSON_ROLES.find((role) => role === search.get("role")) ?? null,
    year: positiveInt(search.get("year"), 9999),
    contact: positiveInt(search.get("contact")),
    q: search.get("q")?.trim() ?? "",
  };
}

export function profileMailSearch(state: ProfileMailState): URLSearchParams {
  return buildQuery({
    role: state.role,
    year: state.year,
    contact: state.contact,
    q: state.q,
    ...pagingQuery(state),
  });
}

/** state with the tab, year, contact or search changed, back on the first page. */
export function withSelection(
  state: ProfileMailState,
  patch: Partial<Pick<ProfileMailState, "role" | "year" | "contact" | "q">>,
): ProfileMailState {
  return { ...state, ...patch, cursor: null, page: 1 };
}

/** The mail list behind a profile's mail card (D32): the person in the tab's role, the year as
 *  UTC days, the mails between both for a contact, the search (D330), duplicates hidden as in
 *  the figures. */
export function personMailList(personId: number, state: ProfileMailState): ListState {
  const year = state.year === null ? null : String(state.year).padStart(4, "0");
  return {
    ...DEFAULT_LIST_STATE,
    q: state.q,
    person: [personId],
    person_role: state.role,
    date_from: year && `${year}-01-01`,
    date_to: year && `${year}-12-31`,
    between: state.contact !== null && state.contact !== personId ? [personId, state.contact] : [],
    hide_duplicates: true,
    cursor: state.cursor,
    page: state.page,
    limit: state.limit,
  };
}

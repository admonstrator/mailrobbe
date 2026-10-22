// The persons screens keep their state in the URL: search, sort, page, tab and "Nur benannte"
// of the person list (/personen) with the switch for uncertain suggestions, and the mail card
// of a profile (/personen/:id: role, year, contact, page). Pages as every list's (D193).

import { buildQuery } from "../../api/client";
import {
  PAGE_SIZE,
  type PersonListParams,
  type PersonRole,
  type PersonSort,
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
  /** The suggestions tab shows the uncertain suggestions instead of the certain ones (D160). */
  uncertain: boolean;
}

export const DEFAULT_PERSON_LIST_STATE: PersonListState = {
  q: "",
  sort: "mails",
  cursor: null,
  page: 1,
  limit: PAGE_SIZE,
  tab: "personen",
  labelled: false,
  uncertain: false,
};

const SORTS: readonly PersonSort[] = ["mails", "name", "recent"];

export function parsePersonListState(search: URLSearchParams): PersonListState {
  return {
    ...parsePaging(search),
    q: search.get("q")?.trim() ?? "",
    sort: SORTS.find((sort) => sort === search.get("sort")) ?? "mails",
    tab: TABS.find((tab) => tab === search.get("tab")) ?? "personen",
    labelled: search.get("labelled") === "true",
    uncertain: search.get("unsicher") === "1",
  };
}

/** The query string of state, defaults left out; the inverse of parsePersonListState. */
export function personListSearch(state: PersonListState): URLSearchParams {
  return buildQuery({
    tab: state.tab === "personen" ? null : state.tab,
    unsicher: state.uncertain ? 1 : null,
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
}

export const DEFAULT_PROFILE_MAIL_STATE: ProfileMailState = {
  role: null,
  year: null,
  contact: null,
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
  };
}

export function profileMailSearch(state: ProfileMailState): URLSearchParams {
  return buildQuery({
    role: state.role,
    year: state.year,
    contact: state.contact,
    ...pagingQuery(state),
  });
}

/** state with the tab, year or contact changed, back on the first page. */
export function withSelection(
  state: ProfileMailState,
  patch: Partial<Pick<ProfileMailState, "role" | "year" | "contact">>,
): ProfileMailState {
  return { ...state, ...patch, cursor: null, page: 1 };
}

/** The mail list behind a profile's mail card (D32): the person in the tab's role, the year as
 *  UTC days, the mails between both for a contact, duplicates hidden as in the figures. */
export function personMailList(personId: number, state: ProfileMailState): ListState {
  const year = state.year === null ? null : String(state.year).padStart(4, "0");
  return {
    ...DEFAULT_LIST_STATE,
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

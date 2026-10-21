import { describe, expect, it } from "vitest";

import { toListParams } from "../mails/listState";
import {
  DEFAULT_PERSON_LIST_STATE,
  DEFAULT_PROFILE_MAIL_STATE,
  parsePersonListState,
  parseProfileMailState,
  personListSearch,
  personMailList,
  profileMailSearch,
  toPersonListParams,
  withSelection,
} from "./urlState";

const params = (query: string) => new URLSearchParams(query);

describe("person list state in the URL", () => {
  it("is the default for an empty query string and drops defaults again", () => {
    expect(parsePersonListState(params(""))).toEqual(DEFAULT_PERSON_LIST_STATE);
    expect(
      personListSearch(parsePersonListState(params("sort=mails&tab=personen"))).toString(),
    ).toBe("");
  });

  it("survives the round trip and gives the API only its parameters", () => {
    const query = "tab=vorschlaege&q=keller&sort=recent&cursor=abc&page=3";
    const state = parsePersonListState(params(query));
    expect(personListSearch(state).toString()).toBe(query);
    expect(toPersonListParams(state)).toEqual({ q: "keller", sort: "recent", cursor: "abc" });
  });

  it("ignores values it cannot use", () => {
    expect(parsePersonListState(params("sort=size&tab=karte&page=4&q=%20"))).toEqual(
      DEFAULT_PERSON_LIST_STATE,
    );
  });
});

describe("a profile's mail list", () => {
  it("keeps role, year, contact and page in the URL", () => {
    const query = "role=cc&year=2023&contact=12&cursor=abc&page=2";
    const state = parseProfileMailState(params(query));
    expect(state).toEqual({ role: "cc", year: 2023, contact: 12, cursor: "abc", page: 2 });
    expect(profileMailSearch(state).toString()).toBe(query);
    expect(parseProfileMailState(params("role=from&year=0&contact=x"))).toEqual(
      DEFAULT_PROFILE_MAIL_STATE,
    );
  });

  it("starts again at the first page when the selection changes", () => {
    const state = parseProfileMailState(params("role=sent&cursor=abc&page=2"));
    expect(withSelection(state, { year: 2020 })).toEqual({
      ...state,
      year: 2020,
      cursor: null,
      page: 1,
    });
  });

  it("asks the mail list for the person's role, the UTC year and the mails between both", () => {
    const state = parseProfileMailState(params("role=sent&year=2023&contact=12"));
    expect(toListParams(personMailList(11, state))).toEqual({
      date_from: "2023-01-01",
      date_to: "2023-12-31",
      hide_duplicates: true,
      person: [11],
      between: [11, 12],
      person_role: "sent",
    });
    expect(toListParams(personMailList(11, DEFAULT_PROFILE_MAIL_STATE))).toEqual({
      hide_duplicates: true,
      person: [11],
    });
    // The person itself is no contact.
    expect(personMailList(11, { ...DEFAULT_PROFILE_MAIL_STATE, contact: 11 }).between).toEqual([]);
  });
});

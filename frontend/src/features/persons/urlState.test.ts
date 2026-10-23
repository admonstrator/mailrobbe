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

  it("keeps the merge log tab and the switch for uncertain suggestions", () => {
    const state = parsePersonListState(params("tab=vorschlaege&unsicher=1"));
    expect(state).toEqual({ ...DEFAULT_PERSON_LIST_STATE, tab: "vorschlaege", uncertain: true });
    expect(personListSearch(state).toString()).toBe("tab=vorschlaege&unsicher=1");
    expect(parsePersonListState(params("tab=zusammengefuehrt")).tab).toBe("zusammengefuehrt");
    expect(parsePersonListState(params("unsicher=ja")).uncertain).toBe(false);
  });

  it("ignores values it cannot use", () => {
    expect(parsePersonListState(params("sort=size&tab=karte&page=x&limit=500&q=%20"))).toEqual(
      DEFAULT_PERSON_LIST_STATE,
    );
  });

  it("keeps a jump and the page size, and asks the API for them (D193)", () => {
    const state = parsePersonListState(params("sort=name&limit=100&page=7"));
    expect(state).toMatchObject({ cursor: null, page: 7, limit: 100 });
    expect(personListSearch(state).toString()).toBe("sort=name&limit=100&page=7");
    expect(toPersonListParams(state)).toEqual({ sort: "name", page: 7, limit: 100 });
    const last = parsePersonListState(params("page=last"));
    expect(toPersonListParams(last)).toEqual({ last: true });
    expect(personListSearch(last).toString()).toBe("page=last");
  });

  it('keeps "Nur benannte" (D157)', () => {
    const state = parsePersonListState(params("q=kasse&labelled=true"));
    expect(state.labelled).toBe(true);
    expect(personListSearch(state).toString()).toBe("q=kasse&labelled=true");
    expect(toPersonListParams(state)).toEqual({ q: "kasse", labelled: true });
    expect(parsePersonListState(params("labelled=1")).labelled).toBe(false);
  });
});

describe("a profile's mail list", () => {
  it("keeps role, year, contact, search and page in the URL", () => {
    const query = "role=cc&year=2023&contact=12&q=Kasse&cursor=abc&page=2";
    const state = parseProfileMailState(params(query));
    expect(state).toEqual({
      role: "cc",
      year: 2023,
      contact: 12,
      q: "Kasse",
      cursor: "abc",
      page: 2,
      limit: 50,
    });
    expect(profileMailSearch(state).toString()).toBe(query);
    expect(parseProfileMailState(params("role=from&year=0&contact=x"))).toEqual(
      DEFAULT_PROFILE_MAIL_STATE,
    );
  });

  it("jumps to a page at a page size of its own (D193)", () => {
    const state = parseProfileMailState(params("role=cc&limit=25&page=last"));
    expect(profileMailSearch(state).toString()).toBe("role=cc&limit=25&page=last");
    expect(toListParams(personMailList(11, state))).toEqual({
      hide_duplicates: true,
      person: [11],
      person_role: "cc",
      last: true,
      limit: 25,
    });
  });

  it("starts again at the first page when the selection changes", () => {
    const state = parseProfileMailState(params("role=sent&limit=25&cursor=abc&page=2"));
    expect(withSelection(state, { year: 2020 })).toEqual({
      ...state,
      year: 2020,
      cursor: null,
      page: 1,
    });
  });

  it("asks the mail list for the person's role, the UTC year and the mails between both", () => {
    const state = parseProfileMailState(params("role=sent&year=2023&contact=12&q=Kasse"));
    expect(toListParams(personMailList(11, state))).toEqual({
      q: "Kasse",
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

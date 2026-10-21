import { describe, expect, it } from "vitest";

import {
  DEFAULT_ENTITY_LIST_STATE,
  entityListSearch,
  entityMailsHref,
  entityYearHref,
  parseEntityListState,
  toEntityListParams,
  withEntityFilters,
  type EntityListState,
} from "./urlState";

const parse = (query: string) => parseEntityListState(new URLSearchParams(query));
const search = (state: EntityListState) => entityListSearch(state).toString();

describe("entity list in the URL", () => {
  it("is the default state for an empty query string, and back", () => {
    expect(parse("")).toEqual(DEFAULT_ENTITY_LIST_STATE);
    expect(search(DEFAULT_ENTITY_LIST_STATE)).toBe("");
  });

  it("survives the round trip with the API's parameter names", () => {
    const state: EntityListState = {
      tab: "amount",
      q: "12.500",
      detail: null,
      value_min: 1000,
      value_max: 50000.5,
      sort: "value",
      cursor: "abc",
      page: 3,
    };
    expect(search(state)).toBe(
      "kind=amount&q=12.500&value_min=1000&value_max=50000.5&sort=value&cursor=abc&page=3",
    );
    expect(parse(search(state))).toEqual(state);
  });

  it("asks for the kinds of a tab's group", () => {
    expect(toEntityListParams({ ...DEFAULT_ENTITY_LIST_STATE, tab: "accounts" })).toEqual({
      kind: ["iban", "account"],
    });
    expect(parse("kind=url&kind=domain").tab).toBe("web");
    // One kind of a group opens the group; a mix of groups is all.
    expect(parse("kind=iban").tab).toBe("accounts");
    expect(parse("kind=iban&kind=term").tab).toBe("all");
    expect(parse("kind=bogus").tab).toBe("all");
  });

  it("keeps the theme of the terms' tab", () => {
    const state = parse("kind=term&detail=spenden");
    expect(state.detail).toBe("spenden");
    expect(toEntityListParams(state)).toEqual({ kind: ["term"], detail: "spenden" });
  });

  it("sorts by value and takes a value range only on the amounts' tab", () => {
    expect(parse("sort=value&value_min=5").sort).toBe("mails");
    expect(parse("sort=value&value_min=5").value_min).toBeNull();
    expect(parse("kind=amount&sort=value&value_min=10,5").value_min).toBeNull();
    expect(parse("sort=recent").sort).toBe("recent");
  });

  it("drops what belongs to the previous tab and starts at the first page", () => {
    const amounts: EntityListState = {
      ...DEFAULT_ENTITY_LIST_STATE,
      tab: "amount",
      q: "EUR",
      value_min: 100,
      sort: "value",
      cursor: "x",
      page: 2,
    };
    expect(withEntityFilters(amounts, { tab: "term" })).toEqual({
      ...DEFAULT_ENTITY_LIST_STATE,
      tab: "term",
      q: "EUR",
    });
    const terms = { ...DEFAULT_ENTITY_LIST_STATE, tab: "term" as const, detail: "gewalt" };
    expect(withEntityFilters(terms, { tab: "all" }).detail).toBeNull();
    expect(withEntityFilters(terms, { q: "Waffe" }).detail).toBe("gewalt");
  });
});

describe("links to the mail list", () => {
  it("filter by the entities, with more filters on request", () => {
    expect(entityMailsHref([312])).toBe("/mails?entity=312");
    expect(entityMailsHref([312, 321])).toBe("/mails?entity=312&entity=321");
    expect(entityMailsHref([312], { amount_context: ["cash"] })).toBe(
      "/mails?entity=312&amount_context=cash",
    );
    expect(entityYearHref(312, 2019)).toBe(
      "/mails?date_from=2019-01-01&date_to=2019-12-31&entity=312",
    );
  });
});

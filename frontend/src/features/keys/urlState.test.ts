import { describe, expect, it } from "vitest";

import {
  DEFAULT_SELECTOR_LIST_STATE,
  parseSelectorListState,
  selectorListHref,
  toSelectorListParams,
} from "./urlState";

const parse = (query: string) => parseSelectorListState(new URLSearchParams(query));

describe("selector list URL", () => {
  it("leaves the defaults out", () => {
    expect(parse("")).toEqual(DEFAULT_SELECTOR_LIST_STATE);
    expect(selectorListHref(DEFAULT_SELECTOR_LIST_STATE)).toBe("/import/selektoren");
    expect(toSelectorListParams(DEFAULT_SELECTOR_LIST_STATE)).toEqual({});
  });

  it("round-trips search, filter and page and asks with an offset", () => {
    const state = parse("q=+nordlicht+&show=resolved&page=3");
    expect(state).toEqual({ q: "nordlicht", show: "resolved", page: 3, limit: 50 });
    expect(selectorListHref(state)).toBe("/import/selektoren?q=nordlicht&show=resolved&page=3");
    expect(toSelectorListParams(state)).toEqual({ q: "nordlicht", show: "resolved", offset: 100 });
  });

  it("pages by the page size chosen (D193)", () => {
    const state = parse("page=4&limit=25");
    expect(selectorListHref(state)).toBe("/import/selektoren?page=4&limit=25");
    expect(toSelectorListParams(state)).toEqual({ offset: 75, limit: 25 });
    expect(parse("limit=201").limit).toBe(50);
  });

  it("ignores values it cannot use", () => {
    expect(parse("show=closed&page=0")).toEqual(DEFAULT_SELECTOR_LIST_STATE);
    expect(parse("page=x").page).toBe(1);
  });
});

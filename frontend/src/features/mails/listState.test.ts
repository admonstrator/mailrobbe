import { describe, expect, it } from "vitest";

import { buildQuery } from "../../api/client";
import {
  DEFAULT_LIST_STATE,
  listSearch,
  parseListState,
  toFilters,
  toListParams,
  toOrderParams,
  withFilters,
  withoutSidebarFilters,
  type ListState,
} from "./listState";

const parse = (query: string) => parseListState(new URLSearchParams(query));
const search = (state: ListState) => listSearch(state).toString();

const full: ListState = {
  q: 'subject:"finale Fassung" from:anna@',
  dkim: ["pass", "no_key"],
  sender_domain: ["nordlicht-gmbh.example", "kanzlei-muster.example"],
  date_from: "2014-01-01",
  date_to: "2026-10-20",
  has_attachment: true,
  in_thread: true,
  hide_duplicates: true,
  external: true,
  flagged: true,
  mbox_file: 7,
  person: [11, 12],
  between: [11, 13],
  person_role: null,
  review: ["unreviewed", "relevant"],
  tag: [4, 2],
  collection: [3],
  has_note: true,
  document: 5101,
  thread: 812,
  entity: [31, 7],
  amount_min: 10000.5,
  amount_context: ["cash", "receipt"],
  sort: "date_asc",
  cursor: "eyJrIjoxfQ",
  limit: 100,
  page: 3,
};

describe("list state in the URL", () => {
  it("is the default state for an empty query string, and back", () => {
    expect(parse("")).toEqual(DEFAULT_LIST_STATE);
    expect(search(DEFAULT_LIST_STATE)).toBe("");
  });

  it("survives the round trip", () => {
    expect(parse(search(full))).toEqual(full);
    expect(search(parse(search(full)))).toBe(search(full));
  });

  it("uses the API's parameter names, repeats lists and writes booleans as true", () => {
    const params = listSearch(full);
    expect(params.getAll("dkim")).toEqual(["pass", "no_key"]);
    expect(params.getAll("between")).toEqual(["11", "13"]);
    expect(params.get("has_attachment")).toBe("true");
    expect(params.get("q")).toBe('subject:"finale Fassung" from:anna@');
    expect(params.get("page")).toBe("3");
    expect([...new Set(params.keys())]).toEqual([
      "q",
      "dkim",
      "sender_domain",
      "date_from",
      "date_to",
      "has_attachment",
      "in_thread",
      "hide_duplicates",
      "external",
      "flagged",
      "mbox_file",
      "person",
      "between",
      "review",
      "tag",
      "collection",
      "has_note",
      "document",
      "thread",
      "entity",
      "amount_min",
      "amount_context",
      "sort",
      "cursor",
      "limit",
      "page",
    ]);
  });

  it("drops defaults", () => {
    const state = parse("q=&sort=date_desc&limit=50&has_attachment=false&page=1&dkim=pass&cursor=");
    expect(search(state)).toBe("dkim=pass");
  });

  it("ignores values it cannot use", () => {
    const state = parse(
      [
        "dkim=bogus",
        "dkim=fail",
        "dkim=fail",
        "date_from=2026-02-30",
        "date_to=20.10.2026",
        "mbox_file=abc",
        "person=-1",
        "person=0",
        "person=12",
        "between=x",
        "sort=relevance",
        "limit=999",
        "flagged=yes",
        "review=bogus",
        "review=seen",
        "tag=0",
        "collection=x",
        "has_note=1",
        "sender_domain=%20",
        "sender_domain=Nordlicht-GmbH.example",
        "entity=0",
        "entity=x",
        "amount_min=10.000%2C00",
        "amount_context=bribe",
        "unknown=1",
      ].join("&"),
    );
    expect(state).toEqual({
      ...DEFAULT_LIST_STATE,
      dkim: ["fail"],
      person: [12],
      sender_domain: ["nordlicht-gmbh.example"],
      review: ["seen"],
    });
  });

  it("carries the entity and amount filters with the API's names (D86)", () => {
    const state = parse(
      "entity=31&entity=7&entity=31&amount_min=0&amount_context=donation&amount_context=cash",
    );
    expect(state.entity).toEqual([31, 7]);
    expect(state.amount_min).toBe(0);
    // Contexts in their fixed order, whatever the URL's.
    expect(state.amount_context).toEqual(["cash", "donation"]);
    expect(toFilters(state)).toEqual({
      entity: [31, 7],
      amount_min: 0,
      amount_context: ["cash", "donation"],
    });
    expect(search(state)).toBe(
      "entity=31&entity=7&amount_min=0&amount_context=cash&amount_context=donation",
    );
    expect(parse("amount_min=2500.5").amount_min).toBe(2500.5);
    expect(withoutSidebarFilters(state)).toEqual(DEFAULT_LIST_STATE);
  });

  it("keeps a person's role only together with exactly one person", () => {
    const state = parse("person=11&person_role=sent&hide_duplicates=true");
    expect(state.person_role).toBe("sent");
    expect(search(state)).toBe("hide_duplicates=true&person=11&person_role=sent");
    expect(toFilters(state)).toEqual({ hide_duplicates: true, person: [11], person_role: "sent" });
    expect(parse("person=11&person=12&person_role=sent").person_role).toBeNull();
    expect(parse("person_role=cc").person_role).toBeNull();
    expect(parse("person=11&person_role=from").person_role).toBeNull();
  });

  it("keeps the page number only together with a cursor", () => {
    expect(parse("page=4").page).toBe(1);
    expect(parse("cursor=abc&page=4").page).toBe(4);
    expect(parse("cursor=abc&page=0").page).toBe(1);
  });

  it("starts again at the first page when a filter changes", () => {
    const next = withFilters(full, { has_attachment: false });
    expect(next.cursor).toBeNull();
    expect(next.page).toBe(1);
    expect(next.has_attachment).toBe(false);
    expect(next.limit).toBe(100);
  });

  it("resets the filter column but keeps search text and sort", () => {
    expect(withoutSidebarFilters(full)).toEqual({
      ...DEFAULT_LIST_STATE,
      q: full.q,
      sort: "date_asc",
      limit: 100,
    });
  });
});

describe("API parameters from the list state", () => {
  it("leave out the defaults, so equal filters give equal objects", () => {
    expect(toFilters(DEFAULT_LIST_STATE)).toEqual({});
    expect(toFilters({ ...DEFAULT_LIST_STATE, sort: "date_asc", cursor: "x", page: 2 })).toEqual(
      {},
    );
    expect(toOrderParams({ ...DEFAULT_LIST_STATE, sort: "date_asc" })).toEqual({
      sort: "date_asc",
    });
  });

  it("build the request's query string without the UI's page", () => {
    const query = buildQuery(toListParams(full)).toString();
    expect(query).not.toContain("page=");
    expect(query).toBe(search({ ...full, page: 1 }));
    expect(
      buildQuery(toListParams(parse("dkim=pass&dkim=fail&has_attachment=true"))).toString(),
    ).toBe("dkim=pass&dkim=fail&has_attachment=true");
  });
});

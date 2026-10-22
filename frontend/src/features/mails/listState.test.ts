import { describe, expect, it } from "vitest";

import { buildQuery } from "../../api/client";
import { MIN_HITS_LIMIT, SEARCH_FIELDS } from "../../api/types";
import {
  canonicalScope,
  DEFAULT_LIST_STATE,
  hasFilters,
  listSearch,
  parseListState,
  searchOptions,
  toFilters,
  toHitsParams,
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
  signal: ["night", "term:spenden"],
  collapse_near: true,
  near_group: 4711,
  event: ["request", "cancel"],
  event_uid: "040000008200E00074C5B7101A82E008",
  scope: ["subject", "body"],
  whole_word: true,
  min_hits: 3,
  include_hidden: true,
  body_part: "own",
  block: "00ff00ff00ff00ff",
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
      "collapse_near",
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
      "signal",
      "near_group",
      "event",
      "event_uid",
      "scope",
      "whole_word",
      "min_hits",
      "include_hidden",
      "body_part",
      "block",
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
        "scope=header",
        "whole_word=1",
        "min_hits=0",
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

  it("reads a page as a jump, or with a cursor as the number of the step's page (D193)", () => {
    expect(parse("page=4")).toMatchObject({ cursor: null, page: 4 });
    expect(parse("page=last")).toMatchObject({ cursor: null, page: "last" });
    expect(parse("page=0").page).toBe(1);
    expect(parse("cursor=abc&page=4")).toMatchObject({ cursor: "abc", page: 4 });
    // A step from a last page read from the end does not know its number.
    expect(parse("cursor=abc").page).toBeNull();
    expect(parse("cursor=abc&page=last").page).toBeNull();
    for (const query of [
      "page=4",
      "page=last",
      "limit=25&page=7",
      "cursor=abc&page=4",
      "cursor=abc",
    ]) {
      expect(search(parse(query))).toBe(query);
    }
  });

  it("asks for a jump by page or last, and for a step by its cursor alone", () => {
    expect(toListParams(parse("page=4&limit=25"))).toEqual({ page: 4, limit: 25 });
    expect(toListParams(parse("page=last"))).toEqual({ last: true });
    expect(toListParams(parse("page=1"))).toEqual({});
    expect(toListParams(parse("cursor=abc&page=4"))).toEqual({ cursor: "abc" });
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

describe("the search options in the URL (D171 to D174, D177)", () => {
  it("keeps places in their fixed order, once each, whole words and the minimum", () => {
    const state = parse(
      "q=Neger&scope=filename&scope=subject&scope=subject&whole_word=true&min_hits=3",
    );
    expect(state.scope).toEqual(["subject", "filename"]);
    expect(state.whole_word).toBe(true);
    expect(state.min_hits).toBe(3);
    expect(toFilters(state)).toEqual({
      q: "Neger",
      scope: ["subject", "filename"],
      whole_word: true,
      min_hits: 3,
    });
    expect(search(state)).toBe("q=Neger&scope=subject&scope=filename&whole_word=true&min_hits=3");
    expect(parse(search(state))).toEqual(state);
  });

  it("stores all four places as none, everywhere, and leaves out the defaults", () => {
    const all = parse("scope=body&scope=subject&scope=filename&scope=attachment&whole_word=false");
    expect(all.scope).toEqual([]);
    expect(all.whole_word).toBe(false);
    expect(search(all)).toBe("");
    expect(canonicalScope(["attachment", "subject", "x"])).toEqual(["subject", "attachment"]);
    expect(canonicalScope([...SEARCH_FIELDS])).toEqual([]);
  });

  it("takes a minimum from 1 to the limit only", () => {
    expect(parse("min_hits=1").min_hits).toBe(1);
    expect(parse(`min_hits=${MIN_HITS_LIMIT}`).min_hits).toBe(MIN_HITS_LIMIT);
    for (const bad of ["0", "-2", "1000", "2.5", "drei", ""]) {
      expect(parse(`min_hits=${bad}`).min_hits).toBeNull();
    }
  });

  it("counts as filters, travels in the API's parameters and is reset with the column", () => {
    const state = parse("q=Neger&scope=body&min_hits=2&sort=date_asc");
    expect(hasFilters({ ...DEFAULT_LIST_STATE, whole_word: true })).toBe(true);
    expect(toOrderParams(state)).toEqual({
      q: "Neger",
      scope: ["body"],
      min_hits: 2,
      sort: "date_asc",
    });
    expect(buildQuery(toListParams(state)).toString()).toBe(
      "q=Neger&scope=body&min_hits=2&sort=date_asc",
    );
    expect(withoutSidebarFilters(state)).toEqual({
      ...DEFAULT_LIST_STATE,
      q: "Neger",
      sort: "date_asc",
    });
    expect(withFilters(full, { whole_word: false }).page).toBe(1);
  });

  it("gives the hits of a mail q, places and whole words, but no minimum (D176)", () => {
    expect(
      toHitsParams(parse("q=Neger&scope=subject&whole_word=true&min_hits=2&dkim=pass")),
    ).toEqual({ q: "Neger", scope: ["subject"], whole_word: true });
    expect(toHitsParams(parse("q=Neger"))).toEqual({ q: "Neger" });
  });

  it("names the options a new search from the header keeps", () => {
    expect(searchOptions(full)).toEqual({
      scope: ["subject", "body"],
      whole_word: true,
      min_hits: 3,
      body_part: "own",
      include_hidden: true,
    });
    expect(searchOptions(DEFAULT_LIST_STATE)).toEqual({
      scope: [],
      whole_word: false,
      min_hits: null,
      body_part: "clean",
      include_hidden: false,
    });
  });
});

describe("hidden mails, the parts of the text and standard blocks in the URL (milestone 18)", () => {
  it("leaves the defaults out and drops values it cannot use", () => {
    expect(parse("body_part=clean&include_hidden=false")).toEqual(DEFAULT_LIST_STATE);
    expect(parse("body_part=quotes").body_part).toBe("clean");
    expect(parse("block=00FF00FF00FF00FF").block).toBeNull();
    expect(parse("block=00ff").block).toBeNull();
  });

  it("hands the parts of the text to the hits of a mail (D226)", () => {
    expect(toHitsParams(parse("q=Rat&body_part=full"))).toEqual({ q: "Rat", body_part: "full" });
  });
});

describe("the signal filter in the URL (D136)", () => {
  it("keeps kinds and word fields in the URL's order, once each, and hands them to the API", () => {
    const state = parse(
      "signal=weekend&signal=term%3Aspenden&signal=weekend&signal=bogus&signal=term%3A&signal=silent",
    );
    expect(state.signal).toEqual(["weekend", "term:spenden"]);
    expect(toFilters(state)).toEqual({ signal: ["weekend", "term:spenden"] });
    expect(search(state)).toBe("signal=weekend&signal=term%3Aspenden");
    expect(parse(search(state))).toEqual(state);
    expect(withoutSidebarFilters(state)).toEqual(DEFAULT_LIST_STATE);
  });

  it("comes last among the filters, so the profile's links match what the list writes", () => {
    const state = parse("signal=night&person=11&person_role=sent");
    expect(search(state)).toBe("person=11&person_role=sent&signal=night");
    expect(withFilters(state, { signal: [] }).signal).toEqual([]);
  });
});

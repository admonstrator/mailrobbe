import { describe, expect, it } from "vitest";

import {
  DEFAULT_GRAPH_STATE,
  draftProblem,
  excerptKey,
  graphHref,
  graphSearch,
  parseGraphState,
  toGraphParams,
  withPerson,
  type GraphState,
} from "./graphState";

const parse = (query: string) => parseGraphState(new URLSearchParams(query));

describe("map URL state", () => {
  it("defaults to the top 50 without parameters and writes nothing for the defaults", () => {
    expect(parse("")).toEqual(DEFAULT_GRAPH_STATE);
    expect(DEFAULT_GRAPH_STATE).toMatchObject({
      mode: "top",
      limit: 50,
      depth: 1,
      min: 1,
      hideLists: true,
      cc: false,
      color: true,
      arrows: false,
      layout: "force",
    });
    expect(graphSearch(DEFAULT_GRAPH_STATE)).toBe("");
    expect(graphHref(DEFAULT_GRAPH_STATE)).toBe("/karte");
  });

  it("reads the mail detail's link as an ego network", () => {
    const state = parse("center=11,12,15,13");
    expect(state.mode).toBe("ego");
    expect(state.center).toEqual([11, 12, 15, 13]);
    expect(graphSearch(state)).toBe("center=11,12,15,13");
  });

  it("round-trips every parameter", () => {
    const full: GraphState = {
      mode: "ego",
      center: [11, 13],
      depth: 2,
      limit: 50,
      domain: [],
      min: 25,
      from: 2016,
      to: 2024,
      dkimOnly: true,
      cc: true,
      hideLists: false,
      expand: [14],
      hide: [19, 17],
      layout: "tree",
      color: false,
      arrows: true,
    };
    const search = graphSearch(full);
    expect(search).toBe(
      "center=11,13&depth=2&min=25&from=2016&to=2024&dkim=1&cc=1&lists=0&expand=14&hide=19,17&layout=tree&color=0&arrows=1",
    );
    expect(parse(search)).toEqual(full);

    const top = { ...DEFAULT_GRAPH_STATE, limit: 400, layout: "circle" as const };
    expect(graphSearch(top)).toBe("limit=400&layout=circle");
    expect(parse(graphSearch(top))).toEqual(top);

    const domains = {
      ...DEFAULT_GRAPH_STATE,
      mode: "domains" as const,
      domain: ["a.example", "b.test"],
    };
    expect(graphSearch(domains)).toBe("mode=domains&domain=a.example,b.test");
    expect(parse(graphSearch(domains))).toEqual(domains);
  });

  it("writes mode only when the centers do not imply it", () => {
    expect(graphSearch({ ...DEFAULT_GRAPH_STATE, mode: "ego", center: [5] })).toBe("center=5");
    // Fields of other modes are left out.
    expect(graphSearch({ ...DEFAULT_GRAPH_STATE, center: [5], domain: ["x.example"] })).toBe("");
    expect(parse("mode=top&center=5")).toMatchObject({ mode: "top", center: [] });
  });

  it("falls back to defaults for broken values", () => {
    expect(parse("mode=ego")).toMatchObject({ mode: "top", center: [] });
    expect(parse("mode=domains&domain=only.example")).toMatchObject({ mode: "top", domain: [] });
    expect(parse("mode=galaxy")).toMatchObject({ mode: "top" });
    expect(parse("center=abc,0,-3,7,7")).toMatchObject({ mode: "ego", center: [7] });
    expect(parse("center=4&depth=9").depth).toBe(1);
    expect(parse("limit=0").limit).toBe(50);
    expect(parse("limit=2001").limit).toBe(50);
    expect(parse("min=1.5").min).toBe(1);
    expect(parse("from=12&to=abc")).toMatchObject({ from: null, to: null });
    expect(parse("layout=spiral&color=maybe&arrows=").layout).toBe("force");
    expect(parse("color=maybe")).toMatchObject({ color: true, arrows: false });
    expect(parse("hide=x,3")).toMatchObject({ hide: [3] });
  });

  it("swaps a reversed year range and accepts repeated lists", () => {
    expect(parse("from=2024&to=2016")).toMatchObject({ from: 2016, to: 2024 });
    expect(parse("center=3&center=4,5").center).toEqual([3, 4, 5]);
    expect(parse("mode=domains&domain=A.Example&domain=b.example").domain).toEqual([
      "a.example",
      "b.example",
    ]);
  });
});

describe("API parameters", () => {
  it("send the mode and only what differs from the API's defaults", () => {
    expect(toGraphParams(DEFAULT_GRAPH_STATE)).toEqual({ mode: "top", hide_lists: true });
    expect(toGraphParams({ ...DEFAULT_GRAPH_STATE, limit: 200, hideLists: false })).toEqual({
      mode: "top",
      limit: 200,
    });
  });

  it("carry the ego network's centers and depth", () => {
    expect(
      toGraphParams(parse("center=11,13&depth=3&min=5&from=2019&to=2019&cc=1&dkim=1")),
    ).toEqual({
      mode: "ego",
      center: [11, 13],
      depth: 3,
      min_edge: 5,
      year_from: 2019,
      year_to: 2019,
      dkim_only: true,
      cc: true,
      hide_lists: true,
    });
  });

  it("carry two domains, expand and hide, and never the view options", () => {
    const state = parse(
      "mode=domains&domain=a.example,b.example&expand=3&hide=4,5&arrows=1&layout=circle",
    );
    expect(toGraphParams(state)).toEqual({
      mode: "domains",
      domain: ["a.example", "b.example"],
      hide_lists: true,
      expand: [3],
      hide: [4, 5],
    });
  });
});

describe("drafts", () => {
  it("explain what is missing before a draft can be drawn", () => {
    expect(draftProblem(DEFAULT_GRAPH_STATE)).toBeNull();
    expect(draftProblem({ ...DEFAULT_GRAPH_STATE, mode: "ego" })).toContain("Zentrum");
    const domains = { ...DEFAULT_GRAPH_STATE, mode: "domains" as const };
    expect(draftProblem({ ...domains, domain: ["a.example", ""] })).toContain("Zwei");
    expect(draftProblem({ ...domains, domain: ["a.example", "a.example"] })).toContain("Zwei");
    expect(draftProblem({ ...domains, domain: ["a.example", "b.example"] })).toBeNull();
  });

  it("compare by excerpt, ignoring the view options", () => {
    const state = parse("center=11&min=3");
    expect(excerptKey({ ...state, arrows: true, layout: "circle", color: false })).toBe(
      excerptKey(state),
    );
    expect(excerptKey({ ...state, min: 4 })).not.toBe(excerptKey(state));
  });

  it("add a person to expand or hide once", () => {
    const state = withPerson(DEFAULT_GRAPH_STATE, "hide", 7);
    expect(state.hide).toEqual([7]);
    expect(withPerson(state, "hide", 7)).toBe(state);
    expect(withPerson(state, "expand", 7).expand).toEqual([7]);
  });
});

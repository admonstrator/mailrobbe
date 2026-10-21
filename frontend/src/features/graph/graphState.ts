// The map's state lives in the URL of /karte: the excerpt (D37) and the view options. Short keys,
// lists comma-separated (the format the mail detail links: /karte?center=11,12,15,13), defaults
// and the fields the mode does not use left out. The API gets GraphParams with its own names.

import { GRAPH_TOP, MAX_GRAPH_NODES, type GraphMode, type GraphParams } from "../../api/types";

export type GraphLayout = "force" | "domains" | "circle" | "tree";

export interface GraphState {
  mode: GraphMode;
  center: number[];
  depth: number;
  limit: number;
  domain: string[];
  min: number;
  from: number | null; // UTC years, inclusive
  to: number | null;
  dkimOnly: boolean;
  cc: boolean;
  hideLists: boolean;
  expand: number[];
  hide: number[];
  // View only: applied without a new request.
  layout: GraphLayout;
  color: boolean;
  arrows: boolean;
}

export const GRAPH_LAYOUTS: readonly GraphLayout[] = ["force", "domains", "circle", "tree"];
export const MAX_DEPTH = 3;
const MAX_MIN = 1_000_000;
const YEAR_MIN = 1900;
const YEAR_MAX = 2200;

export const DEFAULT_GRAPH_STATE: GraphState = {
  mode: "top",
  center: [],
  depth: 1,
  limit: GRAPH_TOP,
  domain: [],
  min: 1,
  from: null,
  to: null,
  dkimOnly: false,
  cc: false,
  hideLists: true,
  expand: [],
  hide: [],
  layout: "force",
  color: true,
  arrows: false,
};

function int(value: string | null, min: number, max: number): number | null {
  if (value === null || !/^\d+$/.test(value.trim())) return null;
  const n = Number(value);
  return n >= min && n <= max ? n : null;
}

function flag(value: string | null, fallback: boolean): boolean {
  if (value === "1" || value === "true" || value === "on") return true;
  if (value === "0" || value === "false" || value === "off") return false;
  return fallback;
}

/** Comma-separated or repeated values, trimmed, without empty ones and repeats. */
function list(search: URLSearchParams, key: string): string[] {
  const values = search.getAll(key).flatMap((value) => value.split(","));
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function ids(search: URLSearchParams, key: string): number[] {
  return list(search, key).flatMap((value) => int(value, 1, Number.MAX_SAFE_INTEGER) ?? []);
}

function isMode(value: string | null): value is GraphMode {
  return value === "ego" || value === "top" || value === "domains";
}

/** The state a query string describes. Values that cannot be used fall back to the defaults; a
 *  mode that lacks what it needs (ego without centers, domains without two) becomes top. */
export function parseGraphState(search: URLSearchParams): GraphState {
  const state: GraphState = { ...DEFAULT_GRAPH_STATE };
  state.center = ids(search, "center");
  state.domain = list(search, "domain")
    .map((domain) => domain.toLowerCase())
    .filter((domain, index, all) => all.indexOf(domain) === index);
  const mode = search.get("mode");
  state.mode = isMode(mode) ? mode : state.center.length ? "ego" : "top";
  if (state.mode === "ego" && state.center.length === 0) state.mode = "top";
  if (state.mode === "domains" && state.domain.length !== 2) state.mode = "top";
  if (state.mode !== "ego") state.center = [];
  if (state.mode !== "domains") state.domain = [];

  state.depth = int(search.get("depth"), 1, MAX_DEPTH) ?? DEFAULT_GRAPH_STATE.depth;
  state.limit = int(search.get("limit"), 1, MAX_GRAPH_NODES) ?? DEFAULT_GRAPH_STATE.limit;
  state.min = int(search.get("min"), 1, MAX_MIN) ?? DEFAULT_GRAPH_STATE.min;
  const from = int(search.get("from"), YEAR_MIN, YEAR_MAX);
  const to = int(search.get("to"), YEAR_MIN, YEAR_MAX);
  [state.from, state.to] = from !== null && to !== null && from > to ? [to, from] : [from, to];
  state.dkimOnly = flag(search.get("dkim"), DEFAULT_GRAPH_STATE.dkimOnly);
  state.cc = flag(search.get("cc"), DEFAULT_GRAPH_STATE.cc);
  state.hideLists = flag(search.get("lists"), DEFAULT_GRAPH_STATE.hideLists);
  state.expand = ids(search, "expand");
  state.hide = ids(search, "hide");

  const layout = search.get("layout");
  state.layout = GRAPH_LAYOUTS.find((name) => name === layout) ?? DEFAULT_GRAPH_STATE.layout;
  state.color = flag(search.get("color"), DEFAULT_GRAPH_STATE.color);
  state.arrows = flag(search.get("arrows"), DEFAULT_GRAPH_STATE.arrows);
  return state;
}

/** The query string of state (without "?"), the inverse of parseGraphState. Commas stay
 *  readable instead of %2C. */
export function graphSearch(state: GraphState): string {
  const pairs: [string, string | number][] = [];
  const add = (key: string, value: string | number) => pairs.push([key, value]);
  // What parseGraphState assumes without mode: ego when there are centers (written for ego only).
  const impliedMode = state.mode === "ego" && state.center.length ? "ego" : "top";
  if (state.mode !== impliedMode) add("mode", state.mode);
  if (state.mode === "ego") {
    if (state.center.length) add("center", state.center.join(","));
    if (state.depth !== DEFAULT_GRAPH_STATE.depth) add("depth", state.depth);
  }
  if (state.mode === "top" && state.limit !== DEFAULT_GRAPH_STATE.limit) add("limit", state.limit);
  if (state.mode === "domains" && state.domain.length) add("domain", state.domain.join(","));
  if (state.min !== DEFAULT_GRAPH_STATE.min) add("min", state.min);
  if (state.from !== null) add("from", state.from);
  if (state.to !== null) add("to", state.to);
  if (state.dkimOnly) add("dkim", 1);
  if (state.cc) add("cc", 1);
  if (!state.hideLists) add("lists", 0);
  if (state.expand.length) add("expand", state.expand.join(","));
  if (state.hide.length) add("hide", state.hide.join(","));
  if (state.layout !== DEFAULT_GRAPH_STATE.layout) add("layout", state.layout);
  if (!state.color) add("color", 0);
  if (state.arrows) add("arrows", 1);
  return pairs
    .map(([key, value]) => `${key}=${encodeURIComponent(value).replace(/%2C/gi, ",")}`)
    .join("&");
}

/** "/karte" plus the query string of state. */
export function graphHref(state: GraphState): string {
  const search = graphSearch(state);
  return search ? `/karte?${search}` : "/karte";
}

/** The parameters of the excerpt for /api/graph*, with the API's defaults left out. mode is
 *  always given: the API's default (ego) is not the map's. */
export function toGraphParams(state: GraphState): GraphParams {
  const params: GraphParams = { mode: state.mode };
  if (state.mode === "ego") {
    params.center = state.center;
    if (state.depth !== 1) params.depth = state.depth;
  }
  if (state.mode === "top" && state.limit !== GRAPH_TOP) params.limit = state.limit;
  if (state.mode === "domains") params.domain = state.domain;
  if (state.min !== 1) params.min_edge = state.min;
  if (state.from !== null) params.year_from = state.from;
  if (state.to !== null) params.year_to = state.to;
  if (state.dkimOnly) params.dkim_only = true;
  if (state.cc) params.cc = true;
  if (state.hideLists) params.hide_lists = true;
  if (state.expand.length) params.expand = state.expand;
  if (state.hide.length) params.hide = state.hide;
  return params;
}

/** Why a draft cannot be drawn yet, as a German hint; null when it can. */
export function draftProblem(state: GraphState): string | null {
  if (state.mode === "ego" && state.center.length === 0) {
    return "Mindestens eine Person als Zentrum hinzufügen.";
  }
  const [first, second] = state.domain;
  if (
    state.mode === "domains" &&
    (state.domain.length !== 2 || !first || !second || first === second)
  ) {
    return "Zwei verschiedene Domains eintragen.";
  }
  return null;
}

/** The part of state that defines the excerpt, as a string: equal strings load the same graph. */
export function excerptKey(state: GraphState): string {
  return graphSearch({
    ...state,
    layout: DEFAULT_GRAPH_STATE.layout,
    color: DEFAULT_GRAPH_STATE.color,
    arrows: DEFAULT_GRAPH_STATE.arrows,
  });
}

/** state with id added to a list of persons (expand, hide), once. */
export function withPerson(state: GraphState, key: "expand" | "hide", id: number): GraphState {
  return state[key].includes(id) ? state : { ...state, [key]: [...state[key], id] };
}

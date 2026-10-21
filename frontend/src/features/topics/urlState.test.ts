import { describe, expect, it } from "vitest";

import { DEFAULT_LIST_STATE } from "../mails/listState";
import {
  DEFAULT_TOPICS_STATE,
  hasSelection,
  parseTopicsState,
  periodMailsHref,
  periodTimelineHref,
  selectionHref,
  termMailsHref,
  termTimelineHref,
  topicsHref,
  topicsSearch,
  withTerm,
  type TopicsState,
} from "./urlState";

const parse = (query: string) => parseTopicsState(new URLSearchParams(query));
const search = (state: TopicsState) => topicsSearch(state).toString();

const list = {
  ...DEFAULT_LIST_STATE,
  q: "Spende from:kasse@",
  date_from: "2025-01-01",
  date_to: "2025-06-30",
  person: [11],
  person_role: "sent" as const,
  tag: [2],
};

describe("topics state in the URL", () => {
  it("is the default state for an empty query string, and back", () => {
    expect(parse("")).toEqual(DEFAULT_TOPICS_STATE);
    expect(search(DEFAULT_TOPICS_STATE)).toBe("");
    expect(topicsHref(DEFAULT_TOPICS_STATE)).toBe("/themen");
  });

  it("leaves the defaults out: the periods by month", () => {
    expect(search({ ...DEFAULT_TOPICS_STATE, view: "periods", unit: "month" })).toBe("");
    expect(search({ ...DEFAULT_TOPICS_STATE, unit: "quarter" })).toBe("unit=quarter");
    expect(search({ ...DEFAULT_TOPICS_STATE, view: "clusters" })).toBe("view=clusters");
  });

  it("survives the round trip with view and unit first, then the mail list's filters", () => {
    const full: TopicsState = { view: "selection", unit: "year", list };
    expect(parse(search(full))).toEqual(full);
    expect(search(full)).toBe(
      "view=selection&unit=year&q=Spende+from%3Akasse%40&date_from=2025-01-01&date_to=2025-06-30" +
        "&person=11&person_role=sent&tag=2",
    );
  });

  it("ignores what it cannot use, and the mail list's sort, cursor and page", () => {
    expect(parse("view=chart&unit=week")).toEqual(DEFAULT_TOPICS_STATE);
    const state = parse("view=selection&sort=date_asc&cursor=abc&page=3&limit=100&person=11");
    expect(state.list).toEqual({ ...DEFAULT_LIST_STATE, person: [11] });
  });

  it("counts a selection only for filters that pick some mails", () => {
    expect(hasSelection(DEFAULT_LIST_STATE)).toBe(false);
    expect(hasSelection({ ...DEFAULT_LIST_STATE, hide_duplicates: true })).toBe(false);
    expect(hasSelection({ ...DEFAULT_LIST_STATE, q: "Spende" })).toBe(true);
    expect(hasSelection(list)).toBe(true);
  });

  it("opens the Auswahl view with a list's filters", () => {
    expect(selectionHref({ ...list, sort: "date_asc", cursor: "x", page: 2 })).toBe(
      "/themen?view=selection&q=Spende+from%3Akasse%40&date_from=2025-01-01&date_to=2025-06-30" +
        "&person=11&person_role=sent&tag=2",
    );
  });
});

describe("links of a term", () => {
  it("adds the label to every alternative of q", () => {
    expect(withTerm("", "Spende")).toBe("Spende");
    expect(withTerm("from:kasse@ Bargeld", "Spende")).toBe("from:kasse@ Bargeld Spende");
    expect(withTerm("Kasse or Konto", "Spende")).toBe("Kasse Spende or Konto Spende");
    expect(withTerm('"schwarze Kasse" OR Konto', "Spende")).toBe(
      '"schwarze Kasse" Spende OR Konto Spende',
    );
    // "or" inside quotes is a phrase, no alternative.
    expect(withTerm('"Kasse or Konto"', "Spende")).toBe('"Kasse or Konto" Spende');
  });

  it("opens the mail list with the label, the filters and duplicates hidden", () => {
    expect(termMailsHref(DEFAULT_LIST_STATE, "Spende")).toBe(
      "/mails?q=Spende&hide_duplicates=true",
    );
    expect(termMailsHref(list, "Wartung")).toBe(
      "/mails?q=Spende+from%3Akasse%40+Wartung&date_from=2025-01-01&date_to=2025-06-30" +
        "&hide_duplicates=true&person=11&person_role=sent&tag=2",
    );
  });

  it("opens the timeline with a lane per label within the filters", () => {
    expect(termTimelineHref(DEFAULT_LIST_STATE, ["Angebot", "Preis"])).toBe(
      "/zeitachse?hide_duplicates=true&split=term&term=Angebot&term=Preis",
    );
    expect(termTimelineHref({ ...DEFAULT_LIST_STATE, person: [11] }, ["Wartung"])).toBe(
      "/zeitachse?hide_duplicates=true&person=11&split=term&term=Wartung",
    );
  });

  it("opens a period's mails and timeline by its days", () => {
    expect(periodMailsHref("2025-10-01", "2025-10-31")).toBe(
      "/mails?date_from=2025-10-01&date_to=2025-10-31&hide_duplicates=true",
    );
    expect(periodTimelineHref("2025-10-01", "2025-10-31")).toBe(
      "/zeitachse?date_from=2025-10-01&date_to=2025-10-31&hide_duplicates=true",
    );
  });
});

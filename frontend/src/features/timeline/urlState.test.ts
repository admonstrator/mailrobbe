import { describe, expect, it } from "vitest";

import { timelineByPerson, timelineByTerm, timelineByThread } from "../../test/fixtures";
import { DEFAULT_LIST_STATE, parseListState, toFilters } from "../mails/listState";
import { timelinePath } from "./buckets";
import {
  bucketList,
  DEFAULT_TIMELINE_STATE,
  mailListHref,
  parseTimelineState,
  timelineHref,
  timelineSearch,
  toFirstMentionParams,
  toTimelineParams,
  withPerson,
  type TimelineState,
} from "./urlState";

const parse = (query: string) => parseTimelineState(new URLSearchParams(query));
const search = (state: TimelineState) => timelineSearch(state).toString();

const list = {
  ...DEFAULT_LIST_STATE,
  q: "Spende from:kasse@",
  dkim: ["fail" as const],
  date_from: "2023-01-01",
  date_to: "2025-06-30",
  hide_duplicates: true,
  person: [11],
  person_role: "sent" as const,
  tag: [2],
  thread: 812,
};

const full: TimelineState = {
  list,
  bucket: "week",
  split: "person",
  split_id: [14, 12],
  term: [],
  role: "sent",
  lists: true,
};

describe("timeline state in the URL", () => {
  it("is the default state for an empty query string, and back", () => {
    expect(parse("")).toEqual(DEFAULT_TIMELINE_STATE);
    expect(search(DEFAULT_TIMELINE_STATE)).toBe("");
    expect(timelineHref(DEFAULT_TIMELINE_STATE)).toBe("/zeitachse");
  });

  it("survives the round trip with the filters first, then its own parameters", () => {
    expect(parse(search(full))).toEqual(full);
    const params = timelineSearch(full);
    expect(params.getAll("split_id")).toEqual(["14", "12"]);
    expect([...new Set(params.keys())]).toEqual([
      "q",
      "dkim",
      "date_from",
      "date_to",
      "hide_duplicates",
      "person",
      "person_role",
      "tag",
      "thread",
      "bucket",
      "split",
      "split_id",
      "role",
      "lists",
    ]);
    const terms: TimelineState = {
      ...DEFAULT_TIMELINE_STATE,
      split: "term",
      term: ["Spende", '"schwarze Kasse"'],
    };
    expect(search(terms)).toBe("split=term&term=Spende&term=%22schwarze+Kasse%22");
    expect(parse(search(terms))).toEqual(terms);
  });

  it("reads every filter of the mail list as the mail list does", () => {
    const query = [
      "q=Spende",
      "dkim=fail",
      "dkim=no_key",
      "sender_domain=kasse.example",
      "date_from=2023-01-01",
      "date_to=2023-12-31",
      "has_attachment=true",
      "in_thread=true",
      "hide_duplicates=true",
      "external=true",
      "flagged=true",
      "mbox_file=3",
      "between=11",
      "between=12",
      "review=relevant",
      "tag=2",
      "collection=3",
      "has_note=true",
      "document=5101",
      "thread=812",
    ].join("&");
    const state = parse(query);
    expect(toFilters(state.list)).toEqual(toFilters(parseListState(new URLSearchParams(query))));
    expect(search(state)).toBe(query);
  });

  it("opens what timelinePath links to", () => {
    const path = timelinePath({ q: "Spende", person: [3, 7] }, { split: "thread", bucket: "day" });
    const state = parse(path.split("?")[1]);
    expect(state.list.person).toEqual([3, 7]);
    expect([state.split, state.bucket]).toEqual(["thread", "day"]);
    const pairs = (query: string) => [...new URLSearchParams(query)].map(String).sort();
    expect(pairs(timelineSearch(state).toString())).toEqual(pairs(path.split("?")[1]));
  });

  it("ignores values it cannot use and what belongs to another split", () => {
    expect(
      parse(
        "bucket=year&split=domain&split_id=4&term=x&role=from&lists=yes&sort=date_asc&cursor=c&page=2&limit=100",
      ),
    ).toEqual(DEFAULT_TIMELINE_STATE);
    expect(parse("split=person&split_id=abc&split_id=4&split_id=4&term=x")).toEqual({
      ...DEFAULT_TIMELINE_STATE,
      split: "person",
      split_id: [4],
    });
    expect(parse("split=term&term=%20&term=a&split_id=4").term).toEqual(["a"]);
    const many = Array.from({ length: 14 }, (_, index) => `split_id=${index + 1}`).join("&");
    expect(parse(`split=thread&${many}`).split_id).toHaveLength(12);
    const terms = Array.from({ length: 8 }, (_, index) => `term=t${index}`).join("&");
    expect(parse(`split=term&${terms}`).term).toEqual(["t0", "t1", "t2", "t3", "t4", "t5"]);
  });

  it("asks the API with the defaults left out", () => {
    expect(toTimelineParams(DEFAULT_TIMELINE_STATE)).toEqual({});
    expect(toTimelineParams(full)).toEqual({
      ...toFilters(list),
      bucket: "week",
      split: "person",
      split_id: [14, 12],
    });
    expect(toFirstMentionParams(DEFAULT_TIMELINE_STATE, 100)).toEqual({});
    expect(toFirstMentionParams(full, 200)).toEqual({
      ...toFilters(list),
      role: "sent",
      limit: 200,
      lists: true,
    });
  });
});

describe("the mails behind a bar", () => {
  const plain = { ...DEFAULT_TIMELINE_STATE, list: { ...DEFAULT_LIST_STATE, q: "Spende" } };

  it("are the filters with the bucket's days, within the Zeitraum", () => {
    expect(mailListHref(bucketList(plain, "2024-03-01", "month", null))).toBe(
      "/mails?q=Spende&date_from=2024-03-01&date_to=2024-03-31",
    );
    const within = { ...plain, list: { ...plain.list, date_from: "2024-03-10" } };
    expect(mailListHref(bucketList(within, "2024-03-01", "month", null))).toBe(
      "/mails?q=Spende&date_from=2024-03-10&date_to=2024-03-31",
    );
  });

  it("add the condition of their series", () => {
    const [anna] = timelineByPerson.series;
    const [contract] = timelineByThread.series;
    const [, cash] = timelineByTerm.series;
    expect(mailListHref(bucketList(plain, "2024-03-04", "week", anna))).toBe(
      "/mails?q=Spende&date_from=2024-03-04&date_to=2024-03-10&person=11",
    );
    expect(mailListHref(bucketList(plain, "2024-03-04", "day", contract))).toBe(
      "/mails?q=Spende&date_from=2024-03-04&date_to=2024-03-04&thread=184001",
    );
    expect(bucketList(plain, "2024-03-01", "month", cash).q).toBe('Spende "schwarze Kasse"');
    expect(bucketList(DEFAULT_TIMELINE_STATE, "2024-03-01", "month", cash).q).toBe(
      '"schwarze Kasse"',
    );
  });

  it("keep a person's role only while it is the one person", () => {
    const sent = { ...DEFAULT_LIST_STATE, person: [12], person_role: "sent" as const };
    expect(withPerson(sent, 12)).toMatchObject({ person: [12], person_role: "sent" });
    expect(withPerson(sent, 11)).toMatchObject({ person: [12, 11], person_role: null });
  });
});

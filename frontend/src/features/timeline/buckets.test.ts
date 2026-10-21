import { describe, expect, it } from "vitest";

import { bucketEnd, bucketRange, formatBucket, isoWeek, timelinePath } from "./buckets";

describe("bucket days", () => {
  it("ends a day, a week and a month on their last day", () => {
    expect(bucketEnd("2021-03-04", "day")).toBe("2021-03-04");
    expect(bucketEnd("2021-03-01", "week")).toBe("2021-03-07");
    expect(bucketEnd("2020-12-28", "week")).toBe("2021-01-03");
    expect(bucketEnd("2020-02-01", "month")).toBe("2020-02-29");
    expect(bucketEnd("2021-12-01", "month")).toBe("2021-12-31");
  });

  it("keeps a bucket's range within the filter's Zeitraum", () => {
    expect(bucketRange("2021-03-01", "month")).toEqual({
      date_from: "2021-03-01",
      date_to: "2021-03-31",
    });
    expect(
      bucketRange("2021-03-01", "month", { date_from: "2021-03-10", date_to: "2021-06-30" }),
    ).toEqual({ date_from: "2021-03-10", date_to: "2021-03-31" });
    expect(bucketRange("2021-03-01", "week", { date_from: null, date_to: "2021-03-03" })).toEqual({
      date_from: "2021-03-01",
      date_to: "2021-03-03",
    });
  });
});

describe("bucket names", () => {
  it("numbers ISO weeks, also across the turn of the year", () => {
    expect(isoWeek("2021-03-01")).toEqual({ week: 9, year: 2021 });
    expect(isoWeek("2020-12-28")).toEqual({ week: 53, year: 2020 });
    expect(isoWeek("2018-12-31")).toEqual({ week: 1, year: 2019 });
    expect(isoWeek("2021-01-04")).toEqual({ week: 1, year: 2021 });
  });

  it("writes days, weeks and months in German", () => {
    expect(formatBucket("2021-03-04", "day")).toBe("04.03.2021");
    expect(formatBucket("2021-03-01", "week")).toBe("KW 9/2021");
    expect(formatBucket("2018-12-31", "week")).toBe("KW 1/2019");
    expect(formatBucket("2021-03-01", "month")).toBe("März 2021");
  });
});

describe("timeline path", () => {
  it("carries the filters and the timeline's own parameters", () => {
    expect(timelinePath({})).toBe("/zeitachse");
    expect(timelinePath({ q: "Spende", person: [3, 7] }, { split: "person", bucket: "week" })).toBe(
      "/zeitachse?q=Spende&person=3&person=7&split=person&bucket=week",
    );
  });
});

import { describe, expect, it } from "vitest";

import { timelineAll } from "../../test/fixtures";
import { axisTicks, bucketAt, bucketOf, laneShape } from "./chart";

/** The first days of count consecutive buckets from start. */
function days(start: string, count: number, stepDays: number): string[] {
  const first = new Date(`${start}T00:00:00Z`).getTime();
  return Array.from({ length: count }, (_, index) =>
    new Date(first + index * stepDays * 86_400_000).toISOString().slice(0, 10),
  );
}

const labels = (starts: string[], bucket: "day" | "week" | "month", width: number) =>
  axisTicks(starts, bucket, width).map((tick) => tick.label);

describe("buckets", () => {
  it("finds the bucket of a day and under the pointer", () => {
    const starts = ["2024-01-01", "2024-02-01", "2024-03-01"];
    expect(bucketOf(starts, "2023-12-31")).toBe(-1);
    expect(bucketOf(starts, "2024-01-01")).toBe(0);
    expect(bucketOf(starts, "2024-02-29")).toBe(1);
    expect(bucketOf(starts, "2024-03-20")).toBe(2);
    expect(bucketAt(0, 300, 3)).toBe(0);
    expect(bucketAt(150, 300, 3)).toBe(1);
    expect(bucketAt(299.9, 300, 3)).toBe(2);
    expect(bucketAt(-5, 300, 3)).toBe(0);
    expect(bucketAt(400, 300, 3)).toBe(2);
    expect(bucketAt(10, 300, 0)).toBe(-1);
  });
});

describe("a lane's bars and marks", () => {
  it("draws one bar per bucket with mails, the high ones apart with ▲ and ▽ for low ones", () => {
    const shape = laneShape(
      [2, 0, 10, 1],
      [
        { index: 2, kind: "high", expected: 2 },
        { index: 3, kind: "low", expected: 6 },
      ],
      400,
      110,
      100,
    );
    expect(shape.max).toBe(10);
    // Buckets of 100 px with a gap of 1 px; bucket 1 has no mail and no bar.
    expect(shape.bars).toBe("M0 110V90h99V110zM300 110V100h99V110z");
    expect(shape.high).toBe("M200 110V10h99V110z");
    expect(shape.above).toBe("M246 8h8l-4 -7z");
    expect(shape.below).toBe("M346 112h8l-4 7z");
  });

  it("keeps a single mail visible and joins narrow buckets without gaps", () => {
    const counts = [1, ...Array.from({ length: 1_499 }, () => 1_000)];
    const shape = laneShape(counts, [], 750, 40, 30);
    expect(shape.bars.startsWith("M0 40V38.5h0.5V40z")).toBe(true);
    expect(shape.bars.match(/M/g)).toHaveLength(1_500);
    expect(laneShape([0, 0], [], 100, 40, 30)).toEqual({
      bars: "",
      high: "",
      above: "",
      below: "",
      max: 0,
    });
  });
});

describe("axis ticks", () => {
  it("labels months by quarters and years as the width allows", () => {
    const months = timelineAll.starts;
    expect(labels(months, "month", 700).slice(0, 6)).toEqual([
      "2023",
      "Apr",
      "Jul",
      "Okt",
      "2024",
      "Apr",
    ]);
    expect(labels(months, "month", 300)).toEqual(["2023", "Jul", "2024", "Jul", "2025", "Jul"]);
    expect(labels(months, "month", 150)).toEqual(["2023", "2024", "2025"]);
    expect(labels(months.slice(3, 8), "month", 600)).toEqual([
      "Apr 2023",
      "Mai",
      "Jun",
      "Jul",
      "Aug",
    ]);
  });

  it("labels weeks by months and days by days, with the year where it starts", () => {
    expect(labels(days("2024-01-01", 20, 7), "week", 700)).toEqual([
      "2024",
      "Feb",
      "Mär",
      "Apr",
      "Mai",
    ]);
    expect(labels(days("2024-03-04", 10, 1), "day", 700)).toEqual(["04.03.2024", "11.03."]);
    expect(labels(days("2024-12-30", 4, 1), "day", 600)).toEqual([
      "30.12.2024",
      "31.12.",
      "01.01.2025",
      "02.01.",
    ]);
    // 1,500 days on a narrow axis: half years, then years; 2024 would run past the end.
    expect(labels(days("2020-01-01", 1_500, 1), "day", 400)).toEqual([
      "2020",
      "Jul",
      "2021",
      "Jul",
      "2022",
      "Jul",
      "2023",
      "Jul",
    ]);
    expect(labels(days("2020-01-01", 1_500, 1), "day", 200)).toEqual([
      "2020",
      "2021",
      "2022",
      "2023",
    ]);
  });

  it("names the first bucket when no tick falls on the axis, and none past its end", () => {
    expect(axisTicks(days("2024-03-05", 3, 1), "day", 60)).toEqual([
      { index: 0, label: "05.03.2024" },
    ]);
    expect(axisTicks([], "day", 600)).toEqual([]);
    // The one tick that fits, on Monday 11.03., would run past the right end.
    expect(axisTicks(days("2024-03-04", 10, 1), "day", 100)).toEqual([
      { index: 0, label: "04.03.2024" },
    ]);
  });
});

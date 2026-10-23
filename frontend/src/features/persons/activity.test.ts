import { describe, expect, it } from "vitest";

import type { Timeline } from "../../api/types";
import { activityLevel, activityTitle, activityWeeks, dayCounts } from "./activity";

describe("the activity grid's steps", () => {
  it("are 0 without mail, 4 for the busiest day and the quarters of it between", () => {
    expect(activityLevel(0, 20)).toBe(0);
    expect(activityLevel(1, 20)).toBe(1);
    expect(activityLevel(5, 20)).toBe(1);
    expect(activityLevel(6, 20)).toBe(2);
    expect(activityLevel(10, 20)).toBe(2);
    expect(activityLevel(11, 20)).toBe(3);
    expect(activityLevel(15, 20)).toBe(3);
    expect(activityLevel(16, 20)).toBe(4);
    expect(activityLevel(20, 20)).toBe(4);
  });

  it("give any mail at least the first step and nothing without a busiest day", () => {
    expect(activityLevel(1, 1000)).toBe(1);
    expect(activityLevel(3, 0)).toBe(0);
    expect(activityLevel(-1, 5)).toBe(0);
  });
});

describe("the activity grid's weeks", () => {
  it("lay a year out Monday first, empty before January 1st and after December 31st", () => {
    // 2026 starts on a Thursday and ends on a Thursday.
    const weeks = activityWeeks(2026, new Map([["2026-01-01", 2]]));
    expect(weeks).toHaveLength(53);
    expect(weeks.every((week) => week.length === 7)).toBe(true);
    expect(weeks[0].slice(0, 3)).toEqual([null, null, null]);
    expect(weeks[0][3]).toEqual({ day: "2026-01-01", count: 2, level: 4 });
    expect(weeks[52][3]?.day).toBe("2026-12-31");
    expect(weeks[52].slice(4)).toEqual([null, null, null]);
    expect(weeks.flat().filter(Boolean)).toHaveLength(365);
  });

  it("count a leap year's 366 days and step each day by the busiest", () => {
    const counts = new Map([
      ["2024-02-29", 8],
      ["2024-03-01", 1],
    ]);
    const days = activityWeeks(2024, counts)
      .flat()
      .filter((day) => day !== null);
    expect(days).toHaveLength(366);
    expect(days.find((day) => day.day === "2024-02-29")?.level).toBe(4);
    expect(days.find((day) => day.day === "2024-03-01")?.level).toBe(1);
    expect(days.find((day) => day.day === "2024-03-02")?.level).toBe(0);
  });

  it("take the counts of a day timeline only", () => {
    const timeline = {
      bucket: "day",
      starts: ["2026-01-01", "2026-01-02", "2026-01-03"],
      total: { counts: [0, 4, 1] },
    } as unknown as Timeline;
    expect([...dayCounts(timeline)]).toEqual([
      ["2026-01-02", 4],
      ["2026-01-03", 1],
    ]);
    expect(dayCounts({ ...timeline, bucket: "month" }).size).toBe(0);
    expect(dayCounts({ ...timeline, total: null }).size).toBe(0);
    expect(dayCounts(undefined).size).toBe(0);
  });

  it("name a day's mails in the tooltip", () => {
    expect(activityTitle({ day: "2024-02-14", count: 3, level: 2 })).toBe("3 Mails am 14.02.2024");
    expect(activityTitle({ day: "2024-02-15", count: 1, level: 1 })).toBe("1 Mail am 15.02.2024");
    expect(activityTitle({ day: "2024-02-16", count: 0, level: 0 })).toBe(
      "Keine Mail am 16.02.2024",
    );
  });
});

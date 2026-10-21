import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatDate,
  formatDateTime,
  formatDateTimeLong,
  formatDay,
  formatDuration,
  formatIsoDay,
  formatNumber,
  formatPercent,
  formatRelative,
  formatRemaining,
  formatShortDate,
  utcDay,
} from "./format";

// vite.config.ts pins the tests to Europe/Berlin.

describe("numbers", () => {
  it("groups thousands with dots", () => {
    expect(formatNumber(412318)).toBe("412.318");
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(1_883_204_117)).toBe("1.883.204.117");
  });

  it("writes percentages with a comma and one decimal", () => {
    expect(formatPercent(0.651)).toBe("65,1\u00a0%");
    expect(formatPercent(1)).toBe("100,0\u00a0%");
  });
});

describe("sizes", () => {
  it("are 1024-based with German units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(188_416)).toBe("184 KB");
    expect(formatBytes(14_336)).toBe("14 KB");
    expect(formatBytes(1.2 * 1024 ** 2)).toBe("1,2 MB");
    expect(formatBytes(4 * 1024 ** 3)).toBe("4,0 GB");
  });

  it("move to the next unit instead of showing 1024", () => {
    expect(formatBytes(1024 ** 2 - 1)).toBe("1,0 MB");
    expect(formatBytes(1024 ** 3 - 1)).toBe("1,0 GB");
  });
});

describe("durations", () => {
  it("are short", () => {
    expect(formatDuration(30)).toBe("30 s");
    expect(formatDuration(600)).toBe("10 min");
    expect(formatDuration(43200)).toBe("12 h");
    expect(formatDuration(86400)).toBe("1 Tag");
    expect(formatDuration(7 * 86400)).toBe("7 Tage");
  });

  it("are exact to the minute as a remaining time", () => {
    expect(formatRemaining(20)).toBe("unter 1 min");
    expect(formatRemaining(168)).toBe("3 min");
    expect(formatRemaining(6012)).toBe("1 h 40 min");
    expect(formatRemaining(26 * 3600 + 10)).toBe("26 h");
  });
});

describe("dates", () => {
  const summer = "2026-10-18T12:32:07Z";

  it("are shown in the browser's time zone", () => {
    expect(formatDateTime(summer)).toBe("18.10.2026 14:32");
    expect(formatDateTime(summer, true)).toBe("18.10.2026 14:32:07");
    expect(formatDateTime("2026-01-05T12:00:00Z")).toBe("05.01.2026 13:00");
  });

  it("have a weekday in the long form", () => {
    expect(formatDateTimeLong(summer)).toBe("So, 18.10.2026 14:32:07");
    expect(formatDateTimeLong("2026-10-17T22:05:00Z")).toBe("So, 18.10.2026 00:05:00");
  });

  it("drop the year when it is the reference's", () => {
    expect(formatShortDate("2026-10-09T14:02:00Z", summer)).toBe("09.10.");
    expect(formatShortDate("2025-12-30T14:02:00Z", summer)).toBe("30.12.2025");
    expect(formatShortDate("2025-12-30T14:02:00Z")).toBe("30.12.");
  });

  it("give local and UTC days", () => {
    expect(formatIsoDay("2014-03-01T23:30:00Z")).toBe("2014-03-02");
    expect(utcDay("2014-03-01T23:30:00Z")).toBe("2014-03-01");
    expect(utcDay("2014-03-02T00:30:00+02:00")).toBe("2014-03-01");
    expect(formatDay("2026-10-20")).toBe("20.10.2026");
    expect(formatDate("2014-03-01T23:30:00Z")).toBe("02.03.2014");
  });

  it("count calendar days, months and years back from now", () => {
    const now = new Date("2026-10-20T09:00:00Z");
    expect(formatRelative("2026-10-20T05:00:00Z", now)).toBe("heute");
    expect(formatRelative("2026-10-19T21:00:00Z", now)).toBe("gestern");
    expect(formatRelative(summer, now)).toBe("vor 2 Tagen");
    expect(formatRelative("2026-07-01T10:00:00Z", now)).toBe("vor 3 Monaten");
    expect(formatRelative("2024-05-01T10:00:00Z", now)).toBe("vor 2 Jahren");
    expect(formatRelative("2026-10-21T10:00:00Z", now)).toBe("morgen");
  });
});

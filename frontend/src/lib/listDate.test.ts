import { describe, expect, it } from "vitest";

import { formatListDate } from "./listDate";

// The tests run in Europe/Berlin.
const now = new Date("2026-10-18T15:00:00Z");

describe("formatListDate", () => {
  it("shows the time for today, in the browser's time zone", () => {
    expect(formatListDate("2026-10-18T12:32:07Z", now)).toBe("14:32");
    expect(formatListDate("2026-10-17T22:30:00Z", now)).toBe("00:30");
  });

  it("shows day and month in this year and the full date before it", () => {
    expect(formatListDate("2026-06-24T09:00:00Z", now)).toBe("24. Juni");
    expect(formatListDate("2024-06-24T09:00:00Z", now)).toBe("24.06.2024");
  });
});

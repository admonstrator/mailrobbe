// Buckets of the timeline (D91) as the screens use them: the days a bucket covers, its name,
// and the URL of the timeline for a filter.

import { withQuery } from "../../api/client";
import type { MailFilters, TimelineBucket, TimelineParams } from "../../api/types";

const MONTHS = [
  "Januar",
  "Februar",
  "März",
  "April",
  "Mai",
  "Juni",
  "Juli",
  "August",
  "September",
  "Oktober",
  "November",
  "Dezember",
];

const DAY_MS = 86_400_000;

function toDate(day: string): Date {
  return new Date(`${day}T00:00:00Z`);
}

function toDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** The last day (inclusive) of the bucket that starts at start (YYYY-MM-DD, UTC). */
export function bucketEnd(start: string, bucket: TimelineBucket): string {
  const date = toDate(start);
  if (bucket === "day") return start;
  if (bucket === "week") return toDay(new Date(date.getTime() + 6 * DAY_MS));
  return toDay(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)));
}

/** The days of a bucket within the filter's Zeitraum: what a click on the bucket sets as the
 *  mail list's date_from and date_to. */
export function bucketRange(
  start: string,
  bucket: TimelineBucket,
  within: { date_from?: string | null; date_to?: string | null } = {},
): { date_from: string; date_to: string } {
  const end = bucketEnd(start, bucket);
  return {
    date_from: within.date_from && within.date_from > start ? within.date_from : start,
    date_to: within.date_to && within.date_to < end ? within.date_to : end,
  };
}

/** ISO 8601 week number and its year of the week that starts on Monday `start`. */
export function isoWeek(start: string): { week: number; year: number } {
  const thursday = new Date(toDate(start).getTime() + 3 * DAY_MS);
  const year = thursday.getUTCFullYear();
  const firstThursday = new Date(Date.UTC(year, 0, 4));
  const week = 1 + Math.round((thursday.getTime() - firstThursday.getTime()) / (7 * DAY_MS));
  return { week, year };
}

/** "04.03.2021", "KW 9/2021", "März 2021". */
export function formatBucket(start: string, bucket: TimelineBucket): string {
  const [year, month, day] = start.split("-");
  if (bucket === "day") return `${day}.${month}.${year}`;
  if (bucket === "week") {
    const iso = isoWeek(start);
    return `KW ${iso.week}/${iso.year}`;
  }
  return `${MONTHS[Number(month) - 1]} ${year}`;
}

/** The timeline screen for these filters, plus its own parameters. */
export function timelinePath(
  filters: MailFilters,
  extra: Omit<TimelineParams, keyof MailFilters> = {},
): string {
  return withQuery("/zeitachse", { ...filters, ...extra });
}

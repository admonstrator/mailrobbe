// The activity grid of a person's profile (D336): one year of UTC days as weeks (columns, Monday
// first) by weekdays (rows), each day in one of five steps of the accent, as GitHub shows it.

import type { Timeline } from "../../api/types";
import { formatNumber } from "../../lib/format";

/** The steps of a day: 0 for none, 1 to 4 by its share of the year's busiest day. */
export type ActivityLevel = 0 | 1 | 2 | 3 | 4;

export const ACTIVITY_LEVELS: readonly ActivityLevel[] = [0, 1, 2, 3, 4];

/** The step of a day with count mails in a year whose busiest day has max: none is 0, any
 *  mail at least 1, the busiest 4, and the quarters of max in between. */
export function activityLevel(count: number, max: number): ActivityLevel {
  if (count <= 0 || max <= 0) return 0;
  const level = Math.ceil((count / max) * 4);
  return Math.min(4, Math.max(1, level)) as ActivityLevel;
}

export interface ActivityDay {
  day: string; // YYYY-MM-DD
  count: number;
  level: ActivityLevel;
}

/** A week of the grid: seven places Monday to Sunday, null before January 1st and after
 *  December 31st. */
export type ActivityWeek = (ActivityDay | null)[];

const DAY_MS = 86_400_000;

function isoDay(time: number): string {
  return new Date(time).toISOString().slice(0, 10);
}

/** The mails per UTC day of a day timeline, by its starts. */
export function dayCounts(timeline: Timeline | undefined): Map<string, number> {
  const counts = new Map<string, number>();
  const total = timeline?.total;
  if (!timeline || !total || timeline.bucket !== "day") return counts;
  timeline.starts.forEach((start, index) => {
    const count = total.counts[index] ?? 0;
    if (count > 0) counts.set(start, count);
  });
  return counts;
}

/** The weeks of year with the counts of its days. */
export function activityWeeks(year: number, counts: Map<string, number>): ActivityWeek[] {
  const start = Date.UTC(year, 0, 1);
  const end = Date.UTC(year + 1, 0, 1);
  const max = Math.max(0, ...counts.values());
  // Monday is 0: the places of the first week before January 1st stay empty.
  const offset = (new Date(start).getUTCDay() + 6) % 7;
  const weeks: ActivityWeek[] = [];
  let week: ActivityWeek = Array.from({ length: offset }, () => null);
  for (let time = start; time < end; time += DAY_MS) {
    const day = isoDay(time);
    const count = counts.get(day) ?? 0;
    week.push({ day, count, level: activityLevel(count, max) });
    if (week.length === 7) {
      weeks.push(week);
      week = [];
    }
  }
  if (week.length > 0)
    weeks.push([...week, ...Array.from({ length: 7 - week.length }, () => null)]);
  return weeks;
}

/** "3 Mails am 14.02.2024", "Keine Mail am 15.02.2024". */
export function activityTitle({ day, count }: ActivityDay): string {
  const [y, m, d] = day.split("-");
  const date = `${d}.${m}.${y}`;
  if (count === 0) return `Keine Mail am ${date}`;
  return `${formatNumber(count)} ${count === 1 ? "Mail" : "Mails"} am ${date}`;
}

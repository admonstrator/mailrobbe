// What the timeline draws, as plain data: the bars and marks of a lane as a few SVG paths (so
// 1,500 buckets in a dozen lanes stay cheap), the ticks of the axis, and the bucket of a day.
// Pure, so the rules are tested without a browser.

import type { TimelineBucket, TimelineOutlier } from "../../api/types";
import { isoWeek } from "./buckets";

/** Space above the bars for ▲ and below the base line for ▽. */
export const MARK_SPACE = 10;
/** A bar with mails is at least this high, so a single mail stays visible. */
const MIN_BAR = 1.5;

const round = (value: number) => Math.round(value * 100) / 100;

/** The bucket a day (YYYY-MM-DD) falls into: the last start not after it; -1 before the first. */
export function bucketOf(starts: readonly string[], day: string): number {
  let low = 0;
  let high = starts.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (starts[middle] <= day) {
      found = middle;
      low = middle + 1;
    } else high = middle - 1;
  }
  return found;
}

/** The bucket under x (0 to width) on an axis of count buckets. */
export function bucketAt(x: number, width: number, count: number): number {
  if (count === 0 || width <= 0) return -1;
  return Math.min(count - 1, Math.max(0, Math.floor((x / width) * count)));
}

export interface LaneShape {
  /** The bars without a mark. */
  bars: string;
  /** The bars far above the moving mean. */
  high: string;
  /** ▲ above each of them. */
  above: string;
  /** ▽ under the base line for each bucket far below it. */
  below: string;
  /** The highest count: the lane's own scale. */
  max: number;
}

/** The bars of one lane: buckets side by side over width, bars up to height above base. */
export function laneShape(
  counts: readonly number[],
  outliers: readonly TimelineOutlier[],
  width: number,
  base: number,
  height: number,
): LaneShape {
  const step = counts.length ? width / counts.length : 0;
  // A gap between bars where they are wide enough for one.
  const barWidth = round(step >= 3 ? step - 1 : step);
  const marks = new Map(outliers.map((outlier) => [outlier.index, outlier.kind]));
  let max = 0;
  for (const count of counts) if (count > max) max = count;
  const bars: string[] = [];
  const high: string[] = [];
  const above: string[] = [];
  const below: string[] = [];
  counts.forEach((count, index) => {
    const x = index * step;
    const center = round(x + step / 2);
    const kind = marks.get(index);
    if (kind === "low") below.push(`M${round(center - 4)} ${base + 2}h8l-4 7z`);
    if (count <= 0 || max === 0) return;
    const h = Math.max(MIN_BAR, (count / max) * height);
    const top = round(base - h);
    const bar = `M${round(x)} ${base}V${top}h${barWidth}V${base}z`;
    if (kind === "high") {
      high.push(bar);
      above.push(`M${round(center - 4)} ${round(top - 2)}h8l-4 -7z`);
    } else bars.push(bar);
  });
  return {
    bars: bars.join(""),
    high: high.join(""),
    above: above.join(""),
    below: below.join(""),
    max,
  };
}

export interface Tick {
  index: number;
  label: string;
}

const SHORT_MONTHS = [
  "Jan",
  "Feb",
  "Mär",
  "Apr",
  "Mai",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Okt",
  "Nov",
  "Dez",
];

const yearOf = (start: string) => start.slice(0, 4);
const monthOf = (start: string) => Number(start.slice(5, 7));
const dayOf = (start: string) => Number(start.slice(8, 10));

/** Days as "04.03.", with the year where it starts or changes: "04.03.2024". */
function dayLabel(start: string, previous: string | null): string {
  const day = `${start.slice(8, 10)}.${start.slice(5, 7)}.`;
  return previous === null || yearOf(previous) !== yearOf(start) ? `${day}${yearOf(start)}` : day;
}

/** Months as "Apr", the year at January ("2024") and on the first tick ("Apr 2023"). */
function monthLabel(start: string, previous: string | null): string {
  if (monthOf(start) === 1) return yearOf(start);
  const month = SHORT_MONTHS[monthOf(start) - 1];
  return previous === null ? `${month} ${yearOf(start)}` : month;
}

const yearLabel = (start: string) => yearOf(start);

interface Level {
  pick: (start: string) => boolean;
  label: (start: string, previous: string | null) => string;
}

/** The first bucket of a month: its first day, the week of its first Monday, or the month. */
function monthStart(bucket: TimelineBucket): (start: string) => boolean {
  if (bucket === "day") return (start) => dayOf(start) === 1;
  if (bucket === "week") return (start) => dayOf(start) <= 7;
  return () => true;
}

/** Tick levels from fine to coarse: days for days, months for weeks, years for months, thinned
 *  out to every other Monday, quarter, or 2, 5, 10 ... years as the width demands. */
function levels(bucket: TimelineBucket): Level[] {
  const inMonth = monthStart(bucket);
  const months = (every: number): Level => ({
    pick: (start) => inMonth(start) && (monthOf(start) - 1) % every === 0,
    label: monthLabel,
  });
  const years = [1, 2, 5, 10, 20, 50, 100].map((every): Level => ({
    pick: (start) => inMonth(start) && monthOf(start) === 1 && Number(yearOf(start)) % every === 0,
    label: yearLabel,
  }));
  const monday = (start: string) => new Date(`${start}T00:00:00Z`).getUTCDay() === 1;
  const days: Level[] =
    bucket === "day"
      ? [
          { pick: () => true, label: dayLabel },
          { pick: monday, label: dayLabel },
          { pick: (start) => monday(start) && isoWeek(start).week % 2 === 1, label: dayLabel },
        ]
      : bucket === "week"
        ? [
            { pick: () => true, label: dayLabel },
            { pick: (start) => isoWeek(start).week % 2 === 1, label: dayLabel },
          ]
        : [];
  return [...days, months(1), months(3), months(6), ...years];
}

/** Estimated width of a label in the axis font (11 px), plus room before the next one. */
function labelSpace(label: string): number {
  return label.length * 6.6 + 12;
}

/** The labelled ticks of an axis of these buckets over width: the finest level whose labels
 *  do not touch, without a label running past the right end; the first bucket's name when no
 *  level has a tick. */
export function axisTicks(
  starts: readonly string[],
  bucket: TimelineBucket,
  width: number,
): Tick[] {
  if (starts.length === 0) return [];
  const step = width / starts.length;
  const all = levels(bucket);
  for (const [position, level] of all.entries()) {
    const ticks: Tick[] = [];
    let previous: string | null = null;
    starts.forEach((start, index) => {
      if (!level.pick(start)) return;
      ticks.push({ index, label: level.label(start, previous) });
      previous = start;
    });
    const fits = ticks.every(
      (tick, at) =>
        at === ticks.length - 1 ||
        (ticks[at + 1].index - tick.index) * step >= labelSpace(tick.label),
    );
    if (!fits && position < all.length - 1) continue;
    const shown = ticks.filter((tick) => tick.index * step + labelSpace(tick.label) - 12 <= width);
    return shown.length ? shown : [{ index: 0, label: all[0].label(starts[0], null) }];
  }
  return [];
}

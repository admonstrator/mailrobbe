// The compact timeline above the mail list and in the person profile (D90, D93): the matching
// mails per bucket as bars in one SVG, with the marks of the timeline screen. It sits in the main
// chunk on the most used screen, so it stays small: the bucket under the pointer is found from
// its position, and the keyboard moves through the buckets of one focusable chart.

import { memo, useId, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { Link } from "react-router";

import { useTimeline } from "../../api/queries";
import {
  MAX_TIMELINE_BUCKETS,
  type MailFilters,
  type Timeline,
  type TimelineBucket,
  type TimelineSeries,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { bucketRange, formatBucket, timelinePath } from "./buckets";
import styles from "./MiniTimeline.module.css";

const BUCKET_NAMES: Record<TimelineBucket, string> = { day: "Tag", week: "Woche", month: "Monat" };

// The chart in pixels: room for ▲ above the bars, the bars, ▽ under the axis.
const TOP = 10;
const AXIS = 70;
const HEIGHT = 80;

const STORAGE_KEY = "mailrobbe.timeline";

function loadShown(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "hidden";
  } catch {
    return true; // storage blocked: shown
  }
}

function saveShown(shown: boolean): void {
  try {
    if (shown) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, "hidden");
  } catch {
    // storage blocked: the choice lasts until reload
  }
}

function mailCount(count: number): string {
  return `${formatNumber(count)} ${count === 1 ? "Mail" : "Mails"}`;
}

/** "März 2024: 4.300 Mails · üblich etwa 1.216" for a marked bucket, else without the mean. */
function bucketText(timeline: Timeline, series: TimelineSeries, index: number): string {
  const text = `${formatBucket(timeline.starts[index], timeline.bucket)}: ${mailCount(series.counts[index])}`;
  const outlier = series.outliers.find((other) => other.index === index);
  return outlier ? `${text} · üblich etwa ${formatNumber(Math.round(outlier.expected))}` : text;
}

/** The first bucket of the silent stretch, or -1. */
function silentIndex(timeline: Timeline, series: TimelineSeries): number {
  const from = series.silent_from;
  return from === null ? -1 : timeline.starts.findLastIndex((start) => start <= from);
}

/** The days of a bucket, as the mail list's Zeitraum takes them. */
type BucketDays = { date_from: string; date_to: string };

/** The bars and their marks; drawn again only for new data, not on every pointer move. */
const Bars = memo(function Bars({
  series,
  max,
  up,
  down,
}: {
  series: TimelineSeries;
  max: number;
  up: string;
  down: string;
}) {
  const slot = 100 / series.counts.length;
  const gap = series.counts.length <= 120 ? slot * 0.2 : 0;
  const top = (count: number) => AXIS - (count > 0 ? Math.max(1, (count / max) * (AXIS - TOP)) : 0);
  const high = new Set(series.outliers.flatMap((o) => (o.kind === "high" ? [o.index] : [])));
  return (
    <g>
      {series.counts.map((count, index) =>
        count > 0 ? (
          <rect
            key={index}
            className={cx(styles.bar, high.has(index) && styles.high)}
            x={`${index * slot + gap / 2}%`}
            width={`${slot - gap}%`}
            y={top(count)}
            height={AXIS - top(count)}
          />
        ) : null,
      )}
      {series.outliers.map((outlier) => (
        <use
          key={outlier.index}
          href={`#${outlier.kind === "high" ? up : down}`}
          className={outlier.kind === "high" ? styles.up : styles.down}
          data-mark={outlier.kind}
          x={`${(outlier.index + 0.5) * slot}%`}
          y={outlier.kind === "high" ? top(series.counts[outlier.index]) - 2 : AXIS + 2}
        />
      ))}
    </g>
  );
});

function Chart({
  timeline,
  series,
  within,
  onPick,
}: {
  timeline: Timeline;
  series: TimelineSeries;
  within: MailFilters;
  onPick: (range: BucketDays) => void;
}) {
  const id = useId();
  // The bucket shown in the tooltip, by its first day, so new data does not shift it.
  const [shown, setShown] = useState<string | null>(null);
  const { starts, bucket } = timeline;
  const count = starts.length;
  const found = shown === null ? -1 : starts.indexOf(shown);
  const index = found >= 0 ? found : null;
  const slot = 100 / count;
  const max = Math.max(1, ...series.counts);
  const silent = silentIndex(timeline, series);

  const at = (event: MouseEvent<HTMLElement>): number | null => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return null;
    const position = Math.floor(((event.clientX - box.left) / box.width) * count);
    return Math.min(count - 1, Math.max(0, position));
  };
  const pick = (bucketIndex: number) => onPick(bucketRange(starts[bucketIndex], bucket, within));
  const show = (bucketIndex: number) =>
    setShown(starts[Math.min(count - 1, Math.max(0, bucketIndex))]);

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "ArrowLeft") show(index === null ? count - 1 : index - 1);
    else if (event.key === "ArrowRight") show(index === null ? 0 : index + 1);
    else if (event.key === "Home") show(0);
    else if (event.key === "End") show(count - 1);
    else if (event.key === "Enter" && index !== null) pick(index);
    else return;
    event.preventDefault();
  }

  const current = index ?? count - 1;
  const place = index === null ? 0 : (index + 0.5) * slot;
  return (
    <div className={styles.chart}>
      <div className={styles.scale} aria-hidden="true">
        <span>{formatNumber(max)}</span>
        <span>0</span>
      </div>
      <div
        role="slider"
        tabIndex={0}
        className={styles.plot}
        aria-label={`Mails pro ${BUCKET_NAMES[bucket]}`}
        aria-valuemin={0}
        aria-valuemax={count - 1}
        aria-valuenow={current}
        aria-valuetext={bucketText(timeline, series, current)}
        onPointerMove={(event) => {
          const position = at(event);
          if (position !== null) show(position);
        }}
        onPointerLeave={() => setShown(null)}
        onFocus={() => {
          if (index === null) show(count - 1);
        }}
        onBlur={() => setShown(null)}
        onClick={(event) => {
          const position = at(event);
          if (position !== null) pick(position);
        }}
        onKeyDown={onKeyDown}
      >
        <svg width="100%" height={HEIGHT} aria-hidden="true">
          <defs>
            <path id={`${id}up`} d="M-4 0H4L0-7Z" />
            <path id={`${id}down`} d="M-4 0H4L0 7Z" />
            <pattern
              id={`${id}hatch`}
              width={6}
              height={6}
              patternUnits="userSpaceOnUse"
              patternTransform="rotate(45)"
            >
              <line className={styles.hatch} x1={0} y1={0} x2={0} y2={6} />
            </pattern>
          </defs>
          {silent >= 0 && (
            <rect
              data-mark="silent"
              x={`${silent * slot}%`}
              width={`${(count - silent) * slot}%`}
              y={0}
              height={AXIS}
              fill={`url(#${id}hatch)`}
            />
          )}
          {index !== null && (
            <rect
              className={styles.hover}
              x={`${index * slot}%`}
              width={`${slot}%`}
              y={0}
              height={HEIGHT}
            />
          )}
          <Bars series={series} max={max} up={`${id}up`} down={`${id}down`} />
          <line className={styles.axis} x1={0} x2="100%" y1={AXIS + 0.5} y2={AXIS + 0.5} />
        </svg>
        {index !== null && (
          <div
            className={cx(styles.tip, place < 15 && styles.tipStart, place > 85 && styles.tipEnd)}
            style={{ left: `${place}%` }}
            aria-hidden="true"
          >
            {bucketText(timeline, series, index)}
          </div>
        )}
      </div>
      <div className={styles.ends} aria-hidden="true">
        <span>{formatBucket(starts[0], bucket)}</span>
        {count > 1 && <span>{formatBucket(starts[count - 1], bucket)}</span>}
      </div>
    </div>
  );
}

/** What the marks mean, the silence, and what the chart leaves out; only what applies. */
function Notes({ timeline, series }: { timeline: Timeline; series: TimelineSeries }) {
  const notes: ReactNode[] = [];
  if (series.outliers.some((outlier) => outlier.kind === "high")) {
    notes.push(
      <li key="high">
        <span className={styles.upGlyph} aria-hidden="true">
          ▲
        </span>{" "}
        viel mehr als üblich
      </li>,
    );
  }
  if (series.outliers.some((outlier) => outlier.kind === "low")) {
    notes.push(
      <li key="low">
        <span className={styles.downGlyph} aria-hidden="true">
          ▽
        </span>{" "}
        viel weniger als üblich
      </li>,
    );
  }
  const silent = silentIndex(timeline, series);
  if (silent >= 0) {
    notes.push(
      <li key="silent">
        <span className={styles.swatch} aria-hidden="true" /> verstummt seit{" "}
        {formatBucket(timeline.starts[silent], timeline.bucket)}
      </li>,
    );
  }
  if (timeline.undated) notes.push(<li key="undated">{mailCount(timeline.undated)} ohne Datum</li>);
  if (timeline.coarsened) {
    notes.push(
      <li key="coarsened">
        gröber eingeteilt, sonst über {formatNumber(MAX_TIMELINE_BUCKETS)} Balken
      </li>,
    );
  }
  return notes.length > 0 && <ul className={styles.notes}>{notes}</ul>;
}

/** The matching mails of filters over time as a small histogram in a card (D90). A click on a
 *  bar, or Enter on the focused one, hands its days within the filter's Zeitraum to onPick; the
 *  parent decides what that opens. collapsible: the mail list's card, which can be hidden (and
 *  then counts nothing), remembered in this browser. silenceLine: also says a silence of the
 *  total in words under the title, as the person profile does. */
export function MiniTimeline({
  filters,
  bucket,
  onPick,
  collapsible = false,
  silenceLine = false,
}: {
  filters: MailFilters;
  bucket?: TimelineBucket;
  onPick: (range: BucketDays) => void;
  collapsible?: boolean;
  silenceLine?: boolean;
}) {
  const [shown, setShown] = useState(() => !collapsible || loadShown());
  const timeline = useTimeline({ ...filters, bucket }, shown);
  const data = timeline.data;
  const series = data?.total ?? null;
  const shownBucket = data?.bucket ?? bucket;
  const drawn = data && series && series.total > 0 && data.starts.length > 0;
  const silent = drawn ? silentIndex(data, series) : -1;

  function toggle() {
    setShown(!shown);
    saveShown(!shown);
  }

  let body;
  if (!data) {
    body = timeline.isError ? (
      <p className={styles.line}>Die Zeitachse konnte nicht geladen werden.</p>
    ) : (
      <div className={styles.placeholder} aria-busy="true" aria-label="Zeitachse wird geladen" />
    );
  } else if (series === null) {
    body = <p className={styles.line}>Zeitachse: Zählung dauerte zu lange</p>;
  } else if (!drawn) {
    body = (
      <p className={styles.line}>
        Zeitachse: keine datierten Mails
        {data.undated ? ` · ${mailCount(data.undated)} ohne Datum` : ""}
      </p>
    );
  } else {
    body = (
      <div className={cx(styles.body, timeline.isPlaceholderData && styles.stale)}>
        <Chart timeline={data} series={series} within={filters} onPick={onPick} />
        <Notes timeline={data} series={series} />
      </div>
    );
  }

  return (
    <Card className={styles.card}>
      <div className={styles.head}>
        <CardTitle>
          {shownBucket ? `Verlauf pro ${BUCKET_NAMES[shownBucket]}` : "Verlauf"}
        </CardTitle>
        {shown && drawn && (
          <span className={styles.hint}>Klick auf einen Balken zeigt seine Mails</span>
        )}
        <span className={styles.links}>
          <Link to={timelinePath(filters, bucket ? { bucket } : {})}>Zeitachse öffnen</Link>
          {collapsible && (
            <Button variant="link" size="sm" onClick={toggle}>
              {shown ? "Zeitachse ausblenden" : "Zeitachse einblenden"}
            </Button>
          )}
        </span>
      </div>
      {shown && silenceLine && drawn && silent >= 0 && (
        <p className={styles.silence}>
          Seit {formatBucket(data.starts[silent], data.bucket)} keine Mails mehr
        </p>
      )}
      {shown && body}
    </Card>
  );
}

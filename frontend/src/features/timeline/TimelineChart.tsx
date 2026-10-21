import {
  Fragment,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Link, useNavigate } from "react-router";

import type { FirstMention, TimelineBucket, TimelineSeries } from "../../api/types";
import { personPath } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { formatNumber, utcDay } from "../../lib/format";
import { personName } from "../../lib/person";
import { bucketEnd, formatBucket } from "./buckets";
import { axisTicks, bucketAt, bucketOf, laneShape, MARK_SPACE, type Tick } from "./chart";
import { bucketText, mailsText, personsText, seriesName } from "./labels";
import styles from "./TimelineChart.module.css";

/** One colour per series lane, from the map's domain palette without its ambers, which belong
 *  to the marks; more lanes repeat them, each lane carries its name anyway. */
const SERIES_COLORS = ["#0F766E", "#7C3AED", "#BE185D", "#0E7490", "#4D7C0F", "#475569"];

const LABEL_WIDTH = 200;
const GAP = 16;
/** The width until the container is measured (and in tests, which have no layout). */
const DEFAULT_WIDTH = 960;
const MIN_PLOT = 240;
const TOTAL_HEIGHT = 112;
const SERIES_HEIGHT = 32;
const MENTION_HEIGHT = 28;
const AXIS_HEIGHT = 22;
/** Half the tooltip's usual width: it stays inside the chart. */
const TOOLTIP_HALF = 110;
/** Names a first-mention dot lists before "+N weitere". */
const MENTION_NAMES = 4;

interface Lane {
  key: string;
  name: string;
  /** null: the lane of the first mentions. */
  series: TimelineSeries | null;
  color: string | null;
  /** Height of the bars' area. */
  height: number;
}

/** The bucket under the pointer or the keyboard, and where its tooltip goes in the chart. */
interface Active {
  key: string;
  index: number;
  left: number;
  top: number;
}

/** The persons whose first mention falls into each bucket. */
function mentionsByBucket(
  mentions: readonly FirstMention[],
  starts: readonly string[],
  bucket: TimelineBucket,
): Map<number, FirstMention[]> {
  const byBucket = new Map<number, FirstMention[]>();
  const end = starts.length ? bucketEnd(starts[starts.length - 1], bucket) : "";
  for (const mention of mentions) {
    const day = utcDay(mention.date);
    const index = bucketOf(starts, day);
    if (index < 0 || day > end) continue;
    byBucket.set(index, [...(byBucket.get(index) ?? []), mention]);
  }
  return byBucket;
}

function namesText(mentions: readonly FirstMention[]): string {
  const names = mentions.slice(0, MENTION_NAMES).map((m) => personName(m.person));
  const more = mentions.length - names.length;
  return more > 0 ? `${names.join(", ")} +${formatNumber(more)} weitere` : names.join(", ");
}

/** The timeline (D90): the total as bars, every series as a lane of its own on the same axis,
 *  the first mentions as dots, and the axis. Lanes are sliders over the buckets: the pointer or
 *  the arrow keys pick a bucket, which shows its figures; a click or Enter opens its mails. */
export function TimelineChart({
  bucket,
  starts,
  total,
  series,
  mentions,
  mentionPersons,
  hrefFor,
  stale,
}: {
  bucket: TimelineBucket;
  starts: string[];
  total: TimelineSeries;
  series: TimelineSeries[];
  /** The first mentions listed; their lane is left out when there are none. */
  mentions: FirstMention[];
  /** Persons with a first mention in all; null: unknown. */
  mentionPersons: number | null;
  /** The mail list of a bucket of a series; null: the first mentions' lane, like the total. */
  hrefFor: (series: TimelineSeries | null, index: number) => string;
  stale: boolean;
}) {
  const navigate = useNavigate();
  const container = useRef<HTMLDivElement>(null);
  const hintId = useId();
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [active, setActive] = useState<Active | null>(null);
  const [cursor, setCursor] = useState(0);

  useEffect(() => {
    const element = container.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const plotWidth = Math.max(MIN_PLOT, Math.floor(width) - LABEL_WIDTH - GAP);
  const count = starts.length;
  const step = plotWidth / count;
  const at = Math.min(cursor, count - 1);
  const ticks = useMemo(() => axisTicks(starts, bucket, plotWidth), [starts, bucket, plotWidth]);
  const byBucket = useMemo(
    () => mentionsByBucket(mentions, starts, bucket),
    [mentions, starts, bucket],
  );

  const lanes: Lane[] = [
    { key: total.key, name: "Alle Treffer", series: total, color: null, height: TOTAL_HEIGHT },
    ...series.map((one, index) => ({
      key: one.key,
      name: seriesName(one),
      series: one,
      color: SERIES_COLORS[index % SERIES_COLORS.length],
      height: SERIES_HEIGHT,
    })),
  ];
  if (mentions.length) {
    lanes.push({
      key: "mentions",
      name: "Erste Erwähnungen",
      series: null,
      color: null,
      height: MENTION_HEIGHT,
    });
  }

  /** The tooltip's lines for a bucket of a lane. */
  function lines(lane: Lane, index: number): string[] {
    const start = starts[index];
    if (!lane.series) {
      const first = byBucket.get(index) ?? [];
      const what = first.length ? `zuerst ${namesText(first)}` : "keine erste Erwähnung";
      return [`${formatBucket(start, bucket)}: ${what}`];
    }
    const text = [bucketText(lane.series, index, start, bucket)];
    const mark = lane.series.outliers.find((outlier) => outlier.index === index)?.kind;
    if (mark === "high") text.push("▲ viel mehr als üblich");
    if (mark === "low") text.push("▽ viel weniger als üblich");
    const silent = lane.series.silent_from;
    if (silent && start >= silent) text.push(`verstummt seit ${formatBucket(silent, bucket)}`);
    return text;
  }

  function show(key: string, index: number, plot: Element) {
    // Relative to the chart, whose own layout puts the plots right of the labels.
    const box = container.current?.getBoundingClientRect() ?? { left: 0, top: 0 };
    const rect = plot.getBoundingClientRect();
    setActive({
      key,
      index,
      left: rect.left - box.left + (index + 0.5) * step,
      top: rect.top - box.top,
    });
  }

  function open(lane: Lane, index: number) {
    void navigate(hrefFor(lane.series, index));
  }

  const shown = active && lanes.find((lane) => lane.key === active.key);

  return (
    <div
      ref={container}
      className={cx(styles.chart, stale && styles.stale)}
      style={{ gridTemplateColumns: `${LABEL_WIDTH}px minmax(0, 1fr)`, columnGap: GAP }}
    >
      {lanes.map((lane) => (
        <Fragment key={lane.key}>
          <LaneLabel
            lane={lane}
            bucket={bucket}
            mentionPersons={mentionPersons}
            listed={mentions.length}
          />
          <Plot
            name={lane.name}
            width={plotWidth}
            height={lane.height + 2 * MARK_SPACE}
            count={count}
            ticks={ticks}
            column={active ? active.index : null}
            cursor={at}
            valueText={lines(lane, at).join(" · ")}
            hintId={hintId}
            onPoint={(index, plot) => show(lane.key, index, plot)}
            onFocusPlot={(plot) => {
              if (active?.key !== lane.key) show(lane.key, at, plot);
            }}
            onCursor={(index, plot) => {
              setCursor(index);
              show(lane.key, index, plot);
            }}
            onLeave={() => setActive((current) => (current?.key === lane.key ? null : current))}
            onOpen={(index) => open(lane, index)}
          >
            {lane.series ? (
              <SeriesMarks series={lane.series} lane={lane} starts={starts} width={plotWidth} />
            ) : (
              <MentionDots
                byBucket={byBucket}
                step={step}
                width={plotWidth}
                height={lane.height + 2 * MARK_SPACE}
              />
            )}
          </Plot>
        </Fragment>
      ))}
      <span aria-hidden="true" />
      <Axis ticks={ticks} step={step} width={plotWidth} />
      {active && shown && (
        <div
          className={styles.tooltip}
          style={{
            left: Math.min(Math.max(active.left, TOOLTIP_HALF), width - TOOLTIP_HALF),
            top: active.top,
          }}
          aria-hidden="true"
        >
          <strong className={styles.tooltipTitle}>{shown.name}</strong>
          {lines(shown, active.index).map((line) => (
            <span key={line}>{line}</span>
          ))}
        </div>
      )}
      <p id={hintId} className="sr-only">
        Pfeiltasten wählen einen Balken, Enter öffnet seine Mails in der Mailliste.
      </p>
    </div>
  );
}

/** A lane's name (a person links to its profile), its mails and peak, and its silence; for the
 *  first mentions the persons listed. */
function LaneLabel({
  lane,
  bucket,
  mentionPersons,
  listed,
}: {
  lane: Lane;
  bucket: TimelineBucket;
  mentionPersons: number | null;
  listed: number;
}) {
  const series = lane.series;
  if (!series) {
    const persons =
      mentionPersons !== null && mentionPersons > listed
        ? `${formatNumber(listed)} von ${personsText(mentionPersons)}`
        : personsText(listed);
    return (
      <div className={styles.label}>
        <span className={styles.name}>
          <span className={cx(styles.swatch, styles.dotSwatch)} aria-hidden="true" />
          {lane.name}
        </span>
        <span className={styles.meta}>{persons}</span>
      </div>
    );
  }
  let max = 0;
  for (const value of series.counts) if (value > max) max = value;
  const name = series.person ? (
    <Link to={personPath(series.person.person_id)} title={series.person.email}>
      {lane.name}
    </Link>
  ) : (
    <span className={cx(series.term !== null && "mono")} title={lane.name}>
      {lane.name}
    </span>
  );
  return (
    <div className={cx(styles.label, !lane.color && styles.totalLabel)}>
      <span className={styles.name}>
        <span
          className={cx(styles.swatch, !lane.color && styles.totalSwatch)}
          style={lane.color ? { background: lane.color } : undefined}
          aria-hidden="true"
        />
        {name}
      </span>
      <span className={styles.meta}>
        {mailsText(series.total)}
        {max > 0 && ` · Spitze ${formatNumber(max)}`}
      </span>
      {series.silent_from && (
        <span className={styles.silentNote}>
          verstummt seit {formatBucket(series.silent_from, bucket)}
        </span>
      )}
    </div>
  );
}

/** A lane's frame: a slider over the buckets with the grid, the highlighted bucket and the
 *  pointer and key handling; children draw what the lane shows. */
function Plot({
  name,
  width,
  height,
  count,
  ticks,
  column,
  cursor,
  valueText,
  hintId,
  onPoint,
  onFocusPlot,
  onCursor,
  onLeave,
  onOpen,
  children,
}: {
  name: string;
  width: number;
  height: number;
  count: number;
  ticks: Tick[];
  column: number | null;
  cursor: number;
  valueText: string;
  hintId: string;
  onPoint: (index: number, plot: Element) => void;
  onFocusPlot: (plot: Element) => void;
  onCursor: (index: number, plot: Element) => void;
  onLeave: () => void;
  onOpen: (index: number) => void;
  children: ReactNode;
}) {
  const step = width / count;
  const grid = ticks.map((tick) => `M${Math.round(tick.index * step) + 0.5} 0V${height}`).join("");

  function indexAt(event: MouseEvent<SVGSVGElement>): number {
    const rect = event.currentTarget.getBoundingClientRect();
    return bucketAt(event.clientX - rect.left, width, count);
  }

  function onKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      onOpen(cursor);
      return;
    }
    const next = { ArrowLeft: cursor - 1, ArrowRight: cursor + 1, Home: 0, End: count - 1 }[
      event.key
    ];
    if (next === undefined) return;
    event.preventDefault();
    onCursor(Math.min(Math.max(next, 0), count - 1), event.currentTarget);
  }

  return (
    <svg
      width={width}
      height={height}
      className={styles.plot}
      role="slider"
      tabIndex={0}
      aria-label={name}
      aria-describedby={hintId}
      aria-orientation="horizontal"
      aria-valuemin={0}
      aria-valuemax={count - 1}
      aria-valuenow={cursor}
      aria-valuetext={valueText}
      onPointerMove={(event) => onPoint(indexAt(event), event.currentTarget)}
      onPointerLeave={onLeave}
      onClick={(event) => onOpen(indexAt(event))}
      onFocus={(event) => onFocusPlot(event.currentTarget)}
      onBlur={onLeave}
      onKeyDown={onKeyDown}
    >
      {column !== null && (
        <rect
          className={styles.column}
          x={column * step}
          width={Math.max(step, 2)}
          y={0}
          height={height}
        />
      )}
      <path className={styles.grid} d={grid} />
      {children}
    </svg>
  );
}

/** A series' bars with its marks: high buckets amber with ▲ above, ▽ under the base line for
 *  low ones, and the silence as a hatched band to the end of the axis. */
function SeriesMarks({
  series,
  lane,
  starts,
  width,
}: {
  series: TimelineSeries;
  lane: Lane;
  starts: string[];
  width: number;
}) {
  const hatch = `${useId().replace(/[^\w-]/g, "")}-hatch`;
  const base = MARK_SPACE + lane.height;
  const shape = useMemo(
    () => laneShape(series.counts, series.outliers, width, base, lane.height),
    [series, width, base, lane.height],
  );
  const silent = series.silent_from ? bucketOf(starts, series.silent_from) : -1;
  const silentX = silent < 0 ? 0 : Math.round((silent / starts.length) * width);
  const silentWidth = width - silentX;
  return (
    <>
      {silent >= 0 && (
        <g data-mark="silent">
          <defs>
            <pattern
              id={hatch}
              width={6}
              height={6}
              patternUnits="userSpaceOnUse"
              patternTransform="rotate(45)"
            >
              <line x1={0} y1={0} x2={0} y2={6} className={styles.hatchLine} />
            </pattern>
          </defs>
          <rect
            x={silentX}
            y={0}
            width={silentWidth}
            height={base + MARK_SPACE}
            fill={`url(#${hatch})`}
          />
          <text
            className={styles.silentLabel}
            x={silentWidth >= 64 ? silentX + 4 : width - 4}
            y={Math.min(base - 4, MARK_SPACE + 12)}
            textAnchor={silentWidth >= 64 ? "start" : "end"}
          >
            verstummt
          </text>
        </g>
      )}
      <path
        className={styles.bars}
        style={lane.color ? { fill: lane.color } : undefined}
        d={shape.bars}
      />
      <path className={styles.high} d={shape.high} />
      <path className={styles.above} d={shape.above} data-mark="high" />
      <line className={styles.base} x1={0} x2={width} y1={base + 0.5} y2={base + 0.5} />
      <path className={styles.below} d={shape.below} data-mark="low" />
    </>
  );
}

/** A dot per bucket with first mentions, larger for more persons. */
function MentionDots({
  byBucket,
  step,
  width,
  height,
}: {
  byBucket: Map<number, FirstMention[]>;
  step: number;
  width: number;
  height: number;
}) {
  return (
    <>
      <line className={styles.base} x1={0} x2={width} y1={height / 2} y2={height / 2} />
      {[...byBucket].map(([index, first]) => (
        <circle
          key={index}
          className={styles.dot}
          cx={(index + 0.5) * step}
          cy={height / 2}
          r={Math.min(9, 2.5 + 1.6 * Math.sqrt(first.length))}
        />
      ))}
    </>
  );
}

function Axis({ ticks, step, width }: { ticks: Tick[]; step: number; width: number }) {
  return (
    <svg width={width} height={AXIS_HEIGHT} className={styles.axis} aria-hidden="true">
      {ticks.map((tick) => {
        const x = Math.round(tick.index * step) + 0.5;
        return (
          <g key={tick.index}>
            <line className={styles.tick} x1={x} x2={x} y1={0} y2={5} />
            <text className={styles.tickLabel} x={x + 3} y={16}>
              {tick.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

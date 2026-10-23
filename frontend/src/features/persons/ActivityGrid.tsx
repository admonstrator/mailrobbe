import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router";

import { withQuery } from "../../api/client";
import { useTimeline } from "../../api/queries";
import type { YearActivity } from "../../api/types";
import { Button } from "../../components/Button";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { timelinePath } from "../timeline/buckets";
import {
  ACTIVITY_LEVELS,
  activityTitle,
  activityWeeks,
  dayCounts,
  type ActivityDay,
} from "./activity";
import styles from "./ActivityGrid.module.css";

const MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
const WEEKDAYS = ["Mo", "", "Mi", "", "Fr", "", ""];
const LEVEL_CLASSES = [styles.l0, styles.l1, styles.l2, styles.l3, styles.l4];
// The newest years stand as buttons, the older ones in a menu.
const YEAR_BUTTONS = 7;

/** The newest year with mails, or the newest year at all. */
function latestYear(years: YearActivity[]): number | null {
  const active = years.filter(({ sent, received }) => sent + received > 0);
  return (active.at(-1) ?? years.at(-1))?.year ?? null;
}

/** "Aktivität" of the profile's overview (D336): one year of the person's mails by day, from the
 *  timeline's day buckets (D90), with a button per year; a day opens its mails in the list. The
 *  years' sent and received figures of the profile stand on the year buttons. */
export function ActivityGrid({ personId, years }: { personId: number; years: YearActivity[] }) {
  const [chosen, setChosen] = useState<number | null>(null);
  const year = chosen ?? latestYear(years);
  if (year === null) {
    return (
      <section className={styles.section} aria-labelledby="activity-title">
        <h2 id="activity-title" className={styles.title}>
          Aktivität
        </h2>
        <p className={styles.note}>Noch keine datierten Mails ausgewertet.</p>
      </section>
    );
  }
  return (
    <YearGrid
      key={year}
      personId={personId}
      year={year}
      years={years}
      onYear={(next) => setChosen(next)}
    />
  );
}

function YearGrid({
  personId,
  year,
  years,
  onYear,
}: {
  personId: number;
  year: number;
  years: YearActivity[];
  onYear: (year: number) => void;
}) {
  const navigate = useNavigate();
  const filters = { person: [personId], hide_duplicates: true };
  const timeline = useTimeline({
    ...filters,
    bucket: "day",
    date_from: `${String(year).padStart(4, "0")}-01-01`,
    date_to: `${String(year).padStart(4, "0")}-12-31`,
  });
  const counts = useMemo(() => dayCounts(timeline.data), [timeline.data]);
  const weeks = useMemo(() => activityWeeks(year, counts), [year, counts]);
  const days = useMemo(
    () => weeks.flat().filter((day): day is ActivityDay => day !== null),
    [weeks],
  );
  const total = days.reduce((sum, day) => sum + day.count, 0);
  const figures = years.find((each) => each.year === year);
  const newest = [...years].reverse().slice(0, YEAR_BUTTONS);
  const older = [...years].reverse().slice(YEAR_BUTTONS);
  const failed = timeline.isError || timeline.data?.timed_out || timeline.data?.total === null;

  // Month labels start in the week of their first day.
  const monthStarts = MONTHS.map((_, month) =>
    weeks.findIndex((week) =>
      week.some(
        (day) => day !== null && day.day.slice(5, 7) === String(month + 1).padStart(2, "0"),
      ),
    ),
  );

  const open = (day: ActivityDay) =>
    void navigate(withQuery("/mails", { ...filters, date_from: day.day, date_to: day.day }));

  return (
    <section className={styles.section} aria-labelledby="activity-title">
      <div className={styles.head}>
        <h2 id="activity-title" className={styles.title}>
          {timeline.isPending || failed
            ? `Aktivität ${year}`
            : `${formatNumber(total)} ${total === 1 ? "Mail" : "Mails"} in ${year}`}
        </h2>
        {figures && (
          <span className={styles.split}>
            {`${formatNumber(figures.sent)} gesendet · ${formatNumber(figures.received)} empfangen`}
          </span>
        )}
        <div role="group" aria-label="Jahr" className={styles.years}>
          {newest.map((each) => (
            <button
              key={each.year}
              type="button"
              aria-pressed={each.year === year}
              className={cx(styles.year, each.year === year && styles.yearActive)}
              title={`${formatNumber(each.sent)} gesendet, ${formatNumber(each.received)} empfangen`}
              onClick={() => each.year !== year && onYear(each.year)}
            >
              {each.year}
            </button>
          ))}
          {older.length > 0 && (
            <select
              aria-label="Älteres Jahr"
              className={cx(
                styles.older,
                older.some((each) => each.year === year) && styles.yearActive,
              )}
              value={older.some((each) => each.year === year) ? year : ""}
              onChange={(event) => event.target.value && onYear(Number(event.target.value))}
            >
              <option value="">älter</option>
              {older.map((each) => (
                <option
                  key={each.year}
                  value={each.year}
                >{`${each.year}: ${formatNumber(each.sent)} gesendet, ${formatNumber(each.received)} empfangen`}</option>
              ))}
            </select>
          )}
        </div>
      </div>
      <div className={styles.frame}>
        <div className={styles.chart} aria-busy={timeline.isPending}>
          <div className={styles.weekdays} aria-hidden="true">
            {WEEKDAYS.map((label, index) => (
              <span key={index}>{label}</span>
            ))}
          </div>
          <div className={styles.body}>
            <div
              className={styles.months}
              style={{ gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))` }}
              aria-hidden="true"
            >
              {MONTHS.map((label, month) =>
                monthStarts[month] < 0 ? null : (
                  <span key={label} style={{ gridColumn: `${monthStarts[month] + 1} / span 4` }}>
                    {label}
                  </span>
                ),
              )}
            </div>
            <Days
              weeks={weeks.length}
              days={days}
              year={year}
              onOpen={open}
              offset={offsetOf(weeks)}
            />
          </div>
        </div>
        <div className={styles.foot}>
          <Link to={timelinePath({ person: [personId] })}>In der Zeitachse öffnen</Link>
          {failed && (
            <span className={styles.error} role="alert">
              {timeline.isError
                ? "Die Tage konnten nicht geladen werden."
                : "Die Zählung hat zu lange gedauert."}{" "}
              <Button variant="link" size="xs" onClick={() => void timeline.refetch()}>
                Erneut versuchen
              </Button>
            </span>
          )}
          <span className={styles.legend} aria-hidden="true">
            weniger
            {ACTIVITY_LEVELS.map((level) => (
              <span key={level} className={cx(styles.cell, LEVEL_CLASSES[level])} />
            ))}
            mehr
          </span>
        </div>
      </div>
    </section>
  );
}

/** The empty places before January 1st in the first week. */
function offsetOf(weeks: (ActivityDay | null)[][]): number {
  return weeks[0]?.findIndex((day) => day !== null) ?? 0;
}

/** The days as one group of buttons with one tab stop: the arrows move by a day (up, down) and
 *  a week (left, right), Enter opens the day's mails. */
function Days({
  weeks,
  days,
  year,
  offset,
  onOpen,
}: {
  weeks: number;
  days: ActivityDay[];
  year: number;
  offset: number;
  onOpen: (day: ActivityDay) => void;
}) {
  const [focus, setFocus] = useState(0);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const step = { ArrowUp: -1, ArrowDown: 1, ArrowLeft: -7, ArrowRight: 7 }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    const next = Math.min(days.length - 1, Math.max(0, index + step));
    setFocus(next);
    buttons.current[next]?.focus();
  }

  return (
    <div
      role="group"
      aria-label={`Mails pro Tag in ${year}`}
      className={styles.days}
      style={{ gridTemplateColumns: `repeat(${weeks}, minmax(0, 1fr))` }}
    >
      {Array.from({ length: offset }, (_, index) => (
        <span key={`empty-${index}`} className={styles.blank} />
      ))}
      {days.map((day, index) => {
        const title = activityTitle(day);
        return (
          <button
            key={day.day}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            tabIndex={index === focus ? 0 : -1}
            className={cx(styles.cell, styles.day, LEVEL_CLASSES[day.level])}
            title={title}
            aria-label={title}
            data-level={day.level}
            onClick={() => {
              setFocus(index);
              onOpen(day);
            }}
            onKeyDown={(event) => onKeyDown(event, index)}
          />
        );
      })}
    </div>
  );
}

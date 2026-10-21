import { memo, useId } from "react";
import { Link } from "react-router";

import { useTopicClusters } from "../../api/queries";
import type { ThemeInfo, TopicCluster, TopicMonth } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { formatDate, formatNumber } from "../../lib/format";
import { DEFAULT_LIST_STATE, withFilters } from "../mails/listState";
import { formatBucket } from "../timeline/buckets";
import styles from "./ClustersView.module.css";
import { formatShare, mailsText, themesOf } from "./labels";
import { TermChip, TermList } from "./TermChip";
import { mailsHref, termMailsHref, termTimelineHref } from "./urlState";

// Labels of a cluster compared in the timeline: those of its search (D145).
const TIMELINE_TERMS = 5;

/** A month's place on an axis of months: months since year 0. */
function monthIndex(day: string): number {
  const [year, month] = day.split("-").map(Number);
  return year * 12 + month - 1;
}

/** The first day of the month at index. */
function monthDay(index: number): string {
  const year = Math.floor(index / 12);
  return `${String(year).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}-01`;
}

/** The months every cluster's bars share: from the earliest to the latest month of any. */
interface Axis {
  first: number;
  count: number;
}

function sharedAxis(clusters: TopicCluster[]): Axis | null {
  const months = clusters.flatMap((cluster) => cluster.months.map((m) => monthIndex(m.month)));
  if (months.length === 0) return null;
  const first = Math.min(...months);
  return { first, count: Math.max(...months) - first + 1 };
}

/** Themen (D145): groups of words that often stand together across the archive, most mails
 *  first, each with its words, mails, dates and months. */
export function ClustersView({ themes }: { themes: ThemeInfo[] | undefined }) {
  const clusters = useTopicClusters();

  if (clusters.isPending) {
    return (
      <Card className={styles.message}>
        <div className={styles.loading}>
          <Spinner label="Themen werden geladen" />
        </div>
      </Card>
    );
  }
  if (clusters.isError) {
    return (
      <Card className={styles.message}>
        <ErrorState
          title="Die Themen konnten nicht geladen werden."
          actions={<Button onClick={() => void clusters.refetch()}>Erneut versuchen</Button>}
        >
          Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
        </ErrorState>
      </Card>
    );
  }
  const items = clusters.data.clusters;
  if (items.length === 0) {
    return (
      <Card className={styles.message}>
        <EmptyState title="Keine Themen gefunden">
          Ein Thema entsteht aus mindestens vier Wörtern, die jeweils in mindestens 10 Mails stehen
          und oft in denselben Mails zusammen vorkommen.
        </EmptyState>
      </Card>
    );
  }
  const axis = sharedAxis(items);
  return (
    <div className={styles.view}>
      <p className={styles.summary}>
        {items.length === 1 ? "1 Thema" : `${formatNumber(items.length)} Themen`}, die meisten Mails
        zuerst.
        {axis &&
          ` Die Balken zeigen die Mails pro Monat, alle auf derselben Achse von ${formatBucket(monthDay(axis.first), "month")} bis ${formatBucket(monthDay(axis.first + axis.count - 1), "month")}.`}
      </p>
      <ol className={styles.grid} aria-label="Themen">
        {items.map((cluster) => (
          <ClusterCard
            key={cluster.id}
            cluster={cluster}
            axis={axis}
            archive={clusters.data.state.mails}
            themes={themes}
          />
        ))}
      </ol>
    </div>
  );
}

function ClusterCard({
  cluster,
  axis,
  archive,
  themes,
}: {
  cluster: TopicCluster;
  axis: Axis | null;
  archive: number;
  themes: ThemeInfo[] | undefined;
}) {
  const titleId = useId();
  const labels = cluster.terms.map((term) => term.label);
  const dates =
    cluster.first_date && cluster.last_date
      ? `${formatDate(cluster.first_date)} bis ${formatDate(cluster.last_date)}`
      : null;
  return (
    <li className={styles.cluster} aria-labelledby={titleId}>
      <h3 id={titleId} className={styles.label}>
        {cluster.label}
      </h3>
      <p className={styles.figures}>
        {mailsText(cluster.mails)}
        {dates && ` · ${dates}`}
      </p>
      {axis && <Sparkline months={cluster.months} axis={axis} />}
      <TermList label={`Wörter von ${cluster.label}`}>
        {cluster.terms.map((term) => (
          <TermChip
            key={term.term}
            label={term.label}
            mails={term.mails}
            href={termMailsHref(DEFAULT_LIST_STATE, term.label)}
            figures={`${mailsText(term.mails)} im Archiv (${formatShare(archive > 0 ? term.mails / archive : 0)})`}
            themes={themesOf(term.themes, themes)}
          />
        ))}
      </TermList>
      <div className={styles.links}>
        <Link
          to={mailsHref(
            withFilters(DEFAULT_LIST_STATE, { q: cluster.query, hide_duplicates: true }),
          )}
          title={`Suche: ${cluster.query}`}
        >
          Mails lesen
        </Link>
        <Link to={termTimelineHref(DEFAULT_LIST_STATE, labels.slice(0, TIMELINE_TERMS))}>
          In der Zeitachse vergleichen
        </Link>
      </div>
    </li>
  );
}

// The sparkline's height in pixels.
const HEIGHT = 36;

/** The cluster's mails per month as bars on the shared axis: one path, scaled to the width. */
const Sparkline = memo(function Sparkline({ months, axis }: { months: TopicMonth[]; axis: Axis }) {
  const max = Math.max(1, ...months.map((m) => m.mails));
  const peak = months.reduce<TopicMonth | null>(
    (best, m) => (best === null || m.mails > best.mails ? m : best),
    null,
  );
  const gap = axis.count <= 60 ? 0.15 : 0;
  const bars = months
    .map((m) => {
      const x = monthIndex(m.month) - axis.first + gap;
      const height = Math.max(1, (m.mails / max) * HEIGHT);
      return `M${x} ${HEIGHT}V${HEIGHT - height}h${1 - 2 * gap}V${HEIGHT}Z`;
    })
    .join("");
  const label = peak
    ? `Mails pro Monat; die meisten im ${formatBucket(peak.month, "month")}: ${formatNumber(peak.mails)}`
    : "Mails pro Monat";
  return (
    <svg
      className={styles.sparkline}
      viewBox={`0 0 ${axis.count} ${HEIGHT}`}
      preserveAspectRatio="none"
      width="100%"
      height={HEIGHT}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      <line className={styles.baseline} x1={0} x2={axis.count} y1={HEIGHT} y2={HEIGHT} />
      <path className={styles.bars} d={bars} />
    </svg>
  );
});

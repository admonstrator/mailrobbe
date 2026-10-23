import type { UseQueryResult } from "@tanstack/react-query";
import { Link } from "react-router";

import { useTimeline } from "../../api/queries";
import type { MailFilters, MailSummary } from "../../api/types";
import { formatDay, formatIsoDay, formatNumber, formatPercent } from "../../lib/format";
import { bucketRange, formatBucket, timelinePath } from "../timeline/buckets";
import styles from "./SummaryLine.module.css";

/** Why "Signatur stimmig" does not count as valid (D100). */
const CONSISTENT_HINT =
  "Gültig: Der Schlüssel steht heute im DNS, wurde dort beobachtet oder ist dokumentiert. Signatur stimmig: nur ein aus Signaturen rekonstruierter Schlüssel bestätigt sie; an die Domain bindet ihn das nicht.";

const SPARK_HEIGHT = 22;
const SPARK_WIDTH = 180;

/** The figures of the filtered list as one quiet line (D335): period, persons and domains, the
 *  DKIM shares, and the mails per month as small bars with the link to the timeline. A click on
 *  a bar narrows the list to its days (onPick). Loaded apart from the page (D19). */
export function SummaryLine({
  summary,
  filters,
  onPick,
}: {
  summary: UseQueryResult<MailSummary>;
  filters: MailFilters;
  onPick: (range: { date_from: string; date_to: string }) => void;
}) {
  return (
    <div className={styles.line} role="group" aria-label="Kennzahlen">
      <Figures summary={summary} />
      <Sparkline filters={filters} onPick={onPick} />
      <Link to={timelinePath(filters)} className={styles.timeline}>
        Zeitachse
      </Link>
    </div>
  );
}

function Figures({ summary }: { summary: UseQueryResult<MailSummary> }) {
  if (!summary.data) {
    return summary.isError ? (
      <span>Zahlen nicht verfügbar</span>
    ) : (
      <span className={styles.skeleton} aria-busy="true" />
    );
  }
  const { dkim, persons, domains, date_min, date_max } = summary.data;
  const signed = dkim ? dkim.pass + dkim.consistent + dkim.fail + dkim.no_key + dkim.temp_error : 0;
  return (
    <>
      {date_min && date_max && (
        <span>
          {formatDay(formatIsoDay(date_min))} bis {formatDay(formatIsoDay(date_max))}
        </span>
      )}
      {persons !== null && (
        <span>
          {formatNumber(persons)} {persons === 1 ? "Person" : "Personen"}
          {domains !== null &&
            ` aus ${formatNumber(domains)} ${domains === 1 ? "Domain" : "Domains"}`}
        </span>
      )}
      {dkim && signed > 0 && (
        <span
          title={
            dkim.consistent > 0
              ? `von ${formatNumber(signed)} signierten, ${formatNumber(dkim.consistent)} stimmig. ${CONSISTENT_HINT}`
              : `von ${formatNumber(signed)} signierten Mails`
          }
        >
          <strong className={styles.pass}>{formatPercent(dkim.pass / signed)}</strong> DKIM gültig
        </span>
      )}
      {dkim && dkim.no_key > 0 && (
        <span title="Selector im DNS gelöscht">
          <strong className={styles.noKey}>{formatNumber(dkim.no_key)}</strong> Schlüssel nicht
          abrufbar
        </span>
      )}
    </>
  );
}

/** The mails per bucket as small bars; a bar standing out of the usual is drawn darker. */
function Sparkline({
  filters,
  onPick,
}: {
  filters: MailFilters;
  onPick: (range: { date_from: string; date_to: string }) => void;
}) {
  const timeline = useTimeline({ ...filters, bucket: "month" });
  const data = timeline.data;
  const series = data?.total;
  if (!data || !series || series.total === 0 || data.starts.length === 0) {
    return <span className={styles.spark} aria-hidden="true" />;
  }
  const max = Math.max(...series.counts, 1);
  const outliers = new Set(series.outliers.map((outlier) => outlier.index));
  // Each bar 3 units and a gap of 1, squeezed into at most SPARK_WIDTH pixels.
  const units = data.starts.length * 4;
  return (
    <svg
      className={styles.spark}
      width={Math.min(SPARK_WIDTH, units)}
      height={SPARK_HEIGHT}
      viewBox={`0 0 ${units} ${SPARK_HEIGHT}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Mails pro Monat"
    >
      {series.counts.map((count, index) => {
        const height = count === 0 ? 0 : Math.max(2, (count / max) * SPARK_HEIGHT);
        const start = data.starts[index];
        return (
          <rect
            key={start}
            x={index * 4}
            y={SPARK_HEIGHT - height}
            width={3}
            height={height}
            className={outliers.has(index) ? styles.outlier : styles.bar}
            onClick={() => onPick(bucketRange(start, data.bucket, filters))}
          >
            <title>{`${formatBucket(start, data.bucket)}: ${formatNumber(count)} ${count === 1 ? "Mail" : "Mails"}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}

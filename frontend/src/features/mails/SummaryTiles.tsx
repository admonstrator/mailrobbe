import type { UseQueryResult } from "@tanstack/react-query";

import type { MailSummary } from "../../api/types";
import { cx } from "../../lib/cx";
import { formatIsoDay, formatNumber, formatPercent } from "../../lib/format";
import styles from "./SummaryTiles.module.css";

const UNKNOWN = "–";

/** "1.207", "mehr als 10.000" for a lower bound, "–" when unknown; never 0 for unknown. */
export function formatTotal(summary: MailSummary): string {
  if (summary.total === null) return UNKNOWN;
  return summary.exact ? formatNumber(summary.total) : `mehr als ${formatNumber(summary.total)}`;
}

interface Tile {
  label: string;
  value: string;
  sub: string;
  tone?: "pass" | "noKey";
}

function tilesOf(summary: MailSummary): Tile[] {
  const { dkim } = summary;
  const signed = dkim ? dkim.pass + dkim.fail + dkim.no_key + dkim.temp_error : 0;
  return [
    {
      label: "Mails im Filter",
      value: formatTotal(summary),
      sub:
        summary.date_min && summary.date_max
          ? `${formatIsoDay(summary.date_min)} bis ${formatIsoDay(summary.date_max)}`
          : UNKNOWN,
    },
    {
      label: "DKIM gültig",
      value: dkim && signed > 0 ? formatPercent(dkim.pass / signed) : UNKNOWN,
      sub: !dkim
        ? UNKNOWN
        : signed > 0
          ? `von ${formatNumber(signed)} signierten Mails`
          : "keine signierten Mails",
      tone: "pass",
    },
    {
      label: "Schlüssel nicht abrufbar",
      value: dkim ? formatNumber(dkim.no_key) : UNKNOWN,
      sub: "Selector im DNS gelöscht",
      tone: "noKey",
    },
    {
      label: "Beteiligte Personen",
      value: summary.persons === null ? UNKNOWN : formatNumber(summary.persons),
      sub: summary.domains === null ? UNKNOWN : `${formatNumber(summary.domains)} Domains`,
    },
  ];
}

const LABELS = [
  "Mails im Filter",
  "DKIM gültig",
  "Schlüssel nicht abrufbar",
  "Beteiligte Personen",
];

/** The four figures of the filtered list, loaded apart from the page (D19). */
export function SummaryTiles({ summary }: { summary: UseQueryResult<MailSummary> }) {
  if (!summary.data) {
    return (
      <div className={styles.tiles} aria-busy={summary.isPending}>
        {LABELS.map((label) => (
          <div key={label} className={styles.tile}>
            <span className={styles.label}>{label}</span>
            {summary.isError ? (
              <>
                <span className={styles.value}>{UNKNOWN}</span>
                <span className={styles.sub}>nicht verfügbar</span>
              </>
            ) : (
              <>
                <span className={cx(styles.skeleton, styles.skeletonValue)} />
                <span className={cx(styles.skeleton, styles.skeletonSub)} />
              </>
            )}
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className={styles.tiles}>
      {tilesOf(summary.data).map((tile) => (
        <div key={tile.label} className={styles.tile}>
          <span className={styles.label}>{tile.label}</span>
          <span
            className={cx(styles.value, tile.value !== UNKNOWN && tile.tone && styles[tile.tone])}
          >
            {tile.value}
          </span>
          <span className={styles.sub}>{tile.sub}</span>
        </div>
      ))}
    </div>
  );
}

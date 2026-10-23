import type { DkimKey, ImportSummary } from "../../api/types";
import { DkimDot } from "../../components/DkimDot";
import { DKIM_KEYS, DKIM_REASON_TEXTS } from "../../lib/dkim";
import { formatDateTime, formatNumber } from "../../lib/format";
import styles from "./DkimResult.module.css";
import { DKIM_RESULT_LABELS } from "./labels";
import { HelpTip } from "./PageHead";

const RECHECK_HINT =
  "„DKIM für ‚Schlüssel fehlt‘ neu prüfen“ im Menü … prüft Mails ohne Ergebnis, mit „Schlüssel fehlt“ oder mit DNS-Fehler erneut.";

/** Always in the legend; DNS errors and unchecked mails only when there are any. */
const MAIN_KEYS: readonly DkimKey[] = ["pass", "fail", "no_key", "unsigned"];
const TOP_REASONS = 3;

/** The DKIM distribution of the archive with the most frequent reasons of failed checks (D48). */
export function DkimResult({ summary }: { summary: ImportSummary }) {
  const counts = summary.dkim;
  const keys = DKIM_KEYS.filter((key) => MAIN_KEYS.includes(key) || counts[key] > 0);
  const total = keys.reduce((sum, key) => sum + counts[key], 0);
  const share = (key: DkimKey) => (total > 0 ? counts[key] / total : 0);
  const reasons = summary.fail_reasons.slice(0, TOP_REASONS);

  return (
    <section className={styles.card} aria-labelledby="import-dkim-title">
      <div className={styles.head}>
        <h2 id="import-dkim-title" className={styles.title}>
          DKIM-Ergebnis bisher
        </h2>
        <HelpTip text={RECHECK_HINT} />
      </div>
      {total === 0 ? (
        <p className={styles.empty}>Noch keine Mail geprüft.</p>
      ) : (
        <>
          <div
            className={styles.bar}
            role="img"
            aria-label={`Anteile: ${keys
              .map((key) => `${Math.round(share(key) * 100)} % ${DKIM_RESULT_LABELS[key]}`)
              .join(", ")}`}
          >
            {keys.map(
              (key) =>
                counts[key] > 0 && (
                  <span
                    key={key}
                    className={styles[key]}
                    style={{ width: `${share(key) * 100}%` }}
                  />
                ),
            )}
          </div>
          <ul className={styles.legend}>
            {keys.map((key) => (
              <li key={key} className={styles.entry}>
                <DkimDot status={key} decorative />
                <span>{DKIM_RESULT_LABELS[key]}</span>
                <strong className={styles.count}>{formatNumber(counts[key])}</strong>
              </li>
            ))}
          </ul>
          {reasons.length > 0 && (
            <p className={styles.reasons}>
              {`Häufigste Ungültig-Gründe: ${reasons
                .map(({ reason, mails }) => `${DKIM_REASON_TEXTS[reason]} (${formatNumber(mails)})`)
                .join(", ")}.`}
            </p>
          )}
        </>
      )}
      {summary.updated_at && (
        <p className={styles.stand} title="Diese Zahlen sind höchstens 5 Minuten alt.">
          {`Stand ${formatDateTime(summary.updated_at)}`}
        </p>
      )}
    </section>
  );
}

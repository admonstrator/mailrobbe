import type { YearActivity } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import styles from "./YearChart.module.css";

/** Sent and received mails per UTC year as grouped bars. Each year is a button: a click
 *  chooses it for the mail list below, a second click clears it. */
export function YearChart({
  years,
  selected,
  onSelect,
}: {
  years: YearActivity[];
  selected: number | null;
  onSelect: (year: number | null) => void;
}) {
  const max = Math.max(1, ...years.flatMap((year) => [year.sent, year.received]));
  const height = (value: number) => ({
    height: `${(value / max) * 100}%`,
    minHeight: value > 0 ? 2 : 0,
  });

  return (
    <Card className={styles.card}>
      <div className={styles.head}>
        <CardTitle>Aktivität pro Jahr</CardTitle>
        <span className={styles.hint}>gesendet · empfangen</span>
        <span className={styles.legend} aria-hidden="true">
          <span>
            <span className={cx(styles.swatch, styles.sent)} />
            gesendet
          </span>
          <span>
            <span className={cx(styles.swatch, styles.received)} />
            empfangen
          </span>
        </span>
      </div>
      {years.length === 0 ? (
        <p className={styles.hint}>Noch keine datierten Mails ausgewertet.</p>
      ) : (
        <div
          role="group"
          aria-label="Mails pro Jahr"
          className={cx(styles.chart, selected !== null && styles.choosing)}
          style={{ gridTemplateColumns: `repeat(${years.length}, minmax(0, 1fr))` }}
        >
          {years.map(({ year, sent, received }) => (
            <button
              key={year}
              type="button"
              className={cx(styles.year, year === selected && styles.selected)}
              aria-pressed={year === selected}
              aria-label={`${year}: ${formatNumber(sent)} gesendet, ${formatNumber(received)} empfangen`}
              title={`${formatNumber(sent)} gesendet, ${formatNumber(received)} empfangen`}
              onClick={() => onSelect(year === selected ? null : year)}
            >
              <span className={styles.bars}>
                <span className={styles.sent} style={height(sent)} />
                <span className={styles.received} style={height(received)} />
              </span>
              <span className={styles.label}>{year}</span>
            </button>
          ))}
        </div>
      )}
      {years.length > 0 && (
        <p className={styles.hint}>
          {selected === null
            ? "Klick auf ein Jahr filtert die Liste unten."
            : `Die Liste unten zeigt ${selected}; ein zweiter Klick auf das Jahr hebt die Auswahl auf.`}
        </p>
      )}
    </Card>
  );
}

import { Link } from "react-router";

import { usePersonSignals } from "../../api/queries";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { mailsText } from "../entities/labels";
import {
  percentText,
  personSignalHref,
  shareText,
  signalName,
  silentMonth,
} from "../signals/labels";
import { timelinePath } from "../timeline/buckets";
import styles from "./PersonSignalsCard.module.css";

/** "Signale gesendeter Mails" (D137): how many of the person's sent mails carry each signal,
 *  their share beside the archive's, and whether and since when the person fell silent (D134).
 *  Counted on request, so a merge counts at once. Hidden when there is nothing to say. */
export function PersonSignalsCard({ personId }: { personId: number }) {
  const signals = usePersonSignals(personId);

  if (signals.isPending || signals.isError) {
    return (
      <Card aria-labelledby="person-signals-title">
        <CardTitle id="person-signals-title">Signale gesendeter Mails</CardTitle>
        {signals.isPending ? (
          <Spinner label="Signale werden geladen" />
        ) : (
          <div className={styles.error} role="alert">
            <span>Die Signale konnten nicht geladen werden.</span>
            <Button variant="link" size="xs" onClick={() => void signals.refetch()}>
              Erneut versuchen
            </Button>
          </div>
        )}
      </Card>
    );
  }
  const { sent, signals: counts, silent_since: since, silent_mails: before } = signals.data;
  if (counts.length === 0 && since === null) return null;

  return (
    <Card aria-labelledby="person-signals-title">
      <div className={styles.head}>
        <CardTitle id="person-signals-title">Signale gesendeter Mails</CardTitle>
        <span className={styles.base}>{`${mailsText(sent)} gesendet, ohne Duplikate`}</span>
      </div>
      {since !== null && (
        <p className={styles.silent}>
          {`Verstummt seit ${silentMonth(since)}, davor ${formatNumber(before ?? 0)} ${
            before === 1 ? "Mail" : "Mails"
          } in sechs Monaten. `}
          <Link to={timelinePath({ person: [personId] })}>Zeitachse</Link>
        </p>
      )}
      {counts.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Signal</th>
              <th scope="col" className={styles.number}>
                Mails
              </th>
              <th scope="col" className={styles.number}>
                Anteil
              </th>
              <th scope="col" className={styles.number}>
                Im Archiv
              </th>
            </tr>
          </thead>
          <tbody>
            {counts.map((count) => {
              const name = signalName(count.key, count.theme);
              return (
                <tr key={count.key}>
                  <th scope="row" className={styles.name}>
                    {name}
                  </th>
                  <td className={styles.number}>
                    <Link
                      to={personSignalHref(personId, count.key)}
                      aria-label={`${mailsText(count.mails)} mit ${name}`}
                    >
                      {formatNumber(count.mails)}
                    </Link>
                  </td>
                  <td className={styles.number}>{shareText(count.mails, sent) ?? "–"}</td>
                  <td className={styles.number}>
                    {count.archive_share === null ? "–" : percentText(count.archive_share)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className={styles.note}>
        Anteil: an den gesendeten Mails der Person; im Archiv: an allen Mails beim letzten Import.
        Signale bewerten nichts.
      </p>
    </Card>
  );
}

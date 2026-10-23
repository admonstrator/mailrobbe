import { Link } from "react-router";

import { usePersonSignals } from "../../api/queries";
import type { PersonSignals } from "../../api/types";
import { Button } from "../../components/Button";
import { HelpMark } from "../../components/HelpMark";
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

const SHARE_HELP =
  "Anteil: an den gesendeten Mails der Person; im Archiv: an allen Mails beim letzten Import. Signale bewerten nichts.";

/** "Verstummt seit März 2025, davor 12 Mails in sechs Monaten. Zeitachse" (D134). */
function Silence({ personId, data }: { personId: number; data: PersonSignals }) {
  const { silent_since: since, silent_mails: before } = data;
  if (since === null) return null;
  return (
    <p className={styles.silent}>
      {`Verstummt seit ${silentMonth(since)}, davor ${formatNumber(before ?? 0)} ${
        before === 1 ? "Mail" : "Mails"
      } in sechs Monaten. `}
      <Link to={timelinePath({ person: [personId] })}>Zeitachse</Link>
    </p>
  );
}

/** "Signale gesendeter Mails" (D137), the profile's tab Signale: how many of the person's sent
 *  mails carry each signal, their share beside the archive's, and whether and since when the
 *  person fell silent (D134). Counted on request, so a merge counts at once. Hidden when there
 *  is nothing to say. */
export function PersonSignalsCard({ personId }: { personId: number }) {
  const signals = usePersonSignals(personId);

  if (signals.isPending || signals.isError) {
    return (
      <section className={styles.section} aria-labelledby="person-signals-title">
        <h2 id="person-signals-title" className={styles.title}>
          Signale gesendeter Mails
        </h2>
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
      </section>
    );
  }
  const { sent, signals: counts, silent_since: since } = signals.data;
  if (counts.length === 0 && since === null) return null;

  return (
    <section className={styles.section} aria-labelledby="person-signals-title">
      <div className={styles.head}>
        <h2 id="person-signals-title" className={styles.title}>
          Signale gesendeter Mails
        </h2>
        <HelpMark text={SHARE_HELP} />
        <span className={styles.base}>{`${mailsText(sent)} gesendet, ohne Duplikate`}</span>
      </div>
      <Silence personId={personId} data={signals.data} />
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
    </section>
  );
}

/** "Signale" of the profile's overview: each signal of the sent mails as a chip leading to its
 *  mails, the silence below; "Details" opens the tab. Nothing while loading or without any. */
export function PersonSignalChips({ personId, onMore }: { personId: number; onMore: () => void }) {
  const signals = usePersonSignals(personId);
  if (!signals.data) return null;
  const { signals: counts, silent_since: since } = signals.data;
  if (counts.length === 0 && since === null) return null;
  return (
    <section className={styles.section} aria-labelledby="person-signal-chips-title">
      <div className={styles.head}>
        <h2 id="person-signal-chips-title" className={styles.title}>
          Signale
        </h2>
        <Button variant="link" size="sm" className={styles.more} onClick={onMore}>
          Details
        </Button>
      </div>
      {counts.length > 0 && (
        <ul className={styles.chips} aria-label="Signale der gesendeten Mails">
          {counts.map((count) => {
            const name = signalName(count.key, count.theme);
            return (
              <li key={count.key}>
                <Link
                  to={personSignalHref(personId, count.key)}
                  className={styles.chip}
                  aria-label={`${mailsText(count.mails)} mit ${name}`}
                >
                  {name} <span className={styles.chipCount}>{formatNumber(count.mails)}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <Silence personId={personId} data={signals.data} />
    </section>
  );
}

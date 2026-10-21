import { Fragment, type ReactNode } from "react";
import { Link } from "react-router";

import { useMailSignals } from "../../api/queries";
import type { PersonRef, SignalReason } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { entityMailsHref } from "../entities/urlState";
import { formatLocalTime, signalMailsHref, signalName } from "../signals/labels";
import styles from "./SignalsCard.module.css";

/** "Warum fällt diese Mail auf" (D137): each signal of the mail with what makes it hold, and a
 *  link to the mails with the same signal. It rates nothing, and says so. */
export function SignalsCard({ mailId }: { mailId: number }) {
  const signals = useMailSignals(mailId);

  return (
    <Card variant="side" aria-labelledby="mail-signals-title">
      <CardTitle id="mail-signals-title" variant="caps">
        Warum fällt diese Mail auf
      </CardTitle>
      {signals.isPending ? (
        <Spinner label="Signale werden geladen" />
      ) : signals.isError ? (
        <div className={styles.error} role="alert">
          <span>Konnte nicht geladen werden.</span>
          <Button variant="link" size="xs" onClick={() => void signals.refetch()}>
            Erneut versuchen
          </Button>
        </div>
      ) : signals.data.computed_at === null ? (
        <p className={styles.empty}>Signale werden beim nächsten Import berechnet.</p>
      ) : signals.data.signals.length === 0 ? (
        <p className={styles.empty}>Keine Signale.</p>
      ) : (
        <>
          <ul className={styles.list}>
            {signals.data.signals.map((reason) => (
              <Reason key={reason.key} reason={reason} timezone={signals.data.timezone} />
            ))}
          </ul>
          <p className={styles.note}>
            Signale sind Hinweise nach <Link to="/auffaelligkeiten">einfachen Regeln</Link>; sie
            bewerten nichts, und vieles hat harmlose Gründe.
          </p>
        </>
      )}
    </Card>
  );
}

function Reason({ reason, timezone }: { reason: SignalReason; timezone: string }) {
  const name = signalName(reason.key, reason.theme);
  return (
    <li className={styles.item}>
      <span className={styles.line}>
        <span className={styles.name}>{name}</span>
        <Link
          to={signalMailsHref(reason.key)}
          className={styles.mails}
          aria-label={`Mails mit ${name}`}
          title="Alle Mails mit diesem Signal"
        >
          Mails
        </Link>
      </span>
      <Details reason={reason} timezone={timezone} />
    </li>
  );
}

/** What makes the signal hold, in the reason's own terms; nothing where the name says it all. */
function Details({ reason, timezone }: { reason: SignalReason; timezone: string }) {
  const parts: ReactNode[] = [];
  if (reason.local_time) {
    parts.push(
      <span key="time">
        {formatLocalTime(reason.local_time)} ({timezone})
      </span>,
    );
  }
  if (reason.recipients !== null) {
    parts.push(<span key="recipients">{`${formatNumber(reason.recipients)} Empfänger`}</span>);
  }
  if (reason.forward_prefix) {
    parts.push(<span key="prefix">{`Betreff mit „${reason.forward_prefix}:“`}</span>);
  }
  if (reason.forwarded_mail !== null) {
    parts.push(
      <span key="attached">
        {reason.forwarded_mail
          ? `Mail im Anhang: ${reason.forwarded_mail}`
          : "Mail im Anhang (ohne Dateinamen)"}
      </span>,
    );
  }
  if (reason.persons.length > 0) {
    parts.push(
      <span key="persons" className={styles.persons}>
        {PERSON_PREFIX[reason.key] ?? ""}
        <Persons persons={reason.persons} />
      </span>,
    );
  }
  if (reason.terms.length > 0) {
    parts.push(
      <span key="terms" className={styles.persons}>
        {reason.terms.map((term, index) => (
          <Fragment key={term.id}>
            {index > 0 && ", "}
            <Link to={entityMailsHref([term.id])} title="Alle Mails, die es erwähnen">
              {term.label}
            </Link>
          </Fragment>
        ))}
      </span>,
    );
  }
  if (parts.length === 0) return null;
  return <span className={styles.details}>{parts}</span>;
}

/** Words before the persons where the name alone leaves open what they are. */
const PERSON_PREFIX: Partial<Record<string, string>> = {
  bcc: "in Bcc: ",
  forward_out: "an ",
};

/** The participants concerned, each with the address the signal is about. */
function Persons({ persons }: { persons: PersonRef[] }) {
  return persons.map((person, index) => (
    <Fragment key={`${person.person_id}-${person.email}`}>
      {index > 0 && ", "}
      <PersonLink person={person} />
      {(person.label?.name || person.name) && (
        <span className={styles.address}> ({person.email})</span>
      )}
    </Fragment>
  ));
}

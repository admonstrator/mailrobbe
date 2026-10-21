import { Link } from "react-router";

import { usePersonEvents } from "../../api/queries";
import { EVENT_KEYS, type PersonEvent } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { PersonLink } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { personName } from "../../lib/person";
import { answerText, eventStart } from "../mail/EventCard";
import { EVENT_LABELS } from "../mails/chips";
import { DEFAULT_LIST_STATE, listSearch, withFilters } from "../mails/listState";
import styles from "./PersonEventsCard.module.css";

/** The calendar mails of a person in the mail list (D155). */
export function personEventsHref(personId: number): string {
  const state = withFilters(DEFAULT_LIST_STATE, { event: [...EVENT_KEYS], person: [personId] });
  return `/mails?${listSearch(state)}`;
}

const termine = (count: number) => (count === 1 ? "1 Termin" : `${formatNumber(count)} Termine`);

/** "Termine" (D155): the events the person organised or was invited to, one per UID, newest
 *  first, each with its date, its summary linking to the mail, and who organised it or the
 *  person's answer. Hidden while loading and when the person has none. */
export function PersonEventsCard({ personId }: { personId: number }) {
  const events = usePersonEvents(personId);

  if (events.isPending) return null;
  if (events.isError) {
    return (
      <Card aria-labelledby="person-events-title">
        <CardTitle id="person-events-title">Termine</CardTitle>
        <div className={styles.error} role="alert">
          <span>Die Termine konnten nicht geladen werden.</span>
          <Button variant="link" size="xs" onClick={() => void events.refetch()}>
            Erneut versuchen
          </Button>
        </div>
      </Card>
    );
  }
  const { items, total } = events.data;
  if (total === 0) return null;

  return (
    <Card aria-labelledby="person-events-title">
      <div className={styles.head}>
        <CardTitle id="person-events-title">Termine</CardTitle>
        <span className={styles.base}>
          {total > items.length
            ? `${termine(total)}, die ${formatNumber(items.length)} neuesten`
            : termine(total)}
        </span>
      </div>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Wann</th>
            <th scope="col">Termin</th>
            <th scope="col">Beteiligung</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <Row key={item.event.id} item={item} />
          ))}
        </tbody>
      </table>
      <Link to={personEventsHref(personId)} className={styles.all}>
        Alle Einladungen in der Mailliste
      </Link>
    </Card>
  );
}

function Row({ item }: { item: PersonEvent }) {
  const { event, mail } = item;
  const organizer = event.organizer;
  const answer = answerText(item.partstat);
  return (
    <tr>
      <td className={styles.when}>{eventStart(event) ?? "–"}</td>
      <td>
        <span className={styles.what}>
          <Link to={`/mails/${mail.id}`} title={mail.subject ?? undefined}>
            {event.summary || "(ohne Titel)"}
          </Link>
          {event.kind !== "request" && (
            <span className={cx(styles.kind, styles[event.kind])}>{EVENT_LABELS[event.kind]}</span>
          )}
        </span>
      </td>
      <td className={styles.part}>
        {item.organizer ? (
          "organisiert"
        ) : (
          <>
            {answer && <span className={styles.answer}>{`${answer}, `}</span>}
            eingeladen
            {organizer && (
              <>
                {" von "}
                {organizer.person ? (
                  <PersonLink person={organizer.person} />
                ) : (
                  personName({ name: organizer.name, email: organizer.email ?? "(ohne Adresse)" })
                )}
              </>
            )}
          </>
        )}
      </td>
    </tr>
  );
}

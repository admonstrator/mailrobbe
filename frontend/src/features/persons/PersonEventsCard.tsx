import { Link } from "react-router";

import { usePersonEvents } from "../../api/queries";
import { EVENT_KEYS, type PersonEvent } from "../../api/types";
import { Button } from "../../components/Button";
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

/** "Termine" (D155), the profile's tab Termine: the events the person organised or was invited to, one per UID, newest
 *  first, each with its date, its summary linking to the mail, and who organised it or the
 *  person's answer. Hidden while loading and when the person has none. */
export function PersonEventsCard({ personId }: { personId: number }) {
  const events = usePersonEvents(personId);

  if (events.isPending) return null;
  if (events.isError) {
    return (
      <section className={styles.section} aria-labelledby="person-events-title">
        <h2 id="person-events-title" className={styles.title}>
          Termine
        </h2>
        <div className={styles.error} role="alert">
          <span>Die Termine konnten nicht geladen werden.</span>
          <Button variant="link" size="xs" onClick={() => void events.refetch()}>
            Erneut versuchen
          </Button>
        </div>
      </section>
    );
  }
  const { items, total } = events.data;
  if (total === 0) return null;

  return (
    <section className={styles.section} aria-labelledby="person-events-title">
      <div className={styles.head}>
        <h2 id="person-events-title" className={styles.title}>
          Termine
        </h2>
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
    </section>
  );
}

// Events the overview shows.
const RECENT_EVENTS = 3;

/** "Neueste Termine" of the profile's overview: the latest three events with their date and the
 *  person's part; "Alle n" opens the tab. Nothing while loading, after an error or without any. */
export function PersonRecentEvents({ personId, onMore }: { personId: number; onMore: () => void }) {
  const events = usePersonEvents(personId);
  if (!events.data || events.data.total === 0) return null;
  const { items, total } = events.data;
  return (
    <section className={styles.section} aria-labelledby="person-recent-events-title">
      <div className={styles.head}>
        <h2 id="person-recent-events-title" className={styles.title}>
          Neueste Termine
        </h2>
        <Button variant="link" size="sm" className={styles.more} onClick={onMore}>
          {`Alle ${formatNumber(total)}`}
        </Button>
      </div>
      <ul className={styles.recent}>
        {items.slice(0, RECENT_EVENTS).map((item) => (
          <li key={item.event.id}>
            <span className={styles.when}>{eventStart(item.event) ?? "–"}</span>
            <Link to={`/mails/${item.mail.id}`} title={item.mail.subject ?? undefined}>
              {item.event.summary || "(ohne Titel)"}
            </Link>
            <span className={styles.part}>
              {item.organizer ? "organisiert" : (answerText(item.partstat) ?? "eingeladen")}
            </span>
          </li>
        ))}
      </ul>
    </section>
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

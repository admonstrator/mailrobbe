import { Link } from "react-router";

import { useContacts } from "../../api/queries";
import type { PersonProfile } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { formatDate, formatNumber } from "../../lib/format";
import { personLabel } from "./labels";
import styles from "./ProfileContacts.module.css";

/** The profile's tab Kontakte (D336): every contact of the person as a card, most mails first, a
 *  page at a time; a card opens the contact's profile, "Mails" the mails between both. */
export function ProfileContacts({
  profile,
  mailsHref,
}: {
  profile: PersonProfile;
  /** The profile's mails between the person and contact. */
  mailsHref: (contact: number) => string;
}) {
  const contacts = useContacts(profile.id);
  const items = contacts.data?.pages.flatMap((page) => page.items) ?? [];
  const total = contacts.data?.pages[0]?.total;

  if (contacts.isPending) {
    return (
      <div className={styles.loading}>
        <Spinner label="Kontakte werden geladen" />
      </div>
    );
  }
  if (contacts.isError) {
    return (
      <p className={styles.note} role="alert">
        Die Kontakte konnten nicht geladen werden.{" "}
        <Button variant="link" size="xs" onClick={() => void contacts.refetch()}>
          Erneut versuchen
        </Button>
      </p>
    );
  }
  if (items.length === 0) {
    return (
      <EmptyState title="Keine Kontakte">
        Kontakte erscheinen, sobald ein Import die Mails dieser Person ausgewertet hat.
      </EmptyState>
    );
  }
  return (
    <div className={styles.contacts}>
      <ul className={styles.grid} aria-label={`Kontakte von ${personLabel(profile)}`}>
        {items.map((contact) => {
          const name = personLabel(contact.person);
          return (
            <li key={contact.person.person_id} className={styles.card}>
              <Avatar
                personId={contact.person.person_id}
                name={contact.person.label?.name || contact.person.name}
                email={contact.person.email}
              />
              <div className={styles.who}>
                <Link to={personPath(contact.person.person_id)} className={styles.name}>
                  {name}
                </Link>
                {contact.person.name && (
                  <span className={styles.address}>{contact.person.email}</span>
                )}
                <span
                  className={styles.figures}
                  title={`${formatNumber(contact.sent)} gesendet an den Kontakt, ${formatNumber(
                    contact.received,
                  )} vom Kontakt empfangen, ${formatNumber(contact.cc)} in Cc`}
                >
                  {`${formatNumber(contact.mails)} ${contact.mails === 1 ? "Mail" : "Mails"}`}
                  {contact.last_date && ` · zuletzt ${formatDate(contact.last_date)}`}
                </span>
              </div>
              <Link
                to={mailsHref(contact.person.person_id)}
                className={styles.mails}
                aria-label={`Mails mit ${name}`}
              >
                Mails
              </Link>
            </li>
          );
        })}
      </ul>
      <div className={styles.foot}>
        <span className={styles.count}>
          {total !== undefined &&
            `${formatNumber(items.length)} von ${formatNumber(total)} Kontakten`}
        </span>
        {contacts.hasNextPage && (
          <Button
            onClick={() => void contacts.fetchNextPage()}
            disabled={contacts.isFetchingNextPage}
          >
            Weitere laden
          </Button>
        )}
      </div>
    </div>
  );
}

import { Link } from "react-router";

import type { PersonProfile } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { HelpMark } from "../../components/HelpMark";
import { personPath } from "../../components/PersonLink";
import { formatNumber } from "../../lib/format";
import { personLabel } from "./labels";
import styles from "./TopContacts.module.css";

/** "Mit wem am meisten" of the profile's overview: the persons with the most mails in both
 *  directions as bars; "Alle n" opens the tab of every contact. */
export function TopContacts({ profile, onMore }: { profile: PersonProfile; onMore: () => void }) {
  const contacts = profile.top_contacts;
  const total = profile.figures?.contacts ?? contacts.length;
  const max = Math.max(1, ...contacts.map((contact) => contact.mails));

  return (
    <section className={styles.section} aria-labelledby="top-contacts-title">
      <div className={styles.head}>
        <h2 id="top-contacts-title" className={styles.title}>
          Mit wem am meisten
        </h2>
        <HelpMark text="Mails in beide Richtungen" />
        {total > 0 && (
          <Button variant="link" size="sm" className={styles.all} onClick={onMore}>
            {`Alle ${formatNumber(total)}`}
          </Button>
        )}
      </div>
      {contacts.length === 0 ? (
        <p className={styles.empty}>Noch keine Kontakte ausgewertet.</p>
      ) : (
        <ol className={styles.bars} aria-label="Kontakte mit den meisten Mails">
          {contacts.map((contact) => (
            <li key={contact.person.person_id}>
              <Link
                to={personPath(contact.person.person_id)}
                className={styles.bar}
                title={contact.person.email}
              >
                <Avatar
                  personId={contact.person.person_id}
                  name={contact.person.label?.name || contact.person.name}
                  email={contact.person.email}
                  size="sm"
                />
                <span className={styles.name}>{personLabel(contact.person)}</span>
                <span className={styles.track} aria-hidden="true">
                  <span
                    className={styles.fill}
                    style={{ width: `${(contact.mails / max) * 100}%` }}
                  />
                </span>
                <span className={styles.count}>{formatNumber(contact.mails)}</span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

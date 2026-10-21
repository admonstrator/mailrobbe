import { useState } from "react";
import { Link } from "react-router";

import type { PersonProfile } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { personPath } from "../../components/PersonLink";
import { formatNumber } from "../../lib/format";
import { ContactsDialog } from "./ContactsDialog";
import { personLabel } from "./labels";
import styles from "./TopContacts.module.css";

/** The persons with the most mails in both directions as bars; "Alle N" lists every one. */
export function TopContacts({ profile }: { profile: PersonProfile }) {
  const [showAll, setShowAll] = useState(false);
  const contacts = profile.top_contacts;
  const total = profile.figures?.contacts ?? contacts.length;
  const max = Math.max(1, ...contacts.map((contact) => contact.mails));

  return (
    <Card className={styles.card}>
      <div className={styles.head}>
        <CardTitle>Top-Kontakte</CardTitle>
        <span className={styles.hint}>Mails in beide Richtungen</span>
        {total > 0 && (
          <Button variant="link" className={styles.all} onClick={() => setShowAll(true)}>
            Alle {formatNumber(total)}
          </Button>
        )}
      </div>
      {contacts.length === 0 ? (
        <p className={styles.empty}>Noch keine Kontakte ausgewertet.</p>
      ) : (
        <ol className={styles.bars}>
          {contacts.map((contact) => (
            <li key={contact.person.person_id} className={styles.bar}>
              <Link
                to={personPath(contact.person.person_id)}
                className={styles.name}
                title={contact.person.email}
              >
                {personLabel(contact.person)}
              </Link>
              <span className={styles.track} aria-hidden="true">
                <span
                  className={styles.fill}
                  style={{ width: `${(contact.mails / max) * 100}%` }}
                />
              </span>
              <span className={styles.count}>{formatNumber(contact.mails)}</span>
            </li>
          ))}
        </ol>
      )}
      {showAll && <ContactsDialog profile={profile} onClose={() => setShowAll(false)} />}
    </Card>
  );
}

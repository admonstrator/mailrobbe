import { Link } from "react-router";

import type { MailDetail } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import styles from "./ActionsCard.module.css";

export function ActionsCard({ mail, onShowRaw }: { mail: MailDetail; onShowRaw: () => void }) {
  const sender = mail.participants.find((person) => person.role === "from");
  const recipient = mail.participants.find(
    (person) => person.role !== "from" && person.person_id !== sender?.person_id,
  );

  return (
    <Card variant="side">
      <CardTitle variant="caps">Aktionen</CardTitle>
      <a href={`/api/mails/${mail.id}/eml`} className={styles.action} download>
        Als EML herunterladen
      </a>
      <a href={`/api/mails/${mail.id}/pdf`} className={styles.action} download>
        Als PDF herunterladen
      </a>
      <a
        href={`/api/mails/${mail.id}/pdf?research=true`}
        className={styles.action}
        title="Mit Status, Schlagwörtern, Akten und Notizen"
        download
      >
        PDF mit Notizen
      </a>
      <button type="button" className={styles.action} onClick={onShowRaw}>
        Rohmail aus MBOX anzeigen
      </button>
      {sender && recipient && (
        <Link
          to={`/mails?between=${sender.person_id}&between=${recipient.person_id}`}
          className={styles.action}
        >
          Alle Mails zwischen {sender.name || sender.email} und {recipient.name || recipient.email}
        </Link>
      )}
    </Card>
  );
}

import { Link } from "react-router";

import { useContacts } from "../../api/queries";
import type { PersonProfile } from "../../api/types";
import { Button } from "../../components/Button";
import { personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { formatDate, formatNumber } from "../../lib/format";
import styles from "./ContactsDialog.module.css";
import { Dialog } from "./Dialog";
import { personLabel } from "./labels";

/** Every contact of a person, most mails first, a page at a time. */
export function ContactsDialog({
  profile,
  onClose,
}: {
  profile: PersonProfile;
  onClose: () => void;
}) {
  const contacts = useContacts(profile.id);
  const items = contacts.data?.pages.flatMap((page) => page.items) ?? [];
  const total = contacts.data?.pages[0]?.total;

  return (
    <Dialog title={`Kontakte von ${personLabel(profile)}`} onClose={onClose}>
      <div className={styles.scroll}>
        {contacts.isPending && <Spinner label="Kontakte werden geladen" />}
        {contacts.isError && (
          <p className={styles.note}>Die Kontakte konnten nicht geladen werden.</p>
        )}
        {items.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Kontakt</th>
                <th className={styles.num}>Mails</th>
                <th className={styles.num} title="von dieser Person an den Kontakt">
                  Gesendet
                </th>
                <th className={styles.num} title="vom Kontakt an diese Person">
                  Empfangen
                </th>
                <th className={styles.num}>Cc</th>
                <th>Letzte Mail</th>
              </tr>
            </thead>
            <tbody>
              {items.map((contact) => (
                <tr key={contact.person.person_id}>
                  <td>
                    <Link to={personPath(contact.person.person_id)} className={styles.name}>
                      {personLabel(contact.person)}
                    </Link>
                    {contact.person.name && (
                      <span className={styles.address}>{contact.person.email}</span>
                    )}
                  </td>
                  <td className={styles.num}>{formatNumber(contact.mails)}</td>
                  <td className={styles.num}>{formatNumber(contact.sent)}</td>
                  <td className={styles.num}>{formatNumber(contact.received)}</td>
                  <td className={styles.num}>{formatNumber(contact.cc)}</td>
                  <td className={styles.date}>
                    {contact.last_date ? formatDate(contact.last_date) : "–"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
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
        <Button variant="primary" onClick={onClose}>
          Schließen
        </Button>
      </div>
    </Dialog>
  );
}

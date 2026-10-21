import type { MouseEvent } from "react";
import { Link, useNavigate } from "react-router";

import type { MailListItem, PersonRef } from "../../api/types";
import { DkimDot } from "../../components/DkimDot";
import { CopyIcon, FlagIcon, PaperclipIcon } from "../../components/icons";
import { PersonLink } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { dkimKey } from "../../lib/dkim";
import { formatBytes, formatDateTime } from "../../lib/format";
import type { ColumnChoice } from "./columns";
import styles from "./MailTable.module.css";

const personLabel = (person: PersonRef) => person.name || person.email;

/** "Jonas Brandt +2": all names for up to two recipients, else the first one and the rest. */
function Recipients({ mail }: { mail: MailListItem }) {
  const { recipients, recipient_count: count } = mail;
  if (count === 0) return <span className={styles.muted}>–</span>;
  const shown = count <= 2 ? recipients : recipients.slice(0, 1);
  const rest = count - shown.length;
  return (
    <span title={recipients.map(personLabel).join(", ") + (count > recipients.length ? " …" : "")}>
      {shown.map(personLabel).join(", ")}
      {rest > 0 && <span className={styles.muted}> +{rest}</span>}
    </span>
  );
}

/** One page of the mail list. Each row opens the mail; the subject is the real link, so
 *  middle-click and "open in new tab" work. */
export function MailTable({
  items,
  columns,
  detailSearch,
  mboxPath,
  stale,
}: {
  items: MailListItem[];
  columns: ColumnChoice;
  /** Query string the detail links carry, so the detail knows the list around it. */
  detailSearch: string;
  mboxPath: (id: number) => string;
  stale: boolean;
}) {
  const navigate = useNavigate();
  const href = (id: number) => `/mails/${id}${detailSearch ? `?${detailSearch}` : ""}`;

  function openRow(event: MouseEvent<HTMLTableRowElement>, id: number) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, label") || window.getSelection()?.toString()) return;
    void navigate(href(id));
  }

  return (
    <div className={styles.scroll}>
      <table className={cx(styles.table, stale && styles.stale)}>
        <thead>
          <tr>
            <th className={styles.dkimCol}>DKIM</th>
            <th>Von</th>
            {columns.to && <th>An</th>}
            <th>Betreff</th>
            {columns.attachment && (
              <th className={styles.iconCol}>
                <span className="sr-only">Anhang</span>
              </th>
            )}
            {columns.size && <th className={styles.sizeCol}>Größe</th>}
            {columns.mbox && <th>MBOX-Datei</th>}
            <th className={styles.dateCol}>Datum</th>
          </tr>
        </thead>
        <tbody>
          {items.map((mail) => (
            <tr key={mail.id} onClick={(event) => openRow(event, mail.id)}>
              <td>
                <DkimDot status={dkimKey(mail.dkim_status)} />
              </td>
              <td className={styles.from}>
                {mail.sender ? (
                  <>
                    <PersonLink person={mail.sender} className={styles.name} />
                    {mail.sender.name && (
                      <span className={styles.address}>{mail.sender.email}</span>
                    )}
                  </>
                ) : (
                  <span className={styles.muted}>(unbekannt)</span>
                )}
              </td>
              {columns.to && (
                <td className={styles.to}>
                  <Recipients mail={mail} />
                </td>
              )}
              <td className={styles.subject}>
                <Link
                  to={href(mail.id)}
                  className={cx(styles.subjectLink, !mail.subject && styles.muted)}
                >
                  {mail.subject || "(kein Betreff)"}
                </Link>
                {mail.flagged && <FlagIcon size={13} label="Markiert" className={styles.flag} />}
                {mail.is_duplicate && (
                  <CopyIcon size={13} label="Duplikat" className={styles.duplicate} />
                )}
              </td>
              {columns.attachment && (
                <td className={styles.icon}>
                  {mail.has_attachments && <PaperclipIcon size={14} label="Anhang" />}
                </td>
              )}
              {columns.size && <td className={styles.size}>{formatBytes(mail.size)}</td>}
              {columns.mbox && <td className={styles.mbox}>{mboxPath(mail.mbox_file_id)}</td>}
              <td className={styles.date}>{mail.date ? formatDateTime(mail.date) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

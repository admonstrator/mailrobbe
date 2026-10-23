import type { MouseEvent } from "react";
import { Link, useNavigate } from "react-router";

import type { PersonSummary } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { personPath } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { formatDate, formatNumber, formatPercent } from "../../lib/format";
import styles from "./PersonTable.module.css";
import { aliasHint, personLabel } from "./labels";

/** One page of the person list (D31, D336): who it is, the domain, mails, contacts and the last
 *  mail; the rest of the figures in a short profile on hovering or focusing the name. Each row
 *  opens the profile; the name is the real link. */
export function PersonTable({ items, stale }: { items: PersonSummary[]; stale: boolean }) {
  const navigate = useNavigate();

  function openRow(event: MouseEvent<HTMLTableRowElement>, id: number) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, label") || window.getSelection()?.toString()) return;
    void navigate(personPath(id));
  }

  return (
    <div className={styles.scroll}>
      <table className={cx(styles.table, stale && styles.stale)}>
        <thead>
          <tr>
            <th>Person</th>
            <th className={styles.domainCol}>Domain</th>
            <th className={styles.num}>Mails</th>
            <th className={styles.num}>Kontakte</th>
            <th className={cx(styles.num, styles.dateCol)}>Zuletzt</th>
          </tr>
        </thead>
        <tbody>
          {items.map((person) => {
            const { figures } = person;
            const name = person.label?.name || person.name;
            return (
              <tr key={person.id} onClick={(event) => openRow(event, person.id)}>
                <td>
                  <div className={styles.person}>
                    <Avatar personId={person.id} name={name} email={person.email} />
                    <div className={styles.identity}>
                      <span className={styles.nameLine}>
                        <Link to={personPath(person.id)} className={styles.name}>
                          {personLabel(person)}
                        </Link>
                        {person.label?.role && (
                          <span className={styles.role}>{person.label.role}</span>
                        )}
                        {person.aliases > 0 && (
                          <span className={styles.aliases}>{aliasHint(person.aliases)}</span>
                        )}
                        <span className={styles.card} role="tooltip">
                          <span className={styles.cardHead}>
                            <Avatar personId={person.id} name={name} email={person.email} />
                            <span className={styles.cardWho}>
                              <span className={styles.cardName}>{personLabel(person)}</span>
                              <span className={styles.address}>{person.email}</span>
                            </span>
                          </span>
                          <span className={styles.cardLine}>
                            {`${formatNumber(figures.sent)} gesendet · ${formatNumber(
                              figures.received,
                            )} empfangen · `}
                            {figures.dkim_pass_ratio === null
                              ? "keine geprüfte Mail gesendet"
                              : `DKIM gültig ${formatPercent(figures.dkim_pass_ratio)}`}
                          </span>
                          {figures.first_date && figures.last_date && (
                            <span className={styles.cardLine}>
                              {`Aktiv ${formatDate(figures.first_date)} bis ${formatDate(figures.last_date)}`}
                            </span>
                          )}
                        </span>
                      </span>
                      {name && <span className={styles.address}>{person.email}</span>}
                    </div>
                  </div>
                </td>
                <td className={styles.domain}>{person.domain}</td>
                <td className={cx(styles.num, styles.strong)}>{formatNumber(figures.mails)}</td>
                <td className={styles.num}>{formatNumber(figures.contacts)}</td>
                <td className={cx(styles.num, styles.date)}>
                  {figures.last_date ? formatDate(figures.last_date) : "–"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

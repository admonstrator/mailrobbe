import type { MouseEvent } from "react";
import { Link, useNavigate } from "react-router";

import type { PersonSummary } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { personPath } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { formatDate, formatNumber, formatPercent } from "../../lib/format";
import styles from "./PersonTable.module.css";
import { aliasHint, personLabel } from "./labels";

/** One page of the person list. Each row opens the profile; the name is the real link. */
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
            <th>Domain</th>
            <th className={styles.num}>Mails</th>
            <th className={styles.num}>Gesendet</th>
            <th className={styles.num}>Empfangen</th>
            <th className={styles.num}>Kontakte</th>
            <th>Letzte Mail</th>
            <th className={styles.num}>DKIM gültig</th>
          </tr>
        </thead>
        <tbody>
          {items.map((person) => {
            const { figures } = person;
            return (
              <tr key={person.id} onClick={(event) => openRow(event, person.id)}>
                <td>
                  <div className={styles.person}>
                    <Avatar
                      personId={person.id}
                      name={person.label?.name || person.name}
                      email={person.email}
                    />
                    <div className={styles.identity}>
                      <span>
                        <Link to={personPath(person.id)} className={styles.name}>
                          {personLabel(person)}
                        </Link>
                        {person.label?.role && (
                          <span className={styles.role}>{person.label.role}</span>
                        )}
                        {person.aliases > 0 && (
                          <span className={styles.aliases}>{aliasHint(person.aliases)}</span>
                        )}
                      </span>
                      {(person.label?.name || person.name) && (
                        <span className={styles.address}>{person.email}</span>
                      )}
                    </div>
                  </div>
                </td>
                <td className={styles.domain}>{person.domain}</td>
                <td className={cx(styles.num, styles.strong)}>{formatNumber(figures.mails)}</td>
                <td className={styles.num}>{formatNumber(figures.sent)}</td>
                <td className={styles.num}>{formatNumber(figures.received)}</td>
                <td className={styles.num}>{formatNumber(figures.contacts)}</td>
                <td className={styles.date}>
                  {figures.last_date ? formatDate(figures.last_date) : "–"}
                </td>
                <td className={styles.num}>
                  {figures.dkim_pass_ratio === null ? (
                    <span className={styles.muted}>–</span>
                  ) : (
                    formatPercent(figures.dkim_pass_ratio)
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

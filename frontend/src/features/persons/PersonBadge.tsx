import type { ReactNode } from "react";
import { Link } from "react-router";

import type { PersonSummary } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { personPath } from "../../components/PersonLink";
import { formatNumber } from "../../lib/format";
import styles from "./PersonBadge.module.css";
import { personLabel } from "./labels";

/** A person in the suggestion list and the merge dialog: avatar, name, address and mails,
 *  then children. The name links to the profile unless the badge sits inside a label. */
export function PersonBadge({
  person,
  link = true,
  children,
}: {
  person: PersonSummary;
  link?: boolean;
  children?: ReactNode;
}) {
  return (
    <span className={styles.badge}>
      <Avatar personId={person.id} name={person.label?.name || person.name} email={person.email} />
      <span className={styles.text}>
        {link ? (
          <Link to={personPath(person.id)} className={styles.name}>
            {personLabel(person)}
          </Link>
        ) : (
          <span className={styles.name}>{personLabel(person)}</span>
        )}
        {(person.label?.name || person.name) && (
          <span className={styles.address}>{person.email}</span>
        )}
        <span className={styles.meta}>
          {formatNumber(person.figures.mails)} Mails
          {children}
        </span>
      </span>
    </span>
  );
}

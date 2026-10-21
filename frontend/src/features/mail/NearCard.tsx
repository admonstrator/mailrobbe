import { Fragment } from "react";
import { Link } from "react-router";

import type { MailDetail, NearMail } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { DkimDot } from "../../components/DkimDot";
import { PersonLink } from "../../components/PersonLink";
import { dkimKey } from "../../lib/dkim";
import { formatDateTime, formatNumber } from "../../lib/format";
import styles from "./NearCard.module.css";

/** Who sent one mail of the group to whom: the persons link to their profiles. */
function People({ mail }: { mail: NearMail }) {
  const rest = mail.recipient_count - mail.recipients.length;
  return (
    <span className={styles.people}>
      {mail.sender ? <PersonLink person={mail.sender} /> : "(unbekannt)"}
      {mail.recipient_count > 0 && " an "}
      {mail.recipients.map((recipient, index) => (
        <Fragment key={`${recipient.person_id}-${index}`}>
          {index > 0 && ", "}
          <PersonLink person={recipient} />
        </Fragment>
      ))}
      {rest > 0 && <span className={styles.rest}> +{formatNumber(rest)}</span>}
    </span>
  );
}

/** The other mails of the open mail's group of near duplicates (D153), oldest first: the same
 *  text sent again, to others or once more, and the whole group in the mail list. */
export function NearCard({
  mail,
  mailHref,
}: {
  mail: MailDetail;
  mailHref: (id: number) => string;
}) {
  const more = mail.near_size - 1 - mail.near.length;
  return (
    <Card variant="side">
      <CardTitle variant="caps">{formatNumber(mail.near_size)} nahezu gleiche Mails</CardTitle>
      <ol className={styles.list}>
        {mail.near.map((near) => (
          <li key={near.id} className={styles.item}>
            <span className={styles.dot}>
              <DkimDot status={dkimKey(near.dkim_status)} size={8} />
            </span>
            <span className={styles.text}>
              <span className={styles.head}>
                <Link to={mailHref(near.id)}>
                  {near.date ? formatDateTime(near.date) : "ohne Datum"}
                </Link>
                {near.is_duplicate && (
                  <span className={styles.duplicate} title="Exaktes Duplikat einer anderen Mail">
                    Doppelt
                  </span>
                )}
              </span>
              <People mail={near} />
            </span>
          </li>
        ))}
      </ol>
      {more > 0 && <p className={styles.more}>… und {formatNumber(more)} weitere</p>}
      {mail.near_group !== null && (
        <p className={styles.links}>
          <Link to={`/mails?near_group=${mail.near_group}`}>Alle in der Mailliste</Link>
        </p>
      )}
    </Card>
  );
}

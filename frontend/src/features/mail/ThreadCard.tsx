import { Link } from "react-router";

import type { MailDetail, ThreadMail } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { DkimDot } from "../../components/DkimDot";
import { cx } from "../../lib/cx";
import { dkimKey } from "../../lib/dkim";
import { formatNumber, formatShortDate } from "../../lib/format";
import styles from "./ThreadCard.module.css";

function Entry({
  mail,
  referenceDate,
  current,
}: {
  mail: ThreadMail;
  referenceDate: string | null;
  current: boolean;
}) {
  const sender = mail.sender ? mail.sender.name || mail.sender.email : "(unbekannt)";
  return (
    <>
      <span className={styles.dot}>
        <DkimDot status={dkimKey(mail.dkim_status)} size={8} />
      </span>
      <span className={styles.text}>
        <span className={styles.head}>
          {sender}
          {mail.date && ` · ${formatShortDate(mail.date, referenceDate)}`}
        </span>
        <span className={styles.subject}>
          {mail.subject || "(kein Betreff)"}
          {current && " (diese Mail)"}
        </span>
      </span>
    </>
  );
}

/** The mails of the thread by date, the open one highlighted (D17). */
export function ThreadCard({
  mail,
  mailHref,
}: {
  mail: MailDetail;
  mailHref: (id: number) => string;
}) {
  const more = mail.thread_size - mail.thread.length;
  return (
    <Card variant="side">
      <CardTitle variant="caps">Thread ({formatNumber(mail.thread_size)} Mails)</CardTitle>
      <ol className={styles.list}>
        {mail.thread.map((member) => {
          const current = member.id === mail.id;
          const entry = <Entry mail={member} referenceDate={mail.date} current={current} />;
          return (
            <li key={member.id}>
              {current ? (
                <div className={cx(styles.item, styles.current)} aria-current="true">
                  {entry}
                </div>
              ) : (
                <Link to={mailHref(member.id)} className={styles.item}>
                  {entry}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
      {more > 0 && <p className={styles.more}>… und {formatNumber(more)} weitere</p>}
    </Card>
  );
}

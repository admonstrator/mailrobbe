import { Fragment, type ReactNode } from "react";
import { Link } from "react-router";

import type { MailDetail, Participant, ParticipationRole } from "../../api/types";
import { Card } from "../../components/Card";
import { DkimBadge } from "../../components/DkimBadge";
import { Highlighted, type SearchMarks } from "../../components/Highlighted";
import { CopyIcon } from "../../components/icons";
import { PersonLink } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { dkimKey } from "../../lib/dkim";
import { formatBytes, formatDateTimeLong, formatNumber, formatRelative } from "../../lib/format";
import styles from "./HeaderCard.module.css";

function Meta({ label, mono, children }: { label: string; mono?: boolean; children: ReactNode }) {
  return (
    <div className={styles.item}>
      <dt className={styles.label}>{label}</dt>
      <dd className={cx(styles.value, mono && styles.mono)}>{children}</dd>
    </div>
  );
}

/** "Anna Keller <anna@…>, Peter Hofmann <p@…>" with the names linking to the profiles. */
function People({ people, strong }: { people: Participant[]; strong?: boolean }) {
  if (people.length === 0) return <span className={styles.muted}>–</span>;
  return people.map((person, index) => (
    <Fragment key={person.person_id}>
      {index > 0 && ", "}
      {person.label?.name || person.name ? (
        <>
          <PersonLink person={person} className={cx(styles.person, strong && styles.strong)} />{" "}
          <span className={styles.address}>&lt;{person.email}&gt;</span>
        </>
      ) : (
        <PersonLink person={person} className={cx(styles.person, styles.address)} />
      )}
    </Fragment>
  ));
}

/** "3f9a…c21e" */
const shortHash = (hash: string) => `${hash.slice(0, 4)}…${hash.slice(-4)}`;

/** Subject, DKIM badge and the metadata grid; the search words marked in the subject (D79). */
export function HeaderCard({
  mail,
  mailHref,
  marks,
}: {
  mail: MailDetail;
  mailHref: (id: number) => string;
  marks?: SearchMarks;
}) {
  const byRole = (role: ParticipationRole) => mail.participants.filter((p) => p.role === role);
  const cc = byRole("cc");
  const bcc = byRole("bcc");
  const { source } = mail;

  return (
    <Card className={styles.card}>
      <div className={styles.titleRow}>
        <h1 className={cx(styles.subject, !mail.subject && styles.muted)}>
          {mail.subject ? <Highlighted text={mail.subject} marks={marks} /> : "(kein Betreff)"}
        </h1>
        <DkimBadge status={dkimKey(mail.dkim.status)} />
      </div>
      <dl className={styles.grid}>
        <Meta label="Von">
          <People people={byRole("from")} strong />
        </Meta>
        <Meta label="Datum">
          {mail.date ? (
            <>
              {formatDateTimeLong(mail.date)}{" "}
              <span className={styles.muted}>({formatRelative(mail.date)})</span>
            </>
          ) : (
            <span className={styles.muted}>unbekannt</span>
          )}
        </Meta>
        <Meta label="An">
          <People people={byRole("to")} />
        </Meta>
        {cc.length > 0 && (
          <Meta label="Cc">
            <People people={cc} />
          </Meta>
        )}
        {bcc.length > 0 && (
          <Meta label="Bcc">
            <People people={bcc} />
          </Meta>
        )}
        <Meta label="Message-ID" mono>
          {mail.message_id ?? "–"}
        </Meta>
        <Meta label="In-Reply-To" mono>
          {mail.in_reply_to === null ? (
            "–"
          ) : mail.in_reply_to_id === null ? (
            mail.in_reply_to
          ) : (
            <Link to={mailHref(mail.in_reply_to_id)}>{mail.in_reply_to}</Link>
          )}
        </Meta>
        <Meta label="Quelle" mono>
          {source.path} · Offset {formatNumber(source.byte_offset)} ·{" "}
          {formatBytes(source.byte_length)}
        </Meta>
        <Meta label="Interne ID" mono>
          #{mail.id} · SHA-256 <span title={mail.raw_sha256}>{shortHash(mail.raw_sha256)}</span>
        </Meta>
      </dl>
      {(mail.duplicate_of !== null || mail.duplicates.length > 0) && (
        <p className={styles.duplicates}>
          <CopyIcon size={14} />
          {mail.duplicate_of !== null ? (
            <span>
              Duplikat von <Link to={mailHref(mail.duplicate_of)}>#{mail.duplicate_of}</Link>
            </span>
          ) : (
            <span>
              {mail.duplicates.length === 1
                ? "1 Duplikat dieser Mail: "
                : `${formatNumber(mail.duplicates.length)} Duplikate dieser Mail: `}
              {mail.duplicates.map((id, index) => (
                <Fragment key={id}>
                  {index > 0 && ", "}
                  <Link to={mailHref(id)}>#{id}</Link>
                </Fragment>
              ))}
            </span>
          )}
        </p>
      )}
    </Card>
  );
}

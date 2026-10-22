import { Fragment, type ReactNode, type Ref } from "react";
import { flushSync } from "react-dom";
import { Link } from "react-router";

import type { MailDetail, Participant, ParticipationRole } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Card } from "../../components/Card";
import { DkimBadge } from "../../components/DkimBadge";
import { FoldCard } from "../../components/FoldCard";
import { Highlighted, type SearchMarks } from "../../components/Highlighted";
import { CopyIcon, PaperclipIcon } from "../../components/icons";
import { PersonLink } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { dkimKey } from "../../lib/dkim";
import { setFoldOpen } from "../../lib/folds";
import {
  formatBytes,
  formatDateTime,
  formatDateTimeLong,
  formatNumber,
  formatRelative,
} from "../../lib/format";
import { personName } from "../../lib/person";
import { ATTACHMENTS_CARD_ID, ATTACHMENTS_FOLD } from "./AttachmentsCard";
import { DKIM_CARD_ID, DKIM_FOLD } from "./DkimCard";
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

/** Opens a block below the text and scrolls to it, once it is open: the page may be too short
 *  to scroll that far while it is folded. */
function show(fold: string, elementId: string): void {
  flushSync(() => setFoldOpen(fold, true));
  document.getElementById(elementId)?.scrollIntoView?.({ block: "start", behavior: "smooth" });
}

/** Subject, DKIM badge, sender, recipients and date, as a mail program shows them; the search
 *  words marked in the subject (D79). The technical fields are in TechCard below the text. */
export function HeaderCard({
  mail,
  mailHref,
  marks,
  ref,
}: {
  mail: MailDetail;
  mailHref: (id: number) => string;
  marks?: SearchMarks;
  ref?: Ref<HTMLElement>;
}) {
  const byRole = (role: ParticipationRole) => mail.participants.filter((p) => p.role === role);
  const from = byRole("from");
  const sender = from.at(0);

  return (
    <Card ref={ref} className={styles.card}>
      <div className={styles.titleRow}>
        <h1 className={cx(styles.subject, !mail.subject && styles.muted)}>
          {mail.subject ? <Highlighted text={mail.subject} marks={marks} /> : "(kein Betreff)"}
        </h1>
        <button
          type="button"
          className={styles.dkim}
          title="DKIM-Prüfung zeigen"
          onClick={() => show(DKIM_FOLD, DKIM_CARD_ID)}
        >
          <DkimBadge status={dkimKey(mail.dkim.status)} />
        </button>
      </div>
      <div className={styles.from}>
        {sender && (
          <Avatar personId={sender.person_id} name={personName(sender)} email={sender.email} />
        )}
        <dl className={styles.people}>
          <div className={styles.line}>
            <dt className={styles.hidden}>Von</dt>
            <dd className={styles.value}>
              <People people={from} strong />
            </dd>
          </div>
          {(["to", "cc", "bcc"] as const).map((role) => {
            const people = byRole(role);
            if (people.length === 0 && role !== "to") return null;
            return (
              <div key={role} className={styles.line}>
                <dt className={styles.role}>{ROLE_LABELS[role]}:</dt>
                <dd className={styles.value}>
                  <People people={people} />
                </dd>
              </div>
            );
          })}
        </dl>
        <p className={styles.when}>
          {mail.date ? (
            <>
              <span>{formatDateTimeLong(mail.date)}</span>
              <span className={styles.muted}>{formatRelative(mail.date)}</span>
            </>
          ) : (
            <span className={styles.muted}>Datum unbekannt</span>
          )}
        </p>
      </div>
      {mail.attachments.length > 0 && (
        <p className={styles.chips}>
          <button
            type="button"
            className={styles.chip}
            onClick={() => show(ATTACHMENTS_FOLD, ATTACHMENTS_CARD_ID)}
          >
            <PaperclipIcon size={14} />
            {mail.attachments.length === 1
              ? "1 Anhang"
              : `${formatNumber(mail.attachments.length)} Anhänge`}
            {` · ${formatBytes(mail.attachments.reduce((sum, { size }) => sum + size, 0))}`}
          </button>
        </p>
      )}
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

const ROLE_LABELS = { to: "An", cc: "Cc", bcc: "Bcc" } as const;

/** Message-ID, In-Reply-To, the place in the MBOX file and the internal id: folded below the
 *  text until opened once. */
export function TechCard({
  mail,
  mailHref,
}: {
  mail: MailDetail;
  mailHref: (id: number) => string;
}) {
  const { source } = mail;
  return (
    <FoldCard
      id="mail.tech"
      variant="main"
      defaultOpen={false}
      title="Technische Angaben"
      summary="Message-ID, In-Reply-To, Quelle in der MBOX, interne ID"
    >
      <dl className={styles.grid}>
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
    </FoldCard>
  );
}

/** The header in the compact bar (D166): subject on one line, sender, date and DKIM status, and
 *  the steps through the list the mail was opened from. */
export function CompactHeader({ mail, steps }: { mail: MailDetail; steps: ReactNode }) {
  const sender = mail.participants.find((person) => person.role === "from");
  return (
    <>
      <span
        className={cx(styles.compactSubject, !mail.subject && styles.muted)}
        title={mail.subject ?? undefined}
      >
        {mail.subject || "(kein Betreff)"}
      </span>
      {sender && (
        <span className={styles.compactSender} title={sender.email}>
          {personName(sender)}
        </span>
      )}
      {mail.date && <span className={styles.compactDate}>{formatDateTime(mail.date)}</span>}
      <DkimBadge status={dkimKey(mail.dkim.status)} />
      {steps}
    </>
  );
}

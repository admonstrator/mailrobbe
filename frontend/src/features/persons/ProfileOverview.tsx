import { Link } from "react-router";

import { useMailPage } from "../../api/queries";
import type { MailListItem, PersonFigures, PersonProfile } from "../../api/types";
import { Button } from "../../components/Button";
import { Figures } from "../../components/PageHead";
import { PersonLink } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { formatDate, formatNumber } from "../../lib/format";
import { listSearch, toListParams } from "../mails/listState";
import { PersonTermsCard } from "../topics/PersonTermsCard";
import { ActivityGrid } from "./ActivityGrid";
import { PersonRecentEvents } from "./PersonEventsCard";
import { PersonSignalChips } from "./PersonSignalsCard";
import styles from "./ProfileOverview.module.css";
import { TopContacts } from "./TopContacts";
import { DEFAULT_PROFILE_MAIL_STATE, personMailList, type ProfileTab } from "./urlState";

// The newest mails the overview lists.
const RECENT_MAILS = 5;

/** The figures of a person (D29) as a row of numbers (D334). */
function PersonFigureRow({ figures }: { figures: PersonFigures }) {
  const items: [string, number][] = [
    ["Mails", figures.mails],
    ["Gesendet", figures.sent],
    ["Empfangen (An/Cc)", figures.received],
    ["Nur Cc", figures.cc_only],
    ["Kontakte", figures.contacts],
  ];
  return (
    <Figures
      label="Kennzahlen"
      items={items.map(([label, value]) => ({ label, value: formatNumber(value) }))}
    />
  );
}

/** The profile's tab Überblick (D336): figures, the activity of a year by day, the contacts,
 *  the striking terms, the signals, the latest events and the newest mails. */
export function ProfileOverview({
  profile,
  onTab,
}: {
  profile: PersonProfile;
  onTab: (tab: ProfileTab) => void;
}) {
  return (
    <div className={styles.overview}>
      {profile.figures ? (
        <PersonFigureRow figures={profile.figures} />
      ) : (
        <p className={styles.pending}>
          Die Kennzahlen dieser Person werden beim nächsten Import berechnet.
        </p>
      )}
      <ActivityGrid personId={profile.id} years={profile.years} />
      <div className={styles.pair}>
        <TopContacts profile={profile} onMore={() => onTab("kontakte")} />
        <div className={styles.column}>
          {profile.figures?.sent !== 0 && <PersonTermsCard personId={profile.id} />}
          <PersonSignalChips personId={profile.id} onMore={() => onTab("signale")} />
          <PersonRecentEvents personId={profile.id} onMore={() => onTab("termine")} />
        </div>
      </div>
      <RecentMails profile={profile} onMore={() => onTab("mails")} />
    </div>
  );
}

/** "Zuletzt": the person's newest mails, with the direction and the other side. */
function RecentMails({ profile, onMore }: { profile: PersonProfile; onMore: () => void }) {
  const list = { ...personMailList(profile.id, DEFAULT_PROFILE_MAIL_STATE), limit: RECENT_MAILS };
  const page = useMailPage(toListParams(list));
  const total = profile.figures?.mails;
  const items = page.data?.items ?? [];
  const detailSearch = listSearch({ ...list, limit: DEFAULT_PROFILE_MAIL_STATE.limit }).toString();

  return (
    <section className={styles.section} aria-labelledby="recent-mails-title">
      <div className={styles.head}>
        <h2 id="recent-mails-title" className={styles.title}>
          Zuletzt
        </h2>
        <Button variant="link" size="sm" className={styles.more} onClick={onMore}>
          {total === undefined ? "Alle Mails" : `Alle ${formatNumber(total)} Mails`}
        </Button>
      </div>
      {page.isError ? (
        <p className={styles.pending} role="alert">
          Die Mails konnten nicht geladen werden.{" "}
          <Button variant="link" size="xs" onClick={() => void page.refetch()}>
            Erneut versuchen
          </Button>
        </p>
      ) : page.isPending ? (
        <p className={styles.pending}>Mails werden geladen …</p>
      ) : items.length === 0 ? (
        <p className={styles.pending}>Keine Mails.</p>
      ) : (
        <ul className={styles.mails} aria-label="Neueste Mails">
          {items.map((mail) => (
            <RecentMail
              key={mail.id}
              mail={mail}
              href={`/mails/${mail.id}${detailSearch ? `?${detailSearch}` : ""}`}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function RecentMail({ mail, href }: { mail: MailListItem; href: string }) {
  const sent = mail.person_role === "from";
  const other = sent ? mail.recipients[0] : mail.sender;
  return (
    <li className={styles.mail}>
      <span className={styles.date}>{mail.date ? formatDate(mail.date) : "–"}</span>
      <span
        className={cx(styles.direction, sent ? styles.out : styles.in)}
        title={sent ? "gesendet" : "empfangen"}
        aria-label={sent ? "gesendet" : "empfangen"}
      >
        {sent ? "↗" : "↙"}
      </span>
      <span className={styles.other}>
        {other ? <PersonLink person={other} /> : <span className={styles.muted}>–</span>}
      </span>
      <Link to={href} className={cx(styles.subject, !mail.subject && styles.muted)}>
        {mail.subject || "(kein Betreff)"}
      </Link>
    </li>
  );
}

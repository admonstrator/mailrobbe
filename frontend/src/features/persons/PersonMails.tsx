import type { MouseEvent } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError } from "../../api/client";
import { useMailPage, usePersonMailCounts } from "../../api/queries";
import {
  type MailListItem,
  type ParticipationRole,
  type PersonFigures,
  type PersonMailCountParams,
  type PersonMailCounts,
  type PersonProfile,
  type PersonRole,
} from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { DkimDot } from "../../components/DkimDot";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { PageTooFar, Pagination } from "../../components/Pagination";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { cx } from "../../lib/cx";
import { dkimKey } from "../../lib/dkim";
import { formatDateTime, formatNumber } from "../../lib/format";
import { edgePages, listPagination } from "../../lib/paging";
import { PERSON_ROLE_LABELS } from "../mails/chips";
import { listSearch, toListParams } from "../mails/listState";
import { personLabel } from "./labels";
import styles from "./PersonMails.module.css";
import { personMailList, withSelection, type ProfileMailState } from "./urlState";

type MailTab = "all" | PersonRole;

const TABS_ID = "person-mails";
const TABS: MailTab[] = ["all", "sent", "received", "cc"];
const TAB_LABELS: Record<MailTab, string> = { all: "Alle", ...PERSON_ROLE_LABELS };

const ROLE_LABELS: Record<ParticipationRole, string> = {
  from: "Von",
  to: "An",
  cc: "Cc",
  bcc: "Bcc",
};

function figureCounts(figures: PersonFigures): PersonMailCounts {
  return {
    all: figures.mails,
    sent: figures.sent,
    received: figures.received,
    cc: figures.cc_only,
  };
}

/** The person's mails (D32): tabs by role, a contact and a year to narrow them, one page of the
 *  mail list. Tab counts are the figures, or counted for a chosen year or contact. */
export function PersonMails({
  profile,
  state,
  onChange,
  href,
}: {
  profile: PersonProfile;
  state: ProfileMailState;
  onChange: (next: ProfileMailState) => void;
  href: (state: ProfileMailState) => string;
}) {
  const list = personMailList(profile.id, state);
  const page = useMailPage(toListParams(list));
  const narrowed = state.year !== null || state.contact !== null;
  const countParams: PersonMailCountParams = {};
  if (state.year !== null) countParams.year = state.year;
  if (state.contact !== null) countParams.contact = state.contact;
  const counted = usePersonMailCounts(
    profile.id,
    countParams,
    narrowed || profile.figures === null,
  );
  const counts = !narrowed && profile.figures ? figureCounts(profile.figures) : counted.data;
  const tab: MailTab = state.role ?? "all";
  const total = counts?.[tab] ?? null;

  const contacts = profile.top_contacts.map((contact) => contact.person);
  // A contact from a link that is not among the top contacts still needs its option.
  const otherContact = contacts.some((person) => person.person_id === state.contact)
    ? null
    : state.contact;
  const otherYear = profile.years.some(({ year }) => year === state.year) ? null : state.year;

  const filters = (
    <div className={styles.filters}>
      <label htmlFor="person-mails-contact">Mit Kontakt</label>
      <select
        id="person-mails-contact"
        value={state.contact ?? ""}
        onChange={(event) =>
          onChange(
            withSelection(state, {
              contact: event.target.value ? Number(event.target.value) : null,
            }),
          )
        }
      >
        <option value="">Alle</option>
        {contacts.map((person) => (
          <option key={person.person_id} value={person.person_id}>
            {personLabel(person)}
          </option>
        ))}
        {otherContact !== null && <option value={otherContact}>Person #{otherContact}</option>}
      </select>
      <label htmlFor="person-mails-year">Jahr</label>
      <select
        id="person-mails-year"
        value={state.year ?? ""}
        onChange={(event) =>
          onChange(
            withSelection(state, { year: event.target.value ? Number(event.target.value) : null }),
          )
        }
      >
        <option value="">Alle</option>
        {[...profile.years].reverse().map(({ year }) => (
          <option key={year} value={year}>
            {year}
          </option>
        ))}
        {otherYear !== null && <option value={otherYear}>{otherYear}</option>}
      </select>
    </div>
  );

  const tabLabel = (id: MailTab) => {
    const count = counts?.[id];
    if (count === undefined) return TAB_LABELS[id];
    return `${TAB_LABELS[id]} ${count === null ? "–" : formatNumber(count)}`;
  };

  return (
    <Card className={styles.card} aria-label="Mails der Person">
      <div className={styles.bar}>
        <Tabs<MailTab>
          items={TABS.map((id) => ({ id, label: tabLabel(id) }))}
          active={tab}
          onSelect={(id) =>
            id !== tab && onChange(withSelection(state, { role: id === "all" ? null : id }))
          }
          idPrefix={TABS_ID}
          label="Rolle der Person"
          end={filters}
        />
      </div>
      <div {...tabPanelProps(TABS_ID, tab)}>
        {page.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Mails werden geladen" />
          </div>
        ) : page.isError ? (
          <PageError
            error={page.error}
            edges={edgePages(state, href)}
            onRetry={() => void page.refetch()}
          />
        ) : page.data.items.length === 0 ? (
          <EmptyState
            title="Keine Mails"
            actions={
              (narrowed || state.role) && (
                <Link
                  to={href({
                    ...state,
                    role: null,
                    year: null,
                    contact: null,
                    cursor: null,
                    page: 1,
                  })}
                  className={buttonClass()}
                >
                  Alle Mails der Person
                </Link>
              )
            }
          >
            Für diese Auswahl gibt es keine Mails.
          </EmptyState>
        ) : (
          <PersonMailTable
            items={page.data.items}
            detailSearch={listSearch(list).toString()}
            stale={page.isPlaceholderData}
          />
        )}
      </div>
      {page.data && page.data.items.length > 0 && (
        <div className={styles.paging}>
          <Pagination
            {...listPagination(
              state,
              page.data,
              page.data.items.length,
              total === null ? null : { count: total, exact: true },
              href,
            )}
          />
        </div>
      )}
    </Card>
  );
}

/** The other side of a mail: its first recipient when the person sent it, else the sender. */
function Counterpart({ mail }: { mail: MailListItem }) {
  if (mail.person_role === "from") {
    const [first] = mail.recipients;
    if (!first) return <span className={styles.muted}>–</span>;
    const rest = mail.recipient_count - 1;
    return (
      <>
        <PersonLink person={first} className={styles.person} />
        {rest > 0 && <span className={styles.muted}> +{formatNumber(rest)}</span>}
      </>
    );
  }
  return mail.sender ? (
    <PersonLink person={mail.sender} className={styles.person} />
  ) : (
    <span className={styles.muted}>(unbekannt)</span>
  );
}

function PersonMailTable({
  items,
  detailSearch,
  stale,
}: {
  items: MailListItem[];
  /** Query string the detail links carry, so Vorherige and Nächste walk this list. */
  detailSearch: string;
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
            <th className={styles.roleCol}>Rolle</th>
            <th>Gegenseite</th>
            <th>Betreff</th>
            <th className={styles.dateCol}>Datum</th>
          </tr>
        </thead>
        <tbody>
          {items.map((mail) => (
            <tr key={mail.id} onClick={(event) => openRow(event, mail.id)}>
              <td>
                <DkimDot status={dkimKey(mail.dkim_status)} />
              </td>
              <td>
                {mail.person_role ? (
                  <span className={cx(styles.role, mail.person_role === "from" && styles.from)}>
                    {ROLE_LABELS[mail.person_role]}
                  </span>
                ) : (
                  <span className={styles.muted}>–</span>
                )}
              </td>
              <td className={styles.counterpart}>
                <Counterpart mail={mail} />
              </td>
              <td className={styles.subject}>
                <Link
                  to={href(mail.id)}
                  className={cx(styles.subjectLink, !mail.subject && styles.muted)}
                >
                  {mail.subject || "(kein Betreff)"}
                </Link>
              </td>
              <td className={styles.date}>{mail.date ? formatDateTime(mail.date) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PageError({
  error,
  edges,
  onRetry,
}: {
  error: Error;
  edges: { first: string; last: string };
  onRetry: () => void;
}) {
  if (error instanceof ApiError && error.code === "page_too_far") return <PageTooFar {...edges} />;
  if (error instanceof ApiError && error.code === "invalid_cursor") {
    return (
      <ErrorState
        title="Diese Seite gibt es nicht mehr."
        actions={
          <Link to={edges.first} className={buttonClass()}>
            Zur ersten Seite
          </Link>
        }
      >
        Der Link verweist auf eine veraltete Seite der Liste.
      </ErrorState>
    );
  }
  return (
    <ErrorState
      title="Die Mails konnten nicht geladen werden."
      actions={<Button onClick={onRetry}>Erneut versuchen</Button>}
    >
      Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
    </ErrorState>
  );
}

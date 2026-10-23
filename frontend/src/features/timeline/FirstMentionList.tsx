import type { UseQueryResult } from "@tanstack/react-query";
import { useId } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import {
  FIRST_MENTIONS,
  MAX_FIRST_MENTIONS,
  type FirstMention,
  type FirstMentions,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { HelpMark } from "../../components/HelpMark";
import { personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDate, formatDateTime, formatNumber } from "../../lib/format";
import { personName } from "../../lib/person";
import { listSearch, withFilters } from "../mails/listState";
import styles from "./FirstMentionList.module.css";
import { KIND_LABELS, NO_SUBJECT, personsText, ROLE_LABELS } from "./labels";
import { mailListHref, withPerson, type TimelineState } from "./urlState";

/** The mail list of a person's matching mails, as its count (D94) counts them. */
function personMailsHref(state: TimelineState, mention: FirstMention): string {
  const list = withPerson(state.list, mention.person.person_id);
  const sent = state.role === "sent" && list.person.length === 1;
  return mailListHref(sent ? withFilters(list, { person_role: "sent" }) : list);
}

/** An error of the search or the filters themselves, not of the server. */
function unusable(error: Error): boolean {
  const code = error instanceof ApiError ? error.code : null;
  return code === "invalid_query" || code === "invalid_filter";
}

function totalText(data: FirstMentions): string {
  if (data.persons === null) return "";
  return data.persons > data.items.length
    ? `${formatNumber(data.items.length)} von ${personsText(data.persons)}`
    : personsText(data.persons);
}

/** "Wer taucht wann zuerst auf" (D94): per person the earliest matching mail, earliest first,
 *  with the toggles for senders only and lists, and "Mehr anzeigen" up to MAX_FIRST_MENTIONS. */
export function FirstMentionList({
  state,
  onChange,
  query,
  limit,
  onMore,
}: {
  state: TimelineState;
  onChange: (next: TimelineState) => void;
  query: UseQueryResult<FirstMentions>;
  limit: number;
  onMore: () => void;
}) {
  const titleId = useId();
  const data = query.data;
  const detailSearch = listSearch(state.list).toString();
  const more =
    data && data.persons !== null && data.persons > data.items.length && limit < MAX_FIRST_MENTIONS;

  return (
    <section className={styles.card} aria-labelledby={titleId}>
      <div className={styles.head}>
        <h2 id={titleId} className={styles.title}>
          Wer taucht wann zuerst auf
        </h2>
        <HelpMark text="Für jede Person die früheste Mail unter den Treffern, an der sie beteiligt ist: wann sie zum ersten Mal mit dieser Suche zu tun hatte, und mit wem." />
        {data && (
          <span className={styles.total} aria-live="polite">
            {totalText(data)}
          </span>
        )}
      </div>
      <div className={styles.toggles}>
        <Checkbox
          checked={state.role === "sent"}
          onChange={(on) => onChange({ ...state, role: on ? "sent" : "any" })}
        >
          Nur Absender
        </Checkbox>
        <Checkbox checked={state.lists} onChange={(lists) => onChange({ ...state, lists })}>
          Verteiler und Automaten einbeziehen
        </Checkbox>
      </div>

      {query.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Erste Erwähnungen werden geladen" />
        </div>
      ) : query.isError && unusable(query.error) ? (
        // The chart above names what it did not understand.
        <EmptyState title="Diese Suche lässt sich so nicht auswerten." />
      ) : query.isError ? (
        <ErrorState
          title="Die ersten Erwähnungen konnten nicht geladen werden."
          actions={<Button onClick={() => void query.refetch()}>Erneut versuchen</Button>}
        >
          Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
        </ErrorState>
      ) : query.data.timed_out ? (
        <EmptyState title="Die Suche hat zu lange gedauert.">
          Grenzen Sie die Suche ein, etwa mit einem Zeitraum.
        </EmptyState>
      ) : query.data.items.length === 0 ? (
        <EmptyState title="Keine Person gefunden">
          {state.role === "sent"
            ? "Keine der Treffer-Mails hat eine Person geschrieben, die hier zählt."
            : "Unter den Treffern ist keine Mail mit Beteiligten, die hier zählen."}
        </EmptyState>
      ) : (
        <>
          <div className={styles.scroll}>
            <table className={cx(styles.table, query.isPlaceholderData && styles.stale)}>
              <thead>
                <tr>
                  <th scope="col">Datum</th>
                  <th scope="col">Person</th>
                  <th scope="col">Rolle</th>
                  <th scope="col">Betreff</th>
                  <th scope="col" className={styles.num}>
                    Mails
                  </th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((mention) => (
                  <tr key={mention.person.person_id}>
                    <td className={styles.date} title={formatDateTime(mention.date)}>
                      {formatDate(mention.date)}
                    </td>
                    <td className={styles.person}>
                      <Link to={personPath(mention.person.person_id)} title={mention.person.email}>
                        {personName(mention.person)}
                      </Link>
                      {mention.kind && (
                        <span className={styles.kind}>{KIND_LABELS[mention.kind]}</span>
                      )}
                    </td>
                    <td className={styles.role}>{ROLE_LABELS[mention.role]}</td>
                    <td className={styles.subject}>
                      <Link
                        to={`/mails/${mention.mail_id}${detailSearch ? `?${detailSearch}` : ""}`}
                      >
                        {mention.subject || NO_SUBJECT}
                      </Link>
                    </td>
                    <td className={styles.num}>
                      <Link
                        to={personMailsHref(state, mention)}
                        aria-label={`${formatNumber(mention.mails)} Mails von ${personName(mention.person)} in der Mailliste`}
                      >
                        {formatNumber(mention.mails)}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {more && (
            <div className={styles.more}>
              <Button onClick={onMore} disabled={query.isPlaceholderData}>
                Mehr anzeigen
              </Button>
              <span className={styles.moreHint}>
                bis zu {formatNumber(Math.min(limit + FIRST_MENTIONS, MAX_FIRST_MENTIONS))} Personen
              </span>
            </div>
          )}
          {query.data.persons !== null &&
            query.data.persons > query.data.items.length &&
            limit >= MAX_FIRST_MENTIONS && (
              <p className={styles.moreHint}>
                Gezeigt werden die ersten {formatNumber(MAX_FIRST_MENTIONS)}. Grenzen Sie die Suche
                ein, um spätere zu sehen.
              </p>
            )}
        </>
      )}
    </section>
  );
}

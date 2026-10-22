import { useMemo, useState, type MouseEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useSelectorPage } from "../../api/queries";
import type { SelectorItem, SelectorPage } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { SearchIcon } from "../../components/icons";
import { KeyOriginBadge } from "../../components/KeyOriginBadge";
import { Pagination, type PaginationProps } from "../../components/Pagination";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { selectorPath } from "../../lib/dkim";
import { formatNumber } from "../../lib/format";
import { pageCount, rangeText } from "../../lib/paging";
import { DebouncedInput } from "../documents/DebouncedInput";
import { KeysRun, useKeysRun } from "./KeysRun";
import { dnsStatusLabel, periodText, SELECTOR_FILTER_LABELS, SELECTOR_FILTERS } from "./labels";
import styles from "./SelectorListPage.module.css";
import { StatusMix } from "./StatusMix";
import {
  parseSelectorListState,
  selectorListHref,
  selectorListSearch,
  toSelectorListParams,
  type SelectorListState,
} from "./urlState";

const selectorCount = (count: number) =>
  `${formatNumber(count)} ${count === 1 ? "Selektor" : "Selektoren"}`;

/** The key names whose signatures do not pass, most mails first (D100): open, resolved by a
 *  key from another source, or all; each row leads to the name's page. */
export function SelectorListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parseSelectorListState(searchParams), [searchParams]);
  const page = useSelectorPage(toSelectorListParams(state));
  const { job } = useKeysRun();
  const [notice, setNotice] = useState<string | null>(null);

  const setState = (next: SelectorListState) =>
    setSearchParams(selectorListSearch(next), { preventScrollReset: true });
  // Typing replaces the entry instead of adding one per pause; the latest URL is the base, as
  // the timer fires after the render that started it.
  const search = (q: string) =>
    setSearchParams(
      (current) => selectorListSearch({ ...parseSelectorListState(current), q, page: 1 }),
      { replace: true, preventScrollReset: true },
    );

  return (
    <main className={styles.page}>
      <title>Gelöschte Selektoren · Mailrobbe</title>
      <nav aria-label="Pfad" className={styles.breadcrumb}>
        <Link to="/import">Import</Link>
        <span aria-hidden="true">›</span>
        <span>Gelöschte Selektoren</span>
      </nav>
      <div className={styles.head}>
        <h1 className={styles.title}>Gelöschte Selektoren</h1>
        {page.data && (
          <span className={styles.total} aria-live="polite">
            {state.q
              ? `${selectorCount(page.data.total)} gefunden`
              : selectorCount(page.data.total)}
          </span>
        )}
      </div>
      <p className={styles.lead}>
        Schlüsselnamen (Selektor und Domain), deren Signaturen keinen Schlüssel im DNS mehr finden
        oder nicht zum heutigen Schlüssel passen. Ein Selektor ist geklärt, sobald ein Schlüssel aus
        einer anderen Quelle seine Signaturen bestätigt.
      </p>
      <KeysRun job={job} ended={false} onError={setNotice} />
      {notice && (
        <p className={styles.error} role="alert">
          {notice}
        </p>
      )}

      <div className={styles.toolbar}>
        <div role="group" aria-label="Anzeigen" className={styles.segments}>
          {SELECTOR_FILTERS.map((show) => (
            <button
              key={show}
              type="button"
              aria-pressed={state.show === show}
              className={cx(styles.segment, state.show === show && styles.active)}
              onClick={() => setState({ ...state, show, page: 1 })}
            >
              {SELECTOR_FILTER_LABELS[show]}
            </button>
          ))}
        </div>
        <div className={styles.search}>
          <SearchIcon className={styles.searchIcon} />
          <label htmlFor="selector-search" className="sr-only">
            Selektor suchen
          </label>
          <DebouncedInput
            id="selector-search"
            type="search"
            className={styles.searchInput}
            placeholder="Selektor oder Domain, auch Teil davon …"
            value={state.q}
            onCommit={search}
          />
        </div>
      </div>

      <Card className={styles.tableCard}>
        {page.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Selektoren werden geladen" />
          </div>
        ) : page.isError ? (
          <ErrorState
            title="Die Selektoren konnten nicht geladen werden."
            actions={<Button onClick={() => void page.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        ) : page.data.items.length === 0 ? (
          <EmptyList state={state} total={page.data.total} />
        ) : (
          <SelectorTable items={page.data.items} stale={page.isPlaceholderData} />
        )}
      </Card>

      {page.data && page.data.items.length > 0 && (
        <Pagination {...selectorPagination(state, page.data)} />
      )}
    </main>
  );
}

/** The list pages by offset and knows its total, so every page has its number (D193). */
function selectorPagination(state: SelectorListState, page: SelectorPage): PaginationProps {
  const total = { count: page.total, exact: true };
  const { pages } = pageCount(total, state.limit);
  const at = (number: number) => selectorListHref({ ...state, page: number });
  return {
    range: rangeText(state.page, false, state.limit, page.items.length, total),
    prev: state.page > 1 ? at(state.page - 1) : null,
    next: state.page < pages ? at(state.page + 1) : null,
    first: state.page > 1 ? at(1) : null,
    last: state.page < pages ? at(pages) : null,
    numbers: { current: state.page, pages, more: false, href: at },
    size: { limit: state.limit, href: (limit) => selectorListHref({ ...state, page: 1, limit }) },
  };
}

function EmptyList({ state, total }: { state: SelectorListState; total: number }) {
  if (state.page > 1 && total > 0) {
    return (
      <EmptyState
        title="Diese Seite gibt es nicht mehr."
        actions={
          <Link to={selectorListHref({ ...state, page: 1 })} className={buttonClass()}>
            Zur ersten Seite
          </Link>
        }
      />
    );
  }
  if (state.q) {
    return (
      <EmptyState
        title="Kein Selektor gefunden"
        actions={
          <Link to={selectorListHref({ ...state, q: "", page: 1 })} className={buttonClass()}>
            Suche leeren
          </Link>
        }
      >
        {`Kein Schlüsselname enthält „${state.q}“.`}
      </EmptyState>
    );
  }
  if (state.show === "open") {
    return (
      <EmptyState title="Kein offener Selektor">
        Jede geprüfte Signatur hat einen Schlüssel, oder es wurde noch keine Mail geprüft.
      </EmptyState>
    );
  }
  if (state.show === "resolved") {
    return (
      <EmptyState title="Noch kein Selektor geklärt">
        Geklärt ist ein Selektor, sobald ein rekonstruierter, im Archiv gefundener oder von Hand
        eingetragener Schlüssel seine Signaturen bestätigt.
      </EmptyState>
    );
  }
  return <EmptyState title="Noch keine signierten Mails" />;
}

function SelectorTable({ items, stale }: { items: SelectorItem[]; stale: boolean }) {
  const navigate = useNavigate();

  function openRow(event: MouseEvent<HTMLTableRowElement>, name: string) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, label") || window.getSelection()?.toString()) return;
    void navigate(selectorPath(name));
  }

  return (
    <div className={styles.scroll}>
      <table className={cx(styles.table, stale && styles.stale)}>
        <thead>
          <tr>
            <th>Selektor</th>
            <th className={styles.num}>Signaturen</th>
            <th className={styles.num}>Mails</th>
            <th>Status</th>
            <th className={styles.num} title="Verschiedene RSA-Signaturen; ab zwei rekonstruierbar">
              RSA
            </th>
            <th>Zeitraum</th>
            <th>Schlüssel</th>
            <th>DNS heute</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.name} onClick={(event) => openRow(event, item.name)}>
              <td>
                <Link
                  to={selectorPath(item.name)}
                  className={styles.name}
                  aria-label={item.name}
                  title={item.name}
                >
                  <span className={styles.selector}>{item.selector}</span>
                  <span className={styles.domain}>{item.domain}</span>
                </Link>
              </td>
              <td className={styles.num}>{formatNumber(item.signatures)}</td>
              <td className={cx(styles.num, styles.strong)}>{formatNumber(item.mails)}</td>
              <td>
                <StatusMix statuses={item.statuses} />
              </td>
              <td className={styles.num}>{formatNumber(item.rsa_signatures)}</td>
              <td className={styles.muted}>{periodText(item.first_signed, item.last_signed)}</td>
              <td>
                {item.keys === 0 || item.best_origin === null ? (
                  <span className={styles.muted}>–</span>
                ) : (
                  <span className={styles.keys}>
                    {formatNumber(item.keys)}
                    <KeyOriginBadge origin={item.best_origin} />
                  </span>
                )}
              </td>
              <td className={styles.muted}>{dnsStatusLabel(item.dns_status)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

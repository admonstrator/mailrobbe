import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { useDocumentPage, useDocumentSummary, useStats } from "../../api/queries";
import type { DocumentSort, DocumentSummary } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { SearchIcon } from "../../components/icons";
import { PageTooFar, Pagination } from "../../components/Pagination";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { edgePages, listPagination, type Total } from "../../lib/paging";
import { DebouncedInput } from "./DebouncedInput";
import { DocumentFilterColumn } from "./DocumentFilterColumn";
import styles from "./DocumentListPage.module.css";
import { DocumentTable } from "./DocumentTable";
import { highlightTerms } from "../../lib/highlight";
import { useBarHeight } from "../mails/useBarHeight";
import { SORT_LABELS } from "./labels";
import {
  documentListHref,
  documentListSearch,
  facetFilters,
  hasDocumentFilters,
  parseDocumentListState,
  toDocumentFilters,
  toDocumentListParams,
  withDocumentFilters,
  type DocumentFilterPatch,
  type DocumentListState,
} from "./urlState";

/** "78.110", "mehr als 10.000" (a lower bound, D19), or null while unknown. */
function totalNumber(summary: DocumentSummary | undefined): string | null {
  if (!summary || summary.total === null) return null;
  return summary.exact ? formatNumber(summary.total) : `mehr als ${formatNumber(summary.total)}`;
}

function totalText(summary: DocumentSummary | undefined, filtered: boolean): string {
  if (summary && summary.total === null) return "Anzahl unbekannt";
  const total = totalNumber(summary);
  if (total === null) return "";
  const noun = summary?.total === 1 && summary.exact ? "Dokument" : "Dokumente";
  return filtered ? `${total} ${noun} gefunden` : `${total} ${noun}`;
}

/** The document list "Anhänge" (D74): filters, search, sort, one page of documents. */
export function DocumentListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parseDocumentListState(searchParams), [searchParams]);
  const filters = toDocumentFilters(state);
  const stats = useStats();
  const page = useDocumentPage(toDocumentListParams(state));
  const summary = useDocumentSummary(filters);
  const kinds = useDocumentSummary(facetFilters(filters, "kind"));
  const statuses = useDocumentSummary(facetFilters(filters, "text_status"));
  const authors = useDocumentSummary(facetFilters(filters, "author"));
  const programs = useDocumentSummary(facetFilters(filters, "program"));
  const terms = useMemo(() => highlightTerms(state.q), [state.q]);
  const bar = useBarHeight<HTMLDivElement>();

  const setState = (next: DocumentListState) =>
    setSearchParams(documentListSearch(next), { preventScrollReset: true });
  // Typing replaces the entry instead of adding one per pause; the latest URL is the base, as
  // the timer fires after the render that started it.
  const typed = (patch: DocumentFilterPatch) =>
    setSearchParams(
      (current) => documentListSearch(withDocumentFilters(parseDocumentListState(current), patch)),
      { replace: true, preventScrollReset: true },
    );

  return (
    <div className={styles.layout}>
      <title>Anhänge · Mailrobbe</title>
      <DocumentFilterColumn
        state={state}
        onChange={setState}
        onName={(name) => typed({ name })}
        kinds={kinds.data}
        statuses={statuses.data}
        authors={authors.data}
        programs={programs.data}
        stats={stats.data}
      />
      <main className={styles.main}>
        {/* Title, count, search and sort in one row that stays above the table while it
            scrolls. */}
        <div ref={bar} className={styles.listBar}>
          <div className={styles.head}>
            <h1 className={styles.title}>Anhänge</h1>
            <span className={styles.total} aria-live="polite">
              {totalText(summary.data, hasDocumentFilters(state))}
            </span>
          </div>

          <div className={styles.toolbar}>
            <div className={styles.search}>
              <SearchIcon className={styles.searchIcon} />
              <label htmlFor="document-search" className="sr-only">
                Anhänge durchsuchen
              </label>
              <DebouncedInput
                id="document-search"
                type="search"
                className={styles.searchInput}
                placeholder="Text und Dateinamen der Anhänge durchsuchen …"
                value={state.q}
                onCommit={(q) => typed({ q })}
              />
            </div>
            <label htmlFor="document-sort" className={styles.sortLabel}>
              Sortierung
            </label>
            <select
              id="document-sort"
              className={styles.sort}
              value={state.sort}
              onChange={(event) =>
                setState(withDocumentFilters(state, { sort: event.target.value as DocumentSort }))
              }
            >
              {Object.entries(SORT_LABELS).map(([sort, label]) => (
                <option key={sort} value={sort}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <Card className={styles.tableCard}>
          {page.isPending ? (
            <div className={styles.loading}>
              <Spinner label="Anhänge werden geladen" />
            </div>
          ) : page.isError ? (
            <PageError error={page.error} state={state} onRetry={() => void page.refetch()} />
          ) : page.data.items.length === 0 ? (
            hasDocumentFilters(state) ? (
              <EmptyState
                title="Kein Dokument gefunden"
                actions={
                  <Link to="/anhaenge" className={buttonClass()}>
                    Alle Filter zurücksetzen
                  </Link>
                }
              >
                {state.q
                  ? "Kein Anhang passt zu dieser Suche und diesen Filtern. Gescannte PDFs ohne Textebene findet die Volltextsuche nicht."
                  : "Kein Anhang passt zu diesen Filtern."}
              </EmptyState>
            ) : (
              <EmptyState title="Noch keine Anhänge">
                Dokumente erscheinen, sobald ein Import die Anhänge der Mails ausgewertet hat.
              </EmptyState>
            )
          ) : (
            <DocumentTable items={page.data.items} terms={terms} stale={page.isPlaceholderData} />
          )}
        </Card>

        {page.data && page.data.items.length > 0 && (
          <Pagination
            {...listPagination(
              state,
              page.data,
              page.data.items.length,
              documentTotal(summary.data),
              documentListHref,
            )}
          />
        )}
      </main>
    </div>
  );
}

/** The list's length as DocumentSummary counts it, for the page numbers (D193). */
function documentTotal(summary: DocumentSummary | undefined): Total | null {
  return summary && summary.total !== null ? { count: summary.total, exact: summary.exact } : null;
}

function PageError({
  error,
  state,
  onRetry,
}: {
  error: Error;
  state: DocumentListState;
  onRetry: () => void;
}) {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "page_too_far") return <PageTooFar {...edgePages(state, documentListHref)} />;
  if (code === "invalid_cursor") {
    return (
      <ErrorState
        title="Diese Seite gibt es nicht mehr."
        actions={
          <Link
            to={documentListHref({ ...state, cursor: null, page: 1 })}
            className={buttonClass()}
          >
            Zur ersten Seite
          </Link>
        }
      >
        Der Link verweist auf eine Seite einer anderen Sortierung oder ist veraltet.
      </ErrorState>
    );
  }
  if (code === "invalid_filter" || code === "invalid_query") {
    return (
      <ErrorState
        title="Diese Filter lassen sich nicht anwenden."
        actions={
          <Link to="/anhaenge" className={buttonClass()}>
            Filter zurücksetzen
          </Link>
        }
      >
        Die Adresse enthält eine Filterkombination, die Mailrobbe nicht auswerten kann.
      </ErrorState>
    );
  }
  return (
    <ErrorState
      title="Die Anhänge konnten nicht geladen werden."
      actions={<Button onClick={onRetry}>Erneut versuchen</Button>}
    >
      Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
    </ErrorState>
  );
}

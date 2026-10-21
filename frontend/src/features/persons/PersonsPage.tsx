import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { Link, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { usePersonPage, useSuggestions } from "../../api/queries";
import { PAGE_SIZE, type PersonPage, type PersonSort } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { SearchIcon } from "../../components/icons";
import { Pagination } from "../../components/Pagination";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { formatNumber } from "../../lib/format";
import { MergeLog } from "./MergeLog";
import { PersonTable } from "./PersonTable";
import styles from "./PersonsPage.module.css";
import { SuggestionList } from "./SuggestionList";
import {
  parsePersonListState,
  personListSearch,
  toPersonListParams,
  type PersonListState,
  type PersonsTab,
} from "./urlState";

const SEARCH_DELAY = 300;
const TABS_ID = "persons";

const SORT_LABELS: Record<PersonSort, string> = {
  mails: "Mails",
  name: "Name",
  recent: "Letzte Mail",
};

const listHref = (state: PersonListState) => {
  const search = personListSearch(state).toString();
  return search ? `/personen?${search}` : "/personen";
};

const TITLES: Record<PersonsTab, string> = {
  personen: "Personen · Mailrobbe",
  vorschlaege: "Alias-Vorschläge · Mailrobbe",
  zusammengefuehrt: "Zuletzt zusammengeführt · Mailrobbe",
};

/** The person list (D31), the open alias suggestions (D30, D160) and the merge log (D163),
 *  one tab each. */
export function PersonsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parsePersonListState(searchParams), [searchParams]);
  const page = usePersonPage(toPersonListParams(state));
  const suggestions = useSuggestions("certain");
  const certainTotal = suggestions.data?.pages[0]?.counts.certain;

  const setState = (next: PersonListState) =>
    setSearchParams(personListSearch(next), { preventScrollReset: true });
  // Typing replaces the entry instead of adding one per pause; the latest URL is the base, as
  // the timer fires after the render that started it.
  const search = (q: string) =>
    setSearchParams(
      (current) => personListSearch({ ...parsePersonListState(current), q, cursor: null, page: 1 }),
      { replace: true, preventScrollReset: true },
    );

  const tabs: TabItem<PersonsTab>[] = [
    { id: "personen", label: "Personen" },
    {
      id: "vorschlaege",
      label:
        certainTotal === undefined
          ? "Alias-Vorschläge"
          : `Alias-Vorschläge (${formatNumber(certainTotal)} sicher)`,
    },
    { id: "zusammengefuehrt", label: "Zuletzt zusammengeführt" },
  ];

  return (
    <main className={styles.page}>
      <title>{TITLES[state.tab]}</title>
      <div className={styles.head}>
        <h1 className={styles.title}>Personen</h1>
        {page.data && (
          <span className={styles.total} aria-live="polite">
            {state.q
              ? `${formatNumber(page.data.total)} ${page.data.total === 1 ? "Person" : "Personen"} gefunden`
              : `${formatNumber(page.data.total)} Personen`}
          </span>
        )}
      </div>

      <Tabs<PersonsTab>
        items={tabs}
        active={state.tab}
        onSelect={(tab) => setState({ ...state, tab })}
        idPrefix={TABS_ID}
        label="Personen, Alias-Vorschläge und Zusammenführungen"
      />

      <div {...tabPanelProps(TABS_ID, state.tab)} className={styles.panel}>
        {state.tab === "vorschlaege" ? (
          <SuggestionList
            uncertain={state.uncertain}
            onUncertain={(uncertain) => setState({ ...state, uncertain })}
            hasPersons={(page.data?.total ?? 0) > 0}
          />
        ) : state.tab === "zusammengefuehrt" ? (
          <MergeLog />
        ) : (
          <>
            <div className={styles.toolbar}>
              <PersonSearch value={state.q} onSearch={search} />
              <label htmlFor="person-sort" className={styles.sortLabel}>
                Sortierung
              </label>
              <select
                id="person-sort"
                className={styles.sort}
                value={state.sort}
                onChange={(event) =>
                  setState({
                    ...state,
                    sort: event.target.value as PersonSort,
                    cursor: null,
                    page: 1,
                  })
                }
              >
                {Object.entries(SORT_LABELS).map(([sort, label]) => (
                  <option key={sort} value={sort}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <PersonList page={page} state={state} />
          </>
        )}
      </div>
    </main>
  );
}

/** The search field: the list follows after a short pause in typing. */
function PersonSearch({ value, onSearch }: { value: string; onSearch: (q: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // The URL changed elsewhere (back, a link): show its search.
  useEffect(() => {
    if (input.current && input.current.value.trim() !== value) input.current.value = value;
  }, [value]);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <div className={styles.search}>
      <SearchIcon className={styles.searchIcon} />
      <label htmlFor="person-search" className="sr-only">
        Person suchen
      </label>
      <input
        ref={input}
        id="person-search"
        type="search"
        defaultValue={value}
        placeholder="Name oder Adresse, auch Teil davon …"
        autoComplete="off"
        spellCheck={false}
        className={styles.searchInput}
        onChange={(event) => {
          const q = event.target.value.trim();
          clearTimeout(timer.current);
          timer.current = setTimeout(() => onSearch(q), SEARCH_DELAY);
        }}
      />
    </div>
  );
}

function PersonList({ page, state }: { page: UseQueryResult<PersonPage>; state: PersonListState }) {
  return (
    <>
      <Card className={styles.tableCard}>
        {page.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Personen werden geladen" />
          </div>
        ) : page.isError ? (
          <PageError error={page.error} state={state} onRetry={() => void page.refetch()} />
        ) : page.data.items.length === 0 ? (
          state.q ? (
            <EmptyState
              title="Keine Person gefunden"
              actions={
                <Link
                  to={listHref({ ...state, q: "", cursor: null, page: 1 })}
                  className={buttonClass()}
                >
                  Suche leeren
                </Link>
              }
            >
              {`Kein Name und keine Adresse enthält „${state.q}“.`}
            </EmptyState>
          ) : (
            <EmptyState title="Noch keine Personen">
              Personen erscheinen, sobald ein Import ihre Mails ausgewertet hat.
            </EmptyState>
          )
        ) : (
          <PersonTable items={page.data.items} stale={page.isPlaceholderData} />
        )}
      </Card>
      {page.data && page.data.items.length > 0 && (
        <Pagination
          range={rangeText(state, page.data)}
          prev={page.data.prev_cursor ? listHref(previousPage(state, page.data.prev_cursor)) : null}
          next={
            page.data.next_cursor
              ? listHref({ ...state, cursor: page.data.next_cursor, page: state.page + 1 })
              : null
          }
        />
      )}
    </>
  );
}

function previousPage(state: PersonListState, cursor: string): PersonListState {
  // The page before the second one is the first: without cursor, as the list starts.
  return state.page === 2
    ? { ...state, cursor: null, page: 1 }
    : { ...state, cursor, page: Math.max(1, state.page - 1) };
}

/** "1–50 von 1.710" */
function rangeText(state: PersonListState, page: PersonPage): string {
  const first = (state.page - 1) * PAGE_SIZE + 1;
  const last = first + page.items.length - 1;
  return `${formatNumber(first)}–${formatNumber(last)} von ${formatNumber(page.total)}`;
}

function PageError({
  error,
  state,
  onRetry,
}: {
  error: Error;
  state: PersonListState;
  onRetry: () => void;
}) {
  if (error instanceof ApiError && error.code === "invalid_cursor") {
    return (
      <ErrorState
        title="Diese Seite gibt es nicht mehr."
        actions={
          <Link to={listHref({ ...state, cursor: null, page: 1 })} className={buttonClass()}>
            Zur ersten Seite
          </Link>
        }
      >
        Der Link verweist auf eine Seite einer anderen Sortierung oder ist veraltet.
      </ErrorState>
    );
  }
  return (
    <ErrorState
      title="Die Personen konnten nicht geladen werden."
      actions={<Button onClick={onRetry}>Erneut versuchen</Button>}
    >
      Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
    </ErrorState>
  );
}

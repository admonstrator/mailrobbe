import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { Link, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { usePersonPage, useSuggestions } from "../../api/queries";
import type { PersonPage, PersonSort } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { SearchIcon } from "../../components/icons";
import { PageTooFar, Pagination } from "../../components/Pagination";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { edgePages, listPagination } from "../../lib/paging";
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
  mails: "Meiste Mails",
  name: "Name",
  recent: "Letzte Mail",
};

const listHref = (state: PersonListState) => {
  const search = personListSearch(state).toString();
  return search ? `/personen?${search}` : "/personen";
};

const TITLES: Record<PersonsTab, string> = {
  personen: "Personen · Mailrobbe",
  vorschlaege: "Zusammenführen · Mailrobbe",
  zusammengefuehrt: "Zusammengeführt · Mailrobbe",
};

/** The person list (D31), the open alias suggestions (D30, D160) and the merge log (D163),
 *  one tab each (D336): the title with the count, the tabs, then the tab's content. */
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
    { id: "personen", label: "Alle" },
    {
      id: "vorschlaege",
      label:
        certainTotal === undefined
          ? "Zusammenführen"
          : `Zusammenführen ${formatNumber(certainTotal)} sicher`,
      title: "Vorschläge, welche Adressen zu einer Person gehören",
    },
    { id: "zusammengefuehrt", label: "Zusammengeführt", title: "Zuletzt zusammengeführt" },
  ];

  return (
    <div className={styles.page}>
      <title>{TITLES[state.tab]}</title>
      <div className={styles.head}>
        <h1 className={styles.title}>Personen</h1>
        {page.data && (
          <span className={styles.total} aria-live="polite">
            {state.q || state.labelled
              ? `${formatNumber(page.data.total)} ${page.data.total === 1 ? "Person" : "Personen"} gefunden`
              : `${formatNumber(page.data.total)} Personen`}
          </span>
        )}
      </div>
      <div className={styles.tabs}>
        <Tabs<PersonsTab>
          items={tabs}
          active={state.tab}
          onSelect={(tab) => setState({ ...state, tab })}
          idPrefix={TABS_ID}
          label="Personen, Alias-Vorschläge und Zusammenführungen"
        />
      </div>

      <div {...tabPanelProps(TABS_ID, state.tab)} className={styles.panel}>
        {state.tab === "vorschlaege" ? (
          <SuggestionList
            view={state.suggestions}
            onView={(suggestions) => setState({ ...state, suggestions })}
            hasPersons={(page.data?.total ?? 0) > 0}
          />
        ) : state.tab === "zusammengefuehrt" ? (
          <MergeLog />
        ) : (
          <>
            <div className={styles.toolbar}>
              <PersonSearch value={state.q} onSearch={search} />
              <button
                type="button"
                aria-pressed={state.labelled}
                className={cx(styles.toggle, state.labelled && styles.toggleOn)}
                title="Nur Personen, die das Team benannt hat"
                onClick={() =>
                  setState({ ...state, labelled: !state.labelled, cursor: null, page: 1 })
                }
              >
                Nur benannte
              </button>
              <label htmlFor="person-sort" className={styles.sortLabel}>
                Sortiert nach
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
    </div>
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
        placeholder="Name oder Adresse"
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
      <div className={styles.tableCard}>
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
          ) : state.labelled ? (
            <EmptyState
              title="Noch keine Person benannt"
              actions={
                <Link
                  to={listHref({ ...state, labelled: false, cursor: null, page: 1 })}
                  className={buttonClass()}
                >
                  Alle Personen zeigen
                </Link>
              }
            >
              Klarname und Rolle vergibt das Team im Profil einer Person mit „Benennen“.
            </EmptyState>
          ) : (
            <EmptyState title="Noch keine Personen">
              Personen erscheinen, sobald ein Import ihre Mails ausgewertet hat.
            </EmptyState>
          )
        ) : (
          <PersonTable items={page.data.items} stale={page.isPlaceholderData} />
        )}
      </div>
      {page.data && page.data.items.length > 0 && (
        <Pagination
          {...listPagination(
            state,
            page.data,
            page.data.items.length,
            { count: page.data.total, exact: true },
            listHref,
          )}
        />
      )}
    </>
  );
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
  if (error instanceof ApiError && error.code === "page_too_far") {
    return <PageTooFar {...edgePages(state, listHref)} />;
  }
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

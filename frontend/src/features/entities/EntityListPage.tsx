import { useEffect, useMemo, useRef } from "react";
import { Link, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { useEntityPage, useEntitySummary, useThemes } from "../../api/queries";
import type { EntityPage, EntitySort, EntitySummary } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { HelpMark } from "../../components/HelpMark";
import { SearchIcon } from "../../components/icons";
import { PageTooFar, Pagination } from "../../components/Pagination";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { formatNumber } from "../../lib/format";
import { edgePages, listPagination, type Total } from "../../lib/paging";
import { DebouncedInput } from "../documents/DebouncedInput";
import { parseAmount } from "./amount";
import styles from "./EntityListPage.module.css";
import { EntityTable } from "./EntityTable";
import {
  ENTITY_GROUPS,
  ENTITY_KINDS,
  GROUP_KINDS,
  GROUP_LABELS,
  KIND_LABELS,
  waitingText,
} from "./labels";
import {
  DEFAULT_ENTITY_LIST_STATE,
  entityListHref,
  entityListSearch,
  hasEntityFilters,
  parseEntityListState,
  toEntityListParams,
  withEntityFilters,
  type EntityListPatch,
  type EntityListState,
  type EntityTab,
} from "./urlState";

const TABS_ID = "entities";

const SORT_LABELS: Record<EntitySort, string> = {
  mails: "Meiste Mails",
  recent: "Zuletzt erwähnt",
  oldest: "Zuerst erwähnt",
  value: "Betrag",
  label: "Name",
};

/** Entities of a tab by the summary; undefined while it loads. */
function tabCount(summary: EntitySummary | undefined, tab: EntityTab): number | undefined {
  if (!summary) return undefined;
  const kinds = tab === "all" ? ENTITY_KINDS : GROUP_KINDS[tab];
  return kinds.reduce((sum, kind) => sum + (summary.kinds[kind] ?? 0), 0);
}

/** The entity list (D88): a tab per kind group, a search over the labels, sorts, a value range
 *  for amounts, one page of entities. */
export function EntityListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parseEntityListState(searchParams), [searchParams]);
  const summary = useEntitySummary();
  const page = useEntityPage(toEntityListParams(state));
  const themes = useThemes();

  // The latest URL is the base, not this render's state: the search field's timer fires after
  // the render that started it, and a change right after typing must keep what was typed.
  const update = (patch: EntityListPatch, replace: boolean) =>
    setSearchParams(
      (current) => entityListSearch(withEntityFilters(parseEntityListState(current), patch)),
      { replace, preventScrollReset: true },
    );
  // Typing replaces the entry instead of adding one per pause.
  const typed = (patch: EntityListPatch) => update(patch, true);
  const change = (patch: EntityListPatch) => update(patch, false);

  const tabs: TabItem<EntityTab>[] = (["all", ...ENTITY_GROUPS] as const).map((tab) => {
    const label = tab === "all" ? "Alle" : GROUP_LABELS[tab];
    const count = tabCount(summary.data, tab);
    return { id: tab, label: count === undefined ? label : `${label} ${formatNumber(count)}` };
  });
  const total = tabCount(summary.data, "all");
  const waiting =
    summary.data && waitingText(summary.data.mails_waiting, summary.data.documents_waiting);
  const sorts = (Object.keys(SORT_LABELS) as EntitySort[]).filter(
    (sort) => sort !== "value" || state.tab === "amount",
  );

  return (
    <div className={styles.page}>
      <title>Entitäten · Mailrobbe</title>
      <div className={styles.head}>
        <h1 className={styles.title}>Entitäten</h1>
        <span className={styles.total}>
          {total !== undefined && `${formatNumber(total)} erkannt in Mails und Anhängen`}
          <HelpMark text="Was in Mails und Anhängen erwähnt wird: Beträge, Konten, Organisationen, Namen, Orte, Kontaktdaten, Daten und die Begriffe der Recherchethemen. Jede Zeile führt zu den Mails, die sie erwähnen." />
        </span>
      </div>
      {waiting && (
        <p className={styles.notice}>
          {waiting} <Link to="/import">Zum Import</Link>
        </p>
      )}

      <Tabs<EntityTab>
        items={tabs}
        active={state.tab}
        onSelect={(tab) => tab !== state.tab && change({ tab })}
        idPrefix={TABS_ID}
        label="Arten"
      />

      <div {...tabPanelProps(TABS_ID, state.tab)} className={styles.panel}>
        <div className={styles.toolbar}>
          <div className={styles.search}>
            <SearchIcon className={styles.searchIcon} />
            <label htmlFor="entity-search" className="sr-only">
              Entitäten durchsuchen
            </label>
            <DebouncedInput
              id="entity-search"
              type="search"
              className={styles.searchInput}
              placeholder="Name, Betrag, Nummer oder Adresse, auch Teil davon …"
              value={state.q}
              onCommit={(q) => typed({ q })}
            />
          </div>
          {state.tab === "term" && themes.data && (
            <>
              <label htmlFor="entity-theme" className="sr-only">
                Thema
              </label>
              <select
                id="entity-theme"
                className={styles.select}
                value={state.detail ?? ""}
                onChange={(event) => change({ detail: event.target.value || null })}
              >
                <option value="">Alle Themen</option>
                {themes.data.map((theme) => (
                  <option key={theme.key} value={theme.key}>
                    {theme.name}
                  </option>
                ))}
              </select>
            </>
          )}
          {state.tab === "amount" && (
            <div className={styles.range} role="group" aria-label="Betrag">
              <AmountField
                id="entity-value-min"
                label="von"
                value={state.value_min}
                onCommit={(value_min) => change({ value_min })}
              />
              <AmountField
                id="entity-value-max"
                label="bis"
                value={state.value_max}
                onCommit={(value_max) => change({ value_max })}
              />
            </div>
          )}
          <label htmlFor="entity-sort" className={styles.sortLabel}>
            Sortierung
          </label>
          <select
            id="entity-sort"
            className={styles.select}
            value={state.sort}
            onChange={(event) => change({ sort: event.target.value as EntitySort })}
          >
            {sorts.map((sort) => (
              <option key={sort} value={sort}>
                {SORT_LABELS[sort]}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.tableCard}>
          {page.isPending ? (
            <div className={styles.loading}>
              <Spinner label="Entitäten werden geladen" />
            </div>
          ) : page.isError ? (
            <PageError error={page.error} state={state} onRetry={() => void page.refetch()} />
          ) : page.data.items.length === 0 ? (
            <Empty state={state} total={total} />
          ) : (
            <EntityTable
              items={page.data.items}
              themes={themes.data}
              showKind={state.tab === "all"}
              stale={page.isPlaceholderData}
            />
          )}
        </div>

        {page.data && page.data.items.length > 0 && (
          <Pagination
            {...listPagination(
              state,
              page.data,
              page.data.items.length,
              entityTotal(state, page.data, summary.data),
              entityListHref,
            )}
          />
        )}
      </div>
    </div>
  );
}

/** An amount typed in German notation; it counts on Enter or when the field is left. */
function AmountField({
  id,
  label,
  value,
  onCommit,
}: {
  id: string;
  label: string;
  value: number | null;
  onCommit: (value: number | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const shown = value === null ? "" : formatNumber(value);

  useEffect(() => {
    if (input.current && document.activeElement !== input.current) input.current.value = shown;
  }, [shown]);

  function commit(field: HTMLInputElement) {
    const next = parseAmount(field.value);
    if (next === undefined) {
      field.value = shown; // not an amount: the range stays as it is
      return;
    }
    field.value = next === null ? "" : formatNumber(next);
    if (next !== value) onCommit(next);
  }

  return (
    <span className={styles.amount}>
      <label htmlFor={id} className={styles.amountLabel}>
        {label}
      </label>
      <input
        ref={input}
        id={id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        className={styles.amountInput}
        defaultValue={shown}
        placeholder="Betrag"
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          commit(event.currentTarget);
        }}
        onBlur={(event) => commit(event.currentTarget)}
      />
    </span>
  );
}

function Empty({ state, total }: { state: EntityListState; total: number | undefined }) {
  if (hasEntityFilters(state)) {
    return (
      <EmptyState
        title="Keine Entität gefunden"
        actions={
          <Link
            to={entityListHref({ ...DEFAULT_ENTITY_LIST_STATE, tab: state.tab, sort: state.sort })}
            className={buttonClass()}
          >
            Filter zurücksetzen
          </Link>
        }
      >
        {state.q
          ? `Keine Entität dieser Art enthält „${state.q}“.`
          : "Keine Entität dieser Art passt zu diesen Filtern."}
      </EmptyState>
    );
  }
  if (state.tab !== "all" && total !== 0) {
    const names = GROUP_KINDS[state.tab].map((kind) => KIND_LABELS[kind].many);
    return (
      <EmptyState title={`Keine ${names.join(" und ")} erkannt`}>
        In den bisher ausgewerteten Mails und Anhängen kommt diese Art nicht vor.
      </EmptyState>
    );
  }
  return (
    <EmptyState title="Noch keine Entitäten">
      Entitäten erscheinen, sobald ein Import die Texte der Mails und Anhänge ausgewertet hat.
    </EmptyState>
  );
}

/** The list's length (D193): counted with the page under a search, a theme or a value range,
 *  else the tab's count in the summary. */
function entityTotal(
  state: EntityListState,
  page: EntityPage,
  summary: EntitySummary | undefined,
): Total | null {
  if (hasEntityFilters(state)) {
    return page.total === null || page.total === undefined
      ? null
      : { count: page.total, exact: page.exact ?? false };
  }
  const count = tabCount(summary, state.tab);
  return count === undefined ? null : { count, exact: true };
}

function PageError({
  error,
  state,
  onRetry,
}: {
  error: Error;
  state: EntityListState;
  onRetry: () => void;
}) {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "page_too_far") return <PageTooFar {...edgePages(state, entityListHref)} />;
  if (code === "invalid_cursor") {
    return (
      <ErrorState
        title="Diese Seite gibt es nicht mehr."
        actions={
          <Link to={entityListHref({ ...state, cursor: null, page: 1 })} className={buttonClass()}>
            Zur ersten Seite
          </Link>
        }
      >
        Der Link verweist auf eine Seite einer anderen Sortierung oder ist veraltet.
      </ErrorState>
    );
  }
  if (code === "invalid_filter" || (error instanceof ApiError && error.status === 422)) {
    return (
      <ErrorState
        title="Diese Filter lassen sich nicht anwenden."
        actions={
          <Link to="/entitaeten" className={buttonClass()}>
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
      title="Die Entitäten konnten nicht geladen werden."
      actions={<Button onClick={onRetry}>Erneut versuchen</Button>}
    >
      Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
    </ErrorState>
  );
}

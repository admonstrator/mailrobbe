import { useEffect, useState } from "react";
import { Link } from "react-router";

import { ApiError, buildQuery } from "../../api/client";
import {
  useDocument,
  useMailDetail,
  useMailPage,
  useMailSummary,
  useMboxFiles,
  useResearch,
  useStats,
} from "../../api/queries";
import {
  LABEL_LIMIT,
  type BulkResult,
  type MailPage,
  type MailSelection,
  type MailSummary,
} from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { Chip } from "../../components/Chip";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { Pagination } from "../../components/Pagination";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { personName as shownName } from "../../lib/person";
import { TAG_PALETTE } from "../../lib/research";
import { ExportDialog, type ExportDialogProps } from "../research/ExportDialog";
import { MiniTimeline } from "../timeline/MiniTimeline";
import { hasSelection, selectionHref } from "../topics/urlState";
import { BulkBar } from "./BulkBar";
import { filterChips } from "./chips";
import { ColumnMenu } from "./ColumnMenu";
import { useColumns } from "./columns";
import { EntityFacets, useEntityChipNames } from "./EntityFacets";
import { FilterColumn } from "./FilterColumn";
import {
  hasFilters,
  listSearch,
  toFilters,
  toListParams,
  toOrderParams,
  withFilters,
  type ListState,
} from "./listState";
import styles from "./MailListPage.module.css";
import { MailTable, type TableSelection } from "./MailTable";
import { invalidTerm } from "./queryText";
import { SaveSearchDialog } from "./SaveSearchDialog";
import { SignalFacets, useSignalChipNames } from "./SignalFacets";
import { formatTotal, SummaryTiles } from "./SummaryTiles";
import { useListState } from "./useListState";

const listHref = (state: ListState) => {
  const search = listSearch(state).toString();
  return search ? `/mails?${search}` : "/mails";
};

function hitText(summary: MailSummary | undefined, state: ListState): string {
  const sorted = `sortiert nach Datum ${state.sort === "date_asc" ? "↑" : "↓"}`;
  if (!summary) return sorted;
  if (summary.total === null) return `Trefferzahl unbekannt · ${sorted}`;
  return `${formatTotal(summary)} Treffer · ${sorted}`;
}

/** The person names a page knows, for the chips of the person and between filters. */
function personName(page: MailPage | undefined, id: number): string {
  for (const mail of page?.items ?? []) {
    for (const person of [mail.sender, ...mail.recipients]) {
      if (person?.person_id === id) return shownName(person);
    }
  }
  return `#${id}`;
}

/** Mails checked in one view of the list (its query string), or every match of its filters. */
interface Picked {
  view: string;
  ids: number[];
  all: boolean;
}

/** "3 Mails geändert", "10 von 12 Mails geändert" when some had the change already. */
function changedText({ mails, changed }: BulkResult): string {
  const noun = mails === 1 ? "Mail" : "Mails";
  return changed === mails
    ? `${formatNumber(changed)} ${noun} geändert`
    : `${formatNumber(changed)} von ${formatNumber(mails)} ${noun} geändert`;
}

/** The mail list (SPEC 5.1): filters, figures, active filters, one page of mails, and the
 *  research file's work on them: selection and bulk changes, saved searches, export. */
export function MailListPage() {
  const [state, setState] = useListState();
  const stats = useStats();
  const mboxFiles = useMboxFiles();
  const research = useResearch();
  const page = useMailPage(toListParams(state));
  const summary = useMailSummary(toFilters(state));
  const [columns, setColumn] = useColumns();
  // The document filter's chip is named by the document (D75).
  const filtered = useDocument(state.document ?? 0, state.document !== null);
  // The thread filter's chip is named by the subject of the thread's first mail (D95).
  const threadMail = useMailDetail(state.thread ?? 0, state.thread !== null);
  // The event filter's chip is named by the event's summary in the first listed mail (D155).
  const eventMailId = state.event_uid !== null ? (page.data?.items[0]?.id ?? 0) : 0;
  const eventMail = useMailDetail(eventMailId, eventMailId > 0);
  const entityNames = useEntityChipNames(state.entity);
  const signalNames = useSignalChipNames();
  const [picked, setPicked] = useState<Picked>({ view: "", ids: [], all: false });
  const [notice, setNotice] = useState<{ text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState<Omit<ExportDialogProps, "onClose"> | null>(null);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4_000);
    return () => clearTimeout(timer);
  }, [notice]);

  const mboxPath = (id: number) =>
    mboxFiles.data?.find((file) => file.id === id)?.path ?? `Datei #${id}`;
  const chips = filterChips(state, page.data?.query_terms ?? [], {
    person: (id) => personName(page.data, id),
    mboxFile: mboxPath,
    tag: (id) => research.data?.tags.find((tag) => tag.id === id),
    collection: (id) => research.data?.collections.find((other) => other.id === id)?.name,
    document: (id) =>
      filtered.data?.id === id ? (filtered.data.name ?? "(ohne Dateinamen)") : `#${id}`,
    thread: (id) =>
      threadMail.data?.id === id ? threadMail.data.subject || "(kein Betreff)" : undefined,
    entity: entityNames,
    signal: signalNames,
    event: (uid) => eventMail.data?.events.find((event) => event.uid === uid)?.summary ?? undefined,
  });
  const exportQuery = buildQuery(toOrderParams(state)).toString();
  const label = (state.q || "Mailliste").slice(0, LABEL_LIMIT);
  const exactTotal = summary.data?.exact ? summary.data.total : null;

  // The selection belongs to this view: other filters, search, sort or page start empty.
  const view = listSearch(state).toString();
  const items = page.data?.items ?? [];
  const current = picked.view === view ? picked : { view, ids: [], all: false };
  const selectedIds = current.all ? items.map((mail) => mail.id) : current.ids;
  const pick = (ids: number[], all = false) => setPicked({ view, ids, all });
  const tableSelection: TableSelection = {
    ids: new Set(selectedIds),
    onToggle: (id, on) =>
      pick(on ? [...selectedIds, id] : selectedIds.filter((other) => other !== id)),
    onTogglePage: (on) => pick(on ? items.map((mail) => mail.id) : []),
  };
  // A page has at most 200 mails, below SELECTION_IDS_LIMIT; every match goes as the filters.
  const selection: MailSelection = current.all
    ? { filters: toFilters(state) }
    : { ids: selectedIds };

  return (
    <div className={styles.layout}>
      <title>Mails · Mailrobbe</title>
      <FilterColumn
        state={state}
        onChange={setState}
        stats={stats.data}
        mboxFiles={mboxFiles.data}
        research={research.data}
        terms={page.data?.query_terms}
      />
      <main className={styles.main}>
        <h1 className="sr-only">Mails</h1>
        <SummaryTiles summary={summary} />
        <MiniTimeline
          filters={toFilters(state)}
          onPick={(range) => setState(withFilters(state, range))}
          collapsible
        />

        <div className={styles.toolbar}>
          {chips.map((chip) => (
            <Chip
              key={chip.id}
              label={chip.label}
              color={chip.color && TAG_PALETTE[chip.color].text}
              onRemove={() => setState(chip.next)}
            />
          ))}
          {hasFilters(state) && (
            <Button variant="link" size="sm" onClick={() => setSaving(true)}>
              Suche speichern
            </Button>
          )}
          {hasSelection(state) && (
            <Link
              to={selectionHref(state)}
              className={buttonClass("link", "sm")}
              title="Wörter, die in diesen Mails häufiger sind als im übrigen Archiv"
            >
              Begriffe
            </Link>
          )}
          <span className={styles.hits} aria-live="polite">
            {hitText(summary.data, state)}
          </span>
          <div className={styles.actions}>
            <label htmlFor="mail-sort" className="sr-only">
              Sortierung
            </label>
            <select
              id="mail-sort"
              className={styles.sort}
              value={state.sort}
              onChange={(event) =>
                setState(withFilters(state, { sort: event.target.value as ListState["sort"] }))
              }
            >
              <option value="date_desc">Datum (neueste zuerst)</option>
              <option value="date_asc">Datum (älteste zuerst)</option>
            </select>
            <ColumnMenu columns={columns} onChange={setColumn} />
            <a
              href={`/api/mails/export.csv${exportQuery ? `?${exportQuery}` : ""}`}
              className={buttonClass()}
              download
            >
              Export CSV
            </a>
            <Button
              onClick={() =>
                setExporting({ selection: { filters: toFilters(state) }, count: exactTotal, label })
              }
            >
              Exportieren
            </Button>
          </div>
        </div>

        {selectedIds.length > 0 ? (
          <BulkBar
            selected={selectedIds.length}
            all={current.all}
            summary={summary.data}
            selection={selection}
            onSelectAll={() => pick([], true)}
            onClear={() => pick([])}
            onDone={(result) => {
              pick([]);
              setNotice({ text: changedText(result) });
            }}
            onExport={() =>
              setExporting({
                selection,
                count: current.all ? exactTotal : selectedIds.length,
                label,
              })
            }
          />
        ) : (
          notice && (
            <p className={styles.notice} role="status">
              {notice.text}
            </p>
          )
        )}

        <SignalFacets state={state} onChange={setState} placement="top" />
        <EntityFacets state={state} onChange={setState} placement="top" />
        <Card className={styles.tableCard}>
          {page.isPending ? (
            <div className={styles.loading}>
              <Spinner label="Mails werden geladen" />
            </div>
          ) : page.isError ? (
            <PageError error={page.error} state={state} onRetry={() => void page.refetch()} />
          ) : page.data.items.length === 0 ? (
            <EmptyState
              title="Keine Mails gefunden"
              actions={
                hasFilters(state) && (
                  <Link to="/mails" className={buttonClass()}>
                    Alle Filter zurücksetzen
                  </Link>
                )
              }
            >
              {hasFilters(state)
                ? "Kein Treffer für diese Suche und Filter."
                : "Das Archiv ist leer."}
            </EmptyState>
          ) : (
            <MailTable
              items={page.data.items}
              columns={columns}
              detailSearch={view}
              mboxPath={mboxPath}
              stale={page.isPlaceholderData}
              selection={tableSelection}
            />
          )}
        </Card>

        {page.data && page.data.items.length > 0 && (
          <Pagination
            range={rangeText(state, page.data.items.length, summary.data)}
            prev={
              page.data.prev_cursor ? listHref(previousPage(state, page.data.prev_cursor)) : null
            }
            next={
              page.data.next_cursor
                ? listHref({ ...state, cursor: page.data.next_cursor, page: state.page + 1 })
                : null
            }
          />
        )}
      </main>
      <div className={styles.facets}>
        <SignalFacets state={state} onChange={setState} placement="column" />
        <EntityFacets state={state} onChange={setState} placement="column" />
      </div>

      {saving && (
        <SaveSearchDialog
          query={listSearch({ ...state, cursor: null, page: 1 }).toString()}
          suggestedName={state.q || chips.map((chip) => chip.label).join(" · ")}
          onClose={() => setSaving(false)}
        />
      )}
      {exporting && <ExportDialog {...exporting} onClose={() => setExporting(null)} />}
    </div>
  );
}

function previousPage(state: ListState, cursor: string): ListState {
  // The page before the second one is the first: without cursor, as the list starts.
  return state.page === 2
    ? { ...state, cursor: null, page: 1 }
    : { ...state, cursor, page: Math.max(1, state.page - 1) };
}

/** "1–50 von 1.207", "51–100 von mehr als 10.000", or just the range when the total is open. */
function rangeText(state: ListState, count: number, summary: MailSummary | undefined): string {
  const first = (state.page - 1) * state.limit + 1;
  const range = `${formatNumber(first)}–${formatNumber(first + count - 1)}`;
  return summary && summary.total !== null ? `${range} von ${formatTotal(summary)}` : range;
}

function PageError({
  error,
  state,
  onRetry,
}: {
  error: Error;
  state: ListState;
  onRetry: () => void;
}) {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "invalid_query") {
    return (
      <ErrorState
        title={`Suche nicht verstanden: ${invalidTerm(error.message, state.q)}`}
        actions={
          <Link to={listHref(withFilters(state, { q: "" }))} className={buttonClass()}>
            Suche leeren
          </Link>
        }
      >
        Suchoperatoren brauchen einen gültigen Wert, zum Beispiel after:2024-01-31, dkim:fail oder
        has:attachment.
      </ErrorState>
    );
  }
  if (code === "invalid_filter") {
    return (
      <ErrorState
        title="Diese Filter lassen sich nicht anwenden."
        actions={
          <Link to="/mails" className={buttonClass()}>
            Filter zurücksetzen
          </Link>
        }
      >
        Die Adresse enthält eine Filterkombination, die Mailrobbe nicht auswerten kann.
      </ErrorState>
    );
  }
  if (code === "invalid_cursor") {
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
      title="Die Mails konnten nicht geladen werden."
      actions={<Button onClick={onRetry}>Erneut versuchen</Button>}
    >
      Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
    </ErrorState>
  );
}

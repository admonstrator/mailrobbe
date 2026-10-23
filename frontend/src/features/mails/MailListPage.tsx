import { useEffect, useEffectEvent, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

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
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { InsightsIcon, PageBackIcon, PageOnIcon } from "../../components/icons";
import { OverflowMenu, type OverflowItem } from "../../components/OverflowMenu";
import { PageTooFar, Pagination } from "../../components/Pagination";
import { SidePanel } from "../../components/SidePanel";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { highlightTerms } from "../../lib/highlight";
import { isPlainKey } from "../../lib/keys";
import { edgePages, listPagination, type Total } from "../../lib/paging";
import { personName as shownName } from "../../lib/person";
import { placesHrefOf } from "../places/urlState";
import { ExportDialog, type ExportDialogProps } from "../research/ExportDialog";
import { timelinePath } from "../timeline/buckets";
import { hasSelection, selectionHref } from "../topics/urlState";
import { AiFacets, useAiChipNames } from "./AiFacets";
import { BulkBar } from "./BulkBar";
import { filterChips } from "./chips";
import { useColumns } from "./columns";
import { EntityFacets, useEntityChipNames } from "./EntityFacets";
import { FilterBar } from "./FilterBar";
import {
  hasFilters,
  listSearch,
  positiveInt,
  toFilters,
  toListParams,
  toOrderParams,
  withFilters,
  type ListState,
} from "./listState";
import styles from "./MailListPage.module.css";
import { MailPreview } from "./MailPreview";
import { MailRows, type Density } from "./MailRows";
import { invalidTerm } from "./queryText";
import { SaveSearchDialog } from "./SaveSearchDialog";
import { SignalFacets, useSignalChipNames } from "./SignalFacets";
import { SummaryLine } from "./SummaryLine";
import { formatTotal } from "./SummaryTiles";
import { useBarHeight } from "./useBarHeight";
import { useListState } from "./useListState";

/** The query parameter of the mail shown in the preview beside the list (D335). */
export const PREVIEW_PARAM = "vorschau";

const DENSITY_KEY = "mailrobbe.row-density";
const INSIGHTS_KEY = "mailrobbe.insights";

const listHref = (state: ListState) => {
  const search = listSearch(state).toString();
  return search ? `/mails?${search}` : "/mails";
};

/** The CSV of the list's mails, in the list's order. */
export function csvHref(state: ListState): string {
  const query = buildQuery(toOrderParams(state)).toString();
  return `/api/mails/export.csv${query ? `?${query}` : ""}`;
}

function load(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage blocked: the default
  }
}

function store(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // storage blocked: the choice lasts until reload
  }
}

/** "686 Treffer", "Treffer (mehr als 10.000)", "Trefferzahl unbekannt". */
function hitText(summary: MailSummary | undefined): string {
  if (!summary) return "";
  if (summary.total === null) return "Trefferzahl unbekannt";
  return `${formatTotal(summary)} Treffer`;
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

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    target.closest("input, textarea, select, [contenteditable], dialog, [role=dialog]") !== null
  );
}

/** The mail list (SPEC 5.1, D335) like a mail program: a toolbar with the count, the panel
 *  "Einblicke", sort, pages and the menu "…"; the filters as chips, or the bulk actions of a
 *  selection; one quiet line of figures; the rows; and the preview of a mail in a panel beside
 *  them, kept in the URL (?vorschau=). */
export function MailListPage() {
  const [state, setState] = useListState();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const previewId = positiveInt(searchParams.get(PREVIEW_PARAM));
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
  const aiNames = useAiChipNames(state.ai_tag);
  const [picked, setPicked] = useState<Picked>({ view: "", ids: [], all: false });
  const [notice, setNotice] = useState<{ text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState<Omit<ExportDialogProps, "onClose"> | null>(null);
  const [density, setDensity] = useState<Density>(() =>
    load(DENSITY_KEY) === "compact" ? "compact" : "comfortable",
  );
  const [insightsWanted, setInsights] = useState(() => load(INSIGHTS_KEY) === "open");
  const insights = insightsWanted && previewId === null;
  const bar = useBarHeight<HTMLDivElement>();

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4_000);
    return () => clearTimeout(timer);
  }, [notice]);

  const showNotice = (text: string) => setNotice({ text });
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
    ...aiNames,
  });
  const label = (state.q || "Mailliste").slice(0, LABEL_LIMIT);
  const exactTotal = summary.data?.exact ? summary.data.total : null;
  const marks = useMemo(() => {
    const words = highlightTerms(state.q);
    return words.length > 0 ? { words, stems: [], whole_word: state.whole_word } : undefined;
  }, [state.q, state.whole_word]);

  // The selection belongs to this view: other filters, search, sort or page start empty.
  const view = listSearch(state).toString();
  const items = page.data?.items ?? [];
  const current = picked.view === view ? picked : { view, ids: [], all: false };
  const selectedIds = current.all ? items.map((mail) => mail.id) : current.ids;
  const pick = (ids: number[], all = false) => setPicked({ view, ids, all });
  const selectedOnPage = items.filter((mail) => selectedIds.includes(mail.id)).length;
  // A page has at most 200 mails, below SELECTION_IDS_LIMIT; every match goes as the filters.
  const selection: MailSelection = current.all
    ? { filters: toFilters(state) }
    : { ids: selectedIds };
  const detailHref = (id: number) => `/mails/${id}${view ? `?${view}` : ""}`;
  const paging =
    page.data && items.length > 0
      ? listPagination(state, page.data, items.length, mailTotal(summary.data), listHref)
      : null;

  /** Shows a mail in the preview; a new entry of the history unless it replaces the shown one. */
  function preview(id: number | null, replace = false) {
    setSearchParams(
      (now) => {
        const next = new URLSearchParams(now);
        if (id === null) next.delete(PREVIEW_PARAM);
        else next.set(PREVIEW_PARAM, String(id));
        return next;
      },
      { replace, preventScrollReset: true },
    );
  }

  function toggleInsights() {
    const open = !insights;
    setInsights(open);
    store(INSIGHTS_KEY, open ? "open" : null);
    if (open && previewId !== null) preview(null);
  }

  // j and k step through the rows: the preview's mail while it is open, else the focus.
  const onKey = useEffectEvent((event: KeyboardEvent) => {
    if (!isPlainKey(event) || event.shiftKey || isTyping(event.target)) return;
    if (event.key !== "j" && event.key !== "k") return;
    const by = event.key === "j" ? 1 : -1;
    const links = [
      ...document.querySelectorAll<HTMLAnchorElement>("[data-mail-row] a[data-subject]"),
    ];
    if (previewId !== null) {
      const index = items.findIndex((mail) => mail.id === previewId);
      const target = items[index + by];
      if (index < 0 || !target) return;
      event.preventDefault();
      preview(target.id, true);
      links[index + by]?.scrollIntoView?.({ block: "nearest" });
      return;
    }
    const index = links.findIndex((link) => link === document.activeElement);
    const target = links[index < 0 ? 0 : index + by];
    if (!target) return;
    event.preventDefault();
    target.focus();
  });
  useEffect(() => {
    const listener = (event: KeyboardEvent) => onKey(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  const menu: OverflowItem[] = [
    ...(hasFilters(state) ? [{ label: "Suche speichern …", onSelect: () => setSaving(true) }] : []),
    {
      label: "Exportieren (ZIP mit PDF und Prüfsummen) …",
      onSelect: () =>
        setExporting({ selection: { filters: toFilters(state) }, count: exactTotal, label }),
    },
    {
      label: "Als CSV herunterladen",
      onSelect: () => {
        const link = document.createElement("a");
        link.href = csvHref(state);
        link.download = "";
        link.click();
      },
    },
    ...(hasSelection(state)
      ? [
          {
            label: "Begriffe dieser Treffer",
            onSelect: () => void navigate(selectionHref(state)),
            separated: true,
          },
        ]
      : []),
    {
      label: "Treffer auf der Karte",
      onSelect: () => void navigate(placesHrefOf(state)),
      separated: !hasSelection(state),
    },
    {
      label: "Treffer in der Zeitachse",
      onSelect: () => void navigate(timelinePath(toFilters(state))),
    },
    ...(!state.include_hidden && summary.data?.hidden
      ? [
          {
            label: `${formatNumber(summary.data.hidden)} ausgeblendete Mails zeigen`,
            onSelect: () => setState(withFilters(state, { include_hidden: true })),
            separated: true,
          },
        ]
      : []),
    {
      label: density === "compact" ? "Zeilen: bequem" : "Zeilen: kompakt",
      onSelect: () => {
        const next = density === "compact" ? "comfortable" : "compact";
        setDensity(next);
        store(DENSITY_KEY, next === "compact" ? "compact" : null);
      },
      separated: state.include_hidden || !summary.data?.hidden,
    },
    {
      label: columns.size ? "Größe ausblenden" : "Größe zeigen",
      onSelect: () => setColumn("size", !columns.size),
    },
    {
      label: columns.mbox ? "MBOX-Datei ausblenden" : "MBOX-Datei zeigen",
      onSelect: () => setColumn("mbox", !columns.mbox),
    },
  ];

  return (
    <div className={styles.page}>
      <title>Mails · Mailrobbe</title>
      {/* Toolbar, filters or bulk actions, and figures stay below the header while the rows
          scroll. */}
      <div ref={bar} className={styles.head}>
        <div className={styles.toolbar}>
          <input
            type="checkbox"
            className={styles.selectAll}
            aria-label="Alle Mails dieser Seite auswählen"
            checked={selectedOnPage > 0 && selectedOnPage === items.length}
            ref={(box) => {
              if (box) box.indeterminate = selectedOnPage > 0 && selectedOnPage < items.length;
            }}
            disabled={items.length === 0}
            onChange={(event) => pick(event.target.checked ? items.map((mail) => mail.id) : [])}
          />
          <h1 className={styles.title}>Mails</h1>
          <span className={styles.hits} aria-live="polite">
            {hitText(summary.data)}
            {state.q && summary.data && ` für „${state.q}“`}
            {!state.include_hidden &&
              !!summary.data?.hidden &&
              ` · ${formatNumber(summary.data.hidden)} ausgeblendet`}
          </span>
          <div className={styles.tools}>
            <button
              type="button"
              className={cx(buttonClass("default", "sm"), insights && styles.pressed)}
              aria-pressed={insights}
              onClick={toggleInsights}
            >
              <InsightsIcon size={16} />
              Einblicke
            </button>
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
              <option value="date_desc">Neueste zuerst</option>
              <option value="date_asc">Älteste zuerst</option>
            </select>
            {paging && (
              <nav className={styles.pager} aria-label="Seite">
                <span className={styles.range}>{paging.range}</span>
                <Step to={paging.prev} label="Vorige Seite">
                  <PageBackIcon size={18} />
                </Step>
                <Step to={paging.next} label="Nächste Seite">
                  <PageOnIcon size={18} />
                </Step>
              </nav>
            )}
            <OverflowMenu items={menu} />
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
          <FilterBar
            state={state}
            onChange={setState}
            chips={chips}
            stats={stats.data}
            mboxFiles={mboxFiles.data}
            research={research.data}
          />
        )}
        {notice && (
          <p className={styles.notice} role="status">
            {notice.text}
          </p>
        )}
        <SummaryLine
          summary={summary}
          filters={toFilters(state)}
          onPick={(range) => setState(withFilters(state, range))}
        />
      </div>

      <div className={styles.body}>
        <div className={styles.list}>
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
            <MailRows
              items={page.data.items}
              detailHref={detailHref}
              marks={marks}
              openId={previewId}
              onOpen={(id) => {
                if (insights) setInsights(false);
                preview(id, previewId !== null);
              }}
              narrow={previewId !== null || insights}
              density={density}
              columns={columns}
              mboxPath={mboxPath}
              stale={page.isPlaceholderData}
              selection={{
                ids: new Set(selectedIds),
                onToggle: (id, on) =>
                  pick(on ? [...selectedIds, id] : selectedIds.filter((other) => other !== id)),
              }}
            />
          )}
          {paging && (
            <div className={styles.foot}>
              <Pagination {...paging} />
            </div>
          )}
        </div>

        {previewId !== null && (
          <MailPreview
            id={previewId}
            detailHref={detailHref}
            order={toOrderParams(state)}
            marks={marks}
            onStep={(id) => preview(id, true)}
            onClose={() => preview(null)}
          />
        )}
        {insights && (
          <SidePanel label="Einblicke" title="Einblicke" width="340px" onClose={toggleInsights}>
            <p className={styles.insightsScope}>
              {summary.data && summary.data.total !== null
                ? `in ${formatTotal(summary.data)} Treffern, ein Klick filtert`
                : "ein Klick filtert"}
            </p>
            <div className={styles.facets}>
              <SignalFacets state={state} onChange={setState} />
              <EntityFacets state={state} onChange={setState} />
              <AiFacets state={state} onChange={setState} onNotice={showNotice} />
            </div>
          </SidePanel>
        )}
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

/** A step of the compact pager: a link, or a quiet disabled button where there is no page. */
function Step({ to, label, children }: { to: string | null; label: string; children: ReactNode }) {
  return to === null ? (
    <span className={cx(styles.step, styles.disabled)} aria-disabled="true" aria-label={label}>
      {children}
    </span>
  ) : (
    <Link to={to} className={styles.step} aria-label={label} title={label}>
      {children}
    </Link>
  );
}

/** The list's length as MailSummary counts it (D19), for the page numbers (D193). */
function mailTotal(summary: MailSummary | undefined): Total | null {
  return summary && summary.total !== null ? { count: summary.total, exact: summary.exact } : null;
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
  if (code === "page_too_far") return <PageTooFar {...edgePages(state, listHref)} />;
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

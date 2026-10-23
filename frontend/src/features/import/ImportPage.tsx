import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";

import {
  runAlive,
  useImportStatus,
  useImportSummary,
  usePauseImport,
  useRescan,
  useStartDkimRun,
  useStartImport,
  type ImportErrorFilters,
} from "../../api/queries";
import type { FileProblem, ImportStatus, ScanResult } from "../../api/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { CrossIcon } from "../../components/icons";
import { OverflowMenu } from "../../components/OverflowMenu";
import { Spinner } from "../../components/Spinner";
import { tabPanelProps, Tabs } from "../../components/Tabs";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { KeyRecoveryCard } from "../keys/KeyRecoveryCard";
import { AiRunLine } from "./AiRunLine";
import { ArchiveTiles } from "./ArchiveTiles";
import { DkimResult } from "./DkimResult";
import { DocumentResult } from "./DocumentResult";
import { ErrorDialog } from "./ErrorDialog";
import { ErrorLog } from "./ErrorLog";
import { FileTable } from "./FileTable";
import styles from "./ImportPage.module.css";
import { actionErrorText, MBOX_DIR_MISSING, scanSummary } from "./labels";
import { canResume, startRequest, type SettingsDraft } from "./model";
import { PageHead, StateBadge } from "../../components/PageHead";
import { runBadge, RunProgress, RunSub, RunTab } from "./RunCard";
import { SettingsCard } from "./SettingsCard";

interface Notice {
  tone: "info" | "error";
  content: ReactNode;
}

type ImportTab = "lauf" | "dateien" | "fehler" | "ergebnis" | "optionen";

const TABS: readonly ImportTab[] = ["lauf", "dateien", "fehler", "ergebnis", "optionen"];

/** Paths a rescan notice lists; beyond this it gives the counts only. */
const LISTED_PATHS = 10;

/** When a run ends, its mails and figures reach every screen: everything is loaded again. */
function useRefreshWhenRunEnds(alive: boolean) {
  const queryClient = useQueryClient();
  const before = useRef(alive);
  useEffect(() => {
    if (before.current && !alive) void queryClient.invalidateQueries();
    before.current = alive;
  }, [alive, queryClient]);
}

/** The import dashboard (SPEC 5.5, D46 to D50) as a page of D336: head with state and actions,
 *  the figures as a row, tabs for the run, the files, the errors, the results and the options. */
export function ImportPage() {
  const status = useImportStatus();
  useRefreshWhenRunEnds(runAlive(status.data));

  return (
    <main className={styles.page}>
      <title>Import · Mailrobbe</title>
      {status.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Importstatus wird geladen" />
        </div>
      ) : status.isError ? (
        <ErrorState
          title="Der Importstatus konnte nicht geladen werden."
          actions={<Button onClick={() => void status.refetch()}>Erneut versuchen</Button>}
        >
          Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
        </ErrorState>
      ) : (
        <Dashboard status={status.data} />
      )}
    </main>
  );
}

function Dashboard({ status }: { status: ImportStatus }) {
  const summary = useImportSummary();
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as ImportTab | null;
  // A new archive opens on its files, where the scan is offered.
  const first: ImportTab = status.files.length === 0 && !status.import_job ? "dateien" : "lauf";
  const tab: ImportTab = requested && TABS.includes(requested) ? requested : first;
  const [notice, setNotice] = useState<Notice | null>(null);
  const [draft, setDraft] = useState<SettingsDraft>({});
  const [errorFilters, setErrorFilters] = useState<ImportErrorFilters | null>(null);
  const rescan = useRescan();
  const showError = (error: Error) => setNotice({ tone: "error", content: actionErrorText(error) });
  const startRescan = () => {
    setNotice(null);
    rescan.mutate(undefined, {
      onSuccess: (result) => setNotice({ tone: "info", content: <ScanNotice result={result} /> }),
      onError: showError,
    });
  };
  const select = (next: ImportTab) =>
    setParams(
      (before) => {
        const search = new URLSearchParams(before);
        if (next === first) search.delete("tab");
        else search.set("tab", next);
        return search;
      },
      { replace: true, preventScrollReset: true },
    );
  const badge = runBadge(status.import_job);
  const { totals } = status;

  return (
    <>
      <PageHead
        title="Import"
        badge={<StateBadge tone={badge.tone}>{badge.text}</StateBadge>}
        sub={<RunSub status={status} />}
        actions={
          <Actions
            status={status}
            draft={draft}
            rescanning={rescan.isPending}
            onRescan={startRescan}
            onStarted={() => setDraft({})}
            onNotice={setNotice}
            onOptions={() => select("optionen")}
          />
        }
      />
      {notice && (
        <div
          role={notice.tone === "error" ? "alert" : "status"}
          className={cx(styles.notice, styles[notice.tone])}
        >
          <div className={styles.noticeText}>{notice.content}</div>
          <Button
            variant="link"
            size="xs"
            className={styles.noticeClose}
            aria-label="Hinweis schließen"
            onClick={() => setNotice(null)}
          >
            <CrossIcon />
          </Button>
        </div>
      )}
      <RunProgress status={status} summary={summary.data} />
      <AiRunLine run={status.ai_job} />
      <div className={styles.tabs}>
        <Tabs
          idPrefix="import"
          label="Bereiche des Imports"
          active={tab}
          onSelect={select}
          items={[
            { id: "lauf", label: "Lauf" },
            { id: "dateien", label: "Dateien", count: formatNumber(totals.files) },
            {
              id: "fehler",
              label: "Fehler",
              count: totals.error_count > 0 ? formatNumber(totals.error_count) : undefined,
            },
            { id: "ergebnis", label: "Ergebnis" },
            { id: "optionen", label: "Startoptionen" },
          ]}
        />
      </div>
      <div {...tabPanelProps("import", tab)} className={styles.panel}>
        {tab === "lauf" ? (
          <RunTab status={status} onError={showError} />
        ) : tab === "dateien" ? (
          status.files.length === 0 ? (
            <EmptyState
              title="Noch keine MBOX-Dateien"
              actions={
                <Button
                  variant="primary"
                  onClick={startRescan}
                  disabled={!status.mbox_dir_ok || runAlive(status) || rescan.isPending}
                >
                  Verzeichnis neu scannen
                </Button>
              }
            >
              {status.mbox_dir_ok
                ? `Lege MBOX-Dateien in das Verzeichnis ${status.mbox_dir} und scanne es neu.`
                : MBOX_DIR_MISSING}
            </EmptyState>
          ) : (
            <FileTable
              status={status}
              onShowErrors={(file) => setErrorFilters({ mbox_file: file.id })}
            />
          )
        ) : tab === "fehler" ? (
          <ErrorLog alive={runAlive(status)} onShow={setErrorFilters} />
        ) : tab === "ergebnis" ? (
          <Results summary={summary} />
        ) : (
          <SettingsCard defaults={status.defaults} draft={draft} onChange={setDraft} />
        )}
      </div>
      {errorFilters && (
        <ErrorDialog
          initial={errorFilters}
          files={status.files}
          onClose={() => setErrorFilters(null)}
        />
      )}
    </>
  );
}

/** The tab "Ergebnis": the DKIM result, the attachments read, the archive's figures and the
 *  deleted selectors with their runs. */
function Results({ summary }: { summary: ReturnType<typeof useImportSummary> }) {
  return (
    <div className={styles.results}>
      {summary.data ? (
        <>
          <div className={styles.resultGrid}>
            <DkimResult summary={summary.data} />
            <DocumentResult summary={summary.data} />
          </div>
          <section aria-labelledby="import-archive-title" className={styles.section}>
            <h2 id="import-archive-title" className={styles.sectionTitle}>
              Archiv
            </h2>
            <ArchiveTiles summary={summary.data} />
          </section>
        </>
      ) : summary.isError ? (
        <p className={styles.summaryError}>
          Die Kennzahlen des Archivs konnten nicht geladen werden.
        </p>
      ) : (
        <div className={styles.loading}>
          <Spinner label="Kennzahlen werden geladen" />
        </div>
      )}
      <KeyRecoveryCard />
    </div>
  );
}

/** Start or stop the run as the one main button; the DKIM recheck, the rescan, the deleted
 *  selectors and the start options in the menu "…". While a run is alive only that run can be
 *  stopped (D46, D50). */
function Actions({
  status,
  draft,
  rescanning,
  onRescan,
  onStarted,
  onNotice,
  onOptions,
}: {
  status: ImportStatus;
  draft: SettingsDraft;
  rescanning: boolean;
  onRescan: () => void;
  onStarted: () => void;
  onNotice: (notice: Notice | null) => void;
  onOptions: () => void;
}) {
  const navigate = useNavigate();
  const start = useStartImport();
  const pause = usePauseImport();
  const dkim = useStartDkimRun();
  const job = status.import_job;
  const busy = job?.alive
    ? "Es läuft gerade ein Import."
    : status.dkim_job?.alive
      ? "Es läuft gerade eine DKIM-Prüfung."
      : status.keys_job?.alive
        ? "Es läuft gerade eine Schlüsselsuche."
        : null;
  const needsDir = busy ?? (status.mbox_dir_ok ? null : MBOX_DIR_MISSING);
  const showError = (error: Error) => onNotice({ tone: "error", content: actionErrorText(error) });

  function onStart() {
    const result = startRequest(status.defaults, draft);
    if ("problem" in result) {
      onNotice({ tone: "error", content: `Eine Einstellung ist ungültig: ${result.problem}` });
      return;
    }
    onNotice(null);
    start.mutate(result.request, { onSuccess: onStarted, onError: showError });
  }

  return (
    <>
      {job?.alive ? (
        <Button
          disabled={job.stop_requested || pause.isPending}
          onClick={() => {
            onNotice(null);
            pause.mutate(undefined, { onError: showError });
          }}
        >
          {job.stop_requested ? "Wird angehalten …" : "Anhalten"}
        </Button>
      ) : (
        <Button
          variant="primary"
          disabled={needsDir !== null || start.isPending}
          title={needsDir ?? undefined}
          onClick={onStart}
        >
          {canResume(status) ? "Import fortsetzen" : "Import starten"}
        </Button>
      )}
      <OverflowMenu
        items={[
          {
            label: "Verzeichnis neu scannen",
            disabled: needsDir !== null || rescanning,
            onSelect: onRescan,
          },
          {
            label: "DKIM für „Schlüssel fehlt“ neu prüfen",
            disabled: busy !== null || dkim.isPending,
            onSelect: () => {
              onNotice(null);
              dkim.mutate(undefined, { onError: showError });
            },
          },
          {
            label: "Gelöschte Selektoren",
            onSelect: () => void navigate("/import/selektoren"),
          },
          { label: "Startoptionen …", separated: true, onSelect: onOptions },
        ]}
      />
    </>
  );
}

/** What the rescan found, with the paths when there are few. */
function ScanNotice({ result }: { result: ScanResult }) {
  const plain = (paths: string[]) => paths.map((path) => ({ path, reason: "" }));
  const groups: [string, FileProblem[]][] = [
    ["Neu", plain(result.new)],
    ["Geändert", result.replaced],
    ["Fehlen", plain(result.missing)],
    ["Nicht lesbar", result.unreadable],
  ];
  const listed = groups.filter(([, files]) => files.length > 0);
  const count = listed.reduce((sum, [, files]) => sum + files.length, 0);
  return (
    <>
      <p>{scanSummary(result)}</p>
      {count > 0 && count <= LISTED_PATHS && (
        <ul className={styles.paths}>
          {listed.map(([label, files]) => (
            <li key={label}>
              {`${label}: `}
              {files.map(({ path, reason }, index) => (
                <span key={path}>
                  {index > 0 && ", "}
                  <span className="mono">{path}</span>
                  {reason && ` (${reason})`}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

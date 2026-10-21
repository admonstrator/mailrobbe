import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";

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
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { CrossIcon } from "../../components/icons";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { ArchiveTiles } from "./ArchiveTiles";
import { KeyRecoveryCard } from "../keys/KeyRecoveryCard";
import { DkimResult } from "./DkimResult";
import { DocumentResult } from "./DocumentResult";
import { ErrorDialog } from "./ErrorDialog";
import { ErrorLog } from "./ErrorLog";
import { FileTable } from "./FileTable";
import styles from "./ImportPage.module.css";
import { actionErrorText, MBOX_DIR_MISSING, scanSummary } from "./labels";
import { canResume, startRequest, type SettingsDraft } from "./model";
import { RunCard } from "./RunCard";
import { SettingsCard } from "./SettingsCard";

interface Notice {
  tone: "info" | "error";
  content: ReactNode;
}

/** Paths a rescan notice lists; beyond this it gives the counts only. */
const LISTED_PATHS = 10;

const DKIM_HINT = "Prüft Mails ohne Ergebnis, mit „Schlüssel fehlt“ oder mit DNS-Fehler erneut.";

/** When a run ends, its mails and figures reach every screen: everything is loaded again. */
function useRefreshWhenRunEnds(alive: boolean) {
  const queryClient = useQueryClient();
  const before = useRef(alive);
  useEffect(() => {
    if (before.current && !alive) void queryClient.invalidateQueries();
    before.current = alive;
  }, [alive, queryClient]);
}

/** The import dashboard (SPEC 5.5, D46 to D50). */
export function ImportPage() {
  const status = useImportStatus();
  useRefreshWhenRunEnds(runAlive(status.data));

  return (
    <main className={styles.page}>
      <title>Import · Mailrobbe</title>
      {status.isPending ? (
        <Card className={styles.loading}>
          <Spinner label="Importstatus wird geladen" />
        </Card>
      ) : status.isError ? (
        <Card>
          <ErrorState
            title="Der Importstatus konnte nicht geladen werden."
            actions={<Button onClick={() => void status.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        </Card>
      ) : (
        <Dashboard status={status.data} />
      )}
    </main>
  );
}

function Dashboard({ status }: { status: ImportStatus }) {
  const summary = useImportSummary();
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

  return (
    <>
      <Toolbar
        status={status}
        draft={draft}
        rescanning={rescan.isPending}
        onRescan={startRescan}
        onStarted={() => setDraft({})}
        onNotice={setNotice}
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
      <RunCard status={status} duplicates={summary.data?.duplicates} onError={showError} />
      {summary.data ? (
        <ArchiveTiles summary={summary.data} />
      ) : summary.isError ? (
        <p className={styles.summaryError}>
          Die Kennzahlen des Archivs konnten nicht geladen werden.
        </p>
      ) : (
        <div className={styles.summaryLoading}>
          <Spinner label="Kennzahlen werden geladen" />
        </div>
      )}
      <div className={styles.columns}>
        <div className={styles.main}>
          {status.files.length === 0 ? (
            <Card>
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
            </Card>
          ) : (
            <FileTable
              status={status}
              onShowErrors={(file) => setErrorFilters({ mbox_file: file.id })}
            />
          )}
        </div>
        <div className={styles.side}>
          {summary.data && <DkimResult summary={summary.data} />}
          <KeyRecoveryCard />
          {summary.data && <DocumentResult summary={summary.data} />}
          <ErrorLog alive={runAlive(status)} onShowAll={() => setErrorFilters({})} />
          <SettingsCard defaults={status.defaults} draft={draft} onChange={setDraft} />
        </div>
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

/** Start or pause, the DKIM recheck and the rescan. While a run is alive only that run can be
 *  stopped (D46, D50). */
function Toolbar({
  status,
  draft,
  rescanning,
  onRescan,
  onStarted,
  onNotice,
}: {
  status: ImportStatus;
  draft: SettingsDraft;
  rescanning: boolean;
  onRescan: () => void;
  onStarted: () => void;
  onNotice: (notice: Notice | null) => void;
}) {
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
    <div className={styles.toolbar}>
      {job?.alive ? (
        <Button
          disabled={job.stop_requested || pause.isPending}
          onClick={() => {
            onNotice(null);
            pause.mutate(undefined, { onError: showError });
          }}
        >
          {job.stop_requested ? "Wird pausiert …" : "Pausieren"}
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
      <Button
        disabled={busy !== null || dkim.isPending}
        title={busy ?? DKIM_HINT}
        onClick={() => {
          onNotice(null);
          dkim.mutate(undefined, { onError: showError });
        }}
      >
        DKIM für „Schlüssel fehlt“ neu prüfen
      </Button>
      <Button
        disabled={needsDir !== null || rescanning}
        title={
          job?.alive
            ? "Es läuft gerade ein Import; er arbeitet die Dateien ab, die er beim Start gefunden hat."
            : (needsDir ?? undefined)
        }
        onClick={onRescan}
      >
        Verzeichnis neu scannen
      </Button>
    </div>
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

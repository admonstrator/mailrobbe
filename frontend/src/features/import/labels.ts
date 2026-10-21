// German texts of the import dashboard: run states, phases, file statuses, error kinds, the
// notices after an action.

import { ApiError } from "../../api/client";
import type { DkimKey, ImportErrorKind, ImportJob, MboxStatus, ScanResult } from "../../api/types";
import { DKIM_FILTER_LABELS } from "../../lib/dkim";
import { formatNumber } from "../../lib/format";
import type { FileFilter, RunState } from "./model";

export const RUN_TITLES: Record<RunState, string> = {
  none: "Noch kein Import",
  running: "Import läuft",
  pausing: "Import wird pausiert …",
  paused: "Import pausiert",
  done: "Import fertig",
  aborted: "Import abgebrochen",
};

/** What a live import does beside importing files; null while it imports (D47, D52). */
export function phaseText(job: ImportJob): string | null {
  switch (job.phase) {
    case "scan":
      return "Verzeichnis wird gescannt";
    case "headers": {
      const { headers_done, headers_total } = job.progress;
      return `Header älterer Mails werden neu gelesen (Verteiler und Automaten), ${formatNumber(headers_done)} von ${formatNumber(headers_total)}`;
    }
    case "finalize":
      return "Nachlauf: Duplikate, Threads und Kennzahlen werden berechnet";
    default:
      return null;
  }
}

export const FILE_STATUS_LABELS: Record<MboxStatus, string> = {
  done: "Fertig",
  running: "Läuft",
  pending: "Wartet",
  paused: "Pausiert",
  error: "Fehler",
};

export const FILE_FILTER_LABELS: Record<FileFilter, string> = {
  all: "Alle",
  ...FILE_STATUS_LABELS,
};

/** Labels of the DKIM result, worded like the mockup and the recheck button. */
export const DKIM_RESULT_LABELS: Record<DkimKey, string> = {
  ...DKIM_FILTER_LABELS,
  no_key: "Schlüssel fehlt",
  unsigned: "Unsigniert",
};

/** One German line per import_error.kind; the entry's English message stays beside it. */
export const ERROR_KIND_TEXTS: Record<ImportErrorKind, string> = {
  separator: "From_-Trennzeile fehlerhaft",
  too_large: "Mail über dem Größenlimit, nur Kopfzeilen gespeichert",
  encoding: "Zeichenkodierung ungültig, heuristisch dekodiert",
  date: "Datum fehlt oder ungültig",
  message_id: "Message-ID fehlt oder ungültig",
  address: "Adresse unlesbar, ausgelassen",
  parse: "Mail nur teilweise lesbar",
  dkim: "DKIM-Prüfung gescheitert, Mail ungeprüft",
  io: "Datei nicht lesbar",
  internal: "Interner Fehler beim Import",
};

export const MBOX_DIR_MISSING = "Das MBOX-Verzeichnis ist für den Server nicht lesbar.";

/** The notice for an action the API refused or that failed. */
export function actionErrorText(error: Error): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "job_running":
        return "Es läuft bereits ein Import oder eine DKIM-Prüfung.";
      case "no_job":
        return "Es läuft gerade nichts, das angehalten werden könnte.";
      case "mbox_dir_missing":
        return MBOX_DIR_MISSING;
      case "invalid_option":
        return `Eine Einstellung ist ungültig: ${error.message}`;
      case "job_failed":
        return "Der Import konnte nicht starten. Details stehen im Server-Log (docker compose logs backend).";
    }
  }
  return "Das hat nicht geklappt: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}

/** "74 Dateien gefunden, 2 neu, 1 geändert (werden neu importiert), 1 nicht lesbar; 19 zu
 *  importieren"; counts of zero are left out. */
export function scanSummary(result: ScanResult): string {
  const found = `${formatNumber(result.files)} ${result.files === 1 ? "Datei" : "Dateien"} gefunden`;
  const missing = result.missing.length;
  const changes = [
    result.new.length > 0 && `${formatNumber(result.new.length)} neu`,
    result.replaced.length > 0 &&
      `${formatNumber(result.replaced.length)} geändert (werden neu importiert)`,
    missing > 0 && `${formatNumber(missing)} ${missing === 1 ? "fehlt" : "fehlen"}`,
    result.unreadable.length > 0 && `${formatNumber(result.unreadable.length)} nicht lesbar`,
  ].filter(Boolean);
  const pending =
    result.pending > 0 ? `${formatNumber(result.pending)} zu importieren` : "nichts zu importieren";
  return `${[found, ...(changes.length ? changes : ["keine Änderungen"])].join(", ")}; ${pending}`;
}

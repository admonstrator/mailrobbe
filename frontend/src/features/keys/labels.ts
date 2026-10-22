// German texts of the screens for keys of deleted selectors (D100 to D104): runs and their
// phases, lookups, today's DNS answer, the selector list's filter, the notices after an action.

import { ApiError } from "../../api/client";
import type {
  DkimKeysJob,
  DkimKeysPhase,
  DkimKeysTask,
  DnsStatus,
  ImportStatus,
  LookupOutcome,
  SelectorFilter,
} from "../../api/types";
import { formatDate, formatNumber } from "../../lib/format";

/** What a run does, as the title of its line: "Rekonstruktion läuft". */
export const TASK_LABELS: Record<DkimKeysTask, string> = {
  reconstruct: "Rekonstruktion",
  search: "Suche im Archiv",
  fetch: "Abfrage des Schlüsselarchivs",
  check: "Prüfung mit den gefundenen Schlüsseln",
};

export const PHASE_LABELS: Record<DkimKeysPhase, string> = {
  select: "Schlüsselnamen und Signaturen werden ausgewählt",
  reconstruct: "Schlüssel werden aus Signaturen berechnet",
  search: "Mails und Anhänge werden nach Schlüsseln durchsucht",
  fetch: "Das Schlüsselarchiv wird abgefragt",
  compare: "Schlüssel werden mit dem DNS und anderen Quellen abgeglichen",
  check: "Signaturen werden mit den Schlüsseln neu geprüft",
  aggregates: "Kennzahlen werden berechnet",
};

export const OUTCOME_LABELS: Record<LookupOutcome, string> = {
  found: "gefunden",
  not_found: "nichts gefunden",
  error: "Fehler",
};

/** Today's answer of the name in the DNS cache; null when it was never asked. */
export function dnsStatusLabel(status: DnsStatus | null): string {
  switch (status) {
    case "found":
      return "Schlüssel im DNS";
    case "not_found":
      return "nicht im DNS";
    case "temp_error":
      return "DNS-Fehler";
    default:
      return "nicht abgefragt";
  }
}

/** "02.03.2014 – 18.11.2019", the first and the last signature's t=; "–" without one. */
export function periodText(first: string | null, last: string | null): string {
  const days = [first, last].filter((iso) => iso !== null).map(formatDate);
  if (days.length === 0) return "–";
  return days.length === 1 || days[0] === days[1] ? days[0] : `${days[0]} – ${days[1]}`;
}

export const SELECTOR_FILTERS: readonly SelectorFilter[] = ["open", "resolved", "all"];

export const SELECTOR_FILTER_LABELS: Record<SelectorFilter, string> = {
  open: "offen",
  resolved: "geklärt",
  all: "alle",
};

/** "37 Schlüssel gefunden · 1.204 Mails geprüft, 85 geändert": what a run's figures say so
 *  far; figures of zero that say nothing yet are left out. */
export function runFigures(job: DkimKeysJob): string {
  const { names, keys_found, factorable, mails_checked, mails_changed } = job.progress;
  const parts = [
    names > 0 && `${formatNumber(names)} ${names === 1 ? "Schlüsselname" : "Schlüsselnamen"}`,
    `${formatNumber(keys_found)} Schlüssel gefunden`,
    factorable > 0 && `${formatNumber(factorable)} faktorisierbar`,
    (mails_checked > 0 || job.phase === "check") &&
      `${formatNumber(mails_checked)} Mails geprüft, ${formatNumber(mails_changed)} geändert`,
  ];
  return parts.filter(Boolean).join(" · ");
}

/** Why no key run can start now, or null: one run at a time (D46, D101). */
export function busyText(status: ImportStatus | undefined): string | null {
  if (status?.keys_job?.alive) return "Es läuft gerade eine Schlüsselsuche.";
  if (status?.import_job?.alive) return "Es läuft gerade ein Import.";
  if (status?.dkim_job?.alive) return "Es läuft gerade eine DKIM-Prüfung.";
  return null;
}

/** The notice for a key action the API refused or that failed. */
export function keysErrorText(error: Error): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "job_running":
        return "Es läuft bereits ein Import, eine DKIM-Prüfung oder eine Schlüsselsuche. Bitte warten, bis sie fertig ist.";
      case "no_job":
        return "Es läuft gerade keine Schlüsselsuche, die angehalten werden könnte.";
      case "archive_off":
        return "Das Schlüsselarchiv ist abgeschaltet (MAILROBBE_DKIM_KEY_ARCHIVE_URL=off).";
      case "invalid_key":
        return "Kein gültiger Schlüssel.";
      case "invalid_option":
        return `Eine Angabe ist ungültig: ${error.message}`;
      case "not_found":
        return "Diesen Schlüsselnamen gibt es im Archiv nicht.";
      case "job_failed":
        return "Der Lauf konnte nicht starten. Details stehen im Server-Log (docker compose logs backend).";
    }
  }
  return "Das hat nicht geklappt: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}

// German texts of the import dashboard: run states, steps, file statuses, error kinds, the
// notices after an action.

import { ApiError } from "../../api/client";
import type {
  DbActivity,
  DkimKey,
  ImportErrorKind,
  JobKind,
  MboxStatus,
  ScanResult,
  StepProgress,
  StepUnit,
} from "../../api/types";
import { DKIM_FILTER_LABELS } from "../../lib/dkim";
import { formatBytes, formatElapsed, formatNumber, formatRemaining } from "../../lib/format";
import type { FileFilter, RunState, StepState } from "./model";

/** The state badge beside the page's title "Import". */
export const RUN_BADGES: Record<RunState, string> = {
  none: "Noch kein Lauf",
  running: "Läuft",
  pausing: "Wird angehalten …",
  paused: "Angehalten",
  done: "Fertig",
  aborted: "Abgebrochen",
  orphaned: "Verwaist",
};

/** The steps of the runs (D110) by their key; a key missing here is shown as it is. */
export const STEP_LABELS: Record<string, string> = {
  scan: "Verzeichnis scannen",
  headers: "Header älterer Mails nachlesen",
  import: "Mails einlesen",
  duplicates: "Duplikate erkennen",
  threads: "Threads bilden",
  names: "Anzeigenamen bestimmen",
  documents: "Anhänge zu Dokumenten zusammenfassen",
  edges: "Beziehungen berechnen",
  person_stats: "Kennzahlen je Person",
  suggestions: "Alias-Vorschläge",
  global_stats: "Kennzahlen des Archivs",
  archives: "Archive und angehängte Mails auspacken",
  attachments: "Text aus Anhängen lesen",
  passwords: "Kennwörter suchen und probieren",
  metadata: "Metadaten aus Anhängen lesen",
  calendar: "Kalendereinladungen lesen",
  near_texts: "Fingerabdrücke der Mailtexte",
  near_groups: "Nahezu gleiche Mails gruppieren",
  hidden: "Ausblendregeln anwenden",
  paragraphs: "Mailtexte in Absätze teilen",
  blocks: "Standardblöcke erkennen",
  entities: "Entitäten erkennen",
  places: "Orte bestimmen",
  signals: "Signale berechnen",
  topic_terms: "Begriffe zählen",
  topic_labels: "Schreibweisen der Begriffe",
  topic_periods: "Begriffe je Zeitraum",
  topic_clusters: "Themen-Cluster bilden",
  check: "Signaturen prüfen",
  // dkim-keys runs (D101)
  select: "Selektoren auswählen",
  reconstruct: "Schlüssel rekonstruieren",
  search: "Archivtexte nach Schlüsseln durchsuchen",
  fetch: "Schlüsselarchiv abfragen",
  compare: "Mit anderen Quellen abgleichen",
  // map runs (D246)
  directories: "Verzeichnis der Kartendatei lesen",
  tiles: "Kartenkacheln laden",
  finish: "Detailkarte fertigstellen",
};

/** The steps of an AI run (D187), whose keys the other runs use for other steps. */
export const AI_STEP_LABELS: Record<string, string> = {
  check: "Dienste prüfen",
  ocr: "Texterkennung",
  transcribe: "Transkription",
  summarize: "Zusammenfassen",
  ask: "Fragen zu Personen",
  aliases: "Personen abgleichen",
  entities: "Entitäten erkennen",
  entity_figures: "Kennzahlen der Entitäten",
  signals: "Signale berechnen",
};

/** The German label of a step; kind tells apart the runs whose keys name different steps. */
export const stepLabel = (key: string, kind?: JobKind) =>
  (kind === "ai" ? AI_STEP_LABELS[key] : undefined) ?? STEP_LABELS[key] ?? key;

const UNIT_TEXTS: Record<Exclude<StepUnit, "bytes">, [one: string, many: string, of: string]> = {
  mails: ["Mail", "Mails", "Mails"],
  documents: ["Dokument", "Dokumente", "Dokumenten"],
  names: ["Selektor", "Selektoren", "Selektoren"],
  domains: ["Domain", "Domains", "Domains"],
  places: ["Ort", "Orte", "Orten"],
  pages: ["Seite", "Seiten", "Seiten"],
  texts: ["Text", "Texte", "Texten"],
  pairs: ["Paar", "Paare", "Paaren"],
  groups: ["Gruppe", "Gruppen", "Gruppen"],
  questions: ["Frage", "Fragen", "Fragen"],
};

const rateFormat = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
const rateNumber = (rate: number) =>
  rate >= 10 ? formatNumber(Math.round(rate)) : rateFormat.format(rate);

/** "1.200 von 5.000 Dokumenten", or "5.000 Dokumente" without a total; bytes as sizes. */
function amount(unit: StepUnit, done: number, total: number | null): string {
  if (unit === "bytes") {
    return total === null ? formatBytes(done) : `${formatBytes(done)} von ${formatBytes(total)}`;
  }
  const [one, many, of] = UNIT_TEXTS[unit];
  if (total === null) return `${formatNumber(done)} ${done === 1 ? one : many}`;
  return `${formatNumber(done)} von ${formatNumber(total)} ${total === 1 ? one : of}`;
}

function rateText(unit: StepUnit, rate: number): string {
  if (unit === "bytes") return `${formatBytes(rate)}/s`;
  const many = UNIT_TEXTS[unit][1];
  // A key reconstruction takes about a minute per name, which per second would read "0".
  return rate < 0.1 ? `${rateNumber(rate * 60)} ${many}/min` : `${rateNumber(rate)} ${many}/s`;
}

/** What a step did or does, after its label: "1.200 von 5.000 Dokumenten · 40 Dokumente/s ·
 *  Restzeit geschätzt 2 min · läuft seit 30 s", "fertig in 12 s", "wartet". The time of a running
 *  step counts on by extra seconds, the age of the report. */
export function stepDetail(step: StepProgress, state: StepState, extra = 0): string {
  const { unit, done, total, rate, eta_seconds: eta } = step;
  const elapsed = formatElapsed(step.seconds + extra);
  switch (state) {
    case "waiting":
      return "wartet";
    case "unreached":
      return "nicht erreicht";
    case "skipped":
      return "nicht nötig";
    case "running": {
      const parts = unit === null ? [] : [amount(unit, done, total)];
      if (unit !== null && rate !== null && rate > 0) parts.push(rateText(unit, rate));
      if (eta !== null) parts.push(`Restzeit geschätzt ${formatRemaining(eta)}`);
      parts.push(`läuft seit ${elapsed}`);
      return parts.join(" · ");
    }
    case "done":
      return unit === null || done === 0
        ? `fertig in ${elapsed}`
        : `fertig in ${elapsed} · ${amount(unit, done, null)}`;
    case "stopped":
      return unit === null
        ? `angehalten nach ${elapsed}`
        : `angehalten bei ${amount(unit, done, total)} nach ${elapsed}`;
    case "failed":
      return `Fehler nach ${elapsed}`;
    case "aborted":
      return unit === null
        ? `abgebrochen nach ${elapsed}`
        : `abgebrochen bei ${amount(unit, done, total)} nach ${elapsed}`;
  }
}

/** What the database does for a run (D110): "rechnet seit 1 min 9 s", "wartet seit 4 s auf eine
 *  Sperre"; wait is Postgres's wait_event_type. */
export function databaseText(activity: DbActivity, extra = 0): string {
  const since = formatElapsed(activity.seconds + extra);
  switch (activity.wait) {
    case null:
      return `rechnet seit ${since}`;
    case "Lock":
      return `wartet seit ${since} auf eine Sperre`;
    case "IO":
      return `liest und schreibt seit ${since}`;
    default:
      return `arbeitet seit ${since}`;
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

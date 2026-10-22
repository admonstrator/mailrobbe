// German texts of the AI page and of machine made texts elsewhere (D180 to D189): engines, task
// and result states, the line of a recognised text, estimates, the notices after an action.

import { ApiError } from "../../api/client";
import type {
  AiEstimate,
  AiQueued,
  AiResultState,
  AiSummaryResult,
  AiSummaryTask,
  AiTarget,
  AiTaskStatus,
  AiWorkList,
  DocumentAiResult,
  OcrEngine,
  OcrEngineChoice,
  TextOrigin,
} from "../../api/types";
import { formatDate, formatNumber, formatRemaining } from "../../lib/format";

export const ENGINE_LABELS: Record<OcrEngineChoice, string> = {
  auto: "Automatisch",
  tesseract: "Tesseract",
  vision: "Bildmodell",
};

/** What each choice does (D182), for the engine selects. */
export const ENGINE_HINTS: Record<OcrEngineChoice, string> = {
  auto: "Scans mit Tesseract, Bilder mit dem Bildmodell; unsichere Seiten liest das Bildmodell noch einmal.",
  tesseract: "Tesseract im Container: schnell, erfindet nichts, nennt seine Sicherheit je Wort.",
  vision:
    "Das Bildmodell auf dem Rechner: liest Handschrift, Fotos und schlechte Scans besser, aber etwa 30-mal langsamer.",
};

export const TASK_STATUS_LABELS: Record<AiTaskStatus, string> = {
  waiting: "vorgemerkt",
  running: "läuft",
  done: "fertig",
  failed: "fehlgeschlagen",
  cancelled: "abgebrochen",
};

/** Every task status, in the order of the queue's filter. */
export const TASK_STATUSES: readonly AiTaskStatus[] = [
  "waiting",
  "running",
  "failed",
  "cancelled",
  "done",
];

export const RESULT_STATE_LABELS: Record<AiResultState, string> = {
  valid: "gültig",
  replaced: "ersetzt",
  discarded: "verworfen",
};

export const WORK_LIST_TITLES: Record<AiWorkList, string> = {
  scanned: "Gescannte PDFs",
  images: "Bilder ab 100 KB",
};

export const WORK_LIST_HINTS: Record<AiWorkList, string> = {
  scanned: "PDFs, deren Seiten nur Bilder sind, ohne Textebene; noch ohne erkannten Text.",
  images:
    "Fotos und Bilder ab 100 KB in höchstens 50 Mails; kleinere und Logos aus Signaturen bleiben außen vor.",
};

/** The engine of a result as a reader knows it: Tesseract, the model's name, or both. */
export function engineName(engine: string, model: string | null): string {
  const vision = model || ENGINE_LABELS.vision;
  if (engine === "tesseract") return "Tesseract";
  if (engine === "text") return model || TEXT_MODEL_LABEL; // a summary (D300)
  if (engine === "vision") return vision;
  return `Tesseract und ${vision}`;
}

/** "Seite 3", "Seiten 2, 5 und 7" */
export function pageNumbers(numbers: number[]): string {
  const listed = numbers.map(formatNumber);
  if (listed.length <= 1) return `Seite ${listed.join("")}`;
  return `Seiten ${listed.slice(0, -1).join(", ")} und ${listed[listed.length - 1]}`;
}

/** "Maschinell erkannt · Tesseract · 22.10.2026 · 3 von 4 Seiten" (D189). */
export function machineLine(result: DocumentAiResult): string {
  const read = result.pages_read - result.failed.length;
  const total = result.pages_total ?? result.pages_read;
  const pages = `${formatNumber(read)} von ${formatNumber(total)} ${total === 1 ? "Seite" : "Seiten"}`;
  return [
    "Maschinell erkannt",
    engineName(result.engine, result.model),
    formatDate(result.created_at),
    pages,
  ].join(" · ");
}

/** "ca. 40 min" or "geschätzt ca. 40 min" for the rule of thumb (D188). */
export function estimateText(estimate: AiEstimate): string {
  const time = `ca. ${formatRemaining(estimate.seconds)}`;
  return estimate.estimated ? `geschätzt ${time}` : time;
}

/** The estimate of the engine a choice takes; auto takes the list's own. */
export function estimateFor(
  estimates: AiEstimate[],
  choice: OcrEngineChoice,
  auto: OcrEngine,
): AiEstimate | undefined {
  const engine = choice === "auto" ? auto : choice;
  return estimates.find((estimate) => estimate.engine === engine);
}

/** "3 Dokumente vorgemerkt, 1 schon vorgemerkt, 2 Logos ausgelassen" */
export function queuedText(queued: AiQueued): string {
  const parts = [
    `${formatNumber(queued.queued)} ${queued.queued === 1 ? "Dokument" : "Dokumente"} vorgemerkt`,
    queued.raised > 0 && `${formatNumber(queued.raised)} schon vorgemerkt`,
    queued.unreadable > 0 &&
      `${formatNumber(queued.unreadable)} ohne Texterkennung (eigener Text oder zu groß)`,
    queued.logos > 0 &&
      `${formatNumber(queued.logos)} ${queued.logos === 1 ? "Logo" : "Logos"} ausgelassen`,
  ].filter(Boolean);
  return parts.join(", ");
}

/** What starting the recognition of one document did (D280). */
export function startedText(queued: AiQueued): string {
  if (queued.queued + queued.raised === 0) {
    return "Dieses Dokument kann die Texterkennung nicht lesen.";
  }
  switch (queued.run) {
    case "started":
      return "Die Texterkennung läuft; das Ergebnis erscheint hier, sobald sie fertig ist.";
    case "running":
      return "Ein KI-Lauf ist schon unterwegs und liest dieses Dokument als nächstes.";
    case "busy":
      return "Vorgemerkt: Gerade läuft ein Import. Danach lässt sich der Lauf auf der Seite „KI“ starten.";
    default:
      return "Vorgemerkt: Der nächste KI-Lauf liest dieses Dokument zuerst.";
  }
}

/** The notice for an action the API refused or that failed. */
export function aiErrorText(error: Error): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "job_running":
        return "Es läuft bereits ein Import, eine DKIM-Prüfung, eine Schlüsselsuche oder ein KI-Lauf. Bitte warten, bis er fertig ist.";
      case "no_job":
        return "Es läuft gerade kein KI-Lauf, der angehalten werden könnte.";
      case "mbox_dir_missing":
        return "Das MBOX-Verzeichnis ist für den Server nicht lesbar; ohne es lassen sich die Anhänge nicht lesen.";
      case "invalid_option":
        return `Eine Einstellung ist ungültig: ${error.message}`;
      case "too_many_documents":
        return "Die Auswahl umfasst mehr als 50.000 Dokumente. Bitte enger filtern.";
      case "invalid_selection":
        return "Die Auswahl ist leer oder nicht eindeutig.";
      case "not_found":
        return "Das gibt es nicht mehr; die Ansicht wird neu geladen.";
      case "job_failed":
        return "Der KI-Lauf konnte nicht starten. Details stehen im Server-Log (docker compose logs backend).";
    }
  }
  return "Das hat nicht geklappt: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}

// Summaries (milestone 17, D300 to D311) ------------------------------------------------------

export const TEXT_MODEL_LABEL = "Textmodell";

/** A summarize task or result in the lists of the page "KI". */
export const SUMMARY_LABEL = "Zusammenfassung";

/** The text of a document a summary read, when it is not the file's own (D302). */
export const SUMMARY_ORIGIN_LABELS: Record<TextOrigin, string | null> = {
  extracted: null,
  ocr: "aus dem erkannten Text",
  transcript: "aus dem Transkript",
};

export const SHORT_SUMMARY_TEXT =
  "Zu wenig eigener Text für eine Zusammenfassung; nur Schlagwörter und Hinweise.";

/** "Maschinell erzeugt · Modell · 22.10.2026 · über einen Dienst im Internet · aus dem erkannten
 *  Text" (D311). */
export function summaryLine(result: AiSummaryResult): string {
  return [
    "Maschinell erzeugt",
    result.model || TEXT_MODEL_LABEL,
    formatDate(result.created_at),
    result.remote && "über einen Dienst im Internet",
    result.origin && SUMMARY_ORIGIN_LABELS[result.origin],
  ]
    .filter(Boolean)
    .join(" · ");
}

/** "Zusammenfassung der ersten 3 von 7 Abschnitten" for a cut text (D303); null when whole. */
export function partsText(result: AiSummaryResult): string | null {
  if (result.parts_total <= result.parts_read) return null;
  const read =
    result.parts_read === 1 ? "des ersten" : `der ersten ${formatNumber(result.parts_read)}`;
  return `Zusammenfassung ${read} von ${formatNumber(result.parts_total)} Abschnitten`;
}

/** "Für die Zusammenfassung vorgemerkt", "Zusammenfassung läuft · Teil 2 von 4". */
export function summaryTaskText(task: AiSummaryTask): string {
  if (task.status !== "running") return "Für die Zusammenfassung vorgemerkt";
  const total = task.parts_total ?? 0;
  if (total <= 1) return "Zusammenfassung läuft";
  const part = Math.min(task.parts_done + 1, total);
  return `Zusammenfassung läuft · Teil ${formatNumber(part)} von ${formatNumber(total)}`;
}

/** "1 Mail", "12 Mails" */
export function mailCount(mails: number): string {
  return `${formatNumber(mails)} ${mails === 1 ? "Mail" : "Mails"}`;
}

/** What starting the summary of one mail or document did (D307), like startedText. */
export function summaryStartedText(queued: AiQueued, target: AiTarget): string {
  const element = target === "mail" ? "diese Mail" : "dieses Dokument";
  if (queued.queued + queued.raised === 0) return "Hier gibt es nichts zusammenzufassen.";
  switch (queued.run) {
    case "started":
      return "Die Zusammenfassung läuft; sie erscheint hier, sobald sie fertig ist.";
    case "running":
      return `Ein KI-Lauf ist schon unterwegs und fasst ${element} als nächstes zusammen.`;
    case "busy":
      return "Vorgemerkt: Gerade läuft ein Import. Danach lässt sich der Lauf auf der Seite „KI“ starten.";
    default:
      return `Vorgemerkt: Der nächste KI-Lauf fasst ${element} zuerst zusammen.`;
  }
}

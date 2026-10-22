// German texts of the AI page and of machine made texts elsewhere (D180 to D189, D290 to D296):
// engines, task and result states, the line of a recognised text or a transcript, estimates, the
// notices after an action.

import { ApiError } from "../../api/client";
import type {
  AiEngine,
  AiEstimate,
  AiQueued,
  AiResultState,
  AiSummaryResult,
  AiSummaryTask,
  AiTarget,
  AiTaskKind,
  AiTaskStatus,
  AiWorkList,
  DocumentAiResult,
  DocumentTranscriptResult,
  OcrEngineChoice,
  TextOrigin,
} from "../../api/types";
import { formatClock, formatDate, formatNumber, formatRemaining } from "../../lib/format";

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

/** What a task or a result does (D186, D295). */
export const TASK_KIND_LABELS: Record<AiTaskKind, string> = {
  ocr: "Texterkennung",
  transcribe: "Transkription",
  summarize: "Zusammenfassung",
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
  media: "Sprachnachrichten und Videos",
};

export const WORK_LIST_HINTS: Record<AiWorkList, string> = {
  scanned: "PDFs, deren Seiten nur Bilder sind, ohne Textebene; noch ohne erkannten Text.",
  images:
    "Fotos und Bilder ab 100 KB in höchstens 50 Mails; kleinere und Logos aus Signaturen bleiben außen vor.",
  media: "Aufnahmen und Videos mit Ton, noch ohne Transkript.",
};

/** The engine of a result as a reader knows it: Tesseract, the model's name, or both. */
export function engineName(engine: string, model: string | null): string {
  const vision = model || ENGINE_LABELS.vision;
  if (engine === "tesseract") return "Tesseract";
  if (engine === "text") return model || TEXT_MODEL_LABEL; // a summary (D300)
  if (engine === "vision") return vision;
  return `Tesseract und ${vision}`;
}

// The transcription models by the name ai_result.model stores (D290): short where a transcript
// is marked, in full where the AI page describes the transcriber.
const TRANSCRIBERS: Record<string, { short: string; full: string }> = {
  "parakeet-tdt-0.6b-v3": {
    short: "Parakeet v3",
    full: "Parakeet TDT 0.6B v3 (NVIDIA, CC-BY-4.0)",
  },
};

/** "Parakeet v3", in full "Parakeet TDT 0.6B v3 (NVIDIA, CC-BY-4.0)"; another model by its
 *  name. */
export function transcriberName(model: string | null, full = false): string {
  const known = model ? TRANSCRIBERS[model] : undefined;
  if (!known) return model || "Spracherkennung";
  return full ? known.full : known.short;
}

/** "12 Minuten", "1 Minute", "2,5 Minuten": minutes of recordings, to a tenth below ten. */
export function minutesText(minutes: number): string {
  const rounded = minutes < 10 ? Math.round(minutes * 10) / 10 : Math.round(minutes);
  const shown = rounded.toLocaleString("de-DE");
  return `${shown} ${rounded === 1 ? "Minute" : "Minuten"}`;
}

/** "Maschinell transkribiert · Parakeet v3 · 22.10.2026 · Aufnahme 3:12" (D296), and "die
 *  ersten 180 Minuten von 245" when the run stopped at its limit of minutes (D292). */
export function transcriptLine(result: DocumentTranscriptResult): string {
  const { duration, transcribed } = result;
  const cut =
    duration !== null && transcribed !== null && transcribed < duration - 1
      ? `die ersten ${formatNumber(Math.floor(transcribed / 60))} Minuten von ${formatNumber(Math.ceil(duration / 60))}`
      : null;
  return [
    "Maschinell transkribiert",
    transcriberName(result.model),
    formatDate(result.created_at),
    duration !== null && `Aufnahme ${formatClock(duration)}`,
    cut,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** What a transcript without words says (D292, D296). */
export function silenceText(result: Pick<DocumentTranscriptResult, "audio">): string {
  return result.audio ? "Keine Sprache erkannt." : "Die Datei hat keine Tonspur.";
}

/** The tasks of every kind by status, as the queue's filters count them. */
export function queueCounts(
  queue: Record<AiTaskKind, Record<AiTaskStatus, number>>,
): Record<AiTaskStatus, number> {
  const counts = { waiting: 0, running: 0, done: 0, failed: 0, cancelled: 0 };
  for (const kind of Object.values(queue)) {
    for (const status of TASK_STATUSES) counts[status] += kind[status];
  }
  return counts;
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
  auto: AiEngine,
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
      `${formatNumber(queued.unreadable)} ohne Texterkennung oder Transkription (eigener Text oder zu groß)`,
    queued.logos > 0 &&
      `${formatNumber(queued.logos)} ${queued.logos === 1 ? "Logo" : "Logos"} ausgelassen`,
  ].filter(Boolean);
  return parts.join(", ");
}

/** What starting the recognition or the transcription of one document did (D280, D295). */
export function startedText(queued: AiQueued, kind: "ocr" | "transcribe" = "ocr"): string {
  const work = TASK_KIND_LABELS[kind];
  if (queued.queued + queued.raised === 0) {
    return kind === "ocr"
      ? "Dieses Dokument kann die Texterkennung nicht lesen."
      : "Diese Aufnahme kann die Transkription nicht lesen.";
  }
  switch (queued.run) {
    case "started":
      return `Die ${work} läuft; das Ergebnis erscheint hier, sobald sie fertig ist.`;
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

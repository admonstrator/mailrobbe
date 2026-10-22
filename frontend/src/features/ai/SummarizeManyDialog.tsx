import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { ApiError, apiPost } from "../../api/client";
import { useAiStatus, useEnqueueAi } from "../../api/queries";
import {
  AI_QUEUE_LIMIT,
  type AiQueued,
  type AiQueueRequest,
  type DocumentFilters,
  type MailFilters,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { Dialog } from "../persons/Dialog";
import { aiErrorText } from "./labels";
import styles from "./SummarizeManyDialog.module.css";

/** What is summarised (D308): mails by id or by the mail list's filters (an Akte is
 *  `{ collection: [id] }`), or the documents of the document list's filters. */
export type SummarizeSelection =
  { mail_ids: number[] } | { mail_filters: MailFilters } | { filters: DocumentFilters };

/** The title of a "Zusammenfassen" that cannot work yet (D300). */
export const NO_TEXT_SERVICE = "Kein Textmodell eingerichtet (MAILROBBE_AI_TEXT_URL)";

/** "Zusammenfassen" for a selection (D308): opens the dialog. Without a usable text service it
 *  is shown disabled with the setting that is missing, so the team learns the function exists. */
export function SummarizeButton({
  selection,
  size = "sm",
}: {
  selection: SummarizeSelection;
  size?: "md" | "sm";
}) {
  const status = useAiStatus();
  const [open, setOpen] = useState(false);
  const usable = status.data?.text === true;
  return (
    <>
      <Button
        size={size}
        disabled={!usable}
        title={status.data && !usable ? NO_TEXT_SERVICE : undefined}
        onClick={() => setOpen(true)}
      >
        Zusammenfassen
      </Button>
      {open && <SummarizeManyDialog selection={selection} onClose={() => setOpen(false)} />}
    </>
  );
}

function ofMails(selection: SummarizeSelection): boolean {
  return "mail_ids" in selection || "mail_filters" in selection;
}

function elements(count: number, mails: boolean): string {
  const noun = mails ? (count === 1 ? "Mail" : "Mails") : count === 1 ? "Dokument" : "Dokumente";
  return `${formatNumber(count)} ${noun}`;
}

/** "etwa 2 Std. 10 Min.", "etwa 3 Tage 4 Std.", "weniger als 1 Min." */
export function durationText(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return "weniger als 1 Min.";
  if (minutes < 60) return `etwa ${minutes} Min.`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return rest ? `etwa ${hours} Std. ${rest} Min.` : `etwa ${hours} Std.`;
  }
  const days = Math.floor(hours / 24);
  const rest = hours % 24;
  const day = `${days} ${days === 1 ? "Tag" : "Tage"}`;
  return rest ? `etwa ${day} ${rest} Std.` : `etwa ${day}`;
}

/** What "Zusammenfassen" did (D308): "12 vorgemerkt; der Lauf hat begonnen". */
export function summarizedText(queued: AiQueued): string {
  const tasks = queued.queued + queued.raised;
  if (tasks === 0) return "Nichts vorgemerkt: Diese Auswahl hat nichts zusammenzufassen.";
  const counted = `${formatNumber(tasks)} vorgemerkt`;
  switch (queued.run) {
    case "started":
      return `${counted}; der Lauf hat begonnen.`;
    case "running":
      return `${counted}; ein KI-Lauf läuft schon und nimmt sie mit.`;
    case "busy":
      return `${counted}; der Lauf wartet, bis der Import fertig ist.`;
    default:
      return `${counted}; der nächste KI-Lauf nimmt sie mit.`;
  }
}

/** Why the preview or the queuing was refused, as a sentence. */
function refusalText(error: Error, mails: boolean): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "too_many_mails":
      case "too_many_documents":
        return `Höchstens ${formatNumber(AI_QUEUE_LIMIT)} auf einmal; bitte die Auswahl eingrenzen.`;
      case "invalid_option":
        return `${NO_TEXT_SERVICE}, siehe Seite „KI“.`;
      case "empty_selection":
        return mails ? "Diese Auswahl enthält keine Mails." : "Diese Auswahl ist leer.";
    }
  }
  return aiErrorText(error);
}

/** Summarising many (D308): first a preview of how many, how many are short and how long it
 *  takes, then "Zusammenfassen" queues them and starts a run. */
export function SummarizeManyDialog({
  selection,
  onClose,
}: {
  selection: SummarizeSelection;
  onClose: () => void;
}) {
  const mails = ofMails(selection);
  const request: AiQueueRequest = { kind: "summarize", ...selection };
  // A preview writes nothing; it is asked again each time the dialog opens.
  const preview = useQuery({
    queryKey: ["summarize-preview", request],
    queryFn: () => apiPost<AiQueued>("/api/ai/tasks", { ...request, preview: true }),
    retry: false,
    gcTime: 0,
  });
  const enqueue = useEnqueueAi();
  const [done, setDone] = useState<AiQueued | null>(null);
  const error = preview.error ?? enqueue.error;

  return (
    <Dialog title="Zusammenfassen" onClose={onClose}>
      {done ? (
        <p className={styles.text} role="status">
          {summarizedText(done)}
        </p>
      ) : error ? (
        <p className={styles.warning} role="alert">
          {refusalText(error, mails)}
        </p>
      ) : preview.data ? (
        <Preview queued={preview.data} mails={mails} />
      ) : (
        <p className={styles.text}>
          <Spinner label="Die Auswahl wird gezählt" /> Die Auswahl wird gezählt …
        </p>
      )}
      <div className={styles.foot}>
        {(done || error) && (
          <Link to="/ki" className={styles.link}>
            zur Seite „KI“
          </Link>
        )}
        {done || error ? (
          <Button variant="primary" onClick={onClose}>
            Schließen
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>Abbrechen</Button>
            <Button
              variant="primary"
              disabled={
                !preview.data ||
                preview.data.queued + preview.data.raised === 0 ||
                enqueue.isPending
              }
              onClick={() => enqueue.mutate({ ...request, start: true }, { onSuccess: setDone })}
            >
              Zusammenfassen
            </Button>
          </>
        )}
      </div>
    </Dialog>
  );
}

function Preview({ queued, mails }: { queued: AiQueued; mails: boolean }) {
  const tasks = queued.queued + queued.raised;
  const estimate = queued.estimate;
  if (tasks === 0) {
    return (
      <p className={styles.text}>
        {queued.unreadable > 0
          ? `Nichts zusammenzufassen: ${mails ? "Diese Mails haben" : "Diese Dokumente haben"} keinen Text, der sich zusammenfassen ließe.`
          : "Nichts zusammenzufassen."}
      </p>
    );
  }
  return (
    <>
      <p className={styles.count}>{elements(tasks, mails)}</p>
      <ul className={styles.facts}>
        {queued.short > 0 && (
          <li>
            {`davon ${formatNumber(queued.short)} mit zu wenig eigenem Text: nur Schlagwörter und Hinweise`}
          </li>
        )}
        {queued.raised > 0 && <li>{`davon ${formatNumber(queued.raised)} schon vorgemerkt`}</li>}
        {queued.unreadable > 0 && (
          <li>
            {`${elements(queued.unreadable, mails)} ohne Text, der sich zusammenfassen ließe, bleiben außen vor`}
          </li>
        )}
        {estimate && (
          <li>
            {`Dauer ${durationText(estimate.seconds)}${estimate.estimated ? " (geschätzt)" : ""}`}
            {estimate.model && ` mit ${estimate.model}`}
          </li>
        )}
      </ul>
      <p className={styles.hint}>
        „Zusammenfassen“ merkt sie vor und startet einen KI-Lauf. Zusammenfassungen, Schlagwörter
        und Hinweise sind maschinell erzeugt und lassen sich auf der Seite „KI“ verwerfen.
      </p>
    </>
  );
}

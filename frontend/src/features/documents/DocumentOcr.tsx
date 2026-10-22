import { useId, useState } from "react";
import { Link } from "react-router";

import { useAiStatus, useDiscardAi, useEnqueueAi } from "../../api/queries";
import type {
  AiQueued,
  DocumentDetail,
  DocumentFilters,
  DocumentSummary,
  OcrEngineChoice,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { formatDate, formatNumber } from "../../lib/format";
import { EngineSelect } from "../ai/EngineSelect";
import {
  aiErrorText,
  engineName,
  machineLine,
  pageNumbers,
  queuedText,
  startedText,
} from "../ai/labels";
import { Dialog } from "../persons/Dialog";
import styles from "./DocumentOcr.module.css";

/** What the text recognition did and can do for one document (D189), in its text card: the line
 *  "Maschinell erkannt · Tesseract · Datum · n von m Seiten" with the uncertain and failed pages,
 *  an open task ("vorgemerkt", "läuft"), and "Text erkennen", "Neu erkennen" and "Verwerfen".
 *  Nothing for a document OCR cannot read and that has no result. */
export function OcrBar({ document }: { document: DocumentDetail }) {
  const result = document.ai?.result ?? null;
  const task = document.ai?.task ?? null;
  const [dialog, setDialog] = useState<"again" | "discard" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const enqueue = useEnqueueAi();
  if (!result && !task && !document.ocr_readable) return null;

  // Starts a run for just this document at once (D280).
  const queue = (engine: OcrEngineChoice) =>
    enqueue.mutate(
      { document_ids: [document.id], single: true, engine, start: true },
      {
        onSuccess: (queued) => {
          setDialog(null);
          setNotice(startedText(queued));
        },
        onError: (error) => setNotice(aiErrorText(error)),
      },
    );

  return (
    <div className={styles.bar}>
      {result && result.characters > 0 && (
        <p className={styles.line}>
          <span>
            {machineLine(result)}
            {result.remote && " · über einen Dienst im Internet"}
          </span>
        </p>
      )}
      {result && result.characters === 0 && (
        <p className={styles.line}>
          {`Maschinell geprüft · ${engineName(result.engine, result.model)} · ${formatDate(result.created_at)}: keine Schrift gefunden.`}
        </p>
      )}
      {result && result.uncertain.length > 0 && (
        <p className={styles.note}>{`Unsicher gelesen: ${pageNumbers(result.uncertain)}.`}</p>
      )}
      {result && result.failed.length > 0 && (
        <p className={styles.warning}>
          {`Nicht gelesen: ${pageNumbers(result.failed)}. „Neu erkennen“ versucht sie noch einmal.`}
        </p>
      )}
      {task ? (
        <p className={styles.task}>
          {task.status === "running"
            ? `Texterkennung läuft${task.pages_read > 0 ? ` · ${formatNumber(task.pages_read)} ${task.pages_read === 1 ? "Seite" : "Seiten"} gelesen` : ""}`
            : "Für die Texterkennung vorgemerkt"}
          {" · "}
          <Link to="/ki">zur Seite „KI“</Link>
        </p>
      ) : (
        <div className={styles.actions}>
          {!result && document.ocr_readable && (
            <Button size="sm" disabled={enqueue.isPending} onClick={() => queue("auto")}>
              Text erkennen
            </Button>
          )}
          {result && (
            <>
              <Button size="sm" onClick={() => setDialog("again")}>
                Neu erkennen
              </Button>
              <Button size="sm" variant="link" onClick={() => setDialog("discard")}>
                Verwerfen
              </Button>
            </>
          )}
        </div>
      )}
      {notice && (
        <p className={styles.note} role="status">
          {notice}
        </p>
      )}
      {dialog === "again" && (
        <AgainDialog pending={enqueue.isPending} onQueue={queue} onClose={() => setDialog(null)} />
      )}
      {dialog === "discard" && result && (
        <DiscardDialog resultId={result.id} onClose={() => setDialog(null)} onDone={setNotice} />
      )}
    </div>
  );
}

/** "Neu erkennen" with the engine of choice; Tesseract only without a vision model. */
function AgainDialog({
  pending,
  onQueue,
  onClose,
}: {
  pending: boolean;
  onQueue: (engine: OcrEngineChoice) => void;
  onClose: () => void;
}) {
  const id = useId();
  const status = useAiStatus();
  const vision = status.data?.vision ?? false;
  const [engine, setEngine] = useState<OcrEngineChoice>("vision");
  const chosen = vision ? engine : "tesseract";
  return (
    <Dialog title="Text neu erkennen?" onClose={onClose}>
      <p className={styles.text}>
        Ein KI-Lauf liest das Dokument gleich noch einmal. Sein neuer Text ersetzt den bisherigen
        erst, wenn er Schrift gefunden hat; der bisherige bleibt bis dahin durchsuchbar.
      </p>
      <EngineSelect id={id} value={chosen} vision={vision} onChange={setEngine} />
      <div className={styles.foot}>
        <Button onClick={onClose}>Abbrechen</Button>
        <Button
          variant="primary"
          disabled={pending || status.isPending}
          onClick={() => onQueue(chosen)}
        >
          Jetzt erkennen
        </Button>
      </div>
    </Dialog>
  );
}

/** "Verwerfen" of a recognised text or, with transcript, of a transcript (D185, D294), after a
 *  confirmation; onDone gets the notice. */
export function DiscardDialog({
  resultId,
  transcript = false,
  onClose,
  onDone,
}: {
  resultId: number;
  transcript?: boolean;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const discard = useDiscardAi();
  return (
    <Dialog
      title={transcript ? "Transkript verwerfen?" : "Erkannten Text verwerfen?"}
      onClose={onClose}
    >
      <p className={styles.text}>
        {transcript
          ? "Das maschinell erstellte Transkript wird aus der Suche genommen. Die Aufnahme bekommt ein früheres Transkript zurück oder steht wieder ohne Text da, wie der Import sie fand. Das Ergebnis bleibt als verworfen auf der Seite „KI“ verzeichnet."
          : "Der maschinell erkannte Text wird aus der Suche genommen. Das Dokument bekommt einen früher erkannten Text zurück oder steht wieder ohne Text da, wie der Import es fand. Das Ergebnis bleibt als verworfen auf der Seite „KI“ verzeichnet."}
      </p>
      {discard.error && (
        <p className={styles.warning} role="alert">
          {aiErrorText(discard.error)}
        </p>
      )}
      <div className={styles.foot}>
        <Button onClick={onClose}>Abbrechen</Button>
        <Button
          variant="primary"
          disabled={discard.isPending}
          onClick={() =>
            discard.mutate(
              { result: resultId },
              {
                onSuccess: () => {
                  onDone(
                    transcript
                      ? "Das Transkript ist verworfen."
                      : "Der erkannte Text ist verworfen.",
                  );
                  onClose();
                },
              },
            )
          }
        >
          Verwerfen
        </Button>
      </div>
    </Dialog>
  );
}

/** "Für KI vormerken" for the document list's current filter (D186): offered when the filter
 *  holds documents OCR can read, with their count and a confirmation. */
export function AiQueueButton({
  filters,
  summary,
}: {
  filters: DocumentFilters;
  summary: DocumentSummary | undefined;
}) {
  const [open, setOpen] = useState(false);
  const readable = summary?.ocr_readable ?? 0;
  if (readable === 0) return null;
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Für KI vormerken
      </Button>
      {open && <QueueDialog filters={filters} readable={readable} onClose={() => setOpen(false)} />}
    </>
  );
}

function QueueDialog({
  filters,
  readable,
  onClose,
}: {
  filters: DocumentFilters;
  readable: number;
  onClose: () => void;
}) {
  const id = useId();
  const status = useAiStatus();
  const vision = status.data?.vision ?? false;
  const [engine, setEngine] = useState<OcrEngineChoice>("auto");
  const [logos, setLogos] = useState(false);
  const [done, setDone] = useState<AiQueued | null>(null);
  const enqueue = useEnqueueAi();
  const chosen = vision ? engine : "tesseract";
  const noun = readable === 1 ? "Dokument" : "Dokumente";

  return (
    <Dialog title="Für die Texterkennung vormerken?" onClose={onClose}>
      {done ? (
        <>
          <p className={styles.text} role="status">
            {`${queuedText(done)}. Der nächste KI-Lauf liest sie; starten lässt er sich auf der Seite „KI“.`}
          </p>
          <div className={styles.foot}>
            <Link to="/ki" className={styles.link}>
              Zur Seite „KI“
            </Link>
            <Button variant="primary" onClick={onClose}>
              Schließen
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className={styles.text}>
            {`${formatNumber(readable)} ${noun} dieser Auswahl kann die Texterkennung lesen: gescannte PDFs und Bilder ohne eigenen Text. Ihr Text wird als „maschinell erkannt“ gekennzeichnet und lässt sich wieder verwerfen.`}
          </p>
          <EngineSelect id={id} value={chosen} vision={vision} onChange={setEngine} />
          <Checkbox checked={logos} onChange={setLogos}>
            Auch Bilder aus mehr als 50 Mails (meist Logos in Signaturen)
          </Checkbox>
          {enqueue.error && (
            <p className={styles.warning} role="alert">
              {aiErrorText(enqueue.error)}
            </p>
          )}
          <div className={styles.foot}>
            <Button onClick={onClose}>Abbrechen</Button>
            <Button
              variant="primary"
              disabled={enqueue.isPending || status.isPending}
              onClick={() =>
                enqueue.mutate(
                  { filters, engine: chosen, include_logos: logos },
                  { onSuccess: setDone },
                )
              }
            >
              {`${formatNumber(readable)} ${noun} vormerken`}
            </Button>
          </div>
        </>
      )}
    </Dialog>
  );
}

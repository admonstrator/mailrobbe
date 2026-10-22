import { useState } from "react";
import { Link } from "react-router";

import { useEnqueueAi } from "../../api/queries";
import type { DocumentDetail, DocumentTranscriptTask } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { formatClock, formatDate, formatNumber } from "../../lib/format";
import {
  aiErrorText,
  silenceText,
  startedText,
  transcriberName,
  transcriptLine,
} from "../ai/labels";
import { Dialog } from "../persons/Dialog";
import { Transcript } from "../preview/Transcript";
import { DiscardDialog } from "./DocumentOcr";
import styles from "./TranscriptCard.module.css";

/** "Transkription läuft · 1:05 von 3:12 transkribiert", "Für die Transkription vorgemerkt". */
function taskText(task: DocumentTranscriptTask, duration: number | null | undefined): string {
  const read =
    task.seconds_read > 0
      ? `${formatClock(task.seconds_read)}${duration ? ` von ${formatClock(duration)}` : ""} transkribiert`
      : null;
  if (task.status === "running") return ["Transkription läuft", read].filter(Boolean).join(" · ");
  return ["Für die Transkription vorgemerkt", read && `bisher ${read}`].filter(Boolean).join(" · ");
}

/** The card "Transkript" of a recording's document page (D296), in place of the text card: what
 *  the transcriber did ("Maschinell transkribiert", model, date, length, how far it read), the
 *  lines with their times, which play the page's player from there, an open task ("vorgemerkt",
 *  "läuft" with the seconds read, the page asks again until it ends), and "Transkribieren",
 *  "Neu transkribieren" and "Verwerfen". */
export function TranscriptCard({
  document,
  player,
}: {
  document: DocumentDetail;
  player: HTMLMediaElement | null;
}) {
  const result = document.transcript?.result ?? null;
  const task = document.transcript?.task ?? null;
  const [dialog, setDialog] = useState<"again" | "discard" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const enqueue = useEnqueueAi();

  // Starts a run for just this recording at once (D280, D295).
  const queue = () =>
    enqueue.mutate(
      { document_ids: [document.id], single: true, start: true, kind: "transcribe" },
      {
        onSuccess: (queued) => {
          setDialog(null);
          setNotice(startedText(queued, "transcribe"));
        },
        onError: (error) => setNotice(aiErrorText(error)),
      },
    );

  return (
    <Card className={styles.card} aria-labelledby="document-transcript-title">
      <div className={styles.head}>
        <CardTitle id="document-transcript-title">Transkript</CardTitle>
        {result && result.segments > 0 && (
          <span className={styles.count}>
            {`${formatNumber(result.segments)} ${result.segments === 1 ? "Zeile" : "Zeilen"}`}
          </span>
        )}
      </div>
      <div className={styles.bar}>
        {result && (
          <p className={styles.line}>
            {result.characters > 0
              ? transcriptLine(result)
              : `Maschinell geprüft · ${transcriberName(result.model)} · ${formatDate(result.created_at)}`}
          </p>
        )}
        {result && result.uncertain > 0 && (
          <p className={styles.note}>
            {`${formatNumber(result.uncertain)} ${result.uncertain === 1 ? "Zeile" : "Zeilen"} unsicher erkannt, gepunktet unterstrichen.`}
          </p>
        )}
        {!result && !task && (
          <p className={styles.note}>
            Noch kein Transkript. Ein KI-Lauf schreibt im Container mit, was in der Aufnahme
            gesprochen wird, mit der Zeit jeder Zeile; die Volltextsuche findet es danach.
          </p>
        )}
        {task ? (
          <p className={styles.note}>
            {taskText(task, document.duration)}
            {" · "}
            <Link to="/ki">zur Seite „KI“</Link>
          </p>
        ) : (
          <div className={styles.actions}>
            {!result && document.transcribable && (
              <Button size="sm" disabled={enqueue.isPending} onClick={queue}>
                Transkribieren
              </Button>
            )}
            {result && (
              <>
                <Button size="sm" onClick={() => setDialog("again")}>
                  Neu transkribieren
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
      </div>
      {result &&
        (result.characters > 0 ? (
          <Transcript documentId={document.id} result={result.id} player={player} />
        ) : (
          <p className={styles.empty}>{silenceText(result)}</p>
        ))}
      {dialog === "again" && (
        <Dialog title="Neu transkribieren?" onClose={() => setDialog(null)}>
          <p className={styles.text}>
            Ein KI-Lauf hört die Aufnahme gleich noch einmal ab. Sein Transkript ersetzt das
            bisherige erst, wenn es Sprache erkannt hat; das bisherige bleibt bis dahin
            durchsuchbar.
          </p>
          <div className={styles.foot}>
            <Button onClick={() => setDialog(null)}>Abbrechen</Button>
            <Button variant="primary" disabled={enqueue.isPending} onClick={queue}>
              Jetzt transkribieren
            </Button>
          </div>
        </Dialog>
      )}
      {dialog === "discard" && result && (
        <DiscardDialog
          resultId={result.id}
          transcript
          onClose={() => setDialog(null)}
          onDone={setNotice}
        />
      )}
    </Card>
  );
}

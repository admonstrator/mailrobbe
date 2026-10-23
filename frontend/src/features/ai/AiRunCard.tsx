import { useId, useState } from "react";

import { useStartAiRun, useStopAiRun } from "../../api/queries";
import type { AiJob, AiProgress, AiStatus, OcrEngineChoice } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { formatClock, formatDateTime, formatNumber } from "../../lib/format";
import { StepList } from "../import/StepList";
import styles from "./AiPage.module.css";
import { EngineSelect } from "./EngineSelect";
import { aiErrorText, minutesText, queueCounts } from "./labels";

const STATUS_TEXTS: Record<AiJob["status"], string> = {
  running: "läuft",
  done: "fertig",
  stopped: "angehalten",
  failed: "fehlgeschlagen",
};

/** "3 Dokumente gelesen, davon 1 ohne Schrift oder Sprache", "· 12 Minuten transkribiert": what
 *  a run read, its recordings in minutes (D295); "40 Paare geprüft, davon 3 dieselbe Person" for
 *  a run of the alias check (D321). */
function readText(job: AiJob): string {
  const progress = job.progress;
  if (job.options.aliases) {
    const pairs = progress.aliases ?? 0;
    return `${formatNumber(pairs)} ${pairs === 1 ? "Paar" : "Paare"} geprüft, davon ${formatNumber(progress.aliases_same ?? 0)} dieselbe Person`;
  }
  const blank = job.options.kinds.includes("transcribe")
    ? "ohne Schrift oder Sprache"
    : "ohne Schrift";
  return [
    `${formatNumber(progress.done + progress.no_text)} Dokumente gelesen`,
    progress.no_text > 0 && `, davon ${formatNumber(progress.no_text)} ${blank}`,
    (progress.minutes ?? 0) > 0 && ` · ${minutesText(progress.minutes ?? 0)} transkribiert`,
  ]
    .filter(Boolean)
    .join("");
}

/** "Anruf.ogg · 1:05 von 3:12": the file in work and, for a recording, how far it is. */
function currentPlace(progress: AiProgress): string | null {
  if (typeof progress.position !== "number") return null;
  const duration = progress.duration ? ` von ${formatClock(progress.duration)}` : "";
  return ` · ${formatClock(progress.position)}${duration}`;
}

/** The run (D187): its start form with the defaults of the settings, its steps and figures while
 *  it lives, stop; the last one's outcome afterwards. One run at a time, never beside an import. */
export function AiRunCard({ status }: { status: AiStatus }) {
  const job = status.job;
  const alive = Boolean(job?.alive && job.status === "running");
  // Documents to read or transcribe, and texts to summarise (D300), share the queue.
  const summaries = status.queue.summarize.waiting;
  const waiting = queueCounts(status.queue).waiting - summaries;
  return (
    <Card aria-labelledby="ai-run-title">
      <CardTitle id="ai-run-title">Lauf</CardTitle>
      {alive && job ? (
        <LiveRun job={job} />
      ) : (
        <>
          {job && <LastRun job={job} />}
          <StartForm status={status} waiting={waiting} summaries={summaries} />
        </>
      )}
    </Card>
  );
}

function LiveRun({ job }: { job: AiJob }) {
  const stop = useStopAiRun();
  const progress = job.progress;
  const ocr = progress.steps.find((step) => step.key === "ocr");
  return (
    <div className={styles.run}>
      <p className={styles.runLine}>
        <Spinner label="Läuft" />
        <strong>{job.stop_requested ? "Wird angehalten …" : "Läuft"}</strong>
        <span className={styles.muted}>{`seit ${formatDateTime(job.started_at)}`}</span>
        <Button
          size="sm"
          className={styles.serviceAction}
          disabled={job.stop_requested || stop.isPending}
          onClick={() => stop.mutate()}
        >
          Anhalten
        </Button>
      </p>
      <p className={styles.figures}>
        {ocr && ocr.done > 0 && (
          <>
            <strong>
              {`${formatNumber(ocr.done)}${ocr.total !== null ? ` von ${formatNumber(ocr.total)}` : ""} Seiten`}
            </strong>
            {" · "}
          </>
        )}
        {readText(job)}
        {progress.failed > 0 && ` · ${formatNumber(progress.failed)} fehlgeschlagen`}
        {progress.summaries > 0 && ` · ${summariesText(progress.summaries)}`}
        {!job.options.aliases && ` · ${formatNumber(progress.queued)} noch vorgemerkt`}
      </p>
      {progress.current && (
        <p className={styles.muted}>
          {"In Arbeit: "}
          <span className={styles.mono}>{progress.current}</span>
          {currentPlace(progress)}
        </p>
      )}
      {progress.unreachable_since && (
        <p className={styles.warning} role="alert">
          {`${job.phase === "summarize" || job.phase === "aliases" ? "Das Textmodell" : "Das Bildmodell"} antwortet nicht seit ${formatDateTime(progress.unreachable_since)}. Der Lauf wartet und versucht es weiter; läuft LM Studio oder Ollama noch?`}
        </p>
      )}
      {stop.error && (
        <p className={styles.warning} role="alert">
          {aiErrorText(stop.error)}
        </p>
      )}
      {progress.steps.length > 0 && (
        <StepList
          steps={progress.steps}
          alive
          age={job.report_age_seconds}
          database={progress.database}
          kind="ai"
        />
      )}
    </div>
  );
}

function LastRun({ job }: { job: AiJob }) {
  const progress = job.progress;
  const when = job.finished_at ?? job.updated_at;
  const ended = job.status === "running" ? "abgebrochen" : STATUS_TEXTS[job.status];
  return (
    <p className={styles.muted}>
      {`Letzter Lauf ${ended} am ${formatDateTime(when)}: ${readText(job)}`}
      {progress.failed > 0 && `, ${formatNumber(progress.failed)} fehlgeschlagen`}
      {progress.summaries > 0 && `; ${summariesText(progress.summaries)}`}
      {"."}
      {job.message && job.status === "failed" && (
        <span className={styles.technical}>{` ${job.message}`}</span>
      )}
    </p>
  );
}

/** "1 Zusammenfassung", "3 Zusammenfassungen" */
function summariesText(count: number): string {
  return `${formatNumber(count)} ${count === 1 ? "Zusammenfassung" : "Zusammenfassungen"}`;
}

function StartForm({
  status,
  waiting,
  summaries,
}: {
  status: AiStatus;
  waiting: number;
  summaries: number;
}) {
  const id = useId();
  const defaults = status.defaults;
  const [engine, setEngine] = useState<OcrEngineChoice>(defaults.ocr_engine);
  const [model, setModel] = useState(defaults.vision_model);
  const [textModel, setTextModel] = useState(defaults.text_model);
  const [maxPages, setMaxPages] = useState(String(defaults.max_pages));
  // The limit per recording (D292), offered once the server knows the transcriber.
  const transcriber = status.transcription;
  const [maxMinutes, setMaxMinutes] = useState(
    String(defaults.max_minutes ?? transcriber?.max_minutes ?? 180),
  );
  const start = useStartAiRun();
  const chosen = status.vision ? engine : "tesseract";
  const pages = Number(maxPages);
  const pagesValid = Number.isInteger(pages) && pages >= 1 && pages <= 10_000;
  const minutes = Number(maxMinutes);
  const minutesValid =
    !transcriber || (Number.isInteger(minutes) && minutes >= 1 && minutes <= 10_000);

  return (
    <form
      className={styles.runForm}
      onSubmit={(event) => {
        event.preventDefault();
        if (!pagesValid || !minutesValid) return;
        start.mutate({
          engine: chosen,
          max_pages: pages,
          ...(status.vision && model.trim() ? { vision_model: model.trim() } : {}),
          ...(status.text && textModel.trim() ? { text_model: textModel.trim() } : {}),
          ...(transcriber ? { max_minutes: minutes } : {}),
        });
      }}
    >
      <p className={styles.muted}>
        {waiting > 0
          ? `${formatNumber(waiting)} ${waiting === 1 ? "Dokument ist" : "Dokumente sind"} vorgemerkt. Der Lauf liest sie und hört auf, wenn die Warteschlange leer ist; angehalten macht der nächste Lauf weiter.`
          : summaries === 0 &&
            "Nichts vorgemerkt. Erst Dokumente vormerken, aus einer Arbeitsliste oder der Anhangsliste."}
        {summaries > 0 &&
          ` ${summariesText(summaries)} ${summaries === 1 ? "ist" : "sind"} vorgemerkt; der Lauf schreibt sie nach der Texterkennung.`}
      </p>
      <div className={styles.runFields}>
        <EngineSelect
          id={`${id}-engine`}
          value={chosen}
          vision={status.vision}
          onChange={setEngine}
        />
        {status.vision && (
          <div className={styles.field}>
            <label htmlFor={`${id}-model`} className={styles.fieldLabel}>
              Bildmodell
            </label>
            <input
              id={`${id}-model`}
              className={styles.input}
              value={model}
              onChange={(event) => setModel(event.target.value)}
              spellCheck={false}
            />
          </div>
        )}
        {status.text && (
          <div className={styles.field}>
            <label htmlFor={`${id}-text`} className={styles.fieldLabel}>
              Textmodell
            </label>
            <input
              id={`${id}-text`}
              className={styles.input}
              value={textModel}
              onChange={(event) => setTextModel(event.target.value)}
              spellCheck={false}
            />
          </div>
        )}
        <div className={styles.field}>
          <label htmlFor={`${id}-pages`} className={styles.fieldLabel}>
            Höchstens Seiten je Dokument
          </label>
          <input
            id={`${id}-pages`}
            className={styles.input}
            inputMode="numeric"
            value={maxPages}
            aria-invalid={!pagesValid}
            onChange={(event) => setMaxPages(event.target.value)}
          />
        </div>
        {transcriber && (
          <div className={styles.field}>
            <label htmlFor={`${id}-minutes`} className={styles.fieldLabel}>
              Minuten je Aufnahme
            </label>
            <input
              id={`${id}-minutes`}
              className={styles.input}
              inputMode="numeric"
              value={maxMinutes}
              aria-invalid={!minutesValid}
              onChange={(event) => setMaxMinutes(event.target.value)}
            />
          </div>
        )}
      </div>
      {start.error && (
        <p className={styles.warning} role="alert">
          {aiErrorText(start.error)}
        </p>
      )}
      <div>
        <Button
          type="submit"
          variant="primary"
          disabled={waiting + summaries === 0 || !pagesValid || !minutesValid || start.isPending}
        >
          KI-Lauf starten
        </Button>
      </div>
    </form>
  );
}

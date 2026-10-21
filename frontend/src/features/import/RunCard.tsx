import { useStopDkimRun } from "../../api/queries";
import type { DbActivity, DkimJob, ImportJob, ImportStatus } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { formatBytes, formatDateTime, formatElapsed, formatNumber } from "../../lib/format";
import { databaseText, MBOX_DIR_MISSING, RUN_TITLES, stepLabel } from "./labels";
import { importRunState, SILENT_SECONDS } from "./model";
import styles from "./RunCard.module.css";
import { StepList } from "./StepList";

const rate = (perSecond: number) => formatNumber(Math.round(perSecond));

const ENDED: Record<ImportJob["status"], string> = {
  running: "beendet",
  done: "fertig",
  stopped: "pausiert",
  failed: "abgebrochen",
};

/** "Gestartet 20.10.2026 01:02 · letzte Meldung vor 2 s", or when the run ended. */
function timeline(job: ImportJob, alive: boolean): string {
  const parts = [
    `Gestartet ${formatDateTime(job.started_at)}${job.origin === "cli" ? " über die Kommandozeile" : ""}`,
  ];
  if (alive) parts.push(`letzte Meldung vor ${formatElapsed(Math.max(1, job.report_age_seconds))}`);
  else if (job.finished_at) parts.push(`${ENDED[job.status]} ${formatDateTime(job.finished_at)}`);
  else parts.push(`letzte Meldung ${formatDateTime(job.updated_at)}`);
  return parts.join(" · ");
}

/** The steps of a run (D110): open while it lives or lies orphaned, folded once it ended. */
function Steps({ run, open }: { run: ImportJob | DkimJob; open: boolean }) {
  const { steps, database } = run.progress;
  if (steps.length === 0) return null; // a run recorded before D110
  const list = (
    <StepList steps={steps} alive={run.alive} age={run.report_age_seconds} database={database} />
  );
  if (open) return list;
  return (
    <details className={styles.history}>
      <summary>Schritte des Laufs</summary>
      {list}
    </details>
  );
}

/** A run that holds its lock but has not reported for a while. */
function Silent({ run }: { run: ImportJob | DkimJob }) {
  if (!run.alive || run.report_age_seconds < SILENT_SECONDS) return null;
  return (
    <p className={styles.warning}>
      {`Seit ${formatElapsed(run.report_age_seconds)} keine Meldung, obwohl der Prozess noch läuft. Details stehen im Server-Log (docker compose logs backend).`}
    </p>
  );
}

/** What a run whose process died left running in the database (D110). */
function Leftover({ activity }: { activity: DbActivity | null }) {
  if (!activity) return null;
  return (
    <p className={styles.warningText}>
      {`In der Datenbank läuft seine letzte Anweisung noch (${databaseText(activity)}). Sie kann Sperren halten, die der nächste Lauf braucht; der nächste Start beendet sie zuerst.`}
    </p>
  );
}

/** The latest import run (D47): state, source, overall progress over bytes, throughput, its steps
 *  (D110); below it the DKIM run while it is alive or the latest of the two. */
export function RunCard({
  status,
  duplicates,
  onError,
}: {
  status: ImportStatus;
  /** From the summary; left out until it is loaded. */
  duplicates: number | undefined;
  onError: (error: Error) => void;
}) {
  const { totals, import_job: job } = status;
  const state = importRunState(job);
  const alive = state === "running" || state === "pausing";
  const ratio = totals.size_bytes > 0 ? Math.min(1, totals.bytes_done / totals.size_bytes) : 0;
  const percent = Math.floor(ratio * 100);
  const complete = totals.size_bytes > 0 && totals.bytes_done >= totals.size_bytes;

  return (
    <Card className={styles.card} aria-labelledby="import-run-title">
      <div className={styles.head}>
        <h1 id="import-run-title" className={styles.title}>
          {RUN_TITLES[state]}
        </h1>
        {alive && job && job.progress.workers > 0 && (
          <span className={styles.badge}>
            <span className={styles.badgeDot} aria-hidden="true" />
            {`${formatNumber(job.progress.workers)} Worker aktiv`}
          </span>
        )}
        <span className={styles.source}>
          {`Quelle: ${status.mbox_dir} · ${formatNumber(totals.files)} ${totals.files === 1 ? "Datei" : "Dateien"} · ${formatBytes(totals.size_bytes)}`}
        </span>
        {job && <span className={styles.timeline}>{timeline(job, alive)}</span>}
      </div>
      {!status.mbox_dir_ok && (
        <p className={styles.warning}>
          {MBOX_DIR_MISSING} Prüfe den Bind-Mount und MAILROBBE_MBOX_DIR.
        </p>
      )}
      <div
        className={styles.bar}
        role="progressbar"
        aria-label="Gesamtfortschritt"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span className={styles.fill} style={{ width: `${ratio * 100}%` }} />
      </div>
      <ul className={styles.figures} aria-label="Importfortschritt">
        <li>
          <strong>{formatNumber(totals.mails_parsed)}</strong>
          {totals.mails_estimated !== null && !complete
            ? ` von ca. ${formatNumber(totals.mails_estimated)} Mails geparst (${percent} %)`
            : " Mails geparst"}
        </li>
        {alive && job?.phase === "import" && (
          <>
            <li>
              <strong>{rate(job.progress.mails_per_second)}</strong> Mails/s Parsing
            </li>
            <li>
              <strong>{rate(job.progress.dkim_per_second)}</strong> Mails/s DKIM
            </li>
          </>
        )}
        {duplicates !== undefined && (
          <li>
            <strong>{formatNumber(duplicates)}</strong> Duplikate (Message-ID + Hash)
          </li>
        )}
        <li>
          <strong>{formatNumber(totals.error_count)}</strong> Importfehler
        </li>
      </ul>
      {job && <Silent run={job} />}
      {job && <Steps run={job} open={alive || state === "orphaned"} />}
      {(state === "aborted" || state === "orphaned") && job && <Aborted job={job} />}
      <DkimBand run={status.dkim_job} importJob={job} onError={onError} />
    </Card>
  );
}

function Aborted({ job }: { job: ImportJob }) {
  const last = job.progress.steps.findLast((step) => step.status === "running");
  return (
    <div className={styles.note}>
      {job.status === "running" && (
        <p>
          Der Importprozess endete, ohne sein Ende zu melden, etwa weil der Server oder der
          Container neu gestartet wurde.
          {last && ` Zuletzt lief „${stepLabel(last.key)}“.`}
        </p>
      )}
      <Leftover activity={job.leftover} />
      <p>
        Gespeicherte Mails bleiben erhalten; „Import fortsetzen“ macht bei der letzten gespeicherten
        Mail weiter.
      </p>
      {job.message && <p className={styles.message}>{job.message}</p>}
    </div>
  );
}

/** The DKIM run of D13: live with a stop button, or one line on how it ended while no import
 *  has started since. */
function DkimBand({
  run,
  importJob,
  onError,
}: {
  run: DkimJob | null;
  importJob: ImportJob | null;
  onError: (error: Error) => void;
}) {
  const stop = useStopDkimRun();
  if (!run || (!run.alive && run.id < (importJob?.id ?? 0))) return null;
  const { checked, selected, skipped } = run.progress;
  const counts = `${formatNumber(checked)} von ${formatNumber(selected)} Mails`;

  if (run.alive && run.status === "running") {
    return (
      <div className={styles.band}>
        <div className={styles.bandHead}>
          <span className={styles.bandText}>
            {run.stop_requested ? "DKIM-Prüfung wird abgebrochen …" : "DKIM-Prüfung läuft"}
          </span>
          <Button
            size="sm"
            disabled={run.stop_requested || stop.isPending}
            onClick={() => stop.mutate(undefined, { onError })}
          >
            {run.stop_requested ? "Wird abgebrochen …" : "DKIM-Prüfung abbrechen"}
          </Button>
        </div>
        <Silent run={run} />
        <Steps run={run} open />
      </div>
    );
  }

  const ended = run.finished_at ? ` · ${formatDateTime(run.finished_at)}` : "";
  const skippedText = skipped > 0 ? `, ${formatNumber(skipped)} übersprungen` : "";
  return (
    <div className={styles.band}>
      <span className={styles.bandText}>
        {run.status === "done"
          ? `DKIM-Prüfung fertig: ${formatNumber(checked)} Mails geprüft${skippedText}${ended}`
          : run.status === "stopped"
            ? `DKIM-Prüfung abgebrochen: ${counts} geprüft${ended}`
            : run.status === "running"
              ? `DKIM-Prüfung verwaist: Der Prozess endete ohne Meldung · letzte Meldung ${formatDateTime(run.updated_at)}`
              : `DKIM-Prüfung abgebrochen${ended}`}
        {run.status === "failed" && run.message && (
          <span className={styles.message}>{run.message}</span>
        )}
      </span>
      <Leftover activity={run.leftover} />
    </div>
  );
}

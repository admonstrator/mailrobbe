import { useStopDkimRun } from "../../api/queries";
import type { DkimJob, ImportJob, ImportStatus } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { formatBytes, formatDateTime, formatNumber, formatRemaining } from "../../lib/format";
import { MBOX_DIR_MISSING, phaseText, RUN_TITLES } from "./labels";
import { importRunState } from "./model";
import styles from "./RunCard.module.css";

const rate = (perSecond: number) => formatNumber(Math.round(perSecond));

const ENDED: Record<ImportJob["status"], string> = {
  running: "beendet",
  done: "fertig",
  stopped: "pausiert",
  failed: "abgebrochen",
};

/** "Gestartet 20.10.2026 01:02 · Restzeit ca. 1 h 40 min", or when the run ended. */
function timeline(job: ImportJob, alive: boolean): string {
  const parts = [
    `Gestartet ${formatDateTime(job.started_at)}${job.origin === "cli" ? " über die Kommandozeile" : ""}`,
  ];
  const eta = job.progress.eta_seconds;
  if (alive && eta !== null) parts.push(`Restzeit ca. ${formatRemaining(eta)}`);
  if (job.finished_at) parts.push(`${ENDED[job.status]} ${formatDateTime(job.finished_at)}`);
  else if (!alive) parts.push(`letzte Meldung ${formatDateTime(job.updated_at)}`);
  return parts.join(" · ");
}

/** The latest import run (D47): state, source, overall progress over bytes, throughput, phase;
 *  below it the DKIM run while it is alive or the latest of the two. */
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
  const phase = job && alive ? phaseText(job) : null;

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
        {alive && job && (
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
      {phase && (
        <p className={styles.phase}>
          <Spinner label="Läuft" />
          {phase}
        </p>
      )}
      {state === "aborted" && job && <Aborted job={job} />}
      <DkimBand run={status.dkim_job} importJob={job} onError={onError} />
    </Card>
  );
}

function Aborted({ job }: { job: ImportJob }) {
  return (
    <div className={styles.note}>
      <p>
        {job.status === "running" &&
          "Der Importprozess endete, ohne sein Ende zu melden (etwa weil der Container gestoppt wurde). "}
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
  const { checked, selected, skipped, mails_per_second, eta_seconds } = run.progress;
  const counts = `${formatNumber(checked)} von ${formatNumber(selected)} Mails`;

  if (run.alive && run.status === "running") {
    const parts = run.stop_requested
      ? ["DKIM-Prüfung wird abgebrochen …"]
      : run.phase === "aggregates"
        ? [`DKIM-Prüfung: ${counts} geprüft, Kennzahlen werden berechnet`]
        : [`DKIM-Prüfung läuft: ${counts}`, `${rate(mails_per_second)} Mails/s`];
    if (!run.stop_requested && run.phase !== "aggregates" && eta_seconds !== null) {
      parts.push(`Restzeit ca. ${formatRemaining(eta_seconds)}`);
    }
    return (
      <div className={styles.band}>
        <Spinner label="Läuft" />
        <span className={styles.bandText}>{parts.join(" · ")}</span>
        <Button
          size="sm"
          disabled={run.stop_requested || stop.isPending}
          onClick={() => stop.mutate(undefined, { onError })}
        >
          {run.stop_requested ? "Wird abgebrochen …" : "DKIM-Prüfung abbrechen"}
        </Button>
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
            : `DKIM-Prüfung abgebrochen${ended}`}
        {run.status === "failed" && run.message && (
          <span className={styles.message}>{run.message}</span>
        )}
      </span>
    </div>
  );
}

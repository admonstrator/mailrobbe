import { useStopDkimRun } from "../../api/queries";
import type { DbActivity, DkimJob, ImportJob, ImportStatus, ImportSummary } from "../../api/types";
import { Button } from "../../components/Button";
import { formatBytes, formatDateTime, formatElapsed, formatNumber } from "../../lib/format";
import { databaseText, MBOX_DIR_MISSING, RUN_BADGES, stepLabel } from "./labels";
import { importRunState, SILENT_SECONDS, type RunState } from "./model";
import { Figures, type BadgeTone, type Figure } from "../../components/PageHead";
import styles from "./RunCard.module.css";
import { RunSteps } from "./RunSteps";
import { StepList } from "./StepList";

const rate = (perSecond: number) => formatNumber(Math.round(perSecond));

const ENDED: Record<ImportJob["status"], string> = {
  running: "beendet",
  done: "fertig",
  stopped: "pausiert",
  failed: "abgebrochen",
};

const BADGE_TONES: Record<RunState, BadgeTone> = {
  none: "quiet",
  running: "accent",
  pausing: "warning",
  paused: "warning",
  done: "done",
  aborted: "error",
  orphaned: "error",
};

/** The state beside the title: "Läuft · Schritt 7 von 15". */
export function runBadge(job: ImportJob | null): { text: string; tone: BadgeTone } {
  const state = importRunState(job);
  const steps = job?.progress.steps ?? [];
  const current = steps.findLastIndex((step) => step.status === "running");
  const alive = state === "running" || state === "pausing";
  const text =
    alive && current >= 0
      ? `${RUN_BADGES[state]} · Schritt ${current + 1} von ${steps.length}`
      : RUN_BADGES[state];
  return { text, tone: BADGE_TONES[state] };
}

/** "Gestartet 20.10.2026 01:02 · letzte Meldung vor 2 s", or when the run ended. */
export function runTimeline(job: ImportJob, alive: boolean): string {
  const parts = [
    `Gestartet ${formatDateTime(job.started_at)}${job.origin === "cli" ? " über die Kommandozeile" : ""}`,
  ];
  if (alive) parts.push(`letzte Meldung vor ${formatElapsed(Math.max(1, job.report_age_seconds))}`);
  else if (job.finished_at) parts.push(`${ENDED[job.status]} ${formatDateTime(job.finished_at)}`);
  else parts.push(`letzte Meldung ${formatDateTime(job.updated_at)}`);
  return parts.join(" · ");
}

/** The muted line below the title: when the run started or ended, workers, the source. */
export function RunSub({ status }: { status: ImportStatus }) {
  const { totals, import_job: job } = status;
  const state = importRunState(job);
  const alive = state === "running" || state === "pausing";
  const workers = alive && job && job.progress.workers > 0 ? job.progress.workers : 0;
  return (
    <>
      {job && <span>{runTimeline(job, alive)}</span>}
      {workers > 0 && (
        <span className={styles.workers}>{`${formatNumber(workers)} Worker aktiv`}</span>
      )}
      <span className={styles.source}>
        {`Quelle: ${status.mbox_dir} · ${formatNumber(totals.files)} ${totals.files === 1 ? "Datei" : "Dateien"} · ${formatBytes(totals.size_bytes)}`}
      </span>
    </>
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

/** The overall progress over bytes and the figures of the run and the archive (D47), with the
 *  warnings of a missing directory and a silent run. */
export function RunProgress({
  status,
  summary,
}: {
  status: ImportStatus;
  /** Left out until it is loaded. */
  summary: ImportSummary | undefined;
}) {
  const { totals, import_job: job } = status;
  const state = importRunState(job);
  const alive = state === "running" || state === "pausing";
  const ratio = totals.size_bytes > 0 ? Math.min(1, totals.bytes_done / totals.size_bytes) : 0;
  const percent = Math.floor(ratio * 100);
  const complete = totals.size_bytes > 0 && totals.bytes_done >= totals.size_bytes;

  const figures: Figure[] = [
    {
      value: formatNumber(totals.mails_parsed),
      label:
        totals.mails_estimated !== null && !complete
          ? `von ca. ${formatNumber(totals.mails_estimated)} Mails geparst (${percent} %)`
          : "Mails geparst",
    },
  ];
  if (alive && job?.phase === "import") {
    figures.push(
      { value: rate(job.progress.mails_per_second), label: "Mails/s Parsing" },
      { value: rate(job.progress.dkim_per_second), label: "Mails/s DKIM" },
    );
  }
  if (summary) {
    figures.push({
      value: formatNumber(summary.duplicates),
      label: "Duplikate",
      title: "Gleiche Message-ID und gleicher Hash",
    });
  }
  figures.push({
    value: formatNumber(totals.error_count),
    label: "Importfehler",
    warn: totals.error_count > 0,
  });
  if (summary) {
    figures.push(
      { value: formatNumber(summary.persons), label: "Personen" },
      { value: formatNumber(summary.attachments), label: "Anhänge" },
      {
        value: formatBytes(summary.db_size_bytes),
        label: "Datenbank",
        title: "Metadaten und Index",
      },
    );
  }

  return (
    <div className={styles.progress}>
      {!status.mbox_dir_ok && (
        <p className={styles.warning}>
          {MBOX_DIR_MISSING} Prüfe den Bind-Mount und MAILROBBE_MBOX_DIR.
        </p>
      )}
      {job && <Silent run={job} />}
      <div
        className={styles.bar}
        role="progressbar"
        aria-label="Gesamtfortschritt"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span
          className={complete ? styles.fillDone : styles.fill}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      <Figures items={figures} label="Importfortschritt" />
    </div>
  );
}

/** The tab "Lauf": the steps of the latest import run (D110) with the chosen step's detail, what
 *  an aborted run left, and the DKIM run below while it lives or ended last. */
export function RunTab({
  status,
  onError,
}: {
  status: ImportStatus;
  onError: (error: Error) => void;
}) {
  const job = status.import_job;
  const state = importRunState(job);
  const alive = state === "running" || state === "pausing";
  return (
    <div className={styles.tab}>
      {job && job.progress.steps.length > 0 ? (
        <RunSteps
          steps={job.progress.steps}
          alive={job.alive}
          age={job.report_age_seconds}
          database={job.progress.database}
        />
      ) : (
        <p className={styles.none}>
          {job ? "Dieser Lauf hat keine Schritte aufgezeichnet." : "Es gab noch keinen Importlauf."}
        </p>
      )}
      {(state === "aborted" || state === "orphaned") && job && <Aborted job={job} />}
      {alive && (
        <p className={styles.hint}>
          Anhalten unterbricht nach dem laufenden Stapel; der nächste Start macht hier weiter.
        </p>
      )}
      <DkimBand run={status.dkim_job} importJob={job} onError={onError} />
    </div>
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

/** The DKIM run of D13: live with a stop button and its steps, or one line on how it ended
 *  while no import has started since. */
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
      <section className={styles.band} aria-label="DKIM-Prüfung">
        <div className={styles.bandHead}>
          <h2 className={styles.bandText}>
            {run.stop_requested ? "DKIM-Prüfung wird abgebrochen …" : "DKIM-Prüfung läuft"}
          </h2>
          <Button
            size="sm"
            disabled={run.stop_requested || stop.isPending}
            onClick={() => stop.mutate(undefined, { onError })}
          >
            {run.stop_requested ? "Wird abgebrochen …" : "DKIM-Prüfung abbrechen"}
          </Button>
        </div>
        <Silent run={run} />
        {run.progress.steps.length > 0 && (
          <StepList
            steps={run.progress.steps}
            alive={run.alive}
            age={run.report_age_seconds}
            database={run.progress.database}
          />
        )}
      </section>
    );
  }

  const ended = run.finished_at ? ` · ${formatDateTime(run.finished_at)}` : "";
  const skippedText = skipped > 0 ? `, ${formatNumber(skipped)} übersprungen` : "";
  return (
    <section className={styles.band} aria-label="DKIM-Prüfung">
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
    </section>
  );
}

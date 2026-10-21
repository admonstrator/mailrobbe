import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useKeysStatus, useStopKeysRun } from "../../api/queries";
import type { DkimKeysJob } from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { formatDateTime, formatNumber } from "../../lib/format";
import styles from "./KeysRun.module.css";
import { busyText, keysErrorText, PHASE_LABELS, runFigures, TASK_LABELS } from "./labels";

/** The latest dkim-keys run and whether another run blocks a start. When a run ends, statuses
 *  of mails have changed (D101), so everything is loaded again. */
export function useKeysRun() {
  const status = useKeysStatus();
  const job = status.data?.keys_job ?? null;
  const alive = job?.alive ?? false;
  const queryClient = useQueryClient();
  const before = useRef(alive);
  useEffect(() => {
    if (before.current && !alive) void queryClient.invalidateQueries();
    before.current = alive;
  }, [alive, queryClient]);
  return { job, busy: busyText(status.data) };
}

const ENDED: Record<DkimKeysJob["status"], string> = {
  running: "abgebrochen", // its process ended without recording it (D47)
  done: "fertig",
  stopped: "angehalten",
  failed: "abgebrochen",
};

/** A dkim-keys run (D101): while it is alive its task, phase and figures with "Anhalten"; after
 *  it one line on how it ended, when ended is set. */
export function KeysRun({
  job,
  ended = true,
  onError,
}: {
  job: DkimKeysJob | null;
  ended?: boolean;
  onError: (message: string) => void;
}) {
  const stop = useStopKeysRun();
  if (!job || (!job.alive && !ended)) return null;
  const task = TASK_LABELS[job.options.task];
  const started = `gestartet ${formatDateTime(job.started_at)}${job.origin === "cli" ? " über die Kommandozeile" : ""}`;

  if (job.alive && job.status === "running") {
    const workers = job.progress.workers;
    return (
      <div className={styles.run} role="group" aria-label="Schlüsselsuche">
        <Spinner label="Läuft" />
        <div className={styles.text}>
          <span className={styles.title}>
            {job.stop_requested ? `${task} wird angehalten …` : `${task} läuft`}
            {workers > 0 && (
              <span className={styles.muted}>{` · ${formatNumber(workers)} Worker`}</span>
            )}
          </span>
          {job.phase && <span>{PHASE_LABELS[job.phase]}</span>}
          {/* The phase's progress bar, rate and remaining time come with the progress steps
              every run reports (the dashboard's step model); they belong here. */}
          <span className={styles.figures}>{runFigures(job)}</span>
          <span className={styles.muted}>{started}</span>
        </div>
        <Button
          size="sm"
          disabled={job.stop_requested || stop.isPending}
          onClick={() =>
            stop.mutate(undefined, { onError: (error) => onError(keysErrorText(error)) })
          }
        >
          {job.stop_requested ? "Wird angehalten …" : "Anhalten"}
        </Button>
      </div>
    );
  }

  const when = job.finished_at ?? job.updated_at;
  return (
    <div className={styles.run}>
      <div className={styles.text}>
        <span>
          <span className={styles.title}>{`${task} ${ENDED[job.status]}`}</span>
          {job.status !== "failed" && job.status !== "running" && `: ${runFigures(job)}`}
          <span className={styles.muted}>{` · ${formatDateTime(when)}`}</span>
        </span>
        {(job.status === "failed" || job.status === "running") && job.message && (
          <span className={styles.message}>{job.message}</span>
        )}
      </div>
    </div>
  );
}

import { useState } from "react";

import type { DbActivity, StepProgress } from "../../api/types";
import { CheckIcon, CrossIcon, MinusIcon } from "../../components/icons";
import { cx } from "../../lib/cx";
import { formatElapsed } from "../../lib/format";
import { databaseText, stepDetail, stepLabel } from "./labels";
import { stepState, type StepState } from "./model";
import styles from "./RunSteps.module.css";

function Mark({ state }: { state: StepState }) {
  switch (state) {
    case "running":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" className={styles.spin}>
          <circle
            cx="12"
            cy="12"
            r="9"
            fill="none"
            stroke="var(--color-nav-active)"
            strokeWidth="3"
          />
          <path
            d="M12 3a9 9 0 0 1 9 9"
            fill="none"
            stroke="var(--color-accent)"
            strokeWidth="3"
            strokeLinecap="round"
          />
        </svg>
      );
    case "done":
      return (
        <span className={cx(styles.dot, styles.doneDot)}>
          <CheckIcon size={12} strokeWidth={3} />
        </span>
      );
    case "failed":
    case "aborted":
      return (
        <span className={cx(styles.dot, styles.failedDot)}>
          <CrossIcon size={12} strokeWidth={3} />
        </span>
      );
    case "skipped":
    case "stopped":
      return (
        <span className={cx(styles.dot, styles.quietDot)}>
          <MinusIcon size={12} strokeWidth={3} />
        </span>
      );
    default:
      return <span className={styles.ring} aria-hidden="true" />;
  }
}

/** What the list shows at the right of a step: its time, its share while it runs. */
function shortText(step: StepProgress, state: StepState): string {
  if (state === "running") {
    return step.total ? `${Math.floor(Math.min(1, step.done / step.total) * 100)} %` : "läuft";
  }
  if (state === "done") return formatElapsed(step.seconds);
  if (state === "stopped") return "angehalten";
  if (state === "aborted") return "abgebrochen";
  if (state === "failed") return "Fehler";
  if (state === "skipped") return "nicht nötig";
  return "";
}

/** The step shown at first: the last running one, else where the run stopped, else the last
 *  that ended. */
function firstChoice(steps: StepProgress[], alive: boolean): number {
  const states = steps.map((step) => stepState(step, alive));
  const running = states.findLastIndex((state) => state === "running");
  if (running >= 0) return running;
  const cut = states.findIndex((state) => ["aborted", "stopped", "failed"].includes(state));
  if (cut >= 0) return cut;
  const ended = states.findLastIndex((state) => state === "done");
  return Math.max(0, ended);
}

/** The steps of a run (D110) at the left, the chosen step's progress, rate and estimate at the
 *  right, as in the mockup of the import page. */
export function RunSteps({
  steps,
  alive,
  age,
  database,
}: {
  steps: StepProgress[];
  alive: boolean;
  age: number;
  database: DbActivity | null;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const index = Math.max(
    0,
    chosen === null ? firstChoice(steps, alive) : steps.findIndex((s) => s.key === chosen),
  );
  const quiet = alive ? steps.findLastIndex((s) => s.status === "running" && s.unit === null) : -1;
  const step = steps[index];
  const state = stepState(step, alive);
  const extra = state === "running" ? age : 0;
  const share =
    step.total && step.total > 0
      ? Math.min(1, step.done / step.total)
      : state === "done" || state === "skipped"
        ? 1
        : 0;

  return (
    <div className={styles.layout}>
      <ol className={styles.list} aria-label="Schritte des Laufs">
        {steps.map((item, position) => {
          const itemState = stepState(item, alive);
          return (
            <li key={item.key}>
              <button
                type="button"
                className={cx(styles.step, position === index && styles.chosen)}
                aria-current={position === index ? "step" : undefined}
                onClick={() => setChosen(item.key)}
              >
                <Mark state={itemState} />
                <span
                  className={cx(
                    styles.label,
                    itemState === "running" && styles.labelRunning,
                    ["waiting", "unreached", "skipped"].includes(itemState) && styles.labelQuiet,
                  )}
                >
                  {stepLabel(item.key)}
                </span>
                <span className={styles.short}>{shortText(item, itemState)}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <section className={styles.detail} aria-label="Gewählter Schritt">
        <h2 className={styles.title}>{stepLabel(step.key)}</h2>
        <div
          className={styles.bar}
          role="progressbar"
          aria-label={stepLabel(step.key)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.floor(share * 100)}
        >
          <span
            className={cx(styles.fill, state === "done" && styles.fillDone)}
            style={{ width: `${share * 100}%` }}
          />
        </div>
        <p className={styles.text}>
          {stepDetail(step, state, extra)}
          {index === quiet && database && ` · Datenbank ${databaseText(database, age)}`}
        </p>
      </section>
    </div>
  );
}

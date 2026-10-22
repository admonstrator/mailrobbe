import type { DbActivity, JobKind, StepProgress } from "../../api/types";
import { CheckIcon, CrossIcon, MinusIcon } from "../../components/icons";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { databaseText, stepDetail, stepLabel } from "./labels";
import { stepState, type StepState } from "./model";
import styles from "./StepList.module.css";

function Mark({ state }: { state: StepState }) {
  switch (state) {
    case "running":
      return <Spinner label="Läuft" />;
    case "done":
      return <CheckIcon size={14} className={styles.done} />;
    case "failed":
    case "aborted":
      return <CrossIcon size={14} className={styles.failed} />;
    case "skipped":
    case "stopped":
      return <MinusIcon size={14} />;
    default:
      return <span className={styles.ring} aria-hidden="true" />;
  }
}

/** The steps of a run in the order it takes them (D110). While the run lives, the times of its
 *  running steps count on by age, the seconds since its report; the database's longest statement
 *  is shown at the last running step that counts nothing, the one it belongs to. */
export function StepList({
  steps,
  alive,
  age,
  database,
  kind,
}: {
  steps: StepProgress[];
  alive: boolean;
  age: number;
  database: DbActivity | null;
  /** The run's kind, for steps whose key another kind uses for another step. */
  kind?: JobKind;
}) {
  const quiet = alive ? steps.findLastIndex((s) => s.status === "running" && s.unit === null) : -1;
  return (
    <ol className={styles.steps} aria-label="Schritte des Laufs">
      {steps.map((step, index) => {
        const state = stepState(step, alive);
        const extra = state === "running" ? age : 0;
        const share =
          state === "running" && step.total ? Math.min(1, step.done / step.total) : null;
        return (
          <li key={step.key} className={cx(styles.step, state === "running" && styles.running)}>
            <span className={styles.mark}>
              <Mark state={state} />
            </span>
            <span className={styles.text}>
              <span className={cx(styles.label, quietState(state) && styles.quiet)}>
                {stepLabel(step.key, kind)}
              </span>
              <span className={styles.detail}>
                {stepDetail(step, state, extra)}
                {index === quiet && database && ` · Datenbank ${databaseText(database, age)}`}
              </span>
            </span>
            {share !== null && (
              <span
                className={styles.bar}
                role="progressbar"
                aria-label={stepLabel(step.key, kind)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.floor(share * 100)}
              >
                <span className={styles.fill} style={{ width: `${share * 100}%` }} />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

const quietState = (state: StepState) =>
  state === "waiting" || state === "unreached" || state === "skipped";

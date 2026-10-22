import { Link } from "react-router";

import type { AiJob } from "../../api/types";
import { Card } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import styles from "./AiRunLine.module.css";
import { StepList } from "./StepList";

/** A live AI run on the dashboard (D187): an import cannot start meanwhile, so it says what runs
 *  and links the page that stops it. Nothing while none lives. */
export function AiRunLine({ run }: { run: AiJob | null | undefined }) {
  if (!run?.alive || run.status !== "running") return null;
  const ocr = run.progress.steps.find((step) => step.key === "ocr");
  const pages =
    ocr && ocr.done > 0
      ? ` · ${formatNumber(ocr.done)}${ocr.total !== null ? ` von ${formatNumber(ocr.total)}` : ""} Seiten`
      : "";
  return (
    <Card className={styles.card} aria-label="KI-Lauf">
      <p className={styles.line}>
        <Spinner label="Läuft" />
        <span>
          <strong>{run.stop_requested ? "KI-Lauf wird angehalten …" : "KI-Lauf läuft"}</strong>
          {pages}
          {" · Ein Import kann erst danach starten. "}
          <Link to="/ki">Zur Seite „KI“</Link>
        </span>
      </p>
      {run.progress.steps.length > 0 && (
        <details className={styles.steps}>
          <summary>Schritte des KI-Laufs</summary>
          <StepList
            steps={run.progress.steps}
            alive
            age={run.report_age_seconds}
            database={run.progress.database}
            kind="ai"
          />
        </details>
      )}
    </Card>
  );
}

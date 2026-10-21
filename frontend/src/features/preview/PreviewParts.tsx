import { Button } from "../../components/Button";
import { ErrorState } from "../../components/ErrorState";
import styles from "./AttachmentPreview.module.css";
import { previewProblem } from "./errors";

/** Under a document drawn in a frame: what keeps the reader safe from it (D121, D122). */
export function IsolationNote() {
  return <p className={styles.note}>Isoliert angezeigt: ohne Skripte, ohne Netzzugriff.</p>;
}

/** A preview that could not be loaded: what happened in German, the server's reason as a muted
 *  technical line, and a retry where asking again can help. */
export function PreviewError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const problem = previewProblem(error);
  return (
    <ErrorState
      title={problem.title}
      actions={problem.retry && <Button onClick={onRetry}>Erneut versuchen</Button>}
    >
      {(problem.text || problem.reason) && (
        <>
          {problem.text}
          {problem.reason && <code className={styles.reason}>{problem.reason}</code>}
        </>
      )}
    </ErrorState>
  );
}
